"""Request validation ladder helpers (PRD §2.1, §2.5).

Rung 1  context headers
Rung 2  endpoint role authorisation (and, for the split-by-action families, the
        role permitted for the named action)
Rung 3  request shape
Rung 4  path identifier resolution
Rung 5  body foreign-key resolution
"""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import store

ROLES = [
    "ProgramAdmin",
    "EventCoordinator",
    "ContainmentInspector",
    "EligibilityClerk",
    "Resident",
    "UnloadTech",
    "PackingContractor",
    "Anonymous",
]

ALL_READ_ROLES = [
    "ProgramAdmin",
    "EventCoordinator",
    "ContainmentInspector",
    "EligibilityClerk",
    "UnloadTech",
    "PackingContractor",
    "Resident",
]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ------------------------------------------------------------- rungs 1 and 2 --

def context():
    """Rung 1 — both headers present, role one of the eight declared roles."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_CONTEXT_HEADER")
    return user_id, role


def authorize(role, allowed):
    """Rung 2 — the role must appear in the endpoint's declared role list."""
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")


def authorize_action(role, action, action_roles):
    """Rung 2 — split-by-action role authorisation.

    An unknown / missing action is left to the request-shape rung so that it
    reports ERR_INVALID_REQUEST.
    """
    if not isinstance(action, str):
        return
    allowed = action_roles.get(action)
    if allowed is None:
        return
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")


# ------------------------------------------------------------------- rung 3 --

def body():
    """Parse the JSON body after the header rungs have passed."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, why))


def req_str(payload, field, allow_empty=False):
    if field not in payload or payload[field] is None:
        bad(field, "is required.")
    v = payload[field]
    if not isinstance(v, str) or (not allow_empty and v.strip() == ""):
        bad(field, "must be a non-empty string.")
    return v


def opt_str(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    v = payload[field]
    if not isinstance(v, str):
        bad(field, "must be a string.")
    return v


def req_enum(payload, field, members):
    v = req_str(payload, field)
    if v not in members:
        bad(field, "must be one of %s." % ", ".join(members))
    return v


def opt_enum(payload, field, members, default=None):
    if field not in payload or payload[field] is None:
        return default
    v = payload[field]
    if not isinstance(v, str) or v not in members:
        bad(field, "must be one of %s." % ", ".join(members))
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(payload, field, minimum=None, maximum=None):
    if field not in payload or payload[field] is None:
        bad(field, "is required.")
    v = payload[field]
    if not _is_int(v):
        bad(field, "must be an integer.")
    if minimum is not None and v < minimum:
        bad(field, "must be >= %s." % minimum)
    if maximum is not None and v > maximum:
        bad(field, "must be <= %s." % maximum)
    return v


def opt_int(payload, field, default=None, minimum=None, maximum=None):
    if field not in payload or payload[field] is None:
        return default
    v = payload[field]
    if not _is_int(v):
        bad(field, "must be an integer.")
    if minimum is not None and v < minimum:
        bad(field, "must be >= %s." % minimum)
    if maximum is not None and v > maximum:
        bad(field, "must be <= %s." % maximum)
    return v


def _to_decimal(field, v):
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        bad(field, "must be a number.")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        bad(field, "must be a number.")
    if not d.is_finite():
        bad(field, "must be a finite number.")
    return d


def req_num(payload, field, gt=None, gte=None, lte=None):
    if field not in payload or payload[field] is None:
        bad(field, "is required.")
    d = _to_decimal(field, payload[field])
    if gt is not None and not d > Decimal(str(gt)):
        bad(field, "must be greater than %s." % gt)
    if gte is not None and d < Decimal(str(gte)):
        bad(field, "must be >= %s." % gte)
    if lte is not None and d > Decimal(str(lte)):
        bad(field, "must be <= %s." % lte)
    return d


def req_bool(payload, field):
    if field not in payload or payload[field] is None:
        bad(field, "is required.")
    v = payload[field]
    if not isinstance(v, bool):
        bad(field, "must be a boolean.")
    return v


def req_str_array(payload, field, non_empty=True):
    if field not in payload or payload[field] is None:
        bad(field, "is required.")
    v = payload[field]
    if not isinstance(v, list):
        bad(field, "must be an array.")
    if non_empty and len(v) == 0:
        bad(field, "may not be empty.")
    for item in v:
        if not isinstance(item, str) or item.strip() == "":
            bad(field, "must contain only non-empty strings.")
    return v


def parse_iso(value, field):
    if not isinstance(value, str) or not value.strip():
        bad(field, "must be an ISO 8601 UTC timestamp.")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        bad(field, "must be an ISO 8601 UTC timestamp.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(payload, field):
    if field not in payload or payload[field] is None:
        bad(field, "is required.")
    return parse_iso(payload[field], field)


def req_date(payload, field):
    v = req_str(payload, field)
    if not DATE_RE.match(v):
        bad(field, "must be a YYYY-MM-DD date string.")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        bad(field, "must be a valid calendar date.")
    return v


# ------------------------------------------------------------ rungs 4 and 5 --

_COLLECTIONS = {
    "program": ("programs", "ERR_PROGRAM_NOT_FOUND"),
    "site": ("sites", "ERR_SITE_NOT_FOUND"),
    "material_category": ("material_categories", "ERR_MATERIAL_CATEGORY_NOT_FOUND"),
    "resident": ("residents", "ERR_RESIDENT_NOT_FOUND"),
    "event": ("events", "ERR_EVENT_NOT_FOUND"),
    "staffer": ("staffers", "ERR_STAFFER_NOT_FOUND"),
    "lane_assignment": ("lane_assignments", "ERR_LANE_ASSIGNMENT_NOT_FOUND"),
    "appointment": ("appointments", "ERR_APPOINTMENT_NOT_FOUND"),
    "dropoff_line": ("dropoff_lines", "ERR_CONTAINER_NOT_FOUND"),
    "container": ("containers", "ERR_CONTAINER_NOT_FOUND"),
    "manifest": ("manifests", "ERR_MANIFEST_NOT_FOUND"),
}


def lookup(kind, row_id, error_id=None):
    coll_name, default_error = _COLLECTIONS[kind]
    coll = getattr(store, coll_name)
    row = coll.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id or default_error)
    return row
