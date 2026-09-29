"""Reusable rejection checks, named after their PRD 2.7 precedence position."""

from db import clock, clock_date, db
from errors import ApiError
from services import calc
from services import recompute as rc

TERMINAL_OFFER = ("ACCEPTED", "EXPIRED", "SUPERSEDED", "VOIDED_BY_SUPPRESSION")
TERMINAL_DISPUTE = ("WITHDRAWN", "RESOLVED_UPHELD", "RESOLVED_REJECTED")
TERMINAL_SESSION = ("CLOSED", "CANCELLED")
TERMINAL_BANK_ACCOUNT = ("VERIFIED", "FAILED", "REPLACED")


def invalid_state(message=None):
    raise ApiError("ERR_INVALID_STATE", message)


def already_terminal(message=None):
    raise ApiError("ERR_ALREADY_TERMINAL", message)


# check 7
def require_invoice_not_suppressed(invoice):
    if invoice["dispute_suppressed"]:
        raise ApiError("ERR_INVOICE_DISPUTE_SUPPRESSED")


# check 8
def require_program_open(program):
    if program["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_NOT_OPEN")


# check 9
def require_session_live(session):
    if session["status"] != "LIVE":
        raise ApiError("ERR_SESSION_NOT_LIVE")
    now = clock()
    if now < session["_opens_at"] or now >= session["_closes_at"]:
        raise ApiError("ERR_SESSION_NOT_LIVE")


def session_is_live_now(session):
    now = clock()
    return (
        session["status"] == "LIVE"
        and session["_opens_at"] <= now < session["_closes_at"]
    )


# check 10
def require_offer_not_terminal(offer):
    if offer["status"] in TERMINAL_OFFER:
        already_terminal()


def require_dispute_not_terminal(dispute):
    if dispute["status"] in TERMINAL_DISPUTE:
        already_terminal()


def require_session_not_terminal(session):
    if session["status"] in TERMINAL_SESSION:
        already_terminal()


def require_program_not_terminal(program):
    if program["status"] == "CLOSED":
        already_terminal()


def require_payment_not_terminal(payment):
    if payment["funding_status"] == "VOID":
        already_terminal()
    if payment["settlement_status"] in ("CONFIRMED", "FAILED"):
        already_terminal()


def require_bank_account_not_terminal(account):
    if account["status"] in TERMINAL_BANK_ACCOUNT:
        already_terminal()


# check 12 / 13
def require_invoice_version(invoice, expected):
    if invoice["version"] != expected:
        raise ApiError("ERR_STALE_INVOICE_VERSION")


def require_offer_version(offer, expected):
    if offer["version"] != expected:
        raise ApiError("ERR_STALE_OFFER_VERSION")


# check 14
def require_no_sanctions_hold(supplier):
    if supplier["sanctions_hold"]:
        raise ApiError("ERR_SUPPLIER_SANCTIONS_HOLD")


# check 15
def require_payment_ready(supplier):
    if supplier["onboarding_status"] != "ACTIVE":
        raise ApiError("ERR_SUPPLIER_NOT_PAYMENT_READY")
    if supplier["bank_status"] != "VERIFIED":
        raise ApiError("ERR_SUPPLIER_NOT_PAYMENT_READY")
    if supplier.get("_payment_ready_at") is None:
        raise ApiError("ERR_SUPPLIER_NOT_PAYMENT_READY")


# check 16
def require_acceptance_window_open(offer):
    if clock() >= offer["_acceptance_deadline"]:
        raise ApiError("ERR_ACCEPTANCE_WINDOW_CLOSED")


# check 19
def require_apr_in_program_bounds(program, apr_bps):
    if apr_bps < calc.MIN_PROGRAM_APR_BPS:
        raise ApiError("ERR_APR_OUT_OF_PROGRAM_BOUNDS")
    if apr_bps > program["max_acceptable_apr_bps"]:
        raise ApiError("ERR_APR_OUT_OF_PROGRAM_BOUNDS")
    if program["program_type"] == "FIXED_RATE":
        if program["fixed_apr_bps"] is None or apr_bps != program["fixed_apr_bps"]:
            raise ApiError("ERR_APR_OUT_OF_PROGRAM_BOUNDS")


# check 20
def require_days_early(program, invoice, basis_dt):
    if basis_dt.date() > invoice["_net_due_date"].date():
        raise ApiError("ERR_INSUFFICIENT_DAYS_EARLY")
    days = calc.days_early(invoice["_net_due_date"], basis_dt)
    if days < program["min_days_early"]:
        raise ApiError("ERR_INSUFFICIENT_DAYS_EARLY")
    return days


# check 25
def require_concentration_within_cap(program, invoice):
    projected = rc.projected_concentration_pct(
        program["id"], invoice["supplier_id"], invoice
    )
    if projected > program["_concentration_cap_pct"]:
        raise ApiError("ERR_CONCENTRATION_CAP_EXCEEDED")


# check 28
def require_buyer_credit_headroom(buyer, pre_fee_net, exclude_payment_id=None):
    used = rc.buyer_credit_used(buyer["id"], exclude_payment_id)
    if used + pre_fee_net > buyer["credit_limit_cents"]:
        raise ApiError("ERR_BUYER_CREDIT_LIMIT_EXCEEDED")
