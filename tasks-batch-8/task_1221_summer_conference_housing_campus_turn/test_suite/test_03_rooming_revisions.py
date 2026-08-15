"""Rooming-list revisions: OCC, supersede cascade, booking-rule gauntlet."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
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
    setup_confirmed_group,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestOptimisticConcurrency:
    def test_occ_stale_group_version_on_revision_first_create_wins(self, api):
        """PRD: "Creating a new rooming-list revision for a group requires the
        request to carry expected_conference_group_version holding the group's
        version as the client last observed it; if the group's current version
        has advanced past that value, the creation is rejected with
        ERR_STALE_VERSION (HTTP 412)"

        Design: Corner/cross_cutting_layers/occ_stale_group_version_on_revision
        """
        building, rooms = create_building_turn_active(name="Uniform Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 2),))
        from test_helpers import add_participants
        group = create_group(building["id"], client_name="OCC Test", deposit_paid_cents=0)
        participants = add_participants(group["id"], [
            ("A One", "1990-01-01", "ATTENDEE"),
            ("A Two", "1990-01-02", "ATTENDEE"),
        ])
        headers = make_coordinator_headers(group["id"])
        stale_version = get_group(group["id"])["version"]
        entry1 = {"participant_id": participants[0]["id"], "room_id": rooms["R1"]["id"],
                  "checkin_at": "2026-06-15T15:00:00Z", "checkout_at": "2026-06-17T11:00:00Z"}
        revision = validate_success(api.create_rooming_list_revision(
            group["id"], create_revision_payload(stale_version, [entry1]), headers),
            expected_status=201)
        entry2 = {"participant_id": participants[1]["id"], "room_id": rooms["R1"]["id"],
                  "checkin_at": "2026-06-15T15:00:00Z", "checkout_at": "2026-06-17T11:00:00Z"}
        resp = api.create_rooming_list_revision(
            group["id"], create_revision_payload(stale_version, [entry2]), headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        rev_after = get_success_data(api.get_rooming_list_revision(revision["id"], ADMIN))
        assert rev_after["status"] == "ACTIVE", \
            "the stale second write must not supersede the first revision"

    def test_occ_stale_building_version_on_window(self, api):
        """PRD: "Creating a maintenance window on a building likewise requires
        expected_building_version matching the building's current version, with
        a mismatch rejected as ERR_STALE_VERSION (HTTP 412)"
        PRD: "The system derives the inclusive blocked interval:
        blocked_start_date is buffer_days before start_date, and
        blocked_end_date is buffer_days after end_date."

        Design: Corner/cross_cutting_layers/occ_stale_building_version_on_window
        """
        from test_helpers import create_building_released
        building, _rooms = create_building_released(name="Victor Hall", key_pool_size=5,
                                                    rooms=(("R1", 1),))
        stale_version = building["version"]  # captured right after confirm-release
        get_success_data(api.begin_turn_season(building["id"],
                                               TEST_USERS["facilities_headers"]))
        payload = {"start_date": "2026-08-10", "end_date": "2026-08-12",
                   "buffer_days": 1, "expected_building_version": stale_version}
        resp = api.create_maintenance_window(building["id"], payload,
                                             TEST_USERS["facilities_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_building(building["id"])["version"]
        payload["expected_building_version"] = fresh_version
        window = validate_success(api.create_maintenance_window(
            building["id"], payload, TEST_USERS["facilities_headers"]),
            expected_status=201)
        assert window["status"] == "PLANNED"
        assert window["blocked_start_date"] == "2026-08-09"
        assert window["blocked_end_date"] == "2026-08-13"


class TestBookingGauntlet:
    def test_participant_double_booking_overlap_rejected(self, api):
        """PRD: "Second, participant double-booking: if the same participant
        already holds a non-cancelled assignment on any room whose half-open
        interval intersects the new one, the request fails with
        ERR_OCCUPANCY_OVERLAP"

        Design: Corner/validations/participant_double_booking_overlap_rejected
        """
        building, rooms = create_building_turn_active(name="Juliet Hall", key_pool_size=5,
                                                      rooms=(("R1", 1), ("R2", 1)))
        group = create_group(building["id"], client_name="Double Book",
                             deposit_paid_cents=5000)
        from test_helpers import add_participant
        participant = add_participant(group["id"])
        headers = make_coordinator_headers(group["id"])
        version = get_group(group["id"])["version"]
        get_success_data(api.create_rooming_list_revision(
            group["id"], create_revision_payload(version, [{
                "participant_id": participant["id"], "room_id": rooms["R1"]["id"],
                "checkin_at": "2026-06-15T15:00:00Z",
                "checkout_at": "2026-06-19T11:00:00Z",
            }]), headers))
        version2 = get_group(group["id"])["version"]
        resp = api.create_rooming_list_revision(
            group["id"], create_revision_payload(version2, [
                {"participant_id": participant["id"], "room_id": rooms["R1"]["id"],
                 "checkin_at": "2026-06-15T15:00:00Z", "checkout_at": "2026-06-19T11:00:00Z"},
                {"participant_id": participant["id"], "room_id": rooms["R2"]["id"],
                 "checkin_at": "2026-06-17T15:00:00Z", "checkout_at": "2026-06-21T11:00:00Z"},
            ]), headers)
        validate_error(resp, ApiErrorId.ERR_OCCUPANCY_OVERLAP)
        revisions, _meta = validate_paginated(
            api.list_rooming_list_revisions(group["id"], ADMIN))
        assert len(revisions) == 1, "the rejected revision must not be persisted"
        assert revisions[0]["revision_number"] == 1
        assert revisions[0]["status"] == "ACTIVE"

    def test_room_not_reservable_during_turn(self, api):
        """PRD: "First, the target room must be reservable — RELEASED, READY,
        RESERVED, or OCCUPIED; a room in NEEDS_TURN, IN_TURN, or OUT_OF_SERVICE
        rejects the assignment with ERR_ROOM_NOT_RESERVABLE."

        Design: Corner/validations/room_not_reservable_during_turn
        """
        building, rooms = create_building_turn_active(name="Echo Hall", key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group_a, participants_a, _rev, _inv = setup_confirmed_group(
            building, rooms, client_name="GA")
        from test_helpers import set_clock
        set_clock("2026-06-15T16:00:00Z")
        assignment = get_assignment_for_participant(group_a["id"], participants_a[0]["id"])
        get_success_data(api.check_in_assignment(assignment["id"], ADMIN))
        set_clock("2026-06-17T10:00:00Z")
        get_success_data(api.check_out_assignment(assignment["id"], ADMIN))
        room = get_room(rooms["R1"]["id"])
        assert room["status"] == "NEEDS_TURN", "last checkout leaves the room NEEDS_TURN"

        group_b = create_group(building["id"], client_name="GB",
                               arrival_date="2026-06-19", departure_date="2026-06-21",
                               deposit_paid_cents=5000)
        from test_helpers import add_participant
        participant_b = add_participant(group_b["id"], full_name="GB P1",
                                        date_of_birth="1991-01-01")
        version_b = get_group(group_b["id"])["version"]
        resp = api.create_rooming_list_revision(
            group_b["id"],
            create_revision_payload(version_b, [{
                "participant_id": participant_b["id"], "room_id": rooms["R1"]["id"],
                "checkin_at": "2026-06-19T15:00:00Z",
                "checkout_at": "2026-06-21T11:00:00Z",
            }]),
            make_coordinator_headers(group_b["id"]))
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_RESERVABLE)


class TestSupersedeAccounting:
    def test_superseded_revision_assignment_cancel_rejected(self, api):
        """PRD: "operating on an assignment that belongs to a SUPERSEDED revision
        — for instance cancelling one of its already-cancelled assignments — is
        rejected with ERR_REVISION_SUPERSEDED."

        Design: Corner/validations/superseded_revision_assignment_cancel_rejected
        """
        building, rooms = create_building_turn_active(name="Delta Hall", key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group = create_group(building["id"], client_name="Supersede", deposit_paid_cents=0)
        from test_helpers import add_participant
        participant = add_participant(group["id"])
        headers = make_coordinator_headers(group["id"])
        version = get_group(group["id"])["version"]
        entry = {"participant_id": participant["id"], "room_id": rooms["R1"]["id"],
                 "checkin_at": "2026-06-15T15:00:00Z",
                 "checkout_at": "2026-06-17T11:00:00Z"}
        rev1 = get_success_data(api.create_rooming_list_revision(
            group["id"], create_revision_payload(version, [entry]), headers))
        old_assignment_id = rev1["assignment_ids"][0]
        version2 = get_group(group["id"])["version"]
        get_success_data(api.create_rooming_list_revision(
            group["id"], create_revision_payload(version2, [entry]), headers))

        resp = api.cancel_assignment(old_assignment_id, headers)
        validate_error(resp, ApiErrorId.ERR_REVISION_SUPERSEDED)

    def test_bed_reserve_supersede_cancel_conservation(self, api):
        """PRD: "available_bed_count is always released_bed_count minus
        reserved_bed_count, recomputed on every assignment creation,
        cancellation, no-show, and checkout."
        PRD: "every one of its stay assignments still in RESERVED is cancelled,
        with the room and building counter effects of a cancellation"

        Design: Difficulty/compensating_invariant/bed_reserve_supersede_cancel_conservation
        """
        from test_helpers import add_participants, assert_bed_ledger_invariant
        building, rooms = create_building_turn_active(name="Sloan Hall", key_pool_size=10,
                                                      rooms=(("R3", 3), ("R4", 3)))
        group = create_group(building["id"], client_name="Track Club",
                             arrival_date="2026-07-06", departure_date="2026-07-10",
                             contracted_bed_count=4, deposit_paid_cents=5000)
        participants = add_participants(group["id"], [
            ("A One", "1994-01-01", "ATTENDEE"), ("A Two", "1994-01-02", "ATTENDEE"),
            ("A Three", "1994-01-03", "ATTENDEE"), ("A Four", "1994-01-04", "ATTENDEE"),
        ])
        headers = make_coordinator_headers(group["id"])
        room_ids = [rooms["R3"]["id"], rooms["R3"]["id"], rooms["R4"]["id"], rooms["R4"]["id"]]
        entries = [{"participant_id": p["id"], "room_id": rid,
                    "checkin_at": "2026-07-06T15:00:00Z",
                    "checkout_at": "2026-07-10T11:00:00Z"}
                   for p, rid in zip(participants, room_ids)]
        version = get_group(group["id"])["version"]
        rev1 = get_success_data(api.create_rooming_list_revision(
            group["id"], create_revision_payload(version, entries), headers))
        b1 = get_building(building["id"])
        assert b1["reserved_bed_count"] == 4 and b1["available_bed_count"] == 2
        assert_bed_ledger_invariant(b1)

        entries2 = [{"participant_id": participants[0]["id"], "room_id": rooms["R3"]["id"],
                     "checkin_at": "2026-07-06T15:00:00Z",
                     "checkout_at": "2026-07-10T11:00:00Z"},
                    {"participant_id": participants[1]["id"], "room_id": rooms["R4"]["id"],
                     "checkin_at": "2026-07-06T15:00:00Z",
                     "checkout_at": "2026-07-10T11:00:00Z"}]
        version2 = get_group(group["id"])["version"]
        get_success_data(api.create_rooming_list_revision(
            group["id"], create_revision_payload(version2, entries2), headers))
        rev1_after = get_success_data(api.get_rooming_list_revision(rev1["id"], ADMIN))
        assert rev1_after["status"] == "SUPERSEDED"
        b2 = get_building(building["id"])
        assert b2["reserved_bed_count"] == 2 and b2["available_bed_count"] == 4
        assert_bed_ledger_invariant(b2)

        get_success_data(api.cancel_group(group["id"], headers))
        b3 = get_building(building["id"])
        assert b3["reserved_bed_count"] == 0 and b3["available_bed_count"] == 6, \
            "the compensating cancel returns the ledger to zero drift"
        assert_bed_ledger_invariant(b3)
        for key in ("R3", "R4"):
            assert get_room(rooms[key]["id"])["status"] == "RELEASED"

    def test_bed_invariant_holds_after_revision_creation(self, api):
        """PRD: "The building's reserved_bed_count increases by the number of new
        assignments and available_bed_count is recomputed, with the building's
        version incrementing."

        Design: Difficulty/compensating_invariant/bed_reserve_supersede_cancel_conservation
        """
        from test_helpers import add_participants, assert_bed_ledger_invariant
        building, rooms = create_building_turn_active(name="Sloan Hall", key_pool_size=10,
                                                      rooms=(("R3", 3), ("R4", 3)))
        group = create_group(building["id"], client_name="Track Club",
                             arrival_date="2026-07-06", departure_date="2026-07-10",
                             contracted_bed_count=4, deposit_paid_cents=5000)
        participants = add_participants(group["id"], [
            ("A One", "1994-01-01", "ATTENDEE"), ("A Two", "1994-01-02", "ATTENDEE"),
            ("A Three", "1994-01-03", "ATTENDEE"), ("A Four", "1994-01-04", "ATTENDEE"),
        ])
        headers = make_coordinator_headers(group["id"])
        entries = [{"participant_id": p["id"], "room_id": rid,
                    "checkin_at": "2026-07-06T15:00:00Z",
                    "checkout_at": "2026-07-10T11:00:00Z"}
                   for p, rid in zip(participants,
                                     [rooms["R3"]["id"], rooms["R3"]["id"],
                                      rooms["R4"]["id"], rooms["R4"]["id"]])]
        version = get_group(group["id"])["version"]
        get_success_data(api.create_rooming_list_revision(
            group["id"], create_revision_payload(version, entries), headers))
        building_after = get_building(building["id"])
        assert building_after["released_bed_count"] == 6
        assert building_after["reserved_bed_count"] == 4
        assert building_after["available_bed_count"] == 2
        assert_bed_ledger_invariant(building_after)
        for key in ("R3", "R4"):
            assert get_room(rooms[key]["id"])["status"] == "RESERVED", \
                "the first active assignment on a RELEASED room flips it to RESERVED"
