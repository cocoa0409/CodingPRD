"""Authentication, role authorization, ownership, versioning and pagination.

Header names and role names are exactly the ones PRD 2.1 declares:
`X-User-ID`, `X-User-Role`, and the six roles Licensee, SalesManager,
EventServicesManager, SettlementAnalyst, FacilitiesPlanner, VenueAdmin.
"""

from functools import wraps

from flask import g, request

import clock
from db import db
from errors import err
from response import LIMIT_DEFAULT, LIMIT_MAX, LIMIT_MIN, OFFSET_DEFAULT
from util import iso_instant

ROLES = (
    "Licensee",
    "SalesManager",
    "EventServicesManager",
    "SettlementAnalyst",
    "FacilitiesPlanner",
    "VenueAdmin",
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def endpoint(*allowed_roles):
    """Ladder steps 1 and 2: authentication then role authorization."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user_id = request.headers.get(USER_ID_HEADER)
            role = request.headers.get(USER_ROLE_HEADER)
            if not user_id or not role or role not in ROLES:
                raise err("ERR_UNAUTHENTICATED")
            if role not in allowed_roles:
                raise err("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.role = role
            g.touched = set()
            return view(*args, **kwargs)

        return wrapped

    return decorator


def actor():
    return g.get("user_id")


def role():
    return g.get("role")


def require_owner(client_id):
    """Ladder step 3: licensee ownership on the five owner-scoped operations."""
    if role() == "Licensee" and actor() != client_id:
        raise err("ERR_NOT_RESOURCE_OWNER")


# --------------------------------------------------------------------------
# request body
# --------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


# --------------------------------------------------------------------------
# versioning (PRD 2.4 / 2.9)
# --------------------------------------------------------------------------
def touch(record):
    """Refresh updated_at and increment version once per record per request."""
    if record is None or "version" not in record:
        return record
    record["updated_at"] = iso_instant(clock.now())
    key = (record["_kind"], record["id"])
    touched = g.get("touched")
    if touched is None:
        touched = set()
        g.touched = touched
    if key not in touched:
        touched.add(key)
        record["version"] = record["version"] + 1
    return record


# --------------------------------------------------------------------------
# pagination and listing (PRD 2.3)
# --------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise err(
                "ERR_INVALID_REQUEST",
                "Query parameter 'limit' must be between %d and %d." % (LIMIT_MIN, LIMIT_MAX),
            )
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "Query parameter 'offset' must be >= 0.")
    return limit, offset


def filter_rows(kind, filters, order=None):
    """Rows of a table, filtered by the supplied query parameters.

    `filters` maps a query parameter name to the record field it filters on.
    Results are ordered by created_at ascending unless `order` supplies a key.
    """
    rows = db.tables[kind].rows()
    for param, field in filters.items():
        if param in request.args:
            wanted = request.args.get(param)
            rows = [r for r in rows if _matches(r.get(field), wanted)]
    if order is not None:
        rows = sorted(rows, key=order)
    return rows


def _matches(value, wanted):
    if value is None:
        return wanted in ("", "null", "None")
    if isinstance(value, bool):
        return str(value).lower() == wanted.lower()
    return str(value) == wanted
