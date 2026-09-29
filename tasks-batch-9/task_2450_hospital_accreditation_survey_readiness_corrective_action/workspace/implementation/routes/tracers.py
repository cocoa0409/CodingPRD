"""The mock tracer program (PRD 3.4)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, request

import calc
import cascade
import serialize
from auth import ALL_ROLES, require_roles
from envelope import array_response, object_response
from errors import ApiError
from helpers import (
    body,
    get_chapter,
    get_standard,
    get_tracer,
    get_unit,
    opt_number,
    opt_str,
    page,
    pagination,
    req_dt,
    req_enum,
    req_int,
    req_str,
)
from store import base_entity, db, rows, touch

bp = Blueprint("tracers", __name__)

ACTIONS = ("START", "COMPLETE", "ABORT")
OCCUPYING_STATES = ("SCHEDULED", "IN_PROGRESS")


@bp.post("/accreditation/mock-tracers")
def schedule_tracer():
    require_roles("TracerSurveyor", "AccreditationDirector")
    b = body()
    unit_id = req_str(b, "unit_id")
    chapter_id = req_str(b, "chapter_id")
    tracer_type = req_enum(b, "tracer_type", calc.TRACER_TYPES)
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")
    expected_unit_version = req_int(b, "expected_unit_version")

    # Rung 6 — body foreign keys, unit before chapter.
    unit = get_unit(unit_id)
    chapter = get_chapter(chapter_id)

    # Rung 8
    if expected_unit_version != unit["version"]:
        raise ApiError("ERR_STALE_UNIT_VERSION")

    # Rung 9
    if not window_end > window_start:
        raise ApiError("ERR_INVALID_INTERVAL")

    # Rung 23
    if unit["posture"] != "OPEN":
        raise ApiError("ERR_UNIT_POSTURE_RESTRICTED")

    # Rung 24
    if cascade.immediate_threat_active():
        raise ApiError("ERR_IMMEDIATE_THREAT_ACTIVE")

    # Rung 28 — half-open interval plus a 60 minute trailing buffer, minute-exact.
    new_start = calc.floor_to_minute(window_start)
    new_end = calc.floor_to_minute(window_end)
    buffer = timedelta(minutes=calc.TURNAROUND_BUFFER_MINUTES)
    for existing in rows(db.tracers):
        if existing["unit_id"] != unit["id"] or existing["state"] not in OCCUPYING_STATES:
            continue
        ex_start = calc.floor_to_minute(existing["window_start"])
        ex_end = calc.floor_to_minute(existing["window_end"])
        if new_start < ex_end + buffer and new_end > ex_start:
            raise ApiError("ERR_TRACER_WINDOW_CONFLICT")

    # Rung 44
    if chapter["mapped_standard_count"] < 1:
        raise ApiError("ERR_CHAPTER_NOT_MAPPED")

    tracer = base_entity("MockTracer")
    tracer.update(
        {
            "unit_id": unit["id"],
            "chapter_id": chapter["id"],
            "tracer_type": tracer_type,
            "window_start": window_start,
            "window_end": window_end,
            "state": "SCHEDULED",
            "scored_weight": Decimal("0"),
            "earned_weight": Decimal("0"),
            "tracer_score": Decimal("0.00"),
            "contributes_to_readiness": False,
            "started_at": None,
            "completed_at": None,
            "abort_reason": None,
        }
    )
    db.tracers[tracer["id"]] = tracer

    unit["scheduled_tracer_count"] += 1
    touch(unit)

    return object_response(serialize.tracer(tracer), 201)


@bp.get("/accreditation/mock-tracers/<tracer_id>")
def read_tracer(tracer_id):
    require_roles(*ALL_ROLES)
    tracer = get_tracer(tracer_id)
    return object_response(serialize.tracer(tracer))


@bp.get("/accreditation/mock-tracers")
def list_tracers():
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    result = rows(db.tracers)
    unit_id = request.args.get("unit_id")
    chapter_id = request.args.get("chapter_id")
    state = request.args.get("state")
    if unit_id:
        result = [t for t in result if t["unit_id"] == unit_id]
    if chapter_id:
        result = [t for t in result if t["chapter_id"] == chapter_id]
    if state:
        result = [t for t in result if t["state"] == state]
    items, total = page(result, limit, offset)
    return array_response([serialize.tracer(t) for t in items], limit, offset, total)


@bp.post("/accreditation/mock-tracers/<tracer_id>/transition")
def transition_tracer(tracer_id):
    require_roles("TracerSurveyor")
    b = body()
    action = req_enum(b, "action", ACTIONS)
    abort_reason = opt_str(b, "abort_reason")

    tracer = get_tracer(tracer_id)
    state = tracer["state"]
    unit = db.units[tracer["unit_id"]]

    # Rung 13
    if action == "START" and state != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if action == "ABORT" and state not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # Rung 14
    if action == "COMPLETE" and state != "IN_PROGRESS":
        raise ApiError("ERR_TRACER_NOT_IN_PROGRESS")

    # Rung 23
    if action == "START" and unit["posture"] != "OPEN":
        raise ApiError("ERR_UNIT_POSTURE_RESTRICTED")

    # Rung 30
    if action == "START" and db.clock < tracer["window_start"]:
        raise ApiError("ERR_TRACER_WINDOW_NOT_STARTED")

    observations = cascade.observations_of_tracer(tracer["id"])

    # Rung 38
    if action == "COMPLETE" and not observations:
        raise ApiError("ERR_NO_OBSERVATIONS_RECORDED")

    if action == "START":
        tracer["state"] = "IN_PROGRESS"
        tracer["started_at"] = db.clock
        touch(tracer)
        unit["scheduled_tracer_count"] = max(0, unit["scheduled_tracer_count"] - 1)
        touch(unit)
        cascade.recompute_unit_readiness(unit)
    elif action == "COMPLETE":
        scored, earned, score, contributes = calc.mock_tracer_score(observations)
        tracer["state"] = "COMPLETED"
        tracer["scored_weight"] = scored
        tracer["earned_weight"] = earned
        tracer["tracer_score"] = score
        tracer["contributes_to_readiness"] = contributes
        tracer["completed_at"] = db.clock
        touch(tracer)

        seen = []
        for obs in observations:
            if obs["result"] == "NON_COMPLIANT" and obs["standard_id"] not in seen:
                seen.append(obs["standard_id"])
        for standard_id in seen:
            standard = db.standards.get(standard_id)
            if standard is not None:
                cascade.mark_standard_deficient(standard)

        cascade.recompute_unit_readiness(unit)
    else:
        tracer["state"] = "ABORTED"
        tracer["abort_reason"] = abort_reason
        touch(tracer)
        if state == "SCHEDULED":
            unit["scheduled_tracer_count"] = max(0, unit["scheduled_tracer_count"] - 1)
            touch(unit)
        cascade.recompute_unit_readiness(unit)

    return object_response(serialize.tracer(tracer))


@bp.post("/accreditation/mock-tracers/<tracer_id>/observations")
def record_observation(tracer_id):
    require_roles("TracerSurveyor")
    b = body()
    standard_id = req_str(b, "standard_id")
    result = req_enum(b, "result", calc.OBSERVATION_RESULTS)
    weight = opt_number(b, "weight", default=Decimal("1"), gt=0)
    note = opt_str(b, "note")

    # Rung 5
    tracer = get_tracer(tracer_id)
    # Rung 6
    standard = get_standard(standard_id)

    # Rung 14
    if tracer["state"] != "IN_PROGRESS":
        raise ApiError("ERR_TRACER_NOT_IN_PROGRESS")

    # Rung 43
    if standard["chapter_id"] != tracer["chapter_id"]:
        raise ApiError("ERR_STANDARD_CHAPTER_MISMATCH")

    observation = base_entity("TracerObservation", versioned=False)
    observation.update(
        {
            "mock_tracer_id": tracer["id"],
            "standard_id": standard["id"],
            "result": result,
            "weight": weight,
            "note": note,
            "recorded_by_user_id": g.user_id,
        }
    )
    db.observations[observation["id"]] = observation
    return object_response(serialize.observation(observation), 201)


@bp.get("/accreditation/mock-tracers/<tracer_id>/observations")
def list_tracer_observations(tracer_id):
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    tracer = get_tracer(tracer_id)
    result_filter = request.args.get("result")
    result = [o for o in rows(db.observations) if o["mock_tracer_id"] == tracer["id"]]
    if result_filter:
        result = [o for o in result if o["result"] == result_filter]
    items, total = page(result, limit, offset)
    return array_response([serialize.observation(o) for o in items], limit, offset, total)


@bp.get("/accreditation/standards/<standard_id>/tracer-observations")
def list_standard_observations(standard_id):
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    standard = get_standard(standard_id)
    result_filter = request.args.get("result")
    result = [o for o in rows(db.observations) if o["standard_id"] == standard["id"]]
    if result_filter:
        result = [o for o in result if o["result"] == result_filter]
    items, total = page(result, limit, offset)
    return array_response([serialize.observation(o) for o in items], limit, offset, total)
