"""Dividend / DRIP endpoints (PRD §3.7, §4)."""
from decimal import Decimal

from flask import Blueprint, request

import constants
import errors
from db import db, created_ts
from middleware import get_identity, require_role, require_account_owner
from models import _base_full, dividend_dict, touch
from response import object_response, array_response
from routes.common import (get_json_body, get_account, get_dividend, paginate,
                           page_slice)
from money import round_half_up, truncate_shares, shares_str
from services.account import recompute_account, auto_meet_margin_calls
from services.position import open_lot, recompute_position
from timeutil import parse_iso, add_calendar_days, iso

bp = Blueprint("dividends", __name__)


@bp.post("/dividends")
def announce_dividend():
    _, role = get_identity()
    require_role(role, {"ClearingSystem"})
    body = get_json_body()

    account_id = body.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise errors.err(errors.ERR_INVALID_REQUEST, "account_id is required")
    acct = get_account(account_id)

    position_id = body.get("position_id")
    if not isinstance(position_id, str) or not position_id:
        raise errors.err(errors.ERR_INVALID_REQUEST, "position_id is required")
    pos = db.positions.get(position_id)
    if pos is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Position not found")

    rate = body.get("rate_per_share_cents")
    if not isinstance(rate, int) or isinstance(rate, bool) or rate <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "rate_per_share_cents must be positive")

    ex_date_raw = body.get("ex_date")
    if not isinstance(ex_date_raw, str) or not ex_date_raw:
        raise errors.err(errors.ERR_INVALID_REQUEST, "ex_date is required")
    try:
        ex_date = parse_iso(ex_date_raw)
    except (ValueError, TypeError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "ex_date is not a valid instant")

    window_end = add_calendar_days(ex_date, constants.DIVIDEND_WINDOW_DAYS)

    # window overlap vs non-terminal (ANNOUNCED/PAID) dividends of same position
    # half-open [ex_date, window_end): overlap iff new.ex < d.window_end AND d.ex < new.window_end
    for d in db.dividends.values():
        if d["position_id"] != position_id:
            continue
        if d["status"] not in ("ANNOUNCED", "PAID"):
            continue
        d_ex = parse_iso(d["ex_date"])
        d_end = parse_iso(d["window_end"])
        if ex_date < d_end and d_ex < window_end:
            raise errors.err(errors.ERR_DIVIDEND_WINDOW_OVERLAP,
                             "Dividend window overlaps an existing non-terminal dividend")

    record_quantity = pos["quantity"]
    gross_amount = round_half_up(Decimal(str(record_quantity)) * Decimal(rate))

    rec = _base_full()
    rec.update({
        "account_id": account_id,
        "position_id": position_id,
        "rate_per_share_cents": rate,
        "ex_date": iso(ex_date),
        "window_end": iso(window_end),
        "record_quantity": shares_str(record_quantity),
        "gross_amount_cents": gross_amount,
        "reinvest_quantity": 0.0,
        "residual_cash_cents": 0,
        "status": "ANNOUNCED",
    })
    db.dividends[rec["id"]] = rec
    return object_response(dividend_dict(rec), 201)


@bp.get("/accounts/<account_id>/dividends")
def list_dividends(account_id):
    user_id, role = get_identity()
    require_role(role, {"AccountHolder", "ClearingSystem", "ComplianceOfficer"})
    acct = get_account(account_id)
    require_account_owner(role, user_id, acct["id"])

    status = request.args.get("status")
    items = [d for d in db.dividends.values() if d["account_id"] == account_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]

    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return array_response([dividend_dict(d) for d in page], limit, offset, total)


@bp.post("/dividends/<dividend_id>/pay")
def pay_dividend(dividend_id):
    _, role = get_identity()
    require_role(role, {"ClearingSystem"})
    d = get_dividend(dividend_id)

    if d["status"] != "ANNOUNCED" or d["record_quantity"] <= 0:
        raise errors.err(errors.ERR_DIVIDEND_NOT_PAYABLE, "Dividend not payable")

    acct = db.accounts.get(d["account_id"])
    acct["settled_cash_cents"] += d["gross_amount_cents"]
    d["status"] = "PAID"
    touch(d)
    recompute_account(acct)
    auto_meet_margin_calls(acct["id"])
    touch(acct)
    return object_response(dividend_dict(d), 200)


@bp.post("/dividends/<dividend_id>/reinvest")
def reinvest_dividend(dividend_id):
    _, role = get_identity()
    require_role(role, {"ClearingSystem"})
    d = get_dividend(dividend_id)

    if d["status"] != "PAID":
        raise errors.err(errors.ERR_DIVIDEND_NOT_PAYABLE, "Dividend not in PAID status")

    pos = db.positions.get(d["position_id"])
    if pos is None or not pos["drip_enabled"]:
        raise errors.err(errors.ERR_DRIP_NOT_ENABLED, "DRIP is not enabled for this position")

    sec = db.securities.get(pos["security_id"])
    last_price = sec["last_price_cents"] if sec else 0

    # pinned rounding order (PRD §3.7)
    gross = d["gross_amount_cents"]
    if last_price <= 0:
        raise errors.err(errors.ERR_DRIP_BELOW_MINIMUM, "Reinvest yields zero shares")
    reinvest_qty = truncate_shares(Decimal(gross) / Decimal(last_price))
    if reinvest_qty <= 0:
        raise errors.err(errors.ERR_DRIP_BELOW_MINIMUM, "Reinvest yields zero shares")

    spent = round_half_up(Decimal(str(reinvest_qty)) * Decimal(last_price))
    residual = gross - spent

    acct = db.accounts.get(d["account_id"])
    acct["settled_cash_cents"] -= spent  # gross - residual

    # open a new lot for the reinvested shares (cost = spent)
    fill_stub = {"id": None}
    lot = open_lot(pos["id"], fill_stub, reinvest_qty, spent)
    recompute_position(pos)
    touch(pos)

    d["reinvest_quantity"] = shares_str(reinvest_qty)
    d["residual_cash_cents"] = residual
    d["status"] = "REINVESTED"
    touch(d)

    recompute_account(acct)
    auto_meet_margin_calls(acct["id"])
    touch(acct)
    return object_response(dividend_dict(d), 200)


@bp.post("/dividends/<dividend_id>/reverse")
def reverse_dividend(dividend_id):
    _, role = get_identity()
    require_role(role, {"ClearingSystem"})
    d = get_dividend(dividend_id)

    if d["status"] != "PAID":
        raise errors.err(errors.ERR_DIVIDEND_NOT_PAYABLE, "Dividend not in PAID status")

    acct = db.accounts.get(d["account_id"])
    acct["settled_cash_cents"] -= d["gross_amount_cents"]
    d["status"] = "REVERSED"
    touch(d)
    recompute_account(acct)
    auto_meet_margin_calls(acct["id"])
    touch(acct)
    return object_response(dividend_dict(d), 200)
