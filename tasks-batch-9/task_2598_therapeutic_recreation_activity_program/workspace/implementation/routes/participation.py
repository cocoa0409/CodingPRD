"""Enrollment and participation documentation endpoints (PRD 3.5 / 3.6)."""
from flask import Blueprint

import serializers
from db import parse_datetime, store
from errors import ApiError
from helpers import ctx, find, load, new_entity, paginate, resolve_fk
from middleware import (
    ROLE_ACTIVITY_AIDE,
    ROLE_ACTIVITY_DIRECTOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_RECREATION_THERAPIST,
    authorize,
    filter_arg,
    pagination,
)
from response import list_response, object_response
from services import clinical
from services import constants as C
from services import plans as plan_svc
from services import sessions as session_svc
from validation import bad, read_body, validate

bp = Blueprint("participation", __name__)

ENROLL_SPEC = {
    "resident_id": {"type": "id", "required": True},
    "gate_override_reason": {"type": "text", "max_len": 500},
}

DOCUMENT_SPEC = {
    "outcome": {
        "type": "enum",
        "values": ["ATTENDED", "REFUSED", "ABSENT"],
        "required": True,
    },
    "engagement_level": {"type": "enum", "values": C.ENGAGEMENT_LEVELS},
    "refusal_reason": {"type": "enum", "values": C.REFUSAL_REASONS},
    "adaptive_equipment_used": {"type": "enum_array", "values": C.EQUIPMENT},
}


def _segregation_guard(actor, body):
    """Rank 4: self-clearance is refused before every other enrollment check."""
    reason = body.get("gate_override_reason") if isinstance(body, dict) else None
    if not isinstance(reason, str) or reason == "":
        return
    resident = find("resident", body.get("resident_id"))
    if resident is None:
        return
    plan = plan_svc.live_plan(store, resident["id"])
    if plan is None:
        return
    assessment = store.assessments.get(plan["source_assessment_id"])
    if assessment is None:
        return
    if assessment["assessed_by_user_id"] == actor.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


@bp.post("/sessions/<session_id>/enrollments")
def create_enrollment(session_id):
    actor = authorize(
        ROLE_ACTIVITY_DIRECTOR, ROLE_RECREATION_THERAPIST, ROLE_ACTIVITY_AIDE
    )
    body = read_body()
    _segregation_guard(actor, body)
    session = load("session", session_id)
    resident = resolve_fk(body, "resident_id", "resident")
    values = validate(body, ENROLL_SPEC)
    override_reason = values["gate_override_reason"]

    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_INVALID_STATE")
    if resident["status"] != "ADMITTED":
        raise ApiError("ERR_RESIDENT_NOT_ADMITTED")
    governing = clinical.governing_assessment(store, resident["id"])
    if governing is None:
        raise ApiError("ERR_NO_ACTIVE_ASSESSMENT")

    program = store.programs[session["program_id"]]
    room = store.rooms[session["room_id"]]
    tier = resident["supervision_tier"]
    if C.TIER_ORDER.get(tier, 0) > C.TIER_ORDER[program["max_supervision_tier"]]:
        raise ApiError("ERR_SUPERVISION_TIER_UNSUPPORTED")

    needed = set(program["required_adaptive_equipment"]) | set(
        governing["adaptive_equipment_needs"]
    )
    if not needed.issubset(set(room["equipment_available"])):
        raise ApiError("ERR_ADAPTIVE_EQUIPMENT_UNAVAILABLE")

    gated = resident["enrollment_gate"] == "THERAPIST_REVIEW"
    if gated:
        if not override_reason or actor.role != ROLE_RECREATION_THERAPIST:
            raise ApiError("ERR_ENROLLMENT_GATED")

    for record in session_svc.roster(store, session["id"]):
        if record["resident_id"] == resident["id"] and record["status"] != "VOID":
            raise ApiError("ERR_DUPLICATE_ENROLLMENT")

    projected = len(session_svc.active_roster(store, session["id"])) + 1
    if projected > session["effective_capacity"]:
        raise ApiError("ERR_SESSION_CAPACITY_EXCEEDED")

    load_value, required_staff = session_svc.staffing_for(
        store, session, extra_tiers=(tier,)
    )
    if required_staff > session["assigned_staff_count"]:
        raise ApiError("ERR_STAFFING_RATIO_EXCEEDED")

    context = ctx()
    record = new_entity(
        {
            "session_id": session["id"],
            "resident_id": resident["id"],
            "status": "PLANNED",
            "finalized_from": None,
            "engagement_level": None,
            "refusal_reason": None,
            "adaptive_equipment_used": [],
            "gate_override_reason": override_reason if gated else None,
            "documented_by_user_id": None,
            "documented_at": None,
        }
    )
    store.participation[record["id"]] = record
    session_svc.recompute_session_counters(store, session, context, force_bump=True)
    plan_svc.recompute_resident_plans(store, resident["id"], context)
    return object_response(serializers.record(record), 201)


@bp.get("/sessions/<session_id>/participation")
def list_session_participation(session_id):
    authorize(
        ROLE_ACTIVITY_DIRECTOR,
        ROLE_RECREATION_THERAPIST,
        ROLE_ACTIVITY_AIDE,
        ROLE_COMPLIANCE_OFFICER,
    )
    session = load("session", session_id)
    limit, offset = pagination()
    status = filter_arg("status")
    rows = session_svc.roster(store, session["id"])
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return list_response([serializers.record(r) for r in page], limit, offset, total)


@bp.patch("/participation/<record_id>")
def document_participation(record_id):
    actor = authorize(
        ROLE_ACTIVITY_AIDE, ROLE_RECREATION_THERAPIST, ROLE_ACTIVITY_DIRECTOR
    )
    record = load("record", record_id)
    values = validate(read_body(), DOCUMENT_SPEC)
    outcome = values["outcome"]
    session = store.sessions.get(record["session_id"])

    if record["status"] != "PLANNED":
        raise ApiError("ERR_PARTICIPATION_INVALID_STATE")
    if session is None or session["status"] != "IN_PROGRESS":
        raise ApiError("ERR_PARTICIPATION_INVALID_STATE")

    engagement = values["engagement_level"]
    refusal = values["refusal_reason"]
    if outcome == "ATTENDED":
        if engagement is None:
            raise ApiError("ERR_ENGAGEMENT_LEVEL_REQUIRED")
    elif engagement is not None:
        raise ApiError("ERR_ENGAGEMENT_LEVEL_REQUIRED")
    if outcome == "REFUSED":
        if refusal is None:
            raise ApiError("ERR_REFUSAL_REASON_REQUIRED")
    elif refusal is not None:
        raise ApiError("ERR_REFUSAL_REASON_REQUIRED")

    context = ctx()
    record["status"] = outcome
    record["engagement_level"] = engagement
    record["refusal_reason"] = refusal
    record["adaptive_equipment_used"] = values["adaptive_equipment_used"] or []
    record["documented_by_user_id"] = actor.user_id
    record["documented_at"] = store.now_iso()
    context.bump(record)

    resident = store.residents.get(record["resident_id"])
    if resident is not None:
        plan_svc.refresh_resident_metrics(store, resident, context)
        context.bump(resident)
        if outcome == "REFUSED":
            if resident["refusal_streak"] >= C.REFUSAL_REVIEW_THRESHOLD:
                for plan in list(store.plans.values()):
                    if plan["resident_id"] != resident["id"]:
                        continue
                    if plan["status"] != "ACTIVE":
                        continue
                    plan["status"] = "UNDER_REVISION"
                    plan["review_reason"] = "REFUSAL_PATTERN"
                    context.bump(plan)
                    plan_svc.raise_gate(resident, context)
        plan_svc.recompute_resident_plans(store, resident["id"], context)
    return object_response(serializers.record(record), 200)


@bp.get("/participation/<record_id>")
def get_participation(record_id):
    authorize(
        ROLE_ACTIVITY_DIRECTOR,
        ROLE_RECREATION_THERAPIST,
        ROLE_ACTIVITY_AIDE,
        ROLE_COMPLIANCE_OFFICER,
    )
    record = load("record", record_id)
    return object_response(serializers.record(record), 200)


@bp.get("/participation")
def list_participation():
    authorize(
        ROLE_ACTIVITY_DIRECTOR,
        ROLE_RECREATION_THERAPIST,
        ROLE_ACTIVITY_AIDE,
        ROLE_COMPLIANCE_OFFICER,
    )
    limit, offset = pagination()
    resident_id = filter_arg("resident_id")
    session_id = filter_arg("session_id")
    outcome = filter_arg("outcome")
    rows = list(store.participation.values())
    if resident_id:
        rows = [r for r in rows if r["resident_id"] == resident_id]
    if session_id:
        rows = [r for r in rows if r["session_id"] == session_id]
    if outcome:
        rows = [r for r in rows if clinical.record_outcome(r) == outcome]

    def sort_key(record):
        session = store.sessions.get(record["session_id"])
        return (
            session["starts_at"] if session else "",
            record["created_at"],
            record["_seq"],
        )

    rows.sort(key=sort_key, reverse=True)
    page, total = paginate(rows, limit, offset)
    return list_response([serializers.record(r) for r in page], limit, offset, total)
