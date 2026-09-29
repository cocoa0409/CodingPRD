"""Rejection-ladder building blocks (PRD 2.9).

Each helper implements exactly one rung of the ladder.  Route handlers call them
in ascending ladder order; no helper ever reorders itself.
"""

from flask import request

import clock
import db
from errors import ApiError

ROLES = (
    "PlanSponsorAdmin",
    "ComplianceOfficer",
    "ExternalAuditor",
    "VendorContact",
    "PlatformOperator",
)

# ---------------------------------------------------------------------------
# Ladder step 1 + 2 — authentication and role authorization
# ---------------------------------------------------------------------------


def caller_id():
    return request.headers.get("X-User-ID")


def authorize(*allowed_roles):
    """PRD 2.1: every request carries X-User-ID and X-User-Role."""
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    role = request.headers.get("X-User-Role")
    if role is None or role == "":
        role = request.headers.get("X-Role")
    if role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "Role '%s' is not authorized for this endpoint." % (role,),
        )
    return user_id, role


# ---------------------------------------------------------------------------
# Ladder step 3 + 6 — path existence and referential integrity
# ---------------------------------------------------------------------------

_COLLECTIONS = {
    "plan_year": (lambda: db.plan_years, "ERR_PLAN_YEAR_NOT_FOUND"),
    "vendor": (lambda: db.vendors, "ERR_VENDOR_NOT_FOUND"),
    "contract": (lambda: db.contracts, "ERR_CONTRACT_NOT_FOUND"),
    "amendment": (lambda: db.amendments, "ERR_AMENDMENT_NOT_FOUND"),
    "disclosure": (lambda: db.disclosures, "ERR_DISCLOSURE_NOT_FOUND"),
    "mrf": (lambda: db.mrfs, "ERR_MRF_NOT_FOUND"),
    "refresh_cycle": (lambda: db.refresh_cycles, "ERR_REFRESH_CYCLE_NOT_FOUND"),
    "tool": (lambda: db.tools, "ERR_TOOL_NOT_FOUND"),
    "rx_submission": (lambda: db.rx_submissions, "ERR_RX_SUBMISSION_NOT_FOUND"),
    "package": (lambda: db.packages, "ERR_PACKAGE_NOT_FOUND"),
    "attestation": (lambda: db.attestations, "ERR_ATTESTATION_NOT_FOUND"),
    "ledger_entry": (lambda: db.ledger_entries, "ERR_LEDGER_ENTRY_NOT_FOUND"),
    "remediation_plan": (lambda: db.remediation_plans, "ERR_REMEDIATION_PLAN_NOT_FOUND"),
}


def fetch(kind, row_id):
    getter, error_id = _COLLECTIONS[kind]
    row = getter().get(row_id)
    if row is None:
        raise ApiError(error_id, "%s '%s' does not exist." % (kind, row_id))
    return row


# ---------------------------------------------------------------------------
# Ladder step 4 — body schema
# ---------------------------------------------------------------------------


def read_body():
    body = request.get_json(silent=True)
    if body is None:
        if request.data and request.data.strip():
            raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def _bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def field(body, name, kind, required=True, enum=None, default=None):
    """Validate one body field against its declared type (PRD 2.9 step 4)."""
    if name not in body or body[name] is None:
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if kind == "string":
        if not isinstance(value, str):
            _bad(name, "must be a string")
        if required and value == "":
            _bad(name, "must be a non-empty string")
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad(name, "must be an integer")
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad(name, "must be a number")
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            _bad(name, "must be a boolean")
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in enum:
            _bad(name, "must be one of %s" % (", ".join(enum),))
        return value
    if kind == "date":
        if clock.parse_date(value) is None:
            _bad(name, "must be an ISO YYYY-MM-DD date")
        return value
    if kind == "datetime":
        if clock.parse_datetime(value) is None:
            _bad(name, "must be an ISO 8601 UTC instant with a Z offset")
        return value
    if kind == "month":
        if not clock.is_month(value):
            _bad(name, "must be a YYYY-MM month")
        return value
    raise AssertionError("unknown field kind %s" % kind)


# ---------------------------------------------------------------------------
# Ladder step 5 — pagination
# ---------------------------------------------------------------------------


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if str(raw).strip() != str(limit):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if str(raw).strip() != str(offset):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be at least 0.")
    return limit, offset


def filter_fk(kind, param):
    """A foreign-key list filter must resolve to an existing row (step 6)."""
    value = request.args.get(param)
    if value is None:
        return None
    fetch(kind, value)
    return value


def filter_value(param):
    return request.args.get(param)


def query_date(param):
    """An optional ISO date supplied as a query parameter."""
    raw = request.args.get(param)
    if raw is None or raw == "":
        return None
    if clock.parse_date(raw) is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Query parameter '%s' must be an ISO date." % param
        )
    return raw


def apply_filters(rows, specs):
    """specs: list of (query_param, record_field, coercion)."""
    out = rows
    for param, record_field, coerce in specs:
        raw = request.args.get(param)
        if raw is None:
            continue
        try:
            wanted = coerce(raw) if coerce else raw
        except (TypeError, ValueError):
            return []
        out = [r for r in out if r.get(record_field) == wanted]
    return out


def as_bool(raw):
    low = str(raw).strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise ValueError(raw)


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)


# ---------------------------------------------------------------------------
# Ladder step 7 — vendor scope   /   step 40 — vendor identity resolves
# ---------------------------------------------------------------------------


def vendor_scope(role, user_id, owning_vendor_id):
    if role == "VendorContact" and owning_vendor_id != user_id:
        raise ApiError(
            "ERR_VENDOR_SCOPE_VIOLATION",
            "This row belongs to a different vendor.",
        )


def vendor_identity(role, user_id):
    if role == "VendorContact" and user_id not in db.vendors:
        raise ApiError(
            "ERR_ROLE_ENTITY_MISMATCH",
            "X-User-ID does not resolve to a registered vendor.",
        )


# ---------------------------------------------------------------------------
# Ladder step 8 — optimistic concurrency
# ---------------------------------------------------------------------------


def occ(expected, parent, error_id):
    if expected != parent["version"]:
        raise ApiError(
            error_id,
            "Expected version %s but the parent is at version %s."
            % (expected, parent["version"]),
        )


# ---------------------------------------------------------------------------
# Ladder step 9 — frozen plan year lockdown
# ---------------------------------------------------------------------------


def not_frozen(plan_year):
    if plan_year is not None and plan_year.get("compliance_posture") == "FROZEN":
        raise ApiError(
            "ERR_PLAN_YEAR_FROZEN",
            "The owning plan year is FROZEN; this mutation is locked down.",
        )


# ---------------------------------------------------------------------------
# Ladder step 10 — state legality
# ---------------------------------------------------------------------------


def state_is(actual, *allowed):
    if actual not in allowed:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Current state '%s' does not permit this transition." % (actual,),
        )


def require(condition, error_id, message=None):
    if not condition:
        raise ApiError(error_id, message)
