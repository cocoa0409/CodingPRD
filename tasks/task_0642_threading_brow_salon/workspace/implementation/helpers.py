"""Shared request-parsing, validation, pagination and existence helpers."""
from flask import request

import clock
from db import db
from errors import ApiError, err


# ---------------------------------------------------------------------------
# Body parsing & field validation (ERR_VALIDATION / 422 — PRD §2.7)
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_VALIDATION", f"Field '{field}' must be a non-empty string.")
    return v


def require_int(body, field, positive=False, non_negative=False):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"Field '{field}' must be an integer.")
    if positive and v <= 0:
        raise err("ERR_VALIDATION", f"Field '{field}' must be greater than zero.")
    if non_negative and v < 0:
        raise err("ERR_VALIDATION", f"Field '{field}' must be at least zero.")
    return v


def optional_int(body, field, default=None, positive=False, non_negative=False):
    if field not in body or body.get(field) is None:
        return default
    return require_int(body, field, positive=positive, non_negative=non_negative)


def optional_bool(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", f"Field '{field}' must be a boolean.")
    return v


def require_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", f"Field '{field}' must be an ISO 8601 string.")
    dt = clock.parse_iso8601(v)
    if dt is None:
        raise err("ERR_VALIDATION", f"Field '{field}' is not a valid ISO 8601 instant.")
    return dt


def require_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_VALIDATION", f"Field '{field}' must be one of {sorted(allowed)}.")
    return v


def require_str_array(body, field):
    v = body.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise err("ERR_VALIDATION", f"Field '{field}' must be an array of strings.")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------
def get_pagination():
    limit = _qint("limit", 10)
    offset = _qint("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _qint(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def sorted_by_created(items):
    return sorted(items, key=lambda o: (o["created_at"], o["_seq"]))


def paginate(items):
    """Sort by created_at ASC (PRD §2.3), slice by limit/offset, return (page, total)."""
    limit, offset = get_pagination()
    ordered = sorted_by_created(items)
    total = len(ordered)
    return ordered[offset:offset + limit], limit, offset, total


# ---------------------------------------------------------------------------
# Existence lookups (PRD §2.6 — left-to-right; first missing wins)
# ---------------------------------------------------------------------------
def get_salon(salon_id):
    s = db.salons.get(salon_id)
    if s is None:
        raise err("ERR_SALON_NOT_FOUND", "Salon not found.")
    return s


def get_ticket(ticket_id):
    t = db.queue_tickets.get(ticket_id)
    if t is None:
        raise err("ERR_TICKET_NOT_FOUND", "Queue ticket not found.")
    return t


def get_visit(visit_id):
    v = db.service_visits.get(visit_id)
    if v is None:
        raise err("ERR_VISIT_NOT_FOUND", "Service visit not found.")
    return v


def get_chair(chair_id):
    c = db.chairs.get(chair_id)
    if c is None:
        raise err("ERR_CHAIR_NOT_FOUND", "Chair not found.")
    return c


def get_technician(tech_id):
    t = db.technicians.get(tech_id)
    if t is None:
        raise err("ERR_TECHNICIAN_NOT_FOUND", "Technician not found.")
    return t


def get_member(member_id):
    m = db.members.get(member_id)
    if m is None:
        raise err("ERR_MEMBER_NOT_FOUND", "Member not found.")
    return m


def get_package(package_id):
    p = db.packages.get(package_id)
    if p is None:
        raise err("ERR_PACKAGE_NOT_FOUND", "Membership package not found.")
    return p


def get_line(line_id):
    li = db.line_items.get(line_id)
    if li is None:
        raise err("ERR_LINE_NOT_FOUND", "Visit line item not found.")
    return li


def get_service_item(item_id):
    si = db.service_menu_items.get(item_id)
    if si is None:
        raise err("ERR_SERVICE_ITEM_NOT_FOUND", "Service menu item not found.")
    return si


def get_addon(addon_id):
    a = db.add_ons.get(addon_id)
    if a is None:
        raise err("ERR_ADDON_NOT_FOUND", "Add-on not found.")
    return a


def get_retail(retail_id):
    r = db.retail_products.get(retail_id)
    if r is None:
        raise err("ERR_RETAIL_NOT_FOUND", "Retail product not found.")
    return r


def get_entry(entry_id):
    e = db.loyalty_entries.get(entry_id)
    if e is None:
        # The catalogue (PRD §5) enumerates no loyalty-entry not-found error and
        # §2.6 omits entryId from the left-to-right list, so a missing entry is a
        # plain 404 with a descriptive error_id.
        raise ApiError("ERR_ENTRY_NOT_FOUND", 404, "Loyalty ledger entry not found.")
    return e
