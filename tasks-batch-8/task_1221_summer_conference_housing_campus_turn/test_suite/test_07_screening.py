"""Background screening: appeal loop, confirm gates, chaperone ratio."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_participant,
    clear_screening,
    create_building_turn_active,
    create_group,
    create_group_with_revision,
    flag_screening,
    get_group,
    get_success_data,
    make_coordinator_headers,
    submit_group,
    submit_screening,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SCREENING = TEST_USERS["screening_headers"]

MINOR_SPECS = [("Chap One", "1980-11-11", "CHAPERONE"),
               ("Kid One", "2013-01-01", "ATTENDEE")]


def _minor_group_submitted(api, building, rooms, name="Hayes Hall", deposit=11000,
                           client_name="STEM Girls"):
    """Minor-flagged group with chaperone + minor, a 2-assignment revision,
    walked to SUBMITTED. Returns (group, chaperone, kid)."""
    group, participants, _revision = create_group_with_revision(
        building["id"], rooms, client_name=client_name,
        participant_specs=list(MINOR_SPECS), assignment_room_map=["R1", "R1"],
        arrival_date="2026-06-22", departure_date="2026-06-26",
        checkin_at="2026-06-22T15:00:00Z", checkout_at="2026-06-26T11:00:00Z",
        contracted_bed_count=2, deposit_paid_cents=deposit,
        has_minor_participants=True)
    submit_group(group["id"])
    return get_group(group["id"]), participants[0], participants[1]


class TestScreeningAppealReversalLoop:
    def test_flagged_screening_blocks_confirm_until_appeal_clears(self, api):
        """PRD: "A flagged decision can be appealed by the group's coordinator,
        moving FLAGGED to APPEALED with the client's appeal_reason recorded. The
        reviewer then resolves the appeal with an outcome: CLEAR closes the
        appeal loop into CLEARED (again stamping decided_at and cleared_on)"
        PRD: "a minor-flagged group whose CHAPERONE or STAFF participant lacks
        any CLEARED screening is rejected with ERR_SCREENING_NOT_CLEARED"

        Design: Difficulty/non_linear_state_machine/screening_appeal_reversal_loop
        """
        building, rooms = create_building_turn_active(name="Hayes Hall",
                                                      key_pool_size=10,
                                                      rooms=(("R1", 2),))
        # Build the group and flag the chaperone's screening.
        group, chaperone, kid = _minor_group_submitted(api, building, rooms)
        screening = flag_screening(chaperone["id"], group["id"], "CONS-9")
        assert screening["status"] == "FLAGGED"

        resp = api.confirm_group(group["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_CLEARED)
        assert get_group(group["id"])["status"] == "SUBMITTED"

        appealed = validate_success(api.appeal_screening(
            screening["id"], "record expunged",
            make_coordinator_headers(group["id"])))
        assert appealed["status"] == "APPEALED"
        cleared = validate_success(
            api.resolve_appeal(screening["id"], "CLEAR", SCREENING))
        assert cleared["status"] == "CLEARED"
        assert cleared["cleared_on"] == "2026-05-01", \
            "the logical clock never advanced from its startup default"
        assert cleared["decided_at"] is not None

        confirmed = validate_success(api.confirm_group(group["id"], ADMIN))
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["provisional_invoice_id"], \
            "the post-appeal CLEARED screening unblocks the confirm gate"

    def test_appeal_loop_closes_into_cleared_terminal_state(self, api):
        """PRD: "`CLEAR` closes the appeal loop into `CLEARED` (again stamping
        `decided_at` and `cleared_on`), and `DENY` terminates the screening as
        `DENIED`. `CLEARED` and `DENIED` are terminal."

        Design: Difficulty/non_linear_state_machine/screening_appeal_reversal_loop
        """
        building, rooms = create_building_turn_active(name="Hayes Hall",
                                                      key_pool_size=10,
                                                      rooms=(("R1", 2),))
        group, chaperone, kid = _minor_group_submitted(api, building, rooms)
        screening = flag_screening(chaperone["id"], group["id"], "CONS-9")
        appealed = get_success_data(api.appeal_screening(
            screening["id"], "clerical error", make_coordinator_headers(group["id"])))
        assert appealed["status"] == "APPEALED"
        cleared = get_success_data(api.resolve_appeal(screening["id"], "CLEAR", SCREENING))
        assert cleared["status"] == "CLEARED"
        assert cleared["cleared_on"] == "2026-05-01"
        # CLEARED is terminal: a further decide attempt is an invalid transition.
        resp = api.decide_screening(screening["id"], "FLAG", SCREENING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestConfirmRequiresClearedScreenings:
    def test_flagged_screening_blocks_confirm_appeal_unblocks_with_invoice(
            self, api):
        """PRD: "a minor-flagged group whose CHAPERONE or STAFF participant lacks
        any CLEARED screening is rejected with ERR_SCREENING_NOT_CLEARED"
        PRD: "Success moves the group to CONFIRMED, creates its Invoice in
        PROVISIONAL status with the bed-night subtotal as its only component so
        far"

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_cleared_screenings
        """
        building, rooms = create_building_turn_active(name="Parker Hall",
                                                      key_pool_size=10,
                                                      rooms=(("R1", 2),))
        group, chaperone, kid = _minor_group_submitted(
            api, building, rooms, client_name="Chess Juniors")
        screening = flag_screening(chaperone["id"], group["id"], "CONS-7")

        resp = api.confirm_group(group["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_CLEARED)
        group_after = get_group(group["id"])
        assert group_after["status"] == "SUBMITTED"
        assert group_after["provisional_invoice_id"] is None, "no invoice on rejection"

        get_success_data(api.appeal_screening(
            screening["id"], "clerical error", make_coordinator_headers(group["id"])))
        get_success_data(api.resolve_appeal(screening["id"], "CLEAR", SCREENING))
        confirmed = validate_success(api.confirm_group(group["id"], ADMIN))
        assert confirmed["status"] == "CONFIRMED"
        invoice = get_success_data(
            api.get_invoice(confirmed["provisional_invoice_id"],
                            TEST_USERS["finance_headers"]))
        assert invoice["provisional_bed_night_subtotal_cents"] == 41400, \
            "2 assignments * 4 weeknights * round_half_up(4500*1.15)=5175"

    def test_undecided_screening_also_blocks_confirm(self, api):
        """PRD: "every participant whose `role_in_group` is `CHAPERONE` or `STAFF`
        must hold a cleared, unexpired background screening."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_cleared_screenings
        """
        building, rooms = create_building_turn_active(name="Parker Hall",
                                                      key_pool_size=10,
                                                      rooms=(("R1", 2),))
        group, chaperone, kid = _minor_group_submitted(
            api, building, rooms, client_name="Chess Juniors")
        screening = submit_screening(chaperone["id"], group["id"], "CONS-7")
        assert screening["status"] == "SUBMITTED"
        resp = api.confirm_group(group["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_CLEARED)
        assert get_group(group["id"])["status"] == "SUBMITTED"


class TestChaperoneRatio:
    def test_chaperone_ratio_unmet_aggregate(self, api):
        """PRD: "The chaperone ratio requires that the number of CHAPERONE
        participants whose is_minor is false be at least the total count of minor
        participants divided by ten and rounded up; a shortfall is rejected with
        ERR_CHAPERONE_RATIO_UNMET."

        Design: Corner/validations/chaperone_ratio_unmet_aggregate
        """
        building, rooms = create_building_turn_active(
            name="Sage Hall", key_pool_size=5,
            rooms=(("R1", 3), ("R2", 3), ("R3", 3), ("R4", 3)))
        specs = [("Chap One", "1980-01-01", "CHAPERONE")] + [
            (f"K{i:02d}", f"2013-01-{i:02d}", "ATTENDEE") for i in range(1, 12)]
        room_map = ["R1", "R1", "R1", "R2", "R2", "R2",
                    "R3", "R3", "R3", "R4", "R4", "R4"]
        group, participants, _revision = create_group_with_revision(
            building["id"], rooms, client_name="Big Youth Camp",
            participant_specs=specs, assignment_room_map=room_map,
            arrival_date="2026-06-22", departure_date="2026-06-26",
            checkin_at="2026-06-22T15:00:00Z", checkout_at="2026-06-26T11:00:00Z",
            contracted_bed_count=12, deposit_paid_cents=100000,
            has_minor_participants=True)
        # The chaperone's screening is CLEARED and the deposit is ample, so the
        # aggregate ratio (11 minors need ceil(11/10)=2 chaperones) is the sole
        # failing check.
        clear_screening(participants[0]["id"], group["id"], "CONS-BIG")
        submit_group(group["id"])
        resp = api.confirm_group(group["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CHAPERONE_RATIO_UNMET)


class TestScreeningSubmissionGate:
    def test_screening_submission_for_attendee_rejected(self, api):
        """PRD: "Screenings are accepted only for `CHAPERONE` and `STAFF`
        participants; submitting one for an `ATTENDEE` is rejected with
        `ERR_SCREENING_NOT_REQUIRED`."

        Design: Corner/validations/screening_submission_for_attendee_rejected
        """
        building, _rooms = create_building_turn_active(name="Upson Hall",
                                                       key_pool_size=5,
                                                       rooms=(("R1", 1),))
        group = create_group(building["id"], client_name="Role Screen",
                             arrival_date="2026-06-22", departure_date="2026-06-26",
                             contracted_bed_count=2, deposit_paid_cents=0,
                             has_minor_participants=True)
        headers = make_coordinator_headers(group["id"])
        attendee = add_participant(group["id"], full_name="Attendee",
                                   date_of_birth="1990-01-01",
                                   role_in_group="ATTENDEE")
        chaperone = add_participant(group["id"], full_name="Chaperone",
                                    date_of_birth="1980-01-01",
                                    role_in_group="CHAPERONE")
        resp = api.create_background_screening(
            attendee["id"], {"consent_reference": "CONS-X"}, headers)
        validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_REQUIRED)
        screening = validate_success(api.create_background_screening(
            chaperone["id"], {"consent_reference": "CONS-Y"}, headers),
            expected_status=201)
        assert screening["status"] == "SUBMITTED"
