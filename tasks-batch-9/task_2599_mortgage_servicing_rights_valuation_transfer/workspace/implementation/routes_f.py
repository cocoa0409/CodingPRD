"""Notice-of-error cases, hedge positions, hedge effectiveness, logical clock."""
from datetime import timedelta

from flask import Blueprint

import calcs
import cascades
import serial
from core import (CLOCK, DB, READ_HEDGE, READ_XFER, R_BUYER, R_COMPLIANCE, R_HEDGE,
                  authenticate, body_of, f_dec, f_enum, f_id, f_int, f_str, fail,
                  filter_eq, fmt_dt, lookup, new_row, no_body, now_date, now_dt, now_iso,
                  ok, paginate, parse_dt, require_owner, rows, sort_created, touch)

bp = Blueprint("group_f", __name__)

CASE_CATEGORIES = ("ESCROW", "SUSPENSE", "LOSS_MIT", "PAYMENT_MISAPPLIED", "OTHER")
INSTRUMENTS = ("TBA_LONG", "SWAPTION_RECEIVER", "TREASURY_FUTURE_LONG")


def case_chain(case):
    transfer = DB["transfers"][case["servicing_transfer_id"]]
    agreement = DB["agreements"][transfer["purchase_agreement_id"]]
    return transfer, agreement


# ---------------------------------------------------------------- error cases
@bp.post("/msr/servicing-transfers/<xf_id>/error-cases")
def open_error_case(xf_id):
    authenticate(R_COMPLIANCE)
    body = body_of("loan_id", "category", "description")
    loan_id = f_id(body, "loan_id")
    category = f_enum(body, "category", CASE_CATEGORIES)
    description = f_str(body, "description", max_len=500)

    transfer = lookup("transfers", xf_id, "ERR_SERVICING_TRANSFER_NOT_FOUND")
    lookup("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    agreement = DB["agreements"][transfer["purchase_agreement_id"]]
    package = DB["bid_packages"][agreement["bid_package_id"]]
    if not any(line["loan_id"] == loan_id for line in calcs.included_lines(package["id"])):
        fail("ERR_LOAN_NOT_ON_TAPE", "the named loan is not on the awarded tape")

    opened = now_dt()
    row = new_row("error_cases")
    row.update({"servicing_transfer_id": xf_id, "loan_id": loan_id, "category": category,
                "description": description, "status": "OPEN", "opened_at": now_iso(),
                "ack_deadline_at": fmt_dt(opened + timedelta(days=5)),
                "_ack_deadline": opened + timedelta(days=5),
                "resolution_deadline_at": fmt_dt(opened + timedelta(days=30)),
                "_res_deadline": opened + timedelta(days=30),
                "acknowledged_at": None, "resolved_at": None, "_resolved": None,
                "ack_breached": False, "resolution_breached": False,
                "remediation_cents": 0, "reopen_count": 0, "resolution_note": None})
    return ok(serial.ser_error_case(row), 201)


@bp.get("/msr/error-cases/<case_id>")
def get_error_case(case_id):
    authenticate(READ_XFER)
    row = lookup("error_cases", case_id, "ERR_ERROR_CASE_NOT_FOUND")
    return ok(serial.ser_error_case(row))


@bp.get("/msr/error-cases")
def list_error_cases():
    authenticate(READ_XFER)
    items = sort_created(rows("error_cases"))
    items = filter_eq(items, "servicing_transfer_id")
    items = filter_eq(items, "loan_id")
    items = filter_eq(items, "status")
    items = filter_eq(items, "category")
    return paginate(items, serial.ser_error_case)


@bp.post("/msr/error-cases/<case_id>/acknowledge")
def acknowledge_case(case_id):
    user_id, _ = authenticate(R_BUYER)
    no_body()
    case = lookup("error_cases", case_id, "ERR_ERROR_CASE_NOT_FOUND")
    _, agreement = case_chain(case)
    require_owner(user_id, agreement["buyer_id"])
    if case["status"] not in ("OPEN", "REOPENED"):
        fail("ERR_CASE_INVALID_STATE", "only an OPEN or REOPENED case can be acknowledged")

    case["acknowledged_at"] = now_iso()
    if now_dt() > case["_ack_deadline"]:
        case["ack_breached"] = True
    case["status"] = "ACKNOWLEDGED"
    touch(case)
    return ok(serial.ser_error_case(case))


@bp.post("/msr/error-cases/<case_id>/resolve")
def resolve_case(case_id):
    user_id, _ = authenticate(R_BUYER)
    body = body_of("remediation_cents", "resolution_note")
    remediation = f_int(body, "remediation_cents", minimum=0)
    note = f_str(body, "resolution_note", max_len=None)

    case = lookup("error_cases", case_id, "ERR_ERROR_CASE_NOT_FOUND")
    _, agreement = case_chain(case)
    require_owner(user_id, agreement["buyer_id"])
    if case["status"] != "ACKNOWLEDGED":
        fail("ERR_CASE_INVALID_STATE", "only an ACKNOWLEDGED case can be resolved")

    resolved = now_dt()
    case["resolved_at"] = fmt_dt(resolved)
    case["_resolved"] = resolved
    if resolved > case["_res_deadline"]:
        case["resolution_breached"] = True
    case["remediation_cents"] += remediation
    case["resolution_note"] = note
    case["status"] = "RESOLVED"
    touch(case)
    return ok(serial.ser_error_case(case))


@bp.post("/msr/error-cases/<case_id>/reopen")
def reopen_case(case_id):
    authenticate(R_COMPLIANCE)
    body = body_of("reason")
    f_str(body, "reason", max_len=None)

    case = lookup("error_cases", case_id, "ERR_ERROR_CASE_NOT_FOUND")
    if case["status"] not in ("RESOLVED", "ESCALATED"):
        fail("ERR_CASE_INVALID_STATE", "only a RESOLVED or ESCALATED case can be reopened")

    if case["_resolved"] is None or (now_date() - case["_resolved"].date()).days > 60:
        fail("ERR_REOPEN_WINDOW_EXPIRED", "the 60 day reopen window has expired")
    if case["status"] == "ESCALATED":
        fail("ERR_MAX_REOPENS_EXCEEDED", "an ESCALATED case can no longer be reopened")

    if case["reopen_count"] >= 2:
        case["status"] = "ESCALATED"
    else:
        case["reopen_count"] += 1
        case["acknowledged_at"] = None
        case["resolved_at"] = None
        case["status"] = "REOPENED"
    touch(case)
    return ok(serial.ser_error_case(case))


# ---------------------------------------------------------------- hedge book
@bp.post("/msr/hedge-positions")
def open_hedge():
    authenticate(R_HEDGE)
    body = body_of("portfolio_id", "instrument", "notional_cents", "hedge_ratio_pct")
    pf_id = f_id(body, "portfolio_id")
    instrument = f_enum(body, "instrument", INSTRUMENTS)
    notional = f_int(body, "notional_cents", minimum=1)
    ratio = f_dec(body, "hedge_ratio_pct", minimum=1, maximum=200, places=2)

    lookup("portfolios", pf_id, "ERR_PORTFOLIO_NOT_FOUND")
    curve = calcs.require_active_curve()

    row = new_row("hedge_positions")
    row.update({"portfolio_id": pf_id, "instrument": instrument,
                "notional_cents": notional, "hedge_ratio_pct": ratio,
                "entry_base_rate_bps": curve["base_rate_bps"],
                "mark_to_market_cents": 0, "status": "OPEN",
                "close_base_rate_bps": None, "realized_pnl_cents": None, "closed_at": None})
    return ok(serial.ser_hedge(row), 201)


@bp.get("/msr/hedge-positions/<pos_id>")
def get_hedge(pos_id):
    authenticate(READ_HEDGE)
    row = lookup("hedge_positions", pos_id, "ERR_HEDGE_POSITION_NOT_FOUND")
    return ok(serial.ser_hedge(row))


@bp.get("/msr/portfolios/<pf_id>/hedge-positions")
def list_portfolio_hedges(pf_id):
    authenticate(READ_HEDGE)
    lookup("portfolios", pf_id, "ERR_PORTFOLIO_NOT_FOUND")
    items = sort_created([p for p in rows("hedge_positions") if p["portfolio_id"] == pf_id])
    items = filter_eq(items, "status")
    items = filter_eq(items, "instrument")
    return paginate(items, serial.ser_hedge)


@bp.get("/msr/portfolios/<pf_id>/hedge-effectiveness")
def hedge_effectiveness(pf_id):
    authenticate(READ_HEDGE)
    lookup("portfolios", pf_id, "ERR_PORTFOLIO_NOT_FOUND")
    run = calcs.effective_valuation(pf_id)
    msr_value = run["value_cents"] if run is not None else 0
    open_mtm = calcs.open_hedge_mtm(pf_id)
    curve = calcs.active_curve()
    return ok({
        "effective_valuation_run_id": run["id"] if run is not None else None,
        "msr_value_cents": msr_value,
        "open_hedge_mtm_cents": open_mtm,
        "net_hedged_position_cents": msr_value + open_mtm,
        "current_base_rate_bps": curve["base_rate_bps"] if curve is not None else None,
    })


@bp.post("/msr/hedge-positions/<pos_id>/close")
def close_hedge(pos_id):
    authenticate(R_HEDGE)
    no_body()
    position = lookup("hedge_positions", pos_id, "ERR_HEDGE_POSITION_NOT_FOUND")
    if position["status"] != "OPEN":
        fail("ERR_HEDGE_ALREADY_CLOSED", "this hedge position is already closed")
    curve = calcs.require_active_curve()
    cascades.close_hedge_position(position, curve)
    return ok(serial.ser_hedge(position))


# ---------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    body = body_of("to_iso8601")
    raw = body.get("to_iso8601")
    if not isinstance(raw, str) or raw.strip() == "":
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO-8601 UTC timestamp")
    parsed = parse_dt(raw)
    if parsed is None:
        from core import parse_date
        as_date = parse_date(raw)
        if as_date is None:
            fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO-8601 UTC timestamp")
        parsed = now_dt().replace(year=as_date.year, month=as_date.month, day=as_date.day,
                                 hour=0, minute=0, second=0, microsecond=0)
    CLOCK["now"] = parsed
    return ok({"current_utc": now_iso()})
