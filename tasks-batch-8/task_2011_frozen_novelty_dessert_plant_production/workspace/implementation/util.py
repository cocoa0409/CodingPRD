"""Shared helpers: datetime/date parsing, request shape validation,
foreign-key resolution, pagination, filters."""

from datetime import datetime, date, timezone

from flask import request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
)


# ---------------------------------------------------------------------------
# Datetimes and dates
# ---------------------------------------------------------------------------

def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime string; accepts trailing Z or offsets."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError(
            ERR_INVALID_REQUEST, 400, f"{field} must be an ISO 8601 datetime string"
        )
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, f"{field} is not a valid ISO 8601 datetime"
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value, field="date"):
    """Parse an ISO 8601 date string (YYYY-MM-DD)."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError(
            ERR_INVALID_REQUEST, 400, f"{field} must be an ISO 8601 date string"
        )
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, f"{field} is not a valid ISO 8601 date"
        )


def dt_of(entity, field):
    """Parse a stored datetime string field."""
    return parse_dt(entity[field], field)


def date_of(entity, field):
    return parse_date(entity[field], field)


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
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_value(name, value, spec):
    kind = spec["type"]
    if kind == "string":
        if not isinstance(value, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be a string")
    elif kind == "integer":
        if not _is_int(value):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be an integer")
        if "min" in spec and value < spec["min"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be >= {spec['min']}")
        if "max" in spec and value > spec["max"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be <= {spec['max']}")
    elif kind == "number":
        if not _is_number(value):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be a number")
        if "min" in spec:
            if spec.get("min_exclusive"):
                bad = not (value > spec["min"])
            else:
                bad = not (value >= spec["min"])
            if bad:
                raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} is out of range")
        if "max" in spec and value > spec["max"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} is out of range")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be a boolean")
    elif kind == "datetime":
        parse_dt(value, name)
    elif kind == "date":
        parse_date(value, name)
    elif kind == "enum":
        if value not in spec["values"]:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                f"{name} must be one of {sorted(spec['values'])}",
            )
    elif kind == "str_list":
        if not isinstance(value, list) or any(not isinstance(i, str) for i in value):
            raise ApiError(
                ERR_INVALID_REQUEST, 400, f"{name} must be an array of strings"
            )
        if "values" in spec:
            bad = [i for i in value if i not in spec["values"]]
            if bad:
                raise ApiError(
                    ERR_INVALID_REQUEST,
                    400,
                    f"{name} entries must be within {sorted(spec['values'])}",
                )
    elif kind == "obj_list":
        if not isinstance(value, list):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be an array")
        item_spec = spec.get("items", {})
        for item in value:
            if not isinstance(item, dict):
                raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} items must be objects")
            check_shape(item, item_spec, parent=name)
    else:
        raise AssertionError(f"unknown spec type {kind}")


def check_shape(body, spec, parent=None):
    """Priority-5 shape validation: unknown fields rejected, required fields
    present, per-field type/enum/range checks. Raises ERR_INVALID_REQUEST."""
    for key in body:
        if key not in spec:
            where = f"{parent}.{key}" if parent else key
            raise ApiError(ERR_INVALID_REQUEST, 400, f"unknown field: {where}")
    for name, s in spec.items():
        if s.get("required") and name not in body:
            where = f"{parent}.{name}" if parent else name
            raise ApiError(ERR_INVALID_REQUEST, 400, f"missing required field: {where}")
        if name in body:
            value = body[name]
            # An explicit JSON null on an optional field means "absent".
            if value is None and not s.get("required"):
                continue
            _check_value(f"{parent}.{name}" if parent else name, value, s)


# ---------------------------------------------------------------------------
# Foreign keys and path parameters
# ---------------------------------------------------------------------------

def path_entity(collection, ent_id, what=None):
    """Priority-3: path-template id resolution (ERR_NOT_FOUND)."""
    ent = db.get(collection, ent_id)
    if ent is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"{what or collection} not found")
    return ent


def exist_body_fks(body, mapping):
    """Priority-4 existence check for body foreign keys that are present and
    non-null (ERR_REFERENCE_NOT_FOUND). mapping: field -> (collection, what)."""
    for field, (collection, what) in mapping.items():
        if field in body and body[field] is not None:
            if db.get(collection, body[field]) is None:
                raise ApiError(
                    ERR_REFERENCE_NOT_FOUND, 404, f"{what or collection} not found"
                )


# ---------------------------------------------------------------------------
# Pagination and filters (PRD §2.3)
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
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if str(raw_limit).strip() != str(limit) and not str(raw_limit).strip().lstrip("+").isdigit():
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
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
