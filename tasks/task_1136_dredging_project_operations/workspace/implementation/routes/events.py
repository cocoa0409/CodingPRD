"""DredgeEvent endpoints (PRD 3.5): posture-gated creation, explicit resume,
shutdown accrual on resume/complete."""
import uuid
from decimal import Decimal

from flask import Blueprint

from db import store
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_REACH_NOT_DREDGABLE,
    ERR_POSTURE_SUSPENDED,
    ERR_POSTURE_RESTRICTED,
    ERR_EVENT_NOT_RESUMABLE,
    ERR_PLAN_NOT_APPROVED,
)
from middleware import require_roles, ALL_ROLES
from response import ok
from routes.common import list_response
from services import serialize_event, accrue_shutdown
from util import as_bool, as_str, get_body, new_entity, parse_dt, req_present, touch

bp = Blueprint("events", __name__)


@bp.post("/dredge-events")
@require_roles("ContractorOps")
def create_event():
    body = get_body()
    # Existence (class 3): reach_id then plant_id.
    reach_id = body.get("reach_id")
    if reach_id is not None and reach_id not in store.reaches:
        raise ApiError(ERR_NOT_FOUND, "Reach not found", 404)
    plant_id = body.get("plant_id")
    if plant_id is not None and plant_id not in store.plants:
        raise ApiError(ERR_NOT_FOUND, "DredgePlant not found", 404)
    reach_id = as_str(req_present(body, "reach_id"), "reach_id")
    plant_id = as_str(req_present(body, "plant_id"), "plant_id")
    started = parse_dt(req_present(body, "started_utc"), "started_utc")
    reduced_rate = False
    if body.get("reduced_rate") is not None:
        reduced_rate = as_bool(body["reduced_rate"], "reduced_rate")
    reach = store.reaches[reach_id]
    # State gate (class 6).
    if reach["status"] != "DREDGING":
        raise ApiError(ERR_REACH_NOT_DREDGABLE, "Reach is not DREDGING", 409)
    project = store.projects[reach["project_id"]]
    # Posture gates (class 7).
    if project["compliance_posture"] == "SUSPENDED":
        raise ApiError(
            ERR_POSTURE_SUSPENDED, "Project compliance posture is SUSPENDED", 409
        )
    if project["compliance_posture"] == "RESTRICTED" and reduced_rate is not True:
        raise ApiError(
            ERR_POSTURE_RESTRICTED,
            "RESTRICTED posture requires reduced_rate=true",
            409,
        )
    # Referenced-entity state (class 11): APPROVED plan for project+plant whose
    # half-open window covers started_utc (at/after start, strictly before end).
    covered = any(
        p["project_id"] == reach["project_id"]
        and p["plant_id"] == plant_id
        and p["status"] == "APPROVED"
        and p["planned_start_utc"] <= started < p["planned_end_utc"]
        for p in store.plans.values()
    )
    if not covered:
        raise ApiError(
            ERR_PLAN_NOT_APPROVED,
            "No APPROVED plan for this project+plant covers started_utc",
            409,
        )
    rec = new_entity(
        {
            "id": str(uuid.uuid4()),
            "reach_id": reach_id,
            "plant_id": plant_id,
            "started_utc": started,
            "reduced_rate": reduced_rate,
            "ended_utc": None,
            "status": "ACTIVE",
            "shutdown_reason": None,
            "last_shutdown_at": None,
            "shutdown_accumulated_hours": Decimal("0"),
            "_project_id": reach["project_id"],
        }
    )
    store.events[rec["id"]] = rec
    return ok(serialize_event(rec), 201)


def _get_event(eid):
    event = store.events.get(eid)
    if event is None:
        raise ApiError(ERR_NOT_FOUND, "DredgeEvent not found", 404)
    return event


@bp.get("/dredge-events/<eid>")
@require_roles(*ALL_ROLES)
def get_event(eid):
    return ok(serialize_event(_get_event(eid)))


@bp.get("/dredge-events")
@require_roles(*ALL_ROLES)
def list_events():
    return list_response(
        store.events, serialize_event, ["reach_id", "plant_id", "status"]
    )


@bp.post("/dredge-events/<eid>/complete")
@require_roles("ContractorOps")
def complete_event(eid):
    event = _get_event(eid)
    if event["status"] not in ("ACTIVE", "SHUTDOWN"):
        raise ApiError(
            ERR_INVALID_STATE, "Only an ACTIVE or SHUTDOWN event can be completed", 409
        )
    # Completing out of a shutdown first settles the open shutdown interval.
    accrue_shutdown(event)
    event["status"] = "COMPLETED"
    event["ended_utc"] = store.logical_now
    event["shutdown_reason"] = None
    event["last_shutdown_at"] = None
    touch(event)
    return ok(serialize_event(event))


@bp.post("/dredge-events/<eid>/resume")
@require_roles("ContractorOps")
def resume_event(eid):
    event = _get_event(eid)
    if event["status"] != "SHUTDOWN":
        raise ApiError(ERR_INVALID_STATE, "Only a SHUTDOWN event can be resumed", 409)
    project = store.projects[event["_project_id"]]
    # Posture gate (class 7).
    if project["compliance_posture"] == "SUSPENDED":
        raise ApiError(
            ERR_EVENT_NOT_RESUMABLE, "Project compliance posture is SUSPENDED", 409
        )
    if event["shutdown_reason"] == "EQUIPMENT":
        plant = store.plants[event["plant_id"]]
        if plant["status"] != "REGISTERED":
            raise ApiError(
                ERR_EVENT_NOT_RESUMABLE,
                "EQUIPMENT shutdown requires the plant to be REGISTERED",
                409,
            )
    accrue_shutdown(event)
    event["status"] = "ACTIVE"
    event["shutdown_reason"] = None
    event["last_shutdown_at"] = None
    touch(event)
    return ok(serialize_event(event))
