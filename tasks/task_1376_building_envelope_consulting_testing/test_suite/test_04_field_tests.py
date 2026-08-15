"""Field tests: pass/fail boundary, parallel diagnosis dimension, FAIL cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_anomaly,
    begin_field_test,
    create_active_engagement,
    create_assembly,
    create_completed_survey,
    create_design_review,
    create_field_test,
    create_anomaly,
    drive_diagnosis_complete,
    get_engagement,
    make_field_technician_headers,
    make_principal_headers,
    record_field_test_result,
    setup_approved_assembly,
    setup_field_test_recorded,
    start_review,
    validate_error,
    validate_paginated,
    validate_success,
)

P = TEST_USERS["principal_headers"]
C = TEST_USERS["consultant_headers"]


class TestFieldTestParallelDimensions:

    def test_fail_certify_blocked_until_diagnosed(self):
        """PRD §3.4: "when the `result` is `FAIL`, the `diagnosis_status` must
        have reached `DIAGNOSED`, otherwise `ERR_DIAGNOSIS_INCOMPLETE`
        (HTTP 409)."
        PRD §3.4: "A `FAIL` result sets off a cascade inside the same request.
        The test's `diagnosis_status` moves from `NOT_REQUIRED` to
        `UNDIAGNOSED`..."

        Design: Difficulty/non_linear_state_machine/field_test_parallel_dimensions
        """
        # allowable = 1.5 * (150/75) = 3.0; measured 3.0001 > 3.0 -> FAIL.
        eng, asm, ft = setup_field_test_recorded(
            measured=3.0001, name="E6", tag="W6",
            test_pressure_pa=150, required_airtightness_lps_m2=1.5,
            tech_user="tech-user-1")
        assert ft["result"] == "FAIL"
        assert ft["diagnosis_status"] == "UNDIAGNOSED"
        assert ft["execution_status"] == "RESULT_RECORDED"

        resp = api_client.certify_field_test(
            eng["id"], ft["id"], make_principal_headers("principal-user-1"))
        validate_error(resp, ApiErrorId.ERR_DIAGNOSIS_INCOMPLETE)
        after = validate_success(
            api_client.get_field_test(eng["id"], ft["id"], C), 200)
        assert after["execution_status"] == "RESULT_RECORDED"
        assert after["diagnosis_status"] == "UNDIAGNOSED"

    def test_pass_certifies_without_diagnosis(self):
        """PRD §3.4: "A passing test may therefore be certified without any
        diagnosis, while a failing test cannot leave the books until its
        failure has been explained."
        PRD §3.4: "Certification is the `Principal`'s act, moving
        `execution_status` from `RESULT_RECORDED` to `CERTIFIED` and stamping
        `certified_by` with the certifying principal's `X-User-ID`."

        Design: Difficulty/non_linear_state_machine/field_test_parallel_dimensions
        """
        # required 1.5 at 150 Pa -> allowable 3.0; measured 1.0 -> PASS.
        eng, asm, ft = setup_field_test_recorded(
            measured=1.0, name="E6B", tag="W6B",
            test_pressure_pa=150, required_airtightness_lps_m2=1.5,
            tech_user="tech-user-1")
        assert ft["result"] == "PASS"
        assert ft["diagnosis_status"] == "NOT_REQUIRED"

        resp = api_client.certify_field_test(
            eng["id"], ft["id"], make_principal_headers("principal-user-1"))
        data = validate_success(resp, 200)
        assert data["execution_status"] == "CERTIFIED"
        assert data["certified_by"] == "principal-user-1"
        assert data["diagnosis_status"] == "NOT_REQUIRED"


class TestFieldTestLeakageEqualityBoundary:

    def _setup_two_in_progress_tests(self):
        eng, asm = setup_approved_assembly(
            "E11", "W11", required_airtightness_lps_m2=1.5,
            assembly_type="WINDOW_WALL", design_u_factor=2.0)
        ft_pass = create_field_test(eng["id"], asm["id"],
                                    test_date="2026-09-10",
                                    test_pressure_pa=150)
        ft_fail = create_field_test(eng["id"], asm["id"],
                                    test_date="2026-09-11",
                                    test_pressure_pa=150)
        begin_field_test(eng["id"], ft_pass["id"], "tech-user-1")
        begin_field_test(eng["id"], ft_fail["id"], "tech-user-1")
        return eng, ft_pass, ft_fail

    def test_measured_equal_to_allowable_passes(self):
        """PRD §3.4: "the assembly's `required_airtightness_lps_m2` is scaled
        linearly by the ratio of the test's `test_pressure_pa` to the
        75-pascal reference pressure, and the measured leakage is compared
        against that allowable figure in exact decimal arithmetic with no
        rounding on either side. A measurement at most equal to the allowable —
        equality included — yields `PASS`; anything strictly greater yields
        `FAIL`."

        Design: Difficulty/boundary_precision_check/field_test_leakage_equality_passes
        """
        eng, ft_pass, _ = self._setup_two_in_progress_tests()
        # allowable = 1.5 * (150/75) = exactly 3.0; measured == 3.0.
        data = record_field_test_result(eng["id"], ft_pass["id"], 3.0,
                                        "tech-user-1")
        assert data["result"] == "PASS"
        assert data["diagnosis_status"] == "NOT_REQUIRED"
        assert data["execution_status"] == "RESULT_RECORDED"

    def test_measured_one_ten_thousandth_over_allowable_fails(self):
        """PRD §3.4: "A measurement at most equal to the allowable — equality
        included — yields `PASS`; anything strictly greater yields `FAIL`."
        PRD §2.6: "A field test whose computed result is a failure subtracts
        25."

        Design: Difficulty/boundary_precision_check/field_test_leakage_equality_passes
        """
        eng, _, ft_fail = self._setup_two_in_progress_tests()
        data = record_field_test_result(eng["id"], ft_fail["id"], 3.0001,
                                        "tech-user-1")
        assert data["result"] == "FAIL"
        assert data["diagnosis_status"] == "UNDIAGNOSED"
        assert get_engagement(eng["id"])["risk_score"] == 75


class TestFieldTestBeginRequiresAssemblyApproved:

    def test_begin_rejected_while_assembly_in_review(self):
        """PRD §3.4: "the tested assembly's `review_status` to be `APPROVED`;
        field-verifying an assembly whose design was never approved is rejected
        with `ERR_ASSEMBLY_NOT_APPROVED` (HTTP 409)."
        PRD §3.2: "The moment a round enters `UNDER_REVIEW`, the reviewed
        assembly's `review_status` moves to `IN_REVIEW`."

        Design: Difficulty/cross_entity_state_dependency/field_test_begin_requires_assembly_approved
        """
        eng = create_active_engagement(name="E13")
        asm = create_assembly(eng["id"], tag="W13",
                              required_airtightness_lps_m2=1.5)
        rev = create_design_review(eng["id"], asm["id"], barrier_scope=["AIR"],
                                   drawing_count=2)
        start_review(eng["id"], rev["id"], "rev-user-1")
        ft = create_field_test(eng["id"], asm["id"], test_method="ASTM_E1105",
                               test_pressure_pa=100)
        resp = api_client.begin_field_test(
            eng["id"], ft["id"], make_field_technician_headers("tech-user-1"))
        validate_error(resp, ApiErrorId.ERR_ASSEMBLY_NOT_APPROVED)
        after = validate_success(
            api_client.get_field_test(eng["id"], ft["id"], C), 200)
        assert after["execution_status"] == "SCHEDULED"

    def test_begin_rejected_when_assembly_never_reviewed(self):
        """PRD §3.4: "the tested assembly's `review_status` to be `APPROVED`;
        field-verifying an assembly whose design was never approved is rejected
        with `ERR_ASSEMBLY_NOT_APPROVED` (HTTP 409)."
        PRD §3.1: "its `review_status` begins at `NONE`, reflecting that no
        design review round has yet been started against it."

        Design: Difficulty/cross_entity_state_dependency/field_test_begin_requires_assembly_approved
        """
        eng = create_active_engagement(name="E13B")
        asm = create_assembly(eng["id"], tag="W13B",
                              required_airtightness_lps_m2=1.5)
        assert asm["review_status"] == "NONE"
        ft = create_field_test(eng["id"], asm["id"], test_method="ASTM_E1105",
                               test_pressure_pa=100)
        resp = api_client.begin_field_test(
            eng["id"], ft["id"], make_field_technician_headers("tech-user-1"))
        validate_error(resp, ApiErrorId.ERR_ASSEMBLY_NOT_APPROVED)
        after = validate_success(
            api_client.get_field_test(eng["id"], ft["id"], C), 200)
        assert after["execution_status"] == "SCHEDULED"


class TestFieldTestCertifyAndCascade:

    def test_field_test_certify_success_after_diagnosis(self):
        """PRD §3.4: "Certification enforces, in order: the posture must be
        other than `FROZEN` (`ERR_ENGAGEMENT_FROZEN`); the test must be in
        `RESULT_RECORDED` (`ERR_FIELD_TEST_NOT_ACTIONABLE`); segregation of
        duties must hold, meaning the certifier's `X-User-ID` must differ from
        the `performed_by` who recorded the result — a self-certified test is
        rejected with `ERR_DUTY_SEGREGATION_VIOLATION`; and when the `result`
        is `FAIL`, the `diagnosis_status` must have reached `DIAGNOSED`,
        otherwise `ERR_DIAGNOSIS_INCOMPLETE` (HTTP 409)."
        PRD §3.4: "Certification is the `Principal`'s act, moving
        `execution_status` from `RESULT_RECORDED` to `CERTIFIED` and stamping
        `certified_by` with the certifying principal's `X-User-ID`."

        Design: Corner/state_machines/field_test_certify_success_after_diagnosis
        """
        # allowable = 1.5 * (150/75) = 3.0; measured 3.5 -> FAIL.
        eng, asm, ft = setup_field_test_recorded(
            measured=3.5, name="EF", tag="AF",
            test_pressure_pa=150, required_airtightness_lps_m2=1.5,
            tech_user="tech-user-1")
        assert ft["result"] == "FAIL"
        drive_diagnosis_complete(eng["id"], ft["id"])
        resp = api_client.certify_field_test(
            eng["id"], ft["id"], make_principal_headers("principal-user-1"))
        data = validate_success(resp, 200)
        assert data["execution_status"] == "CERTIFIED"
        assert data["certified_by"] == "principal-user-1"

    def test_cascading_side_effects_fail_spawns_anomaly(self):
        """PRD §3.4: "A `FAIL` result sets off a cascade inside the same
        request. The test's `diagnosis_status` moves from `NOT_REQUIRED` to
        `UNDIAGNOSED`; the server automatically raises an Anomaly on the
        engagement with its `field_test_id` pointing at this test,
        `anomaly_type` `AIR_LEAKAGE`, `severity` `HIGH`, the description text
        "Auto-raised from failing field test", and status `OPEN`; the
        engagement's `risk_score` drops by 25, clamped at 0; and the engagement
        posture is re-derived — which, because an `OPEN` anomaly now exists,
        moves the posture to at least `RESTRICTED`."

        Design: Corner/cross_cutting_layers/cascading_side_effects_fail_spawns_anomaly
        """
        eng, asm = setup_approved_assembly(
            "ECS", "ACS", required_airtightness_lps_m2=1.5,
            assembly_type="WINDOW_WALL", design_u_factor=2.0)
        ft = create_field_test(eng["id"], asm["id"], test_pressure_pa=75)
        begin_field_test(eng["id"], ft["id"], "tech-user-1")
        data = record_field_test_result(eng["id"], ft["id"], 9.9, "tech-user-1")
        assert data["result"] == "FAIL"

        anomalies, meta = validate_paginated(api_client.list_anomalies(
            eng["id"], C, params={"field_test_id": ft["id"]}))
        assert len(anomalies) == 1
        auto = anomalies[0]
        assert_anomaly(auto)
        assert auto["field_test_id"] == ft["id"]
        assert auto["survey_id"] is None
        assert auto["anomaly_type"] == "AIR_LEAKAGE"
        assert auto["severity"] == "HIGH"
        assert auto["status"] == "OPEN"

        eng_after = get_engagement(eng["id"])
        assert eng_after["risk_score"] == 75
        assert eng_after["posture"] == "RESTRICTED"

    def test_filtered_list_by_foreign_key(self):
        """PRD §3.6: "Anomaly lists can be filtered by `field_test_id` or by
        `survey_id`, and the warranty claims filed against a given anomaly can
        be read back through the flat listing route for that anomaly."

        Design: Corner/endpoints/filtered_list_by_foreign_key
        """
        eng, asm = setup_approved_assembly(
            "EFL", "AFL", required_airtightness_lps_m2=1.5,
            assembly_type="WINDOW_WALL", design_u_factor=2.0)
        ft = create_field_test(eng["id"], asm["id"], test_pressure_pa=75)
        begin_field_test(eng["id"], ft["id"], "tech-user-1")
        record_field_test_result(eng["id"], ft["id"], 9.9, "tech-user-1")
        srv = create_completed_survey(eng["id"], asm["id"])
        create_anomaly(eng["id"], anomaly_type="MOISTURE_TRAP", severity="LOW",
                       description="survey one", survey_id=srv["id"])

        by_survey, meta = validate_paginated(api_client.list_anomalies(
            eng["id"], C, params={"survey_id": srv["id"]}))
        assert len(by_survey) == 1
        assert by_survey[0]["survey_id"] == srv["id"]
        assert by_survey[0]["field_test_id"] is None

        by_test, meta = validate_paginated(api_client.list_anomalies(
            eng["id"], C, params={"field_test_id": ft["id"]}))
        assert len(by_test) == 1
        assert by_test[0]["field_test_id"] == ft["id"]
        assert by_test[0]["anomaly_type"] == "AIR_LEAKAGE"
        assert by_test[0]["severity"] == "HIGH"
