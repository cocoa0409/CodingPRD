"""Shared helpers: body parsing, validation, lookups, pagination, money math."""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
import errors
from errors import err


# ---------------------------------------------------------------------------
# Money / basis-point arithmetic (PRD §2.6: integer cents, half-up rounding).
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal/number to the nearest whole integer, ties going up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    """Round to one decimal place, ties going up (PRD §3.7 loyalty score)."""
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def bps_apply(amount_cents, bps):
    """amount * bps / 10000, rounded half up to a whole cent."""
    return round_half_up(Decimal(amount_cents) * Decimal(bps) / Decimal(10000))


# ---------------------------------------------------------------------------
# Request body parsing.
# ---------------------------------------------------------------------------
def get_body():
    """Parse the JSON body; missing/non-object/malformed -> ERR_VALIDATION (400)."""
    if request.method in ("POST", "PATCH", "PUT"):
        try:
            data = request.get_json(silent=True)
        except Exception:
            raise err(errors.ERR_VALIDATION, "Malformed request body")
        if data is None:
            # Allow a truly empty body for no-input endpoints.
            if request.data and request.data.strip():
                raise err(errors.ERR_VALIDATION, "Malformed request body")
            return {}
        if not isinstance(data, dict):
            raise err(errors.ERR_VALIDATION, "Request body must be a JSON object")
        return data
    return {}


def require_fields(body, *names):
    """Every named field must be present and non-null, else ERR_VALIDATION (400)."""
    for name in names:
        if name not in body or body[name] is None:
            raise err(errors.ERR_VALIDATION, "Missing required field: %s" % name)


def require_int(body, name, *, min_value=None, max_value=None):
    """Validate a present integer field; ERR_VALIDATION (400) on type/range fault."""
    val = body.get(name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_VALIDATION, "Field %s must be an integer" % name)
    if min_value is not None and val < min_value:
        raise err(errors.ERR_VALIDATION, "Field %s must be >= %s" % (name, min_value))
    if max_value is not None and val > max_value:
        raise err(errors.ERR_VALIDATION, "Field %s must be <= %s" % (name, max_value))
    return val


def require_str(body, name):
    val = body.get(name)
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_VALIDATION, "Field %s must be a non-empty string" % name)
    return val


def require_enum(body, name, allowed):
    val = body.get(name)
    if val not in allowed:
        raise err(errors.ERR_VALIDATION,
                  "Field %s must be one of %s" % (name, sorted(allowed)))
    return val


# ---------------------------------------------------------------------------
# Existence lookups (PRD §2.5: ERR_NOT_FOUND 404, left-to-right).
# ---------------------------------------------------------------------------
def lookup(table, resource_id):
    """Fetch a record by id or raise ERR_NOT_FOUND (404)."""
    rec = table.get(resource_id)
    if rec is None:
        raise err(errors.ERR_NOT_FOUND, "Resource %s not found" % resource_id)
    return rec


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3: limit default 10 / min 1 / max 100; offset default 0 min 0).
# ---------------------------------------------------------------------------
def paginate_params():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise err(errors.ERR_VALIDATION, "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise err(errors.ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def list_collection(table, predicate=None):
    """Filter + sort-by-created (asc) + paginate a table (PRD §2.3)."""
    limit, offset = paginate_params()
    items = list(table.values())
    if predicate is not None:
        items = [r for r in items if predicate(r)]
    items.sort(key=lambda r: r["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total
