"""Common record helpers, body validation, pagination, serialization."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import store
from errors import err


# ---------------------------------------------------------------------------
# Common-field record construction
# ---------------------------------------------------------------------------
def new_record(with_version=True):
    """Create a fresh record dict with the common fields (PRD §2.4).

    Every entity except ReceiptEvent carries created_at, updated_at, version.
    ReceiptEvent carries only id + created_at (with_version=False).
    """
    now = store.now_iso()
    rec = {
        "id": store.new_id(),
        "created_at": now,
        "_seq": store.next_seq(),  # internal tiebreak; stripped on serialize
    }
    if with_version:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump version + updated_at on a mutation (PRD §2.4)."""
    rec["updated_at"] = store.now_iso()
    rec["version"] = rec.get("version", 0) + 1


def serialize(rec):
    """Strip internal fields before returning to the client."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Body parsing / field validation (ERR_INVALID_REQUEST, priority 4)
# ---------------------------------------------------------------------------
def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def require_str(body, field, allow_empty=False):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    if not allow_empty and not val.strip():
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be non-empty." % field)
    return val


def require_int(body, field, minimum=None, exclusive_min=None):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (field, minimum))
    if exclusive_min is not None and val <= exclusive_min:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be > %s." % (field, exclusive_min))
    return val


def optional_int(body, field, default, minimum=None, exclusive_min=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum=minimum, exclusive_min=exclusive_min)


def require_number(body, field, exclusive_min=None):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)
    if exclusive_min is not None and val <= exclusive_min:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be > %s." % (field, exclusive_min))
    return val


def require_enum(body, field, allowed):
    val = require_str(body, field)
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (field, sorted(allowed)))
    return val


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    return require_enum(body, field, allowed)


def require_bool(body, field):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return val


# ---------------------------------------------------------------------------
# Volume rounding (PRD §2.7): sum first, round once half-up to 2dp.
# ---------------------------------------------------------------------------
def round_volume(total):
    return float(Decimal(str(total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def paginate(records):
    """Sort by created_at ASC (PRD §2.3), apply limit/offset, return page+meta."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(r) for r in page], limit, offset, total


# ---------------------------------------------------------------------------
# Existence lookups (ERR_NOT_FOUND, priority 3)
# ---------------------------------------------------------------------------
def lookup(table, entity_id):
    rec = table.get(entity_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found.")
    return rec


def lookup_fk(table, entity_id, field_name="reference"):
    """Resolve a referenced id from a body; 404 if it does not resolve."""
    if not isinstance(entity_id, str):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a string id." % field_name)
    rec = table.get(entity_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Referenced %s not found." % field_name)
    return rec
