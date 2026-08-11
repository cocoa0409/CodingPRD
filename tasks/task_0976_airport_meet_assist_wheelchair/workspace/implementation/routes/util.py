"""Shared route helpers: pagination parsing, serialization, validation."""
import re
from datetime import datetime

from flask import request

import db
from errors import bad_request, not_found
from response import success_list


def parse_pagination():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise bad_request("limit must be an integer")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise bad_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise bad_request("limit must be between 1 and 100")
    if offset < 0:
        raise bad_request("offset must be >= 0")
    return limit, offset


def list_response(items, serializer):
    """items: full filtered list. Applies created_at-asc sort + pagination."""
    limit, offset = parse_pagination()
    items_sorted = sorted(items, key=lambda e: e["created_at"])
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    return success_list([serializer(e) for e in page], limit, offset, total)


def json_body(required=True):
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise bad_request("Request body must be valid JSON")
        return {}
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise bad_request(f"Missing required field: {f}")


def parse_datetime_field(value, name):
    try:
        return db.parse_dt(value)
    except (ValueError, TypeError):
        raise bad_request(f"Invalid datetime for {name}")


def parse_date_field(value, name):
    if not isinstance(value, str):
        raise bad_request(f"Invalid date for {name}")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise bad_request(f"Invalid date for {name}; expected YYYY-MM-DD")


def require_enum(value, allowed, name):
    if value not in allowed:
        raise bad_request(f"Invalid value for {name}: {value}")
    return value


def get_or_404(store, entity_id, what="Resource"):
    entity = store.get(entity_id)
    if entity is None:
        raise not_found(f"{what} not found: {entity_id}")
    return entity


# ---------------------------------------------------------------------------
# Serializers — convert internal datetimes to ISO strings for output.
# ---------------------------------------------------------------------------

def _copy_with_dt(entity, dt_fields):
    out = dict(entity)
    for f in dt_fields:
        if f in out:
            out[f] = db.fmt_dt(out[f]) if isinstance(out[f], datetime) else out[f]
    out.pop("_last_change_epoch", None)
    out.pop("cancel_reason", None)
    return out


def serialize_airport(a):
    return _copy_with_dt(a, [])


def serialize_terminal(t):
    return _copy_with_dt(t, [])


def serialize_segment(s):
    return _copy_with_dt(s, ["scheduled_utc", "actual_utc"])


def serialize_passenger(p):
    return _copy_with_dt(p, [])


def serialize_agent(a):
    return _copy_with_dt(a, ["tsa_cleared_until", "shift_start_utc", "shift_end_utc"])


def serialize_wheelchair(w):
    return _copy_with_dt(w, ["last_maintenance_utc"])


def serialize_assist_request(r):
    return _copy_with_dt(r, [])


def serialize_leg(l):
    return _copy_with_dt(l, ["scheduled_pickup_utc", "actual_pickup_utc", "completed_utc"])


def serialize_assignment(a):
    return _copy_with_dt(a, ["scheduled_completion_utc"])


def serialize_incident(i):
    return _copy_with_dt(i, ["opened_at_utc"])


def serialize_invoice(inv):
    return _copy_with_dt(inv, [])


def serialize_tracking_event(t):
    return _copy_with_dt(t, ["occurred_at_utc"])


IATA_RE = re.compile(r"^[A-Z]{3}$")
