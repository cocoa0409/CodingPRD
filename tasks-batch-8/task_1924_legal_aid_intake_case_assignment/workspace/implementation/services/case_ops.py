"""Case closure side effects, shared by POST /cases/{id}/close and the sweep."""
from db import db, now
from services.common import touch
from services.enums import BILLABLE_OUTCOMES


def close_case(case, outcome_code, closure_reason):
    """Apply the full closure side-effect set (PRD section 3.8).

    - stamps closed_at, moves status to CLOSED
    - attorney load release happens implicitly (load is derived from OPEN cases)
    - grant ledger settle: billable outcomes convert reservation to spent;
      non-billable outcomes release it
    - any ACCEPTED referral for the case -> COMPLETED (panel count is derived)
    """
    case["status"] = "CLOSED"
    case["outcome_code"] = outcome_code
    case["closure_reason"] = closure_reason
    case["closed_at"] = now()
    touch(case)

    if case["assigned_attorney_id"] is not None:
        attorney = db.staff.get(case["assigned_attorney_id"])
        if attorney is not None:
            touch(attorney)  # derived load changed for OPEN-source closes

    if case["funding_status"] in ("GRANT_RESERVED", "GRANT_FROZEN"):
        program = db.grant_programs.get(case["grant_program_id"])
        if outcome_code in BILLABLE_OUTCOMES:
            case["funding_status"] = "GRANT_SPENT"
        else:
            case["funding_status"] = "GRANT_RELEASED"
        if program is not None:
            touch(program)  # reserved/spent buckets changed (derived)

    for ref in db.referrals.values():
        if ref["case_id"] == case["id"] and ref["status"] == "ACCEPTED":
            ref["status"] = "COMPLETED"
            touch(ref)
            member = db.panel_members.get(ref["panel_member_id"])
            if member is not None:
                touch(member)  # active_referral_count fell (derived)
