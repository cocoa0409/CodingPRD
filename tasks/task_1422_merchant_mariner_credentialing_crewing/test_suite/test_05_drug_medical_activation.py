"""Mariner activation gates, medical-certificate lifecycle, and the drug
program's posture cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    confirm_assignment,
    create_activated_mariner,
    create_manning_slot,
    create_manning_slot_payload,
    create_mariner,
    issue_credential,
    issue_medical_certificate,
    propose_assignment,
    record_drug_result,
    record_negative_drug_test,
    schedule_drug_test,
    setup_active_vessel_with_slot,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
CREWING = TEST_USERS["crewing_headers"]


class TestMarinerActivation:

    def test_mariner_activation_gates_missing_rejected(self, fleet_admin_headers):
        """PRD section 3.1: "Activation moves a mariner from `APPLICANT` to
        `ACTIVE` and enforces three gates, each of which fails with
        `ERR_MARINER_ACTIVATION_REQUIREMENTS_MISSING`: at least one medical
        certificate in `VALID` status whose `expiry_date` is on or after now;
        at least one completed drug test with result `NEGATIVE` whose
        `collected_date` extended by 365 days is on or after now; and at least
        one credential in `VALID` status."

        Design: Corner/state_machines/mariner_activation_gates_missing_rejected
        """
        mariner = create_mariner()
        # Zero of three gates satisfied.
        resp = api_client.activate_mariner(mariner["id"], fleet_admin_headers)
        validate_error(
            resp, ApiErrorId.ERR_MARINER_ACTIVATION_REQUIREMENTS_MISSING)

        # Medical and credential present, but no qualifying drug test.
        issue_medical_certificate(mariner["id"])
        issue_credential(mariner["id"])
        resp = api_client.activate_mariner(mariner["id"], fleet_admin_headers)
        validate_error(
            resp, ApiErrorId.ERR_MARINER_ACTIVATION_REQUIREMENTS_MISSING)


class TestMedicalCertificateLifecycle:

    def test_medical_double_suspend_rejected(self, officer_headers):
        """PRD section 3.5: "Suspending a certificate moves `VALID` to
        `SUSPENDED` (any other source state is
        `ERR_MEDICAL_CERT_NOT_VALID`)."

        Design: Corner/errors/medical_double_suspend_rejected
        """
        mariner = create_mariner()
        cert = issue_medical_certificate(mariner["id"])
        suspended = validate_success(
            api_client.suspend_medical_certificate(
                mariner["id"], cert["id"], officer_headers))
        assert suspended["status"] == "SUSPENDED"

        resp = api_client.suspend_medical_certificate(
            mariner["id"], cert["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_MEDICAL_CERT_NOT_VALID)


class TestDrugTestProgram:

    def test_drug_test_double_result_rejected(self, officer_headers):
        """PRD section 3.5: "Recording a result moves `PENDING` to `COMPLETED`
        (else `ERR_DRUG_TEST_NOT_PENDING`) with a `result` of `NEGATIVE`,
        `POSITIVE`, or `REFUSAL` (anything else is `ERR_INVALID_REQUEST`) and
        the supplied `collected_date`, stamping `recorded_by_user_id` with the
        recorder's `X-User-ID`."

        Design: Corner/state_machines/drug_test_double_result_rejected
        """
        mariner = create_mariner()
        test = schedule_drug_test(
            mariner["id"], test_type="RANDOM",
            scheduled_date="2026-05-01T00:00:00Z")
        recorded = record_drug_result(
            mariner["id"], test["id"], result="NEGATIVE",
            collected_date="2026-05-01T00:00:00Z")
        assert recorded["status"] == "COMPLETED"

        resp = api_client.record_drug_test_result(
            mariner["id"], test["id"],
            {"result": "POSITIVE", "collected_date": "2026-05-02T00:00:00Z"},
            officer_headers)
        validate_error(resp, ApiErrorId.ERR_DRUG_TEST_NOT_PENDING)

        tests = validate_success(
            api_client.list_drug_tests(mariner["id"], officer_headers))
        assert tests[0]["result"] == "NEGATIVE", \
            "the second record-result call must have no effect"


class TestDrugPositiveCascade:

    def _setup_two_confirmed_assignments(self):
        """CLEAR mariner with two CONFIRMED assignments on two slots of one
        vessel (touching half-open windows, so no overlap), plus one PENDING
        PERIODIC drug test."""
        mariner = create_activated_mariner()
        env = setup_active_vessel_with_slot(
            slot_overrides={"is_critical_position": True,
                            "position_code": "AB"})
        slot2 = create_manning_slot(
            env["vessel"]["id"],
            **create_manning_slot_payload(
                position_code="OS", min_rank_grade=1,
                is_critical_position=False))
        a1 = propose_assignment(
            mariner["id"], env["slot"]["id"],
            sign_on_date="2026-08-10T00:00:00Z",
            planned_relief_date="2026-11-10T00:00:00Z", local_join=True)
        a2 = propose_assignment(
            mariner["id"], slot2["id"],
            sign_on_date="2026-11-10T00:00:00Z",
            planned_relief_date="2027-02-10T00:00:00Z", local_join=True)
        a1 = confirm_assignment(a1["id"])
        a2 = confirm_assignment(a2["id"])
        test = schedule_drug_test(
            mariner["id"], test_type="PERIODIC",
            scheduled_date="2026-08-05T00:00:00Z")
        return {"mariner": mariner, "a1": a1, "a2": a2, "test": test}

    def test_positive_result_blocks_posture_without_extending_currency(
            self, officer_headers):
        """PRD section 3.5: "A `POSITIVE` or `REFUSAL` result forces the
        mariner's posture to `BLOCKED` with reason `DRUG_RESULT_POSITIVE`"
        PRD section 3.2: "The third gate is drug currency:
        `drug_test_current_until` is the latest `collected_date` among the
        mariner's completed tests with result `NEGATIVE` and `test_type` one
        of `PRE_EMPLOYMENT`, `PERIODIC`, `RANDOM`, or `RETURN_TO_DUTY`,
        extended by 365 days"

        Design: Difficulty/transitive_cascade/drug_positive_cascade
        """
        ctx = self._setup_two_confirmed_assignments()
        recorded = record_drug_result(
            ctx["mariner"]["id"], ctx["test"]["id"], result="POSITIVE",
            collected_date="2026-08-05T00:00:00Z")
        assert recorded["status"] == "COMPLETED"

        mariner = validate_success(
            api_client.get_mariner(ctx["mariner"]["id"], officer_headers))
        assert mariner["readiness_posture"] == "BLOCKED"
        assert "DRUG_RESULT_POSITIVE" in mariner["readiness_reasons"]
        assert mariner["drug_test_current_until"] == "2027-01-02T00:00:00Z", (
            f"a POSITIVE never extends the currency window (the earlier "
            f"NEGATIVE still governs), got {mariner['drug_test_current_until']}")

    def test_positive_result_suspends_all_confirmed_assignments(self):
        """PRD section 3.5: "A `POSITIVE` or `REFUSAL` result forces the
        mariner's posture to `BLOCKED` with reason `DRUG_RESULT_POSITIVE` and
        suspends every confirmed assignment of the mariner, with slot coverage
        and vessel compliance recomputed."

        Design: Difficulty/transitive_cascade/drug_positive_cascade
        """
        ctx = self._setup_two_confirmed_assignments()
        record_drug_result(
            ctx["mariner"]["id"], ctx["test"]["id"], result="POSITIVE",
            collected_date="2026-08-05T00:00:00Z")

        a1 = validate_success(api_client.get_assignment(ctx["a1"]["id"], CREWING))
        a2 = validate_success(api_client.get_assignment(ctx["a2"]["id"], CREWING))
        assert a1["assignment_status"] == "SUSPENDED", \
            f"hop to first CONFIRMED assignment, got {a1['assignment_status']}"
        assert a2["assignment_status"] == "SUSPENDED", \
            f"hop to second CONFIRMED assignment, got {a2['assignment_status']}"
