"""Authentication, request-shape validation, pagination (PRD 2.1 / 2.3 / 2.6)."""
import re

from flask import request

from db import db
from errors import ApiError
from util import dec, parse_dt

ROLES = ("PortfolioAdmin", "StructuralEngineer", "ComplianceAuditor", "Tenant", "Landlord")
ALL_ROLES = ROLES

_MISSING = object()
_INT_TEXT = re.compile(r"^[+-]?\d+$")


# ---------------------------------------------------------------------------
# 1. Authentication and 2. role authorization
# ---------------------------------------------------------------------------

def auth(*allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and a valid X-User-Role header are required.")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "Role %s is not permitted to call this endpoint." % role)
    return user_id, role


# ---------------------------------------------------------------------------
# 7. Entity-backed identity resolution
# ---------------------------------------------------------------------------

def resolve_identity(user_id, role):
    """Tenant / Landlord principals must resolve to a stored row."""
    if role == "Tenant":
        tenant = db.tenants.get(user_id)
        if tenant is None:
            raise ApiError("ERR_IDENTITY_NOT_FOUND",
                           "Acting tenant identity does not resolve to a tenant.")
        return tenant
    if role == "Landlord":
        landlord = db.landlords.get(user_id)
        if landlord is None:
            raise ApiError("ERR_IDENTITY_NOT_FOUND",
                           "Acting landlord identity does not resolve to a landlord.")
        return landlord
    return None


# ---------------------------------------------------------------------------
# 8. Ownership scope
# ---------------------------------------------------------------------------

def require_tenant_scope(role, user_id, owning_tenant_id):
    if role == "Tenant" and owning_tenant_id != user_id:
        raise ApiError("ERR_TENANT_SCOPE_VIOLATION",
                       "Tenant may act only on its own resources.")


def require_landlord_scope(role, user_id, owning_landlord_id):
    if role == "Landlord" and owning_landlord_id != user_id:
        raise ApiError("ERR_LANDLORD_SCOPE_VIOLATION",
                       "Landlord may act only on its own ground leases.")


# ---------------------------------------------------------------------------
# 3. Request shape
# ---------------------------------------------------------------------------

def _bad(field, detail=None):
    raise ApiError("ERR_INVALID_REQUEST",
                   detail or ("Field '%s' is missing or invalid." % field))


class Body(object):
    """Typed access to a JSON request body with PRD-shaped validation."""

    def __init__(self):
        raw = request.get_data(as_text=True) or ""
        if raw.strip() == "":
            self.data = {}
        else:
            parsed = request.get_json(silent=True)
            if not isinstance(parsed, dict):
                _bad(None, "Request body must be a JSON object.")
            self.data = parsed
        self.date_raw = {}

    # -- primitives ---------------------------------------------------------

    def _get(self, field, required):
        if field not in self.data or self.data[field] is None:
            if required:
                _bad(field, "Field '%s' is required." % field)
            return _MISSING
        return self.data[field]

    def has(self, field):
        return field in self.data and self.data[field] is not None

    def string(self, field, required=True, min_len=1, max_len=None, default=None):
        value = self._get(field, required)
        if value is _MISSING:
            return default
        if not isinstance(value, str):
            _bad(field)
        if len(value.strip()) == 0:
            _bad(field, "Field '%s' must not be blank." % field)
        if min_len is not None and len(value) < min_len:
            _bad(field)
        if max_len is not None and len(value) > max_len:
            _bad(field)
        return value

    def ident(self, field, required=True, default=None):
        value = self._get(field, required)
        if value is _MISSING:
            return default
        if not isinstance(value, str) or not value.strip():
            _bad(field)
        return value

    def enum(self, field, choices, required=True, default=None):
        value = self._get(field, required)
        if value is _MISSING:
            return default
        if not isinstance(value, str) or value not in choices:
            _bad(field, "Field '%s' must be one of %s." % (field, ", ".join(choices)))
        return value

    def boolean(self, field, required=False, default=None):
        value = self._get(field, required)
        if value is _MISSING:
            return default
        if not isinstance(value, bool):
            _bad(field)
        return value

    def integer(self, field, required=True, minimum=None, maximum=None,
                exclusive_min=None, default=None):
        value = self._get(field, required)
        if value is _MISSING:
            return default
        if isinstance(value, bool):
            _bad(field)
        if isinstance(value, float):
            if not float(value).is_integer():
                _bad(field)
            value = int(value)
        if not isinstance(value, int):
            _bad(field)
        _range(field, dec(value), minimum, maximum, exclusive_min, None)
        return int(value)

    def number(self, field, required=True, minimum=None, maximum=None,
               exclusive_min=None, exclusive_max=None, default=None):
        value = self._get(field, required)
        if value is _MISSING:
            return default if default is None else dec(default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad(field)
        value = dec(value)
        _range(field, value, minimum, maximum, exclusive_min, exclusive_max)
        return value

    def moment(self, field, required=True, default=None):
        """A date or an instant; stored as an aware UTC datetime."""
        value = self._get(field, required)
        if value is _MISSING:
            return default
        if not isinstance(value, str):
            _bad(field)
        parsed = parse_dt(value)
        if parsed is None:
            _bad(field, "Field '%s' must be an ISO 8601 date or instant." % field)
        self.date_raw[field] = value.strip()
        return parsed

    def raw_dates(self, *fields):
        if not fields:
            return dict(self.date_raw)
        return dict((f, self.date_raw[f]) for f in fields if f in self.date_raw)


def _range(field, value, minimum, maximum, exclusive_min, exclusive_max):
    if minimum is not None and value < dec(minimum):
        _bad(field, "Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > dec(maximum):
        _bad(field, "Field '%s' must be <= %s." % (field, maximum))
    if exclusive_min is not None and value <= dec(exclusive_min):
        _bad(field, "Field '%s' must be > %s." % (field, exclusive_min))
    if exclusive_max is not None and value >= dec(exclusive_max):
        _bad(field, "Field '%s' must be < %s." % (field, exclusive_max))


# ---------------------------------------------------------------------------
# 3./4. Query parameters and pagination
# ---------------------------------------------------------------------------

def query_enum(field, choices):
    value = request.args.get(field)
    if value is None:
        return None
    if value not in choices:
        _bad(field, "Query parameter '%s' must be one of %s." % (field, ", ".join(choices)))
    return value


def query_value(field):
    return request.args.get(field)


def pagination():
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        text = raw_limit.strip()
        if not _INT_TEXT.match(text):
            _bad("limit", "Query parameter 'limit' must be an integer.")
        limit = int(text)
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        text = raw_offset.strip()
        if not _INT_TEXT.match(text):
            _bad("offset", "Query parameter 'offset' must be an integer.")
        offset = int(text)
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION", "offset must not be negative.")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
