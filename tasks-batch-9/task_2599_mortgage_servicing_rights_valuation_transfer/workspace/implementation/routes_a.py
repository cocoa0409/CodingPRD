"""Counterparties, servicing portfolios, loans."""
import re

from flask import Blueprint, request

import calcs
import serial
from core import (ALL_ROLES, DB, D, READ_CP, READ_LOAN, READ_NOTICE, READ_PF,
                  R_ADMIN, R_SELLER, authenticate, body_of, f_dec, f_enum, f_id, f_int,
                  f_str, f_str_list, fail, filter_eq, lookup, new_row, no_body, now_iso, ok,
                  paginate, require_owner, rows, sort_created, touch)

bp = Blueprint("group_a", __name__)

AGENCIES = ("FNMA", "FHLMC", "GNMA")
DQ_BUCKETS = ("CURRENT", "DQ_30_59", "DQ_60_89", "DQ_90_PLUS", "FORECLOSURE")
LOSS_MIT = ("NONE", "TRIAL_MOD", "PERMANENT_MOD", "FORBEARANCE")
_STATE_RE = re.compile(r"^[A-Z]{2}$")


# ---------------------------------------------------------------- counterparties
@bp.post("/msr/counterparties")
def create_counterparty():
    authenticate(R_ADMIN)
    body = body_of("legal_name", "role_type", "net_worth_cents", "servicer_rating",
                   "agency_approvals")
    legal_name = f_str(body, "legal_name", max_len=120)
    role_type = f_enum(body, "role_type", ("SELLER", "BUYER"))
    net_worth = f_int(body, "net_worth_cents", minimum=0)
    rating = f_enum(body, "servicer_rating", ("TIER_1", "TIER_2", "TIER_3"))
    approvals = f_str_list(body, "agency_approvals", AGENCIES, required=False, default=[])

    row = new_row("counterparties")
    row.update({"legal_name": legal_name, "role_type": role_type,
                "net_worth_cents": net_worth, "servicer_rating": rating,
                "agency_approvals": approvals, "status": "ACTIVE", "suspended_at": None})
    return ok(serial.ser_counterparty(row), 201)


@bp.get("/msr/counterparties/<cp_id>")
def get_counterparty(cp_id):
    authenticate(ALL_ROLES)
    row = lookup("counterparties", cp_id, "ERR_COUNTERPARTY_NOT_FOUND")
    return ok(serial.ser_counterparty(row))


@bp.get("/msr/counterparties")
def list_counterparties():
    authenticate(READ_CP)
    items = sort_created(rows("counterparties"))
    items = filter_eq(items, "role_type")
    items = filter_eq(items, "status")
    return paginate(items, serial.ser_counterparty)


@bp.post("/msr/counterparties/<cp_id>/suspend")
def suspend_counterparty(cp_id):
    authenticate(R_ADMIN)
    no_body()
    row = lookup("counterparties", cp_id, "ERR_COUNTERPARTY_NOT_FOUND")
    row["status"] = "SUSPENDED"
    row["suspended_at"] = now_iso()
    touch(row)
    return ok(serial.ser_counterparty(row))


@bp.get("/msr/counterparties/<cp_id>/risk-score")
def counterparty_risk_score(cp_id):
    authenticate(READ_CP)
    variant = request.args.get("variant", "PRE_AWARD")
    if variant not in ("PRE_AWARD", "POST_TRANSFER"):
        fail("ERR_INVALID_REQUEST", "variant must be PRE_AWARD or POST_TRANSFER")
    row = lookup("counterparties", cp_id, "ERR_COUNTERPARTY_NOT_FOUND")
    return ok(calcs.risk_score(row, variant))


# ---------------------------------------------------------------- portfolios
@bp.post("/msr/portfolios")
def create_portfolio():
    user_id, role = authenticate(("SellerServicer", "PlatformAdmin"))
    body = body_of("seller_id", "portfolio_name", "agency_type")
    seller_id = f_id(body, "seller_id")
    name = f_str(body, "portfolio_name", max_len=120)
    agency = f_enum(body, "agency_type", AGENCIES)

    seller = lookup("counterparties", seller_id, "ERR_COUNTERPARTY_NOT_FOUND")
    if role == "SellerServicer":
        require_owner(user_id, seller["id"])
    if seller["role_type"] != "SELLER":
        fail("ERR_COUNTERPARTY_ROLE_MISMATCH", "named counterparty is not a SELLER")

    row = new_row("portfolios")
    row.update({"seller_id": seller_id, "portfolio_name": name, "agency_type": agency,
                "status": "DRAFT", "tape_locked_at": None,
                "frozen_total_upb_cents": None, "frozen_custodial_cents": None})
    return ok(serial.ser_portfolio(row), 201)


@bp.get("/msr/portfolios/<pf_id>")
def get_portfolio(pf_id):
    authenticate(READ_PF)
    row = lookup("portfolios", pf_id, "ERR_PORTFOLIO_NOT_FOUND")
    return ok(serial.ser_portfolio(row))


@bp.get("/msr/portfolios")
def list_portfolios():
    authenticate(READ_PF)
    items = sort_created(rows("portfolios"))
    items = filter_eq(items, "seller_id")
    items = filter_eq(items, "status")
    items = filter_eq(items, "agency_type")
    freshness = request.args.get("valuation_freshness")
    if freshness is not None:
        items = [p for p in items if calcs.valuation_freshness(p["id"]) == freshness]
    return paginate(items, serial.ser_portfolio)


@bp.post("/msr/portfolios/<pf_id>/loans")
def create_loan(pf_id):
    user_id, _ = authenticate(R_SELLER)
    body = body_of("loan_number", "upb_cents", "note_rate_pct", "servicing_fee_bps",
                   "escrow_balance_cents", "suspense_balance_cents", "delinquency_bucket",
                   "loss_mit_status", "state_code")
    loan_number = f_str(body, "loan_number", max_len=32)
    upb = f_int(body, "upb_cents", minimum=1)
    note_rate = f_dec(body, "note_rate_pct", minimum=0, exclusive_min=True,
                      maximum=25, places=4)
    fee_bps = f_int(body, "servicing_fee_bps", minimum=1, maximum=100)
    escrow = f_int(body, "escrow_balance_cents", required=False, minimum=0, default=0)
    suspense = f_int(body, "suspense_balance_cents", required=False, minimum=0, default=0)
    bucket = f_enum(body, "delinquency_bucket", DQ_BUCKETS, required=False, default="CURRENT")
    loss_mit = f_enum(body, "loss_mit_status", LOSS_MIT, required=False, default="NONE")
    state_code = f_str(body, "state_code", min_len=2, max_len=2)
    if not _STATE_RE.match(state_code):
        fail("ERR_INVALID_REQUEST", "state_code must be exactly two uppercase letters")

    portfolio = lookup("portfolios", pf_id, "ERR_PORTFOLIO_NOT_FOUND")
    require_owner(user_id, portfolio["seller_id"])
    if portfolio["status"] != "DRAFT":
        fail("ERR_TAPE_LOCKED", "loans may only be added while the portfolio is DRAFT")
    for existing in calcs.portfolio_loans(pf_id):
        if existing["loan_number"] == loan_number:
            fail("ERR_DUPLICATE_LOAN_NUMBER",
                 "loan_number is already present on this portfolio")

    row = new_row("loans")
    row.update({"portfolio_id": pf_id, "loan_number": loan_number, "upb_cents": upb,
                "note_rate_pct": note_rate, "servicing_fee_bps": fee_bps,
                "escrow_balance_cents": escrow, "suspense_balance_cents": suspense,
                "delinquency_bucket": bucket, "loss_mit_status": loss_mit,
                "state_code": state_code, "status": "ACTIVE",
                "escrow_balance_at_mapping_cents": None,
                "suspense_balance_at_mapping_cents": None, "transferred_at": None})
    touch(portfolio)
    return ok(serial.ser_loan(row), 201)


@bp.get("/msr/portfolios/<pf_id>/loans")
def list_portfolio_loans(pf_id):
    authenticate(READ_LOAN)
    lookup("portfolios", pf_id, "ERR_PORTFOLIO_NOT_FOUND")
    items = calcs.portfolio_loans(pf_id)
    items = filter_eq(items, "status")
    items = filter_eq(items, "delinquency_bucket")
    return paginate(items, serial.ser_loan)


@bp.post("/msr/portfolios/<pf_id>/lock-tape")
def lock_tape(pf_id):
    user_id, _ = authenticate(R_SELLER)
    no_body()
    portfolio = lookup("portfolios", pf_id, "ERR_PORTFOLIO_NOT_FOUND")
    require_owner(user_id, portfolio["seller_id"])
    if portfolio["status"] != "DRAFT":
        fail("ERR_TAPE_LOCKED", "the tape has already been locked")
    if calcs.portfolio_loan_count(pf_id) < 1:
        fail("ERR_TAPE_EMPTY", "a portfolio must hold at least one loan to lock its tape")
    portfolio["status"] = "TAPE_LOCKED"
    portfolio["tape_locked_at"] = now_iso()
    portfolio["frozen_total_upb_cents"] = calcs.portfolio_total_upb(pf_id)
    portfolio["frozen_custodial_cents"] = calcs.custodial_funds_total(pf_id)
    touch(portfolio)
    return ok(serial.ser_portfolio(portfolio))


# ---------------------------------------------------------------- loans
@bp.get("/msr/loans/<loan_id>")
def get_loan(loan_id):
    authenticate(READ_LOAN)
    row = lookup("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    return ok(serial.ser_loan(row))


@bp.get("/msr/loans/<loan_id>/tape-lines")
def list_loan_tape_lines(loan_id):
    authenticate(READ_LOAN)
    lookup("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    items = sort_created([t for t in rows("tape_lines") if t["loan_id"] == loan_id])
    included = request.args.get("included")
    if included is not None:
        want = str(included).strip().lower()
        if want not in ("true", "false"):
            fail("ERR_INVALID_REQUEST", "included filter must be true or false")
        items = [t for t in items if t["included"] == (want == "true")]
    return paginate(items, serial.ser_tape_line)


@bp.get("/msr/loans/<loan_id>/notices")
def list_loan_notices(loan_id):
    authenticate(READ_NOTICE)
    lookup("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    items = sort_created([n for n in rows("notices") if n["loan_id"] == loan_id])
    items = filter_eq(items, "notice_type")
    items = filter_eq(items, "compliance_status")
    return paginate(items, serial.ser_notice)
