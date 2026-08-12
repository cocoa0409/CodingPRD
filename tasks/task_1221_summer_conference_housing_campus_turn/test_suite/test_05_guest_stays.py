"""Guest stays: check-in/out windows, cascades, group cancellation, listings."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_participant,
    add_participants,
    assert_bed_ledger_invariant,
    assert_instant_equal,
    create_building_turn_active,
    create_group,
    create_group_with_revision,
    create_revision_payload,
    get_assignment_for_participant,
    get_building,
    get_group,
    get_room,
    get_success_data,
    list_assignments,
    make_coordinator_headers,
    set_clock,
    setup_confirmed_group,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestStayTemporalWindows:
    def test_checkin_before_window_and_early_no_show_rejected(self, api):
        """PRD: "the logical clock must fall within the planned stay — on or after
        checkin_at and strictly before checkout_at — else
        ERR_OUTSIDE_CHECKIN_WINDOW."
        PRD: "A guest who never arrives is marked as a no-show, moving RESERVED to
        NO_SHOW — but only once the logical clock is more than 24 hours past the
        planned checkin_at; earlier attempts fail with ERR_OUTSIDE_CHECKIN_WINDOW."

        Design: Corner/validations/checkin_before_window_and_early_no_show_rejected
        """
        building, rooms = create_building_turn_active(name="Foxtrot Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, participants, _rev, _inv = setup_confirmed_group(
            building, rooms, client_name="Early Bird")
        assignment = get_assignment_for_participant(group["id"], participants[0]["id"])

        set_clock("2026-06-14T10:00:00Z")
        validate_error(api.check_in_assignment(assignment["id"], ADMIN),
                       ApiErrorId.ERR_OUTSIDE_CHECKIN_WINDOW)
        set_clock("2026-06-16T03:00:00Z")  # only 12h past checkin_at
        validate_error(api.mark_no_show(assignment["id"], ADMIN),
                       ApiErrorId.ERR_OUTSIDE_CHECKIN_WINDOW)
        after = get_success_data(api.get_stay_assignment(assignment["id"], ADMIN))
        assert after["status"] == "RESERVED"


class TestImmediateConsistency:
    def test_immediate_visibility_of_mutation_in_same_response(self, api):
        """PRD: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD: "On success, actual_checkin_at is stamped from the clock"

        Design: Corner/consistency_model/immediate_visibility_of_mutation_in_same_response
        """
        building, rooms = create_building_turn_active(name="Yankee Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, participants, _rev, _inv = setup_confirmed_group(
            building, rooms, client_name="Immediate")
        assignment = get_assignment_for_participant(group["id"], participants[0]["id"])
        version_before = assignment["version"]
        set_clock("2026-06-15T16:00:00Z")
        checked = validate_success(api.check_in_assignment(assignment["id"], ADMIN))
        assert checked["status"] == "CHECKED_IN"
        assert_instant_equal(checked["actual_checkin_at"], "2026-06-15T16:00:00Z")
        assert checked["version"] == version_before + 1, \
            "version increments by exactly one on the mutation"
        reread = get_success_data(api.get_stay_assignment(assignment["id"], ADMIN))
        assert reread["status"] == "CHECKED_IN"
        assert_instant_equal(reread["actual_checkin_at"], "2026-06-15T16:00:00Z")


class TestCheckoutTurnSpawnCascade:
    def _two_guest_group(self, api, name="Jarvis Hall"):
        building, rooms = create_building_turn_active(name=name, key_pool_size=10,
                                                      rooms=(("R1", 2),))
        group, participants, _rev, _inv = setup_confirmed_group(
            building, rooms, client_name="Bar Association",
            participant_specs=[("A One", "1965-05-05", "ATTENDEE"),
                               ("A Two", "1966-06-06", "ATTENDEE")],
            assignment_room_map=["R1", "R1"], deposit_paid_cents=5000)
        set_clock("2026-06-15T16:00:00Z")
        assignments = []
        for participant in participants:
            a = get_assignment_for_participant(group["id"], participant["id"])
            assignments.append(
                get_success_data(api.check_in_assignment(a["id"], ADMIN)))
        return building, rooms, group, assignments

    def test_first_checkout_does_not_fire_cascade(self, api):
        """PRD: "When no CHECKED_IN assignment remains on the room afterwards, the
        room cascades from OCCUPIED to NEEDS_TURN"
        PRD: "Check-out ... settles the building ledger — reserved_bed_count
        decreases by one and available_bed_count increases by one."

        Design: Difficulty/transitive_cascade/checkout_turn_spawn_cascade_depth3
        """
        building, rooms, group, assignments = self._two_guest_group(api)
        set_clock("2026-06-17T09:00:00Z")
        get_success_data(api.check_out_assignment(assignments[0]["id"], ADMIN))
        room = get_room(rooms["R1"]["id"])
        building_after = get_building(building["id"])
        assert room["status"] == "OCCUPIED", "one CHECKED_IN guest remains on the room"
        assert building_after["scheduled_turn_count"] == 0, \
            "no turn task spawns while the room still has an occupant"
        assert building_after["reserved_bed_count"] == 1
        assert building_after["available_bed_count"] == 1

    def test_last_checkout_spawns_turn_task_with_window(self, api):
        """PRD: "The task's cleaning window starts at the triggering checkout
        instant — window_start equals the actual_checkout_at that emptied the
        room — and window_end is the earliest future RESERVED check-in on that
        room, or seven days after window_start when no next reservation exists."
        PRD: "the last checkout from a room pushes the room into NEEDS_TURN and
        spawns its turn task."

        Design: Difficulty/transitive_cascade/checkout_turn_spawn_cascade_depth3
        """
        building, rooms, group, assignments = self._two_guest_group(api)
        set_clock("2026-06-17T09:00:00Z")
        get_success_data(api.check_out_assignment(assignments[0]["id"], ADMIN))
        get_success_data(api.check_out_assignment(assignments[1]["id"], ADMIN))
        room = get_room(rooms["R1"]["id"])
        assert room["status"] == "NEEDS_TURN"
        assert room["active_turn_task_id"], "the empty room points at its new turn task"
        task = get_success_data(api.get_turn_task(room["active_turn_task_id"], ADMIN))
        assert task["status"] == "SCHEDULED"
        assert_instant_equal(task["window_start"], "2026-06-17T09:00:00Z")
        assert_instant_equal(task["window_end"], "2026-06-24T09:00:00Z"), \
            "no future reservation on the room means window_start + 7 days"
        assert task["linen_tier"] == "STANDARD", "no next reservation: departing group's tier"
        building_after = get_building(building["id"])
        assert building_after["scheduled_turn_count"] == 1
        assert building_after["reserved_bed_count"] == 0
        assert building_after["available_bed_count"] == 2


class TestGroupCancelCascade:
    def _confirmed_four_bed_group(self, api):
        """CONFIRMED group, 4 assignments across R3/R4 (3 beds each), provisional 72000."""
        building, rooms = create_building_turn_active(name="Irving Hall",
                                                      key_pool_size=10,
                                                      rooms=(("R3", 3), ("R4", 3)))
        group, participants, _rev, invoice_id = setup_confirmed_group(
            building, rooms, client_name="Cheer Nationals",
            participant_specs=[("A One", "1992-01-01", "ATTENDEE"),
                               ("A Two", "1992-01-02", "ATTENDEE"),
                               ("A Three", "1992-01-03", "ATTENDEE"),
                               ("A Four", "1992-01-04", "ATTENDEE")],
            assignment_room_map=["R3", "R3", "R4", "R4"],
            arrival_date="2026-07-20", departure_date="2026-07-24",
            checkin_at="2026-07-20T15:00:00Z", checkout_at="2026-07-24T11:00:00Z",
            contracted_bed_count=4, deposit_paid_cents=20000)
        return building, rooms, group, invoice_id

    def test_group_cancel_cascade_fee_rooms_and_ledger(self, api):
        """PRD: "In every cancellation the reserved-stay cascade runs: each
        RESERVED assignment of the group moves to CANCELLED; each room left
        without any active assignment returns from RESERVED to RELEASED; and each
        freed bed decrements reserved_bed_count and increments
        available_bed_count on the building ledger."
        PRD: "Cancelling from CONFIRMED also voids the PROVISIONAL invoice,
        moving it to VOID."

        Design: Difficulty/transitive_cascade/group_cancel_cascade_depth3
        """
        building, rooms, group, invoice_id = self._confirmed_four_bed_group(api)
        invoice_before = get_success_data(api.get_invoice(invoice_id, FINANCE))
        assert invoice_before["provisional_total_cents"] == 72000, \
            "16 planned bed-nights at 4500 (Mon-Thu nights, no weekend premium)"
        set_clock("2026-06-20T00:00:00Z")  # exactly 30 days before arrival

        cancelled = validate_success(
            api.cancel_group(group["id"], make_coordinator_headers(group["id"])))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_fee_cents"] == 14400, \
            "20% of the 72000 provisional total at exactly 30 days before arrival"
        invoice_after = get_success_data(api.get_invoice(invoice_id, FINANCE))
        assert invoice_after["status"] == "VOID"
        rows = list_assignments(group_id=group["id"])
        assert len(rows) == 4
        assert all(r["status"] == "CANCELLED" for r in rows), \
            "every RESERVED assignment of the group is cancelled (cascade link 1)"
        for key in ("R3", "R4"):
            assert get_room(rooms[key]["id"])["status"] == "RELEASED", \
                "emptied rooms return RESERVED -> RELEASED (cascade link 2)"
        b = get_building(building["id"])
        assert b["reserved_bed_count"] == 0 and b["available_bed_count"] == 6
        assert b["released_bed_count"] == 6, "the frozen release count is untouched"
        assert_bed_ledger_invariant(b)

    def test_group_cancel_cascade_frees_every_reserved_assignment(self, api):
        """PRD: "In every cancellation the reserved-stay cascade runs: each
        RESERVED assignment of the group moves to CANCELLED; each room left
        without any active assignment returns from RESERVED to RELEASED"

        Design: Difficulty/transitive_cascade/group_cancel_cascade_depth3
        """
        building, rooms, group, invoice_id = self._confirmed_four_bed_group(api)
        set_clock("2026-06-20T00:00:00Z")
        validate_success(api.cancel_group(group["id"], make_coordinator_headers(group["id"])))
        # Every assignment is terminal, both rooms released, and the ledger returns
        # to the frozen release baseline with zero drift.
        b = get_building(building["id"])
        assert b["reserved_bed_count"] == 0
        assert b["available_bed_count"] == b["released_bed_count"] == 6
        assert all(r["status"] == "CANCELLED"
                   for r in list_assignments(group_id=group["id"]))


class TestCancellationFeeTiers:
    def _confirmed_two_groups(self, api):
        building, rooms = create_building_turn_active(
            name="Price Hall", key_pool_size=5,
            rooms=(("R1", 2), ("R2", 2), ("R3", 2), ("R4", 2)))
        g1, _p1, _r1, _i1 = setup_confirmed_group(
            building, rooms, client_name="Free Cancel",
            participant_specs=[("F P1", "1990-01-01", "ATTENDEE"),
                               ("F P2", "1990-01-02", "ATTENDEE"),
                               ("F P3", "1990-01-03", "ATTENDEE"),
                               ("F P4", "1990-01-04", "ATTENDEE")],
            assignment_room_map=["R1", "R1", "R2", "R2"],
            arrival_date="2026-07-20", departure_date="2026-07-24",
            checkin_at="2026-07-20T15:00:00Z", checkout_at="2026-07-24T11:00:00Z",
            contracted_bed_count=4, deposit_paid_cents=20000)
        g2, _p2, _r2, _i2 = setup_confirmed_group(
            building, rooms, client_name="Late Cancel",
            participant_specs=[("L P1", "1991-01-01", "ATTENDEE"),
                               ("L P2", "1991-01-02", "ATTENDEE"),
                               ("L P3", "1991-01-03", "ATTENDEE"),
                               ("L P4", "1991-01-04", "ATTENDEE")],
            assignment_room_map=["R3", "R3", "R4", "R4"],
            arrival_date="2026-07-20", departure_date="2026-07-24",
            checkin_at="2026-07-20T15:00:00Z", checkout_at="2026-07-24T11:00:00Z",
            contracted_bed_count=4, deposit_paid_cents=20000)
        return g1, g2

    def test_cancellation_fee_free_and_late_tiers(self, api):
        """PRD: "at least 31 days out, the fee is zero; at least 15 days out — so
        a cancellation exactly 30 days before arrival lands in this tier — the
        fee is twenty percent of the invoice's provisional_total_cents, rounded
        half-up; fewer than 15 days out — a cancellation exactly 14 days before
        arrival lands here — the fee is fifty percent, rounded half-up."

        Design: Corner/calculations/cancellation_fee_free_and_late_tiers
        """
        g1, g2 = self._confirmed_two_groups(api)
        set_clock("2026-06-15T00:00:00Z")  # 35 days before arrival 2026-07-20
        cancelled1 = validate_success(
            api.cancel_group(g1["id"], make_coordinator_headers(g1["id"])))
        assert cancelled1["cancellation_fee_cents"] == 0, "35 days out: free tier"
        set_clock("2026-07-06T00:00:00Z")  # exactly 14 days before arrival
        cancelled2 = validate_success(
            api.cancel_group(g2["id"], make_coordinator_headers(g2["id"])))
        assert cancelled2["cancellation_fee_cents"] == 36000, \
            "exactly 14 days out lands in the late tier: 50% of 72000"


class TestStayAssignmentListing:
    def test_filtered_list_stay_assignments_by_room(self, api):
        """PRD endpoint table: "GET `/stay-assignments` — List stay assignments;
        optional `revision_id`, `group_id`, `room_id`, `participant_id`, `status`
        filters"

        Design: Corner/endpoints/filtered_list_stay_assignments_by_room
        """
        building, rooms = create_building_turn_active(name="Kilo Hall", key_pool_size=5,
                                                      rooms=(("R1", 2), ("R2", 1)))
        group, participants, _revision = create_group_with_revision(
            building["id"], rooms, client_name="Filter Test",
            participant_specs=[("A One", "1990-01-01", "ATTENDEE"),
                               ("A Two", "1990-01-02", "ATTENDEE"),
                               ("A Three", "1990-01-03", "ATTENDEE")],
            assignment_room_map=["R1", "R1", "R2"],
            contracted_bed_count=3, deposit_paid_cents=0)
        data, meta = validate_paginated(api.list_stay_assignments(
            ADMIN, params={"room_id": rooms["R1"]["id"]}))
        assert len(data) == 2 and meta["total_count"] == 2
        assert all(row["room_id"] == rooms["R1"]["id"] for row in data)
        data2, meta2 = validate_paginated(api.list_stay_assignments(
            ADMIN, params={"room_id": rooms["R2"]["id"]}))
        assert len(data2) == 1 and meta2["total_count"] == 1
        assert data2[0]["room_id"] == rooms["R2"]["id"]
