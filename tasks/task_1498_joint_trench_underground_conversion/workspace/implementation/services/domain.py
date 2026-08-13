"""Domain services: logical clock, posture/freeze derivation, depth accounting,
the provisional-share and final-true-up waterfalls, withdrawal and incorporation
cascades, liquidated damages, late fees, and trench geometry/window rules.

Derived-at-read fields (never stored, always computed from stored state):
  Project.posture, Project.cumulative_delay_days, Project.liquidated_damages_cents,
  TrenchSegment.occupied_depth_inches / available_depth_inches / frozen,
  Invoice.late_fee_cents / amount_due_cents, Parcel.panel_upgrade_required.

Stored computed fields (mutated by cascades): UtilityParticipation
  .provisional_share_cents / .final_share_cents / .variance_flag,
  Project.latest_true_up_run_id.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import db
from db import touch
from errors import (
    raise_err,
    ERR_MIN_COVER_VIOLATION,
    ERR_DEPTH_CAPACITY_EXCEEDED,
    ERR_MIN_SEPARATION_VIOLATION,
    ERR_ELECTRIC_NOT_DEEPEST,
    ERR_SLOT_WINDOW_OUT_OF_RANGE,
    ERR_SLOT_WINDOW_CONFLICT,
    ERR_SLOT_ORDER_VIOLATION,
)
from util import parse_iso8601, render_dt, round_half_up_int


# ---------------------------------------------------------------------------
# Constants (SCAFFOLD calculations)
# ---------------------------------------------------------------------------

STANDARD_SEPARATION_IN = 12
REDUCED_SEPARATION_IN = 6
MIN_COVER_IN = 12
CONCURRENT_SEPARATION_IN = 24

MAX_CONCURRENT_OUTAGES = 2
MAX_OUTAGE_SECONDS = 8 * 3600
NOTIFICATION_LEAD_SECONDS = 72 * 3600

LATE_FEE_GRACE_DAYS = 30
LATE_FEE_PERIOD_DAYS = 30
STANDARD_LATE_RATE = Decimal("0.015")
ELEVATED_LATE_RATE = Decimal("0.02")
PRINCIPAL_TIER_THRESHOLD_CENTS = 10_000_000
INVOICE_DUE_DAYS = 30

LD_RATE_CENTS_PER_DAY = 50_000
LD_CAP_PCT = Decimal("0.10")
LD_CAUSE_FACTOR = {"EXCUSABLE": Decimal("0"), "NEGLIGENT": Decimal("1"), "MIXED": Decimal("0.5")}

WARRANTY_DAYS = 180

# Status sets
PROV_STATUSES = {"COMMITTED", "MOBILIZED", "INSTALLED", "BILLED", "SETTLED"}
# Slots that still claim trench geometry (separation / window / order checks)
SLOT_ACTIVE_STATUSES = {"RESERVED", "INSTALLING", "INSTALL_FAILED", "INSTALLED", "VERIFIED"}
# Slots counted in occupied_depth_inches (INSTALL_FAILED excluded per entity spec)
SLOT_DEPTH_STATUSES = {"RESERVED", "INSTALLING", "INSTALLED", "VERIFIED"}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def clock_str() -> str:
    """The logical clock as an ISO string (stamped verbatim onto entities)."""
    return db.get_clock_raw()


def clock_dt():
    return parse_iso8601(db.get_clock_raw(), "clock")


def clock_plus_days(days: int) -> str:
    return render_dt(clock_dt() + timedelta(days=days))


# ---------------------------------------------------------------------------
# Project lookups
# ---------------------------------------------------------------------------

def project_participations(project_id: str) -> list[dict]:
    return [p for p in db.participations.values() if p["project_id"] == project_id]


def project_segments(project_id: str) -> list[dict]:
    return [s for s in db.segments.values() if s["project_id"] == project_id]


def project_parcels(project_id: str) -> list[dict]:
    return [p for p in db.parcels.values() if p["project_id"] == project_id]


def project_change_orders(project_id: str) -> list[dict]:
    return [c for c in db.change_orders.values() if c["project_id"] == project_id]


def project_cost_entries(project_id: str) -> list[dict]:
    return [e for e in db.cost_entries.values() if e["project_id"] == project_id]


def project_trueup_runs(project_id: str) -> list[dict]:
    return [r for r in db.trueup_runs.values() if r["project_id"] == project_id]


def pinned_order(parts: list[dict]) -> list[dict]:
    """Ascending sequence_order, ties by ascending created_at (then _seq)."""
    return sorted(parts, key=lambda p: (p["sequence_order"], p["created_at"], p.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Posture and freeze derivation (calculation project_posture)
# ---------------------------------------------------------------------------

def compute_posture(project: dict) -> str:
    pid = project["id"]
    if any(c["status"] == "APPROVED" for c in project_change_orders(pid)):
        return "FROZEN"
    parcel_ids = {p["id"] for p in project_parcels(pid)}
    for e in db.easements.values():
        if (e["parcel_id"] in parcel_ids and e["easement_type"] == "TRENCH"
                and e["status"] == "REFUSED"):
            return "CONDITIONAL"
    for p in project_participations(pid):
        if p.get("variance_flag"):
            return "CONDITIONAL"
    return "CLEAR"


def is_segment_frozen(segment: dict) -> bool:
    for co in project_change_orders(segment["project_id"]):
        if co["status"] == "APPROVED":
            seg_ids = co.get("segment_ids") or []
            if not seg_ids or segment["id"] in seg_ids:
                return True
    return False


# ---------------------------------------------------------------------------
# Segment depth accounting (derived)
# ---------------------------------------------------------------------------

def segment_slots(segment_id: str) -> list[dict]:
    return [s for s in db.slots.values() if s["trench_segment_id"] == segment_id]


def occupied_depth(segment: dict) -> int:
    depths = [s["depth_bottom_inches"] for s in segment_slots(segment["id"])
              if s["status"] in SLOT_DEPTH_STATUSES]
    return max(depths) if depths else 0


# ---------------------------------------------------------------------------
# Permit lazy expiry (state machine Permit, system transition)
# ---------------------------------------------------------------------------

def refresh_permit(permit: dict) -> None:
    """Lazily flip ISSUED -> EXPIRED when the clock has passed valid_to."""
    if permit["status"] == "ISSUED" and clock_dt() > parse_iso8601(permit["valid_to"]):
        permit["status"] = "EXPIRED"
        touch(permit)


def sweep_permits() -> None:
    for permit in db.permits.values():
        refresh_permit(permit)


# ---------------------------------------------------------------------------
# Waterfall allocation (calculations provisional_cost_share / final gross step)
# ---------------------------------------------------------------------------

def waterfall_shares(total_cents: int, parts: list[dict]) -> dict[str, int]:
    """Split total_cents across parts by cost_share_bp with the pinned order:
    per-participant round-half-up first, then the remainder is distributed one
    cent at a time in ascending sequence_order (ties: created_at)."""
    parts = pinned_order(parts)
    if not parts:
        return {}
    shares = {}
    for p in parts:
        raw = Decimal(total_cents) * Decimal(p["cost_share_bp"]) / Decimal(10000)
        shares[p["id"]] = round_half_up_int(raw)
    remainder = total_cents - sum(shares.values())
    step = 1 if remainder > 0 else -1
    for i in range(abs(remainder)):
        if not parts:
            break
        shares[parts[i % len(parts)]["id"]] += step
    return shares


def recompute_provisional(project: dict) -> None:
    """Recompute provisional_share_cents + variance_flag for every non-withdrawn
    (status COMMITTED|MOBILIZED|INSTALLED|BILLED|SETTLED) participation."""
    parts = [p for p in project_participations(project["id"]) if p["status"] in PROV_STATUSES]
    shares = waterfall_shares(project["estimated_total_cost_cents"], parts)
    for p in pinned_order(parts):
        new = shares[p["id"]]
        old = p["provisional_share_cents"]
        had_previous = p.get("_prov_exists", False)
        flag = had_previous and (abs(new - old) * 100 >= 10 * old)
        if new != old or flag != p["variance_flag"]:
            p["provisional_share_cents"] = new
            p["variance_flag"] = flag
            touch(p)
        p["_prov_exists"] = True


# ---------------------------------------------------------------------------
# Withdrawal cascade (UtilityParticipation state machine notes)
# ---------------------------------------------------------------------------

def withdrawal_cascade(participation: dict, project: dict) -> None:
    # (1) this participation -> WITHDRAWN, withdrawn_on = clock, share -> 0
    # (2) its slots in RESERVED|INSTALLING|INSTALL_FAILED -> RELEASED
    for s in db.slots.values():
        if (s["participation_id"] == participation["id"]
                and s["status"] in {"RESERVED", "INSTALLING", "INSTALL_FAILED"}):
            s["status"] = "RELEASED"
            touch(s)
    participation["status"] = "WITHDRAWN"
    participation["withdrawn_on"] = clock_str()
    participation["provisional_share_cents"] = 0
    touch(participation)
    # (3) segment depth figures are derived at read; nothing to store.
    # (4) rescale cost_share_bp of remaining non-withdrawn participations to 10000
    remaining = [p for p in project_participations(project["id"])
                 if p["status"] != "WITHDRAWN"]
    if remaining:
        bp_sum = sum(p["cost_share_bp"] for p in remaining)
        ordered = pinned_order(remaining)
        new_bp = {}
        for p in ordered:
            new_bp[p["id"]] = round_half_up_int(
                Decimal(p["cost_share_bp"]) * Decimal(10000) / Decimal(bp_sum))
        drift = 10000 - sum(new_bp.values())
        if drift != 0:
            # fix rounding drift on the participant with lowest sequence_order
            target = ordered[0]
            new_bp[target["id"]] += drift
        for p in ordered:
            if p["cost_share_bp"] != new_bp[p["id"]]:
                p["cost_share_bp"] = new_bp[p["id"]]
                touch(p)
    # (5) provisional shares recomputed; (6) variance flags updated
    recompute_provisional(project)
    # posture is derived at read.


# ---------------------------------------------------------------------------
# Change-order incorporation cascade
# ---------------------------------------------------------------------------

def incorporation_cascade(project: dict, change_order: dict) -> None:
    project["estimated_total_cost_cents"] += change_order["delta_cost_cents"]
    touch(project)
    recompute_provisional(project)
    # unfreeze + posture + LD are derived at read.


def compute_cumulative_delay_days(project: dict) -> int:
    return sum(
        c["delta_delay_days"] or 0
        for c in project_change_orders(project["id"])
        if c["status"] == "INCORPORATED"
    )


def compute_liquidated_damages(project: dict) -> int:
    weighted = Decimal(0)
    for c in project_change_orders(project["id"]):
        if c["status"] == "INCORPORATED":
            weighted += Decimal(c["delta_delay_days"] or 0) * LD_CAUSE_FACTOR[c["delay_cause"]]
    billable = weighted - Decimal(project.get("contingency_days", 0))
    if billable < 0:
        billable = Decimal(0)
    raw = billable * Decimal(LD_RATE_CENTS_PER_DAY)
    cap = Decimal(round_half_up_int(
        Decimal(project["estimated_total_cost_cents"]) * LD_CAP_PCT))
    return int(min(cap, raw))


# ---------------------------------------------------------------------------
# Final true-up allocation (calculation final_trueup_allocation)
# ---------------------------------------------------------------------------

JOINT_COST_CODES = {"JOINT_TRENCH", "RESTORATION", "PROGRAM_OVERHEAD"}


def compute_trueup_lines(project: dict) -> tuple[list[dict], int, int]:
    """Returns (lines, total_actual_cost_cents, rule20_credit_applied_cents)."""
    entries = project_cost_entries(project["id"])
    joint_pool = sum(e["amount_cents"] for e in entries if e["cost_code"] in JOINT_COST_CODES)
    parts = [p for p in project_participations(project["id"]) if p["status"] in PROV_STATUSES]
    parts = pinned_order(parts)
    exclusive = {p["id"]: 0 for p in parts}
    for e in entries:
        if e["cost_code"] == "EXCLUSIVE" and e.get("participation_id") in exclusive:
            exclusive[e["participation_id"]] += e["amount_cents"]
    total_actual = joint_pool + sum(exclusive.values())

    gross = waterfall_shares(joint_pool, parts)

    # Rule 20 credit waterfall in the pinned order
    remaining = project["rule20_credit_cents"]
    credit = {}
    for p in parts:
        c = min(remaining, gross[p["id"]])
        credit[p["id"]] = c
        remaining -= c
    credit_applied = project["rule20_credit_cents"] - remaining

    lines = []
    for p in parts:
        g = gross[p["id"]]
        final = g - credit[p["id"]] + exclusive[p["id"]]
        delta = final - p["provisional_share_cents"]
        lines.append({
            "participation_id": p["id"],
            "gross_share_cents": g,
            "credit_cents": credit[p["id"]],
            "exclusive_cents": exclusive[p["id"]],
            "final_share_cents": final,
            "delta_cents": delta,
            "refund_cents": max(0, -delta),
        })
    return lines, total_actual, credit_applied


# ---------------------------------------------------------------------------
# Invoice late fees (calculation late_fee_accrual)
# ---------------------------------------------------------------------------

def invoice_late_fee(invoice: dict) -> int:
    """Late fee evaluated at read time against the logical clock. PAID invoices
    freeze the evaluation at paid_on; VOID invoices carry no fee."""
    if invoice["status"] == "VOID":
        return 0
    if invoice["status"] == "PAID" and invoice.get("paid_on"):
        ref = parse_iso8601(invoice["paid_on"])
    else:
        ref = clock_dt()
    due = parse_iso8601(invoice["due_on"])
    days_overdue = int((ref - due).total_seconds() // 86400)
    if days_overdue < LATE_FEE_GRACE_DAYS:
        return 0
    periods = days_overdue // LATE_FEE_PERIOD_DAYS
    principal = invoice["principal_cents"]
    rate = (ELEVATED_LATE_RATE if principal >= PRINCIPAL_TIER_THRESHOLD_CENTS
            else STANDARD_LATE_RATE)
    return round_half_up_int(Decimal(principal) * rate * Decimal(periods))


# ---------------------------------------------------------------------------
# Trench geometry and window rules (calculations depth_separation_requirement
# and occupancy_window_conflict)
# ---------------------------------------------------------------------------

def vertical_gap(a_top: int, a_bottom: int, b_top: int, b_bottom: int) -> int:
    """Vertical gap between two bands; overlapping bands count as gap 0."""
    if a_top < b_bottom and b_top < a_bottom:
        return 0
    return abs(max(a_top, b_top) - min(a_bottom, b_bottom))


def _pair_required_separation(p_a: dict, p_b: dict) -> int:
    if (p_a["utility_type"] != "ELECTRIC" and p_b["utility_type"] != "ELECTRIC"
            and p_a.get("has_separation_waiver") and p_b.get("has_separation_waiver")):
        return REDUCED_SEPARATION_IN
    return STANDARD_SEPARATION_IN


def check_slot_geometry(segment: dict, participation: dict,
                        depth_top: int, depth_bottom: int) -> None:
    """Min cover -> band capacity -> pairwise separation -> electric-deepest."""
    if depth_top < MIN_COVER_IN:
        raise_err(ERR_MIN_COVER_VIOLATION,
                  f"depth_top_inches {depth_top} below minimum cover {MIN_COVER_IN}")
    if depth_bottom > segment["max_depth_inches"]:
        raise_err(ERR_DEPTH_CAPACITY_EXCEEDED,
                  f"depth_bottom_inches {depth_bottom} exceeds segment max "
                  f"{segment['max_depth_inches']}")
    existing = [s for s in segment_slots(segment["id"])
                if s["status"] in SLOT_ACTIVE_STATUSES]
    for e in existing:
        other = db.participations.get(e["participation_id"])
        if other is None:
            continue
        gap = vertical_gap(depth_top, depth_bottom,
                           e["depth_top_inches"], e["depth_bottom_inches"])
        required = _pair_required_separation(participation, other)
        if gap < required:
            raise_err(ERR_MIN_SEPARATION_VIOLATION,
                      f"vertical gap {gap} below required separation {required}")
    # Electric-deepest rule
    electric_tops = []
    non_electric_bottoms = []
    for e in existing:
        other = db.participations.get(e["participation_id"])
        if other is None:
            continue
        if other["utility_type"] == "ELECTRIC":
            electric_tops.append(e["depth_top_inches"])
        else:
            non_electric_bottoms.append(e["depth_bottom_inches"])
    if participation["utility_type"] == "ELECTRIC":
        electric_tops.append(depth_top)
    else:
        non_electric_bottoms.append(depth_bottom)
    if electric_tops:
        min_elec_top = min(electric_tops)
        for bottom in non_electric_bottoms:
            if bottom > min_elec_top - STANDARD_SEPARATION_IN:
                raise_err(ERR_ELECTRIC_NOT_DEEPEST,
                          "non-electric band must sit at least 12in above the "
                          "shallowest electric band")


def check_slot_window(segment: dict, depth_top: int, depth_bottom: int,
                      install_start: str, install_end: str) -> None:
    """Window must lie within the excavation window (inclusive), and slots closer
    than CONCURRENT_SEPARATION_IN must run disjoint, deeper-first."""
    start_dt = parse_iso8601(install_start)
    end_dt = parse_iso8601(install_end)
    exc_start = parse_iso8601(segment["excavation_start_on"])
    exc_end = parse_iso8601(segment["excavation_end_on"])
    if start_dt < exc_start or end_dt > exc_end:
        raise_err(ERR_SLOT_WINDOW_OUT_OF_RANGE,
                  "install window outside the segment excavation window")
    for e in segment_slots(segment["id"]):
        if e["status"] not in SLOT_ACTIVE_STATUSES:
            continue
        gap = vertical_gap(depth_top, depth_bottom,
                           e["depth_top_inches"], e["depth_bottom_inches"])
        if gap >= CONCURRENT_SEPARATION_IN:
            continue
        e_start = parse_iso8601(e["install_start_at"])
        e_end = parse_iso8601(e["install_end_at"])
        # Deeper-first: the shallower slot's window must not start before the
        # deeper slot's window ends (half-open; adjacency allowed). This also
        # enforces disjointness.
        if depth_top > e["depth_top_inches"]:
            # candidate is the deeper slot; the existing (shallower) window
            # must not start before the candidate's window ends.
            if e_start < end_dt:
                raise_err(ERR_SLOT_WINDOW_CONFLICT,
                          "shallower slot window may not start before the "
                          "deeper slot's window ends")
        else:
            # candidate is the shallower slot
            if start_dt < e_end:
                raise_err(ERR_SLOT_WINDOW_CONFLICT,
                          "shallower slot window may not start before the deeper "
                          "slot's window ends")


def check_deeper_first(segment: dict, slot: dict) -> None:
    """Every deeper slot on the segment must be INSTALLED|VERIFIED before this
    slot may move to INSTALLING (released slots no longer participate)."""
    for e in segment_slots(segment["id"]):
        if e["id"] == slot["id"]:
            continue
        if e["status"] not in SLOT_ACTIVE_STATUSES:
            continue
        if e["depth_top_inches"] > slot["depth_top_inches"]:
            if e["status"] not in {"INSTALLED", "VERIFIED"}:
                raise_err(ERR_SLOT_ORDER_VIOLATION,
                          "a deeper slot on the segment is not yet INSTALLED|VERIFIED")
