"""Field-shape validation, pagination parsing, and lookup helpers
(PRD §2.3, §2.9; SCAFFOLD validations priority 13)."""
from errors import err
from services import parse_datetime

ALLERGEN_TOKENS = {"PEANUT", "TREE_NUT", "SHELLFISH", "DAIRY", "GLUTEN", "EGG", "SOY"}
DIETARY_PATTERNS = {"OMNIVORE", "VEGETARIAN", "VEGAN", "PESCATARIAN"}


def get_json_body():
    """Return the request JSON body as a dict; {} for empty body. Malformed JSON
    or non-object bodies are ERR_INVALID_REQUEST."""
    from flask import request
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def as_int(body, field, required=True, default=None, minimum=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %d" % (field, minimum))
    return val


def as_str(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string" % field)
    return val


def as_array(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default if default is not None else []
    val = body[field]
    if not isinstance(val, list):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an array" % field)
    return val


def validate_datetime_field(body, field, required=True):
    raw = as_str(body, field, required=required, default=None)
    if raw is None:
        return None
    dt = parse_datetime(raw)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "Field %s is not a valid ISO 8601 datetime" % field)
    return dt


def validate_allergen_tokens(values, field):
    for v in values:
        if v not in ALLERGEN_TOKENS:
            raise err("ERR_INVALID_REQUEST", "Invalid allergen token in %s: %s" % (field, v))


# ---- pagination (PRD §2.3) ----
def parse_pagination():
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (PRD §2.3), apply offset/limit, build meta."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total_count = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = (offset + limit) < total_count
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return page, meta
