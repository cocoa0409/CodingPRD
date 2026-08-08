"""Request-level helpers: auth, RBAC, body validation, pagination."""

from flask import request

from constants import ROLES
from clock import parse_datetime, InvalidDateTime
from errors import ApiError
from store import DB


# --- Existence lookups (raise the resource-specific not-found error) ---------

def _lookup(collection, ident, error_id):
    rec = collection.get(ident)
    if rec is None:
        raise ApiError(error_id, "Resource %s not found." % ident)
    return rec


def get_pole_owner(ident):
    return _lookup(DB.pole_owners, ident, "ERR_POLE_OWNER_NOT_FOUND")


def get_crew(ident):
    return _lookup(DB.crews, ident, "ERR_CREW_NOT_FOUND")


def get_pole(ident):
    return _lookup(DB.poles, ident, "ERR_POLE_NOT_FOUND")


def get_attacher(ident):
    return _lookup(DB.attachers, ident, "ERR_ATTACHER_NOT_FOUND")


def get_application(ident):
    return _lookup(DB.applications, ident, "ERR_APPLICATION_NOT_FOUND")


def get_survey(ident):
    return _lookup(DB.surveys, ident, "ERR_SURVEY_NOT_FOUND")


def get_attachment(ident):
    return _lookup(DB.attachments, ident, "ERR_ATTACHMENT_NOT_FOUND")


def get_finding(ident):
    return _lookup(DB.findings, ident, "ERR_FINDING_NOT_FOUND")


def get_invoice(ident):
    return _lookup(DB.invoices, ident, "ERR_INVOICE_NOT_FOUND")


def get_dispute(ident):
    return _lookup(DB.disputes, ident, "ERR_DISPUTE_NOT_FOUND")


# --- Auth / RBAC -------------------------------------------------------------

def current_actor():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unknown user context.")
    return user_id, role


def authorize(role, allowed_roles):
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s is not permitted for this operation." % role)


def require_owner(resource_attacher_id, user_id):
    """Entity-backed ownership check for the Attacher role."""
    if resource_attacher_id != user_id:
        raise ApiError("ERR_UNAUTHORIZED", "Attacher does not own this resource.")


# --- Body access -------------------------------------------------------------

def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def _bad(msg):
    raise ApiError("ERR_VALIDATION", msg)


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v.strip() == "":
        _bad("Field '%s' must be a non-empty string." % name)
    return v


def req_enum(body, name, choices):
    v = body.get(name)
    if not isinstance(v, str) or v not in choices:
        _bad("Field '%s' must be one of %s." % (name, sorted(choices)))
    return v


def req_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad("Field '%s' must be an integer." % name)
    return v


def req_int_positive(body, name):
    v = req_int(body, name)
    if v <= 0:
        _bad("Field '%s' must be a positive integer." % name)
    return v


def req_int_min(body, name, minimum):
    v = req_int(body, name)
    if v < minimum:
        _bad("Field '%s' must be >= %d." % (name, minimum))
    return v


def opt_int(body, name, default):
    if name not in body or body.get(name) is None:
        return default
    return req_int(body, name)


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        _bad("Field '%s' must be a boolean." % name)
    return v


def req_number(body, name, minimum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad("Field '%s' must be a number." % name)
    if minimum is not None and v < minimum:
        _bad("Field '%s' must be >= %s." % (name, minimum))
    return v


def req_datetime(body, name):
    """Return (raw_string, parsed_utc_datetime)."""
    v = body.get(name)
    try:
        dt = parse_datetime(v)
    except InvalidDateTime:
        _bad("Field '%s' must be an ISO-8601 datetime." % name)
    return v, dt


# --- Pagination --------------------------------------------------------------

def paginate():
    def _read(name, default):
        raw = request.args.get(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = _read("limit", 10)
    offset = _read("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def apply_pagination(records):
    """Sort by created_at ASC (stable via _seq) and page."""
    records = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    return records
