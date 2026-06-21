"""Shared service helpers: lookups, request parsing, derived-field recompute,
ledger posting, quote lazy-expiry, and pagination.
"""
from flask import request

import db
from clock import logical_now, parse_iso
from errors import err

REGIONS = {"NORTH", "SOUTH", "EAST", "WEST"}
ADDON_CODES = {"GUTTER", "SCREEN", "SOFT_WASH"}
SKILL_CODES = {"SOFT_WASH", "HIGH_RISE"}


# --------------------------------------------------------------------------
# Request body parsing / validation (ERR_INVALID_REQUEST, 400)
# --------------------------------------------------------------------------
def body():
    """Return the parsed JSON body as a dict (empty dict when absent).

    Malformed JSON -> ERR_INVALID_REQUEST.
    """
    if request.content_length in (None, 0) and not (request.data or b"").strip():
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # Empty body is allowed for parameterless transitions.
        if not (request.data or b"").strip():
            return {}
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def require(data, field):
    if field not in data or data[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return data[field]


def req_str(data, field):
    val = require(data, field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return val


def req_int(data, field):
    val = require(data, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return val


def req_number(data, field):
    val = require(data, field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    return val


def req_enum(data, field, allowed):
    val = req_str(data, field)
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))
    return val


def opt_enum_list(data, field, allowed):
    if field not in data or data[field] is None:
        return []
    val = data[field]
    if not isinstance(val, list):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a list" % field)
    out = []
    for item in val:
        if not isinstance(item, str) or item not in allowed:
            raise err("ERR_INVALID_REQUEST", "Field %s contains an invalid value" % field)
        out.append(item)
    return out


# --------------------------------------------------------------------------
# Existence lookups (ERR_NOT_FOUND, 404)
# --------------------------------------------------------------------------
def get_or_404(collection, rid):
    if not isinstance(rid, str):
        raise err("ERR_NOT_FOUND", "Resource not found")
    rec = collection.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
def pagination_params():
    """Parse limit/offset query params. Defaults limit=10 (1..100), offset=0.

    Out-of-range or malformed values -> ERR_INVALID_REQUEST.
    """
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (creation order via _seq) and slice."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# --------------------------------------------------------------------------
# Ledger + derived account balances (PRD §2.7)
# --------------------------------------------------------------------------
def post_ledger(account_id, source_type, source_id, signed_amount_cents):
    db.new_record(
        db.ledger_entries,
        {
            "account_id": account_id,
            "source_type": source_type,
            "source_id": source_id,
            "signed_amount_cents": signed_amount_cents,
        },
        leaner=True,
    )
    recompute_account(account_id)


def recompute_account(account_id):
    """Recompute balance_cents and deposit_held_cents for an account and bump
    its version/updated_at (PRD §2.4 / §2.7)."""
    acct = db.accounts.get(account_id)
    if acct is None:
        return
    balance = sum(
        le["signed_amount_cents"]
        for le in db.ledger_entries.values()
        if le["account_id"] == account_id
    )
    held = sum(
        d["amount_cents"]
        for d in db.deposits.values()
        if d["account_id"] == account_id and d["status"] == "HELD"
    )
    if acct.get("balance_cents") != balance or acct.get("deposit_held_cents") != held:
        acct["balance_cents"] = balance
        acct["deposit_held_cents"] = held
        db.touch(acct)


# --------------------------------------------------------------------------
# Route booked_minutes (PRD §2.8)
# --------------------------------------------------------------------------
_BOOKED_STATUSES = {"SCHEDULED", "DISPATCHED", "IN_PROGRESS", "COMPLETED"}


def recompute_route_minutes(route):
    """Recompute booked_minutes for a route from its committed visits and bump
    version/updated_at when the value changes (PRD §2.4 / §2.8)."""
    total = sum(
        v["duration_minutes"]
        for v in db.visits.values()
        if v.get("route_id") == route["id"] and v["schedule_status"] in _BOOKED_STATUSES
    )
    if route.get("booked_minutes") != total:
        route["booked_minutes"] = total
        db.touch(route)


# --------------------------------------------------------------------------
# Quote lazy expiry (PRD §2.10)
# --------------------------------------------------------------------------
def apply_quote_expiry(quote):
    """Lazily transition a DRAFT/SENT quote to EXPIRED when the logical clock
    has reached or passed valid_until."""
    if quote["status"] in ("DRAFT", "SENT"):
        valid_until = parse_iso(quote["valid_until"])
        if logical_now() >= valid_until:
            quote["status"] = "EXPIRED"
            db.touch(quote)
    return quote
