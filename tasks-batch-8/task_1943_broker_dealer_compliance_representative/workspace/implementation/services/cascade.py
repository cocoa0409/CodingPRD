"""Multi-entity cascades (PRD 3.1, 3.5, 3.6). All atomic within the request."""
from db import db
from services.branch import recompute_branch
from services.core import new_record, touch
from util import add_days, parse_date, today


def terminate_rep_cascade(rep):
    """RegisteredRepresentative ACTIVE -> TERMINATED side effects (PRD 3.1):
    - every OBA in {SUBMITTED, SUSPENDED_REVIEW} -> WITHDRAWN (no count/fee change)
    - every ACTIVE plan -> TERMINATED with terminated_reason = REP_TERMINATED
    - branch sd_rep_count recompute (decrements if the rep was SD-flagged)
    The rep's own is_statutorily_disqualified / supervision_tier stay as-is.
    """
    for act in db["outside_activities"].values():
        if act["rep_id"] == rep["id"] and act["status"] in ("SUBMITTED", "SUSPENDED_REVIEW"):
            act["status"] = "WITHDRAWN"
            touch(act)
    for plan in db["supervision_plans"].values():
        if plan["rep_id"] == rep["id"] and plan["status"] == "ACTIVE":
            plan["status"] = "TERMINATED"
            plan["terminated_reason"] = "REP_TERMINATED"
            touch(plan)
    branch = db["branches"].get(rep["branch_id"])
    if branch is not None and recompute_branch(branch):
        touch(branch)


def sd_ack_cascade(rep):
    """SD-trigger DisclosureEvent acknowledgement cascade (PRD 3.6).

    L1: rep.is_statutorily_disqualified := true; supervision_tier := HEIGHTENED;
        rep.version + 1 (unconditional per the state machine).
    L1 fan-out: every OBA of the rep in SUBMITTED -> SUSPENDED_REVIEW.
    L2: branch sd_rep_count recompute; when >= 1 the cycle accelerates
        (inspection_cycle_months := min(current, 6), sticky) and the due date is
        recomputed on the shortened cycle; branch.version + 1.
    L3: a SCHEDULED inspection of the branch whose scheduled_date exceeds the new
        due date is pulled forward to the due date; inspection.version + 1.
    """
    rep["is_statutorily_disqualified"] = True
    rep["supervision_tier"] = "HEIGHTENED"
    touch(rep)

    for act in db["outside_activities"].values():
        if act["rep_id"] == rep["id"] and act["status"] == "SUBMITTED":
            act["status"] = "SUSPENDED_REVIEW"
            touch(act)

    branch = db["branches"].get(rep["branch_id"])
    if branch is None:
        return
    recompute_branch(branch)  # refresh sd_rep_count first
    if branch["sd_rep_count"] >= 1:
        branch["inspection_cycle_months"] = min(branch["inspection_cycle_months"],
                                                6)
        recompute_branch(branch, recompute_due=True)
        touch(branch)  # L2 pins an unconditional branch bump when sd >= 1
        due = branch["next_inspection_due_date"]
        if due is not None:
            for insp in db["inspections"].values():
                if (insp["branch_id"] == branch["id"] and insp["status"] == "SCHEDULED"
                        and parse_date(insp["scheduled_date"]) > parse_date(due)):
                    insp["scheduled_date"] = due
                    touch(insp)
    else:
        if recompute_branch(branch):
            touch(branch)


def complaint_award_cascade(complaint):
    """complaint_award_disclosure_trigger (PRD 3.5): damages_paid_cents >= 150000
    auto-creates a DRAFT CUSTOMER_AWARD DisclosureEvent linked to the complaint."""
    event_date = today()
    return new_record("disclosure_events", {
        "rep_id": complaint["rep_id"],
        "event_type": "CUSTOMER_AWARD",
        "event_date": event_date.isoformat(),
        "description": "",
        "is_sd_trigger": False,
        "filing_deadline": add_days(event_date, 30).isoformat(),
        "filed_at": None,
        "is_late": None,
        "source_complaint_id": complaint["id"],
        "status": "DRAFT",
    })
