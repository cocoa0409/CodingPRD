"""Shared helpers: datetime parsing, round-half-up money math, request body
validation, pagination, filters, and typed foreign-key resolution."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_PAGINATION_PARAMETERS,
    ERR_DEPARTMENT_NOT_FOUND,
    ERR_VENDOR_NOT_FOUND,
    ERR_GRANT_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_REQUISITION_NOT_FOUND,
    ERR_SOLICITATION_NOT_FOUND,
    ERR_QUOTE_NOT_FOUND,
    ERR_PO_NOT_FOUND,
    ERR_RECEIPT_NOT_FOUND,
    ERR_INVOICE_NOT_FOUND,
    ERR_PCARD_NOT_FOUND,
    ERR_TRANSACTION_NOT_FOUND,
    ERR_ELEVATION_NOT_FOUND,
    ERR_SURPLUS_ASSET_NOT_FOUND,
)

NOT_FOUND_BY_COLLECTION = {
    "departments": ERR_DEPARTMENT_NOT_FOUND,
    "vendors": ERR_VENDOR_NOT_FOUND,
    "grants": ERR_GRANT_NOT_FOUND,
    "contracts": ERR_CONTRACT_NOT_FOUND,
    "requisitions": ERR_REQUISITION_NOT_FOUND,
    "solicitations": ERR_SOLICITATION_NOT_FOUND,
    "quotes": ERR_QUOTE_NOT_FOUND,
    "purchase_orders": ERR_PO_NOT_FOUND,
    "receipts": ERR_RECEIPT_NOT_FOUND,
    "invoices": ERR_INVOICE_NOT_FOUND,
    "pcards": ERR_PCARD_NOT_FOUND,
    "pcard_transactions": ERR_TRANSACTION_NOT_FOUND,
    "limit_elevations": ERR_ELEVATION_NOT_FOUND,
    "surplus_assets": ERR_SURPLUS_ASSET_NOT_FOUND,
}


# ---------------------------------------------------------------------------
# Datetimes
# ---------------------------------------------------------------------------

def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime string; accepts trailing Z or offsets."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be an ISO 8601 datetime string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} is not a valid ISO 8601 datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def dt_of(entity, field):
    """Parse a stored datetime string field (input fields echo verbatim)."""
    return parse_dt(entity[field], field)


# ---------------------------------------------------------------------------
# Rounding (round half up via Decimal; never float math for money)
# ---------------------------------------------------------------------------

def dec(value):
    """Decimal from a JSON number without float artifacts."""
    return Decimal(str(value))


def rhu_int(value):
    """round_half_up to whole cents; returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_2dp(value):
    """round_half_up to exactly 2 decimal places; returns float for JSON."""
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def rhu_4dp(value):
    """round_half_up to exactly 4 decimal places; returns float for JSON."""
    return float(Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Request body handling
# ---------------------------------------------------------------------------

def body_json():
    """Return the request JSON body as a dict; empty body -> {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def _check_value(name, value, spec):
    kind = spec["type"]
    if kind == "string":
        if not isinstance(value, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be a string")
        if spec.get("non_empty") and not value.strip():
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be non-empty")
    elif kind == "integer":
        if not _is_int(value):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be an integer")
        if "min" in spec and value < spec["min"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be >= {spec['min']}")
        if spec.get("min_exclusive") is not None and value <= spec["min_exclusive"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be > {spec['min_exclusive']}")
    elif kind == "number":
        if not _is_number(value):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be a number")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be a boolean")
    elif kind == "datetime":
        parse_dt(value, name)
    elif kind == "enum":
        if value not in spec["values"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be one of {sorted(spec['values'])}")
    elif kind == "array":
        if not isinstance(value, list):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be an array")
        item_spec = spec.get("items")
        if item_spec == "string":
            for item in value:
                if not isinstance(item, str):
                    raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} items must be strings")
        elif item_spec == "enum":
            for item in value:
                if item not in spec["values"]:
                    raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} items must be one of {sorted(spec['values'])}")
        elif isinstance(item_spec, dict):
            for item in value:
                if not isinstance(item, dict):
                    raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} items must be objects")
                check_shape(item, item_spec, parent=name)
    else:
        raise AssertionError(f"unknown spec type {kind}")


def check_shape(body, spec, parent=None):
    """Validate declared fields: required presence, per-field type/enum/range.

    Unknown/extra fields are IGNORED (lenient input): client-supplied
    system/computed fields such as total_cents or status are discarded, never
    rejected.
    """
    for name, s in spec.items():
        if s.get("required") and name not in body:
            where = f"{parent}.{name}" if parent else name
            raise ApiError(ERR_INVALID_REQUEST, 400, f"missing required field: {where}")
        if name in body:
            value = body[name]
            # An explicit JSON null on an optional nullable field means "absent".
            if value is None and not s.get("required"):
                continue
            _check_value(f"{parent}.{name}" if parent else name, value, s)


def require_fk(collection, value):
    """Resolve a path/body foreign key to an existing entity (typed 404)."""
    ent = db.get(collection, value)
    if ent is None:
        raise ApiError(
            NOT_FOUND_BY_COLLECTION[collection],
            404,
            f"{collection} id {value} not found",
        )
    return ent


def exist_body_fks(body, mapping):
    """Priority-3 existence check for body foreign keys that are present and
    non-null. mapping: field name -> collection. A present non-string FK is a
    shape error (400)."""
    for field, collection in mapping.items():
        if field in body and body[field] is not None:
            if not isinstance(body[field], str):
                raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be a string id")
            require_fk(collection, body[field])


# ---------------------------------------------------------------------------
# Pagination (limit/offset; PRD 2.3)
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_PAGINATION_PARAMETERS, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_PAGINATION_PARAMETERS, 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_PAGINATION_PARAMETERS, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_PAGINATION_PARAMETERS, 400, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, total, has_more


def apply_filters(items, allowed_filters):
    """Exact-match filters from query params. Unknown params are ignored."""
    result = items
    for field in allowed_filters:
        if field in request.args:
            wanted = request.args.get(field)
            result = [e for e in result if _filter_match(e.get(field), wanted)]
    return result


def _filter_match(value, wanted):
    if value is None:
        return wanted in ("null", "")
    if isinstance(value, bool):
        return wanted.lower() == str(value).lower()
    return str(value) == wanted
