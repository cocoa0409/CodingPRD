"""Inpatient units and bed reservations with lazy hold expiry (PRD 3.8)."""

from flask import Blueprint

import calc
import clock
import derived
import envelope
import errors
import ladder
import serializers
import store
from domain import beds as bed_service
from errors import fail
from routes.common import apply_filter, endpoint
from store import DB

bp = Blueprint("beds", __name__)

BED_READ_ROLES = ["ProgramAdmin", "AdmittingPhysician"]


@endpoint(bp, "/inpatient-units", ["POST"], ["ProgramAdmin"])
def create_unit(caller):
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, ["unit_code", "total_beds"])
    # rung 4c
    ladder.check_non_empty_string(body, "unit_code")
    ladder.check_integer_range(body, "total_beds", 1)
    ladder.check_unique("units", "unit_code", body["unit_code"])

    row = store.make_row("units", {
        "unit_code": body["unit_code"],
        "total_beds": body["total_beds"],
    })
    return envelope.ObjResult(row, serializers.inpatient_unit, 201)


@endpoint(bp, "/inpatient-units/<unit_id>", ["GET"], BED_READ_ROLES)
def get_unit(caller, unit_id):
    # rung 3
    unit = ladder.path_row("units", unit_id)
    # lazy expiry is evaluated the moment anyone looks
    bed_service.sweep_unit(unit_id)
    return envelope.ObjResult(unit, serializers.inpatient_unit, 200)


@endpoint(bp, "/bed-reservations", ["POST"], ["AdmittingPhysician"])
def create_reservation(caller):
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, ["unit_id", "episode_id", "expected_unit_version"])
    # rung 4c
    supplied_version = ladder.expected_version(body, "expected_unit_version")
    # rung 5 -- declared resource-type order: episode, then unit
    episode = ladder.body_episode(body)
    unit = ladder.body_unit(body)
    # rung 6
    ladder.check_occ(unit, supplied_version)
    # rung 7 -- there is deliberately no ACTIVE-only gate here
    ladder.require_state(episode["status"] != "DISCHARGED")
    # rung 14a -- stale holds are swept before capacity is judged
    bed_service.sweep_unit(unit["id"])
    held, occupied, available = derived.unit_bed_census(unit)
    if available < 1:
        fail(errors.ERR_NO_BEDS_AVAILABLE)

    held_at = clock.now_raw()
    reservation = store.make_row("reservations", {
        "unit_id": unit["id"],
        "episode_id": episode["id"],
        "status": "HELD",
        "held_at": held_at,
        "hold_expires_at": clock.plus_minutes(held_at, calc.BED_HOLD_MINUTES),
        "occupied_at": None,
    })
    # Holding a bed advances the UNIT's version by 1.
    store.touch(unit)
    return envelope.ObjResult(reservation, serializers.bed_reservation, 201)


@endpoint(bp, "/bed-reservations/<reservation_id>", ["GET"], BED_READ_ROLES)
def get_reservation(caller, reservation_id):
    # rung 3
    reservation = ladder.path_row("reservations", reservation_id)
    bed_service.expire_reservation_if_due(reservation)
    return envelope.ObjResult(reservation, serializers.bed_reservation, 200)


@endpoint(bp, "/bed-reservations", ["GET"], BED_READ_ROLES)
def list_reservations(caller):
    limit, offset = ladder.pagination_params()
    rows = list(DB.reservations.values())
    rows = apply_filter(rows, "unit_id")
    rows = apply_filter(rows, "episode_id")
    rows = apply_filter(rows, "status")
    return envelope.ListResult(store.ordered(rows), serializers.bed_reservation, limit, offset)
