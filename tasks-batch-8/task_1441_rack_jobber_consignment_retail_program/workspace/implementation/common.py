"""Shared helpers: common fields, mutation bookkeeping, input parsing,
pagination, date/datetime handling, and half-up rounding.

PRD Section 2.4: every primary resource carries id, created_at, updated_at,
and integer version (increments on every mutation, including cascades per
Section 2.10). ScanEvent is append-only: id + created_at only.

PRD Section 2.5: all money is integer cents; every rounding anywhere is
round half-up (0.5 rounds away from zero).
"""
import datetime
from decimal import Decimal, ROUND_HALF_UP

from db import store, fmt_dt
from errors import err


# --- rounding (PRD Section 2.5) -----------------------------------------------

def rhu(value):
    """Round half-up to a whole integer (0.5 rounds away from zero)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    """Decimal view of a JSON number without binary-float artifacts."""
    return Decimal(str(value))


# --- entity bookkeeping ---------------------------------------------------------

def new_entity(extra_fields, common=True):
    """Mint an entity row with system fields + extra fields.

    version begins at 1 on create. _seq is a hidden monotonic insertion
    counter used for stable created_at-ASC ordering of ties (the logical
    clock makes created_at ties the norm).
    """
    now = store.now_iso()
    base = {"id": store.new_id(), "created_at": now}
    if common:
        base["updated_at"] = now
        base["version"] = 1
    base["_seq"] = store.next_seq()
    base.update(extra_fields)
    return base


def touch(entity):
    """Refresh updated_at and bump version on any mutation (PRD 2.10)."""
    entity["updated_at"] = store.now_iso()
    entity["version"] = entity["version"] + 1


def public(entity):
    """Strip private bookkeeping fields (prefixed '_') for output."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# --- date / datetime parsing ----------------------------------------------------
# Calendar dates are ISO date strings YYYY-MM-DD; instants are ISO 8601 UTC
# datetimes (PRD Section 2.5). Datetimes normalize to millisecond 'Z' form so
# lexicographic string comparison equals chronological comparison.

def parse_date(value, field):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "%s must be an ISO date string" % field)
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "%s must be a valid YYYY-MM-DD date" % field)


def parse_datetime(value, field):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "%s must be an ISO 8601 datetime" % field)
    text = value.strip()
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "%s must be a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def add_days(date_obj, days):
    return date_obj + datetime.timedelta(days=days)


def add_months(date_obj, months):
    """Add calendar months (MONTHLY settlement cadence)."""
    month = date_obj.month - 1 + months
    year = date_obj.year + month // 12
    month = month % 12 + 1
    # Clamp the day to the target month's length.
    if month == 12:
        next_first = datetime.date(year + 1, 1, 1)
    else:
        next_first = datetime.date(year, month + 1, 1)
    last_day = (next_first - datetime.timedelta(days=1)).day
    return datetime.date(year, month, min(date_obj.day, last_day))


def months_between(anchor, day):
    """Whole calendar months from anchor to day (for MONTHLY period index)."""
    m = (day.year - anchor.year) * 12 + (day.month - anchor.month)
    if day.day < anchor.day:
        m -= 1
    return m


# --- JSON body + field parsing ----------------------------------------------------

def get_json(req):
    """Return the request JSON body as a dict, or {} when absent/empty."""
    if not req.data:
        return {}
    body = req.get_json(force=True, silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "%s is required and must be a string" % field)
    return val


def optional_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a string" % field)
    return val


def require_enum(body, field, allowed):
    """Stage 5 (shape) then stage 6 (enum) of the PRD Section 2.8 ladder."""
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "%s is required and must be a string" % field)
    if val not in allowed:
        raise err("ERR_INVALID_ENUM", "%s must be one of %s" % (field, sorted(allowed)))
    return val


def optional_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return require_enum(body, field, allowed)


def _is_int(val):
    return isinstance(val, int) and not isinstance(val, bool)


def _is_num(val):
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def require_int(body, field, minimum=None, range_err=False):
    val = body.get(field)
    if not _is_int(val):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if minimum is not None and val < minimum:
        if range_err:
            raise err("ERR_RANGE_INVALID", "%s must be >= %d" % (field, minimum))
        raise err("ERR_INVALID_REQUEST", "%s must be >= %d" % (field, minimum))
    return val


def optional_int(body, field, default, minimum=None, range_err=False):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum=minimum, range_err=range_err)


def require_num(body, field):
    val = body.get(field)
    if not _is_num(val):
        raise err("ERR_INVALID_REQUEST", "%s must be a number" % field)
    return val


def optional_num(body, field, default):
    if field not in body or body[field] is None:
        return default
    return require_num(body, field)


def require_pct(body, field, lo=0.0, hi=1.0, lo_open=False, hi_open=False):
    """Stage 7 numeric-range check for percentage fields -> ERR_RANGE_INVALID."""
    val = require_num(body, field)
    _check_pct(val, field, lo, hi, lo_open, hi_open)
    return val


def optional_pct(body, field, default, lo=0.0, hi=1.0, lo_open=False, hi_open=False):
    if field not in body or body[field] is None:
        return default
    return require_pct(body, field, lo, hi, lo_open, hi_open)


def _check_pct(val, field, lo, hi, lo_open, hi_open):
    bad_lo = (val <= lo) if lo_open else (val < lo)
    bad_hi = (val >= hi) if hi_open else (val > hi)
    if bad_lo or bad_hi:
        raise err("ERR_RANGE_INVALID", "%s is outside its allowed range" % field)


# --- pagination (PRD Section 2.3) -------------------------------------------------
# limit defaults to 10 (min 1, max 100); offset defaults to 0 (min 0).

def parse_pagination(args):
    limit = _parse_page_int(args, "limit", 10)
    offset = _parse_page_int(args, "offset", 0)
    if limit < 1 or limit > 100:
        raise err("ERR_RANGE_INVALID", "limit must be between 1 and 100")
    if offset < 0:
        raise err("ERR_RANGE_INVALID", "offset must be >= 0")
    return limit, offset


def _parse_page_int(args, name, default):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % name)


def list_page(rows, limit, offset):
    """Sort by creation ascending (stable via _seq), slice, build meta."""
    ordered = sorted(rows, key=lambda r: r["_seq"])
    total = len(ordered)
    page = [public(r) for r in ordered[offset:offset + limit]]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


# --- lookup helpers ---------------------------------------------------------------

def get_or_404(collection, rid, label="resource"):
    ent = collection.get(rid)
    if ent is None:
        raise err("ERR_NOT_FOUND", "%s %s does not exist" % (label, rid))
    return ent


def fk_exists(body, field, collection):
    """Stage-4 body FK resolution: present-but-unresolvable -> 404.

    Missing/None fields are left for the stage-5 shape check.
    """
    val = body.get(field)
    if val is None:
        return None
    if not isinstance(val, str) or val not in collection:
        raise err("ERR_NOT_FOUND", "%s %s does not exist" % (field, val))
    return collection[val]


def require_from_state(entity, allowed_from, terminal_states, label="resource",
                       target=None):
    """Stage 9/10 state checks (PRD Section 2.8).

    On a terminal resource the action is rejected with ERR_ALREADY_TERMINAL,
    except when the requested transition would move the resource into a
    *different* terminal state — that is a from-state violation and yields
    ERR_INVALID_STATE (e.g. cancelling an already-ENDED promotion, whose
    enumerated cancel from-states are DRAFT/SCHEDULED/ACTIVE/SUSPENDED).
    A non-terminal state outside the from-state set yields ERR_INVALID_STATE.
    """
    status = entity["status"]
    if status in terminal_states:
        if target is not None and target in terminal_states and target != status:
            raise err(
                "ERR_INVALID_STATE",
                "%s in state %s cannot transition to %s" % (label, status, target),
            )
        raise err("ERR_ALREADY_TERMINAL", "%s is in terminal state %s" % (label, status))
    if status not in allowed_from:
        raise err(
            "ERR_INVALID_STATE",
            "%s in state %s cannot perform this transition" % (label, status),
        )


def require_store_manager(user_id, agreement):
    """Stage 8 ownership: RetailerManager X-User-ID == agreement.store_id."""
    if user_id != agreement["store_id"]:
        raise err(
            "ERR_STORE_MANAGER_MISMATCH",
            "X-User-ID must equal the agreement's store_id",
        )


def require_driver(user_id, route):
    """Stage 8 ownership: RouteDriver X-User-ID == route.assigned_driver_id."""
    if user_id != route["assigned_driver_id"]:
        raise err(
            "ERR_DRIVER_NOT_ASSIGNED",
            "X-User-ID must equal the route's assigned_driver_id",
        )
