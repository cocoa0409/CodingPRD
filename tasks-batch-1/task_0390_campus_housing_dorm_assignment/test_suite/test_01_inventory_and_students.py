"""Inventory (buildings/rooms) and student creation, computed fields, and the
room optimistic-concurrency version guard.

Every test translates exactly one instance from the corner-design index.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    assert_building, assert_room, assert_student,
    create_building_payload, create_room_payload, create_student_payload,
    make_officer_headers,
    create_building, create_room,
    NON_EXISTENT_UUID,
)

OFFICER = make_officer_headers()


def test_create_building_returns_201_with_zero_counters(api):
    """PRD §3.1: "A freshly created building reports `total_bed_count` of 0 and
    `occupied_bed_count` of 0; both are derived rollups maintained thereafter
    per §2.5."
    PRD §2.4: "a `version`, an integer that starts at 1 on creation and increases
    by exactly 1 on every mutation."

    Design: Corner/entities/create_building_returns_201_with_computed_counters_zero
    """
    res = api.create_building(
        create_building_payload(name="Alpha Hall", building_type="SUITE"), OFFICER)
    building = validate_success(res, 201)
    assert_building(building)
    assert building["total_bed_count"] == 0
    assert building["occupied_bed_count"] == 0
    assert building["version"] == 1


def test_room_bed_capacity_computed_from_room_type(api):
    """PRD §3.1: "The `room_type` is one of `SINGLE`, `DOUBLE`, `TRIPLE`, or
    `SUITE_DOUBLE`, and it fixes the room's `bed_capacity`: a `SINGLE` has one
    bed, a `DOUBLE` has two, a `TRIPLE` has three, and a `SUITE_DOUBLE` has two."
    PRD §3.1: "A new room begins with `status` of `OPEN`, an `occupied_bed_count`
    of 0, and an `open_incident_count` of 0."

    Design: Corner/entities/room_bed_capacity_computed_from_room_type
    """
    building = create_building(name="Cap Build", building_type="TRADITIONAL")
    res = api.create_room(
        building["id"],
        create_room_payload(room_number="X1", room_type="TRIPLE",
                            gender_inclusivity="ALL_GENDER"),
        OFFICER)
    room = validate_success(res, 201)
    assert_room(room)
    assert room["bed_capacity"] == 3
    assert room["status"] == "OPEN"
    assert room["occupied_bed_count"] == 0


def test_create_student_invalid_enum_class_year_rejected(api):
    """PRD §2.8: "Request well-formedness comes fourth: a missing required field,
    an invalid enum member, or an out-of-range integer yields
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_student_invalid_enum_class_year_rejected
    """
    res = api.create_student(
        create_student_payload(full_name="Bad Enum", class_year="GRAD",
                               gender_identity="MALE", lottery_number=1),
        OFFICER)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_get_room_nonexistent_returns_not_found(api):
    """PRD §2.8: "Existence comes third: any referenced resource that does not
    exist, validated left to right across the path and body, yields
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_room_nonexistent_returns_not_found
    """
    res = api.get_room(NON_EXISTENT_UUID, OFFICER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_student_system_fields_ignored_on_create(api):
    """PRD §3.2: "A new student starts in `status` `ACTIVE` with an
    `account_balance_cents` of 0."
    PRD §2.4: "a `version`, an integer that starts at 1 on creation and increases
    by exactly 1 on every mutation."

    Design: Corner/entities/student_system_fields_ignored_on_create
    """
    res = api.create_student(
        create_student_payload(full_name="Sys S", class_year="JUNIOR",
                               gender_identity="FEMALE", lottery_number=7),
        OFFICER)
    student = validate_success(res, 201)
    assert_student(student)
    assert student["status"] == "ACTIVE"
    assert student["account_balance_cents"] == 0
    assert student["version"] == 1


def test_building_offers_break_housing_default_false(api):
    """PRD §3.1: "the officer may also set `offers_break_housing`, a boolean that
    defaults to `false` and governs whether any room in the building may host
    break occupancy, and `break_housing_capacity`, a non-negative integer (it
    must be zero or greater) that defaults to 0 and caps the building's
    simultaneous approved break occupants as described in §3.8."

    Design: Corner/entities/building_offers_break_housing_default_false
    """
    res = api.create_building(
        create_building_payload(name="Default Hall", building_type="TRADITIONAL"),
        OFFICER)
    building = validate_success(res, 201)
    assert building["offers_break_housing"] is False
    assert building["break_housing_capacity"] == 0


def test_take_offline_occupied_room_rejected(api):
    """PRD §3.1: "Taking a room offline is an officer-only capability that
    transitions its `status` to `OFFLINE`, but only when the room is empty — if
    `occupied_bed_count` is greater than 0 the request is rejected with
    `ERR_ROOM_OCCUPIED` (HTTP 409)."

    Design: Corner/validations/take_offline_occupied_room_rejected
    """
    from test_helpers import setup_active_assignment
    scn = setup_active_assignment(room_kwargs={"room_number": "OF1"})
    room = validate_success(api.get_room(scn["room"]["id"], OFFICER), 200)
    assert room["occupied_bed_count"] > 0, "precondition: room is occupied"
    res = api.take_offline_room(
        room["id"], {"expected_room_version": room["version"]}, OFFICER)
    validate_error(res, "ERR_ROOM_OCCUPIED")
    after = validate_success(api.get_room(room["id"], OFFICER), 200)
    assert after["status"] != "OFFLINE"


def test_take_offline_stale_room_version_rejected(api):
    """PRD §2.7: "Taking a room offline and restoring a room each require
    `expected_room_version` matching the room's current `version`, again failing
    with `ERR_STALE_VERSION` (HTTP 412) on mismatch."

    Design: Corner/cross_cutting_complexity_layers/occ_room_take_offline_stale_version_conflict
    """
    building = create_building(name="OCC Hall", building_type="TRADITIONAL")
    room = create_room(building["id"], room_number="OC1", room_type="SINGLE")
    v0 = room["version"]
    # Take offline (bumps version), then restore with a stale (one-below) version.
    validate_success(
        api.take_offline_room(room["id"], {"expected_room_version": v0}, OFFICER), 200)
    now = validate_success(api.get_room(room["id"], OFFICER), 200)
    res = api.restore_room(
        room["id"], {"expected_room_version": now["version"] - 1}, OFFICER)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_room_version_increments_on_each_write(api):
    """PRD §3.1: "On success the room leaves the bed totals, so the owning
    building's `total_bed_count` is recomputed, and the room's `version`
    increments by 1." ... "Restoring a room is the inverse officer-only
    capability: it re-derives the room's `status` from its current occupancy and
    open incidents (so a restored room becomes `OPEN` or `RESTRICTED` according
    to its posture, never staying `OFFLINE`), recomputes the building's
    `total_bed_count`, increments the room's `version` by 1, and likewise
    requires `expected_room_version` to match."

    Design: Corner/cross_cutting_complexity_layers/occ_room_version_increments_on_each_write
    """
    building = create_building(name="VerBump Hall", building_type="TRADITIONAL")
    room = create_room(building["id"], room_number="VB1", room_type="SINGLE")
    v0 = room["version"]
    assert v0 == 1
    off = validate_success(
        api.take_offline_room(room["id"], {"expected_room_version": v0}, OFFICER), 200)
    restored = validate_success(
        api.restore_room(room["id"], {"expected_room_version": off["version"]}, OFFICER), 200)
    assert restored["version"] == 3
    assert restored["status"] == "OPEN"
