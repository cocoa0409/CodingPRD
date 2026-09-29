"""Activity plan lifecycle endpoints (PRD 3.2 / 3.3)."""
from flask import Blueprint

import serializers
from db import iso, parse_datetime, store
from errors import ApiError
from helpers import ctx, load, new_entity, paginate, resolve_fk
from middleware import (
    ROLE_ACTIVITY_AIDE,
    ROLE_ACTIVITY_DIRECTOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_RECREATION_THERAPIST,
    authenticate,
    authorize,
    filter_arg,
    pagination,
)
from response import list_response, object_response
from services import clinical
from services import constants as C
from services import plans as plan_svc
from validation import bad, read_body, validate

bp = Blueprint("plans", __name__)

CREATE_SPEC = {
    "resident_id": {"type": "id", "required": True},
    "source_assessment_id": {"type": "id", "required": True},
    "cycle_start_at": {"type": "datetime", "required": True},
    "domain_frequency_targets": {"type": "int_map", "required": True},
    "expected_resident_version": {"type": "int", "min": 0, "required": True},
}

TRANSITION_SPEC = {
    "action": {
        "type": "enum",
        "values": ["ACTIVATE", "REVISE", "REACTIVATE", "CLOSE"],
        "required": True,
    },
    "review_reason": {
        "type": "enum",
        "values": ["THERAPIST_REQUEST", "COUNCIL_INPUT"],
    },
    "cycle_start_at": {"type": "datetime"},
}

THERAPIST_ACTIONS = ("ACTIVATE", "REVISE", "REACTIVATE")
DIRECTOR_ACTIONS = ("CLOSE",)


def _validate_targets(raw):
    if not isinstance(raw, dict):
        raise ApiError("ERR_PLAN_TARGETS_INVALID")
    if sorted(raw.keys()) != sorted(C.DOMAINS):
        raise ApiError("ERR_PLAN_TARGETS_INVALID")
    total = 0
    cleaned = {}
    for domain in C.DOMAINS:
        value = raw[domain]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError("ERR_PLAN_TARGETS_INVALID")
        if value < 0 or value > 20:
            raise ApiError("ERR_PLAN_TARGETS_INVALID")
        cleaned[domain] = value
        total += value
    if total < 1:
        raise ApiError("ERR_PLAN_TARGETS_INVALID")
    return cleaned, total


@bp.post("/activity-plans")
def create_plan():
    authorize(ROLE_RECREATION_THERAPIST)
    body = read_body()
    resident = resolve_fk(body, "resident_id", "resident")
    assessment = resolve_fk(body, "source_assessment_id", "assessment")
    values = validate(body, CREATE_SPEC)
    targets, total = _validate_targets(values["domain_frequency_targets"])

    if values["expected_resident_version"] != resident["version"]:
        raise ApiError("ERR_STALE_RESIDENT_VERSION")
    if resident["status"] != "ADMITTED":
        raise ApiError("ERR_RESIDENT_NOT_ADMITTED")
    if not clinical.resident_assessments(store, resident["id"]):
        raise ApiError("ERR_NO_ACTIVE_ASSESSMENT")
    if assessment["resident_id"] != resident["id"] or assessment["superseded"]:
        raise ApiError("ERR_STALE_ASSESSMENT_REFERENCE")

    context = ctx()
    plan = new_entity(
        {
            "resident_id": resident["id"],
            "source_assessment_id": assessment["id"],
            "status": "DRAFT",
            "cycle_start_at": iso(values["cycle_start_at"]),
            "domain_frequency_targets": targets,
            "target_total_sessions": total,
            "credited_attainment_pct": 0.0,
            "offered_attainment_pct": 0.0,
            "revision_count": 0,
            "review_reason": "NONE",
            "activated_at": None,
        }
    )
    store.plans[plan["id"]] = plan
    context.bump(resident)
    return object_response(serializers.plan(plan), 201)


def _cited_assessment(plan):
    return store.assessments.get(plan["source_assessment_id"])


@bp.post("/activity-plans/<plan_id>/transition")
def transition_plan(plan_id):
    authorize(ROLE_RECREATION_THERAPIST, ROLE_ACTIVITY_DIRECTOR)
    raw = read_body()
    plan = load("plan", plan_id)
    values = validate(raw, TRANSITION_SPEC)
    action = values["action"]
    resident = store.residents.get(plan["resident_id"])
    context = ctx()

    if action == "ACTIVATE":
        if plan["status"] != "DRAFT":
            raise ApiError("ERR_PLAN_INVALID_STATE")
        if resident is None or resident["status"] != "ADMITTED":
            raise ApiError("ERR_RESIDENT_NOT_ADMITTED")
        cited = _cited_assessment(plan)
        if cited is None or cited["superseded"]:
            raise ApiError("ERR_PLAN_INVALID_STATE")
        for other in plan_svc.live_plans(store, resident["id"]):
            if other["id"] == plan["id"]:
                continue
            other["status"] = "SUPERSEDED"
            context.bump(other)
            plan_svc.release_gate(resident, context)
        plan["status"] = "ACTIVE"
        plan["activated_at"] = store.now_iso()
        context.bump(plan)
        context.bump(resident)
    elif action == "REVISE":
        if plan["status"] != "ACTIVE":
            raise ApiError("ERR_PLAN_INVALID_STATE")
        if values["review_reason"] is None:
            raise ApiError("ERR_PLAN_INVALID_STATE")
        plan["status"] = "UNDER_REVISION"
        plan["review_reason"] = values["review_reason"]
        context.bump(plan)
        if resident is not None:
            plan_svc.raise_gate(resident, context)
            context.bump(resident)
    elif action == "REACTIVATE":
        if plan["status"] != "UNDER_REVISION":
            raise ApiError("ERR_PLAN_INVALID_STATE")
        cited = _cited_assessment(plan)
        if cited is None or cited["superseded"]:
            raise ApiError("ERR_PLAN_INVALID_STATE")
        plan["status"] = "ACTIVE"
        plan["revision_count"] = plan["revision_count"] + 1
        plan["review_reason"] = "NONE"
        plan["activated_at"] = store.now_iso()
        if values["cycle_start_at"] is not None:
            plan["cycle_start_at"] = iso(values["cycle_start_at"])
        context.bump(plan)
        if resident is not None:
            plan_svc.release_gate(resident, context)
            context.bump(resident)
    else:
        if plan["status"] not in ("DRAFT", "ACTIVE", "UNDER_REVISION"):
            raise ApiError("ERR_PLAN_INVALID_STATE")
        was_live = plan["status"] in C.LIVE_PLAN_STATUSES
        plan["status"] = "CLOSED"
        context.bump(plan)
        if was_live and resident is not None:
            plan_svc.release_gate(resident, context)
            context.bump(resident)

    if resident is not None:
        plan_svc.recompute_resident_plans(store, resident["id"], context)
    return object_response(serializers.plan(plan), 200)


@bp.get("/activity-plans/<plan_id>")
def get_plan(plan_id):
    authorize(
        ROLE_RECREATION_THERAPIST,
        ROLE_ACTIVITY_DIRECTOR,
        ROLE_ACTIVITY_AIDE,
        ROLE_COMPLIANCE_OFFICER,
    )
    plan = load("plan", plan_id)
    return object_response(serializers.plan(plan), 200)


@bp.get("/activity-plans")
def list_plans():
    authorize(
        ROLE_RECREATION_THERAPIST,
        ROLE_ACTIVITY_DIRECTOR,
        ROLE_ACTIVITY_AIDE,
        ROLE_COMPLIANCE_OFFICER,
    )
    limit, offset = pagination()
    resident_id = filter_arg("resident_id")
    assessment_id = filter_arg("source_assessment_id")
    status = filter_arg("status")
    rows = list(store.plans.values())
    if resident_id:
        rows = [p for p in rows if p["resident_id"] == resident_id]
    if assessment_id:
        rows = [p for p in rows if p["source_assessment_id"] == assessment_id]
    if status:
        rows = [p for p in rows if p["status"] == status]
    rows.sort(
        key=lambda p: (p["cycle_start_at"], p["created_at"], p["_seq"]), reverse=True
    )
    page, total = paginate(rows, limit, offset)
    return list_response([serializers.plan(p) for p in page], limit, offset, total)
