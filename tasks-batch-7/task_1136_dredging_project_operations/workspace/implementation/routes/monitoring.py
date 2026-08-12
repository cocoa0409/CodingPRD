"""TurbidityReading and SpeciesSighting endpoints (PRD 3.6)."""
import uuid
from datetime import timedelta

from flask import Blueprint, g

from db import store
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_SPECIES_COOLDOWN_ACTIVE,
)
from middleware import require_roles, ALL_ROLES
from response import ok
from routes.common import list_response
from services import (
    serialize_reading,
    serialize_sighting,
    refresh_posture,
    shutdown_project_events,
    governing_permit,
)
from util import as_enum, as_int, as_str, check, get_body, parse_dt, req_present, touch

bp = Blueprint("monitoring", __name__)


def _cause_to_reason(cause):
    return {"SPECIES": "SPECIES", "TURBIDITY": "TURBIDITY"}.get(cause, "WINDOW")


# --- TurbidityReading -------------------------------------------------------

@bp.post("/turbidity-readings")
@require_roles("EnvironmentalMonitor")
def create_reading():
    body = get_body()
    project_id = body.get("project_id")
    if project_id is not None and project_id not in store.projects:
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    project_id = as_str(req_present(body, "project_id"), "project_id")
    value = as_int(req_present(body, "value_ntu"), "value_ntu")
    check(value >= 0, "value_ntu must be >= 0")
    taken = parse_dt(req_present(body, "taken_utc"), "taken_utc")
    rec = {
        "id": str(uuid.uuid4()),
        "project_id": project_id,
        "value_ntu": value,
        "taken_utc": taken,
        "recorded_by_user_id": g.user_id,
        "created_at": store.logical_now,
        "_seq": store.next_seq(),
    }
    store.readings[rec["id"]] = rec
    # Immediate posture recompute; a ceiling reading suspends the project and
    # auto-shuts ACTIVE events (reason TURBIDITY).
    posture, cause = refresh_posture(project_id)
    if posture == "SUSPENDED":
        shutdown_project_events(project_id, _cause_to_reason(cause))
    return ok(serialize_reading(rec), 201)


@bp.get("/turbidity-readings/<rid>")
@require_roles(*ALL_ROLES)
def get_reading(rid):
    reading = store.readings.get(rid)
    if reading is None:
        raise ApiError(ERR_NOT_FOUND, "TurbidityReading not found", 404)
    return ok(serialize_reading(reading))


@bp.get("/turbidity-readings")
@require_roles(*ALL_ROLES)
def list_readings():
    return list_response(store.readings, serialize_reading, ["project_id"])


# --- SpeciesSighting --------------------------------------------------------

@bp.post("/species-sightings")
@require_roles("EnvironmentalMonitor")
def create_sighting():
    body = get_body()
    project_id = body.get("project_id")
    if project_id is not None and project_id not in store.projects:
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    project_id = as_str(req_present(body, "project_id"), "project_id")
    species_class = as_enum(
        req_present(body, "species_class"),
        "species_class",
        ["FISH", "MAMMAL", "REPTILE", "BIRD"],
    )
    observed = parse_dt(req_present(body, "observed_utc"), "observed_utc")
    rec = {
        "id": str(uuid.uuid4()),
        "project_id": project_id,
        "species_class": species_class,
        "observed_utc": observed,
        "reported_by_user_id": g.user_id,
        "cleared_at": None,
        "status": "ACTIVE",
    }
    from util import new_entity

    new_entity(rec)
    store.sightings[rec["id"]] = rec
    # Cascade origin: posture -> SUSPENDED, ACTIVE events -> SHUTDOWN (SPECIES).
    posture, cause = refresh_posture(project_id)
    if posture == "SUSPENDED":
        shutdown_project_events(project_id, _cause_to_reason(cause))
    return ok(serialize_sighting(rec), 201)


@bp.get("/species-sightings/<sid>")
@require_roles(*ALL_ROLES)
def get_sighting(sid):
    sighting = store.sightings.get(sid)
    if sighting is None:
        raise ApiError(ERR_NOT_FOUND, "SpeciesSighting not found", 404)
    return ok(serialize_sighting(sighting))


@bp.get("/species-sightings")
@require_roles(*ALL_ROLES)
def list_sightings():
    return list_response(store.sightings, serialize_sighting, ["project_id", "status"])


@bp.post("/species-sightings/<sid>/clear")
@require_roles("EnvironmentalMonitor")
def clear_sighting(sid):
    sighting = store.sightings.get(sid)
    if sighting is None:
        raise ApiError(ERR_NOT_FOUND, "SpeciesSighting not found", 404)
    if sighting["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Only an ACTIVE sighting can be cleared", 409)
    # Temporal (class 9): cooldown from observed_utc over the governing permit's
    # standdown hours; equality allowed.
    permit = governing_permit(sighting["project_id"])
    if permit is None:
        issued = [
            p
            for p in store.permits.values()
            if p["project_id"] == sighting["project_id"] and p["status"] == "ISSUED"
        ]
        permit = max(issued, key=lambda p: p["window_end_utc"]) if issued else None
    standdown = permit["species_standdown_hours"] if permit else 0
    ready_at = sighting["observed_utc"] + timedelta(hours=standdown)
    if store.logical_now < ready_at:
        raise ApiError(
            ERR_SPECIES_COOLDOWN_ACTIVE,
            "Species standdown cooldown has not elapsed",
            409,
        )
    sighting["status"] = "CLEARED"
    sighting["cleared_at"] = store.logical_now
    touch(sighting)
    # Posture recompute; events are NOT auto-resumed (deliberate asymmetry).
    refresh_posture(sighting["project_id"])
    return ok(serialize_sighting(sighting))
