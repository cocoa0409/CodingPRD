"""Request validation: body shape, type/enum/range checks, date parsing helpers."""
import re
from datetime import date, datetime, timezone

from flask import request

from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MD_RE = re.compile(r"^\d{2}-\d{2}$")


def parse_date_str(value):
    """Strict ISO YYYY-MM-DD -> datetime.date, or None when malformed."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_iso_dt(value):
    """ISO 8601 datetime (Z or offset suffix) -> aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def valid_fiscal_md(value):
    """Fiscal year end as MM-DD (month 01-12, day valid for the month)."""
    if not isinstance(value, str) or not _MD_RE.match(value):
        return False
    month, day = int(value[0:2]), int(value[3:5])
    try:
        date(2024, month, day)  # leap year so 02-29 is acceptable
    except ValueError:
        return False
    return True


def _is_string(v):
    return isinstance(v, str)


def _is_integer(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and v not in (float("inf"), float("-inf")))


def _check_tiers(value):
    """adviser_fee_tiers: non-empty list of {up_to_net_assets, rate_bps};
    ceilings ascend; exactly one null ceiling, on the last tier."""
    if not isinstance(value, list) or len(value) == 0:
        return False
    prev_ceiling = None
    nulls = 0
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            return False
        if set(item.keys()) != {"up_to_net_assets", "rate_bps"}:
            return False
        if not _is_number(item["rate_bps"]):
            return False
        ceiling = item["up_to_net_assets"]
        if ceiling is None:
            nulls += 1
            if idx != len(value) - 1:
                return False
        else:
            if not _is_number(ceiling):
                return False
            if prev_ceiling is not None and ceiling <= prev_ceiling:
                return False
            prev_ceiling = ceiling
    return nulls == 1


def _check(kind, value, extra):
    if kind == "string":
        return _is_string(value)
    if kind == "integer":
        return _is_integer(value)
    if kind == "number":
        return _is_number(value)
    if kind == "posnumber":
        return _is_number(value) and value > 0
    if kind == "nonnegnumber":
        return _is_number(value) and value >= 0
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "enum":
        return _is_string(value) and value in extra
    if kind == "date":
        return parse_date_str(value) is not None
    if kind == "fiscal_md":
        return valid_fiscal_md(value)
    if kind == "iso8601":
        return parse_iso_dt(value) is not None
    if kind == "tiers":
        return _check_tiers(value)
    if kind == "int_range":
        lo, hi = extra
        return _is_integer(value) and lo <= value <= hi
    return False


def validate_schema(body, schema):
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    for key in body:
        if key not in schema:
            raise ApiError("ERR_VALIDATION", 400, "Unknown or system-managed field: %s" % key)
    for field, (kind, required, extra) in schema.items():
        if field not in body:
            if required:
                raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % field)
            continue
        if not _check(kind, body[field], extra):
            raise ApiError("ERR_VALIDATION", 400,
                           "Field %s has an invalid type or value" % field)


def parse_body(schema):
    """Parse and validate the JSON request body against schema.

    A missing body is tolerated only when the schema has no required fields.
    """
    has_required = any(req for _, req, _ in schema.values())
    body = request.get_json(silent=True)
    if body is None:
        if not has_required:
            body = {}
        else:
            raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    validate_schema(body, schema)
    return body


def require_path_entity(table, entity_id):
    entity = table.get(entity_id)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found: %s" % entity_id)
    return entity


def require_fk(table, fk_id, field_name):
    """Body-carried reference that must resolve to an existing resource."""
    entity = table.get(fk_id)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced %s does not exist" % field_name)
    return entity


def query_param_date(name):
    """Required well-formed YYYY-MM-DD query parameter."""
    raw = request.args.get(name)
    if raw is None or parse_date_str(raw) is None:
        raise ApiError("ERR_VALIDATION", 400, "Query parameter %s must be a YYYY-MM-DD date" % name)
    return raw


def query_param_number(name):
    """Required numeric query parameter (int or float, finite)."""
    raw = request.args.get(name)
    if raw is None:
        raise ApiError("ERR_VALIDATION", 400, "Query parameter %s is required" % name)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "Query parameter %s must be a number" % name)
    if value != value or value in (float("inf"), float("-inf")):
        raise ApiError("ERR_VALIDATION", 400, "Query parameter %s must be finite" % name)
    return value
