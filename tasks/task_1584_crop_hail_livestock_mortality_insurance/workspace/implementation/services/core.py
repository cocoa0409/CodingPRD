"""Domain services: rating, premium/indemnity calculations, derived postures,
and the carrier logical-clock automatic transitions (PRD 2.5, 3.2–3.9).

Constants (SCAFFOLD 1.3):
  USD_CENTS_PER_ACRE = 40000          ($400.00 exposure per declared acre)
  reserve ratio      = 0.60           (floor at bind / on recompute)
  carryover          = 5% of prior premium when continuity gap <= 7 days
  dual offset        = 20% of federal liability, capped at remaining indemnity
  hail notice window = 72h; livestock = 24h; late tiers 10% (<=7d) / 25% (<=30d)
  necropsy threshold = 500_000 cents ($5,000), strictly greater
"""

from __future__ import annotations

from datetime import timedelta

import db
from util import dt, rhu_div, ceil_whole_days

USD_CENTS_PER_ACRE = 40_000
CARRYOVER_PCT = 5
MAX_CONTINUITY_GAP_DAYS = 7
DUAL_OFFSET_PCT = 20
NECROPSY_THRESHOLD_CENTS = 500_000
HAIL_NOTICE_WINDOW_HOURS = 72
LIVESTOCK_NOTICE_WINDOW_HOURS = 24

OPEN_CLAIM_STATES = ("REPORTED", "INSPECTION_SCHEDULED", "INSPECTED", "UNDER_REVIEW")
BLOCKING_CLAIM_STATES = ("INSPECTION_SCHEDULED", "INSPECTED", "UNDER_REVIEW", "APPROVED")
TERMINAL_LIFECYCLE = ("EXPIRED", "CANCELLED", "NON_RENEWED")

VERSION_NOTE = "OCC target — version increments on every mutation including cascaded side effects"


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------

def policies_of_carrier(carrier_id: str) -> list[dict]:
    return [p for p in db.policies.values() if p["carrier_id"] == carrier_id]


def policies_of_grower(grower_id: str) -> list[dict]:
    return [p for p in db.policies.values() if p["grower_id"] == grower_id]


def units_of_policy(policy_id: str) -> list[dict]:
    return sorted(
        (u for u in db.coverage_units.values() if u["policy_id"] == policy_id),
        key=lambda u: u["_seq"],
    )


def claims_of_policy(policy_id: str) -> list[dict]:
    return [c for c in db.claims.values() if c["policy_id"] == policy_id]


def reports_of_unit(unit_id: str, unit_kind: str) -> list[dict]:
    store = db.acreage_reports if unit_kind == "CROP_HAIL" else db.head_reports
    return sorted(
        (r for r in store.values() if r["coverage_unit_id"] == unit_id),
        key=lambda r: r["_seq"],
    )


def vet_reports_of_claim(claim_id: str) -> list[dict]:
    return sorted(
        (r for r in db.vet_reports.values() if r["claim_id"] == claim_id),
        key=lambda r: r["_seq"],
    )


def adjuster_open_claims(adjuster_id: str) -> int:
    return sum(
        1
        for c in db.claims.values()
        if c.get("adjuster_id") == adjuster_id and c["claim_state"] in OPEN_CLAIM_STATES
    )


# ---------------------------------------------------------------------------
# Derived postures (never set directly — PRD 3.4)
# ---------------------------------------------------------------------------

def derive_claims_posture(policy: dict) -> str:
    if policy["billing_state"] == "DELINQUENT":
        return "RESTRICTED"
    if policy["lifecycle_state"] in TERMINAL_LIFECYCLE:
        return "RESTRICTED"
    return "OPEN"


def reinsurance_posture(carrier: dict) -> str:
    """Aggregate APPROVED+PAID indemnities vs the treaty attachment (PRD 3.8)."""
    policy_ids = {p["id"] for p in policies_of_carrier(carrier["id"])}
    aggregate = sum(
        c["final_indemnity_cents"]
        for c in db.claims.values()
        if c["policy_id"] in policy_ids and c["claim_state"] in ("APPROVED", "PAID")
    )
    if aggregate >= carrier["reinsurance_treaty_attachment_cents"]:
        return "ATTACHED"
    return "BELOW_ATTACHMENT"


# ---------------------------------------------------------------------------
# Rating (PRD 3.2 / SCAFFOLD coverage_unit_premium)
# ---------------------------------------------------------------------------

def select_rate_row(carrier_id: str, clock_dt, rating_kind: str, *,
                    county_code=None, crop_code=None, species=None,
                    per_head_value_cents=None):
    """Latest-effective_from PUBLISHED row whose window contains clock_dt;
    remaining ties broken by earliest created_at (insertion order)."""
    matches = []
    for row in db.rate_tables.values():
        if row["carrier_id"] != carrier_id:
            continue
        if row["status"] != "PUBLISHED" or row["rating_kind"] != rating_kind:
            continue
        if dt(row["effective_from"]) > clock_dt:
            continue
        if row["effective_to"] is not None and clock_dt >= dt(row["effective_to"]):
            continue
        if rating_kind == "CROP_HAIL":
            if row["county_code"] != county_code or row["crop_code"] != crop_code:
                continue
        else:
            if row["species"] != species:
                continue
            if not (row["value_band_floor_cents"] <= per_head_value_cents
                    < row["value_band_ceiling_cents"]):
                continue
        matches.append(row)
    if not matches:
        return None
    matches.sort(key=lambda r: (-dt(r["effective_from"]).timestamp(), r["_seq"]))
    return matches[0]


def compute_unit_liability(unit: dict) -> int:
    if unit["unit_kind"] == "CROP_HAIL":
        return unit["declared_acres"] * USD_CENTS_PER_ACRE
    return unit["declared_head_count"] * unit["per_head_value_cents"]


def rate_unit(unit: dict, carrier_id: str, clock_dt):
    """(rate_row, premium_cents): premium is None when no PUBLISHED row matches."""
    if unit["unit_kind"] == "CROP_HAIL":
        row = select_rate_row(
            carrier_id, clock_dt, "CROP_HAIL",
            county_code=unit["county_code"], crop_code=unit["crop_code"],
        )
    else:
        row = select_rate_row(
            carrier_id, clock_dt, "LIVESTOCK_MORTALITY",
            species=unit["species"],
            per_head_value_cents=unit["per_head_value_cents"],
        )
    if row is None:
        return None, None
    premium = rhu_div(
        unit["liability_cents"] * row["rate_per_100_cents_of_liability"], 10_000
    )
    return row, premium


# ---------------------------------------------------------------------------
# Policy-level pricing (PRD 3.4 / SCAFFOLD policy_premium_aggregation)
# ---------------------------------------------------------------------------

def surcharge_pct_for(grower: dict) -> int:
    count = grower["prior_claims_count"]
    if count >= 4:
        return 25
    if count >= 2:
        return 10
    return 0


def carryover_credit_for(prior: dict, new_effective_dt) -> int:
    """5% of prior premium (half-up) when prior EXPIRED and gap <= 7 days."""
    if prior["lifecycle_state"] != "EXPIRED":
        return 0
    gap = continuity_gap_days(prior, new_effective_dt)
    if gap > MAX_CONTINUITY_GAP_DAYS:
        return 0
    return rhu_div(prior["premium_cents"] * CARRYOVER_PCT, 100)


def continuity_gap_days(prior: dict, new_effective_dt) -> int:
    delta = new_effective_dt - dt(prior["expiration_date"])
    if delta.total_seconds() <= 0:
        return 0
    return ceil_whole_days(delta)


def aggregate_policy_premium(policy: dict) -> int:
    """Per-unit round THEN sum THEN surcharge THEN subtract credit; floor 0."""
    subtotal = sum(u["premium_cents"] for u in units_of_policy(policy["id"]))
    multiplier_bp = 10_000 + policy["high_risk_surcharge_pct"] * 100
    after_surcharge = rhu_div(subtotal * multiplier_bp, 10_000)
    return max(0, after_surcharge - policy["continuous_coverage_carryover_credit_cents"])


def recompute_reserve(policy: dict) -> None:
    """reserve = max(0, floor(premium * 0.60) - APPROVED/PAID indemnity sum)."""
    total = sum(
        c["final_indemnity_cents"]
        for c in claims_of_policy(policy["id"])
        if c["claim_state"] in ("APPROVED", "PAID")
    )
    policy["premium_reserve_cents"] = max(0, policy["premium_cents"] * 3 // 5 - total)


# ---------------------------------------------------------------------------
# Claim intake penalty (SCAFFOLD late_notification_penalty)
# ---------------------------------------------------------------------------

def late_notice(claim_kind: str, reported_at_dt, loss_dt) -> tuple[bool, int]:
    """(reported_within_window, penalty_pct); boundaries inclusive."""
    window_hours = (
        HAIL_NOTICE_WINDOW_HOURS if claim_kind == "HAIL_DAMAGE"
        else LIVESTOCK_NOTICE_WINDOW_HOURS
    )
    delta_hours = (reported_at_dt - loss_dt).total_seconds() / 3600
    if delta_hours <= window_hours:
        return True, 0
    if delta_hours <= 7 * 24:
        return False, 10
    if delta_hours <= 30 * 24:
        return False, 25
    return False, 100  # unreachable: intake rejects notice beyond 30 days


# ---------------------------------------------------------------------------
# Report lateness (SCAFFOLD acreage_report_lateness)
# ---------------------------------------------------------------------------

def latest_coverage_reduction_pct(unit: dict) -> int:
    """Reduction recorded on the latest late report; 0 when all timely."""
    reduction = 0
    for report in reports_of_unit(unit["id"], unit["unit_kind"]):
        if report["coverage_reduction_pct"] > 0:
            reduction = report["coverage_reduction_pct"]
    return reduction


# ---------------------------------------------------------------------------
# Provisional indemnity (SCAFFOLD provisional_indemnity; PRD 3.7)
# ---------------------------------------------------------------------------

def compute_provisional_indemnity(claim: dict, unit: dict,
                                  observed: dict) -> int:
    """No intermediate truncation; round half up at the final step only."""
    reduction = latest_coverage_reduction_pct(unit)
    penalty = claim["late_notification_penalty_pct"]
    if claim["claim_kind"] == "HAIL_DAMAGE":
        numerator = (
            unit["liability_cents"]
            * (100 - reduction)
            * observed["observed_percent_damage_pct"]
            * (100 - penalty)
        )
        return rhu_div(numerator, 1_000_000)
    # Livestock appraisal method
    basis = min(observed["observed_appraisal_cents"], claim["appraisal_value_cents"])
    cap = None
    row = db.rate_tables.get(unit.get("_rate_table_id") or "")
    if row is not None and row.get("value_band_ceiling_cents") is not None:
        cap = row["value_band_ceiling_cents"] * observed["observed_deceased_count"]
    capped = basis if cap is None else min(basis, cap)
    numerator = capped * (100 - reduction) * (100 - penalty)
    return rhu_div(numerator, 10_000)


# ---------------------------------------------------------------------------
# Final indemnity waterfall (SCAFFOLD final_indemnity; PRD 3.8)
# ---------------------------------------------------------------------------

def dual_coverage_offset(policy: dict, claim: dict, unit: dict,
                         remaining_cents: int) -> int:
    """20% of federal liability, capped at the remaining indemnity. Applies
    only when the policy is linked and the federal policy was ACTIVE on the
    loss date with overlapping crop/county (PRD 3.3 / 3.8)."""
    link_id = policy.get("dual_coverage_link_id")
    if not link_id:
        return 0
    link = db.dual_links.get(link_id)
    if link is None:
        return 0
    fed = db.federal_policies.get(link["federal_crop_policy_id"])
    if fed is None or fed["status"] == "CANCELLED":
        return 0
    loss_dt = dt(claim["loss_date"])
    if not (dt(fed["effective_date"]) <= loss_dt < dt(fed["expiration_date"])):
        return 0
    if unit["unit_kind"] != "CROP_HAIL":
        return 0
    if unit["crop_code"] != fed["crop_code"] or unit["county_code"] != fed["county_code"]:
        return 0
    raw_offset = fed["liability_cents"] * DUAL_OFFSET_PCT // 100
    return min(remaining_cents, raw_offset)


def final_indemnity_waterfall(policy: dict, claim: dict, unit: dict,
                              base_cents: int) -> tuple[int, int, int, int]:
    """Each intermediate step truncates to whole cents before the next runs.
    Returns (coverage_reduction_pct, late_penalty_pct, offset_cents, final)."""
    coverage_pct = latest_coverage_reduction_pct(unit)
    late_pct = claim["late_notification_penalty_pct"]
    after_coverage = base_cents * (100 - coverage_pct) // 100
    after_late = after_coverage * (100 - late_pct) // 100
    offset = dual_coverage_offset(policy, claim, unit, after_late)
    final = max(0, after_late - offset)
    return coverage_pct, late_pct, offset, final


# ---------------------------------------------------------------------------
# Livestock documentation posture (PRD 3.7)
# ---------------------------------------------------------------------------

def recompute_doc_posture(claim: dict, now: str) -> None:
    if claim["claim_kind"] != "LIVESTOCK_MORTALITY":
        return
    reports = vet_reports_of_claim(claim["id"])
    has_certificate = any(r["report_kind"] == "VETERINARY_CERTIFICATE" for r in reports)
    needs_necropsy = claim["appraisal_value_cents"] > NECROPSY_THRESHOLD_CENTS
    has_necropsy = any(
        r["report_kind"] == "NECROPSY_REPORT" and r["necropsy_performed"]
        for r in reports
    )
    complete = has_certificate and (not needs_necropsy or has_necropsy)
    new_posture = "DOCS_COMPLETE" if complete else "DOCS_PENDING"
    if claim["doc_posture"] != new_posture:
        claim["doc_posture"] = new_posture
        db.touch(claim, now)


# ---------------------------------------------------------------------------
# Carrier logical clock: automatic transitions (PRD 2.5)
# ---------------------------------------------------------------------------

def _policy_clock_events(policy: dict, now_dt, now: str) -> None:
    """Fire due lifecycle/billing transitions in chronological trigger order."""
    while True:
        events = []
        if (
            policy["lifecycle_state"] == "BOUND"
            and policy["billing_state"] in ("BILLED", "PARTIALLY_PAID", "PAID_IN_FULL")
            and now_dt >= dt(policy["effective_date"])
        ):
            events.append((dt(policy["effective_date"]), 0, "activate"))
        if (
            policy["billing_state"] in ("BILLED", "PARTIALLY_PAID")
            and policy.get("_bound_at") is not None
            and policy["premium_paid_cents"] < policy["premium_cents"]
        ):
            threshold = dt(policy["_bound_at"]) + timedelta(days=30)
            if now_dt > threshold:
                events.append((threshold, 1, "delinquent"))
        if policy["lifecycle_state"] == "ACTIVE" and now_dt >= dt(policy["expiration_date"]):
            events.append((dt(policy["expiration_date"]), 2, "expire"))
        if not events:
            return
        events.sort(key=lambda e: (e[0], e[1]))
        kind = events[0][2]
        if kind == "activate":
            policy["lifecycle_state"] = "ACTIVE"
            db.touch(policy, now)
        elif kind == "delinquent":
            policy["billing_state"] = "DELINQUENT"
            db.touch(policy, now)
            grower = db.growers.get(policy["grower_id"])
            if grower is not None and grower["status"] == "ACTIVE":
                grower["status"] = "SUSPENDED"
                db.touch(grower, now)
        else:  # expire
            policy["lifecycle_state"] = "EXPIRED"
            db.touch(policy, now)
            for unit in units_of_policy(policy["id"]):
                if unit["status"] == "PENDING_REPORT":
                    unit["status"] = "LAPSED_REPORT"
                    db.touch(unit, now)


def run_clock_transitions(carrier: dict) -> None:
    """Evaluate every automatic transition against the carrier's new clock."""
    now = carrier["current_utc"]
    now_dt = dt(now)
    carrier_id = carrier["id"]

    for policy in sorted(policies_of_carrier(carrier_id), key=lambda p: p["_seq"]):
        _policy_clock_events(policy, now_dt, now)

    # Units whose first-report deadline passes with no report lapse.
    for unit in sorted(db.coverage_units.values(), key=lambda u: u["_seq"]):
        if unit["status"] != "PENDING_REPORT":
            continue
        policy = db.policies.get(unit["policy_id"])
        if policy is None or policy["carrier_id"] != carrier_id:
            continue
        if unit["unit_kind"] == "CROP_HAIL":
            deadline = policy["acreage_report_deadline"]
        else:
            deadline = policy["head_report_deadline"]
        if deadline is not None and now_dt > dt(deadline):
            unit["status"] = "LAPSED_REPORT"
            db.touch(unit, now)

    # Claims still REPORTED thirty days after the loss close as untimely.
    for claim in sorted(db.claims.values(), key=lambda c: c["_seq"]):
        policy = db.policies.get(claim["policy_id"])
        if policy is None or policy["carrier_id"] != carrier_id:
            continue
        if claim["claim_state"] != "REPORTED":
            continue
        if now_dt > dt(claim["loss_date"]) + timedelta(days=30):
            claim["claim_state"] = "CLOSED_UNTIMELY"
            db.touch(claim, now)
            unit = db.coverage_units.get(claim["coverage_unit_id"])
            if unit is not None and unit["status"] == "UNDER_CLAIM":
                unit["status"] = "REPORTED"
                db.touch(unit, now)

    # Federal crop policies expire at their expiration date.
    for fed in sorted(db.federal_policies.values(), key=lambda f: f["_seq"]):
        if fed["carrier_id"] != carrier_id:
            continue
        if fed["status"] == "ACTIVE" and now_dt >= dt(fed["expiration_date"]):
            fed["status"] = "EXPIRED"
            db.touch(fed, now)


def settle_unit_for_decision(claim: dict, now: str) -> None:
    unit = db.coverage_units.get(claim["coverage_unit_id"])
    if unit is not None and unit["status"] == "UNDER_CLAIM":
        unit["status"] = "SETTLED"
        db.touch(unit, now)


def release_unit(claim: dict, now: str) -> None:
    unit = db.coverage_units.get(claim["coverage_unit_id"])
    if unit is not None and unit["status"] == "UNDER_CLAIM":
        unit["status"] = "REPORTED"
        db.touch(unit, now)
