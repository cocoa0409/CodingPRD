from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success
from services import posture
from services.common import parse_dt, stamp_new, touch
from services.pagination import get_pagination, paginate
from services.serialize import loan as ser_loan
from services.validate import (
    body_json, opt_int, require_fields, req_enum, req_int, req_number, req_str,
)

bp = Blueprint("loans", __name__)


@bp.post("/loans")
def create_loan():
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer"])
    data = body_json()
    require_fields(data, [
        "borrower_id", "loan_number", "original_principal_cents", "note_rate",
        "origination_date", "maturity_date", "dscr_covenant_threshold",
        "ltv_covenant_threshold", "dscr_basis", "assumption_fee_basis",
    ])
    borrower_id = req_str(data, "borrower_id")
    if borrower_id not in db.borrowers:
        raise errors.not_found("borrower_id does not reference an existing borrower")
    loan_number = req_str(data, "loan_number")
    original_principal = req_int(data, "original_principal_cents", gt=0)
    note_rate = req_number(data, "note_rate", gt=0, lt=1)
    origination = parse_dt(data.get("origination_date"), "origination_date")
    maturity = parse_dt(data.get("maturity_date"), "maturity_date")
    dscr_thr = req_number(data, "dscr_covenant_threshold", gt=0)
    ltv_thr = req_number(data, "ltv_covenant_threshold", gt=0, lt=1)
    dscr_basis = req_enum(data, "dscr_basis", ("TTM", "T3_ANNUALIZED"))
    fee_basis = req_enum(data, "assumption_fee_basis", ("OUTSTANDING", "ORIGINAL"))
    current_balance = opt_int(data, "current_balance_cents", default=original_principal, minimum=0)
    for l in db.loans.values():
        if l["loan_number"] == loan_number:
            raise errors.invalid_request("loan_number must be unique")
    loan = {
        "id": db.new_id(),
        "borrower_id": borrower_id,
        "loan_number": loan_number,
        "original_principal_cents": original_principal,
        "current_balance_cents": current_balance,
        "note_rate": note_rate,
        "origination_date": db.fmt_ts(origination),
        "origination_date_dt": origination,
        "maturity_date": db.fmt_ts(maturity),
        "maturity_date_dt": maturity,
        "payment_status": "CURRENT",
        "servicing_status": "PERFORMING",
        "delinquent_since": None,
        "delinquent_since_dt": None,
        "dscr_covenant_threshold": dscr_thr,
        "ltv_covenant_threshold": ltv_thr,
        "dscr_basis": dscr_basis,
        "assumption_fee_basis": fee_basis,
        "current_dscr": None,
        "current_ltv": None,
        "capitalized_advances_cents": 0,
    }
    stamp_new(loan)
    db.loans[loan["id"]] = loan
    return success(ser_loan(loan), status=201)


@bp.get("/loans")
def list_loans():
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    limit, offset = get_pagination()
    items = list(db.loans.values())
    borrower_id = request.args.get("borrower_id")
    servicing_status = request.args.get("servicing_status")
    payment_status = request.args.get("payment_status")
    if borrower_id is not None:
        items = [l for l in items if l["borrower_id"] == borrower_id]
    if servicing_status is not None:
        items = [l for l in items if l["servicing_status"] == servicing_status]
    if payment_status is not None:
        items = [l for l in items if l["payment_status"] == payment_status]
    if actor["role"] == "Borrower":
        items = [l for l in items if l["borrower_id"] == actor["user_id"]]
    # Newest created_at first.
    items.sort(key=lambda l: (l["created_at"], l["id"]), reverse=True)
    page, pg = paginate([ser_loan(l) for l in items], limit, offset)
    return success(page, pagination=pg, is_array=True)


@bp.get("/loans/<lid>")
def get_loan(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    loan = db.loans.get(lid)
    if not mw.read_scope_allows(actor, "loan", loan):
        raise errors.not_found("Loan not found")
    return success(ser_loan(loan))


@bp.post("/loans/<lid>/payment-status")
def set_payment_status(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer"])
    loan = db.loans.get(lid)
    if loan is None:
        raise errors.not_found("Loan not found")
    data = body_json()
    require_fields(data, ["to_status"])
    to_status = req_enum(data, "to_status", ("DELINQUENT", "CURRENT", "DEFAULT"))
    cur = loan["payment_status"]
    # State-machine precondition (priority 7) before temporal gate (priority 31).
    if to_status == "DELINQUENT":
        if cur != "CURRENT":
            raise errors.invalid_state("Only a CURRENT loan can be marked DELINQUENT")
        loan["payment_status"] = "DELINQUENT"
        loan["delinquent_since_dt"] = db.get_clock()
        loan["delinquent_since"] = db.fmt_ts(db.get_clock())
    elif to_status == "CURRENT":
        if cur != "DELINQUENT":
            raise errors.invalid_state("Only a DELINQUENT loan can return to CURRENT")
        loan["payment_status"] = "CURRENT"
        loan["delinquent_since_dt"] = None
        loan["delinquent_since"] = None
    else:  # DEFAULT
        if cur != "DELINQUENT":
            raise errors.invalid_state("Only a DELINQUENT loan can move to DEFAULT")
        if posture.loan_days_delinquent(loan) < 60:
            raise errors.ApiError(
                errors.ERR_DELINQUENCY_THRESHOLD,
                "DEFAULT requires days_delinquent >= 60", 422,
            )
        loan["payment_status"] = "DEFAULT"
    touch(loan)
    posture.reevaluate_risk(loan)
    posture.reevaluate_servicing(loan)
    return success(ser_loan(loan))


@bp.post("/loans/<lid>/reinstate")
def reinstate(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["SpecialServicer"])
    loan = db.loans.get(lid)
    if loan is None:
        raise errors.not_found("Loan not found")
    if loan["servicing_status"] != "SPECIAL_SERVICING":
        raise errors.invalid_state("Loan is not in SPECIAL_SERVICING")
    # Pipeline order: covenant (9) -> currency (10) -> active entries (13) -> reserve target (36)
    if posture.loan_open_assessments(loan["id"]):
        raise errors.ApiError(
            errors.ERR_OPEN_COVENANT_BREACH, "OPEN covenant assessment blocks reinstatement", 409)
    if loan["payment_status"] != "CURRENT":
        raise errors.ApiError(
            errors.ERR_LOAN_NOT_CURRENT, "Loan payment_status must be CURRENT", 409)
    if posture.loan_active_entries(loan["id"]):
        raise errors.ApiError(
            errors.ERR_ACTIVE_WATCHLIST_ENTRIES, "ACTIVE watchlist entries remain", 409)
    for r in db.reserve_accounts.values():
        if r["loan_id"] == loan["id"] and r["balance_cents"] < r["target_balance_cents"]:
            raise errors.ApiError(
                errors.ERR_RESERVE_TARGET_SHORTFALL,
                "Reserve balance below target", 422)
    loan["servicing_status"] = "PERFORMING"
    touch(loan)
    clock = db.get_clock()
    for r in db.reserve_accounts.values():
        if r["loan_id"] != loan["id"]:
            continue
        changed = False
        if r["disbursement_frozen"]:
            r["disbursement_frozen"] = False
            changed = True
        if r["elevated_retainage"]:
            r["elevated_retainage"] = False
            changed = True
        if changed:
            touch(r)
    for o in db.extension_options.values():
        if o["loan_id"] != loan["id"] or o["status"] != "SUSPENDED":
            continue
        o["status"] = "AVAILABLE" if o["exercise_window_end_dt"] >= clock else "EXPIRED"
        touch(o)
    return success(ser_loan(loan))
