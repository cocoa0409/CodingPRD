"""SafetyPlan routes (mounted under /practice/patients/{pid}/safety-plans and /practice/safety-plans/{id})."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, request

from ..auth import require_roles
from ..clock import now
from ..errors import (
    err_high_assessment_required,
    err_invalid_state,
    err_not_found,
    err_reference_not_found,
    err_risk_still_high,
    err_validation,
)
from ..helpers import (
    assert_array,
    assert_string,
    new_uuid,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.cascades import (
    bump,
    unhold_for_patient_safety,
)
from ..services.serialize import serialize_safety_plan
from ..store import store

bp = Blueprint("safety_plans", __name__)

SAFETY_PLAN_STATUSES = ["ACTIVE", "SUPERSEDED", "RESCINDED"]


@bp.post("/practice/patients/<pid>/safety-plans")
@require_roles("Therapist")
def create_safety_plan(pid: str, _caller_id: str, _caller_role: str, **_):
    body = require_json_object()
    s = store()
    with s.lock:
        if pid not in s.patients:
            raise err_not_found("Patient not found")
        trigger_id = assert_string(body.get("trigger_assessment_id"), "trigger_assessment_id")
        warning_signs = assert_string(body.get("warning_signs"), "warning_signs")
        coping_strategies = assert_string(body.get("coping_strategies"), "coping_strategies")
        support_contacts = assert_array(body.get("support_contacts"), "support_contacts", min_len=1)
        crisis_hotline = assert_string(body.get("crisis_hotline"), "crisis_hotline")
        means_restriction_plan = assert_string(body.get("means_restriction_plan"), "means_restriction_plan")
        # Validate support_contacts shape (each must be an object with name and phone).
        for i, entry in enumerate(support_contacts):
            if not isinstance(entry, dict):
                raise err_validation(f"support_contacts[{i}] must be an object")
            if not isinstance(entry.get("name"), str) or not entry.get("name"):
                raise err_validation(f"support_contacts[{i}].name must be a non-empty string")
            if not isinstance(entry.get("phone"), str) or not entry.get("phone"):
                raise err_validation(f"support_contacts[{i}].phone must be a non-empty string")

        # trigger_assessment_id must resolve and reference a HIGH assessment for THIS patient.
        trigger = s.crisis_assessments.get(trigger_id)
        if trigger is None:
            raise err_reference_not_found("trigger_assessment_id does not resolve")
        if trigger["patient_id"] != pid or trigger["risk_level"] != "HIGH":
            raise err_high_assessment_required()

        # Supersede any prior ACTIVE safety plan for this patient.
        for plan in s.safety_plans.values():
            if plan["patient_id"] == pid and plan["status"] == "ACTIVE":
                plan["status"] = "SUPERSEDED"
                bump(plan)

        sid = new_uuid()
        ts = now()
        row: dict[str, Any] = {
            "id": sid,
            "patient_id": pid,
            "trigger_assessment_id": trigger_id,
            "warning_signs": warning_signs,
            "coping_strategies": coping_strategies,
            "support_contacts": support_contacts,
            "crisis_hotline": crisis_hotline,
            "means_restriction_plan": means_restriction_plan,
            "status": "ACTIVE",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        s.safety_plans[sid] = row

        # Side effects.
        patient = s.patients[pid]
        patient["safety_plan_required"] = False
        bump(patient)
        unhold_for_patient_safety(s, pid)

        return created(serialize_safety_plan(row))


@bp.post("/practice/safety-plans/<sid>/rescind")
@require_roles("PracticeAdmin")
def rescind_safety_plan(sid: str, **_):
    s = store()
    with s.lock:
        plan = s.safety_plans.get(sid)
        if plan is None:
            raise err_not_found("SafetyPlan not found")
        if plan["status"] != "ACTIVE":
            raise err_invalid_state("Only ACTIVE safety plans may be rescinded")
        patient = s.patients.get(plan["patient_id"])
        latest_level = patient["latest_crisis_level"] if patient else None
        if latest_level is not None and latest_level not in {"LOW", "MODERATE"}:
            raise err_risk_still_high()
        plan["status"] = "RESCINDED"
        bump(plan)
        return ok(serialize_safety_plan(plan))


@bp.get("/practice/patients/<pid>/safety-plans")
@require_roles("Therapist", "PracticeAdmin")
def list_safety_plans(pid: str, **_):
    s = store()
    if pid not in s.patients:
        raise err_not_found("Patient not found")
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in SAFETY_PLAN_STATUSES:
        raise err_validation("status filter invalid")
    rows = [r for r in s.safety_plans.values() if r["patient_id"] == pid
            and (status_filter is None or r["status"] == status_filter)]
    rows.sort(key=lambda r: r["created_at"])
    return listing([serialize_safety_plan(r) for r in paginate(rows, limit, offset)],
                   total_count=len(rows), limit=limit, offset=offset)
