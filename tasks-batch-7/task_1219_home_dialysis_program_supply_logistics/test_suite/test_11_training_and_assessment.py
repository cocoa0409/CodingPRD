"""Corner coverage: training attempt lifecycle battery, work-order invalid
transitions, and the assessment review battery."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_program, create_patient,
    api_client, make_admin_headers, make_nurse_headers, make_biomed_headers,
    create_training_attempt_payload, create_home_assessment_payload,
    create_work_order_payload,
)


class TestTrainingAttemptLifecycleBattery:
    """Score boundary 79/80; failing attempts, SoD, repeat sign-off, and an
    unknown module are all rejected."""

    def test_score_boundary_and_failing_signoff(self, api):
        """PRD §3.2: "The server stamps the attempt with the caller's
        identifier as `trainer_user_id`, computes `is_passing` — a score of at
        least 80 passes — and starts the attempt in `RECORDED`."
        PRD §3.2: "The attempt must currently be `RECORDED`
        (`ERR_ATTEMPT_NOT_RECORDED`), it must be passing
        (`ERR_ATTEMPT_NOT_PASSING`), and the signing nurse's `X-User-ID` must
        differ from `trainer_user_id` (`ERR_SOD_SIGNOFF_BY_TRAINER`, per
        §2.11)."

        Design: Corner/state_machines/training_attempt_lifecycle_battery
        """
        program = create_program()
        patient = create_patient(program["id"])
        failing = validate_success(api.create_training_attempt(
            create_training_attempt_payload(patient["id"], "WATER_HANDLING",
                                            score_pct=79),
            make_nurse_headers("nurse-1")), 201)
        assert failing["is_passing"] is False
        resp = api.sign_off_attempt(failing["id"], make_nurse_headers("nurse-2"))
        validate_error(resp, ApiErrorId.ERR_ATTEMPT_NOT_PASSING)
        passing = validate_success(api.create_training_attempt(
            create_training_attempt_payload(patient["id"], "WATER_HANDLING",
                                            score_pct=80),
            make_nurse_headers("nurse-1")), 201)
        assert passing["is_passing"] is True, "boundary is >= 80"

    def test_sod_and_terminal_lockdown_and_unknown_module(self, api):
        """PRD §2.11: "A HomeNurse who records a training attempt may not sign
        it off: sign-off by the attempt's own `trainer_user_id` is rejected
        with `ERR_SOD_SIGNOFF_BY_TRAINER` (HTTP 403)."
        PRD §3.2: "A successful sign-off stamps `signed_off_by_user_id` with
        the signer and `signed_off_at` with the current logical clock, moves
        the attempt to `SIGNED_OFF` (terminal), clears the patient's
        `retraining_required` latch if it was set — any passing sign-off clears
        it, regardless of module — and recomputes posture."

        Design: Corner/state_machines/training_attempt_lifecycle_battery
        """
        program = create_program()
        patient = create_patient(program["id"])
        att = validate_success(api.create_training_attempt(
            create_training_attempt_payload(patient["id"], "WATER_HANDLING",
                                            score_pct=80),
            make_nurse_headers("nurse-1")), 201)
        # Sign-off by the trainer: segregation of duties.
        resp = api.sign_off_attempt(att["id"], make_nurse_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_SIGNOFF_BY_TRAINER)
        signed = validate_success(api.sign_off_attempt(
            att["id"], make_nurse_headers("nurse-2")))
        assert signed["status"] == "SIGNED_OFF"
        assert signed["signed_off_by_user_id"] == "nurse-2"
        # Terminal lockdown: a second sign-off is an invalid transition.
        resp = api.sign_off_attempt(att["id"], make_nurse_headers("nurse-2"))
        validate_error(resp, ApiErrorId.ERR_ATTEMPT_NOT_RECORDED)
        # Unknown module enum is a 400.
        resp = api.create_training_attempt(
            create_training_attempt_payload(patient["id"], "WATER_SAFETY",
                                            score_pct=90),
            make_nurse_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestWorkOrderInvalidTransitionsProbe:
    """complete from REQUESTED and approve from CANCELLED are rejected."""

    def _setup_work_order(self, api):
        program = create_program()
        patient = create_patient(program["id"])
        asmt = validate_success(api.create_home_assessment(
            create_home_assessment_payload(patient["id"],
                                           water_chloramine_ppm=0.2),
            make_nurse_headers("nurse-1")), 201)
        validate_success(api.require_remediation(asmt["id"],
                                                 make_nurse_headers("nurse-2")))
        wo = validate_success(api.create_work_order(
            create_work_order_payload(patient["id"], asmt["id"],
                                      work_type="ELECTRICAL",
                                      cost_estimate_cents=180000),
            make_nurse_headers("nurse-1")), 201)
        return wo

    def test_complete_from_requested_rejected(self, api):
        """PRD §3.3: "`INSPECTED_PASS` and `CANCELLED` are terminal. Any
        approve, complete, inspect, or cancel attempted from a state without
        that transition is `ERR_WORK_ORDER_INVALID_STATE`."

        Design: Corner/state_machines/work_order_invalid_transitions_probe
        """
        wo = self._setup_work_order(api)
        resp = api.complete_work_order(wo["id"], {"final_cost_cents": 180000},
                                       make_biomed_headers("biomed-1"))
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_INVALID_STATE)

    def test_cancel_then_approve_terminal_lockdown(self, api):
        """PRD §3.3: "Cancellation by a `HomeNurse` or `ProgramAdmin` is
        allowed from `REQUESTED` or `SCHEDULED` and lands in `CANCELLED`.
        `INSPECTED_PASS` and `CANCELLED` are terminal. Any approve, complete,
        inspect, or cancel attempted from a state without that transition is
        `ERR_WORK_ORDER_INVALID_STATE`."

        Design: Corner/state_machines/work_order_invalid_transitions_probe
        """
        wo = self._setup_work_order(api)
        cancelled = validate_success(api.cancel_work_order(
            wo["id"], make_nurse_headers("nurse-1")))
        assert cancelled["status"] == "CANCELLED"
        resp = api.approve_work_order(
            wo["id"], {"scheduled_window_start": "2026-05-05T08:00:00Z",
                       "scheduled_window_end": "2026-05-05T16:00:00Z"},
            make_admin_headers("admin-1"))
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_INVALID_STATE)


class TestAssessmentReviewBattery:
    """Chloramine boundary, FAIL accept rejection, work-order gate on resubmit,
    double-resubmit rejection, and the SoD refresh on resubmission."""

    def _program_patient(self, api):
        program = create_program()
        patient = create_patient(program["id"])
        return patient["id"]

    def test_chloramine_boundary_and_fail_accept(self, api):
        """PRD §3.3: "The second is `result`, which is `PASS` only when all
        four conditions hold — chloramine at most 0.1 ppm compared at full
        precision so that exactly 0.1 passes, a dedicated electrical circuit
        present, voltage verified, and at least 25 square feet of certified
        storage — and `FAIL` otherwise."
        PRD §3.3: "The assessment must be `SUBMITTED`
        (`ERR_ASSESSMENT_INVALID_STATE`), its computed `result` must be `PASS`
        (`ERR_ASSESSMENT_RESULT_FAIL`), and the caller must not be the
        `assessed_by_user_id` (`ERR_SOD_ASSESSOR_SELF_ACCEPT`)."

        Design: Corner/state_machines/assessment_review_battery
        """
        pat = self._program_patient(api)
        a_pass = validate_success(api.create_home_assessment(
            create_home_assessment_payload(pat, water_chloramine_ppm=0.1,
                                           storage_area_sqft=30),
            make_nurse_headers("nurse-1")), 201)
        assert a_pass["result"] == "PASS", "exactly 0.1 ppm passes (<=)"
        a_fail = validate_success(api.create_home_assessment(
            create_home_assessment_payload(pat, water_chloramine_ppm=0.11,
                                           storage_area_sqft=30),
            make_nurse_headers("nurse-1")), 201)
        assert a_fail["result"] == "FAIL"
        resp = api.accept_assessment(a_fail["id"], make_nurse_headers("nurse-2"))
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_RESULT_FAIL)

    def test_resubmit_gate_and_assessor_refresh(self, api):
        """PRD §3.3: "It is permitted only when every work order linked to the
        assessment is settled — `INSPECTED_PASS` or `CANCELLED`; anything still
        outstanding is rejected with `ERR_WORK_ORDERS_OUTSTANDING`."
        PRD §3.3: "Resubmission replaces the measurement fields, recomputes
        `result` and `storage_cap_units`, and refreshes `assessed_by_user_id`
        to the resubmitting nurse, which means the next acceptance must again
        come from a different nurse."

        Design: Corner/state_machines/assessment_review_battery
        """
        pat = self._program_patient(api)
        asmt = validate_success(api.create_home_assessment(
            create_home_assessment_payload(pat, water_chloramine_ppm=0.11,
                                           storage_area_sqft=30),
            make_nurse_headers("nurse-1")), 201)
        validate_success(api.require_remediation(asmt["id"],
                                                 make_nurse_headers("nurse-2")))
        wo = validate_success(api.create_work_order(
            create_work_order_payload(pat, asmt["id"],
                                      cost_estimate_cents=90000),
            make_nurse_headers("nurse-1")), 201)
        # Outstanding work order blocks resubmission.
        resp = api.resubmit_assessment(
            asmt["id"],
            {"water_chloramine_ppm": 0.05, "electrical_dedicated_circuit": True,
             "electrical_voltage_verified": True, "storage_area_sqft": 30},
            make_nurse_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_WORK_ORDERS_OUTSTANDING)
        validate_success(api.cancel_work_order(wo["id"],
                                               make_admin_headers("admin-1")))
        resub = validate_success(api.resubmit_assessment(
            asmt["id"],
            {"water_chloramine_ppm": 0.05, "electrical_dedicated_circuit": True,
             "electrical_voltage_verified": True, "storage_area_sqft": 30},
            make_nurse_headers("nurse-1")))
        assert resub["status"] == "SUBMITTED"
        assert resub["result"] == "PASS"
        # Double resubmit from SUBMITTED is an invalid transition.
        resp = api.resubmit_assessment(
            asmt["id"],
            {"water_chloramine_ppm": 0.05, "electrical_dedicated_circuit": True,
             "electrical_voltage_verified": True, "storage_area_sqft": 30},
            make_nurse_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_INVALID_STATE)
        # The resubmitter refreshed the assessor, so nurse-1 cannot accept.
        resp = api.accept_assessment(asmt["id"], make_nurse_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_ASSESSOR_SELF_ACCEPT)
        accepted = validate_success(api.accept_assessment(
            asmt["id"], make_nurse_headers("nurse-2")))
        assert accepted["status"] == "ACCEPTED"
