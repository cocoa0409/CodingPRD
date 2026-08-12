"""Building season lifecycle, entity basics, listing/pagination, and not-found."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_conference_group,
    assert_participant,
    assert_rooming_list_revision,
    create_building_turn_active,
    create_building_payload,
    create_conference_group_payload,
    create_participant_payload,
    create_revision_payload,
    create_room_payload,
    get_assignment_for_participant,
    get_group,
    get_room,
    get_success_data,
    is_valid_uuid,
    make_coordinator_headers,
    set_clock,
    setup_confirmed_group,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
FACILITIES = TEST_USERS["facilities_headers"]
HOUSEKEEPING = TEST_USERS["housekeeping_headers"]


class TestBuildingEntityBasics:
    def test_create_building_missing_required_name_returns_400(self, api):
        """PRD: "The request body is then checked for well-formedness — required
        fields present, enum members valid, and foreign-key identifiers in the
        body referencing existing entities — with failures rejected as
        ERR_INVALID_REQUEST (HTTP 400)."

        Design: Corner/entities/create_building_missing_required_name_returns_400
        """
        payload = create_building_payload()
        del payload["name"]
        resp = api.create_building(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _data, meta = validate_paginated(api.list_buildings(ADMIN))
        assert meta["total_count"] == 0, "No building may be persisted by the rejected create"

    def test_group_optional_fields_defaults_applied(self, api):
        """PRD: "Optional fields at creation are has_minor_participants
        (defaulting to false), the linen_tier service level of STANDARD or DELUXE
        (defaulting to STANDARD; a DELUXE group lengthens the required turn window
        after its stay), and an initial deposit_paid_cents (defaulting to zero)."
        PRD: "New groups begin in DRAFT"

        Design: Corner/entities/group_optional_fields_defaults_applied
        """
        building = get_success_data(api.create_building(
            create_building_payload(name="Abbot Hall", key_pool_size=5), ADMIN))
        payload = create_conference_group_payload(building["id"], client_name="Minimalists")
        group = validate_success(api.create_conference_group(payload, ADMIN),
                                 expected_status=201)
        assert_conference_group(group)
        assert group["has_minor_participants"] is False
        assert group["linen_tier"] == "STANDARD"
        assert group["deposit_paid_cents"] == 0
        assert group["status"] == "DRAFT"

    def test_participant_is_minor_computed_at_arrival_date(self, api):
        """PRD: "The system derives is_minor for each participant: true when the
        participant's age at the group's arrival_date is strictly under 18."

        Design: Corner/entities/participant_is_minor_computed_at_arrival_date
        """
        building = get_success_data(api.create_building(
            create_building_payload(name="Bond Hall", key_pool_size=5), ADMIN))
        group = get_success_data(api.create_conference_group(
            create_conference_group_payload(
                building["id"], client_name="Age Test", arrival_date="2026-06-15",
                departure_date="2026-06-17", has_minor_participants=True,
                contracted_bed_count=2), ADMIN))
        headers = make_coordinator_headers(group["id"])
        minor = validate_success(api.add_participant(
            group["id"], create_participant_payload(
                full_name="Still Seventeen", date_of_birth="2008-07-01",
                role_in_group="ATTENDEE"), headers), expected_status=201)
        adult = validate_success(api.add_participant(
            group["id"], create_participant_payload(
                full_name="Just Eighteen", date_of_birth="2008-06-01",
                role_in_group="CHAPERONE"), headers), expected_status=201)
        assert_participant(minor)
        assert minor["is_minor"] is True, "17 at arrival 2026-06-15 is strictly under 18"
        assert adult["is_minor"] is False, "18th birthday 2026-06-01 is on/before arrival"

    def test_get_room_not_found_returns_404(self, api):
        """PRD: "The request is rejected with ERR_NOT_FOUND (HTTP 404) at the first
        path identifier that does not reference an existing resource"
        PRD error envelope: "The meta object for error responses contains only
        api_request_id and api_request_timestamp."

        Design: Corner/entities/get_room_not_found_returns_404
        """
        resp = api.get_room(NON_EXISTENT_UUID, ADMIN)
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert error.get("message"), "error envelope carries data.message"

    def test_room_creation_requires_existing_building(self, api):
        """PRD: "a request addressed to a room under a non-existent building
        therefore fails on the building identifier first."

        Design: Corner/entities/room_creation_requires_existing_building
        """
        resp = api.create_room(NON_EXISTENT_UUID, create_room_payload(bed_count=2),
                               FACILITIES)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestListingsAndRevisionShape:
    def test_list_groups_pagination_envelope(self, api):
        """PRD: "The limit parameter sets the maximum number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The offset
        parameter sets the number of items skipped and defaults to 0."
        PRD: "The meta object of a list response carries limit, offset,
        total_count, and has_more."

        Design: Corner/entities/list_groups_pagination_envelope
        """
        building = get_success_data(api.create_building(
            create_building_payload(name="Case Hall", key_pool_size=5), ADMIN))
        for name in ("G1", "G2", "G3"):
            get_success_data(api.create_conference_group(
                create_conference_group_payload(building["id"], client_name=name), ADMIN))
        data, meta = validate_paginated(
            api.list_conference_groups(ADMIN, params={"limit": 2, "offset": 2}))
        assert len(data) == 1, f"limit=2&offset=2 over 3 rows must skip 2 and return 1, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        data0, meta0 = validate_paginated(
            api.list_conference_groups(ADMIN, params={"limit": 2, "offset": 0}))
        assert len(data0) == 2 and meta0["has_more"] is True

    def test_rooming_list_revision_has_no_version_field(self, api):
        """PRD: "One entity is an exception: a RoomingListRevision is immutable
        once written and therefore carries only id and created_at — both
        updated_at and version are absent on revisions."
        PRD: "Each revision receives a per-group monotonically increasing
        revision_number starting at 1 and begins ACTIVE."

        Design: Corner/entities/rooming_list_revision_has_no_version_field
        """
        building, rooms = create_building_turn_active(name="Dana Hall", key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group = get_success_data(api.create_conference_group(
            create_conference_group_payload(building["id"], client_name="Immutable List"),
            ADMIN))
        participant = get_success_data(api.add_participant(
            group["id"], create_participant_payload(),
            make_coordinator_headers(group["id"])))
        group = get_group(group["id"])
        revision = validate_success(api.create_rooming_list_revision(
            group["id"],
            create_revision_payload(group["version"], [{
                "participant_id": participant["id"],
                "room_id": rooms["R1"]["id"],
                "checkin_at": "2026-06-15T15:00:00Z",
                "checkout_at": "2026-06-17T11:00:00Z",
            }]),
            make_coordinator_headers(group["id"])), expected_status=201)
        assert_rooming_list_revision(revision)
        assert revision["revision_number"] == 1
        assert revision["status"] == "ACTIVE"
        assert len(revision["assignment_ids"]) == 1
        assert is_valid_uuid(revision["id"])


class TestBuildingSeasonCycle:
    def test_building_full_season_cycle(self, api):
        """PRD: "The summer cycle starts when a FacilitiesManager initiates the
        release, moving the building from ACADEMIC_USE to RELEASE_REVIEW."
        PRD: "reopening for the academic year moves the building from
        READY_FOR_FALL back to ACADEMIC_USE: every room in READY or RELEASED
        returns to ACADEMIC_OCCUPIED, and released_bed_count, reserved_bed_count,
        and available_bed_count all reset to zero, closing the season cycle."

        Design: Corner/state_machines/building_full_season_cycle
        """
        building = get_success_data(api.create_building(
            create_building_payload(name="Ives Hall", key_pool_size=5), ADMIN))
        room = get_success_data(api.create_room(building["id"], create_room_payload(),
                                                FACILITIES))
        observed = []
        for call, _expected in [
            (api.initiate_release, "RELEASE_REVIEW"),
            (api.confirm_release, "RELEASED"),
            (api.begin_turn_season, "TURN_ACTIVE"),
            (api.begin_fall_prep, "FALL_PREP"),
            (api.certify_fall_ready, "READY_FOR_FALL"),
            (api.reopen_academic, "ACADEMIC_USE"),
        ]:
            building = validate_success(call(building["id"], FACILITIES))
            observed.append(building["status"])
        assert observed == ["RELEASE_REVIEW", "RELEASED", "TURN_ACTIVE",
                            "FALL_PREP", "READY_FOR_FALL", "ACADEMIC_USE"]
        room_after = get_success_data(api.get_room(room["id"], FACILITIES))
        assert room_after["status"] == "ACADEMIC_OCCUPIED", \
            "reopen-academic returns RELEASED/READY rooms to ACADEMIC_OCCUPIED"
        assert building["released_bed_count"] == 0
        assert building["reserved_bed_count"] == 0
        assert building["available_bed_count"] == 0

    def test_begin_fall_prep_blocked_by_open_turn_task(self, api):
        """PRD: "Beginning fall prep moves the building from TURN_ACTIVE to
        FALL_PREP, and is permitted only when no stay assignment in RESERVED or
        CHECKED_IN remains in any room of the building and no turn task in
        SCHEDULED, IN_PROGRESS, READY_FOR_INSPECTION, or FAILED remains open"

        Design: Corner/state_machines/begin_fall_prep_blocked_by_open_turn_task
        """
        building, rooms = create_building_turn_active(name="James Hall", key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, participants, _revision, _inv = setup_confirmed_group(building, rooms)
        set_clock("2026-06-15T16:00:00Z")
        assignment = get_assignment_for_participant(group["id"], participants[0]["id"])
        get_success_data(api.check_in_assignment(assignment["id"], ADMIN))
        set_clock("2026-06-17T10:00:00Z")
        get_success_data(api.check_out_assignment(assignment["id"], ADMIN))
        get_success_data(api.close_out_group(group["id"], ADMIN))
        room = get_room(rooms["R1"]["id"])
        task_id = room["active_turn_task_id"]
        assert task_id, "checkout of the last occupant spawns a turn task"

        resp = api.begin_fall_prep(building["id"], FACILITIES)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        get_success_data(api.start_turn_task(task_id, HOUSEKEEPING))
        get_success_data(api.submit_turn_task_for_inspection(task_id, HOUSEKEEPING))
        get_success_data(api.inspect_turn_task(task_id, "PASS", HOUSEKEEPING))
        building = validate_success(api.begin_fall_prep(building["id"], FACILITIES))
        assert building["status"] == "FALL_PREP"
