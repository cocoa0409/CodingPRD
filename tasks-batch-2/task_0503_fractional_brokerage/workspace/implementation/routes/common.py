"""Shared route helpers: body parsing, pagination, existence lookups.

Validation ordering (PRD §2.7): auth -> authz -> existence -> well-formedness
-> OCC -> state -> business rules. Routes call these in that order."""
from flask import request

import errors
from db import db


def get_json_body():
    """Parse the JSON body; tolerate empty body as {}."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return data


def paginate(query_args=None):
    """Parse limit/offset (PRD §2.3). Defaults limit=10 (min1,max100), offset=0(min0).
    Out-of-range values are clamped into range."""
    args = query_args if query_args is not None else request.args
    limit = _parse_int(args.get("limit"), 10)
    offset = _parse_int(args.get("offset"), 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_int(val, default):
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def page_slice(items, limit, offset):
    """Sort by creation order then slice. Returns (page_items, total_count)."""
    ordered = sorted(items, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    return ordered[offset:offset + limit], total


def require_found(record):
    if record is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    return record


def get_account(account_id):
    return require_found(db.accounts.get(account_id))


def get_security(security_id):
    return require_found(db.securities.get(security_id))


def get_order(order_id):
    return require_found(db.orders.get(order_id))


def get_position(position_id):
    return require_found(db.positions.get(position_id))


def get_deposit(deposit_id):
    return require_found(db.deposits.get(deposit_id))


def get_settlement(settlement_id):
    return require_found(db.settlements.get(settlement_id))


def get_dividend(dividend_id):
    return require_found(db.dividends.get(dividend_id))


def get_options_approval(oa_id):
    return require_found(db.options_approvals.get(oa_id))


def get_margin_call(mc_id):
    return require_found(db.margin_calls.get(mc_id))
