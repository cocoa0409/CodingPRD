"""Exposure intake risk classification, parallel status dimensions, and
source-patient testing under segregation of duties."""
from test_helpers import (
    ApiErrorId,
    assert_exposure_case,
    create_exposure_case,
    create_exposure_case_payload,
    get_case_followup,
    get_case_pep,
    get_exposure_case,
    list_case_followups,
    list_case_pep,
    make_nurse_headers,
    register_employee,
    transition_case,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRiskClassificationBranches:
    def test_known_source_high_vs_unknown_source_medium(self, api, nurse_headers,
                                                        physician_headers):
        """PRD §3.4: "a `PERCUTANEOUS` exposure to `BLOOD` with a known source
        is `HIGH`; the same exposure with an unknown source is `MEDIUM`" and
        "The source-testing dimension, `source_test_status`, begins at
        `CONSENT_PENDING` when the source patient is known and at
        `NOT_REQUIRED` otherwise." and "When the classification is `HIGH` or
        `MEDIUM`, the computed `pep_required` flag is true and intake
        auto-creates one prophylaxis regimen in `RECOMMENDED` status."

        Design: Difficulty/combinatorial_formula/risk_classification_branch_interaction
        """
        emp = register_employee("E-CF1", full_name="Ria Branch", department="ED")

        high = create_exposure_case(
            emp["id"], exposure_type="PERCUTANEOUS", source_known=True,
            source_patient_ref="SP-100", body_fluid="BLOOD",
        )
        med = create_exposure_case(
            emp["id"], exposure_type="PERCUTANEOUS", source_known=False,
            body_fluid="BLOOD",
        )

        # Identical mechanics (PERCUTANEOUS/BLOOD) classify differently on
        # source_known alone.
        assert high["risk_classification"] == "HIGH"
        assert high["pep_required"] is True
        assert high["source_test_status"] == "CONSENT_PENDING"
        assert med["risk_classification"] == "MEDIUM"
        assert med["pep_required"] is True
        assert med["source_test_status"] == "NOT_REQUIRED"

        for case in (high, med):
            peps = list_case_pep(case["id"])
            assert len(peps) == 1, "intake auto-creates exactly one regimen"
            assert peps[0]["status"] == "RECOMMENDED"
            followups = list_case_followups(case["id"])
            assert len(followups) == 1, "intake always creates the BASELINE follow-up"
            assert followups[0]["milestone"] == "BASELINE"
            assert followups[0]["status"] == "SCHEDULED"

    def test_low_classification_suppresses_pep_autocreation(self, api,
                                                            physician_headers):
        """PRD §3.4: "An exposure whose `body_fluid` is `NON_INFECTIOUS` is
        always `LOW`." and "any `SKIN_CONTACT` exposure, regardless of fluid,
        is `LOW`." and "Regardless of classification, intake always
        auto-creates one serology follow-up at the `BASELINE` milestone in
        `SCHEDULED` status."

        Design: Difficulty/combinatorial_formula/risk_classification_branch_interaction
        """
        emp = register_employee("E-CF1L", full_name="Lo Risk", department="ED")
        case = create_exposure_case(
            emp["id"], exposure_type="SKIN_CONTACT", source_known=False,
            body_fluid="NON_INFECTIOUS",
        )
        assert_exposure_case(case)
        assert case["risk_classification"] == "LOW"
        assert case["pep_required"] is False

        peps = list_case_pep(case["id"])
        assert peps == [], "LOW classification creates no prophylaxis regimen"
        baseline = get_case_followup(case["id"], "BASELINE")
        assert baseline["status"] == "SCHEDULED"


class TestParallelStatusDimensions:
    def test_case_advance_leaves_source_dimension_untouched(self, api,
                                                            physician_headers):
        """PRD §3.4: "The case carries two parallel status dimensions that
        evolve independently." and "From `REPORTED`, the case moves to
        `EVALUATION`; any other from-state is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/exposure_case_parallel_dimensions
        """
        emp = register_employee("E-NL1", full_name="Pam Dims")
        case = create_exposure_case(
            emp["id"], exposure_type="PERCUTANEOUS", source_known=True,
            source_patient_ref="SP-200", body_fluid="BLOOD",
            headers=make_nurse_headers("nurse-1"),
        )
        assert case["case_status"] == "REPORTED"
        assert case["source_test_status"] == "CONSENT_PENDING"

        advanced = transition_case(case["id"], "EVALUATION")
        assert advanced["case_status"] == "EVALUATION"
        assert advanced["source_test_status"] == "CONSENT_PENDING", (
            "advancing the clinical dimension must not move the source dimension"
        )

    def test_consent_recording_leaves_case_dimension_untouched(self, api,
                                                               physician_headers):
        """PRD §3.4: "Consent recording moves `CONSENT_PENDING` to
        `CONSENT_GRANTED`, `CONSENT_DECLINED`, or `WAIVED_UNABLE` according to
        the submitted `outcome`, stamps `consent_recorded_by_user_id` (which
        remains null until a consent outcome is recorded)" and "Intake stamps
        `reported_at` from the logical clock and records the intake nurse's
        identity in `recorded_by_user_id`."

        Design: Difficulty/non_linear_state_machine/exposure_case_parallel_dimensions
        """
        emp = register_employee("E-NL1B", full_name="Pam Two")
        case = create_exposure_case(
            emp["id"], exposure_type="PERCUTANEOUS", source_known=True,
            source_patient_ref="SP-201", body_fluid="BLOOD",
            headers=make_nurse_headers("nurse-1"),
        )
        transition_case(case["id"], "EVALUATION")

        resp = api.record_source_testing(
            case["id"],
            {"action": "RECORD_CONSENT", "outcome": "CONSENT_GRANTED"},
            make_nurse_headers("nurse-2"),
        )
        updated = validate_success(resp)
        assert updated["source_test_status"] == "CONSENT_GRANTED"
        assert updated["case_status"] == "EVALUATION", (
            "recording consent must not move the clinical dimension"
        )
        assert updated["recorded_by_user_id"] == "nurse-1"
        assert updated["consent_recorded_by_user_id"] == "nurse-2"


class TestSourceConsentSegregationOfDuties:
    def test_intake_nurse_cannot_record_consent_on_own_case(self, api):
        """PRD §3.4: "enforces segregation of duties: the acting nurse's
        `X-User-ID` must differ from the case's `recorded_by_user_id`, so the
        intake nurse can never record the source patient's consent on their own
        case (`ERR_SOD_SOURCE_CONSENT`)."

        Design: Corner/rbac/sod_source_consent_recorder_must_differ
        """
        emp = register_employee("E-RB5", full_name="Sod Case")
        case = create_exposure_case(
            emp["id"], exposure_type="PERCUTANEOUS", source_known=True,
            source_patient_ref="SP-RB5", body_fluid="BLOOD",
            headers=make_nurse_headers("nurse-1"),
        )

        same = api.record_source_testing(
            case["id"],
            {"action": "RECORD_CONSENT", "outcome": "CONSENT_GRANTED"},
            make_nurse_headers("nurse-1"),
        )
        validate_error(same, ApiErrorId.ERR_SOD_SOURCE_CONSENT)

        other = api.record_source_testing(
            case["id"],
            {"action": "RECORD_CONSENT", "outcome": "CONSENT_GRANTED"},
            make_nurse_headers("nurse-2"),
        )
        updated = validate_success(other)
        assert updated["source_test_status"] == "CONSENT_GRANTED"
        assert updated["consent_recorded_by_user_id"] == "nurse-2"


class TestSourcePatientRefCondition:
    def test_source_ref_required_when_source_known(self, api, nurse_headers):
        """PRD §3.4: "When `source_known` is true, `source_patient_ref` is
        required; when false, `source_patient_ref` must be null; a violation of
        either direction is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/case_source_ref_required_when_known
        """
        emp = register_employee("E-V7", full_name="No Ref")
        resp = api.create_exposure_case(
            emp["id"],
            create_exposure_case_payload(
                exposure_type="PERCUTANEOUS", source_known=True, body_fluid="BLOOD",
            ),
            nurse_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        _data, meta = validate_paginated(
            api.list_exposure_cases(nurse_headers, params={"employee_id": emp["id"]})
        )
        assert meta["total_count"] == 0


class TestCaseAdvanceGates:
    def test_management_blocked_while_source_consent_pending(self, api,
                                                             physician_headers):
        """PRD §3.4: "From `EVALUATION` to `MANAGEMENT` there is an additional
        gate: `source_test_status` must be one of `NOT_REQUIRED`, `RESULTED`,
        `CONSENT_DECLINED`, or `WAIVED_UNABLE`, so that source testing is
        resolved before management begins — otherwise the advance is rejected
        with `ERR_SOURCE_TESTING_UNRESOLVED`."

        Design: Corner/state_machines/case_management_blocked_while_consent_pending
        """
        emp = register_employee("E-SM9", full_name="Src Pending")
        case = create_exposure_case(
            emp["id"], exposure_type="PERCUTANEOUS", source_known=True,
            source_patient_ref="SP-9", body_fluid="BLOOD",
        )
        transition_case(case["id"], "EVALUATION")

        resp = api.transition_exposure_case(
            case["id"], {"to_state": "MANAGEMENT"}, physician_headers
        )
        validate_error(resp, ApiErrorId.ERR_SOURCE_TESTING_UNRESOLVED)
        assert get_exposure_case(case["id"])["case_status"] == "EVALUATION"

    def test_close_blocked_by_open_followup_and_regimen(self, api,
                                                        physician_headers):
        """PRD §3.4: "From `MANAGEMENT` to `CLOSED`, three closures must hold:
        no serology follow-up of the case remains in `SCHEDULED`, `DUE`, or
        `OVERDUE`; every prophylaxis regimen of the case has reached
        `COMPLETED`, `DECLINED`, or `WINDOW_EXPIRED`; and no work restriction
        linked to the case remains `ACTIVE`. Any failure is rejected with
        `ERR_CASE_CLOSE_BLOCKED`."

        Design: Corner/state_machines/case_close_blocked_by_open_items
        """
        emp = register_employee("E-SM10", full_name="Close Block", department="ED")
        case = create_exposure_case(
            emp["id"], exposure_type="PERCUTANEOUS", source_known=False,
            body_fluid="BLOOD",
        )
        transition_case(case["id"], "EVALUATION")
        # source_test_status is NOT_REQUIRED: the management gate is satisfied.
        transition_case(case["id"], "MANAGEMENT")

        resp = api.transition_exposure_case(
            case["id"], {"to_state": "CLOSED"}, physician_headers
        )
        validate_error(resp, ApiErrorId.ERR_CASE_CLOSE_BLOCKED)

        after = get_exposure_case(case["id"])
        assert after["case_status"] == "MANAGEMENT"
        baseline = get_case_followup(case["id"], "BASELINE")
        assert baseline["status"] == "SCHEDULED", (
            "the never-resulted BASELINE follow-up still blocks closure"
        )
        assert get_case_pep(case["id"])["status"] == "RECOMMENDED", (
            "the never-acted-on regimen still blocks closure"
        )


class TestExposureCaseListing:
    def test_list_filters_by_case_status(self, api, nurse_headers,
                                         physician_headers):
        """PRD §3.1: "list endpoints for employee-owned resources — screenings,
        titers, cycles, holds, exposure cases, restrictions, and injury reports
        alike — accept the owning employee's `employee_id` as a filter
        alongside their resource-specific filters."
        PRD §4: exposure-case listing is "filterable by employee and case
        status".

        Design: Corner/endpoints/exposure_case_list_filter_by_status
        """
        emp = register_employee("E-P2", full_name="Fil Ter", department="ED")
        case1 = create_exposure_case(
            emp["id"], exposure_type="SKIN_CONTACT", source_known=False,
            body_fluid="NON_INFECTIOUS",
            exposure_datetime="2026-07-30T10:00:00Z",
        )
        case2 = create_exposure_case(
            emp["id"], exposure_type="SKIN_CONTACT", source_known=False,
            body_fluid="NON_INFECTIOUS",
            exposure_datetime="2026-07-30T11:00:00Z",
        )
        transition_case(case2["id"], "EVALUATION")

        reported, meta_r = validate_paginated(api.list_exposure_cases(
            nurse_headers,
            params={"employee_id": emp["id"], "case_status": "REPORTED"},
        ))
        assert meta_r["total_count"] == 1
        assert [row["id"] for row in reported] == [case1["id"]]

        evaluation, meta_e = validate_paginated(api.list_exposure_cases(
            nurse_headers,
            params={"employee_id": emp["id"], "case_status": "EVALUATION"},
        ))
        assert meta_e["total_count"] == 1
        assert [row["id"] for row in evaluation] == [case2["id"]]
