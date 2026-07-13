"""Shared request-handling helpers: auth, body validation, existence, pagination,
datetime parsing, entity base fields, and serialization."""
from datetime import datetime, timezone

from flask import request

from errors import ApiError
from store import store, new_id
from envelope import fmt_ts

# ---------------------------------------------------------------------------
# Auth / RBAC (PRD 2.1)
# ---------------------------------------------------------------------------
ROLES = {"IntakeWorker", "Caseworker", "Supervisor", "Admin"}


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unknown authentication headers", 401)
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role not permitted for this operation", 403)


# ---------------------------------------------------------------------------
# Body parsing / field validation (ERR_VALIDATION 400)
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object", 400)
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_str(body, field):
    if field not in body or not isinstance(body[field], str):
        raise ApiError("ERR_VALIDATION", "Missing or invalid field: %s" % field, 400)
    return body[field]


def require_int(body, field):
    if field not in body or not _is_int(body[field]):
        raise ApiError("ERR_VALIDATION", "Missing or invalid field: %s" % field, 400)
    return body[field]


def require_array(body, field):
    if field not in body or not isinstance(body[field], list):
        raise ApiError("ERR_VALIDATION", "Missing or invalid field: %s" % field, 400)
    return body[field]


def optional_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], str):
        raise ApiError("ERR_VALIDATION", "Invalid field: %s" % field, 400)
    return body[field]


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], bool):
        raise ApiError("ERR_VALIDATION", "Invalid field: %s" % field, 400)
    return body[field]


def check_enum(value, allowed):
    if value not in allowed:
        raise ApiError("ERR_INVALID_ENUM", "Invalid enum value: %r" % (value,), 422)
    return value


# ---------------------------------------------------------------------------
# Datetime parsing
# ---------------------------------------------------------------------------
def parse_dt(value, field):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", "Invalid datetime: %s" % field, 400)
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "Malformed datetime: %s" % field, 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Existence resolution (404)
# ---------------------------------------------------------------------------
_COLLECTIONS = {
    "report": ("reports", "ERR_REPORT_NOT_FOUND"),
    "client": ("clients", "ERR_CLIENT_NOT_FOUND"),
    "account": ("accounts", "ERR_ACCOUNT_NOT_FOUND"),
    "facility": ("facilities", "ERR_FACILITY_NOT_FOUND"),
    "case": ("cases", "ERR_CASE_NOT_FOUND"),
    "investigation": ("investigations", "ERR_INVESTIGATION_NOT_FOUND"),
    "placement": ("placements", "ERR_PLACEMENT_NOT_FOUND"),
    "freeze": ("freezes", "ERR_FREEZE_NOT_FOUND"),
}


def resolve(kind, entity_id):
    coll_name, err_id = _COLLECTIONS[kind]
    coll = getattr(store, coll_name)
    ent = coll.get(entity_id)
    if ent is None:
        raise ApiError(err_id, "%s not found" % kind, 404)
    return ent


def resolve_body_id(body, field, kind):
    """Existence check for a body-supplied id when present and a string.
    Missing / wrong-typed ids are deferred to body validation (400)."""
    val = body.get(field)
    if isinstance(val, str):
        return resolve(kind, val)
    return None


# ---------------------------------------------------------------------------
# Entity base fields + mutation bookkeeping
# ---------------------------------------------------------------------------
def base_fields():
    return {
        "id": new_id(),
        "created_at": store.clock,
        "updated_at": store.clock,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(ent, bump_version=True):
    ent["updated_at"] = store.clock
    if bump_version:
        ent["version"] += 1


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def _int_arg(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def paginate(items):
    """items: list already sorted. Returns (page, pagination_meta)."""
    limit = _int_arg("limit", 10)
    offset = _int_arg("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }


def sort_key(ent):
    return (ent["created_at"], ent["_seq"])


# ---------------------------------------------------------------------------
# Serialization: explicit field ordering per entity; datetimes formatted.
# ---------------------------------------------------------------------------
_FIELDS = {
    "report": ["client_id", "reporter_type", "reporter_name", "allegation_types",
               "priority", "narrative", "status", "response_due_at",
               "screening_overdue", "screen_out_reason", "case_id"],
    "client": ["full_name", "date_of_birth", "address", "capacity_status", "status",
               "placement_status", "risk_level", "preliminary_risk_score",
               "comprehensive_risk_score", "open_case_count"],
    "account": ["client_id", "institution_name", "total_balance_cents",
                "frozen_amount_cents", "available_balance_cents", "status",
                "flagged_amount_cents", "restitution_cents"],
    "facility": ["name", "total_beds", "occupied_beds", "available_beds"],
    "case": ["report_id", "client_id", "status", "allegation_types", "risk_level",
             "estimated_exposure_cents", "substantiated_exposure_cents",
             "frozen_account_count", "cross_report_agency", "cross_reported_at",
             "guardianship_status", "service_plan_status", "benefit_programs",
             "closed_at", "closure_reason"],
    "investigation": ["case_id", "assigned_caseworker_id", "status",
                      "finding_summary", "disposition", "return_count", "disposed_at"],
    "placement": ["case_id", "client_id", "facility_id", "start_at", "end_at",
                  "court_authorized", "status", "expires_at", "discharged_at"],
    "freeze": ["case_id", "account_id", "flagged_amount_cents", "freeze_start",
               "freeze_end", "status", "lifted_at"],
}


def serialize(ent, kind):
    out = {"id": ent["id"]}
    for f in _FIELDS[kind]:
        v = ent.get(f)
        out[f] = fmt_ts(v) if isinstance(v, datetime) else v
    out["created_at"] = fmt_ts(ent["created_at"])
    out["updated_at"] = fmt_ts(ent["updated_at"])
    out["version"] = ent["version"]
    return out
