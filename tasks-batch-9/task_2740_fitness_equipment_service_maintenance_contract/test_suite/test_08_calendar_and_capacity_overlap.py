"""
The two overlap rules that use deliberately opposite interval conventions: the
club's on-floor visit capacity, measured over closed windows, and the technician's
own calendar, measured over half-open intervals under a symmetric travel buffer.

Each test builds its whole world through declared endpoints and drives the logical
clock itself, because the database is empty when the test starts.
"""

from test_helpers import (
    CONTRACT_ADMIN,
    ERR_CLUB_VISIT_CAPACITY,
    ERR_TECHNICIAN_WINDOW_CONFLICT,
    SERVICE_COORDINATOR,
    assert_fields,
    assert_instant,
    assert_technician_capacity_identity,
    assignment_for_visit,
    build_fleet,
    get_success_data,
    preventive_visit_payload,
    read_technician,
    read_visit,
    rows_of,
    schedule_visit,
    validate_error,
)


def _single_slot_club_with_a_booked_morning(api):
    """
    A club that allows one visit at a time, holding a 08:00-09:30 visit on E1 with
    T1, and a second idle technician T2 whose own calendar is completely empty.
    """
    fleet = build_fleet(
        api,
        clock="2026-08-19T07:00:00Z",
        club_kwargs={"max_concurrent_visits": 1},
        serials=["SN-CC-1", "SN-CC-2"],
        equipment_kwargs={"install_date": "2024-03-01", "initial_usage_hours": 500},
        technicians=[
            {"full_name": "Dana Reyes", "region_code": "NW"},
            {"full_name": "Nils Okonjo", "region_code": "NW"},
        ],
    )
    fleet["first_technician"], fleet["idle_technician"] = fleet["technician_ids"]
    fleet["morning_visit"] = schedule_visit(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        "2026-08-19T08:00:00Z",
        "2026-08-19T09:30:00Z",
        fleet["first_technician"],
    )
    return fleet


def test_a_window_touching_the_booked_window_exhausts_the_club_visit_capacity(api):
    """
    A second window that starts at the very instant the first one ends is concurrent
    with it, so a club allowing one visit at a time refuses the booking with
    ERR_CLUB_VISIT_CAPACITY even though the candidate names an idle technician.

    PRD §3.4: "A candidate overlaps an existing visit when the candidate's
    `window_start` is at or before the existing visit's `window_end` and the existing
    visit's `window_start` is at or before the candidate's `window_end`."

    Design: Difficulty/resource_temporal_overlap/club_visit_capacity_treats_touching_windows_as_concurrent
    """
    fleet = _single_slot_club_with_a_booked_morning(api)

    response = api.create_preventive_visit(
        preventive_visit_payload(
            fleet["contract_id"],
            fleet["equipment_ids"][1],
            "2026-08-19T09:30:00Z",
            "2026-08-19T11:00:00Z",
            fleet["idle_technician"],
        ),
        SERVICE_COORDINATOR,
    )
    validate_error(response, ERR_CLUB_VISIT_CAPACITY, 409)

    visits = rows_of(
        api.list_preventive_visits(CONTRACT_ADMIN, contract_id=fleet["contract_id"])
    )
    assert len(visits) == 1, f"the refused window must create nothing, got {len(visits)}"
    assert_fields(read_visit(api, fleet["morning_visit"]["id"]), visit_status="SCHEDULED")

    idle = read_technician(api, fleet["idle_technician"])
    assert idle["committed_minutes"] == 0
    assert_technician_capacity_identity(
        idle,
        rows_of(
            api.list_technician_assignments(
                CONTRACT_ADMIN, technician_id=fleet["idle_technician"]
            )
        ),
    )
    assert read_technician(api, fleet["first_technician"])["committed_minutes"] == 90


def test_a_window_starting_one_minute_after_the_endpoint_is_not_concurrent(api):
    """
    Pushing the same second window one minute past the endpoint removes the overlap
    entirely, so the single-slot club accepts it and books an 89-minute visit for the
    idle technician while the first visit is left exactly as it was.

    PRD §3.4: "**Visit windows are closed intervals**: two visits that merely touch at
    an endpoint *do* collide, which is the opposite of the half-open technician rule in
    §3.3."

    Design: Difficulty/resource_temporal_overlap/club_visit_capacity_treats_touching_windows_as_concurrent
    """
    fleet = _single_slot_club_with_a_booked_morning(api)

    booked = get_success_data(
        api.create_preventive_visit(
            preventive_visit_payload(
                fleet["contract_id"],
                fleet["equipment_ids"][1],
                "2026-08-19T09:31:00Z",
                "2026-08-19T11:00:00Z",
                fleet["idle_technician"],
            ),
            SERVICE_COORDINATOR,
        ),
        201,
    )
    assert_fields(
        booked,
        visit_status="SCHEDULED",
        safety_doc_status="PENDING",
        planned_minutes=89,
        assigned_technician_id=fleet["idle_technician"],
    )
    assert_instant(booked["window_start"], "2026-08-19T09:31:00Z", "window_start")
    assert_instant(booked["window_end"], "2026-08-19T11:00:00Z", "window_end")
    assert_fields(assignment_for_visit(api, booked["id"]), status="RESERVED", planned_minutes=89)

    visits = rows_of(
        api.list_preventive_visits(CONTRACT_ADMIN, contract_id=fleet["contract_id"])
    )
    assert len(visits) == 2, f"both windows must stand, got {len(visits)}"
    assert_fields(
        read_visit(api, fleet["morning_visit"]["id"]),
        visit_status="SCHEDULED",
        planned_minutes=90,
    )

    idle = read_technician(api, fleet["idle_technician"])
    assert idle["committed_minutes"] == 89
    assert_technician_capacity_identity(
        idle,
        rows_of(
            api.list_technician_assignments(
                CONTRACT_ADMIN, technician_id=fleet["idle_technician"]
            )
        ),
    )
    assert read_technician(api, fleet["first_technician"])["committed_minutes"] == 90


def _roomy_club_with_one_busy_technician(api):
    """
    A club that allows three simultaneous visits, so nothing but the technician's own
    calendar can refuse a booking, holding one 08:00-09:30 visit on E1 with T1.
    """
    fleet = build_fleet(
        api,
        clock="2026-08-19T07:00:00Z",
        club_kwargs={"max_concurrent_visits": 3},
        serials=["SN-TB-1", "SN-TB-2"],
        equipment_kwargs={"install_date": "2024-03-01", "initial_usage_hours": 500},
        technicians=[{"full_name": "Dana Reyes", "region_code": "NW"}],
    )
    fleet["technician_id"] = fleet["technician_ids"][0]
    fleet["morning_visit"] = schedule_visit(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        "2026-08-19T08:00:00Z",
        "2026-08-19T09:30:00Z",
        fleet["technician_id"],
    )
    return fleet


def test_a_forty_four_minute_gap_collides_with_the_technicians_own_calendar(api):
    """
    With the club able to host three simultaneous visits, a second window opening 44
    minutes after the first one ends is still inside the travel buffer, so the booking
    is refused with ERR_TECHNICIAN_WINDOW_CONFLICT and reserves nothing.

    PRD §3.3: "A gap of exactly 45 minutes between two pieces of work is therefore
    legal, while a gap of 44 minutes is a conflict, and the collision is refused with
    `ERR_TECHNICIAN_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/technician_calendar_needs_a_full_45_minute_travel_gap
    """
    fleet = _roomy_club_with_one_busy_technician(api)
    technician_id = fleet["technician_id"]

    response = api.create_preventive_visit(
        preventive_visit_payload(
            fleet["contract_id"],
            fleet["equipment_ids"][1],
            "2026-08-19T10:14:00Z",
            "2026-08-19T11:00:00Z",
            technician_id,
        ),
        SERVICE_COORDINATOR,
    )
    validate_error(response, ERR_TECHNICIAN_WINDOW_CONFLICT, 409)

    assignments = rows_of(
        api.list_technician_assignments(CONTRACT_ADMIN, technician_id=technician_id)
    )
    assert len(assignments) == 1, f"the refused window must reserve nothing, got {len(assignments)}"
    assert_fields(assignments[0], status="RESERVED", planned_minutes=90)

    technician = read_technician(api, technician_id)
    assert technician["committed_minutes"] == 90
    assert_technician_capacity_identity(technician, assignments)

    visits = rows_of(
        api.list_preventive_visits(CONTRACT_ADMIN, contract_id=fleet["contract_id"])
    )
    assert len(visits) == 1, f"the refused window must create no visit, got {len(visits)}"
    assert_fields(
        read_visit(api, fleet["morning_visit"]["id"]),
        visit_status="SCHEDULED",
        planned_minutes=90,
    )


def test_a_gap_of_exactly_forty_five_minutes_is_a_legal_second_reservation(api):
    """
    Moving that same window one minute later makes the gap exactly the travel buffer,
    which the PRD declares legal, so the technician ends up holding two reservations
    and 135 committed minutes.

    PRD §3.3: "A gap of exactly 45 minutes between two pieces of work is therefore
    legal, while a gap of 44 minutes is a conflict, and the collision is refused with
    `ERR_TECHNICIAN_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/technician_calendar_needs_a_full_45_minute_travel_gap
    """
    fleet = _roomy_club_with_one_busy_technician(api)
    technician_id = fleet["technician_id"]

    booked = get_success_data(
        api.create_preventive_visit(
            preventive_visit_payload(
                fleet["contract_id"],
                fleet["equipment_ids"][1],
                "2026-08-19T10:15:00Z",
                "2026-08-19T11:00:00Z",
                technician_id,
            ),
            SERVICE_COORDINATOR,
        ),
        201,
    )
    assert_fields(
        booked,
        visit_status="SCHEDULED",
        planned_minutes=45,
        assigned_technician_id=technician_id,
    )

    second = assignment_for_visit(api, booked["id"])
    assert_fields(second, status="RESERVED", planned_minutes=45)
    assert_instant(second["start_at"], "2026-08-19T10:15:00Z", "start_at")
    assert_instant(second["end_at"], "2026-08-19T11:00:00Z", "end_at")

    assignments = rows_of(
        api.list_technician_assignments(CONTRACT_ADMIN, technician_id=technician_id)
    )
    assert len(assignments) == 2, f"both reservations must stand, got {len(assignments)}"
    assert [row["status"] for row in assignments] == ["RESERVED", "RESERVED"]

    technician = read_technician(api, technician_id)
    assert technician["committed_minutes"] == 135
    assert_technician_capacity_identity(technician, assignments)

    first = assignment_for_visit(api, fleet["morning_visit"]["id"])
    assert_fields(first, status="RESERVED", planned_minutes=90)
    assert_instant(first["start_at"], "2026-08-19T08:00:00Z", "start_at")
    assert_instant(first["end_at"], "2026-08-19T09:30:00Z", "end_at")
