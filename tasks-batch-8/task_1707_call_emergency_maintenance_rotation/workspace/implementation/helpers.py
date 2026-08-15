"""Shared helpers: serialization, datetime handling, validation, pagination."""

import uuid
from datetime import datetime, timezone, timedelta

from db import store, clock
from errors import ApiError, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def iso_now():
    """Logical-clock now as ISO 8601 UTC with three fractional digits."""
    return fmt_dt(clock.now())


def fmt_dt(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field_name):
    """Parse an ISO 8601 datetime; accepts trailing Z or offset."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field_name} must be an ISO 8601 datetime string", 400)
    v = value.strip()
    try:
        if v.endswith("Z"):
            dt = datetime.fromisoformat(v[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(v)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, f"{field_name} is not a well-formed datetime", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------

def body():
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return data


def req_string(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is required and must be a non-empty string", 400)
    return v


def opt_string(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a string", 400)
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}", 400)
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is required and must be an integer", 400)
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be >= {minimum}", 400)
    return v


def opt_int(data, field, minimum=None):
    v = data.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an integer", 400)
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be >= {minimum}", 400)
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is required and must be a boolean", 400)
    return v


def req_dt(data, field):
    return parse_dt(data.get(field), field)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def pagination_params():
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, "limit must be between 1 and 100", 400)
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0", 400)
    return limit, offset


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Entity serialization (internal records hold datetimes as datetime objects;
# serializers emit ISO strings with three fractional digits)
# ---------------------------------------------------------------------------

def _base(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def serialize_technician(t):
    out = _base(t)
    out.update({
        "full_name": t["full_name"],
        "capability": t["capability"],
        "base_hourly_rate_cents": t["base_hourly_rate_cents"],
        "on_call_differential_bp": t["on_call_differential_bp"],
        "status": t["status"],
        "callback_minutes_168h": t["callback_minutes_168h"],
        "fatigue_block_until": fmt_dt(t["fatigue_block_until"]),
    })
    return out


def serialize_unit(u):
    out = _base(u)
    out.update({
        "unit_number": u["unit_number"],
        "building_code": u["building_code"],
        "habitability_status": u["habitability_status"],
    })
    return out


def serialize_vendor(v):
    out = _base(v)
    out.update({
        "name": v["name"],
        "trade": v["trade"],
        "per_incident_limit_cents": v["per_incident_limit_cents"],
        "status": v["status"],
    })
    return out


def serialize_rotation_shift(s):
    out = _base(s)
    out.update({
        "technician_id": s["technician_id"],
        "start_at": fmt_dt(s["start_at"]),
        "end_at": fmt_dt(s["end_at"]),
        "status": s["status"],
        "needs_coverage": s["needs_coverage"],
        "standby_minutes": s["standby_minutes"],
        "provisional_shift_pay_cents": s["provisional_shift_pay_cents"],
    })
    return out


def serialize_call_ticket(t):
    out = _base(t)
    out.update({
        "unit_id": t["unit_id"],
        "caller_name": t["caller_name"],
        "caller_phone": t["caller_phone"],
        "category": t["category"],
        "description": t["description"],
        "received_at": fmt_dt(t["received_at"]),
        "is_true_emergency": t["is_true_emergency"],
        "status": t["status"],
        "sla_target_minutes": t["sla_target_minutes"],
        "assigned_technician_id": t["assigned_technician_id"],
        "triaged_at": fmt_dt(t["triaged_at"]),
        "dispatched_at": fmt_dt(t["dispatched_at"]),
        "on_scene_at": fmt_dt(t["on_scene_at"]),
        "mitigated_at": fmt_dt(t["mitigated_at"]),
        "closed_at": fmt_dt(t["closed_at"]),
        "response_minutes": t["response_minutes"],
        "response_breach": t["response_breach"],
        "escalation_level": t["escalation_level"],
        "unit_declared_uninhabitable": t["unit_declared_uninhabitable"],
        "callback_minutes": t["callback_minutes"],
        "callback_pay_cents": t["callback_pay_cents"],
    })
    return out


def serialize_work_order(w):
    out = _base(w)
    out.update({
        "call_ticket_id": w["call_ticket_id"],
        "unit_id": w["unit_id"],
        "parent_work_order_id": w["parent_work_order_id"],
        "title": w["title"],
        "description": w["description"],
        "priority": w["priority"],
        "status": w["status"],
        "assigned_technician_id": w["assigned_technician_id"],
    })
    return out


def serialize_vendor_authorization(a):
    out = _base(a)
    out.update({
        "call_ticket_id": a["call_ticket_id"],
        "work_order_id": a["work_order_id"],
        "vendor_id": a["vendor_id"],
        "amount_cents": a["amount_cents"],
        "requested_by_technician_id": a["requested_by_technician_id"],
        "authorized_by_technician_id": a["authorized_by_technician_id"],
        "status": a["status"],
        "invoice_subtotal_cents": a["invoice_subtotal_cents"],
        "invoice_markup_cents": a["invoice_markup_cents"],
        "invoice_total_cents": a["invoice_total_cents"],
    })
    return out


def serialize_relocation_case(c):
    out = _base(c)
    out.update({
        "unit_id": c["unit_id"],
        "call_ticket_id": c["call_ticket_id"],
        "proposed_by_technician_id": c["proposed_by_technician_id"],
        "approved_by_technician_id": c["approved_by_technician_id"],
        "start_date": fmt_dt(c["start_date"]),
        "end_date": fmt_dt(c["end_date"]),
        "nightly_rate_cents": c["nightly_rate_cents"],
        "planned_nights": c["planned_nights"],
        "est_cost_cents": c["est_cost_cents"],
        "actual_cost_cents": c["actual_cost_cents"],
        "status": c["status"],
        "reject_reason": c["reject_reason"],
    })
    return out


def serialize_incident_record(r):
    out = _base(r)
    out.update({
        "call_ticket_id": r["call_ticket_id"],
        "narrative": r["narrative"],
        "estimated_damage_cents": r["estimated_damage_cents"],
        "status": r["status"],
        "created_by_technician_id": r["created_by_technician_id"],
        "insurance_notified_at": fmt_dt(r["insurance_notified_at"]),
        "insurance_claim_number": r["insurance_claim_number"],
        "insurance_notification_late": r["insurance_notification_late"],
        "insurance_waived_reason": r["insurance_waived_reason"],
        "return_reason": r["return_reason"],
    })
    return out


def serialize_pay_period(p):
    out = _base(p)
    out.update({
        "period_start": fmt_dt(p["period_start"]),
        "period_end": fmt_dt(p["period_end"]),
        "status": p["status"],
    })
    return out


def serialize_pay_statement(s):
    # PayStatement: only id + created_at, no updated_at / version
    return {
        "id": s["id"],
        "created_at": fmt_dt(s["created_at"]),
        "pay_period_id": s["pay_period_id"],
        "technician_id": s["technician_id"],
        "standby_minutes_total": s["standby_minutes_total"],
        "standby_pay_final_cents": s["standby_pay_final_cents"],
        "callback_minutes_total": s["callback_minutes_total"],
        "callback_pay_final_cents": s["callback_pay_final_cents"],
        "total_pay_cents": s["total_pay_cents"],
    }


def touch(rec):
    """Refresh updated_at and bump version on a mutated resource."""
    rec["updated_at"] = clock.now()
    rec["version"] = rec.get("version", 0) + 1


def minutes_between(a, b):
    """Whole minutes from a to b, truncating partial minutes."""
    return int((b - a).total_seconds() // 60)
