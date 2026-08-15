"""Request-body shape validation (pipeline layer 1, ERR_VALIDATION) and
existence helpers (pipeline layer 3, ERR_NOT_FOUND)."""
from datetime import datetime

from db import db
from errors import raise_error, ERR_VALIDATION, ERR_NOT_FOUND
from util import parse_dt

WORK_CATEGORIES = {
    "EXTERIOR_ALTERATION", "ADDITION", "NEW_CONSTRUCTION",
    "DEMOLITION", "RELOCATION", "SITE_WORK",
}


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION, "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_VALIDATION, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str):
        raise_error(ERR_VALIDATION, f"invalid field type: {field}")
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_VALIDATION, f"missing or invalid integer field: {field}")
    if minimum is not None and v < minimum:
        raise_error(ERR_VALIDATION, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_VALIDATION, f"field {field} above maximum {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


def req_bool(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, bool):
        raise_error(ERR_VALIDATION, f"missing or invalid boolean field: {field}")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_bool(body, field)


def req_number(body, field):
    """A JSON number (int or float; booleans rejected)."""
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_VALIDATION, f"missing or invalid numeric field: {field}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_VALIDATION, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def _validate_datetime_string(v, field):
    if not isinstance(v, str):
        raise_error(ERR_VALIDATION, f"invalid ISO datetime: {field}")
    try:
        parse_dt(v)
    except (ValueError, TypeError):
        raise_error(ERR_VALIDATION, f"invalid ISO datetime: {field}")


def req_datetime(body, field):
    """Required ISO 8601 datetime; returns the parsed datetime (UTC)."""
    v = body.get(field)
    _validate_datetime_string(v, field)
    return parse_dt(v)


def opt_nullable_str(body, field, default=None):
    """A string field that may legitimately arrive as explicit null."""
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_VALIDATION, f"invalid field type: {field}")
    return v


def req_str_list(body, field):
    v = body.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise_error(ERR_VALIDATION, f"field {field} must be an array of strings")
    return list(v)


def opt_str_list(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_str_list(body, field)


def req_work_items(body, field="work_items"):
    """Array of {category, description, estimated_cost_cents}; shape only —
    the non-empty rule is a structural gate (ERR_EMPTY_WORK_ITEMS) at layer 9."""
    v = body.get(field)
    if not isinstance(v, list):
        raise_error(ERR_VALIDATION, f"missing or invalid array field: {field}")
    out = []
    for item in v:
        if not isinstance(item, dict):
            raise_error(ERR_VALIDATION, f"{field} entries must be objects")
        category = item.get("category")
        if not isinstance(category, str) or category not in WORK_CATEGORIES:
            raise_error(ERR_VALIDATION, f"{field}.category must be a declared work category")
        description = item.get("description")
        if description is None or not isinstance(description, str):
            raise_error(ERR_VALIDATION, f"{field}.description must be a string")
        cost = item.get("estimated_cost_cents")
        if cost is None or isinstance(cost, bool) or not isinstance(cost, int) or cost < 0:
            raise_error(ERR_VALIDATION, f"{field}.estimated_cost_cents must be a non-negative integer")
        out.append({
            "category": category,
            "description": description,
            "estimated_cost_cents": cost,
        })
    return out


def req_verified_work_items(body, field="verified_work_items"):
    """Array of {category, verified_cost_cents}; may legitimately be empty."""
    v = body.get(field)
    if not isinstance(v, list):
        raise_error(ERR_VALIDATION, f"missing or invalid array field: {field}")
    out = []
    for item in v:
        if not isinstance(item, dict):
            raise_error(ERR_VALIDATION, f"{field} entries must be objects")
        category = item.get("category")
        if not isinstance(category, str) or category not in WORK_CATEGORIES:
            raise_error(ERR_VALIDATION, f"{field}.category must be a declared work category")
        cost = item.get("verified_cost_cents")
        if cost is None or isinstance(cost, bool) or not isinstance(cost, int) or cost < 0:
            raise_error(ERR_VALIDATION, f"{field}.verified_cost_cents must be a non-negative integer")
        out.append({"category": category, "verified_cost_cents": cost})
    return out


def req_sections(body, field="sections"):
    v = body.get(field)
    if not isinstance(v, list):
        raise_error(ERR_VALIDATION, f"missing or invalid array field: {field}")
    out = []
    for item in v:
        if not isinstance(item, dict):
            raise_error(ERR_VALIDATION, f"{field} entries must be objects")
        code = item.get("section_code")
        text = item.get("text")
        if not isinstance(code, str) or not isinstance(text, str):
            raise_error(ERR_VALIDATION, f"{field} entries need section_code and text strings")
        out.append({"section_code": code, "text": text})
    return out


def require_path_resource(collection, rid):
    """Pipeline layer 3 (existence): path identifier, validated left-to-right."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj


def require_body_ref(collection, rid, field):
    """Pipeline layer 3 (existence): body-supplied reference must resolve."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{field} does not resolve: {rid}")
    return obj
