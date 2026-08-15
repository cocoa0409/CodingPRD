"""Conference group lifecycle: review loop, invalid transitions, lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_building_turn_active,
    create_conference_group_payload,
    create_participant_payload,
    create_revision_payload,
    create_building_payload,
    get_assignment_for_participant,
    get_building,
    get_group,
    get_room,
    get_success_data,
    make_coordinator_headers,
    set_clock,
    setup_confirmed_group,
    setup_paid_group,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
FACILITIES = TEST_USERS["facilities_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestReviewLoop:
    def test_resubmit_returned_group_revision_loop(self, api):
        """PRD: "When the client is ready for review, submission moves the group
        from DRAFT — or from RETURNED on the resubmission loop — to SUBMITTED,
        requiring at least one participant to exist. An admin who finds the
        submission deficient returns it for revision, moving SUBMITTED back to
        RETURNED so the coordinator can correct and resubmit."

        Design: Corner/state_machines/resubmit_returned_group_revision_loop
        """
        building = get_success_data(api.create_building(
            create_building_payload(name="Ellis Hall", key_pool_size=5), ADMIN))
        group = get_success_data(api.create_conference_group(
            create_conference_group_payload(building["id"], client_name="Loop Group"),
            ADMIN))
        headers = make_coordinator_headers(group["id"])
        get_success_data(api.add_participant(
            group["id"], create_participant_payload(), headers))
        group = get_success_data(api.submit_group(group["id"], headers))
        assert group["status"] == "SUBMITTED"

        group = validate_success(api.return_for_revision(group["id"], ADMIN))
        assert group["status"] == "RETURNED"
        group = validate_success(api.submit_group(group["id"], headers))
        assert group["status"] == "SUBMITTED", \
            "resubmission from RETURNED traverses the review loop"

    def test_submit_already_submitted_group_rejected(self, api):
        """PRD: "submission moves the group from `DRAFT` — or from `RETURNED` on
        the resubmission loop — to `SUBMITTED`, requiring at least one
        participant to exist."
        PRD §2.6: state-machine legality checks reject with "ERR_INVALID_STATE".

        Design: Corner/state_machines/submit_already_submitted_group_rejected
        """
        building = get_success_data(api.create_building(
            create_building_payload(name="Field Hall", key_pool_size=5), ADMIN))
        group = get_success_data(api.create_conference_group(
            create_conference_group_payload(building["id"], client_name="Twice Submit"),
            ADMIN))
        headers = make_coordinator_headers(group["id"])
        get_success_data(api.add_participant(
            group["id"], create_participant_payload(), headers))
        group = get_success_data(api.submit_group(group["id"], headers))
        version_before = group["version"]

        resp = api.submit_group(group["id"], headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        group_after = get_group(group["id"])
        assert group_after["status"] == "SUBMITTED"
        assert group_after["version"] == version_before, \
            "a rejected transition must not mutate the group"


class TestCancelAndTerminalStates:
    def test_cancel_in_house_group_rejected(self, api):
        """PRD: "A coordinator (or admin) cancels a group from DRAFT, SUBMITTED,
        RETURNED, or CONFIRMED; from IN_HOUSE, DEPARTED, CLOSED, or CANCELLED the
        attempt is rejected with ERR_GROUP_NOT_CANCELLABLE."

        Design: Corner/state_machines/cancel_in_house_group_rejected
        """
        building, rooms = create_building_turn_active(name="Gray Hall", key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, participants, _rev, _inv = setup_confirmed_group(
            building, rooms, client_name="In House")
        set_clock("2026-06-15T16:00:00Z")
        assignment = get_assignment_for_participant(group["id"], participants[0]["id"])
        assignment = get_success_data(api.check_in_assignment(assignment["id"], ADMIN))
        group = get_group(group["id"])
        assert group["status"] == "IN_HOUSE"

        resp = api.cancel_group(group["id"], make_coordinator_headers(group["id"]))
        validate_error(resp, ApiErrorId.ERR_GROUP_NOT_CANCELLABLE)
        group_after = get_group(group["id"])
        assignment_after = get_success_data(
            api.get_stay_assignment(assignment["id"], ADMIN))
        building_after = get_building(building["id"])
        assert group_after["status"] == "IN_HOUSE"
        assert assignment_after["status"] == "CHECKED_IN"
        assert building_after["reserved_bed_count"] == 1, "no counters change on rejection"

    def test_closed_group_terminal_lockdown(self, api):
        """PRD: "On success the invoice moves to PAID, paid_at is stamped from the
        clock, and the group bubbles from DEPARTED to its terminal CLOSED state."
        PRD: "from IN_HOUSE, DEPARTED, CLOSED, or CANCELLED the attempt is
        rejected with ERR_GROUP_NOT_CANCELLABLE."

        Design: Corner/state_machines/closed_group_terminal_lockdown
        """
        building, rooms = create_building_turn_active(name="Holt Hall", key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, invoice = setup_paid_group(building, rooms, client_name="Terminal")
        assert group["status"] == "CLOSED", \
            "recording payment on the DEPARTED group's invoice closes the group"
        assert invoice["total_cents"] == 9000, "2 actual nights * 4500 base rate"
        assert invoice["balance_due_cents"] == 4000, "total 9000 minus deposit 5000"

        headers = make_coordinator_headers(group["id"])
        validate_error(api.submit_group(group["id"], headers),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.cancel_group(group["id"], headers),
                       ApiErrorId.ERR_GROUP_NOT_CANCELLABLE)
        validate_error(api.close_out_group(group["id"], ADMIN),
                       ApiErrorId.ERR_INVALID_STATE)


class TestCheckinGating:
    def test_checkin_requires_group_confirmed_rejected_leg(self, api):
        """PRD: "Its checks fire in order: the assignment must be RESERVED, its
        group must be CONFIRMED or IN_HOUSE, and the room must be RESERVED or
        OCCUPIED — violations reject with ERR_INVALID_STATE"

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_group_confirmed
        """
        building, rooms = create_building_turn_active(name="Owen Hall", key_pool_size=10,
                                                      rooms=(("R1", 1),))
        from test_helpers import create_group_with_revision
        group, participants, revision = create_group_with_revision(
            building["id"], rooms, client_name="Poetry Society",
            deposit_paid_cents=3000)
        assignment = get_assignment_for_participant(group["id"], participants[0]["id"])
        set_clock("2026-06-15T16:00:00Z")

        resp = api.check_in_assignment(assignment["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_stay_assignment(assignment["id"], ADMIN))
        assert after["status"] == "RESERVED", \
            "check-in while the group is DRAFT is rejected and the stay is untouched"

    def test_checkin_requires_group_confirmed_success_leg(self, api):
        """PRD: "if it is the first check-in of the whole group, the group bubbles
        from CONFIRMED to IN_HOUSE."

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_group_confirmed
        """
        building, rooms = create_building_turn_active(name="Owen Hall", key_pool_size=10,
                                                      rooms=(("R1", 1),))
        from test_helpers import create_group_with_revision
        group, participants, revision = create_group_with_revision(
            building["id"], rooms, client_name="Poetry Society",
            deposit_paid_cents=3000)
        assignment = get_assignment_for_participant(group["id"], participants[0]["id"])
        set_clock("2026-06-15T16:00:00Z")

        get_success_data(api.submit_group(group["id"], make_coordinator_headers(group["id"])))
        get_success_data(api.confirm_group(group["id"], ADMIN))
        checked = validate_success(api.check_in_assignment(assignment["id"], ADMIN))
        assert checked["status"] == "CHECKED_IN"
        group_after = get_group(group["id"])
        assert group_after["status"] == "IN_HOUSE", \
            "the first check-in of the group bubbles CONFIRMED -> IN_HOUSE"
