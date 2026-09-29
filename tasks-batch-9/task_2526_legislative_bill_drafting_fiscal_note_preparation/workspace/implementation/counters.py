"""Derived-counter recomputation (PRD S2.10: counters are derived, not narrative).

Every helper recomputes its counter from scratch and only marks the row dirty
when a value actually changed, so a row's `version` moves exactly once per
request no matter how many counters on it were revisited.
"""

from calc import (
    occupancy_intervals,
    responsiveness_score,
    MEMBER_CLARIFICATION_HOLD_THRESHOLD,
)
from store import all_rows, db, touch


def _apply(row, values):
    changed = False
    for key, value in values.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


# ---------------------------------------------------------------------------


def recompute_member(member_id):
    member = db.members.get(member_id)
    if member is None:
        return
    slots = 0
    pending = 0
    for row in db.drafting_requests.values():
        if row["member_id"] != member_id:
            continue
        if row["priority_flag"] and row["status"] not in ("WITHDRAWN", "LAPSED"):
            slots += 1
        if row["status"] == "RETURNED_FOR_CLARIFICATION":
            pending += 1
    _apply(
        member,
        {
            "priority_slots_used": slots,
            "clarification_pending_count": pending,
            "intake_hold": pending >= MEMBER_CLARIFICATION_HOLD_THRESHOLD,
        },
    )


def recompute_drafter(drafter_id):
    drafter = db.drafters.get(drafter_id)
    if drafter is None:
        return
    _apply(
        drafter,
        {"active_engagement_count": len(occupancy_intervals(drafter_id))},
    )


def recompute_committee(committee_id):
    committee = db.committees.get(committee_id)
    if committee is None:
        return
    count = 0
    for row in db.committee_referrals.values():
        if row["committee_id"] == committee_id and row["status"] == "IN_COMMITTEE":
            count += 1
    _apply(committee, {"active_referral_count": count})


def recompute_agency(agency_id):
    agency = db.agencies.get(agency_id)
    if agency is None:
        return
    open_count = 0
    for row in db.fiscal_note_requests.values():
        if row["agency_id"] == agency_id and row["status"] in (
            "ROUTED",
            "SUBMITTED",
            "RETURNED_FOR_REVISION",
        ):
            open_count += 1
    _apply(
        agency,
        {
            "open_request_count": open_count,
            "responsiveness_score": responsiveness_score(agency),
        },
    )


def recompute_request_conflicts(request_id):
    row = db.drafting_requests.get(request_id)
    if row is None:
        return
    blocking = 0
    open_blocking = 0
    advisory = 0
    for conflict in db.statutory_conflicts.values():
        if conflict["drafting_request_id"] != request_id:
            continue
        if conflict["severity"] == "BLOCKING":
            blocking += 1
            if conflict["resolution_status"] == "OPEN":
                open_blocking += 1
        else:
            advisory += 1
    _apply(
        row,
        {
            "blocking_conflict_count": blocking,
            "open_blocking_conflict_count": open_blocking,
            "advisory_conflict_count": advisory,
        },
    )


def recompute_bill_rollups(bill_id):
    bill = db.bills.get(bill_id)
    if bill is None:
        return
    referrals = 0
    for row in db.committee_referrals.values():
        if row["bill_id"] == bill_id:
            referrals += 1
    adopted = 0
    delta = 0
    for row in db.amendments.values():
        if row["bill_id"] == bill_id and row["status"] == "ADOPTED":
            adopted += 1
            delta += row["fiscal_impact_delta_cents"]
    _apply(
        bill,
        {
            "referral_count": referrals,
            "adopted_amendment_count": adopted,
            "adopted_fiscal_delta_cents": delta,
        },
    )


def recompute_session_bill_counts(session_id):
    session = db.sessions.get(session_id)
    if session is None:
        return
    introduced = 0
    enrolled = 0
    for row in db.bills.values():
        if row["session_id"] != session_id:
            continue
        introduced += 1
        if row["legislative_status"] in ("ENROLLED", "TRANSMITTED"):
            enrolled += 1
    _apply(
        session,
        {"bills_introduced_count": introduced, "bills_enrolled_count": enrolled},
    )


def recompute_enrollment_counts(enrolled_bill_id):
    enrollment = db.enrolled_bills.get(enrolled_bill_id)
    if enrollment is None:
        return
    applied = 0
    open_count = 0
    for row in db.technical_corrections.values():
        if row["enrolled_bill_id"] != enrolled_bill_id:
            continue
        if row["status"] == "APPLIED":
            applied += 1
        elif row["status"] == "PROPOSED":
            open_count += 1
    _apply(
        enrollment,
        {"corrections_applied_count": applied, "open_corrections_count": open_count},
    )


def recompute_session_posture(session):
    """fiscal_posture is CONSTRAINED at an inclusive boundary (PRD S2.9)."""
    posture = (
        "CONSTRAINED"
        if session["certified_fiscal_total_cents"] >= session["constrained_threshold_cents"]
        else "NORMAL"
    )
    _apply(session, {"fiscal_posture": posture})


def post_to_ledger(session, amount_cents):
    session["certified_fiscal_total_cents"] = (
        session["certified_fiscal_total_cents"] + amount_cents
    )
    touch(session)
    recompute_session_posture(session)
