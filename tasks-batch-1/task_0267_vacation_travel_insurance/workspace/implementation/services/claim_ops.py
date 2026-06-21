"""Claim domain operations: provisional/final reimbursement, adjudication gates,
delay-event de-duplication."""
import errors
from db import db
from services import calc, common
from services.store_helpers import (
    touch, expenses_for_claim, documents_for_claim, get_named_storm,
)


# --------------------------------------------------------------------------
# Provisional reimbursement (at submission / resubmit / expense add)
# --------------------------------------------------------------------------
def compute_provisional(claim, policy, plan):
    expenses = expenses_for_claim(claim["id"])
    remaining = policy["remaining_aggregate_cents"]
    peril = claim["peril"]
    if peril == "CANCELLATION":
        return calc.cancellation_provisional(
            expenses, policy["trip_cost_cents"], plan, remaining
        )
    if peril == "MEDICAL":
        return calc.medical_provisional(expenses, plan, remaining)
    if peril == "DELAY":
        return calc.delay_final(claim["delay_hours"], plan, remaining)
    if peril == "BAGGAGE":
        return calc.baggage_provisional(expenses, plan, remaining)
    return 0


def refresh_provisional(claim):
    policy = db.policies[claim["policy_id"]]
    plan = db.plans[policy["plan_id"]]
    claim["provisional_amount_cents"] = compute_provisional(claim, policy, plan)


# --------------------------------------------------------------------------
# Filing-window gate (one-sided lateness deadline; PRD §3.4)
# --------------------------------------------------------------------------
def filing_window_open(claim, plan):
    """True if current clock <= incident_at + claim_filing_window_days."""
    incident = claim["_incident_at_dt"]
    deadline = common.add_days(incident, plan["claim_filing_window_days"])
    return common.current_clock() <= deadline


# --------------------------------------------------------------------------
# Delay-event de-duplication (PRD §3.7)
# --------------------------------------------------------------------------
def enforce_delay_event_overlap(policy_id, new_incident_dt, new_delay_hours):
    """Reject a DELAY claim whose covered delay window falls within
    DELAY_MERGE_BUFFER_HOURS of an existing DELAY claim on the same policy.

    Per PRD §3.7 the comparison is over the *covered delay window* — the closed
    interval [incident_at, incident_at + delay_hours] — extended by the six-hour
    merge buffer. Two windows are the same event when, after extending by the
    buffer, they touch or overlap; i.e. the gap between the two closed intervals
    is at most the buffer."""
    from datetime import timedelta
    buffer = timedelta(hours=calc.DELAY_MERGE_BUFFER_HOURS).total_seconds()
    new_start = new_incident_dt
    new_end = new_incident_dt + timedelta(hours=new_delay_hours)
    for c in db.claims.values():
        if c["policy_id"] != policy_id:
            continue
        if c["peril"] != "DELAY":
            continue
        existing_start = c["_incident_at_dt"]
        existing_end = existing_start + timedelta(hours=c["delay_hours"])
        # Same event if the closed intervals overlap after extending by the buffer:
        # new_start <= existing_end + buffer AND existing_start <= new_end + buffer.
        if (new_start.timestamp() <= existing_end.timestamp() + buffer
                and existing_start.timestamp() <= new_end.timestamp() + buffer):
            raise errors.conflict(
                errors.ERR_DELAY_EVENT_OVERLAP,
                "A DELAY claim within the merge buffer already exists on this policy.",
            )


# --------------------------------------------------------------------------
# Final reimbursement (at approval)
# --------------------------------------------------------------------------
def compute_final(claim, policy, plan):
    expenses = expenses_for_claim(claim["id"])
    remaining = policy["remaining_aggregate_cents"]
    peril = claim["peril"]
    if peril == "CANCELLATION":
        return calc.cancellation_final(
            expenses, policy["trip_cost_cents"], plan, remaining, claim.get("cancellation_reason")
        )
    if peril == "MEDICAL":
        return calc.medical_final(expenses, plan, remaining)
    if peril == "DELAY":
        return calc.delay_final(claim["delay_hours"], plan, remaining)
    if peril == "BAGGAGE":
        return calc.baggage_final(expenses, plan, remaining)
    return 0


# --------------------------------------------------------------------------
# Approval gates (PRD §3.6, ordered; safety/eligibility before fiscal)
# --------------------------------------------------------------------------
def approve_claim(claim):
    policy = db.policies[claim["policy_id"]]
    plan = db.plans[policy["plan_id"]]

    # 1. state
    if claim["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Claim is not UNDER_REVIEW.")
    # 2. policy active
    if policy["coverage_status"] != "ACTIVE":
        raise errors.conflict(errors.ERR_POLICY_NOT_ACTIVE, "Policy is not ACTIVE.")
    # 3. filing deadline (re-checked at approval)
    if not filing_window_open(claim, plan):
        raise errors.conflict(errors.ERR_FILING_WINDOW_CLOSED, "Filing window has closed.")
    # 4. pre-existing waiver (MEDICAL + involves_preexisting)
    if claim["peril"] == "MEDICAL" and claim["involves_preexisting"]:
        if not policy["preexisting_waiver_granted"]:
            raise errors.conflict(errors.ERR_PREEXISTING_NOT_WAIVED, "Pre-existing condition not waived.")
    # 5. named-storm cutoff (CANCELLATION + NAMED_STORM)
    if claim["peril"] == "CANCELLATION" and claim.get("cancellation_reason") == "NAMED_STORM":
        storm = db.named_storms.get(claim["named_storm_id"])
        # storm existence validated at filing; re-resolve for the cutoff test
        issued_at = policy["_issued_at_dt"]
        if storm is None or not (issued_at < storm["_named_at_dt"]):
            raise errors.conflict(errors.ERR_NAMED_STORM_CUTOFF, "Policy issued on or after the storm was named.")
    # 6. delay threshold (DELAY)
    if claim["peril"] == "DELAY":
        if claim["delay_hours"] < calc.MIN_DELAY_HOURS:
            raise errors.conflict(errors.ERR_DELAY_BELOW_THRESHOLD, "Delay below the covered threshold.")
    # 7. documentation present
    if len(documents_for_claim(claim["id"])) == 0:
        raise errors.conflict(errors.ERR_DOCUMENTATION_MISSING, "No supporting document on the claim.")

    # All gates passed: compute final reimbursement (capped), approve.
    claim["approved_amount_cents"] = compute_final(claim, policy, plan)
    claim["status"] = "APPROVED"
    touch(claim)
