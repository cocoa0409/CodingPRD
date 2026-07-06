"""Cross-cutting concerns: response envelope, errors, auth, validation,
timestamps, serialization, and job/crew reconciliation helpers."""

import random
import re
import string
from datetime import datetime, timezone
from functools import wraps

from flask import jsonify, request

import calc
from store import db

# ---------------------------------------------------------------------------
# Error catalogue (PRD Section 5)
# ---------------------------------------------------------------------------
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_VALIDATION": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_DATE_WINDOW": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_AUDIT_NOT_APPROVED": 409,
    "ERR_SCOPE_NOT_INSTALLED": 409,
    "ERR_NOT_WAP_ELIGIBLE": 409,
    "ERR_BASELINE_TEST_REQUIRED": 409,
    "ERR_SOD_VIOLATION": 409,
    "ERR_SCOPE_INCOMPLETE": 409,
    "ERR_CREW_DOUBLE_BOOKED": 409,
    "ERR_DWELLING_WINDOW_CONFLICT": 409,
    "ERR_CREW_CAPACITY_EXCEEDED": 409,
    "ERR_REBATE_BUDGET_EXCEEDED": 409,
    "ERR_STALE_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_CATALOG[error_id]
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Roles / auth (PRD Section 2.1)
# ---------------------------------------------------------------------------
ROLES = {"ProgramAdmin", "Auditor", "Installer", "Homeowner"}
ANY = "ANY"


def current_role():
    return request.headers.get("X-User-Role")


def current_user_id():
    return request.headers.get("X-User-ID")


def require_roles(*allowed):
    """Decorator enforcing authentication (401) then authorization (403)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = current_role()
            if not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role")
            if ANY not in allowed and role not in allowed:
                raise ApiError("ERR_FORBIDDEN", "Role not permitted for this operation")
            return fn(*args, **kwargs)

        return wrapper

    return deco


# ---------------------------------------------------------------------------
# Timestamps and ids
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def new_uuid():
    import uuid

    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Response envelope (PRD Section 2.2)
# ---------------------------------------------------------------------------
def _base_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }


def respond_object(data, status=200):
    body = {"meta": _base_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def respond_list(items, limit, offset, total):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Serialization -- strip internal (underscore-prefixed) fields
# ---------------------------------------------------------------------------
def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Mutation bookkeeping (PRD Section 2.4 / 2.8)
# ---------------------------------------------------------------------------
def touch(entity, bump_version=True):
    """Refresh updated_at (if present) and optionally bump version.

    DiagnosticTest has neither field and is never touched.
    """
    if "updated_at" in entity:
        entity["updated_at"] = now_iso()
    if bump_version and "version" in entity:
        entity["version"] += 1


# ---------------------------------------------------------------------------
# Body access + field validators (all raise ERR_VALIDATION on failure)
# ---------------------------------------------------------------------------
def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def _fail(key, reason):
    raise ApiError("ERR_VALIDATION", "Field '{}' {}".format(key, reason))


def v_str(body, key):
    if key not in body or not isinstance(body[key], str):
        _fail(key, "is required and must be a string")
    return body[key]


def v_int(body, key, minimum=None, exclusive_min=None):
    if key not in body:
        _fail(key, "is required")
    val = body[key]
    if isinstance(val, bool):
        _fail(key, "must be an integer")
    if isinstance(val, int):
        iv = val
    elif isinstance(val, float) and val.is_integer():
        iv = int(val)
    else:
        _fail(key, "must be an integer")
    _range_check(key, iv, minimum, exclusive_min)
    return iv


def v_num(body, key, minimum=None, exclusive_min=None):
    if key not in body:
        _fail(key, "is required")
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        _fail(key, "must be a number")
    _range_check(key, val, minimum, exclusive_min)
    return val


def _range_check(key, val, minimum, exclusive_min):
    if minimum is not None and val < minimum:
        _fail(key, "must be >= {}".format(minimum))
    if exclusive_min is not None and not (val > exclusive_min):
        _fail(key, "must be > {}".format(exclusive_min))


def v_enum(body, key, allowed):
    if key not in body or not isinstance(body[key], str) or body[key] not in allowed:
        _fail(key, "must be one of {}".format(sorted(allowed)))
    return body[key]


def v_array(body, key):
    if key not in body or not isinstance(body[key], list):
        _fail(key, "is required and must be an array")
    return body[key]


def v_datetime(body, key):
    if key not in body or not isinstance(body[key], str):
        _fail(key, "is required and must be an ISO 8601 date-time string")
    dt = parse_iso(body[key])
    if dt is None:
        _fail(key, "must be a valid ISO 8601 date-time")
    return dt


def parse_iso(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    normalized = t
    if normalized[-1] in ("Z", "z"):
        normalized = normalized[:-1] + "+00:00"
    for candidate in (normalized, t):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    fmts = (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    )
    for fmt in fmts:
        try:
            dt = datetime.strptime(t, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Pagination + list helpers (PRD Section 2.3)
# ---------------------------------------------------------------------------
def _parse_int_arg(raw):
    if not re.fullmatch(r"[+-]?\d+", raw.strip()):
        return None
    try:
        return int(raw)
    except Exception:
        return None


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        limit = _parse_int_arg(raw_limit)
        if limit is None or limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be an integer in [1, 100]")
    if raw_offset is None:
        offset = 0
    else:
        offset = _parse_int_arg(raw_offset)
        if offset is None or offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be an integer >= 0")
    return limit, offset


def list_response(collection, filters):
    """filters: dict of query-param-name -> entity-field-name."""
    limit, offset = parse_pagination()
    items = []
    for entity in collection.values():
        if _matches(entity, filters):
            items.append(entity)
    items.sort(key=lambda e: e["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    data = [serialize(e) for e in page]
    return respond_list(data, limit, offset, total)


def _matches(entity, filters):
    for param, field in filters.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        value = entity.get(field)
        if value is None or str(value) != raw:
            return False
    return True


# ---------------------------------------------------------------------------
# Existence resolution
# ---------------------------------------------------------------------------
def resolve(collection, entity_id):
    entity = collection.get(entity_id)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", "Resource '{}' not found".format(entity_id))
    return entity


def resolve_fk(collection, entity_id):
    """Foreign-key resolution -- same ERR_NOT_FOUND semantics as path ids."""
    entity = collection.get(entity_id)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", "Referenced resource '{}' not found".format(entity_id))
    return entity


# ---------------------------------------------------------------------------
# Reconciliation: job financial rollup + savings (PRD 3.4 / 3.6)
# ---------------------------------------------------------------------------
def job_scope_items(job_id):
    return [s for s in db.scope_items.values() if s["job_id"] == job_id]


def job_rebate_claims(job_id):
    return [c for c in db.rebate_claims.values() if c["job_id"] == job_id]


def recompute_job_rollup(job):
    scopes = job_scope_items(job["id"])
    rollup_set = ("APPROVED", "INSTALLED", "VERIFIED")

    total_est = sum(
        s["estimated_cost_cents"] for s in scopes if s["status"] in rollup_set
    )
    approved_total = sum(
        (c["finalized_amount_cents"] or 0)
        for c in job_rebate_claims(job["id"])
        if c["status"] == "APPROVED"
    )
    tax_credit = calc.tax_credit_25c(scopes)
    est_savings = sum(
        s["estimated_savings_kwh"] for s in scopes if s["status"] in rollup_set
    )

    job["total_estimated_cost_cents"] = total_est
    job["approved_rebate_total_cents"] = approved_total
    job["tax_credit_cents"] = tax_credit
    job["estimated_out_of_pocket_cents"] = max(
        0, total_est - approved_total - tax_credit
    )
    job["estimated_annual_savings_kwh"] = calc.round_kwh(est_savings)
    # Reconciliation mutates the job -> refresh updated_at, but do NOT bump
    # version (version only advances on the five operations in PRD 2.4).
    touch(job, bump_version=False)


def recompute_crew(crew):
    committed = sum(
        a["duration_days"]
        for a in db.crew_assignments.values()
        if a["crew_id"] == crew["id"] and a["status"] == "SCHEDULED"
    )
    crew["committed_days"] = committed
    crew["available_days"] = crew["capacity_days"] - committed
    touch(crew, bump_version=False)
