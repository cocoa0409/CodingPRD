"""Request body schema validation helpers (priority 0 ERR_VALIDATION)."""

import re
from flask import request

import errors
from db import parse_dt

# System/computed fields that must never appear in request bodies.
SYSTEM_FIELDS = {
    "id", "created_at", "updated_at", "version",
    # ShowEvent system/computed
    "backup_consumed", "lifecycle_status", "payment_status",
    "contract_value_cents", "deposit_cents", "balance_cents",
    "paid_total_cents", "refunded_total_cents", "cancellation_status",
    "cancelled_at", "cancellation_tier", "refund_due_cents",
    "pinned_design_id", "pinned_safety_config_id", "pinned_authorization_id",
    "assigned_count", "readiness_posture",
    # AirspaceAuthorization system
    "status", "decided_at", "decided_by",
    # ShowDesign
    "design_version_no",
    # SimulationRun
    "verdict",
    # SafetyConfiguration
    "created_by_user_id", "approved_by_user_id",
    # ChargeSession
    "charge_from_pct", "started_at", "ended_at",
    # GoNoGoEvaluation
    "evaluated_at", "reason_codes", "effective_wind_limit_kt",
    "effective_gust_limit_kt", "certified_at", "certified_by_user_id",
    # IncidentReport
    "source", "filed_by_user_id", "closed_by_user_id",
    # FlightLog
    "flag_status",
    # computed envelope
    "readiness", "posture",
}


ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


def get_body():
    """Return the JSON body as a dict; raise ERR_VALIDATION on malformed."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.validation("Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.validation("Request body must be a JSON object")
    return body


def reject_system_fields(body):
    for k in body:
        if k in SYSTEM_FIELDS:
            raise errors.validation(f"System-managed field '{k}' must not be supplied")


def req_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.validation(f"Missing required field: {f}")


def opt_string(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise errors.validation(f"{name} must be a string")
    return v


def req_string(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise errors.validation(f"{name} must be a non-empty string")
    return v


def req_number(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.validation(f"{name} must be a number")
    return v


def req_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"{name} must be an integer")
    return v


def req_dt(body, name):
    """Return (raw_string, parsed_datetime). The raw client-supplied string is
    what gets stored/echoed; the parsed form is for comparisons only."""
    v = body.get(name)
    if not isinstance(v, str) or not ISO_RE.match(v):
        raise errors.validation(f"{name} must be an ISO 8601 timestamp")
    try:
        return v, parse_dt(v)
    except Exception:
        raise errors.validation(f"{name} must be an ISO 8601 timestamp")


def opt_dt(body, name):
    """Return (raw_string, parsed_datetime) or None when absent."""
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str) or not ISO_RE.match(v):
        raise errors.validation(f"{name} must be an ISO 8601 timestamp")
    try:
        return v, parse_dt(v)
    except Exception:
        raise errors.validation(f"{name} must be an ISO 8601 timestamp")


def req_enum(body, name, values):
    v = body.get(name)
    if not isinstance(v, str) or v not in values:
        raise errors.validation(f"{name} must be one of {sorted(values)}")
    return v


def pagination_params():
    """Parse and validate limit/offset query params."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.validation("limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise errors.validation("limit must be within [1, 100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.validation("offset must be an integer")
        if offset < 0:
            raise errors.validation("offset must be >= 0")
    return limit, offset
