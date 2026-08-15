"""CA room endpoints: registration, schedule (OCC), seal, open, atmosphere
readings, disorder inspections, allocations, select-release (PRD 3.2, 3.3)."""
from decimal import Decimal

from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_LOT_INVALID_STATE,
    ERR_NO_RELEASABLE_ALLOCATIONS,
    ERR_O2_NOT_AT_SETPOINT,
    ERR_OPEN_DATE_NOT_FUTURE,
    ERR_ROOM_CAPACITY_EXCEEDED,
    ERR_ROOM_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_UNIQUE_CONSTRAINT_VIOLATION,
    ERR_VERSION_REQUIRED,
    ERR_INVALID_REQUEST,
)
from middleware import authorized, ALL_ROLES
from response import success_object
from routes.helpers import list_response, public, public_room, sorted_items
from services.core import new_record, touch
from services.domain import (
    DECAY_PRIORITY_THRESHOLD_PCT,
    O2_TOLERANCE_PCT,
    PRIORITY_OPEN_DAYS,
    PRIORITY_RELEASE_DAYS,
    ROOM_EMPTY_DAYS,
    bins_allocated,
    compute_release_score,
    recompute_room_scores,
    release_allocation,
    room_active_allocations,
)
from util import CLOCK, add_days, parse_dt, round_half_up
from validate import (
    check_body_fk, get_body, opt_datetime, opt_num, req_datetime, req_int,
    req_num, req_pct, req_str, require_path_resource,
)

bp = Blueprint("ca_rooms", __name__)


@bp.post("/ca-rooms")
def create_room():
    authorized(["Admin", "StorageOperator"])
    body = get_body()
    room_code = req_str(body, "room_code")
    bin_capacity = req_int(body, "bin_capacity", positive=True)
    o2_setpoint_pct = req_num(body, "o2_setpoint_pct")
    if o2_setpoint_pct < Decimal("0.1") or o2_setpoint_pct > Decimal("21.0"):
        raise_error(ERR_INVALID_REQUEST,
                    "o2_setpoint_pct must be within 0.1..21.0")
    for r in db["ca_rooms"].values():
        if r["room_code"] == room_code:
            raise_error(ERR_UNIQUE_CONSTRAINT_VIOLATION,
                        f"room_code already registered: {room_code}")
    rec = new_record("ca_rooms", {
        "room_code": room_code,
        "bin_capacity": bin_capacity,
        "o2_setpoint_pct": o2_setpoint_pct,
        "current_o2_pct": Decimal("20.9"),
        "atmosphere_alarm": False,
        "o2_excursion_count": 0,
        "disorder_index": Decimal("0"),
        "priority_release": False,
        "sealed_at": None,
        "planned_open_date": None,
        "actual_opened_at": None,
        "must_empty_by": None,
        "status": "AVAILABLE",
    })
    return success_object(public_room(rec), status=201)


@bp.get("/ca-rooms/<rid>")
def get_room(rid):
    authorized(list(ALL_ROLES))
    room = require_path_resource("ca_rooms", rid)
    return success_object(public_room(room))


@bp.put("/ca-rooms/<rid>/schedule")
def update_schedule(rid):
    authorized(["Admin", "StorageOperator"])
    room = require_path_resource("ca_rooms", rid)
    body = get_body()
    # Tier 5: shape of the optional fields.
    planned_open_date = opt_datetime(body, "planned_open_date")
    o2_setpoint_pct = opt_num(body, "o2_setpoint_pct")
    if o2_setpoint_pct is not None and (
            o2_setpoint_pct < Decimal("0.1") or o2_setpoint_pct > Decimal("21.0")):
        raise_error(ERR_INVALID_REQUEST,
                    "o2_setpoint_pct must be within 0.1..21.0")
    # Tier 6: OCC presence.
    if "expected_ca_room_version" not in body or body.get("expected_ca_room_version") is None:
        raise_error(ERR_VERSION_REQUIRED,
                    "expected_ca_room_version is required")
    expected = body.get("expected_ca_room_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST,
                    "expected_ca_room_version must be an integer")
    # Tier 7: OCC freshness.
    if expected != room["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_ca_room_version does not match the room's current version")
    # Tier 8: schedule updates allowed while AVAILABLE, FILLING, or SEALED.
    if room["status"] not in ("AVAILABLE", "FILLING", "SEALED"):
        raise_error(ERR_ROOM_INVALID_STATE,
                    f"schedule update not allowed while room is {room['status']}")
    if planned_open_date is not None:
        room["planned_open_date"] = planned_open_date
    if o2_setpoint_pct is not None:
        room["o2_setpoint_pct"] = o2_setpoint_pct
    touch(room)
    return success_object(public_room(room))


@bp.post("/ca-rooms/<rid>/seal")
def seal_room(rid):
    authorized(["Admin", "StorageOperator"])
    room = require_path_resource("ca_rooms", rid)
    body = get_body()
    planned_open_date = req_datetime(body, "planned_open_date")
    # Tier 8: FILLING with at least one allocated bin.
    if room["status"] != "FILLING" or bins_allocated(room["id"]) < 1:
        raise_error(ERR_ROOM_INVALID_STATE,
                    "seal requires a FILLING room with at least one allocated bin")
    # Tier 9 (safety): exact decimal comparison; equality is within tolerance.
    if abs(room["current_o2_pct"] - room["o2_setpoint_pct"]) > O2_TOLERANCE_PCT:
        raise_error(ERR_O2_NOT_AT_SETPOINT,
                    "current_o2_pct is outside the tolerance of o2_setpoint_pct")
    # Tier 10 (temporal): planned_open_date strictly after the logical clock.
    if parse_dt(planned_open_date) <= CLOCK.now():
        raise_error(ERR_OPEN_DATE_NOT_FUTURE,
                    "planned_open_date must be strictly after the current logical clock")
    room["sealed_at"] = CLOCK.now_iso()
    room["planned_open_date"] = planned_open_date
    room["status"] = "SEALED"
    touch(room)
    return success_object(public_room(room))


@bp.post("/ca-rooms/<rid>/open")
def open_room(rid):
    authorized(["Admin", "StorageOperator"])
    room = require_path_resource("ca_rooms", rid)
    get_body()  # tolerate an empty/absent body
    if room["status"] != "SEALED":
        raise_error(ERR_ROOM_INVALID_STATE,
                    f"open requires a SEALED room, found {room['status']}")
    now = CLOCK.now_iso()
    room["actual_opened_at"] = now
    room["must_empty_by"] = add_days(now, ROOM_EMPTY_DAYS)
    room["status"] = "OPENED"
    touch(room)
    # Cascade hop 1 (room -> allocations): tighten deadlines, recompute scores.
    for alloc in room_active_allocations(room["id"]):
        changed = False
        if parse_dt(room["must_empty_by"]) < parse_dt(alloc["must_release_by"]):
            alloc["must_release_by"] = room["must_empty_by"]
            changed = True
        new_score = compute_release_score(room, alloc)
        if new_score != alloc["release_priority_score"]:
            alloc["release_priority_score"] = new_score
            changed = True
        if changed:
            touch(alloc)
    return success_object(public_room(room))


@bp.post("/ca-rooms/<rid>/atmosphere-readings")
def record_reading(rid):
    authorized(["Admin", "StorageOperator"])
    room = require_path_resource("ca_rooms", rid)
    body = get_body()
    o2_pct = req_pct(body, "o2_pct")
    room["current_o2_pct"] = o2_pct
    flipped = False
    # Alarm semantics apply only while the room is SEALED.
    if room["status"] == "SEALED":
        excursion = abs(o2_pct - room["o2_setpoint_pct"]) > O2_TOLERANCE_PCT
        if excursion and not room["atmosphere_alarm"]:
            room["atmosphere_alarm"] = True
            room["o2_excursion_count"] += 1
            flipped = True
        elif not excursion and room["atmosphere_alarm"]:
            room["atmosphere_alarm"] = False
            flipped = True
    touch(room)
    if flipped:
        recompute_room_scores(room)
    return success_object(public_room(room))


@bp.post("/ca-rooms/<rid>/inspections")
def create_inspection(rid):
    authorized(["Admin", "StorageOperator"])
    room = require_path_resource("ca_rooms", rid)
    body = get_body()
    scald_pct = req_pct(body, "scald_pct")
    bitter_pit_pct = req_pct(body, "bitter_pit_pct")
    decay_pct = req_pct(body, "decay_pct")
    if room["status"] not in ("SEALED", "OPENED"):
        raise_error(ERR_ROOM_INVALID_STATE,
                    "inspections require a SEALED or OPENED room")
    now = CLOCK.now_iso()
    disorder_index = round_half_up(
        Decimal("0.2") * scald_pct
        + Decimal("0.3") * bitter_pit_pct
        + Decimal("0.5") * decay_pct, 2)
    insp = new_record("inspections", {
        "room_id": room["id"],
        "inspected_at": now,
        "scald_pct": scald_pct,
        "bitter_pit_pct": bitter_pit_pct,
        "decay_pct": decay_pct,
        "disorder_index": disorder_index,
    }, versioned=False)

    # Room update: latest disorder index; priority-release cascade at threshold.
    room["disorder_index"] = disorder_index
    fires = decay_pct >= DECAY_PRIORITY_THRESHOLD_PCT
    if fires:
        room["priority_release"] = True
        candidate = add_days(now, PRIORITY_OPEN_DAYS)
        if room["planned_open_date"] is None or \
                parse_dt(candidate) < parse_dt(room["planned_open_date"]):
            room["planned_open_date"] = candidate
    touch(room)
    # Cascade hop 2 (room -> allocations): deadline tightening + score recompute.
    for alloc in room_active_allocations(room["id"]):
        changed = False
        if fires:
            candidate = add_days(now, PRIORITY_RELEASE_DAYS)
            if parse_dt(candidate) < parse_dt(alloc["must_release_by"]):
                alloc["must_release_by"] = candidate
                changed = True
        new_score = compute_release_score(room, alloc)
        if new_score != alloc["release_priority_score"]:
            alloc["release_priority_score"] = new_score
            changed = True
        if changed:
            touch(alloc)
    return success_object(public(insp), status=201)


@bp.get("/ca-rooms/<rid>/inspections")
def list_inspections(rid):
    authorized(list(ALL_ROLES))
    require_path_resource("ca_rooms", rid)
    items = [i for i in sorted_items("inspections") if i["room_id"] == rid]
    return list_response(items)


@bp.post("/ca-rooms/<rid>/allocations")
def create_allocation(rid):
    authorized(["Admin", "StorageOperator"])
    room = require_path_resource("ca_rooms", rid)
    body = get_body()
    # Tier 4: body-supplied FK existence.
    lot = check_body_fk("lots", body.get("lot_id"), "lot_id")
    # Tier 5: shape.
    lot_id = req_str(body, "lot_id")
    bins = req_int(body, "bins", positive=True)
    if lot is None:
        lot = db["lots"][lot_id]
    # Tier 8 (fixed order: lot before room).
    if lot["status"] not in ("RECEIVED", "PRESIZED"):
        raise_error(ERR_LOT_INVALID_STATE,
                    f"allocation requires a RECEIVED or PRESIZED lot, found {lot['status']}")
    if room["status"] not in ("AVAILABLE", "FILLING", "OPENED"):
        raise_error(ERR_ROOM_INVALID_STATE,
                    f"allocation not allowed while room is {room['status']}")
    # Tier 11: aggregate bin capacity.
    if bins > room["bin_capacity"] - bins_allocated(room["id"]):
        raise_error(ERR_ROOM_CAPACITY_EXCEEDED,
                    "requested bins exceed the room's bins_free")
    now = CLOCK.now_iso()
    block = db["blocks"][lot["block_id"]]
    must_release_by = add_days(lot["received_at"], block["storage_life_days"])
    if room["status"] == "OPENED" and room["must_empty_by"] is not None:
        if parse_dt(room["must_empty_by"]) < parse_dt(must_release_by):
            must_release_by = room["must_empty_by"]
    alloc = new_record("allocations", {
        "room_id": room["id"],
        "lot_id": lot["id"],
        "bins": bins,
        "allocated_at": now,
        "must_release_by": must_release_by,
        "release_priority_score": Decimal("0"),
        "status": "ACTIVE",
        "released_at": None,
        "release_reason": None,
    })
    alloc["release_priority_score"] = compute_release_score(room, alloc)
    # Room: first allocation into an AVAILABLE room moves it to FILLING; an
    # OPENED room stays OPENED. bins_allocated grew -> the room is mutated.
    if room["status"] == "AVAILABLE":
        room["status"] = "FILLING"
    touch(room)
    # Lot: first ACTIVE allocation moves RECEIVED/PRESIZED -> IN_STORAGE.
    if lot["status"] in ("RECEIVED", "PRESIZED"):
        lot["status"] = "IN_STORAGE"
        touch(lot)
    return success_object(public(alloc), status=201)


@bp.post("/ca-rooms/<rid>/select-release")
def select_release(rid):
    authorized(["Admin", "StorageOperator"])
    room = require_path_resource("ca_rooms", rid)
    get_body()
    if room["status"] != "OPENED":
        raise_error(ERR_ROOM_INVALID_STATE,
                    f"select-release requires an OPENED room, found {room['status']}")
    candidates = room_active_allocations(room["id"])
    if not candidates:
        raise_error(ERR_NO_RELEASABLE_ALLOCATIONS,
                    "no ACTIVE allocations in this room")
    # Ranking: score DESC, allocated_at ASC, created_at ASC (insertion order).
    picked = min(
        candidates,
        key=lambda a: (
            -a["release_priority_score"],
            a["allocated_at"],
            a["created_at"],
            a["_seq"],
        ),
    )
    release_allocation(picked, room, "SELECTED")
    return success_object(public(picked))
