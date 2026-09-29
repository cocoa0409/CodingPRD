"""Follow-up episodes, clinic slots and rescreen appointments."""
from flask import Blueprint, request

import calc
import db
import resolve
import response
import serialize
import services
import validate
from db import store
from errors import ApiError
from middleware import (ALL_ROLES, FACILITY_ADMIN, NAVIGATOR, PROGRAM_ADMIN,
                        endpoint, identity)

bp = Blueprint("followup", __name__)

SLOT_TYPE_FOR_EPISODE = {
    "INITIAL_SCREEN": "RESCREEN",
    "RESCREEN": "RESCREEN",
    "DIAGNOSTIC": "DIAGNOSTIC",
}


# --- follow-up episodes -----------------------------------------------------
@bp.post("/follow-up-episodes")
@endpoint([PROGRAM_ADMIN, FACILITY_ADMIN, NAVIGATOR])
def create_episode():
    body = validate.body()
    infant_id = validate.id_field(body, "infant_id")
    episode_type = validate.enum_field(body, "episode_type", validate.EPISODE_TYPES)
    expected_infant_version = validate.int_field(body, "expected_infant_version")
    supersedes_episode_id = validate.id_field(body, "supersedes_episode_id",
                                              required=False)
    linked = resolve.fks({"infant_id": infant_id,
                          "supersedes_episode_id": supersedes_episode_id})
    infant = linked["infant_id"]
    supersedes = linked.get("supersedes_episode_id")
    identity(facility_id=infant["birth_facility_id"])
    if expected_infant_version != infant["version"]:
        raise ApiError("ERR_STALE_INFANT_VERSION")
    if supersedes is not None and supersedes["status"] not in ("PENDING_SCHEDULING",
                                                              "SCHEDULED"):
        raise ApiError("ERR_EPISODE_NOT_SCHEDULABLE")
    if supersedes is not None and supersedes["infant_id"] != infant["id"]:
        raise ApiError("ERR_LINKAGE_MISMATCH")
    remaining_open = [e for e in calc.open_episodes(infant["id"])
                      if supersedes is None or e["id"] != supersedes["id"]]
    if remaining_open:
        raise ApiError("ERR_ACTIVE_EPISODE_EXISTS")

    if supersedes is not None:
        services.close_episode(supersedes, "SUPERSEDED", "SUPERSEDED")
    row = services.create_episode(
        infant, episode_type,
        supersedes_episode_id=supersedes["id"] if supersedes else None)
    if episode_type == "DIAGNOSTIC" and infant["screening_status"] == "REFERRED":
        infant["screening_status"] = "DIAGNOSTIC_IN_PROGRESS"
    db.touch(infant)
    services.recompute_risk(infant)
    return response.single(row, serialize.episode, 201)


@bp.post("/follow-up-episodes/<episode_id>/close")
@endpoint([PROGRAM_ADMIN, NAVIGATOR])
def close_episode(episode_id):
    body = validate.body()
    closure_reason = validate.enum_field(body, "closure_reason",
                                         validate.ADMIN_CLOSURE_REASONS)
    episode = resolve.one("episode", episode_id)
    infant = store.infants.get(episode["infant_id"])
    identity(facility_id=infant["birth_facility_id"] if infant else None)
    if episode["status"] not in ("PENDING_SCHEDULING", "SCHEDULED"):
        raise ApiError("ERR_EPISODE_NOT_SCHEDULABLE")
    services.close_episode(episode, "CLOSED_DECLINED", closure_reason)
    if infant is not None:
        services.recompute_risk(infant)
    return response.single(episode, serialize.episode)


@bp.get("/follow-up-episodes/<episode_id>")
@endpoint(ALL_ROLES)
def get_episode(episode_id):
    row = resolve.one("episode", episode_id)
    identity()
    return response.single(row, serialize.episode)


@bp.get("/follow-up-episodes")
@endpoint(ALL_ROLES)
def list_episodes():
    limit, offset = response.pagination()
    identity()
    rows = list(store.episodes.values())
    for field in ("infant_id", "supersedes_episode_id", "status", "episode_type",
                  "owner_scope", "timeliness_status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return response.listing(db.sort_rows(rows), serialize.episode, limit, offset)


# --- clinic slots -----------------------------------------------------------
@bp.post("/clinic-slots")
@endpoint([PROGRAM_ADMIN, FACILITY_ADMIN])
def create_slot():
    body = validate.body()
    facility_id = validate.id_field(body, "facility_id")
    provider_id = validate.id_field(body, "provider_id")
    starts_at = validate.datetime_field(body, "starts_at")
    ends_at = validate.datetime_field(body, "ends_at")
    slot_type = validate.enum_field(body, "slot_type", validate.SLOT_TYPES)
    total_capacity = validate.int_field(body, "total_capacity", required=False,
                                        minimum=1, maximum=20, default=1)
    linked = resolve.fks({"facility_id": facility_id, "provider_id": provider_id})
    facility = linked["facility_id"]
    provider = linked["provider_id"]
    identity(facility_id=facility["id"])
    if provider["credential_status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_CREDENTIALED")
    if provider["provider_type"] != "AUDIOLOGIST":
        raise ApiError("ERR_PROVIDER_TYPE_MISMATCH")
    if facility["facility_type"] != "AUDIOLOGY_CLINIC":
        raise ApiError("ERR_FACILITY_TYPE_MISMATCH")
    if ends_at <= starts_at:
        raise ApiError("ERR_INVALID_WINDOW")
    for other in store.slots.values():
        if other["provider_id"] != provider["id"]:
            continue
        if starts_at < other["ends_at"] and other["starts_at"] < ends_at:
            raise ApiError("ERR_SLOT_OVERLAP")
    row = db.base_row()
    row.update({
        "facility_id": facility["id"],
        "provider_id": provider["id"],
        "starts_at": starts_at,
        "ends_at": ends_at,
        "slot_type": slot_type,
        "total_capacity": total_capacity,
    })
    store.slots[row["id"]] = row
    return response.single(row, serialize.slot, 201)


@bp.get("/clinic-slots/<slot_id>")
@endpoint(ALL_ROLES)
def get_slot(slot_id):
    row = resolve.one("slot", slot_id)
    identity()
    return response.single(row, serialize.slot)


@bp.get("/clinic-slots")
@endpoint(ALL_ROLES)
def list_slots():
    limit, offset = response.pagination()
    identity()
    rows = list(store.slots.values())
    for field in ("facility_id", "provider_id", "slot_type"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if calc.slot_status(r) == status]
    return response.listing(db.sort_rows(rows), serialize.slot, limit, offset)


# --- rescreen appointments --------------------------------------------------
@bp.post("/rescreen-appointments")
@endpoint([PROGRAM_ADMIN, FACILITY_ADMIN, NAVIGATOR])
def create_appointment():
    body = validate.body()
    episode_id = validate.id_field(body, "episode_id")
    slot_id = validate.id_field(body, "slot_id")
    interpreter_needed = validate.bool_field(body, "interpreter_needed",
                                             required=False, default=False)
    linked = resolve.fks({"episode_id": episode_id, "slot_id": slot_id})
    episode = linked["episode_id"]
    slot = linked["slot_id"]
    infant = store.infants.get(episode["infant_id"])
    identity(facility_id=infant["birth_facility_id"] if infant else None)
    if episode["status"] != "PENDING_SCHEDULING":
        raise ApiError("ERR_EPISODE_NOT_SCHEDULABLE")
    if slot["slot_type"] != SLOT_TYPE_FOR_EPISODE[episode["episode_type"]]:
        raise ApiError("ERR_SLOT_TYPE_MISMATCH")
    if slot["starts_at"] <= db.now():
        raise ApiError("ERR_SLOT_IN_PAST")
    for other in calc.infant_appointments(episode["infant_id"]):
        if other["status"] not in ("BOOKED", "ATTENDED"):
            continue
        other_slot = store.slots.get(other["slot_id"])
        if other_slot is None:
            continue
        gap = abs((other_slot["starts_at"] - slot["starts_at"]).total_seconds())
        if gap < calc.FAMILY_BURDEN_SECONDS:
            raise ApiError("ERR_FAMILY_BURDEN_BUFFER")
    if calc.attempt_count(episode) >= calc.ATTEMPT_CEILING:
        raise ApiError("ERR_ATTEMPT_LIMIT_REACHED")
    if calc.slot_remaining(slot) < 1:
        raise ApiError("ERR_SLOT_FULL")
    task = None
    if interpreter_needed:
        task = services.mint_interpreter_task(infant, episode["id"])

    row = db.base_row()
    row.update({
        "episode_id": episode["id"],
        "slot_id": slot["id"],
        "infant_id": episode["infant_id"],
        "linked_navigation_task_id": task["id"] if task else None,
        "interpreter_needed": interpreter_needed,
        "status": "BOOKED",
        "disposition_reason": None,
    })
    store.appointments[row["id"]] = row
    episode["status"] = "SCHEDULED"
    db.touch(episode)
    if infant is not None:
        services.recompute_risk(infant)
    return response.single(row, serialize.appointment, 201)


@bp.post("/rescreen-appointments/<appointment_id>/close")
@endpoint([PROGRAM_ADMIN, FACILITY_ADMIN, NAVIGATOR])
def close_appointment(appointment_id):
    body = validate.body()
    disposition = validate.enum_field(body, "disposition",
                                      validate.APPOINTMENT_DISPOSITIONS)
    reason = validate.string_field(body, "reason", required=False)
    appointment = resolve.one("appointment", appointment_id)
    infant = store.infants.get(appointment["infant_id"])
    identity(facility_id=infant["birth_facility_id"] if infant else None)
    if appointment["status"] != "BOOKED":
        raise ApiError("ERR_APPOINTMENT_NOT_OPEN")

    appointment["status"] = disposition
    appointment["disposition_reason"] = reason
    db.touch(appointment)
    services.cancel_linked_interpreter_task(appointment)
    episode = store.episodes.get(appointment["episode_id"])
    if episode is not None and episode["status"] == "SCHEDULED":
        episode["status"] = "PENDING_SCHEDULING"
        db.touch(episode)
    if infant is not None:
        services.recompute_risk(infant)
    return response.single(appointment, serialize.appointment)


@bp.get("/rescreen-appointments/<appointment_id>")
@endpoint(ALL_ROLES)
def get_appointment(appointment_id):
    row = resolve.one("appointment", appointment_id)
    identity()
    return response.single(row, serialize.appointment)


@bp.get("/rescreen-appointments")
@endpoint(ALL_ROLES)
def list_appointments():
    limit, offset = response.pagination()
    identity()
    rows = list(store.appointments.values())
    for field in ("episode_id", "slot_id", "infant_id",
                  "linked_navigation_task_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return response.listing(db.sort_rows(rows), serialize.appointment, limit, offset)
