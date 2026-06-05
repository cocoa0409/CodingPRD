"""Calculation rules (scaffold §1.3, PRD §3.5/§3.6)."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db
from common import touch

# Constants. PRD §3.2 is authoritative: one-person poverty line of 15,080,000
# cents plus 5,320,000 cents per additional household member. (The scaffold's
# §1.3 values 1508000/532000 are off by 10x; PRD prose wins per the build spec.)
FPL_BASE_CENTS = 15080000
FPL_PER_PERSON_CENTS = 5320000
SIBLING_DISCOUNT_PCT = 10
WAITLIST_OFFER_TTL_HOURS = 48

CACFP_RATES = {
    "TIER_I": {"breakfast": 240, "lunch": 449, "snack": 119},
    "TIER_II": {"breakfast": 90, "lunch": 271, "snack": 33},
}

SLIDING_TIERS = {"TIER_A", "TIER_B", "TIER_C", "FULL_PAY"}


def round_half_up(numerator: int, denominator: int) -> int:
    """round_half_up(numerator/denominator) to nearest integer cent."""
    return int((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Sliding scale tier selection
# ---------------------------------------------------------------------------
def compute_sliding_scale_tier(family: dict) -> str:
    income = family["annual_household_income_cents"]
    size = family["household_size"]
    fpl_base = FPL_BASE_CENTS + (size - 1) * FPL_PER_PERSON_CENTS
    # floor on the ratio division
    fpl_ratio_pct = (income * 100) // fpl_base

    rows = [r for r in db.sliding_scale.values() if r["center_id"] == family["center_id"]]
    # sort by max_fpl_ratio_pct ASC, tie-break created_at (seq) ASC
    rows.sort(key=lambda r: (r["max_fpl_ratio_pct"], r["_seq"]))
    for r in rows:
        if r["max_fpl_ratio_pct"] >= fpl_ratio_pct:
            return r["tier"]
    # no row qualifies; FULL_PAY sentinel row should always catch. If none, default FULL_PAY.
    return "FULL_PAY"


def parent_share_for_tier(center_id: str, tier: str) -> int:
    rows = [r for r in db.sliding_scale.values()
            if r["center_id"] == center_id and r["tier"] == tier]
    rows.sort(key=lambda r: r["_seq"])
    if rows:
        return rows[0]["parent_share_pct"]
    return 100


# ---------------------------------------------------------------------------
# Monthly net tuition (pinned: sliding scale first, then sibling discount)
# ---------------------------------------------------------------------------
def compute_monthly_net_tuition(locked_base: int, parent_share_pct: int,
                                sibling_discount_pct: int) -> int:
    after_sliding = round_half_up(locked_base * parent_share_pct, 100)
    net = round_half_up(after_sliding * (100 - sibling_discount_pct), 100)
    return net


# ---------------------------------------------------------------------------
# Sibling-discount cascade across a family's ACTIVE enrollments
# ---------------------------------------------------------------------------
def family_of_enrollment(enr: dict):
    child = db.children.get(enr["child_id"])
    if child is None:
        return None
    return db.families.get(child["family_id"])


def recompute_sibling_cascade(family_id: str) -> None:
    """Re-rank family's ACTIVE enrollments by created_at ASC; anchor=0%, juniors=10%.
    Recompute monthly_net_tuition_cents for each affected enrollment."""
    # gather ACTIVE enrollments whose child belongs to this family
    active = []
    for enr in db.enrollments.values():
        if enr["status"] != "ACTIVE":
            continue
        child = db.children.get(enr["child_id"])
        if child is None or child["family_id"] != family_id:
            continue
        active.append(enr)
    active.sort(key=lambda e: e["_seq"])  # enrollment created_at ASC
    for idx, enr in enumerate(active):
        new_disc = 0 if idx == 0 else SIBLING_DISCOUNT_PCT
        new_net = compute_monthly_net_tuition(
            enr["locked_base_tuition_cents"], enr["locked_parent_share_pct"], new_disc)
        if enr.get("sibling_discount_pct") != new_disc or \
                enr.get("monthly_net_tuition_cents") != new_net:
            enr["sibling_discount_pct"] = new_disc
            enr["monthly_net_tuition_cents"] = new_net
            touch(enr)


# ---------------------------------------------------------------------------
# Late pickup fine (scaffold §1.3)
# ---------------------------------------------------------------------------
def compute_late_fine(record: dict, center: dict) -> tuple[int, int]:
    """Returns (late_pickup_minutes, late_fine_cents). check_out_at must be set."""
    check_out = _parse_iso(record["check_out_at"])
    # scheduled pickup instant: service_date + scheduled_pickup_local, center-local => UTC.
    # Center-local timezone is unspecified; treat the wall-clock as UTC for determinism.
    sched = _parse_local_to_utc(record["service_date"], record["scheduled_pickup_local"])
    raw_late_min = max(0, int((check_out - sched).total_seconds() // 60))
    grace = center["late_pickup_grace_minutes"]
    billable = max(0, raw_late_min - grace)
    block = center["late_pickup_block_minutes"]
    if billable > 0:
        blocks = -(-billable // block)  # ceil
    else:
        blocks = 0
    fine = blocks * center["late_pickup_fee_per_block_cents"]
    return billable, fine


def compute_cacfp(record: dict, child: dict, center: dict) -> int:
    if not child.get("enrolls_in_cacfp", True):
        return 0
    rate = CACFP_RATES[center["cacfp_tier"]]
    return (record["meals_breakfast"] * rate["breakfast"]
            + record["meals_lunch"] * rate["lunch"]
            + record["meals_snack"] * rate["snack"])


# ---------------------------------------------------------------------------
# Datetime parsing
# ---------------------------------------------------------------------------
def _parse_iso(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_local_to_utc(service_date: str, local_hhmm: str) -> datetime:
    # interpret HH:MM wall-clock on service_date as UTC (center-local tz unspecified)
    hh, mm = local_hhmm.split(":")
    y, mo, d = service_date.split("-")
    return datetime(int(y), int(mo), int(d), int(hh), int(mm), tzinfo=timezone.utc)


def offer_ttl(now: datetime) -> datetime:
    return now + timedelta(hours=WAITLIST_OFFER_TTL_HOURS)
