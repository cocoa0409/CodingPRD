"""Excursion investigation workflows: the rejection cycle, approval
segregation, validation ordering, and the derived room posture."""
from test_helpers import (
    QA,
    ApiErrorId,
    add_sampling_point,
    approve_investigation,
    assert_investigation,
    close_excursion,
    create_investigation_payload,
    create_room,
    get_success_data,
    make_qa_headers,
    open_investigation,
    record_excursion_sample,
    record_sample,
    setup_certified_room,
    validate_error,
    validate_success,
)


def _iso7_room_with_point(room_code):
    room = create_room(room_code=room_code)
    point = add_sampling_point(room["id"], point_code=f"SP-{room_code}",
                               metric="PARTICLE")
    return room, point


def _iso5_viable_room(room_code):
    room = create_room(room_code=room_code, iso_class="ISO_5",
                       particle_alert_limit=100000, particle_action_limit=352000,
                       viable_alert_limit=10, viable_action_limit=20)
    point = add_sampling_point(room["id"], point_code=f"SP-{room_code}",
                               metric="VIABLE")
    return room, point


class TestInvestigationRejectionCycle:
    def test_investigation_rejection_loops_excursion_back_to_open(self, api):
        """PRD §3.4: "Rejection likewise requires a `DRAFT` investigation
        (`ERR_INVESTIGATION_NOT_DRAFT`); it moves the investigation to terminal
        `REJECTED` and loops the excursion back from `UNDER_INVESTIGATION` to
        `OPEN` — a cycle that may repeat without bound until an investigation
        survives approval — and the recomputed posture stays raised while the
        excursion stands open again."

        Design: Difficulty/non_linear_state_machine/excursion_investigation_rejection_cycle
        """
        room, point = _iso7_room_with_point("CR-F")
        _sample, excursion_id = record_excursion_sample(
            point["id"], 300500, tech_user_id="tech-1")

        investigation = open_investigation(
            excursion_id, root_cause="Initial investigation, rejected later",
            investigator_id="qa-1")
        assert investigation["status"] == "DRAFT"
        assert get_success_data(api.get_excursion(excursion_id, QA))["status"] == (
            "UNDER_INVESTIGATION")

        rejected = validate_success(
            api.reject_investigation(investigation["id"], make_qa_headers("qa-2")), 200)
        assert_investigation(rejected)
        assert rejected["status"] == "REJECTED"
        excursion = get_success_data(api.get_excursion(excursion_id, QA))
        assert excursion["status"] == "OPEN", (
            "rejection loops the excursion back to OPEN")

    def test_excursion_investigation_cycle_is_repeatable(self, api):
        """PRD §3.4: "it moves the investigation to terminal `REJECTED` and
        loops the excursion back from `UNDER_INVESTIGATION` to `OPEN` — a cycle
        that may repeat without bound until an investigation survives
        approval".
        PRD §3.4: "Opening one requires the excursion to stand `OPEN`
        (`ERR_EXCURSION_NOT_OPEN`) and requires that no other investigation for
        the same excursion already sits in `DRAFT` — exactly one open
        investigation per excursion (`ERR_INVESTIGATION_ALREADY_OPEN`)."

        Design: Difficulty/non_linear_state_machine/excursion_investigation_rejection_cycle
        """
        room, point = _iso7_room_with_point("CR-F")
        _sample, excursion_id = record_excursion_sample(
            point["id"], 300500, tech_user_id="tech-1")
        first = open_investigation(
            excursion_id, root_cause="Initial investigation, rejected later",
            investigator_id="qa-1")
        get_success_data(
            api.reject_investigation(first["id"], make_qa_headers("qa-2")))

        resp = api.open_investigation(
            excursion_id,
            create_investigation_payload(
                root_cause="Second investigation after rejection loop"),
            make_qa_headers("qa-1"),
        )
        second = validate_success(resp, 201)
        assert second["status"] == "DRAFT"
        assert second["excursion_id"] == excursion_id
        excursion = get_success_data(api.get_excursion(excursion_id, QA))
        assert excursion["status"] == "UNDER_INVESTIGATION", (
            "a fresh investigation re-enters UNDER_INVESTIGATION after a rejection")


class TestValidationOrdering:
    def test_state_error_beats_segregation_when_approving_approved_investigation(
            self, api):
        """PRD §2.10: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order so that the surfaced
        error is deterministic".
        PRD §2.10: "5. Whether the target entity stands in a state from which
        the requested transition exists (`ERR_INVALID_STATE`)."
        PRD §2.10: "8. Segregation of duties on the four pairs of §2.8
        (`ERR_SEGREGATION_OF_DUTIES`)."
        PRD §3.4: "Approval requires the investigation to still stand `DRAFT`
        (`ERR_INVESTIGATION_NOT_DRAFT`) and requires the approver's `X-User-ID`
        to differ from the investigation's `investigated_by_user_id`
        (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_segregation_of_duties
        """
        room, point = _iso7_room_with_point("CR-I")
        _sample, excursion_id = record_excursion_sample(
            point["id"], 300500, tech_user_id="tech-i")
        investigation = open_investigation(
            excursion_id, root_cause="Investigation narrative for CR-I alert",
            investigator_id="qa-i1")
        approve_investigation(investigation["id"], approver_id="qa-i2")

        # qa-i1 is the investigator: both the state gate (already APPROVED) and
        # segregation are violated; the state check is evaluated first.
        resp = api.approve_investigation(investigation["id"], make_qa_headers("qa-i1"))
        validate_error(resp, ApiErrorId.ERR_INVESTIGATION_NOT_DRAFT)
        assert get_success_data(
            api.get_investigation(investigation["id"], QA))["status"] == "APPROVED"

    def test_state_error_when_approving_approved_investigation_by_other_user(
            self, api):
        """PRD §3.4: "Approval requires the investigation to still stand
        `DRAFT` (`ERR_INVESTIGATION_NOT_DRAFT`) and requires the approver's
        `X-User-ID` to differ from the investigation's `investigated_by_user_id`
        (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_segregation_of_duties
        """
        room, point = _iso7_room_with_point("CR-I")
        _sample, excursion_id = record_excursion_sample(
            point["id"], 300500, tech_user_id="tech-i")
        investigation = open_investigation(
            excursion_id, root_cause="Investigation narrative for CR-I alert",
            investigator_id="qa-i1")
        approve_investigation(investigation["id"], approver_id="qa-i2")

        # A third party with no segregation conflict still hits the state gate.
        resp = api.approve_investigation(investigation["id"], make_qa_headers("qa-i3"))
        validate_error(resp, ApiErrorId.ERR_INVESTIGATION_NOT_DRAFT)

    def test_second_investigation_open_reports_state_error(self, api):
        """PRD §2.10: "5. Whether the target entity stands in a state from
        which the requested transition exists (`ERR_INVALID_STATE`)."
        PRD §2.10: "13. Aggregate guards — no second draft investigation per
        excursion (`ERR_INVESTIGATION_ALREADY_OPEN`), no second active or
        validated cleaning program per room (`ERR_PROGRAM_ALREADY_ACTIVE`), no
        second open entry log for the same personnel-and-room pair
        (`ERR_ENTRY_ALREADY_OPEN`), traveler step order
        (`ERR_TRAVELER_STEP_ORDER`), batch release with unsettled travelers
        (`ERR_BATCH_TRAVELERS_UNSETTLED`), audit close with unverified findings
        (`ERR_AUDIT_FINDINGS_OPEN`), and certification with open excursions
        (`ERR_OPEN_EXCURSIONS_BLOCK_CERTIFICATION`) or without a validated
        cleaning program (`ERR_CLEANING_NOT_VALIDATED`)."
        PRD §3.4: "Opening one requires the excursion to stand `OPEN`
        (`ERR_EXCURSION_NOT_OPEN`) and requires that no other investigation for
        the same excursion already sits in `DRAFT` — exactly one open
        investigation per excursion (`ERR_INVESTIGATION_ALREADY_OPEN`)."

        Design: Corner/validations/investigation_state_check_fires_before_aggregate_guard
        """
        room, point = _iso5_viable_room("CR-V5")
        _sample, excursion_id = record_excursion_sample(
            point["id"], 15, tech_user_id="tech-v5")
        open_investigation(excursion_id,
                           root_cause="First investigation narrative for V5",
                           investigator_id="qa-v5a")

        # Excursion is UNDER_INVESTIGATION and a DRAFT exists: the state gate
        # (priority 5) precedes the aggregate guard (priority 13).
        resp = api.open_investigation(
            excursion_id,
            create_investigation_payload(
                root_cause="Second investigation attempt narrative"),
            make_qa_headers("qa-v5b"),
        )
        validate_error(resp, ApiErrorId.ERR_EXCURSION_NOT_OPEN)

    def test_open_investigation_on_closed_excursion_rejected(self, api):
        """PRD §3.4: "Opening one requires the excursion to stand `OPEN`
        (`ERR_EXCURSION_NOT_OPEN`) and requires that no other investigation for
        the same excursion already sits in `DRAFT` — exactly one open
        investigation per excursion (`ERR_INVESTIGATION_ALREADY_OPEN`)."

        Design: Corner/errors/error_excursion_not_open_on_investigate_closed
        """
        room, point = _iso5_viable_room("CR-ER7")
        _sample, excursion_id = record_excursion_sample(
            point["id"], 15, tech_user_id="tech-er7")
        close_excursion(excursion_id,
                        root_cause="Investigation narrative for ER7 closure",
                        investigator_id="qa-er7a", approver_id="qa-er7b")

        resp = api.open_investigation(
            excursion_id,
            create_investigation_payload(
                root_cause="Attempt on closed excursion narrative"),
            make_qa_headers("qa-er7a"),
        )
        validate_error(resp, ApiErrorId.ERR_EXCURSION_NOT_OPEN)


class TestInvestigationSegregation:
    def test_investigator_cannot_approve_own_investigation(self, api):
        """PRD §2.8: "The QA who opened an investigation (anchored as its
        `investigated_by_user_id`) may not approve that same investigation."
        PRD §3.4: "Approval requires the investigation to still stand `DRAFT`
        (`ERR_INVESTIGATION_NOT_DRAFT`) and requires the approver's `X-User-ID`
        to differ from the investigation's `investigated_by_user_id`
        (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/roles/segregation_of_duties_investigator_cannot_approve_own
        """
        room, point = _iso5_viable_room("CR-RB4")
        _sample, excursion_id = record_excursion_sample(
            point["id"], 15, tech_user_id="tech-rb4")
        investigation = open_investigation(
            excursion_id,
            root_cause="Investigation narrative for RB4 segregation",
            investigator_id="qa-rb4a")
        assert investigation["investigated_by_user_id"] == "qa-rb4a"

        resp = api.approve_investigation(investigation["id"],
                                         make_qa_headers("qa-rb4a"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = validate_success(api.approve_investigation(
            investigation["id"], make_qa_headers("qa-rb4b")), 200)
        assert approved["status"] == "APPROVED"
        assert get_success_data(api.get_excursion(excursion_id, QA))["status"] == "CLOSED"


class TestPostureDerivationConservation:
    def test_closing_one_of_two_open_excursions_keeps_alert(self, api):
        """PRD §2.7: "Otherwise, if any excursion of the room stands in `OPEN`
        or `UNDER_INVESTIGATION` with severity `ALERT`, the posture is
        `ALERT`."
        PRD §2.7: "Closing the last open alert excursion while certification
        stands `CERTIFIED` returns the room from `ALERT` to `IN_CONTROL`; an
        alert-severity excursion entering the open set raises `IN_CONTROL` to
        `ALERT`, and an action-severity excursion entering the open set raises
        the room to `ACTION`."

        Design: Difficulty/compensating_invariant/excursion_raise_close_conserves_posture_derivation
        """
        room = setup_certified_room(room_code="CR-R")
        point = add_sampling_point(room["id"], point_code="SP-R", metric="VIABLE")
        _s1, exc1 = record_excursion_sample(point["id"], 75,
                                            sampled_at="2026-08-01T09:00:00Z")
        _s2, exc2 = record_excursion_sample(point["id"], 80,
                                            sampled_at="2026-08-01T09:30:00Z")

        close_excursion(exc1,
                        root_cause="First excursion investigation narrative",
                        investigator_id="qa-r1", approver_id="qa-r2")
        room_mid = get_success_data(api.get_room(room["id"], QA))
        assert room_mid["environment_posture"] == "ALERT", (
            "one of two alert excursions is still open")

        close_excursion(exc2,
                        root_cause="Second excursion investigation narrative",
                        investigator_id="qa-r1", approver_id="qa-r2")
        room_end = get_success_data(api.get_room(room["id"], QA))
        assert room_end["environment_posture"] == "IN_CONTROL"

    def test_closing_all_open_excursions_restores_in_control(self, api):
        """PRD §2.7: "Closing the last open alert excursion while certification
        stands `CERTIFIED` returns the room from `ALERT` to `IN_CONTROL`; an
        alert-severity excursion entering the open set raises `IN_CONTROL` to
        `ALERT`, and an action-severity excursion entering the open set raises
        the room to `ACTION`."
        PRD §2.7: "Otherwise, the posture is `IN_CONTROL`."

        Design: Difficulty/compensating_invariant/excursion_raise_close_conserves_posture_derivation
        """
        room = setup_certified_room(room_code="CR-R")
        point = add_sampling_point(room["id"], point_code="SP-R", metric="VIABLE")
        _s1, exc1 = record_excursion_sample(point["id"], 75,
                                            sampled_at="2026-08-01T09:00:00Z")
        _s2, exc2 = record_excursion_sample(point["id"], 80,
                                            sampled_at="2026-08-01T09:30:00Z")
        close_excursion(exc1,
                        root_cause="First excursion investigation narrative",
                        investigator_id="qa-r1", approver_id="qa-r2")
        close_excursion(exc2,
                        root_cause="Second excursion investigation narrative",
                        investigator_id="qa-r1", approver_id="qa-r2")

        room_end = get_success_data(api.get_room(room["id"], QA))
        assert room_end["environment_posture"] == "IN_CONTROL", (
            "zero open excursions with CERTIFIED standing: full recovery, no drift")
        assert room_end["certification_status"] == "CERTIFIED"
        for excursion_id in (exc1, exc2):
            assert get_success_data(
                api.get_excursion(excursion_id, QA))["status"] == "CLOSED"


class TestParallelRoomDimensions:
    def test_alert_excursion_raises_posture_without_touching_certification(self, api):
        """PRD §3.3: "The room posture is recomputed in the same breath — a
        first alert-severity excursion moves `IN_CONTROL` to `ALERT`, and an
        action-severity excursion raises the room to `ACTION`."

        Design: Difficulty/non_linear_state_machine/cleanroom_parallel_dimensions_move_independently
        """
        room = setup_certified_room(
            room_code="CR-E", iso_class="ISO_8",
            particle_alert_limit=3500000, particle_action_limit=3520000,
            viable_alert_limit=100, viable_action_limit=200)
        point = add_sampling_point(room["id"], point_code="SP-E", metric="VIABLE")

        sample = record_sample(point["id"], 150, sampled_at="2026-08-01T11:00:00Z")
        assert sample["classification"] == "ALERT_EXCEEDED", (
            "150 >= viable alert 100, < action 200")
        room_mid = get_success_data(api.get_room(room["id"], QA))
        assert room_mid["environment_posture"] == "ALERT"
        assert room_mid["certification_status"] == "CERTIFIED", (
            "the certification dimension does not move when posture raises")

    def test_closing_alert_excursion_recovers_posture_with_certification_intact(
            self, api):
        """PRD §2.7: "Closing the last open alert excursion while certification
        stands `CERTIFIED` returns the room from `ALERT` to `IN_CONTROL`; an
        alert-severity excursion entering the open set raises `IN_CONTROL` to
        `ALERT`, and an action-severity excursion entering the open set raises
        the room to `ACTION`."

        Design: Difficulty/non_linear_state_machine/cleanroom_parallel_dimensions_move_independently
        """
        room = setup_certified_room(
            room_code="CR-E", iso_class="ISO_8",
            particle_alert_limit=3500000, particle_action_limit=3520000,
            viable_alert_limit=100, viable_action_limit=200)
        point = add_sampling_point(room["id"], point_code="SP-E", metric="VIABLE")
        _sample, excursion_id = record_excursion_sample(
            point["id"], 150, sampled_at="2026-08-01T11:00:00Z",
            tech_user_id="tech-e")

        close_excursion(excursion_id,
                        root_cause="Investigation narrative for CR-E alert",
                        investigator_id="qa-e1", approver_id="qa-e2")
        room_end = get_success_data(api.get_room(room["id"], QA))
        assert room_end["environment_posture"] == "IN_CONTROL"
        assert room_end["certification_status"] == "CERTIFIED"
        assert get_success_data(api.get_excursion(excursion_id, QA))["status"] == "CLOSED"
