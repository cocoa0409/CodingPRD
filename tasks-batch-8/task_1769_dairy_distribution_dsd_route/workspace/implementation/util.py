"""Generic helpers: request-body validation, ids, mutation bumps, pagination,
Decimal rounding (round-half-up) per PRD §2.7.
"""

import re
import uuid
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from clock import now_iso_ms, parse_iso
from db import DB
from errors import ERR_INVALID_REQUEST, err


# ---------- request-body validation ----------

def get_json_body():
    if not request.is_json:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def check_unknown_fields(body, allowed):
    for k in body.keys():
        if k not in allowed:
            raise err(ERR_INVALID_REQUEST, f"Unknown field: {k}")


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def opt_string(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a string")
    return v


def opt_int(body, name, gt=None, ge=None, ne=None):
    v = body.get(name)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if isinstance(v, float):
        if not v.is_integer():
            raise err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
        v = int(v)
    if gt is not None and not (v > gt):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be > {gt}")
    if ge is not None and not (v >= ge):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be >= {ge}")
    if ne is not None and v == ne:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be != {ne}")
    return v


def opt_number(body, name, gt=None, ge=None):
    v = body.get(name)
    if v is None:
        return None
    if not is_number(v):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    if gt is not None and not (v > gt):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be > {gt}")
    if ge is not None and not (v >= ge):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be >= {ge}")
    return v


def opt_enum(body, name, choices):
    v = body.get(name)
    if v is None:
        return None
    if v not in choices:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(choices)}")
    return v


def opt_bool(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return v


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def opt_date_str(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a YYYY-MM-DD date string")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a valid calendar date")
    return v


def opt_month_str(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str) or not _MONTH_RE.match(v):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a YYYY-MM month string")
    try:
        datetime.strptime(v + "-01", "%Y-%m-%d")
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a valid month")
    return v


def opt_iso_dt(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be an ISO 8601 timestamp")
    try:
        parse_iso(v)
    except Exception:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a valid ISO 8601 timestamp")
    return v


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


# ---------- entity helpers ----------

def new_id():
    return str(uuid.uuid4())


def base_fields():
    ts = now_iso_ms()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": DB.next_seq(),
    }


def event_fields():
    """Event-log entities (TemperatureReading, CrateTransaction): id/created_at only."""
    return {"id": new_id(), "created_at": now_iso_ms(), "_seq": DB.next_seq()}


def touch(entity):
    """Any change to a resource refreshes updated_at and increments version."""
    entity["updated_at"] = now_iso_ms()
    entity["version"] += 1


def apply_changes(entity, changes):
    """Apply field updates; bump updated_at/version only if something changed."""
    changed = False
    for k, v in changes.items():
        if entity.get(k) != v:
            entity[k] = v
            changed = True
    if changed:
        touch(entity)
    return changed


def paginate(items):
    """PRD §2.3: limit default 10 (min 1, max 100), offset default 0."""
    q = request.args
    limit_raw = q.get("limit")
    offset_raw = q.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


# ---------- decimal helpers (PRD §2.7) ----------

def dec(v):
    return Decimal(str(v))


def round_half_up_int(value):
    """Round to integer cents, ROUND_HALF_UP."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_3dp(value):
    return dec(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def round_half_up_2dp(value):
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ceil_div(numer, denom):
    """Integer ceiling division for positive operands."""
    return -(-int(numer) // int(denom))


def num3(value):
    """Serialize a 3dp Decimal price as a JSON number (shortest round-trip float)."""
    return float(value)


def date_to_iso_minute(d, minutes):
    """service_date + minutes-from-midnight -> aware datetime (UTC)."""
    base = datetime(d.year, d.month, d.day)
    from datetime import timezone as _tz
    base = base.replace(tzinfo=_tz.utc)
    return base + timedelta(minutes=int(minutes))
