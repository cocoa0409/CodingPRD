"""CarePlan endpoints + activation/revision loop (PRD §3.2)."""
from flask import Blueprint, request

import errors
import serializers
import validation as V
from common import (get_json_body, parse_pagination, sort_by_created,
                    paginate)
from db import db, stamp_create, touch
from middleware import require_roles
from response import object_response, array_response
from services import lookups

bp = Blueprint("care_plans", __name__)


def _get_patient_or_404(pid):
    rec = db.patients.get(pid)
    if rec is None:
        raise errors.not_found("Patient not found.")
    return rec


@bp.post("/patients/<pid>/care-plans")
@require_roles("Physician")
def create_care_plan(pid):
    _get_patient_or_404(pid)
    body = get_json_body()
    diagnosis_code = V.require_string(body, "diagnosis_code")
    goal_text = V.require_string(body, "goal_text")
    required_care_minutes = V.optional_int(body, "required_care_minutes", 20,
                                           minimum=20)
    rec = {
        "patient_id": pid,
        "diagnosis_code": diagnosis_code,
        "goal_text": goal_text,
        "required_care_minutes": required_care_minutes,
        "status": "DRAFT",
        "superseded_by_plan_id": None,
    }
    stamp_create(rec)
    db.care_plans[rec["id"]] = rec
    return object_response(serializers.care_plan(rec), 201)


@bp.get("/patients/<pid>/care-plans")
@require_roles("Physician", "CareCoordinator", "Clinician")
def list_care_plans(pid):
    _get_patient_or_404(pid)
    limit, offset = parse_pagination()
    records = lookups.care_plans_of(pid)
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serializers.care_plan(r) for r in page],
                          limit, offset, total)


@bp.get("/care-plans/<plan_id>")
@require_roles("Physician", "CareCoordinator", "Clinician")
def get_care_plan(plan_id):
    rec = db.care_plans.get(plan_id)
    if rec is None:
        raise errors.not_found("Care plan not found.")
    return object_response(serializers.care_plan(rec))


@bp.post("/patients/<pid>/care-plans/<plan_id>/activate")
@require_roles("Physician")
def activate_care_plan(pid, plan_id):
    patient = _get_patient_or_404(pid)
    plan = db.care_plans.get(plan_id)
    if plan is None or plan["patient_id"] != pid:
        raise errors.not_found("Care plan not found.")

    body = get_json_body()
    supersede = V.optional_bool(body, "supersede", False)

    # State legality (priority 6): activate defined only from DRAFT.
    if plan["status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT care plan can be activated.")

    active = lookups.active_care_plan(pid)
    # Business constraint (priority 17): at most one ACTIVE plan unless supersede.
    if active is not None and not supersede:
        raise errors.ApiError(errors.ERR_ACTIVE_PLAN_EXISTS, 409,
                              "An ACTIVE care plan already exists for this patient.")

    if active is not None and supersede:
        # Revision: prior ACTIVE -> REVISED, point superseded_by_plan_id.
        active["status"] = "REVISED"
        active["superseded_by_plan_id"] = plan["id"]
        touch(active)

    plan["status"] = "ACTIVE"
    touch(plan)
    patient["care_plan_id"] = plan["id"]
    # care_plan_id is a denormalized back-pointer on the patient; the activation
    # mutates the patient. Bump the patient version for this change.
    touch(patient)

    return object_response(serializers.care_plan(plan))
