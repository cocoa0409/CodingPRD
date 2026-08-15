"""Charge-off and recovery ledger event routes (PRD §3.8)."""
from flask import Blueprint

import db
from auth import (
    ROLE_CREDIT_COMMITTEE, ROLE_LEGAL_COUNSEL, ROLE_LOAN_ACCOUNTING,
    ROLE_PORTFOLIO_ANALYST, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_SYSTEM_ADMIN,
    ROLE_WORKOUT_OFFICER, require_roles,
)
from db import STORE
from errors import (
    ApiError, ERR_CASE_NOT_LIQUIDATABLE, ERR_COLLATERAL_NOT_PLEDGED,
    ERR_FISCAL_LIMIT, ERR_NOT_FOUND,
)
from response import ok, paginate
from services import (
    book_charge_off, book_recovery, charge_off_out, get_collateral, get_loan,
    recovery_out, sorted_rows,
)
from validate import as_enum, as_int, as_str, field, get_body, no_unknown

bp = Blueprint("ledger", __name__)

REASON_CODES = ("CONFIRMED_LOSS", "STATUTORY", "PARTIAL_IMPAIRMENT")
RECOVERY_SOURCES = (
    "GUARANTOR_SETTLEMENT", "COLLATERAL_LIQUIDATION", "BORROWER_CURE",
    "NOTE_SALE_PROCEEDS",
)
ALLOCATION_MODES = ("CHRONOLOGICAL", "WATERFALL")
CHARGE_OFF_READERS = (
    ROLE_WORKOUT_OFFICER, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_CREDIT_COMMITTEE,
    ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST, ROLE_SYSTEM_ADMIN,
)
RECOVERY_READERS = (
    ROLE_WORKOUT_OFFICER, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_CREDIT_COMMITTEE,
    ROLE_LEGAL_COUNSEL, ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST,
    ROLE_SYSTEM_ADMIN,
)


def resolve(loanId, caseId):
    loan = get_loan(loanId)
    if loan is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Loan not found")
    case = STORE["cases"].get(caseId)
    if case is None or case["loan_id"] != loanId:
        raise ApiError(ERR_NOT_FOUND, 404, "Workout case not found")
    return loan, case


# --------------------------------------------------------------------------
# Charge-offs
# --------------------------------------------------------------------------

@bp.route("/loans/<loanId>/workout-cases/<caseId>/charge-offs", methods=["POST"])
def create_charge_off(loanId, caseId):
    require_roles(ROLE_LOAN_ACCOUNTING)
    loan, case = resolve(loanId, caseId)
    data = get_body()
    no_unknown(data, {"amount_cents", "reason_code"})
    amount = as_int(field(data, "amount_cents"), "amount_cents")
    reason = as_enum(field(data, "reason_code"), "reason_code", REASON_CODES)
    # fiscal (priority 9): positive and no more than the outstanding principal
    if amount <= 0 or amount > loan["current_principal_cents"]:
        raise ApiError(
            ERR_FISCAL_LIMIT, 422,
            "amount_cents must be > 0 and <= current_principal_cents",
        )
    event = book_charge_off(loan, case, amount, reason)
    return ok(charge_off_out(event), 201)


@bp.route("/loans/<loanId>/workout-cases/<caseId>/charge-offs", methods=["GET"])
def list_charge_offs(loanId, caseId):
    require_roles(*CHARGE_OFF_READERS)
    resolve(loanId, caseId)
    rows = [
        charge_off_out(e)
        for e in sorted_rows(
            [e for e in STORE["charge_offs"].values() if e["case_id"] == caseId]
        )
    ]
    return paginate(rows)


# --------------------------------------------------------------------------
# Recoveries
# --------------------------------------------------------------------------

@bp.route("/loans/<loanId>/workout-cases/<caseId>/recoveries", methods=["POST"])
def create_recovery(loanId, caseId):
    require_roles(ROLE_LOAN_ACCOUNTING)
    loan, case = resolve(loanId, caseId)
    data = get_body()
    no_unknown(data, {"amount_cents", "recovery_source", "allocation_mode", "collateral_id"})
    amount = as_int(field(data, "amount_cents"), "amount_cents")
    source = as_enum(field(data, "recovery_source"), "recovery_source", RECOVERY_SOURCES)
    mode = as_enum(field(data, "allocation_mode"), "allocation_mode", ALLOCATION_MODES)

    item = None
    if source == "COLLATERAL_LIQUIDATION":
        collateral_id = as_str(field(data, "collateral_id"), "collateral_id")
        # body reference existence (priority 3)
        item = get_collateral(collateral_id)
        if item is None or item["loan_id"] != loanId:
            raise ApiError(ERR_NOT_FOUND, 404, "collateral_id does not resolve")
        # state (priority 4): liquidation only while LEGAL or RESOLUTION
        if case["status"] not in ("LEGAL", "RESOLUTION"):
            raise ApiError(
                ERR_CASE_NOT_LIQUIDATABLE, 409,
                "Collateral liquidation requires the case in LEGAL or RESOLUTION",
            )
        if item["status"] != "PLEDGED":
            raise ApiError(
                ERR_COLLATERAL_NOT_PLEDGED, 409, "Collateral item is not PLEDGED"
            )
    elif "collateral_id" in data:
        as_str(data["collateral_id"], "collateral_id")

    # fiscal (priority 9): recovery amount must be positive
    if amount <= 0:
        raise ApiError(
            ERR_FISCAL_LIMIT, 422, "amount_cents must be greater than zero"
        )

    # a liquidation removes the item from the cover base before LGD recompute
    if item is not None:
        item["status"] = "LIQUIDATED"
        db.touch(item)
    event = book_recovery(loan, case, amount, source, mode)
    return ok(recovery_out(event), 201)


@bp.route("/loans/<loanId>/workout-cases/<caseId>/recoveries", methods=["GET"])
def list_recoveries(loanId, caseId):
    require_roles(*RECOVERY_READERS)
    resolve(loanId, caseId)
    rows = [
        recovery_out(e)
        for e in sorted_rows(
            [e for e in STORE["recoveries"].values() if e["case_id"] == caseId]
        )
    ]
    return paginate(rows)
