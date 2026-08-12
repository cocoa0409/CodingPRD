"""Disbursement lifecycle: issue, cancel, return, reissue (PRD §3.7, §2.10)."""

from flask import Blueprint

import errors
from db import clock_date, create_entity, store, touch
from middleware import require_roles
from response import ok
from services import (
    AGE_THRESHOLD_MONTHS,
    WINDOW_DAYS,
    add_days,
    age_months_on,
    case_source_account,
    draft_1099,
    parse_date,
    restore_disbursement,
    serialize_disbursement,
)

bp = Blueprint("disbursements", __name__)


def _get_disb_or_404(disb_id):
    d = store.disbursements.get(disb_id)
    if d is None:
        raise errors.err_disbursement_not_found()
    return d


def _in_freeze_window(plan_id, on_date):
    """Closed-interval membership in any freeze window of the plan (PRD §2.10)."""
    for w in store.freeze_windows.values():
        if w["plan_id"] != plan_id:
            continue
        s = parse_date(w["start_date"])
        e = parse_date(w["end_date"])
        if s is not None and e is not None and s <= on_date <= e:
            return True
    return False


def _participant_age_months(case):
    src = case_source_account(case)
    if src is None:
        return 0
    participant = store.participants.get(src["participant_id"])
    if participant is None:
        return 0
    dob = parse_date(participant["date_of_birth"])
    if dob is None:
        return 0
    return age_months_on(dob, clock_date())


@bp.post("/v1/disbursements/<disb_id>/issue")
@require_roles("RolloverProcessor")
def issue_disbursement(disb_id):
    disb = _get_disb_or_404(disb_id)
    if disb["status"] != "PENDING":
        raise errors.err_disbursement_invalid_state("Only a PENDING disbursement may be issued")
    case = store.cases.get(disb["rollover_case_id"])
    if case is None or case["status"] != "ELIGIBLE":
        raise errors.err_case_invalid_state("Owning case is not ELIGIBLE")
    src = case_source_account(case)
    today = clock_date()
    if src is not None and _in_freeze_window(src["plan_id"], today):
        raise errors.err_disbursement_in_freeze()

    disb["issued_date"] = today.isoformat()
    disb["status"] = "ISSUED"
    touch(disb)

    # First-issuance anchoring — never re-anchored by later reissue (PRD §3.7).
    first_issuance = case.get("disbursement_issued_date") is None
    if first_issuance:
        case["disbursement_issued_date"] = today.isoformat()

    src_acct = case_source_account(case)
    participant_id = src_acct["participant_id"] if src_acct else None
    if case["case_type"] == "DIRECT_ROLLOVER_OUT":
        case["status"] = "DISBURSED"
        if first_issuance:
            # Non-taxable trustee-to-trustee movement: CODE_G, taxable 0.
            draft_1099(
                case_id=case["id"],
                loan_id=None,
                participant_id=participant_id,
                tax_year=today.year,
                gross=case["gross_cents"],
                withholding=case["withholding_cents"],
                taxable=0,
                code="CODE_G",
            )
    else:  # INDIRECT_ROLLOVER_OUT
        case["status"] = "AWAITING_REDEPOSIT"
        if first_issuance:
            deadline = add_days(today, WINDOW_DAYS)
            case["rollover_deadline_date"] = deadline.isoformat()
            for seq, days in ((1, 30), (2, 45), (3, 55)):
                create_entity(
                    store.notices,
                    {
                        "rollover_case_id": case["id"],
                        "notice_seq": seq,
                        "scheduled_date": add_days(today, days).isoformat(),
                        "status": "SCHEDULED",
                        "days_remaining": None,
                        "outstanding_cents": None,
                    },
                )
            months = _participant_age_months(case)
            code = "CODE_7" if months >= AGE_THRESHOLD_MONTHS else "CODE_1"
            # Provisional variant: assumes nothing will be redeposited.
            draft_1099(
                case_id=case["id"],
                loan_id=None,
                participant_id=participant_id,
                tax_year=today.year,
                gross=case["gross_cents"],
                withholding=case["withholding_cents"],
                taxable=case["taxable_cents"],
                code=code,
            )
    touch(case)
    return ok(serialize_disbursement(disb))


@bp.post("/v1/disbursements/<disb_id>/cancel")
@require_roles("RolloverProcessor")
def cancel_disbursement(disb_id):
    disb = _get_disb_or_404(disb_id)
    if disb["status"] not in ("PENDING", "RETURNED"):
        raise errors.err_disbursement_invalid_state("Only PENDING or RETURNED disbursements may be cancelled")
    disb["status"] = "CANCELLED"
    touch(disb)
    restore_disbursement(disb)  # compensating restoration to pre-issue values
    return ok(serialize_disbursement(disb))


@bp.post("/v1/disbursements/<disb_id>/return")
@require_roles("RolloverProcessor")
def return_disbursement(disb_id):
    disb = _get_disb_or_404(disb_id)
    if disb["status"] != "ISSUED":
        raise errors.err_disbursement_invalid_state("Only an ISSUED disbursement may be returned")
    disb["status"] = "RETURNED"
    touch(disb)
    return ok(serialize_disbursement(disb))


@bp.post("/v1/disbursements/<disb_id>/reissue")
@require_roles("RolloverProcessor")
def reissue_disbursement(disb_id):
    disb = _get_disb_or_404(disb_id)
    if disb["status"] != "RETURNED":
        raise errors.err_disbursement_invalid_state("Only a RETURNED disbursement may be reissued")
    case = store.cases.get(disb["rollover_case_id"])
    if case is None or case["status"] not in ("DISBURSED", "AWAITING_REDEPOSIT"):
        raise errors.err_case_invalid_state("Owning case is not DISBURSED or AWAITING_REDEPOSIT")
    disb["issued_date"] = clock_date().isoformat()  # refreshed; 60-day deadline NOT restarted
    disb["status"] = "ISSUED"
    touch(disb)
    return ok(serialize_disbursement(disb))
