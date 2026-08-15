"""Shared helpers: body validation, date parsing, rounding, common fields."""

import re
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import Store
from errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND, raise_err


# ---------------------------------------------------------------------------
# Rounding (PRD §2.6 — round-half-up, whole cents)
# ---------------------------------------------------------------------------

def round_half_up_cents(value):
    """Round a Decimal (or int) to whole cents using ROUND_HALF_UP."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date_field(body, field, required=True):
    """Parse a YYYY-MM-DD request field into a datetime.date. Raises
    ERR_INVALID_REQUEST on missing/malformed values."""
    raw = body.get(field)
    if raw is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return None
    if not isinstance(raw, str) or not DATE_RE.match(raw):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be a YYYY-MM-DD date string")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} is not a valid calendar date")


def parse_iso_datetime(raw, field="to_iso8601"):
    """Parse an ISO 8601 datetime string (accepts trailing Z)."""
    if not isinstance(raw, str):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be an ISO 8601 string")
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Body validation helpers (validation priority 4 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, f"Missing or invalid required field: {field}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or v not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}")
    return v


def req_int(body, field, min_v=None, max_v=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if min_v is not None and v < min_v:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be <= {max_v}")
    return v


def req_number(body, field):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be a number")
    return v


# ---------------------------------------------------------------------------
# Entity lookup helpers (validation priority 3 -> ERR_NOT_FOUND, left-to-right)
# ---------------------------------------------------------------------------

def lookup(table, entity_id, label):
    ent = table.get(entity_id)
    if ent is None:
        raise_err(ERR_NOT_FOUND, f"{label} not found: {entity_id}")
    return ent


# ---------------------------------------------------------------------------
# Common fields (PRD §2.4): id, created_at, updated_at, version
# ---------------------------------------------------------------------------

def stamp_new(store, entity):
    now = Store.now_iso()
    entity["id"] = store.new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def touch(entity):
    entity["updated_at"] = Store.now_iso()
    entity["version"] = entity.get("version", 1) + 1


def stamp_new_audit(store, entity):
    entity["id"] = store.new_id()
    entity["created_at"] = Store.now_iso()
    return entity


def append_audit(store, client_id, event_type, message, actor_id):
    ev = {
        "client_id": client_id,
        "event_type": event_type,
        "message": message,
        "actor_id": actor_id,
    }
    stamp_new_audit(store, ev)
    store.audit_events[ev["id"]] = ev
    return ev
