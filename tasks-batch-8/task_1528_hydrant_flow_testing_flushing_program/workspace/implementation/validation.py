"""Request body schema validation (validation priority 2).

Enforces: required fields present, types valid, enum values from the declared
set, unknown fields rejected. Cross-field structural rules are enforced by the
route handlers right after calling validate_body."""
from flask import request

from errors import invalid_request
from timeutil import parse_iso

ABSENT = object()


def F(name, kind, required=True, arg=None, default=None, nullable=False):
    """Field spec. kind in: int, number, str, bool, datetime, enum, steps."""
    return {
        "name": name,
        "kind": kind,
        "required": required,
        "arg": arg,
        "default": default,
        "nullable": nullable,
    }


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and v not in (float("inf"), float("-inf")))


def _validate_steps(value):
    """Validate the FlushSequence steps array: unique step_index, dense from 1."""
    if not isinstance(value, list):
        raise invalid_request("steps must be an array")
    steps = []
    for item in value:
        if not isinstance(item, dict):
            raise invalid_request("each step must be an object")
        allowed = {"step_index", "valve_tag", "action", "status"}
        for key in item:
            if key not in allowed:
                raise invalid_request("unknown step field: %s" % key)
        idx = item.get("step_index")
        if not _is_int(idx) or idx < 1:
            raise invalid_request("step_index must be a positive integer")
        valve_tag = item.get("valve_tag")
        if not isinstance(valve_tag, str):
            raise invalid_request("valve_tag must be a string")
        action = item.get("action")
        if action not in ("OPEN", "CLOSE"):
            raise invalid_request("action must be OPEN or CLOSE")
        status = item.get("status", "PENDING")
        if status != "PENDING":
            raise invalid_request("step status must be PENDING at creation")
        steps.append({
            "step_index": idx,
            "valve_tag": valve_tag,
            "action": action,
            "status": "PENDING",
            "executed_at": None,
            "executed_by_user_id": None,
            "flow_gpm": None,
            "duration_minutes": None,
        })
    indexes = sorted(s["step_index"] for s in steps)
    if indexes != list(range(1, len(steps) + 1)):
        raise invalid_request("step_index values must be unique and dense from 1")
    steps.sort(key=lambda s: s["step_index"])
    return steps


def _convert(spec, value):
    kind = spec["kind"]
    name = spec["name"]
    if kind == "int":
        if not _is_int(value):
            raise invalid_request("field %s must be an integer" % name)
        return value
    if kind == "number":
        if not _is_number(value):
            raise invalid_request("field %s must be a number" % name)
        return value
    if kind == "str":
        if not isinstance(value, str):
            raise invalid_request("field %s must be a string" % name)
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise invalid_request("field %s must be a boolean" % name)
        return value
    if kind == "datetime":
        if not isinstance(value, str):
            raise invalid_request("field %s must be an ISO 8601 datetime string" % name)
        try:
            return parse_iso(value)
        except (ValueError, TypeError):
            raise invalid_request("field %s must be an ISO 8601 datetime string" % name)
    if kind == "enum":
        if not isinstance(value, str) or value not in spec["arg"]:
            raise invalid_request("field %s must be one of %s" % (name, sorted(spec["arg"])))
        return value
    if kind == "steps":
        return _validate_steps(value)
    raise AssertionError("unknown kind %s" % kind)


def _raw_json():
    """Return the JSON request body as a dict; {} when absent; raise otherwise."""
    if not request.data:
        return {}
    raw = request.get_json(silent=True)
    if raw is None:
        raise invalid_request("request body must be a JSON object")
    if not isinstance(raw, dict):
        raise invalid_request("request body must be a JSON object")
    return raw


def validate_body(specs):
    """Validate the request body against the field specs. Returns a dict with
    converted values (ABSENT marker removed; defaults applied for missing
    optional fields)."""
    body = _raw_json()
    allowed = {s["name"] for s in specs}
    for key in body:
        if key not in allowed:
            raise invalid_request("unknown field: %s" % key)
    out = {}
    for spec in specs:
        name = spec["name"]
        if name not in body:
            if spec["required"]:
                raise invalid_request("missing required field: %s" % name)
            out[name] = spec["default"]
            continue
        value = body[name]
        if value is None:
            if spec["required"] and not spec["nullable"]:
                raise invalid_request("missing required field: %s" % name)
            if spec["nullable"]:
                out[name] = None
            else:
                out[name] = spec["default"]
            continue
        out[name] = _convert(spec, value)
    return out


def validate_empty_body():
    """Endpoints declared with no input reject a non-empty JSON object body."""
    body = _raw_json()
    if body:
        raise invalid_request("unknown field: %s" % sorted(body.keys())[0])


def parse_pagination():
    """limit (default 10, min 1, max 100) and offset (default 0), clamped."""
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise invalid_request("limit and offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items):
    """Sort by created_at ascending (insertion order as tiebreak), then slice."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
