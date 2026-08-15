"""Errors, response envelope, validation helpers, time/decimal utilities."""

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import jsonify, request

from store import fmt_ts

# ---------------------------------------------------------------------------
# Error ids (SCAFFOLD §1.6)
# ---------------------------------------------------------------------------

ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_INVALID_TERM = "ERR_INVALID_TERM"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_REQUEST_NOT_ROUTED_TO_YOU = "ERR_REQUEST_NOT_ROUTED_TO_YOU"
ERR_NOT_AUDITOR = "ERR_NOT_AUDITOR"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_MILESTONE_NOT_ACTIONABLE = "ERR_MILESTONE_NOT_ACTIONABLE"
ERR_DECISION_NOT_ALLOWED = "ERR_DECISION_NOT_ALLOWED"
ERR_AUDITOR_IS_ASSIGNED_ADVISOR = "ERR_AUDITOR_IS_ASSIGNED_ADVISOR"
ERR_DUPLICATE_CODE = "ERR_DUPLICATE_CODE"
ERR_OUTCOME_EXISTS = "ERR_OUTCOME_EXISTS"
ERR_NOT_SENIOR = "ERR_NOT_SENIOR"
ERR_PREREQUISITE_INCOMPLETE = "ERR_PREREQUISITE_INCOMPLETE"
ERR_DUE_DATE_PAST = "ERR_DUE_DATE_PAST"
ERR_DEADLINE_PASSED = "ERR_DEADLINE_PASSED"
ERR_TERM_NOT_STARTED = "ERR_TERM_NOT_STARTED"
ERR_PLACEMENT_OVERLAP = "ERR_PLACEMENT_OVERLAP"
ERR_PATHWAY_NOT_ACTIVE = "ERR_PATHWAY_NOT_ACTIVE"
ERR_PLAN_NOT_ACTIVE = "ERR_PLAN_NOT_ACTIVE"
ERR_STUDENT_NOT_ENROLLED = "ERR_STUDENT_NOT_ENROLLED"
ERR_CROSS_STUDENT_REFERENCE = "ERR_CROSS_STUDENT_REFERENCE"
ERR_STUDENT_NOT_GRADUATED = "ERR_STUDENT_NOT_GRADUATED"
ERR_NO_CERTIFIED_AUDIT = "ERR_NO_CERTIFIED_AUDIT"
ERR_MILESTONES_INCOMPLETE = "ERR_MILESTONES_INCOMPLETE"
ERR_PENDING_REC_LETTERS = "ERR_PENDING_REC_LETTERS"
ERR_OPEN_ENROLLMENTS = "ERR_OPEN_ENROLLMENTS"
ERR_CREDITS_SHORTFALL = "ERR_CREDITS_SHORTFALL"
ERR_PATHWAY_INCOMPLETE = "ERR_PATHWAY_INCOMPLETE"
ERR_CERTIFICATION_MISSING = "ERR_CERTIFICATION_MISSING"
ERR_WORK_HOURS_SHORTFALL = "ERR_WORK_HOURS_SHORTFALL"
ERR_CASELOAD_FULL = "ERR_CASELOAD_FULL"
ERR_TEACHER_CAPACITY_EXCEEDED = "ERR_TEACHER_CAPACITY_EXCEEDED"
ERR_SITE_CAPACITY_EXCEEDED = "ERR_SITE_CAPACITY_EXCEEDED"
ERR_NO_ADVISOR_AVAILABLE = "ERR_NO_ADVISOR_AVAILABLE"


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def fail(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD §1.0 / PRD §2.2)
# ---------------------------------------------------------------------------

def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


# ---------------------------------------------------------------------------
# Auth (PRD §2.1)
# ---------------------------------------------------------------------------

ROLES = {"DistrictAdmin", "Advisor", "Student", "Teacher", "WblCoordinator"}


def auth_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail(ERR_UNAUTHENTICATED, 401, "Missing or unknown X-User-Role / X-User-ID header")
    return uid, role


def require_role(role, *allowed):
    if role not in allowed:
        fail(ERR_FORBIDDEN, 403, "Role not authorized for this endpoint")


# ---------------------------------------------------------------------------
# Time parsing (comparisons exact to the second per PRD §2.10)
# ---------------------------------------------------------------------------

def parse_datetime(value):
    """Parse an ISO 8601 string to an aware UTC datetime, or None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Decimal helpers (PRD §2.10: half-up, 2dp; equity per-group 4dp)
# ---------------------------------------------------------------------------

D2 = Decimal("0.01")
D4 = Decimal("0.0001")


def d(value):
    """Exact Decimal from an int/float/str JSON number."""
    return Decimal(str(value))


def round_half_up(dec, places=D2):
    return dec.quantize(places, rounding=ROUND_HALF_UP)


def num2(dec):
    """Decimal rounded half-up to 2dp, returned as a JSON number (float)."""
    return float(round_half_up(dec, D2))


def pct2(numerator, denominator, empty_score=Decimal("100")):
    """100 * num / den rounded half-up to 2dp; empty denominator -> empty_score."""
    if denominator == 0:
        return float(empty_score)
    return num2(round_half_up((d(numerator) * 100) / d(denominator), D2))


# ---------------------------------------------------------------------------
# Body parsing + schema validation (pipeline stage 2 -> ERR_VALIDATION 400)
# ---------------------------------------------------------------------------

def get_body():
    if request.data is None or request.data == b"":
        return {}
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        fail(ERR_VALIDATION, 400, "Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def _check_type(name, value, kind):
    if kind == "str":
        return isinstance(value, str)
    if kind == "int":
        return _is_int(value)
    if kind == "num":
        return _is_num(value)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "list":
        return isinstance(value, list)
    if kind == "datetime":
        return parse_datetime(value) is not None
    return True


def validate_schema(body, fields):
    """fields: {name: {"kind":..., "required":bool, "choices":[...], "min":...,
    "max":..., "quarter":bool, "gt":..., "future":bool, "inventory":bool}}.
    Enforces: required presence, no unknown fields, type, enum, ranges.
    """
    if not isinstance(body, dict):
        fail(ERR_VALIDATION, 400, "Request body must be a JSON object")
    unknown = set(body.keys()) - set(fields.keys())
    if unknown:
        fail(ERR_VALIDATION, 400, f"Unknown field(s): {sorted(unknown)[0]}")
    for name, spec in fields.items():
        present = name in body and body[name] is not None
        if not present:
            if name in body and body[name] is None and spec.get("required"):
                fail(ERR_VALIDATION, 400, f"Field '{name}' is required")
            if spec.get("required") and name not in body:
                fail(ERR_VALIDATION, 400, f"Field '{name}' is required")
            if name in body and body[name] is None:
                if spec.get("required"):
                    fail(ERR_VALIDATION, 400, f"Field '{name}' is required")
                continue
            continue
        value = body[name]
        if spec.get("inventory"):
            _validate_inventory(value)
            continue
        if not _check_type(name, value, spec.get("kind", "str")):
            fail(ERR_VALIDATION, 400, f"Field '{name}' has invalid type")
        if "choices" in spec and value not in spec["choices"]:
            fail(ERR_VALIDATION, 400, f"Field '{name}' has invalid value")
        kind = spec.get("kind")
        if kind in ("int", "num"):
            dv = d(value)
            if "min" in spec and dv < d(spec["min"]):
                fail(ERR_VALIDATION, 400, f"Field '{name}' below minimum")
            if "max" in spec and dv > d(spec["max"]):
                fail(ERR_VALIDATION, 400, f"Field '{name}' above maximum")
            if "gt" in spec and dv <= d(spec["gt"]):
                fail(ERR_VALIDATION, 400, f"Field '{name}' must be > {spec['gt']}")
            if spec.get("quarter"):
                scaled = dv * 4
                if scaled != scaled.to_integral_value():
                    fail(ERR_VALIDATION, 400, f"Field '{name}' must use quarter-credit granularity")
        if kind == "datetime" and spec.get("future"):
            from store import now as _now
            if parse_datetime(value) <= _now():
                fail(ERR_VALIDATION, 400, f"Field '{name}' must be in the future")


def _validate_inventory(value):
    if not isinstance(value, list):
        fail(ERR_VALIDATION, 400, "interest_inventory must be a list")
    for entry in value:
        if not isinstance(entry, dict):
            fail(ERR_VALIDATION, 400, "interest_inventory entries must be objects")
        if set(entry.keys()) - {"interest_code", "score"}:
            fail(ERR_VALIDATION, 400, "interest_inventory entry has unknown fields")
        if "interest_code" not in entry or "score" not in entry:
            fail(ERR_VALIDATION, 400, "interest_inventory entry requires interest_code and score")
        if not isinstance(entry["interest_code"], str):
            fail(ERR_VALIDATION, 400, "interest_code must be a string")
        if not _is_int(entry["score"]) or not (1 <= entry["score"] <= 5):
            fail(ERR_VALIDATION, 400, "score must be an integer in 1..5")


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3: limit default 10, 1..100; offset default 0)
# ---------------------------------------------------------------------------

_INT_RE = re.compile(r"^-?\d+$")


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        if not _INT_RE.match(raw_limit):
            fail(ERR_VALIDATION, 400, "limit must be an integer")
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            fail(ERR_VALIDATION, 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        if not _INT_RE.match(raw_offset):
            fail(ERR_VALIDATION, 400, "offset must be an integer")
        offset = int(raw_offset)
        if offset < 0:
            fail(ERR_VALIDATION, 400, "offset must be >= 0")
    return limit, offset


def sort_records(records):
    """created_at ASC; insertion sequence as deterministic tie-break."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(records, serializer):
    limit, offset = pagination_params()
    ordered = sort_records(records)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in window], total, limit, offset)
