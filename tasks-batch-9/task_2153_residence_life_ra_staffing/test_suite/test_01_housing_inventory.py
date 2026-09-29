"""Halls, floors, rooms and the residents who occupy their beds."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_building,
    assert_room,
    create_building,
    create_building_payload,
    create_floor,
    create_floor_payload,
    create_room,
    create_room_payload,
    create_student,
    create_student_payload,
    place_student,
    read_building,
    read_floor,
    read_room,
    read_student,
    setup_hall_with_floor,
    setup_hall_with_rooms,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
    vacate_student,
)


def test_new_hall_opens_with_zero_beds_and_version_one(api, director_headers):
    """PRD §3.1: "A newly created hall opens at `posture` `OPEN` with `closure_reason`
    and `last_posture_change_at` both null, a `bed_capacity` of 0 and an
    `assigned_bed_count` of 0."
    PRD §2.4: "All fourteen resource types additionally carry `updated_at`, refreshed
    to the current instant on every mutation, and `version`, an integer that begins at
    1 when the resource is created and increases by exactly one on each subsequent
    mutation."

    Design: Corner/entities/create_building_returns_declared_fields_with_server_defaults
    """
    first = create_building(name="Kerr Hall", code="KERR")

    response = api.create_building(
        create_building_payload(name="McGregor Hall", code="MCGR", campus_zone="SOUTH"),
        director_headers,
    )
    hall = validate_success(response, 201)

    assert_building(hall)
    assert hall["posture"] == "OPEN", f"Expected posture OPEN, got {hall['posture']}"
    assert hall["break_housing_enabled"] is False
    assert hall["bed_capacity"] == 0 and hall["assigned_bed_count"] == 0
    assert hall["version"] == 1, f"Expected version 1 on create, got {hall['version']}"
    assert hall["closure_reason"] is None
    assert hall["last_posture_change_at"] is None
    assert hall["id"] != first["id"], "each hall must carry its own server-minted id"


def test_room_listing_filters_by_floor_and_reports_total_count(api, director_headers):
    """PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` as
    they were applied, `total_count` as the number of rows matching the filters before
    the page window was taken, and `has_more` as a boolean that is true when rows remain
    beyond the current window."
    PRD §2.3: "Rooms accept `floor_id` and `status`."

    Design: Corner/entities/list_rooms_filters_by_floor_and_paginates_with_total_count
    """
    base = setup_hall_with_rooms(
        room_specs=[
            {"room_number": "201", "bed_capacity": 2},
            {"room_number": "202", "bed_capacity": 2},
            {"room_number": "203", "bed_capacity": 1, "last_renovation_year": 2019},
        ]
    )
    floor_id = base["floor"]["id"]

    first_page, first_meta = validate_paginated(
        api.list_rooms(director_headers, params={"floor_id": floor_id, "limit": 2, "offset": 0})
    )
    assert len(first_page) == 2, f"Expected a 2-row page, got {len(first_page)}"
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_rooms(director_headers, params={"floor_id": floor_id, "limit": 2, "offset": 2})
    )
    assert len(second_page) == 1, f"Expected the tail row, got {len(second_page)}"
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    assert read_floor(floor_id)["bed_capacity"] == 5


def test_unknown_resident_id_reports_the_student_not_found_code(api, director_headers):
    """PRD §2.6: "Each resource type has its own not-found code:
    `ERR_BUILDING_NOT_FOUND`, `ERR_FLOOR_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`,
    `ERR_STUDENT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_RA_NOT_FOUND`,
    `ERR_SHIFT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_CONDUCT_CASE_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`,
    `ERR_ROOM_CHANGE_CASE_NOT_FOUND`, `ERR_PROGRAM_EVENT_NOT_FOUND` and
    `ERR_BREAK_REQUEST_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/get_unknown_student_returns_student_not_found
    """
    resident = create_student(full_name="Dee Sun", email=unique_email("dee"))

    response = api.get_student(NON_EXISTENT_UUID, director_headers)

    validate_error(response, ApiErrorId.ERR_STUDENT_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"
    assert read_student(resident["id"])["id"] == resident["id"]


def test_room_created_without_bed_capacity_is_refused(api, director_headers):
    """PRD §3.1: "Rooms are created on a floor by naming the `floor_id`, a
    `room_number` unique among that floor's rooms, a `bed_capacity` between 1 and 4,
    and a `last_renovation_year` between 1950 and 2100 — the year that later drives
    damage depreciation."
    PRD §2.7: "Any breach is `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_room_without_bed_capacity_returns_invalid_request
    """
    base = setup_hall_with_floor()
    floor_id = base["floor"]["id"]

    response = api.create_room(
        {"floor_id": floor_id, "room_number": "201", "last_renovation_year": 2021},
        director_headers,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _, meta = validate_paginated(
        api.list_rooms(director_headers, params={"floor_id": floor_id})
    )
    assert meta["total_count"] == 0, "the refused create must leave no Room row behind"
    assert read_floor(floor_id)["bed_capacity"] == 0


def test_break_housing_flag_defaults_to_false_when_omitted(api, director_headers):
    """PRD §3.1: "A `ResidenceDirector` creates one by supplying its display `name`, a
    short `code` and the `campus_zone` it sits in, optionally declaring
    `break_housing_enabled` — a boolean that defaults to false and determines whether
    the hall will accept break-housing requests at all."

    Design: Corner/entities/create_building_omitting_break_housing_enabled_defaults_to_false
    """
    explicit = create_building(name="Kerr Hall", code="KERR", break_housing_enabled=True)

    response = api.create_building(
        create_building_payload(name="McGregor Hall", code="MCGR", campus_zone="WEST"),
        director_headers,
    )
    defaulted = validate_success(response, 201)

    assert explicit["break_housing_enabled"] is True
    assert defaulted["break_housing_enabled"] is False, (
        "a hall created without the key must read false"
    )


def test_room_bed_capacity_above_four_is_refused_while_four_is_accepted(api, director_headers):
    """PRD §3.1: "Rooms are created on a floor by naming the `floor_id`, a
    `room_number` unique among that floor's rooms, a `bed_capacity` between 1 and 4,
    and a `last_renovation_year` between 1950 and 2100 — the year that later drives
    damage depreciation."
    PRD §2.7: "Any breach is `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_room_with_bed_capacity_five_returns_invalid_request
    """
    base = setup_hall_with_floor()
    floor_id = base["floor"]["id"]

    refused = api.create_room(
        create_room_payload(floor_id, room_number="201", bed_capacity=5),
        director_headers,
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    accepted = api.create_room(
        create_room_payload(floor_id, room_number="201", bed_capacity=4),
        director_headers,
    )
    room = validate_success(accepted, 201)
    assert_room(room)
    assert room["bed_capacity"] == 4
    assert read_floor(floor_id)["bed_capacity"] == 4


def test_floor_created_under_an_unknown_hall_reports_the_building_not_found_code(
    api, director_headers
):
    """PRD §2.6: "The same codes cover references that arrive in a request body rather
    than in the path."
    PRD §2.6: "Each resource type has its own not-found code:
    `ERR_BUILDING_NOT_FOUND`, `ERR_FLOOR_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`,
    `ERR_STUDENT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_RA_NOT_FOUND`,
    `ERR_SHIFT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_CONDUCT_CASE_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`,
    `ERR_ROOM_CHANGE_CASE_NOT_FOUND`, `ERR_PROGRAM_EVENT_NOT_FOUND` and
    `ERR_BREAK_REQUEST_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/create_floor_under_unknown_building_returns_building_not_found
    """
    hall = create_building(name="Kerr Hall", code="KERR")

    response = api.create_floor(
        create_floor_payload(NON_EXISTENT_UUID, floor_number=3), director_headers
    )

    validate_error(response, ApiErrorId.ERR_BUILDING_NOT_FOUND.value, 404)
    _, meta = validate_paginated(
        api.list_floors(director_headers, params={"building_id": hall["id"]})
    )
    assert meta["total_count"] == 0, "no floor may be written under the real hall"


def test_room_number_is_unique_per_floor_not_per_hall(api, director_headers):
    """PRD §3.1: "A duplicate room label on the same floor is
    `ERR_DUPLICATE_ROOM_NUMBER`."
    PRD §3.1: "Rooms are created on a floor by naming the `floor_id`, a `room_number`
    unique among that floor's rooms, a `bed_capacity` between 1 and 4, and a
    `last_renovation_year` between 1950 and 2100 — the year that later drives damage
    depreciation."

    Design: Corner/entities/duplicate_room_number_on_same_floor_returns_409
    """
    hall = create_building(name="Kerr Hall", code="KERR")
    floor_two = create_floor(hall["id"], floor_number=2)
    floor_three = create_floor(hall["id"], floor_number=3)
    original = create_room(floor_two["id"], room_number="201", bed_capacity=2)

    duplicate = api.create_room(
        create_room_payload(
            floor_two["id"], room_number="201", bed_capacity=1, last_renovation_year=2020
        ),
        director_headers,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_ROOM_NUMBER.value, 409)

    elsewhere = api.create_room(
        create_room_payload(
            floor_three["id"], room_number="201", bed_capacity=1, last_renovation_year=2020
        ),
        director_headers,
    )
    validate_success(elsewhere, 201)

    assert read_room(original["id"])["bed_capacity"] == 2, (
        "the rejected create must not overwrite the existing room"
    )
    assert read_building(hall["id"])["bed_capacity"] == 3


def test_vacating_a_room_returns_it_to_available_and_drops_the_hall_bed_count(
    api, director_headers
):
    """PRD §3.1: "A `VACATE` reverses this: `current_room_id` returns to null,
    `housing_status` returns to `UNASSIGNED`, the room's `occupied_beds` falls by one,
    and when the departing resident was the room's only occupant — that is, when the
    room held exactly one occupied bed — the room moves `OCCUPIED → AVAILABLE`."
    PRD §3.1: "Floor and hall aggregates are recomputed on this path too."

    Design: Corner/endpoints/vacating_a_room_returns_it_to_available_and_decrements_assigned_bed_count
    """
    base = setup_hall_with_rooms(room_specs=[{"room_number": "201", "bed_capacity": 2}])
    room = base["rooms"][0]
    resident = create_student(full_name="Dee Sun", email=unique_email("dee"))
    place_student(resident["id"], room["id"])

    before_room = read_room(room["id"])
    assert before_room["status"] == "OCCUPIED" and before_room["occupied_beds"] == 1
    assert read_building(base["building"]["id"])["assigned_bed_count"] == 1

    vacated = vacate_student(resident["id"])

    assert vacated["current_room_id"] is None
    assert vacated["housing_status"] == "UNASSIGNED"
    after_room = read_room(room["id"])
    assert after_room["occupied_beds"] == 0
    assert after_room["status"] == "AVAILABLE"
    assert read_floor(base["floor"]["id"])["occupied_beds"] == 0
    hall = read_building(base["building"]["id"])
    assert hall["assigned_bed_count"] == 0
    assert hall["bed_capacity"] == 2, "vacating never changes physical capacity"


def test_placing_a_resident_into_a_full_room_reports_room_at_capacity(api, director_headers):
    """PRD §3.1: "Placement requires the target room to be `AVAILABLE` with
    `occupied_beds` strictly below its `bed_capacity`, and the owning hall to be
    `OPEN`; a room that is `OFFLINE` or `CONSOLIDATED` draws `ERR_ROOM_NOT_AVAILABLE`
    and a room already at its bed capacity draws `ERR_ROOM_AT_CAPACITY`."

    Design: Corner/errors/placing_a_student_into_a_full_room_returns_room_at_capacity
    """
    base = setup_hall_with_rooms(room_specs=[{"room_number": "201", "bed_capacity": 1}])
    room = base["rooms"][0]
    first = create_student(full_name="Dee Sun", email=unique_email("dee"))
    second = create_student(
        full_name="Eli Cross", email=unique_email("eli"), class_year="SENIOR"
    )
    place_student(first["id"], room["id"])

    response = api.room_assignment(
        second["id"], {"action": "PLACE", "room_id": room["id"]}, director_headers
    )

    validate_error(response, ApiErrorId.ERR_ROOM_AT_CAPACITY.value, 409)
    assert read_room(room["id"])["occupied_beds"] == 1
    turned_away = read_student(second["id"])
    assert turned_away["current_room_id"] is None
    assert turned_away["housing_status"] == "UNASSIGNED"
    assert read_building(base["building"]["id"])["assigned_bed_count"] == 1


def test_placing_a_resident_into_an_offline_room_reports_room_not_available(
    api, director_headers
):
    """PRD §3.1: "Placement requires the target room to be `AVAILABLE` with
    `occupied_beds` strictly below its `bed_capacity`, and the owning hall to be
    `OPEN`; a room that is `OFFLINE` or `CONSOLIDATED` draws `ERR_ROOM_NOT_AVAILABLE`
    and a room already at its bed capacity draws `ERR_ROOM_AT_CAPACITY`."
    PRD §3.1: "A director can also take a room out of service directly, outside any
    hall-wide event, by supplying a `target_status` of `OFFLINE` or `AVAILABLE`
    together with an optional `reason`."

    Design: Corner/errors/placing_a_student_into_an_offline_room_returns_room_not_available
    """
    base = setup_hall_with_rooms(room_specs=[{"room_number": "201", "bed_capacity": 2}])
    room = base["rooms"][0]
    resident = create_student(full_name="Dee Sun", email=unique_email("dee"))
    validate_success(
        api.set_room_status(
            room["id"], {"target_status": "OFFLINE", "reason": "asbestos survey"},
            director_headers,
        )
    )

    response = api.room_assignment(
        resident["id"], {"action": "PLACE", "room_id": room["id"]}, director_headers
    )

    validate_error(response, ApiErrorId.ERR_ROOM_NOT_AVAILABLE.value, 409)
    offline_room = read_room(room["id"])
    assert offline_room["status"] == "OFFLINE"
    assert offline_room["occupied_beds"] == 0, "a refused placement moves no bed"
    assert read_student(resident["id"])["current_room_id"] is None
