"""Shared helpers: body parsing, validation primitives, pagination, lookups."""
from datetime import datetime, timezone

from flask import request

from db import db
from errors import ApiError


# --------------------------------------------------------------------------
# Body parsing
# --------------------------------------------------------------------------
def get_body():
    """Return JSON body as dict; tolerate empty body (returns {})."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def as_int(value, field, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be >= {minimum}")
    return value


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be a non-empty string")
    return value


def as_enum(value, field, allowed):
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(allowed)}")
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be a boolean")
    return value


def parse_iso(value, field):
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be an ISO8601 string")
    raw = value
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} is not a valid ISO8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    """Parse a YYYY-MM-DD calendar day."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be a YYYY-MM-DD string")
    try:
        d = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be a valid YYYY-MM-DD date")
    return d.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items already sorted; returns (page, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sorted_by_creation(values):
    """Sort by created_at asc, with _seq as a stable tiebreak."""
    return sorted(values, key=lambda e: (e["created_at"], e["_seq"]))


# --------------------------------------------------------------------------
# Existence lookups (raise the correct not-found error)
# --------------------------------------------------------------------------
def get_customer(cid):
    c = db.customers.get(cid)
    if c is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", "Customer not found")
    return c


def get_technician(tid):
    t = db.technicians.get(tid)
    if t is None:
        raise ApiError("ERR_TECHNICIAN_NOT_FOUND", "Technician not found")
    return t


def get_route(rid):
    r = db.routes.get(rid)
    if r is None:
        raise ApiError("ERR_ROUTE_NOT_FOUND", "Route not found")
    return r


def get_property(pid):
    p = db.properties.get(pid)
    if p is None:
        raise ApiError("ERR_PROPERTY_NOT_FOUND", "Property not found")
    return p


def get_quote(qid):
    q = db.quotes.get(qid)
    if q is None:
        raise ApiError("ERR_QUOTE_NOT_FOUND", "ServiceQuote not found")
    return q


def get_plan(pid):
    p = db.recurring_plans.get(pid)
    if p is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "RecurringPlan not found")
    return p


def get_visit(vid):
    v = db.visits.get(vid)
    if v is None:
        raise ApiError("ERR_VISIT_NOT_FOUND", "Visit not found")
    return v


def get_assignment(aid):
    a = db.crew_assignments.get(aid)
    if a is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", "CrewAssignment not found")
    return a


def get_weather_window(wid):
    w = db.weather_windows.get(wid)
    if w is None:
        raise ApiError("ERR_WEATHER_WINDOW_NOT_FOUND", "WeatherWindow not found")
    return w


def get_invoice(iid):
    i = db.invoices.get(iid)
    if i is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND", "Invoice not found")
    return i


def get_claim(cid):
    c = db.satisfaction_claims.get(cid)
    if c is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "SatisfactionClaim not found")
    return c
