"""Shared helpers: identity, stamping, lookups, request-body validation,
and per-entity serializers (views)."""

import uuid

from flask import request

import db as _db
from clock import CLOCK, fmt, fmt_ms, parse_iso, parse_date
from errors import ApiError
from services import calc

MISSING = object()


def new_id():
    return str(uuid.uuid4())


def stamp_new(rec, with_version=True):
    """Attach common system fields (PRD 2.4). IncentiveEvent and EMRForecast
    use with_version=False: they carry only id and created_at."""
    now = CLOCK.now()
    rec["created_at"] = fmt_ms(now)
    if with_version:
        rec["updated_at"] = fmt_ms(now)
        rec["version"] = 1
    rec["_seq"] = _db.next_seq()
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and bumps version (PRD 2.4/2.11)."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = fmt_ms(CLOCK.now())


def get_or_404(coll, rid, label="Resource"):
    rec = _db.DB[coll].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found")
    return rec


def sorted_by_created(items):
    return sorted(items, key=lambda r: (r["_seq"],))


# --- request body parsing ----------------------------------------------------

def body_json():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return body


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def req_field(body, name):
    v = body.get(name, MISSING)
    if v is MISSING or v is None:
        _bad(f"Missing required field: {name}")
    return v


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str) or not v.strip():
        _bad(f"Field {name} must be a non-empty string")
    return v


def opt_str(body, name, default=None):
    v = body.get(name, MISSING)
    if v is MISSING or v is None:
        return default
    if not isinstance(v, str):
        _bad(f"Field {name} must be a string")
    return v


def req_int(body, name, minimum=None):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        _bad(f"Field {name} must be >= {minimum}")
    return v


def opt_int(body, name, default=None, minimum=None):
    v = body.get(name, MISSING)
    if v is MISSING or v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        _bad(f"Field {name} must be >= {minimum}")
    return v


def req_num(body, name, minimum=None):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(f"Field {name} must be a number")
    if minimum is not None and v < minimum:
        _bad(f"Field {name} must be >= {minimum}")
    return v


def opt_num(body, name, default=None, minimum=None):
    v = body.get(name, MISSING)
    if v is MISSING or v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(f"Field {name} must be a number")
    if minimum is not None and v < minimum:
        _bad(f"Field {name} must be >= {minimum}")
    return v


def opt_bool(body, name, default=None):
    v = body.get(name, MISSING)
    if v is MISSING or v is None:
        return default
    if not isinstance(v, bool):
        _bad(f"Field {name} must be a boolean")
    return v


def req_enum(body, name, values):
    v = req_field(body, name)
    if not isinstance(v, str) or v not in values:
        _bad(f"Field {name} must be one of {sorted(values)}")
    return v


def req_list(body, name):
    v = req_field(body, name)
    if not isinstance(v, list):
        _bad(f"Field {name} must be an array")
    return v


def opt_list(body, name, default=None):
    v = body.get(name, MISSING)
    if v is MISSING or v is None:
        return default
    if not isinstance(v, list):
        _bad(f"Field {name} must be an array")
    return v


def req_datetime(body, name):
    v = req_field(body, name)
    try:
        return parse_iso(v)
    except (ValueError, TypeError):
        _bad(f"Field {name} must be an ISO 8601 datetime")


def opt_datetime(body, name, default=None):
    v = body.get(name, MISSING)
    if v is MISSING or v is None:
        return default
    try:
        return parse_iso(v)
    except (ValueError, TypeError):
        _bad(f"Field {name} must be an ISO 8601 datetime")


def req_date(body, name):
    v = req_field(body, name)
    try:
        return parse_date(v)
    except (ValueError, TypeError):
        _bad(f"Field {name} must be an ISO 8601 date")


def opt_date(body, name, default=None):
    v = body.get(name, MISSING)
    if v is MISSING or v is None:
        return default
    try:
        return parse_date(v)
    except (ValueError, TypeError):
        _bad(f"Field {name} must be an ISO 8601 date")


def parse_bool_param(raw, name):
    if raw is None:
        return None
    v = raw.strip().lower()
    if v == "true":
        return True
    if v == "false":
        return False
    raise ApiError("ERR_INVALID_REQUEST", 400, f"Query parameter {name} must be true or false")


# --- serializers (views) ------------------------------------------------------
# Business datetime fields render whole-second; created_at/updated_at render
# with three fractional digits (PRD 2.4).

def _dt(v):
    return fmt(v) if v is not None else None


def _d(v):
    return v.isoformat() if v is not None else None


def program_view(p):
    return {
        "id": p["id"],
        "program_year": p["program_year"],
        "scoring_variant": p["scoring_variant"],
        "incentive_budget_cents": p["incentive_budget_cents"],
        "remaining_budget_cents": p["remaining_budget_cents"],
        "observation_target_rate": p["observation_target_rate"],
        "near_miss_floor_ratio": p["near_miss_floor_ratio"],
        "quorum_min": p["quorum_min"],
        "exposure_hours": p["exposure_hours"],
        "payroll_by_class": p["payroll_by_class"],
        "elr_by_class": p["elr_by_class"],
        "status": p["status"],
        "posture": p["posture"],
        "overdue_control_count": p["overdue_control_count"],
        "sla_breach_count": p["sla_breach_count"],
        "integrity_flag": calc.compute_integrity_flag(p),
        "sweep_index": p["sweep_index"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def job_role_view(r):
    return {
        "id": r["id"],
        "title": r["title"],
        "hazard_class": r["hazard_class"],
        "required_course_ids": r["required_course_ids"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def course_view(c):
    return {
        "id": c["id"],
        "title": c["title"],
        "hazard_class": c["hazard_class"],
        "validity_months": c["validity_months"],
        "renewal_window_days": c["renewal_window_days"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def employee_view(e):
    return {
        "id": e["id"],
        "full_name": e["full_name"],
        "job_role_id": e["job_role_id"],
        "hired_on": e["hired_on"],
        "committee_member": e["committee_member"],
        "status": e["status"],
        "pending_required_training_count": e["pending_required_training_count"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def assignment_view(t):
    return {
        "id": t["id"],
        "employee_id": t["employee_id"],
        "course_id": t["course_id"],
        "due_date": _dt(t["due_date"]),
        "required": t["required"],
        "source": t["source"],
        "status": t["status"],
        "completed_at": _dt(t["completed_at"]),
        "cert_valid_until": _dt(t["cert_valid_until"]),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def hazard_view(h):
    return {
        "id": h["id"],
        "program_id": h["program_id"],
        "location": h["location"],
        "description": h["description"],
        "identified_by": h["identified_by"],
        "severity": h["severity"],
        "probability": h["probability"],
        "risk_score": h["risk_score"],
        "risk_band": h["risk_band"],
        "response_sla_due": _dt(h["response_sla_due"]),
        "sla_breached": h["sla_breached"],
        "overdue_control_count": h["overdue_control_count"],
        "status": h["status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def control_view(c):
    return {
        "id": c["id"],
        "hazard_id": c["hazard_id"],
        "description": c["description"],
        "implementer_id": c["implementer_id"],
        "due_date": _dt(c["due_date"]),
        "implemented_at": _dt(c["implemented_at"]),
        "verified_by": c["verified_by"],
        "verified_at": _dt(c["verified_at"]),
        "outcome_note": c["outcome_note"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def observation_view(o):
    return {
        "id": o["id"],
        "program_id": o["program_id"],
        "reporter_id": o["reporter_id"],
        "kind": o["kind"],
        "description": o["description"],
        "occurred_at": _dt(o["occurred_at"]),
        "linked_hazard_id": o["linked_hazard_id"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def meeting_view(m):
    return {
        "id": m["id"],
        "program_id": m["program_id"],
        "scheduled_start": _dt(m["scheduled_start"]),
        "scheduled_end": _dt(m["scheduled_end"]),
        "location": m["location"],
        "attendee_ids": m["attendee_ids"],
        "minutes_text": m["minutes_text"],
        "open_action_count": m["open_action_count"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def action_item_view(a):
    return {
        "id": a["id"],
        "meeting_id": a["meeting_id"],
        "assignee_id": a["assignee_id"],
        "description": a["description"],
        "due_date": _dt(a["due_date"]),
        "hazard_id": a["hazard_id"],
        "completed_at": _dt(a["completed_at"]),
        "verified_by": a["verified_by"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def contractor_view(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "contact_email": c["contact_email"],
        "emr": c["emr"],
        "trir": c["trir"],
        "safety_audit_pct": c["safety_audit_pct"],
        "insurance_cert_expires_on": c["insurance_cert_expires_on"],
        "prequal_score": (float(c["prequal_score"]) if c["prequal_score"] is not None else None),
        "computed_decision": c["computed_decision"],
        "status": c["status"],
        "prequal_valid_until": _dt(c["prequal_valid_until"]),
        "suspension_reason": c["suspension_reason"],
        "suspension_claim_id": c["suspension_claim_id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def claim_view(c):
    return {
        "id": c["id"],
        "program_id": c["program_id"],
        "employee_id": c["employee_id"],
        "contractor_org_id": c["contractor_org_id"],
        "occurred_on": c["occurred_on"],
        "kind": c["kind"],
        "incurred_cents": c["incurred_cents"],
        "effective_incurred_cents": c["effective_incurred_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def recommendation_view(r):
    return {
        "id": r["id"],
        "program_id": r["program_id"],
        "carrier_name": r["carrier_name"],
        "priority": r["priority"],
        "description": r["description"],
        "due_date": _dt(r["due_date"]),
        "response_text": r["response_text"],
        "evidence_control_id": r["evidence_control_id"],
        "responded_by": r["responded_by"],
        "reviewed_by": r["reviewed_by"],
        "review_note": r["review_note"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def award_view(a):
    return {
        "id": a["id"],
        "program_id": a["program_id"],
        "employee_id": a["employee_id"],
        "points_earned": a["points_earned"],
        "tier": a["tier"],
        "payout_cents": a["payout_cents"],
        "void_reason": a["void_reason"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def event_view(e):
    """IncentiveEvent is a point-ledger entry: id and created_at only (PRD 2.4)."""
    return {
        "id": e["id"],
        "program_id": e["program_id"],
        "employee_id": e["employee_id"],
        "source_type": e["source_type"],
        "points_base": e["points_base"],
        "hazard_class_multiplier": float(e["hazard_class_multiplier"]),
        "timeliness_multiplier": float(e["timeliness_multiplier"]),
        "points_awarded": e["points_awarded"],
        "reference_id": e["reference_id"],
        "created_at": e["created_at"],
    }


def forecast_view(f):
    """EMRForecast is an immutable snapshot: id and created_at only (PRD 2.4)."""
    return {
        "id": f["id"],
        "program_id": f["program_id"],
        "as_of": _dt(f["as_of"]),
        "payroll_factor": f["payroll_factor"],
        "expected_losses_provisional_cents": f["expected_losses_provisional_cents"],
        "expected_losses_final_cents": f["expected_losses_final_cents"],
        "weighting_w": f["weighting_w"],
        "ballast_provisional_cents": f["ballast_provisional_cents"],
        "ballast_final_cents": f["ballast_final_cents"],
        "actual_primary_provisional_cents": f["actual_primary_provisional_cents"],
        "actual_excess_provisional_cents": f["actual_excess_provisional_cents"],
        "actual_primary_final_cents": f["actual_primary_final_cents"],
        "actual_excess_final_cents": f["actual_excess_final_cents"],
        "emr_provisional": f["emr_provisional"],
        "emr_final": f["emr_final"],
        "created_at": f["created_at"],
    }
