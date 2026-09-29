"""Housing inventory: buildings, floors, rooms, residents."""
from flask import Blueprint

import derive
import responses
import services
import store
import validators as V
from auth import endpoint
from constants import (
    API_PREFIX, CAMPUS_ZONES, CLASS_YEARS, CONSOLIDATION_MIN_VACANCY_RATE,
    POSTURES,
)
from errors import ApiError
from store import DB

DIRECTOR = ["ResidenceDirector"]
bp = Blueprint("housing", __name__)


# ------------------------------------------------------------- buildings
@bp.route("%s/buildings" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def create_building():
    body = V.body()
    name = V.s_str(body, "name")
    code = V.s_str(body, "code", pattern=r"^[A-Z0-9]{2,8}$")
    zone = V.s_enum(body, "campus_zone", CAMPUS_ZONES)
    enabled = V.s_bool(body, "break_housing_enabled", default=False)
    for other in store.all_rows("buildings"):
        if other["code"] == code:
            raise ApiError("ERR_DUPLICATE_BUILDING_CODE")
    row = store.insert("buildings", "Building", {
        "name": name,
        "code": code,
        "campus_zone": zone,
        "break_housing_enabled": bool(enabled),
        "posture": "OPEN",
        "closure_reason": None,
        "last_posture_change_at": None,
    })
    return responses.obj(row, 201)


@bp.route("%s/buildings/<building_id>/posture" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def building_posture(building_id):
    building = V.must_get("Building", building_id)
    body = V.body()
    target = V.s_enum(body, "target_posture", POSTURES)
    reason = V.s_str(body, "reason", required=False)
    if target == "EMERGENCY_CLOSED" and not (reason and reason.strip()):
        raise ApiError("ERR_INVALID_REQUEST", "A non-empty reason is required.")
    current = building["posture"]
    pair = (current, target)
    if pair == ("OPEN", "RESTRICTED"):
        building["posture"] = "RESTRICTED"
        building["closure_reason"] = reason
        building["last_posture_change_at"] = store.now_iso()
    elif pair == ("RESTRICTED", "OPEN"):
        building["posture"] = "OPEN"
        building["closure_reason"] = None
        building["last_posture_change_at"] = store.now_iso()
    elif pair in (("OPEN", "EMERGENCY_CLOSED"), ("RESTRICTED", "EMERGENCY_CLOSED")):
        services.close_building(building, reason)
    elif pair == ("EMERGENCY_CLOSED", "OPEN"):
        services.reopen_building(building)
    else:
        raise ApiError("ERR_INVALID_POSTURE_TRANSITION")
    return responses.obj(building)


@bp.route("%s/buildings/<building_id>/consolidation" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def consolidation(building_id):
    building = V.must_get("Building", building_id)
    body = V.body()
    mode = V.s_enum(body, "mode", ("PLAN", "EXECUTE"))
    services.posture_gate(building)
    census = derive.occupancy_census(building)
    if census["occupied_beds"] == 0:
        raise ApiError("ERR_CENSUS_EMPTY")
    if census["vacancy_rate"] < float(CONSOLIDATION_MIN_VACANCY_RATE):
        raise ApiError("ERR_CONSOLIDATION_NOT_WARRANTED")

    rooms = derive.rooms_of_building(building["id"])
    occ = {r["id"]: derive.room_occupied_beds(r) for r in rooms}

    sources = [r for r in rooms
               if r["status"] == "OCCUPIED" and 1 <= occ[r["id"]] < r["bed_capacity"]]
    sources.sort(key=lambda r: (occ[r["id"]], -r["bed_capacity"], r["created_at"], r["_seq"]))

    targets = [r for r in rooms
               if r["status"] in ("AVAILABLE", "OCCUPIED") and occ[r["id"]] < r["bed_capacity"]]
    targets.sort(key=lambda r: (-occ[r["id"]], -r["bed_capacity"], r["created_at"], r["_seq"]))

    roster = {r["id"]: [] for r in rooms}
    for student in store.all_rows("students"):
        room_id = student.get("current_room_id")
        if room_id in roster:
            roster[room_id].append(student)

    emptied = []
    emptied_ids = set()
    moves = []
    sim = dict(occ)
    for source in sources:
        occupants = sorted(roster[source["id"]],
                           key=lambda s: (s["created_at"], s["_seq"]))
        if not occupants:
            continue
        temp = dict(sim)
        tentative = []
        placeable = True
        for student in occupants:
            chosen = None
            for target in targets:
                if target["id"] == source["id"] or target["id"] in emptied_ids:
                    continue
                if temp[target["id"]] < target["bed_capacity"]:
                    chosen = target
                    break
            if chosen is None:
                placeable = False
                break
            temp[chosen["id"]] += 1
            temp[source["id"]] -= 1
            tentative.append((student, chosen))
        if not placeable:
            continue
        sim = temp
        emptied.append(source)
        emptied_ids.add(source["id"])
        moves.extend(tentative)
        roster[source["id"]] = []
        for student, target in tentative:
            roster[target["id"]].append(student)

    executed = 0
    if mode == "EXECUTE":
        for student, target in moves:
            student["current_room_id"] = target["id"]
            student["housing_status"] = "ASSIGNED"
        for room in rooms:
            services.sync_room_status(room)
        for source in emptied:
            source["status"] = "CONSOLIDATED"
        executed = len(moves)

    after = derive.occupancy_census(building)
    return responses.raw({
        "mode": mode,
        "planned_move_count": len(moves),
        "executed_move_count": executed,
        "vacated_room_ids": [r["id"] for r in emptied],
        "moved_student_ids": [s["id"] for s, _t in moves],
        "occupied_beds_after": after["occupied_beds"],
        "vacancy_rate_before": census["vacancy_rate"],
    })


# ----------------------------------------------------------------- floors
@bp.route("%s/floors" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def create_floor():
    body = V.body()
    building_id = V.s_id(body, "building_id")
    number = V.s_int(body, "floor_number", 1, 30)
    required = V.s_int(body, "required_programs_per_term", 1, 12, required=False, default=4)
    building = store.get("buildings", building_id)
    if building is None:
        raise ApiError("ERR_BUILDING_NOT_FOUND")
    for other in store.all_rows("floors"):
        if other["building_id"] == building_id and other["floor_number"] == number:
            raise ApiError("ERR_DUPLICATE_FLOOR_NUMBER")
    row = store.insert("floors", "Floor", {
        "building_id": building_id,
        "floor_number": number,
        "required_programs_per_term": required,
        "programming_budget_cents": 0,
        "programming_frozen": False,
    })
    return responses.obj(row, 201)


@bp.route("%s/floors/<floor_id>/budget-allocations" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def budget_allocation(floor_id):
    floor = V.must_get("Floor", floor_id)
    body = V.body()
    amount = V.s_int(body, "amount_cents", 0)
    V.s_str(body, "term_code")
    floor["programming_budget_cents"] += amount
    return responses.obj(floor)


# ------------------------------------------------------------------ rooms
@bp.route("%s/rooms" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def create_room():
    body = V.body()
    floor_id = V.s_id(body, "floor_id")
    number = V.s_str(body, "room_number")
    capacity = V.s_int(body, "bed_capacity", 1, 4)
    year = V.s_int(body, "last_renovation_year", 1950, 2100)
    floor = store.get("floors", floor_id)
    if floor is None:
        raise ApiError("ERR_FLOOR_NOT_FOUND")
    for other in store.all_rows("rooms"):
        if other["floor_id"] == floor_id and other["room_number"] == number:
            raise ApiError("ERR_DUPLICATE_ROOM_NUMBER")
    row = store.insert("rooms", "Room", {
        "floor_id": floor_id,
        "room_number": number,
        "bed_capacity": capacity,
        "last_renovation_year": year,
        "status": "AVAILABLE",
        "pre_closure_status": None,
    })
    return responses.obj(row, 201)


@bp.route("%s/rooms/<room_id>/status" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def room_status(room_id):
    room = V.must_get("Room", room_id)
    body = V.body()
    target = V.s_enum(body, "target_status", ("OFFLINE", "AVAILABLE"))
    V.s_str(body, "reason", required=False)
    if target == "OFFLINE":
        if room["status"] not in ("AVAILABLE", "OCCUPIED"):
            raise ApiError("ERR_ROOM_NOT_AVAILABLE")
        services.take_room_offline(room, cascade=False)
    else:
        if room["status"] != "OFFLINE":
            raise ApiError("ERR_ROOM_NOT_AVAILABLE")
        if derive.room_occupied_beds(room) != 0:
            raise ApiError("ERR_ROOM_AT_CAPACITY")
        room["status"] = "AVAILABLE"
        room["pre_closure_status"] = None
    return responses.obj(room)


# --------------------------------------------------------------- students
@bp.route("%s/students" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def create_student():
    body = V.body()
    full_name = V.s_str(body, "full_name")
    email = V.s_str(body, "email")
    class_year = V.s_enum(body, "class_year", CLASS_YEARS)
    hardship = V.s_bool(body, "financial_hardship_flag", default=False)
    for other in store.all_rows("students"):
        if other["email"] == email:
            raise ApiError("ERR_DUPLICATE_STUDENT_EMAIL")
    row = store.insert("students", "Student", {
        "full_name": full_name,
        "email": email,
        "class_year": class_year,
        "financial_hardship_flag": bool(hardship),
        "current_room_id": None,
        "housing_status": "UNASSIGNED",
        "break_housing_eligible": True,
    })
    return responses.obj(row, 201)


@bp.route("%s/students/<student_id>/room-assignment" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def room_assignment(student_id):
    student = V.must_get("Student", student_id)
    body = V.body()
    action = V.s_enum(body, "action", ("PLACE", "VACATE"))
    if action == "PLACE":
        room_id = V.s_id(body, "room_id")
        room = store.get("rooms", room_id)
        if room is None:
            raise ApiError("ERR_ROOM_NOT_FOUND")
        services.room_posture_gate(room)
        services.room_available_gate(room)
        previous = DB["rooms"].get(student.get("current_room_id"))
        student["current_room_id"] = room["id"]
        student["housing_status"] = "ASSIGNED"
        if previous is not None:
            services.sync_room_status(previous)
        services.sync_room_status(room)
    else:
        previous = DB["rooms"].get(student.get("current_room_id"))
        student["current_room_id"] = None
        student["housing_status"] = "UNASSIGNED"
        if previous is not None:
            services.sync_room_status(previous)
    return responses.obj(student)
