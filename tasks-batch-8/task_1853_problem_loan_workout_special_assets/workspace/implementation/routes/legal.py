"""Legal referral routes (PRD §3.7)."""
from flask import Blueprint

import db
from auth import (
    ROLE_LEGAL_COUNSEL, ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST,
    ROLE_SPECIAL_ASSETS_MANAGER, ROLE_SYSTEM_ADMIN, ROLE_WORKOUT_OFFICER,
    require_roles,
)
from db import STORE
from errors import (
    ApiError, ERR_BUSINESS_CONSTRAINT, ERR_CASE_NOT_REFERRABLE,
    ERR_FISCAL_LIMIT, ERR_INVALID_TEMPORAL, ERR_NOT_FOUND,
    ERR_REFERRAL_NOT_ACTIVE, ERR_REFERRAL_NOT_PENDING, ERR_STATUTE_EXPIRED,
)
from response import ok, paginate
from services import (
    book_recovery, force_nonaccrual, get_borrower, get_loan, get_referral,
    referral_out, referrals_of_case, sorted_rows,
)
from validate import as_datetime, as_enum, as_int, as_str, field, get_body, no_unknown

bp = Blueprint("legal", __name__)

REFERRAL_KINDS = ("GUARANTOR_PURSUITS", "FORECLOSURE", "DEED_IN_LIEU", "NOTE_SALE_PREP")
REFERRAL_READERS = (
    ROLE_WORKOUT_OFFICER, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_LEGAL_COUNSEL,
    ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST, ROLE_SYSTEM_ADMIN,
)


def resolve(loanId, caseId, referralId=None):
    loan = get_loan(loanId)
    if loan is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Loan not found")
    case = STORE["cases"].get(caseId)
    if case is None or case["loan_id"] != loanId:
        raise ApiError(ERR_NOT_FOUND, 404, "Workout case not found")
    referral = None
    if referralId is not None:
        referral = get_referral(referralId)
        if referral is None or referral["case_id"] != caseId:
            raise ApiError(ERR_NOT_FOUND, 404, "Legal referral not found")
    return loan, case, referral


@bp.route("/loans/<loanId>/workout-cases/<caseId>/legal-referrals", methods=["POST"])
def create_referral(loanId, caseId):
    require_roles(ROLE_WORKOUT_OFFICER)
    loan, case, _ = resolve(loanId, caseId)
    data = get_body()
    no_unknown(data, {
        "referral_kind", "target_guarantor_name", "demand_amount_cents",
        "statute_deadline", "decision_rationale",
    })
    kind = as_enum(field(data, "referral_kind"), "referral_kind", REFERRAL_KINDS)
    guarantor = as_str(
        field(data, "target_guarantor_name", ""), "target_guarantor_name"
    )
    demand = as_int(field(data, "demand_amount_cents"), "demand_amount_cents", 0)
    statute_raw, statute_dt = as_datetime(
        field(data, "statute_deadline"), "statute_deadline"
    )
    rationale = as_str(field(data, "decision_rationale", ""), "decision_rationale")

    # state (priority 4)
    if case["status"] not in ("NEGOTIATION", "IMPAIRMENT_REVIEW"):
        raise ApiError(
            ERR_CASE_NOT_REFERRABLE, 409,
            "Referral requires NEGOTIATION or IMPAIRMENT_REVIEW",
        )
    # structural (priority 8)
    if kind == "GUARANTOR_PURSUITS":
        if guarantor == "":
            raise ApiError(
                ERR_BUSINESS_CONSTRAINT, 422,
                "target_guarantor_name is required for guarantor pursuits",
            )
        borrower = get_borrower(loan["borrower_id"])
        if demand > borrower["guarantor_net_worth_cents"]:
            raise ApiError(
                ERR_BUSINESS_CONSTRAINT, 422,
                "demand_amount_cents exceeds guarantor_net_worth_cents",
            )
        if demand > case["loss_given_default_cents"]:
            raise ApiError(
                ERR_BUSINESS_CONSTRAINT, 422,
                "demand_amount_cents exceeds loss_given_default_cents",
            )
    if kind in ("FORECLOSURE", "DEED_IN_LIEU") and rationale == "":
        raise ApiError(
            ERR_BUSINESS_CONSTRAINT, 422,
            "decision_rationale is required for FORECLOSURE and DEED_IN_LIEU",
        )
    # temporal (priority 10): statute deadline strictly in the future
    if statute_dt <= db.logical_now():
        raise ApiError(
            ERR_INVALID_TEMPORAL, 422,
            "statute_deadline must be strictly after the current time",
        )

    referral = db.stamp({
        "id": db.new_id(),
        "case_id": caseId,
        "referral_kind": kind,
        "target_guarantor_name": guarantor,
        "demand_amount_cents": demand,
        "statute_deadline": statute_raw,
        "statute_dt": statute_dt,
        "decision_rationale": rationale,
        "status": "PENDING_COUNSEL",
    })
    STORE["referrals"][referral["id"]] = referral
    case["status"] = "LEGAL"
    db.touch(case)
    force_nonaccrual(loan)
    return ok(referral_out(referral), 201)


@bp.route("/loans/<loanId>/workout-cases/<caseId>/legal-referrals", methods=["GET"])
def list_referrals(loanId, caseId):
    require_roles(*REFERRAL_READERS)
    resolve(loanId, caseId)
    rows = [referral_out(r) for r in sorted_rows(referrals_of_case(caseId))]
    return paginate(rows)


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/legal-referrals/<referralId>/accept",
    methods=["POST"],
)
def accept_referral(loanId, caseId, referralId):
    require_roles(ROLE_LEGAL_COUNSEL)
    _, _, referral = resolve(loanId, caseId, referralId)
    if referral["status"] != "PENDING_COUNSEL":
        raise ApiError(
            ERR_REFERRAL_NOT_PENDING, 409, "Referral is not PENDING_COUNSEL"
        )
    # statute re-checked against the logical clock at acceptance
    if referral["statute_dt"] <= db.logical_now():
        raise ApiError(
            ERR_STATUTE_EXPIRED, 422, "Statute of limitations deadline has passed"
        )
    referral["status"] = "ACTIVE"
    db.touch(referral)
    return ok(referral_out(referral))


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/legal-referrals/<referralId>/settle",
    methods=["POST"],
)
def settle_referral(loanId, caseId, referralId):
    require_roles(ROLE_LEGAL_COUNSEL)
    loan, case, referral = resolve(loanId, caseId, referralId)
    if referral["status"] != "ACTIVE":
        raise ApiError(ERR_REFERRAL_NOT_ACTIVE, 409, "Referral is not ACTIVE")
    if referral["referral_kind"] == "GUARANTOR_PURSUITS":
        data = get_body()
        no_unknown(data, {"settled_amount_cents"})
        amount = as_int(field(data, "settled_amount_cents"), "settled_amount_cents")
        if amount <= 0:
            raise ApiError(
                ERR_FISCAL_LIMIT, 422, "settled_amount_cents must be greater than zero"
            )
        # guarantor settlement books a linked CHRONOLOGICAL recovery
        book_recovery(loan, case, amount, "GUARANTOR_SETTLEMENT", "CHRONOLOGICAL")
    referral["status"] = "SETTLED"
    db.touch(referral)
    return ok(referral_out(referral))


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/legal-referrals/<referralId>/dismiss",
    methods=["POST"],
)
def dismiss_referral(loanId, caseId, referralId):
    require_roles(ROLE_LEGAL_COUNSEL)
    _, _, referral = resolve(loanId, caseId, referralId)
    if referral["status"] != "ACTIVE":
        raise ApiError(ERR_REFERRAL_NOT_ACTIVE, 409, "Referral is not ACTIVE")
    referral["status"] = "DISMISSED"
    db.touch(referral)
    return ok(referral_out(referral))
