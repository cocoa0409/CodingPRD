"""Cross-cutting helpers: envelope, timestamps, auth, schema validation, serialization."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from flask import request, jsonify

import store
from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED_ROLE,
    ERR_INVALID_REQUEST,
)

ROLES = {"VendorAdmin", "ClientAdmin", "Provider", "Editor", "QASupervisor"}


# ---------------------------------------------------------------------------
# Time formatting / parsing
# ---------------------------------------------------------------------------

def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 instant; naive values are treated as UTC."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, "expected an ISO 8601 timestamp string", 400)
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"unparseable timestamp: {value!r}", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD §1.0 / PRD §2.2)
# ---------------------------------------------------------------------------

def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_dt(store.now()),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(page, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(page)) < total_count
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------------------------
# Auth (PRD §2.1, validations priority 1-2)
# ---------------------------------------------------------------------------

def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and the role recognized",
            400,
        )
    return uid, role


def require_role(role, *allowed):
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED_ROLE,
            f"role {role} is not permitted to invoke this endpoint",
            403,
        )


ALL_ROLES = ("VendorAdmin", "ClientAdmin", "Provider", "Editor", "QASupervisor")


# ---------------------------------------------------------------------------
# Body schema validation (validations priority 2.5 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "request body must be a JSON object", 400)
    return data


def req_str(b, key):
    v = b.get(key)
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{key} is required and must be a string", 400)
    return v


def opt_str(b, key, default=None):
    if key not in b or b[key] is None:
        return default
    v = b[key]
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{key} must be a string", 400)
    return v


def req_int(b, key, min_v=None, max_v=None):
    v = b.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, f"{key} is required and must be an integer", 400)
    if min_v is not None and v < min_v:
        raise ApiError(ERR_INVALID_REQUEST, f"{key} must be >= {min_v}", 400)
    if max_v is not None and v > max_v:
        raise ApiError(ERR_INVALID_REQUEST, f"{key} must be <= {max_v}", 400)
    return v


def opt_int(b, key, default, min_v=None, max_v=None):
    if key not in b or b[key] is None:
        return default
    return req_int(b, key, min_v=min_v, max_v=max_v)


def req_enum(b, key, allowed):
    v = req_str(b, key)
    if v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST, f"{key} must be one of {sorted(allowed)}", 400
        )
    return v


def req_dt(b, key):
    return parse_dt(req_str(b, key))


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def paginate(items):
    limit, offset = 10, 0
    raw = request.args.get("limit")
    if raw is not None:
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, "limit must be between 1 and 100", 400)
    raw = request.args.get("offset")
    if raw is not None:
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0", 400)
    total = len(items)
    page = items[offset : offset + limit]
    return page, limit, offset, total


def truthy_param(name):
    raw = request.args.get(name)
    return raw is not None and raw.lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

def base_entity():
    n = store.now()
    return {
        "id": store.new_id(),
        "created_at": n,
        "updated_at": n,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(e):
    """Any mutation refreshes updated_at and increments version (PRD §2.5)."""
    e["updated_at"] = store.now()
    e["version"] += 1


def sorted_created(items):
    """created_at ASC; _seq keeps a stable deterministic order within one instant."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def _ser_value(v):
    if isinstance(v, datetime):
        return fmt_dt(v)
    if isinstance(v, Decimal):
        return float(v)
    return v


def serialize(e, fields):
    return {k: _ser_value(e.get(k)) for k in fields}


CLINIC_FIELDS = [
    "id", "name", "unsigned_report_threshold", "aging_tier1_hours",
    "aging_tier2_hours", "payment_grace_days", "billing_hold",
    "suspended_provider_count", "created_at", "updated_at", "version",
]

SLA_POLICY_FIELDS = [
    "id", "clinic_account_id", "priority", "tat_minutes", "rate_per_line_cents",
    "breach_credit_pct", "measurement_basis", "created_at", "updated_at", "version",
]

PROVIDER_FIELDS = [
    "id", "clinic_account_id", "full_name", "specialty", "status",
    "unsigned_tier1_count", "unsigned_aged_count", "suspension_reason",
    "created_at", "updated_at", "version",
]

EDITOR_FIELDS = [
    "id", "display_name", "status", "rolling_quality_score", "qa_review_count",
    "skill_tier", "max_concurrent_claims", "active_claim_count",
    "created_at", "updated_at", "version",
]

SHIFT_WINDOW_FIELDS = [
    "id", "editor_id", "start_at", "end_at", "created_at", "updated_at", "version",
]

JOB_FIELDS = [
    "id", "provider_id", "clinic_account_id", "work_type", "priority",
    "audio_duration_seconds", "template_id", "workflow_status", "escalation_level",
    "claimed_by_editor_id", "first_claimed_at", "claimed_at", "submitted_at",
    "delivered_at", "due_at", "asr_char_estimate", "rework_count",
    "preempted_count", "created_at", "updated_at", "version",
]

TRANSCRIPT_FIELDS = [
    "id", "dictation_job_id", "editor_id", "version_number", "final_text",
    "visible_char_count", "line_count", "status", "aging_tier", "delivered_at",
    "signed_at", "addendum_text", "created_at", "updated_at", "version",
]

# QAReview is append-only: id + created_at only, no updated_at / version (PRD §2.5)
QA_REVIEW_FIELDS = [
    "id", "created_at", "dictation_job_id", "transcript_id", "reviewer_user_id",
    "critical_error_count", "major_error_count", "minor_error_count",
    "accuracy_score", "outcome", "editor_sequence",
]

TEMPLATE_FIELDS = [
    "id", "provider_id", "work_type", "name", "body_text", "is_active",
    "created_at", "updated_at", "version",
]

MACRO_FIELDS = [
    "id", "provider_id", "shortcut", "expansion_text", "status",
    "created_at", "updated_at", "version",
]

BILLING_PERIOD_FIELDS = [
    "id", "clinic_account_id", "period_start", "period_end", "status",
    "gross_amount_cents", "credit_amount_cents", "net_amount_cents",
    "finalized_at", "created_at", "updated_at", "version",
]

LINE_ITEM_FIELDS = [
    "id", "billing_period_id", "transcript_id", "priority", "rate_per_line_cents",
    "provisional_line_count", "provisional_amount_cents", "final_line_count",
    "final_amount_cents", "sla_breach", "credit_cents", "status",
    "created_at", "updated_at", "version",
]
