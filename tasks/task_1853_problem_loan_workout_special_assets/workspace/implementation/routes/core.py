"""Clock, borrowers, loans, workout cases."""
from flask import Blueprint, request

import db
from auth import (
    ROLE_LOAN_ACCOUNTING, ROLE_SYSTEM_ADMIN, ROLE_WORKOUT_OFFICER,
    require_any_role, require_roles,
)
from db import STORE
from errors import (
    ApiError, ERR_LOAN_NOT_PERFORMING, ERR_NOT_FOUND, ERR_REGULATORY_TIMING,
    ERR_SOD,
)
from response import ok, paginate
from services import (
    borrower_out, case_out, cases_of_loan, get_borrower, get_loan, loan_out,
    loans_of_borrower, sorted_rows,
)
from validate import as_datetime, as_enum, as_int, as_str, field, get_body, no_unknown

bp = Blueprint("core", __name__)

ENTRY_TRIGGERS = ("DELINQUENCY_60", "RISK_RATING_DOWNGRADE", "COVENANT_DEFAULT", "MANUAL_REFERRAL")


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles(ROLE_SYSTEM_ADMIN)
    data = get_body()
    no_unknown(data, {"to_iso8601"})
    _, parsed = as_datetime(field(data, "to_iso8601"), "to_iso8601")
    db.set_clock(parsed)
    return ok({"current_utc": db.fmt_clock(db.logical_now())})


# --------------------------------------------------------------------------
# Borrowers
# --------------------------------------------------------------------------

@bp.route("/borrowers", methods=["POST"])
def create_borrower():
    require_roles(ROLE_WORKOUT_OFFICER, ROLE_SYSTEM_ADMIN)
    data = get_body()
    no_unknown(data, {
        "legal_name", "tax_id", "naics_code", "internal_risk_rating",
        "guarantor_name", "guarantor_net_worth_cents",
    })
    legal_name = as_str(field(data, "legal_name"), "legal_name")
    tax_id = as_str(field(data, "tax_id"), "tax_id")
    naics_code = as_str(field(data, "naics_code"), "naics_code")
    rating = as_int(field(data, "internal_risk_rating"), "internal_risk_rating", 1, 10)
    guarantor_name = as_str(field(data, "guarantor_name", ""), "guarantor_name")
    net_worth = as_int(
        field(data, "guarantor_net_worth_cents", 0), "guarantor_net_worth_cents", 0
    )
    if any(b["tax_id"] == tax_id for b in STORE["borrowers"].values()):
        raise ApiError(
            "ERR_BUSINESS_CONSTRAINT", 422,
            "tax_id must be unique across borrowers",
        )
    borrower = db.stamp({
        "id": db.new_id(),
        "legal_name": legal_name,
        "tax_id": tax_id,
        "naics_code": naics_code,
        "internal_risk_rating": rating,
        "guarantor_name": guarantor_name,
        "guarantor_net_worth_cents": net_worth,
        "status": "ACTIVE",
    })
    STORE["borrowers"][borrower["id"]] = borrower
    return ok(borrower_out(borrower), 201)


@bp.route("/borrowers/<borrowerId>", methods=["GET"])
def get_borrower_route(borrowerId):
    require_any_role()
    borrower = get_borrower(borrowerId)
    if borrower is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Borrower not found")
    return ok(borrower_out(borrower))


@bp.route("/borrowers/<borrowerId>/loans", methods=["GET"])
def list_borrower_loans(borrowerId):
    require_any_role()
    borrower = get_borrower(borrowerId)
    if borrower is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Borrower not found")
    rows = [loan_out(l) for l in sorted_rows(loans_of_borrower(borrowerId))]
    return paginate(rows)


# --------------------------------------------------------------------------
# Loans
# --------------------------------------------------------------------------

@bp.route("/loans", methods=["POST"])
def create_loan():
    require_roles(ROLE_WORKOUT_OFFICER, ROLE_SYSTEM_ADMIN)
    data = get_body()
    no_unknown(data, {
        "borrower_id", "loan_number", "original_principal_cents",
        "contractual_rate_bps", "days_past_due",
    })
    borrower_id = as_str(field(data, "borrower_id"), "borrower_id")
    loan_number = as_str(field(data, "loan_number"), "loan_number")
    original = as_int(
        field(data, "original_principal_cents"), "original_principal_cents", 0
    )
    rate = as_int(field(data, "contractual_rate_bps"), "contractual_rate_bps", 0)
    dpd = as_int(field(data, "days_past_due"), "days_past_due", 0)
    if get_borrower(borrower_id) is None:
        raise ApiError(ERR_NOT_FOUND, 404, "borrower_id does not resolve")
    if any(l["loan_number"] == loan_number for l in STORE["loans"].values()):
        raise ApiError(
            "ERR_BUSINESS_CONSTRAINT", 422, "loan_number must be unique across loans"
        )
    loan = db.stamp({
        "id": db.new_id(),
        "borrower_id": borrower_id,
        "loan_number": loan_number,
        "original_principal_cents": original,
        "current_principal_cents": original,
        "contractual_rate_bps": rate,
        "days_past_due": dpd,
        "is_tdr": False,
        "nonaccrual": False,
        "charged_off_principal_cents": 0,
        "status": "PERFORMING",
    })
    STORE["loans"][loan["id"]] = loan
    return ok(loan_out(loan), 201)


@bp.route("/loans", methods=["GET"])
def list_loans():
    require_any_role()
    borrower_id = request.args.get("borrower_id")
    rows = STORE["loans"].values()
    if borrower_id is not None:
        rows = [l for l in rows if l["borrower_id"] == borrower_id]
    return paginate([loan_out(l) for l in sorted_rows(rows)])


@bp.route("/loans/<loanId>", methods=["GET"])
def get_loan_route(loanId):
    require_any_role()
    loan = get_loan(loanId)
    if loan is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Loan not found")
    return ok(loan_out(loan))


@bp.route("/loans/<loanId>/aging-refresh", methods=["POST"])
def aging_refresh(loanId):
    require_roles(ROLE_LOAN_ACCOUNTING, ROLE_SYSTEM_ADMIN)
    loan = get_loan(loanId)
    if loan is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Loan not found")
    data = get_body()
    no_unknown(data, {"days_past_due"})
    dpd = as_int(field(data, "days_past_due"), "days_past_due", 0)
    loan["days_past_due"] = dpd
    loan["nonaccrual"] = dpd >= 90 or any(
        c["status"] == "LEGAL" for c in cases_of_loan(loan["id"])
    )
    db.touch(loan)
    return ok(loan_out(loan))


# --------------------------------------------------------------------------
# Workout cases
# --------------------------------------------------------------------------

@bp.route("/loans/<loanId>/workout-cases", methods=["POST"])
def create_case(loanId):
    user_id, _ = require_roles(ROLE_WORKOUT_OFFICER)
    loan = get_loan(loanId)
    if loan is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Loan not found")
    data = get_body()
    no_unknown(data, {"entry_trigger", "risk_rating_at_entry", "case_officer_id"})
    trigger = as_enum(field(data, "entry_trigger"), "entry_trigger", ENTRY_TRIGGERS)
    rating = as_int(field(data, "risk_rating_at_entry"), "risk_rating_at_entry", 1, 10)
    officer = as_str(field(data, "case_officer_id"), "case_officer_id")
    # state precondition
    if loan["status"] != "PERFORMING":
        raise ApiError(ERR_LOAN_NOT_PERFORMING, 409, "Loan is not PERFORMING")
    # segregation anchor: the case officer must be the acting officer (PRD §3.2)
    if officer != user_id:
        raise ApiError(
            ERR_SOD, 403, "case_officer_id must be the acting officer's X-User-ID"
        )
    # regulatory timing: downgrade entry requires a deteriorated rating
    if trigger == "RISK_RATING_DOWNGRADE" and rating < 6:
        raise ApiError(
            ERR_REGULATORY_TIMING, 422,
            "RISK_RATING_DOWNGRADE requires risk_rating_at_entry >= 6",
        )
    case = db.stamp({
        "id": db.new_id(),
        "loan_id": loan["id"],
        "entry_trigger": trigger,
        "risk_rating_at_entry": rating,
        "case_officer_id": officer,
        "loss_given_default_cents": 0,
        "impairment_reserve_cents": 0,
        "tdr_status": "NOT_EVALUATED",
        "unapplied_cash_cents": 0,
        "resolution_path": "NONE",
        "status": "WATCHLIST",
    })
    STORE["cases"][case["id"]] = case
    loan["status"] = "WATCHLIST"
    db.touch(loan)
    return ok(case_out(case), 201)


@bp.route("/loans/<loanId>/workout-cases", methods=["GET"])
def list_cases(loanId):
    require_any_role()
    if get_loan(loanId) is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Loan not found")
    rows = [case_out(c) for c in sorted_rows(cases_of_loan(loanId))]
    return paginate(rows)


@bp.route("/loans/<loanId>/workout-cases/<caseId>", methods=["GET"])
def get_case_route(loanId, caseId):
    require_any_role()
    if get_loan(loanId) is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Loan not found")
    case = db.STORE["cases"].get(caseId)
    if case is None or case["loan_id"] != loanId:
        raise ApiError(ERR_NOT_FOUND, 404, "Workout case not found")
    return ok(case_out(case))
