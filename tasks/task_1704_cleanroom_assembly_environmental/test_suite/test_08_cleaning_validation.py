"""Cleaning validation programs and cycles: defaults, the consecutive-pass
counter, FAIL/reject resets, the one-live-program guard, and verifier
segregation."""
from test_helpers import (
    ENV_TECH,
    QA,
    ApiErrorId,
    assert_cleaning_cycle,
    assert_cleaning_program,
    create_cleaning_cycle_payload,
    create_cleaning_program,
    create_room,
    get_success_data,
    make_environment_tech_headers,
    make_qa_headers,
    record_cycle,
    setup_validated_cleaning_program,
    validate_error,
    validate_success,
    verify_cycle,
)


class TestProgramDefaults:
    def test_cleaning_program_applies_default_required_passes(self, api):
        """PRD §3.7: "QA creates a cleaning validation program for a room by
        supplying the `cleanroom_id`, a `method_code` identifying the cleaning
        method, and optionally `required_consecutive_passes`, which defaults to
        3 when omitted. The program starts `DRAFT` with
        `consecutive_pass_count` 0."

        Design: Corner/entities/cleaning_program_default_required_consecutive_passes
        """
        room = create_room(room_code="CR-E5", iso_class="ISO_8",
                           particle_alert_limit=3500000,
                           particle_action_limit=3520000,
                           viable_alert_limit=100, viable_action_limit=200)
        resp = api.create_cleaning_program(
            {"cleanroom_id": room["id"], "method_code": "MOP-D"}, QA)
        program = validate_success(resp, 201)
        assert_cleaning_program(program)
        assert program["required_consecutive_passes"] == 3, (
            "the default of 3 applies when the field is omitted")
        assert program["status"] == "DRAFT"
        assert program["consecutive_pass_count"] == 0


class TestConsecutivePassBoundary:
    def test_program_validates_at_exactly_required_passes(self, api):
        """PRD §3.7: "verification stamps `verified_by_user_id`, moves the
        cycle to terminal `VERIFIED`, and increments the program's
        `consecutive_pass_count` by one. When the count reaches
        `required_consecutive_passes` — the boundary is inclusive, so reaching
        the required number exactly is sufficient — the program moves
        automatically to `VALIDATED`, whether it stood `ACTIVE` or
        `RE_VALIDATION_REQUIRED`."

        Design: Corner/calculations/pass_count_reaches_exactly_required_validates
        """
        room = create_room(room_code="CR-C4", iso_class="ISO_8",
                           particle_alert_limit=3500000,
                           particle_action_limit=3520000,
                           viable_alert_limit=100, viable_action_limit=200)
        program = create_cleaning_program(room["id"], method_code="MOP-C4",
                                          required_consecutive_passes=2)
        get_success_data(api.activate_cleaning_program(program["id"], QA))

        cycle1 = record_cycle(program["id"], result="PASS")
        verify_cycle(cycle1["id"])
        program = get_success_data(api.get_cleaning_program(program["id"], QA))
        assert program["consecutive_pass_count"] == 1
        assert program["status"] == "ACTIVE", "1 < 2: not yet VALIDATED"

        cycle2 = record_cycle(program["id"], result="PASS")
        verify_cycle(cycle2["id"])
        program = get_success_data(api.get_cleaning_program(program["id"], QA))
        assert program["consecutive_pass_count"] == 2
        assert program["status"] == "VALIDATED", (
            "reaching the required count exactly is sufficient (boundary >=)")


class TestFailCycleCascade:
    def _validated_program(self, api):
        room = create_room(room_code="CR-H", iso_class="ISO_8",
                           particle_alert_limit=3500000,
                           particle_action_limit=3520000,
                           viable_alert_limit=100, viable_action_limit=200)
        program = setup_validated_cleaning_program(
            room["id"], required_consecutive_passes=2, method_code="MOP-8")
        assert program["status"] == "VALIDATED"
        assert program["consecutive_pass_count"] == 2
        return program

    def test_fail_cycle_recorded_rejected_and_resets_counter(self, api):
        """PRD §3.7: "A cycle recorded with `result` `FAIL` never waits for
        review: it is stored directly as `REJECTED`, the program's
        `consecutive_pass_count` resets to 0, and a program that stood
        `VALIDATED` drops to `RE_VALIDATION_REQUIRED`."

        Design: Difficulty/transitive_cascade/failed_cleaning_cycle_cascades_program_revalidation
        """
        program = self._validated_program(api)
        resp = api.create_cleaning_cycle(
            program["id"], create_cleaning_cycle_payload(result="FAIL"), ENV_TECH)
        cycle = validate_success(resp, 201)
        assert_cleaning_cycle(cycle)
        assert cycle["status"] == "REJECTED", (
            "a FAIL result is recorded directly as REJECTED")

        program = get_success_data(api.get_cleaning_program(program["id"], QA))
        assert program["consecutive_pass_count"] == 0, "the counter resets"

    def test_fail_cycle_drops_validated_program_to_revalidation(self, api):
        """PRD §3.7: "A cycle recorded with `result` `FAIL` never waits for
        review: it is stored directly as `REJECTED`, the program's
        `consecutive_pass_count` resets to 0, and a program that stood
        `VALIDATED` drops to `RE_VALIDATION_REQUIRED`."

        Design: Difficulty/transitive_cascade/failed_cleaning_cycle_cascades_program_revalidation
        """
        program = self._validated_program(api)
        record_cycle(program["id"], result="FAIL")

        program = get_success_data(api.get_cleaning_program(program["id"], QA))
        assert program["status"] == "RE_VALIDATION_REQUIRED", (
            "a VALIDATED program drops out of VALIDATED on the failed cycle")
        assert program["consecutive_pass_count"] == 0


class TestPassCountConservation:
    def test_verify_reject_sequence_conserves_pass_count(self, api):
        """PRD §3.7: "Verification requires the cycle to stand `RECORDED`
        (`ERR_CYCLE_NOT_RECORDED`), a `result` of `PASS`
        (`ERR_CYCLE_RESULT_FAIL`), and a verifier whose `X-User-ID` differs
        from the cycle's `performed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`);
        verification stamps `verified_by_user_id`, moves the cycle to terminal
        `VERIFIED`, and increments the program's `consecutive_pass_count` by
        one."
        PRD §3.7: "QA may instead reject a recorded cycle (again
        `ERR_CYCLE_NOT_RECORDED` when the cycle is not `RECORDED`), moving it
        to terminal `REJECTED`, resetting `consecutive_pass_count` to 0, and
        forcing a `VALIDATED` program back to `RE_VALIDATION_REQUIRED`, from
        which it must re-accumulate the full run of consecutive verified passes
        to reach `VALIDATED` again."

        Design: Difficulty/compensating_invariant/cleaning_cycle_verify_reject_conserves_pass_count_derivation
        """
        room = create_room(room_code="CR-Q", iso_class="ISO_8",
                           particle_alert_limit=3500000,
                           particle_action_limit=3520000,
                           viable_alert_limit=100, viable_action_limit=200)
        program = create_cleaning_program(room["id"], method_code="MOP-17",
                                          required_consecutive_passes=3)
        get_success_data(api.activate_cleaning_program(program["id"], QA))

        verify_cycle(record_cycle(program["id"])["id"])                      # 1
        get_success_data(api.reject_cleaning_cycle(
            record_cycle(program["id"])["id"], QA))                          # reset 0
        verify_cycle(record_cycle(program["id"])["id"])                      # 1
        verify_cycle(record_cycle(program["id"])["id"])                      # 2

        program = get_success_data(api.get_cleaning_program(program["id"], QA))
        assert program["consecutive_pass_count"] == 2, (
            "verify (+1), reject (reset), verify, verify replays to exactly 2")
        assert program["status"] == "ACTIVE", "2 < required 3: not yet VALIDATED"

    def test_cycle_terminal_states_after_mixed_verdicts(self, api):
        """PRD §3.7: "verification stamps `verified_by_user_id`, moves the
        cycle to terminal `VERIFIED`, and increments the program's
        `consecutive_pass_count` by one."
        PRD §3.7: "QA may instead reject a recorded cycle (again
        `ERR_CYCLE_NOT_RECORDED` when the cycle is not `RECORDED`), moving it
        to terminal `REJECTED`, resetting `consecutive_pass_count` to 0".

        Design: Difficulty/compensating_invariant/cleaning_cycle_verify_reject_conserves_pass_count_derivation
        """
        room = create_room(room_code="CR-Q", iso_class="ISO_8",
                           particle_alert_limit=3500000,
                           particle_action_limit=3520000,
                           viable_alert_limit=100, viable_action_limit=200)
        program = create_cleaning_program(room["id"], method_code="MOP-17",
                                          required_consecutive_passes=3)
        get_success_data(api.activate_cleaning_program(program["id"], QA))

        cyc1 = record_cycle(program["id"])
        verify_cycle(cyc1["id"])
        cyc2 = record_cycle(program["id"])
        get_success_data(api.reject_cleaning_cycle(cyc2["id"], QA))
        cyc3 = record_cycle(program["id"])
        verify_cycle(cyc3["id"])
        cyc4 = record_cycle(program["id"])
        verify_cycle(cyc4["id"])

        for cycle_id in (cyc1["id"], cyc3["id"], cyc4["id"]):
            cycle = get_success_data(api.get_cleaning_cycle(cycle_id, QA))
            assert cycle["status"] == "VERIFIED"
            assert cycle["verified_by_user_id"] is not None
        assert get_success_data(
            api.get_cleaning_cycle(cyc2["id"], QA))["status"] == "REJECTED"
        program = get_success_data(api.get_cleaning_program(program["id"], QA))
        assert program["consecutive_pass_count"] == 2


class TestOneLiveProgramPerRoom:
    def test_second_program_activation_blocked_while_validated(self, api):
        """PRD §3.7: "Activation moves the program from `DRAFT` to `ACTIVE`
        and is refused with `ERR_PROGRAM_ALREADY_ACTIVE` when another program
        for the same room already stands `ACTIVE` or `VALIDATED` — one room
        carries at most one live program."

        Design: Difficulty/resource_temporal_overlap/single_active_cleaning_program_per_room
        """
        room = create_room(room_code="CR-P", iso_class="ISO_8",
                           particle_alert_limit=3500000,
                           particle_action_limit=3520000,
                           viable_alert_limit=100, viable_action_limit=200)
        first = setup_validated_cleaning_program(
            room["id"], required_consecutive_passes=1, method_code="MOP-16A")
        assert first["status"] == "VALIDATED"
        second = create_cleaning_program(room["id"], method_code="MOP-16B",
                                         required_consecutive_passes=1)

        resp = api.activate_cleaning_program(second["id"], QA)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_ALREADY_ACTIVE)
        assert get_success_data(
            api.get_cleaning_program(second["id"], QA))["status"] == "DRAFT"

    def test_second_program_activation_blocked_while_active(self, api):
        """PRD §3.7: "Activation moves the program from `DRAFT` to `ACTIVE`
        and is refused with `ERR_PROGRAM_ALREADY_ACTIVE` when another program
        for the same room already stands `ACTIVE` or `VALIDATED` — one room
        carries at most one live program."

        Design: Difficulty/resource_temporal_overlap/single_active_cleaning_program_per_room
        """
        room = create_room(room_code="CR-P", iso_class="ISO_8",
                           particle_alert_limit=3500000,
                           particle_action_limit=3520000,
                           viable_alert_limit=100, viable_action_limit=200)
        first = create_cleaning_program(room["id"], method_code="MOP-16A",
                                        required_consecutive_passes=2)
        get_success_data(api.activate_cleaning_program(first["id"], QA))
        second = create_cleaning_program(room["id"], method_code="MOP-16B",
                                         required_consecutive_passes=1)

        resp = api.activate_cleaning_program(second["id"], QA)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_ALREADY_ACTIVE)
        assert get_success_data(
            api.get_cleaning_program(second["id"], QA))["status"] == "DRAFT"


class TestCycleVerification:
    def test_double_verify_rejected(self, api):
        """PRD §3.7: "Verification requires the cycle to stand `RECORDED`
        (`ERR_CYCLE_NOT_RECORDED`), a `result` of `PASS`
        (`ERR_CYCLE_RESULT_FAIL`), and a verifier whose `X-User-ID` differs
        from the cycle's `performed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`)".

        Design: Corner/errors/error_cycle_not_recorded_on_double_verify
        """
        room = create_room(room_code="CR-ER2", iso_class="ISO_8",
                           particle_alert_limit=3500000,
                           particle_action_limit=3520000,
                           viable_alert_limit=100, viable_action_limit=200)
        program = create_cleaning_program(room["id"], method_code="MOP-ER2",
                                          required_consecutive_passes=3)
        get_success_data(api.activate_cleaning_program(program["id"], QA))
        cycle = record_cycle(program["id"], result="PASS")
        verify_cycle(cycle["id"])
        assert get_success_data(
            api.get_cleaning_cycle(cycle["id"], QA))["status"] == "VERIFIED"

        resp = api.verify_cleaning_cycle(cycle["id"], QA)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_RECORDED)

    def test_cycle_performer_cannot_verify_own_cycle(self, api):
        """PRD §2.8: "The technician who performed a cleaning cycle (anchored
        as its `performed_by_user_id`) may not verify that same cycle."
        PRD §3.7: "Verification requires the cycle to stand `RECORDED`
        (`ERR_CYCLE_NOT_RECORDED`), a `result` of `PASS`
        (`ERR_CYCLE_RESULT_FAIL`), and a verifier whose `X-User-ID` differs
        from the cycle's `performed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`);
        verification stamps `verified_by_user_id`, moves the cycle to terminal
        `VERIFIED`, and increments the program's `consecutive_pass_count` by
        one."

        Design: Corner/roles/segregation_of_duties_cycle_performer_cannot_verify_own
        """
        room = create_room(room_code="CR-RB5", iso_class="ISO_8",
                           particle_alert_limit=3500000,
                           particle_action_limit=3520000,
                           viable_alert_limit=100, viable_action_limit=200)
        program = create_cleaning_program(room["id"], method_code="MOP-RB5",
                                          required_consecutive_passes=3)
        get_success_data(api.activate_cleaning_program(program["id"], QA))
        cycle = record_cycle(program["id"], result="PASS",
                             tech_headers=make_environment_tech_headers("tech-rb5"))
        assert cycle["performed_by_user_id"] == "tech-rb5"

        # A QA-role caller carrying the performer's X-User-ID hits the
        # segregation check even though the role gate passes.
        resp = api.verify_cleaning_cycle(cycle["id"], make_qa_headers("tech-rb5"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        verified = validate_success(api.verify_cleaning_cycle(
            cycle["id"], make_qa_headers("qa-rb5")), 200)
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "qa-rb5"
