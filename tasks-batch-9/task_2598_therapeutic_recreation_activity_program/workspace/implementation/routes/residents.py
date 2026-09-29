"""Census and clinical assessment endpoints (PRD 3.1)."""
from flask import Blueprint

import serializers
from db import date_str, store
from helpers import ctx, find, load, new_entity, paginate
from middleware import (
    ROLE_ACTIVITY_AIDE,
    ROLE_ACTIVITY_DIRECTOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_RECREATION_THERAPIST,
    ROLE_VOLUNTEER_COORDINATOR,
    authorize,
    filter_arg,
    pagination,
)
from response import list_response, object_response
from services import clinical
from services import constants as C
from services import plans as plan_svc
from validation import read_body, validate

bp = Blueprint("residents", __name__)

CREATE_SPEC = {
    "full_name": {"type": "string", "max_len": 120, "required": True},
    "room_number": {"type": "string", "max_len": 12, "required": True},
    "admission_date": {"type": "date", "required": True},
    "status": {"type": "enum", "values": C.RESIDENT_STATUSES},
}

PATCH_SPEC = {
    "full_name": {"type": "string", "max_len": 120},
    "room_number": {"type": "string", "max_len": 12},
    "status": {"type": "enum", "values": C.RESIDENT_STATUSES},
}

ASSESSMENT_SPEC = {
    "cognitive_level": {"type": "enum", "values": C.COGNITIVE_LEVELS, "required": True},
    "functional_mobility": {
        "type": "enum",
        "values": C.MOBILITY_LEVELS,
        "required": True,
    },
    "interest_domains": {
        "type": "enum_array",
        "values": C.DOMAINS,
        "non_empty": True,
        "required": True,
    },
    "adaptive_equipment_needs": {"type": "enum_array", "values": C.EQUIPMENT},
    "preferred_group_size": {
        "type": "enum",
        "values": C.GROUP_SIZES,
        "required": True,
    },
    "effective_date": {"type": "date", "required": True},
}


@bp.post("/residents")
def create_resident():
    authorize(ROLE_ACTIVITY_DIRECTOR)
    body = read_body()
    values = validate(body, CREATE_SPEC)
    resident = new_entity(
        {
            "full_name": values["full_name"],
            "room_number": values["room_number"],
            "admission_date": date_str(values["admission_date"]),
            "status": values["status"] or "ADMITTED",
            "cognitive_level": None,
            "functional_mobility": None,
            "interest_domains": [],
            "supervision_tier": None,
            "engagement_index": 0.0,
            "refusal_streak": 0,
            "absence_count": 0,
            "enrollment_gate": "NONE",
            "care_plan_review_due": False,
        }
    )
    store.residents[resident["id"]] = resident
    return object_response(serializers.resident(resident), 201)


@bp.patch("/residents/<resident_id>")
def patch_resident(resident_id):
    authorize(ROLE_ACTIVITY_DIRECTOR)
    resident = load("resident", resident_id)
    body = read_body()
    values = validate(body, PATCH_SPEC)
    context = ctx()
    for field in ("full_name", "room_number", "status"):
        if values[field] is not None:
            resident[field] = values[field]
    context.bump(resident)
    return object_response(serializers.resident(resident), 200)


@bp.get("/residents/<resident_id>")
def get_resident(resident_id):
    authorize(
        ROLE_ACTIVITY_DIRECTOR,
        ROLE_RECREATION_THERAPIST,
        ROLE_ACTIVITY_AIDE,
        ROLE_VOLUNTEER_COORDINATOR,
        ROLE_COMPLIANCE_OFFICER,
    )
    resident = load("resident", resident_id)
    return object_response(serializers.resident(resident), 200)


@bp.get("/residents")
def list_residents():
    authorize(
        ROLE_ACTIVITY_DIRECTOR,
        ROLE_RECREATION_THERAPIST,
        ROLE_ACTIVITY_AIDE,
        ROLE_COMPLIANCE_OFFICER,
    )
    limit, offset = pagination()
    status = filter_arg("status")
    tier = filter_arg("supervision_tier")
    rows = list(store.residents.values())
    if status:
        rows = [r for r in rows if r["status"] == status]
    if tier:
        rows = [r for r in rows if r["supervision_tier"] == tier]
    rows.sort(key=lambda r: r["id"])
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    page, total = paginate(rows, limit, offset)
    return list_response(
        [serializers.resident(r) for r in page], limit, offset, total
    )


@bp.post("/residents/<resident_id>/assessments")
def create_assessment(resident_id):
    actor = authorize(ROLE_RECREATION_THERAPIST)
    resident = load("resident", resident_id)
    body = read_body()
    values = validate(body, ASSESSMENT_SPEC)
    context = ctx()
    assessment = new_entity(
        {
            "resident_id": resident["id"],
            "cognitive_level": values["cognitive_level"],
            "functional_mobility": values["functional_mobility"],
            "interest_domains": values["interest_domains"],
            "adaptive_equipment_needs": values["adaptive_equipment_needs"] or [],
            "preferred_group_size": values["preferred_group_size"],
            "effective_date": date_str(values["effective_date"]),
            "assessed_by_user_id": actor.user_id,
            "superseded": False,
        }
    )
    assessment.pop("updated_at", None)
    assessment.pop("version", None)
    store.assessments[assessment["id"]] = assessment

    clinical.refresh_superseded(store, resident["id"])
    clinical.apply_clinical_mirrors(store, resident)
    context.bump(resident)
    plan_svc.recompute_resident_plans(store, resident["id"], context)
    return object_response(serializers.assessment(assessment), 201)


@bp.get("/residents/<resident_id>/assessments")
def list_resident_assessments(resident_id):
    authorize(
        ROLE_RECREATION_THERAPIST, ROLE_ACTIVITY_DIRECTOR, ROLE_COMPLIANCE_OFFICER
    )
    resident = load("resident", resident_id)
    limit, offset = pagination()
    rows = clinical.rank_assessments(
        clinical.resident_assessments(store, resident["id"])
    )
    page, total = paginate(rows, limit, offset)
    return list_response(
        [serializers.assessment(a) for a in page], limit, offset, total
    )


@bp.get("/assessments/<assessment_id>")
def get_assessment(assessment_id):
    authorize(
        ROLE_RECREATION_THERAPIST, ROLE_ACTIVITY_DIRECTOR, ROLE_COMPLIANCE_OFFICER
    )
    assessment = load("assessment", assessment_id)
    return object_response(serializers.assessment(assessment), 200)


@bp.get("/assessments")
def list_assessments():
    authorize(
        ROLE_RECREATION_THERAPIST, ROLE_ACTIVITY_DIRECTOR, ROLE_COMPLIANCE_OFFICER
    )
    limit, offset = pagination()
    resident_id = filter_arg("resident_id")
    superseded = filter_arg("superseded")
    rows = list(store.assessments.values())
    if resident_id:
        rows = [a for a in rows if a["resident_id"] == resident_id]
    if superseded is not None:
        lowered = superseded.lower()
        if lowered in ("true", "false"):
            rows = [a for a in rows if a["superseded"] == (lowered == "true")]
    rows = clinical.rank_assessments(rows)
    page, total = paginate(rows, limit, offset)
    return list_response(
        [serializers.assessment(a) for a in page], limit, offset, total
    )
