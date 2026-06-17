"""Request-shape validation helpers (generic ERR_INVALID_REQUEST, priority 99)
and pagination parsing (PRD §2.3).

These helpers sit at the BOTTOM of the validation priority order. They are only
invoked after auth, role, existence, ownership, state, and business gates have
passed — except where a field's basic shape must be known earlier (e.g. an enum
value used to drive a state gate). The route handlers control ordering.
"""
from flask import request

import errors
from errors import fail


def get_body():
    """Parse JSON body, tolerating an empty body as {}."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a non-empty string" % field)
    return v


def require_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    # bool is a subclass of int — reject it explicitly
    if not isinstance(v, int) or isinstance(v, bool):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be an integer" % field)
    if minimum is not None and v < minimum:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be <= %s" % (field, maximum))
    return v


def require_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a number" % field)
    return v


def optional_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a boolean" % field)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be one of %s" % (field, sorted(allowed)))
    return v


def require_line_items(body, field="line_items"):
    """Validate an array of { description, quantity>=1, unit_rate_cents>=0 }."""
    items = body.get(field)
    if not isinstance(items, list):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be an array" % field)
    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            fail(errors.ERR_INVALID_REQUEST, "Each line item must be an object")
        desc = item.get("description")
        if not isinstance(desc, str) or desc == "":
            fail(errors.ERR_INVALID_REQUEST, "Line item 'description' must be a non-empty string")
        qty = item.get("quantity")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            fail(errors.ERR_INVALID_REQUEST, "Line item 'quantity' must be an integer >= 1")
        rate = item.get("unit_rate_cents")
        if not isinstance(rate, int) or isinstance(rate, bool) or rate < 0:
            fail(errors.ERR_INVALID_REQUEST, "Line item 'unit_rate_cents' must be an integer >= 0")
        cleaned.append({"description": desc, "quantity": qty, "unit_rate_cents": rate})
    return cleaned


def require_slots(body, field="slots"):
    """Validate an array of { zone_id, start_sec, run_minutes }."""
    slots = body.get(field)
    if not isinstance(slots, list):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be an array" % field)
    cleaned = []
    for slot in slots:
        if not isinstance(slot, dict):
            fail(errors.ERR_INVALID_REQUEST, "Each slot must be an object")
        zone_id = slot.get("zone_id")
        if not isinstance(zone_id, str) or zone_id == "":
            fail(errors.ERR_INVALID_REQUEST, "Slot 'zone_id' must be a non-empty string")
        start_sec = slot.get("start_sec")
        if not isinstance(start_sec, int) or isinstance(start_sec, bool) or start_sec < 0 or start_sec > 86399:
            fail(errors.ERR_INVALID_REQUEST, "Slot 'start_sec' must be an integer in 0..86399")
        run_minutes = slot.get("run_minutes")
        if not isinstance(run_minutes, int) or isinstance(run_minutes, bool) or run_minutes < 1:
            fail(errors.ERR_INVALID_REQUEST, "Slot 'run_minutes' must be an integer >= 1")
        cleaned.append({"zone_id": zone_id, "start_sec": start_sec, "run_minutes": run_minutes})
    return cleaned


def parse_pagination():
    """Read limit/offset from the query string per PRD §2.3.

    limit default 10, min 1, max 100. offset default 0, min 0.
    Malformed values are ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            fail(errors.ERR_INVALID_REQUEST, "'limit' must be an integer")
        if limit < 1 or limit > 100:
            fail(errors.ERR_INVALID_REQUEST, "'limit' must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            fail(errors.ERR_INVALID_REQUEST, "'offset' must be an integer")
        if offset < 0:
            fail(errors.ERR_INVALID_REQUEST, "'offset' must be >= 0")

    return limit, offset
