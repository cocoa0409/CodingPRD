"""Derived fields, cascades, calculations, and the clock sweep.

Every computed value follows SCAFFOLD.yaml §1.3 and PRD §2/§3 exactly.
"""
from decimal import Decimal

import db
import utils

LEVELS = {"PERMITTED", "DISCRETIONARY", "PROHIBITED"}
CURE_DAYS = {"MINOR": 90, "MATERIAL": 30, "IRREPARABLE": 7}
OPEN_VIOLATION_STATES = {"OPEN", "NOTICE_SENT", "CURE_IN_PROGRESS", "ESCALATED"}
ACTIVE_ENFORCEMENT_STATES = {"PROPOSED", "EXECUTED", "BREACHED"}
IN_FLIGHT_AMENDMENT_STATES = {"SUBMITTED", "STAFF_REVIEW", "REVISION_REQUESTED", "BOARD_REVIEW"}
ACTIVE_USE_AUTH_STATES = {"REQUESTED", "APPROVED", "APPROVED_WITH_CONDITIONS"}
BOARD_THRESHOLD = 70


def bump(record):
    """Every mutation advances version by exactly one and refreshes updated_at."""
    record["version"] += 1
    record["updated_at"] = utils.now_iso()


# ---------------------------------------------------------------- easement derived
def next_monitoring_due_on(e):
    if e["status"] == "DRAFT":
        return None
    base = e["last_monitoring_completed_on"] or e["recorded_on"]
    return utils.add_months(base, e["monitoring_interval_months"])


def open_violation_count(easement_id):
    return sum(
        1
        for v in db.violations.values()
        if v["easement_id"] == easement_id and v["status"] in OPEN_VIOLATION_STATES
    )


def amendment_count(easement_id):
    return sum(
        1
        for a in db.amendment_requests.values()
        if a["easement_id"] == easement_id and a["status"] == "APPROVED"
    )


def posture(e, on_date=None):
    """PRD §2.5 precedence: ENFORCEMENT_ACTIVE > VIOLATION_OPEN > MONITORING_DUE > GOOD_STANDING."""
    on_date = on_date if on_date is not None else utils.today()
    eid = e["id"]
    for a in db.enforcement_actions.values():
        if a["easement_id"] == eid and a["status"] in ACTIVE_ENFORCEMENT_STATES:
            return "ENFORCEMENT_ACTIVE"
    for v in db.violations.values():
        if v["easement_id"] == eid and v["status"] in OPEN_VIOLATION_STATES:
            return "VIOLATION_OPEN"
    due = next_monitoring_due_on(e)
    if due is not None and on_date > due:
        return "MONITORING_DUE"
    return "GOOD_STANDING"


# ---------------------------------------------------------------- fund derived
def policy_amount_for(prior_close_mv_cents, spending_rate_bps):
    """round(prior_close * bps / 10000, 0) half-up."""
    return int(
        (Decimal(prior_close_mv_cents) * Decimal(spending_rate_bps) / Decimal(10000)).quantize(
            Decimal("1"), rounding="ROUND_HALF_UP"
        )
    )


def provisional_draws_ytd(f):
    return sum(
        abs(t["amount_cents"])
        for t in db.endowment_transactions.values()
        if t["fund_id"] == f["id"] and t["txn_type"] == "DRAW" and t["fiscal_year"] == f["fiscal_year"]
    )


def policy_draw_allowance(f):
    return policy_amount_for(f["prior_year_close_mv_cents"], f["spending_rate_bps"]) + f[
        "carryover_allowance_cents"
    ]


# ---------------------------------------------------------------- calculations
def required_photo_points(parcel_acreage):
    return max(4, -(-parcel_acreage // 100))


def materiality(parcel_acreage, matrix, requested_changes, affected_acreage):
    """SCAFFOLD calculations.amendment_materiality_score (pinned)."""
    acreage_pts = utils.round_half_up_int(affected_acreage * 50, parcel_acreage)
    change_pts = 10 * len(requested_changes)
    levels = [(ch["use_type"], ch["new_level"]) for ch in requested_changes]
    downgrade_pts = 0
    if any(matrix.get(u) == "PROHIBITED" and n == "PERMITTED" for u, n in levels):
        downgrade_pts = 30
    elif any(matrix.get(u) == "DISCRETIONARY" and n == "PERMITTED" for u, n in levels):
        downgrade_pts = 15
    score = min(100, acreage_pts + change_pts + downgrade_pts)
    return score, ("BOARD" if score >= BOARD_THRESHOLD else "STAFF")


def post_ledger(fund, txn_type, amount_cents, purpose=None, buckets=None):
    """Pinned unitization (SCAFFOLD calculations.unit_value_unitization, mode b).

    Steps: 1) units_delta = round(|amount| / unit_value, 4) half-up;
    2) apply aggregates; 3) unit_value = round(MV / units, 4) (skip if units == 0).
    """
    units_delta = Decimal("0.0000")
    if txn_type in ("CONTRIBUTION", "DRAW"):
        units_delta = utils.round4(abs(amount_cents), fund["_unit_value_cents"])
    if txn_type == "CONTRIBUTION":
        fund["units_outstanding"] = utils.q4(fund["units_outstanding"] + units_delta)
        fund["market_value_cents"] += amount_cents
    elif txn_type == "DRAW":
        fund["units_outstanding"] = utils.q4(fund["units_outstanding"] - units_delta)
        fund["market_value_cents"] -= abs(amount_cents)
    else:  # INVESTMENT_RETURN
        fund["market_value_cents"] += amount_cents
    if fund["units_outstanding"] != 0:
        fund["_unit_value_cents"] = utils.round4(
            fund["market_value_cents"], fund["units_outstanding"]
        )
    txn = {
        "id": utils.new_id(),
        "created_at": utils.now_iso(),
        "fund_id": fund["id"],
        "txn_type": txn_type,
        "amount_cents": amount_cents,
        # PRD §3.9: the ledger records the computed (absolute-based) units
        # delta; the sign lives only on amount_cents, and the DRAW subtraction
        # happens at the aggregates above.
        "units": (units_delta if txn_type in ("CONTRIBUTION", "DRAW") else Decimal("0.0000")),
        "purpose": purpose,
        "from_policy_allowance_cents": buckets[0] if buckets else None,
        "from_excess_cents": buckets[1] if buckets else None,
        "from_principal_invasion_cents": buckets[2] if buckets else None,
        "fiscal_year": fund["fiscal_year"],
        "posted_on": utils.today_str(),
    }
    db.endowment_transactions[txn["id"]] = txn
    return txn


def escalate_violation(v, escalated_by):
    """Three-link escalation cascade (PRD §3.3)."""
    v["status"] = "ESCALATED"
    v["escalated_by"] = escalated_by
    bump(v)
    action = {
        "id": utils.new_id(),
        "created_at": utils.now_iso(),
        "updated_at": utils.now_iso(),
        "version": 1,
        "violation_id": v["id"],
        "easement_id": v["easement_id"],
        "agreement_terms": None,
        "remediation_cost_cents": None,
        "executed_by_user_id": None,
        "completed_by_user_id": None,
        "breach_notes": None,
        "status": "PROPOSED",
    }
    db.enforcement_actions[action["id"]] = action
    easement = db.easements[v["easement_id"]]
    bump(easement)  # posture flips to ENFORCEMENT_ACTIVE
    return action


def run_sweep(old_clock, new_clock):
    """POST /_clock/set_current_utc side effects (PRD §2.10)."""
    new_date = new_clock.date()
    old_date = old_clock.date()
    escalated_easements = set()
    # 1) overdue violations escalate (NOTICE_SENT / CURE_IN_PROGRESS)
    for v in sorted(db.violations.values(), key=lambda r: r["created_at"]):
        if v["status"] in ("NOTICE_SENT", "CURE_IN_PROGRESS") and v["cure_deadline_on"] is not None:
            if new_date > v["cure_deadline_on"]:
                escalate_violation(v, "CLOCK_SWEEP")
                escalated_easements.add(v["easement_id"])
    # 2) unacknowledged succession notices expire
    for n in sorted(db.succession_notices.values(), key=lambda r: r["created_at"]):
        if n["status"] == "NOTICE_GIVEN" and new_date > n["ack_deadline_on"]:
            n["status"] = "EXPIRED"
            bump(n)
    # 3) monitoring posture recompute per easement; mutate only on actual flip
    for e in db.easements.values():
        if e["id"] in escalated_easements:
            continue  # already bumped by its escalation this sweep
        before = posture(e, on_date=old_date)
        after = posture(e, on_date=new_date)
        if before != after:
            bump(e)


# ---------------------------------------------------------------- serializers
def easement_json(e):
    return {
        "id": e["id"],
        "easement_name": e["easement_name"],
        "grantor_name": e["grantor_name"],
        "parcel_acreage": e["parcel_acreage"],
        "permitted_use_matrix": dict(e["permitted_use_matrix"]),
        "monitoring_interval_months": e["monitoring_interval_months"],
        "status": e["status"],
        "posture": posture(e),
        "current_landowner_id": e["current_landowner_id"],
        "recorded_on": e["recorded_on"].isoformat() if e["recorded_on"] else None,
        "last_monitoring_completed_on": e["last_monitoring_completed_on"].isoformat()
        if e["last_monitoring_completed_on"]
        else None,
        "next_monitoring_due_on": (
            lambda d: d.isoformat() if d else None
        )(next_monitoring_due_on(e)),
        "open_violation_count": open_violation_count(e["id"]),
        "amendment_count": amendment_count(e["id"]),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def landowner_json(r):
    return {
        "id": r["id"],
        "easement_id": r["easement_id"],
        "predecessor_landowner_id": r["predecessor_landowner_id"],
        "owner_name": r["owner_name"],
        "contact_email": r["contact_email"],
        "status": r["status"],
        "acquired_on": r["acquired_on"].isoformat() if r["acquired_on"] else None,
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def baseline_json(r):
    e = db.easements.get(r["easement_id"])
    return {
        "id": r["id"],
        "easement_id": r["easement_id"],
        "prepared_by_user_id": r["prepared_by_user_id"],
        "condition_narrative": r["condition_narrative"],
        "photo_point_count": r["photo_point_count"],
        "required_photo_points": required_photo_points(e["parcel_acreage"]) if e else None,
        "review_round": r["review_round"],
        "submitted_on": r["submitted_on"].isoformat() if r["submitted_on"] else None,
        "accepted_on": r["accepted_on"].isoformat() if r["accepted_on"] else None,
        "revision_notes": r["revision_notes"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def visit_json(r):
    return {
        "id": r["id"],
        "easement_id": r["easement_id"],
        "monitor_user_id": r["monitor_user_id"],
        "window_start_on": r["window_start_on"].isoformat(),
        "window_end_on": r["window_end_on"].isoformat(),
        "actual_visit_on": r["actual_visit_on"].isoformat() if r["actual_visit_on"] else None,
        "findings_summary": r["findings_summary"],
        "stewardship_cost_cents": r["stewardship_cost_cents"],
        "on_time": r["on_time"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def violation_json(r):
    return {
        "id": r["id"],
        "easement_id": r["easement_id"],
        "monitoring_visit_id": r["monitoring_visit_id"],
        "detected_by_user_id": r["detected_by_user_id"],
        "violation_type": r["violation_type"],
        "severity": r["severity"],
        "detected_on": r["detected_on"].isoformat(),
        "notice_served_on": r["notice_served_on"].isoformat() if r["notice_served_on"] else None,
        "cure_deadline_on": r["cure_deadline_on"].isoformat() if r["cure_deadline_on"] else None,
        "resolved_on": r["resolved_on"].isoformat() if r["resolved_on"] else None,
        "resolution_verified_by_user_id": r["resolution_verified_by_user_id"],
        "escalated_by": r["escalated_by"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def amendment_json(r):
    return {
        "id": r["id"],
        "easement_id": r["easement_id"],
        "submitted_by_user_id": r["submitted_by_user_id"],
        "requested_changes": r["requested_changes"],
        "affected_acreage": r["affected_acreage"],
        "materiality_score": r["materiality_score"],
        "review_path": r["review_path"],
        "revision_notes": r["revision_notes"],
        "decided_by_user_id": r["decided_by_user_id"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def use_auth_json(r):
    return {
        "id": r["id"],
        "easement_id": r["easement_id"],
        "use_type": r["use_type"],
        "requested_by_landowner_id": r["requested_by_landowner_id"],
        "justification": r["justification"],
        "decision": r["decision"],
        "conditions": r["conditions"],
        "decision_reason": r["decision_reason"],
        "conditions_breached": r["conditions_breached"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def enforcement_json(r):
    return {
        "id": r["id"],
        "violation_id": r["violation_id"],
        "easement_id": r["easement_id"],
        "agreement_terms": r["agreement_terms"],
        "remediation_cost_cents": r["remediation_cost_cents"],
        "executed_by_user_id": r["executed_by_user_id"],
        "completed_by_user_id": r["completed_by_user_id"],
        "breach_notes": r["breach_notes"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def succession_json(r):
    return {
        "id": r["id"],
        "easement_id": r["easement_id"],
        "successor_landowner_id": r["successor_landowner_id"],
        "predecessor_landowner_id": r["predecessor_landowner_id"],
        "transfer_on": r["transfer_on"].isoformat(),
        "notice_given_on": r["notice_given_on"].isoformat(),
        "ack_deadline_on": r["ack_deadline_on"].isoformat(),
        "recorded_on": r["recorded_on"].isoformat() if r["recorded_on"] else None,
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def appraisal_json(r):
    return {
        "id": r["id"],
        "easement_id": r["easement_id"],
        "appraiser_user_id": r["appraiser_user_id"],
        "effective_on": r["effective_on"].isoformat(),
        "gift_on": r["gift_on"].isoformat(),
        "contiguous_enhancement_applies": r["contiguous_enhancement_applies"],
        "before_value_cents": r["before_value_cents"],
        "after_value_cents": r["after_value_cents"],
        "enhancement_value_cents": r["enhancement_value_cents"],
        "deductible_value_cents": r["deductible_value_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def fund_json(f):
    units = f["units_outstanding"]
    return {
        "id": f["id"],
        "easement_id": f["easement_id"],
        "spending_rate_bps": f["spending_rate_bps"],
        "principal_floor_cents": f["principal_floor_cents"],
        "status": f["status"],
        "market_value_cents": f["market_value_cents"],
        "units_outstanding": utils.num4(units),
        "unit_value_cents": None if units == 0 else utils.num4(f["_unit_value_cents"]),
        "fiscal_year": f["fiscal_year"],
        "prior_year_close_mv_cents": f["prior_year_close_mv_cents"],
        "provisional_draws_ytd_cents": provisional_draws_ytd(f),
        "policy_draw_allowance_cents": policy_draw_allowance(f),
        "carryover_allowance_cents": f["carryover_allowance_cents"],
        "unitized_draw_capacity_cents": max(
            0, f["market_value_cents"] - f["principal_floor_cents"]
        ),
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def txn_json(t):
    """EndowmentTransaction: id + created_at only (no updated_at/version)."""
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "fund_id": t["fund_id"],
        "txn_type": t["txn_type"],
        "amount_cents": t["amount_cents"],
        "units": utils.num4(t["units"]),
        "purpose": t["purpose"],
        "from_policy_allowance_cents": t["from_policy_allowance_cents"],
        "from_excess_cents": t["from_excess_cents"],
        "from_principal_invasion_cents": t["from_principal_invasion_cents"],
        "fiscal_year": t["fiscal_year"],
        "posted_on": t["posted_on"],
    }
