"""CovenantEvaluation endpoints (PRD 3.7)."""
from flask import Blueprint

from db import STORE
from errors import raise_err
from middleware import ALL_ROLES, auth, require_role
from response import ok_list, ok_object
from serialize import list_response, ser_covenant
from services.core import reevaluate_borrower, stamp_new, touch
from util import as_dt, as_nonneg_int, as_str, body, need, new_id

bp = Blueprint("covenants", __name__)

TIER1_CAP_CENTS = 25_000_000
TIER2_CAP_CENTS = 100_000_000
TIER1_MILLI = 1100
TIER2_MILLI = 1250
TIER3_MILLI = 1400


def get_covenant_or_404(cid):
    c = STORE.covenants.get(cid)
    if c is None:
        raise_err("ERR_NOT_FOUND", "Covenant evaluation not found")
    return c


def required_ratio_milli(approved_commitment_cents):
    if approved_commitment_cents is None:
        return TIER1_MILLI
    if approved_commitment_cents <= TIER1_CAP_CENTS:
        return TIER1_MILLI
    if approved_commitment_cents <= TIER2_CAP_CENTS:
        return TIER2_MILLI
    return TIER3_MILLI


@bp.route("/covenant-evaluations", methods=["POST"])
def create_covenant():
    uid, role = auth()
    require_role(role, ["LoanOfficer"])
    b = body()
    loan_account_id = as_str(need(b, "loan_account_id"), "loan_account_id")
    as_of_date = as_dt(need(b, "as_of_date"), "as_of_date")
    assets = as_nonneg_int(need(b, "current_assets_cents"), "current_assets_cents")
    liabs = as_nonneg_int(need(b, "current_liabilities_cents"), "current_liabilities_cents")
    loan = STORE.loans.get(loan_account_id)
    if loan is None:
        raise_err("ERR_NOT_FOUND", "Loan account not found")
    required = required_ratio_milli(loan["approved_commitment_cents"])
    working_capital = assets - liabs
    if liabs == 0:
        ratio = 0 if assets == 0 else 999999999
        outcome = "COMPLIANT" if assets > 0 else "BREACH"
    else:
        ratio = (assets * 1000) // liabs
        outcome = ("COMPLIANT" if assets * 1000 >= required * liabs else "BREACH")
    evaluation = stamp_new({
        "id": new_id(),
        "loan_account_id": loan["id"],
        "borrower_id": loan["borrower_id"],
        "as_of_date": as_of_date,
        "current_assets_cents": assets,
        "current_liabilities_cents": liabs,
        "working_capital_cents": working_capital,
        "current_ratio_milli": ratio,
        "required_ratio_milli": required,
        "outcome": outcome,
        "recorded_by_user_id": uid,
        "status": "RECORDED",
    })
    STORE.covenants[evaluation["id"]] = evaluation
    borrower = STORE.borrowers.get(loan["borrower_id"])
    if borrower is not None:
        if outcome == "BREACH":
            borrower["active_covenant_breach_count"] += 1
        else:
            borrower["active_covenant_breach_count"] = 0
    reevaluate_borrower(loan["borrower_id"])
    return ok_object(ser_covenant(evaluation), code=201)


@bp.route("/covenant-evaluations/<cid>", methods=["GET"])
def get_covenant(cid):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return ok_object(ser_covenant(get_covenant_or_404(cid)))


@bp.route("/covenant-evaluations", methods=["GET"])
def list_covenants():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    page, total, limit, offset, ser = list_response(
        STORE.covenants.values(), ser_covenant,
        [("loan_account_id", lambda e: e["loan_account_id"]),
         ("borrower_id", lambda e: e["borrower_id"]),
         ("status", lambda e: e["status"])])
    return ok_list([ser(e) for e in page], limit, offset, total)


@bp.route("/covenant-evaluations/<cid>/waive", methods=["POST"])
def waive_covenant(cid):
    uid, role = auth()
    require_role(role, ["CreditCommittee"])
    evaluation = get_covenant_or_404(cid)
    if evaluation["status"] != "RECORDED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a RECORDED evaluation can be waived")
    if uid == evaluation["recorded_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "The recording officer cannot waive this evaluation")
    evaluation["status"] = "WAIVED"
    touch(evaluation)
    if evaluation["outcome"] == "BREACH":
        borrower = STORE.borrowers.get(evaluation["borrower_id"])
        if borrower is not None and borrower["active_covenant_breach_count"] > 0:
            borrower["active_covenant_breach_count"] -= 1
    reevaluate_borrower(evaluation["borrower_id"])
    return ok_object(ser_covenant(evaluation))


@bp.route("/covenant-evaluations/<cid>/void", methods=["POST"])
def void_covenant(cid):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    evaluation = get_covenant_or_404(cid)
    if evaluation["status"] != "RECORDED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a RECORDED evaluation can be voided")
    evaluation["status"] = "VOIDED"
    touch(evaluation)
    if evaluation["outcome"] == "BREACH":
        borrower = STORE.borrowers.get(evaluation["borrower_id"])
        if borrower is not None and borrower["active_covenant_breach_count"] > 0:
            borrower["active_covenant_breach_count"] -= 1
    reevaluate_borrower(evaluation["borrower_id"])
    return ok_object(ser_covenant(evaluation))
