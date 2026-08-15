"""Quarantine protocol timing, release gating, re-entry, and stall zoning."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    assert_quarantine_protocol, assert_same_instant,
    daily_health_log_payload, appointment_payload, create_intake_evaluation_payload,
    complete_evaluation_payload, stall_payload, stall_assignment_payload,
    make_veterinarian_headers, make_farrier_headers,
    intake_horse, get_horse, complete_medical_pass, protocols_for,
    active_protocol_for, clear_active_protocol, release_horse, set_clock,
    register_vet, register_farrier, create_stall,
)

INTAKE = TEST_USERS["intake_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _setup_horse_with_cleared_path(horse_overrides=None, vet_id=None,
                                   eval_at="2026-08-14T12:00:00Z"):
    """Intake + MEDICAL PASS eval; protocol left ACTIVE, clock moved onward."""
    if vet_id is None:
        vet_id = register_vet()
    horse = intake_horse(**(horse_overrides or {}))
    complete_medical_pass(horse["id"], at=eval_at)
    return horse, vet_id


class TestReleaseGatedByProtocolCleared:
    def test_release_rejected_while_protocol_active(self):
        """PRD §3.1: "Releasing to `REHABILITATION` requires the horse still in
        `QUARANTINE` (`ERR_INVALID_STATE`) and its active protocol already
        `CLEARED` (`ERR_QUARANTINE_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/release_gated_by_protocol_cleared
        """
        horse, _vet = _setup_horse_with_cleared_path()
        set_clock("2026-08-15T00:00:00Z")
        resp = api_client.release_quarantine(
            horse["id"], {"target_status": "ADOPTABLE"}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_QUARANTINE_ACTIVE, 409)
        assert get_horse(horse["id"])["status"] == "QUARANTINE"

    def test_release_succeeds_after_protocol_cleared(self):
        """PRD §3.1: "Releasing to `ADOPTABLE` adds two further gates: a
        `COMPLETED` `MEDICAL` evaluation with outcome `PASS` must exist
        (`ERR_INVALID_STATE`), and when `bonded_companion_id` is set, the companion
        horse must currently be `ADOPTABLE` or `ADOPTION_PENDING`
        (`ERR_BONDED_PAIR_VIOLATION`); an adoptable release moves the horse to
        `MAIN_PASTURE` with the same version increment."

        Design: Difficulty/cross_entity_state_dependency/release_gated_by_protocol_cleared
        """
        horse, vet_id = _setup_horse_with_cleared_path()
        clear_active_protocol(horse["id"], vet_id)
        released = release_horse(horse["id"], "ADOPTABLE")
        assert released["status"] == "ADOPTABLE"
        assert released["current_location"] == "MAIN_PASTURE"


class TestClearanceBoundaryPrecision:
    def test_clear_at_exactly_48h_exam_age_succeeds(self):
        """PRD §3.1: "Second, the horse must have a `COMPLETED` `MEDICAL` intake
        evaluation whose `evaluation_date` falls within 48 hours of now — an exam
        exactly 48 hours old still counts — else `ERR_CLEARANCE_EXAM_STALE`."
        PRD §3.1: "First, the logical now must have reached the protocol's
        `start_date` plus `min_days` plus `extension_days` days — arrival exactly
        at that instant is allowed — else `ERR_RELEASE_DATE_NOT_REACHED`."

        Design: Difficulty/boundary_precision_check/quarantine_clearance_exam_exactly_48h
        """
        vet_id = register_vet()
        horse = intake_horse(body_condition_score=5)
        complete_medical_pass(horse["id"], at="2026-08-13T00:00:00Z")
        # Exam age exactly 48h; quarantine age exactly 14 days at the boundary.
        proto = clear_active_protocol(horse["id"], vet_id,
                                      at="2026-08-15T00:00:00Z")
        assert proto["status"] == "CLEARED"

    def test_clear_stamps_cleared_at_boundary_instant(self):
        """PRD §3.1: "A successful clearance moves the protocol from `ACTIVE` to
        `CLEARED` and stamps `cleared_at`."
        PRD §2.4: "Every piece of date arithmetic in this document — quarantine
        duration windows, cooling-off periods, document validity windows, refund
        windows, seasonal multipliers, "within N days" freshness checks —
        evaluates against this logical clock."

        Design: Difficulty/boundary_precision_check/quarantine_clearance_exam_exactly_48h
        """
        vet_id = register_vet()
        horse = intake_horse(body_condition_score=5)
        complete_medical_pass(horse["id"], at="2026-08-13T00:00:00Z")
        clear_active_protocol(horse["id"], vet_id, at="2026-08-15T00:00:00Z")
        cleared = [p for p in protocols_for(horse["id"]) if p["status"] == "CLEARED"]
        assert len(cleared) == 1
        assert_quarantine_protocol(cleared[0])
        assert_same_instant(cleared[0]["cleared_at"], "2026-08-15T00:00:00Z")


class TestQuarantineReentryCycle:
    def _setup_adoptable_with_farrier_appointment(self):
        vet_id = register_vet()
        farrier_id = register_farrier()
        horse = intake_horse(name="H", sex="GELDING", age_years=9,
                             body_condition_score=5)
        complete_medical_pass(horse["id"])
        clear_active_protocol(horse["id"], vet_id)
        release_horse(horse["id"], "ADOPTABLE")
        appt = get_success_data(api_client.create_care_service_appointment(
            appointment_payload(
                horse["id"], farrier_id, service_type="FARRIER_TRIM",
                scheduled_start="2026-08-16T09:00:00Z",
                scheduled_end="2026-08-16T09:45:00Z"),
            INTAKE))
        return horse, vet_id, appt

    def test_requarantine_cancels_open_appointments(self):
        """PRD §3.1: "Re-quarantine — again an `IntakeCoordinator` act, taking
        `min_days` and a free-text `reason` such as `EXPOSURE` — applies to a
        horse in `REHABILITATION`, `ADOPTABLE`, or `SANCTUARY` (`ERR_INVALID_STATE`
        from any other posture), is refused while another protocol is still
        `ACTIVE` (`ERR_QUARANTINE_ACTIVE`), creates a fresh `ACTIVE` protocol from
        the supplied values with `start_date` at now, returns the horse to
        `QUARANTINE` in the `QUARANTINE_STALL`, cancels every one of the horse's
        appointments still in `REQUESTED` or `CONFIRMED` with `cancellation_reason`
        recorded as `QUARANTINE_REENTRY`, and increments the horse's `version`."

        Design: Difficulty/non_linear_state_machine/horse_quarantine_reentry_cycle
        """
        horse, _vet_id, appt = self._setup_adoptable_with_farrier_appointment()
        proto2 = validate_success(api_client.requarantine_horse(
            horse["id"], {"min_days": 7, "reason": "EXPOSURE"}, INTAKE), 201)
        assert proto2["status"] == "ACTIVE"
        assert proto2["min_days"] == 7
        assert proto2["reason"] == "EXPOSURE"

        cancelled = validate_success(
            api_client.get_care_service_appointment(appt["id"], INTAKE))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "QUARANTINE_REENTRY"
        assert get_horse(horse["id"])["status"] == "QUARANTINE"
        assert get_horse(horse["id"])["current_location"] == "QUARANTINE_STALL"

    def test_horse_completes_adoptable_quarantine_adoptable_loop(self):
        """PRD §3.1: "Releasing to `ADOPTABLE` adds two further gates: a
        `COMPLETED` `MEDICAL` evaluation with outcome `PASS` must exist
        (`ERR_INVALID_STATE`), and when `bonded_companion_id` is set, the companion
        horse must currently be `ADOPTABLE` or `ADOPTION_PENDING`
        (`ERR_BONDED_PAIR_VIOLATION`); an adoptable release moves the horse to
        `MAIN_PASTURE` with the same version increment."
        PRD §3.1: "A horse carries at most one `ACTIVE` protocol at any moment."

        Design: Difficulty/non_linear_state_machine/horse_quarantine_reentry_cycle
        """
        horse, vet_id, _appt = self._setup_adoptable_with_farrier_appointment()
        first_protocols = protocols_for(horse["id"])
        assert len(first_protocols) == 1
        assert first_protocols[0]["status"] == "CLEARED"

        proto2 = validate_success(api_client.requarantine_horse(
            horse["id"], {"min_days": 7, "reason": "EXPOSURE"}, INTAKE), 201)
        # Second episode: eval at 08-20, release eligible 08-22 (start 08-15 + 7).
        complete_medical_pass(horse["id"], at="2026-08-20T12:00:00Z")
        cleared2 = clear_active_protocol(horse["id"], vet_id,
                                         at="2026-08-22T00:00:00Z")
        assert cleared2["id"] == proto2["id"]
        released = release_horse(horse["id"], "ADOPTABLE")
        assert released["status"] == "ADOPTABLE"

        all_protocols = protocols_for(horse["id"])
        assert len(all_protocols) == 2, "two distinct quarantine episodes"
        assert all(p["status"] == "CLEARED" for p in all_protocols)


class TestEvaluationAndExtensionEdges:
    def test_eval_double_complete_returns_invalid_state(self):
        """PRD §2.8: "The same lockdown logic applies to the terminal states of
        the other state machines — a `COMPLETED` or `CANCELLED` appointment, home
        check, or follow-up visit; a `COMPLETED` evaluation; a `CLEARED` protocol;
        an `ENDED` stall assignment; a `FINALIZED`, `RETURN_COMPLETED`,
        `REJECTED`, or `WITHDRAWN` application; a `COMPLETED` or `SUPERSEDED`
        rehabilitation plan; a `SUPERSEDED` or `CLOSED` care plan; a `COMPLETED`
        or `CANCELLED` sponsorship; a `RECEIVED` purchase order; a `COMPLETED` or
        `NO_SHOW` shift; an `EXECUTED` or `OVERRIDDEN` euthanasia case — none
        accepts further transitions, and attempts fail with `ERR_INVALID_STATE`."
        PRD §3.1: "separately, completing a `MEDICAL` intake evaluation with an
        outcome of `FAIL` on a horse with an `ACTIVE` protocol adds the same 7-day
        extension."

        Design: Corner/state_machines/eval_double_complete_returns_invalid_state
        """
        horse = intake_horse()
        ev = get_success_data(api_client.create_intake_evaluation(
            create_intake_evaluation_payload(
                horse["id"], evaluation_type="MEDICAL",
                scheduled_date="2026-08-02T00:00:00Z"), INTAKE))
        get_success_data(api_client.complete_intake_evaluation(
            ev["id"], complete_evaluation_payload(outcome="FAIL",
                                                  findings="strangles suspected"),
            INTAKE))
        proto = active_protocol_for(horse["id"])
        assert proto["extension_days"] == 7

        resp = api_client.complete_intake_evaluation(
            ev["id"], complete_evaluation_payload(outcome="PASS"), INTAKE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        proto_after = active_protocol_for(horse["id"])
        assert proto_after["extension_days"] == 7, (
            "the FAIL extension must fire exactly once")

    def test_quarantine_extensions_stack(self):
        """PRD §3.1: "A fever reading — `temp_f` at or above 103.0 — on a horse
        with an `ACTIVE` protocol automatically adds 7 days to that protocol's
        `extension_days`; separately, completing a `MEDICAL` intake evaluation
        with an outcome of `FAIL` on a horse with an `ACTIVE` protocol adds the
        same 7-day extension."

        Design: Corner/state_machines/quarantine_extensions_stack
        """
        horse = intake_horse()
        get_success_data(api_client.create_daily_health_log(
            daily_health_log_payload(horse["id"], temp_f=103.0, appetite="REDUCED"),
            INTAKE))
        ev = get_success_data(api_client.create_intake_evaluation(
            create_intake_evaluation_payload(
                horse["id"], evaluation_type="MEDICAL",
                scheduled_date="2026-08-02T00:00:00Z"), INTAKE))
        get_success_data(api_client.complete_intake_evaluation(
            ev["id"], complete_evaluation_payload(outcome="FAIL"), INTAKE))
        # 102.9F is below the >= 103.0 threshold and must contribute nothing.
        get_success_data(api_client.create_daily_health_log(
            daily_health_log_payload(horse["id"], temp_f=102.9, appetite="NORMAL"),
            INTAKE))
        proto = active_protocol_for(horse["id"])
        assert proto["extension_days"] == 14, "7 fever + 7 medical-fail; 102.9F adds 0"


class TestClearanceRejectionReasons:
    def test_release_date_not_reached(self):
        """PRD §3.1: "First, the logical now must have reached the protocol's
        `start_date` plus `min_days` plus `extension_days` days — arrival exactly
        at that instant is allowed — else `ERR_RELEASE_DATE_NOT_REACHED`."

        Design: Corner/errors/release_date_not_reached
        """
        vet_id = register_vet()
        horse = intake_horse()
        complete_medical_pass(horse["id"], at="2026-08-13T12:00:00Z")
        set_clock("2026-08-14T00:00:00Z")  # day 13 of a 14-day protocol
        proto = active_protocol_for(horse["id"])
        resp = api_client.clear_quarantine_protocol(
            proto["id"], make_veterinarian_headers(vet_id))
        validate_error(resp, ApiErrorId.ERR_RELEASE_DATE_NOT_REACHED, 422)

    def test_stale_clearance_exam_49h(self):
        """PRD §3.1: "Second, the horse must have a `COMPLETED` `MEDICAL` intake
        evaluation whose `evaluation_date` falls within 48 hours of now — an exam
        exactly 48 hours old still counts — else `ERR_CLEARANCE_EXAM_STALE`."

        Design: Corner/validations/stale_clearance_exam_49h
        """
        vet_id = register_vet()
        horse = intake_horse()
        complete_medical_pass(horse["id"], at="2026-08-12T23:00:00Z")
        set_clock("2026-08-15T00:00:00Z")  # release reached; exam 49h old
        proto = active_protocol_for(horse["id"])
        resp = api_client.clear_quarantine_protocol(
            proto["id"], make_veterinarian_headers(vet_id))
        validate_error(resp, ApiErrorId.ERR_CLEARANCE_EXAM_STALE, 422)

    def test_fever_within_72h_blocks_clear(self):
        """PRD §3.1: "Third, no daily health log with `temp_f` at or above 103.0
        may have been recorded strictly within the trailing 72 hours — a fever log
        exactly 72 hours old does not block clearance — else
        `ERR_FEVER_WITHIN_72H`."

        Design: Corner/validations/fever_within_72h_blocks_clear
        """
        vet_id = register_vet()
        horse = intake_horse()
        set_clock("2026-08-20T06:00:00Z")
        get_success_data(api_client.create_daily_health_log(
            daily_health_log_payload(horse["id"], temp_f=103.0, appetite="NONE"),
            INTAKE))
        proto = active_protocol_for(horse["id"])
        assert proto["extension_days"] == 7, "fever auto-extension must fire"
        complete_medical_pass(horse["id"], at="2026-08-20T12:00:00Z")
        # Release date = 08-01 + (14+7)d = 08-22 reached; exam 36h fresh; fever 42h old.
        set_clock("2026-08-22T00:00:00Z")
        resp = api_client.clear_quarantine_protocol(
            proto["id"], make_veterinarian_headers(vet_id))
        validate_error(resp, ApiErrorId.ERR_FEVER_WITHIN_72H, 422)


class TestBondedReleaseAndStallZoning:
    def test_bonded_pair_release_violation(self):
        """PRD §3.1: "Releasing to `ADOPTABLE` adds two further gates: a
        `COMPLETED` `MEDICAL` evaluation with outcome `PASS` must exist
        (`ERR_INVALID_STATE`), and when `bonded_companion_id` is set, the companion
        horse must currently be `ADOPTABLE` or `ADOPTION_PENDING`
        (`ERR_BONDED_PAIR_VIOLATION`)"

        Design: Corner/errors/bonded_pair_release_violation
        """
        vet_id = register_vet()
        h1 = intake_horse(name="H1")
        h2 = intake_horse(name="H2", sex="GELDING", estimated_weight_lbs=950,
                          age_years=7, body_condition_score=4,
                          bonded_companion_id=h1["id"])
        complete_medical_pass(h1["id"], at="2026-08-14T12:00:00Z")
        complete_medical_pass(h2["id"], at="2026-08-14T12:30:00Z")
        clear_active_protocol(h1["id"], vet_id)
        clear_active_protocol(h2["id"], vet_id)
        release_horse(h1["id"], "REHABILITATION")

        resp = api_client.release_quarantine(
            h2["id"], {"target_status": "ADOPTABLE"}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_BONDED_PAIR_VIOLATION, 422)
        assert get_horse(h2["id"])["status"] == "QUARANTINE"

    def test_stall_zone_mismatch_rejected(self):
        """PRD §3.1: "Zone and posture must also agree: a `QUARANTINE` horse may
        be assigned only into `QUARANTINE_BARN` stalls, and any other pairing
        fails with `ERR_STALL_ZONE_MISMATCH`."

        Design: Corner/validations/stall_zone_mismatch_rejected
        """
        sm = create_stall(stall_code="M-01", barn_zone="MAIN_BARN")
        sq = create_stall(stall_code="Q-01", barn_zone="QUARANTINE_BARN")
        horse = intake_horse()

        resp = api_client.create_stall_assignment(
            stall_assignment_payload(horse["id"], sm["id"],
                                     start_date="2026-08-01T00:00:00Z"),
            INTAKE)
        validate_error(resp, ApiErrorId.ERR_STALL_ZONE_MISMATCH, 422)

        ok = validate_success(api_client.create_stall_assignment(
            stall_assignment_payload(horse["id"], sq["id"],
                                     start_date="2026-08-01T00:00:00Z"),
            INTAKE), 201)
        assert ok["status"] == "ACTIVE"
