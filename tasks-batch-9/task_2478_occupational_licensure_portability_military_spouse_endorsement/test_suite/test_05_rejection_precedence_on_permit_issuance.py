"""Permit issuance can fail four different ways at once. The global order decides
which reason the applicant is told: lifecycle before money, and safety before the
calendar."""

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    APP_DENIED,
    APP_UNDER_REVIEW,
    DECISION_DENY,
    ENTRY_ASSESSMENT,
    ENTRY_PAYMENT,
    ENTRY_PERMIT_FEE,
    ENTRY_WAIVER_CREDIT,
    PATHWAY_UNIVERSAL_RECOGNITION,
    PERMIT_ACTIVE,
    SEVERITY_PROBATION,
    ApiErrorId,
    assert_applicant_fields,
    assert_application_fields,
    assert_ledger_signature,
    assert_permit_fields,
    temporary_permit_payload,
    validate_error,
)


@pytest.fixture
def denied_file_still_owing(setup):
    """A DENIED endorsement file that never paid a cent, with its evaluation already
    on file so the evaluation-before-permit check cannot mask anything."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Bram Silva", state_code="TX", residency_months=24)
    credential = setup.credential(
        applicant["id"], license_number="OK-70041", scope_elements=["ASSESS", "TREAT", "SUPERVISE"]
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    setup.evaluation(application["id"], credential["id"])
    setup.decide(application["id"], DECISION_DENY)
    return {
        "ap_id": applicant["id"],
        "app_id": application["id"],
        "app_version": setup.application_version(application["id"]),
    }


@pytest.fixture
def barred_applicant_with_a_live_permit(setup):
    """A universal-recognition file holding a live permit through 2026-11-29, whose
    applicant has since picked up a probation record worth 15.00 on the reported
    variant the pathway reads."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Lena Duarte", state_code="TX", residency_months=24)
    credential = setup.credential(
        applicant["id"], license_number="OK-70051", scope_elements=["ASSESS", "TREAT", "SUPERVISE"]
    )
    application = setup.application(
        applicant["id"],
        profession["id"],
        credential["id"],
        pathway=PATHWAY_UNIVERSAL_RECOGNITION,
    )
    setup.submit(application["id"], applicant["id"])
    setup.pay(application["id"], applicant["id"], 48000)
    setup.evaluation(application["id"], credential["id"])
    permit = setup.permit(application["id"], "2026-08-01T00:00:00Z")
    setup.pay(application["id"], applicant["id"], 6000)
    setup.set_clock("2026-10-01T00:00:00Z")
    record = setup.disciplinary_record(
        applicant["id"],
        source_state="NM",
        source_database="NPDB",
        severity=SEVERITY_PROBATION,
        action_effective_at="2023-09-01T00:00:00Z",
        reported_at="2026-09-15T00:00:00Z",
    )
    return {
        "ap_id": applicant["id"],
        "app_id": application["id"],
        "dr_id": record["id"],
        "permit": permit,
        "app_version": setup.application_version(application["id"]),
    }


class TestStateOutranksFiscal:
    def test_a_permit_on_a_denied_file_reports_the_lifecycle_bar_not_the_unpaid_balance(
        self, api, denied_file_still_owing, setup
    ):
        """PRD §2.8: "Application from-state — the application is in a state this
        operation permits. Submitting requires `DRAFT`; curing requires `DEFICIENT`;
        recording a deficiency and issuing a board decision require `UNDER_REVIEW`;
        opening the credential evaluation requires `SUBMITTED`; permit issuance,
        exam-result recording, credit-award creation and credit-award revocation
        require the application to be in `SUBMITTED`, `UNDER_REVIEW` or `DEFICIENT`;
        review-assignment creation likewise requires `SUBMITTED`, `UNDER_REVIEW` or
        `DEFICIENT`."

        Design: Difficulty/priority_pair_validation_conflict/permit_on_denied_application_with_balance_reports_state_before_fiscal
        """
        env = denied_file_still_owing
        assert_application_fields(
            setup.read_application(env["app_id"]), status=APP_DENIED, fee_balance_cents=48000
        )

        response = api.create_temporary_permit(
            temporary_permit_payload(env["app_id"], "2026-08-01T00:00:00Z", env["app_version"]),
            ANALYST_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_REVIEWABLE.value, 409)

    def test_the_fiscal_gate_never_speaks_for_a_file_that_is_out_of_the_reviewable_set(
        self, api, denied_file_still_owing, setup
    ):
        """PRD §2.8: "A single request can violate many rules at once, and the
        agency's appeals process depends on the applicant being told the *same* reason
        every time. The system therefore evaluates checks in one fixed global order
        and the **first** violated check decides the response; no later check can mask
        an earlier one, and no earlier success excuses a later failure."

        Design: Difficulty/priority_pair_validation_conflict/permit_on_denied_application_with_balance_reports_state_before_fiscal
        """
        env = denied_file_still_owing
        response = api.create_temporary_permit(
            temporary_permit_payload(env["app_id"], "2026-08-01T00:00:00Z", env["app_version"]),
            ANALYST_HEADERS,
        )
        body = response.json()
        assert body["data"]["error_id"] != ApiErrorId.ERR_FEE_BALANCE_OUTSTANDING.value, (
            "check 36 sits far below check 8 and may not surface here"
        )

        assert_application_fields(
            setup.read_application(env["app_id"]), status=APP_DENIED, fee_balance_cents=48000
        )
        assert setup.read_permits(env["app_id"]) == []
        assert_ledger_signature(
            setup.read_ledger(env["app_id"]),
            [(ENTRY_ASSESSMENT, 48000), (ENTRY_WAIVER_CREDIT, 0)],
        )


class TestSafetyOutranksTemporal:
    def test_a_barred_applicant_hears_the_disciplinary_bar_not_the_window_collision(
        self, api, barred_applicant_with_a_live_permit
    ):
        """PRD §2.8: "Disciplinary bar — reject when the applicant's
        `good_standing_flag` is false, or when the application's `pathway_risk_index`
        is at or above the pathway bar of 12.00 under the pathway-selected variant.
        `ERR_DISCIPLINARY_BAR`, 422. Applies to submitting an application, issuing a
        temporary permit, and a board decision of `APPROVE`."

        Design: Difficulty/priority_pair_validation_conflict/permit_with_bar_and_overlap_reports_safety_before_temporal
        """
        env = barred_applicant_with_a_live_permit
        assert_permit_fields(env["permit"], expires_at="2026-11-29T00:00:00Z")

        response = api.create_temporary_permit(
            temporary_permit_payload(env["app_id"], "2026-10-15T00:00:00Z", env["app_version"]),
            ANALYST_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_DISCIPLINARY_BAR.value, 422)
        assert response.json()["data"]["error_id"] != ApiErrorId.ERR_PERMIT_WINDOW_OVERLAP.value, (
            "the requested window opens inside the live permit's half-open interval, "
            "but check 30 sits below check 13"
        )

    def test_the_pathway_reads_the_reported_variant_so_the_bar_bites_at_fifteen_points(
        self, barred_applicant_with_a_live_permit, setup
    ):
        """PRD §3.3: "An application's `pathway_risk_index` mirrors
        `disciplinary_risk_index_reported` when its `pathway` is
        `UNIVERSAL_RECOGNITION`, and mirrors `disciplinary_risk_index_effective` for
        the `ENDORSEMENT` and `MILITARY_SPOUSE_EXPEDITED` pathways."

        Design: Difficulty/priority_pair_validation_conflict/permit_with_bar_and_overlap_reports_safety_before_temporal
        """
        env = barred_applicant_with_a_live_permit

        applicant = setup.read_applicant(env["ap_id"])
        assert_applicant_fields(
            applicant,
            good_standing_flag=True,
            disciplinary_risk_index_reported=15.00,
            disciplinary_risk_index_effective=6.00,
        )
        assert_application_fields(
            setup.read_application(env["app_id"]),
            pathway_risk_index=15.00,
            status=APP_UNDER_REVIEW,
        )

    def test_a_probation_row_below_the_ceiling_starts_no_cascade_against_the_live_permit(
        self, api, barred_applicant_with_a_live_permit, setup
    ):
        """PRD §3.3: "A posting that leaves `good_standing_flag` unchanged — because
        it was already false, or because the new row is not severe enough to change
        the conjunction — cascades nothing."

        Design: Difficulty/priority_pair_validation_conflict/permit_with_bar_and_overlap_reports_safety_before_temporal
        """
        env = barred_applicant_with_a_live_permit
        api.create_temporary_permit(
            temporary_permit_payload(env["app_id"], "2026-10-15T00:00:00Z", env["app_version"]),
            ANALYST_HEADERS,
        )

        permits = setup.read_permits(env["app_id"])
        assert len(permits) == 1, "the refused issuance created nothing"
        assert_permit_fields(permits[0], status=PERMIT_ACTIVE, revoked_at=None)

    def test_the_refused_issuance_moves_no_money(
        self, api, barred_applicant_with_a_live_permit, setup
    ):
        """PRD §2.10: "Money moves only by appending a `FeeLedgerEntry`."

        Design: Difficulty/priority_pair_validation_conflict/permit_with_bar_and_overlap_reports_safety_before_temporal
        """
        env = barred_applicant_with_a_live_permit
        api.create_temporary_permit(
            temporary_permit_payload(env["app_id"], "2026-10-15T00:00:00Z", env["app_version"]),
            ANALYST_HEADERS,
        )

        assert_ledger_signature(
            setup.read_ledger(env["app_id"]),
            [
                (ENTRY_ASSESSMENT, 48000),
                (ENTRY_WAIVER_CREDIT, 0),
                (ENTRY_PAYMENT, -48000),
                (ENTRY_PERMIT_FEE, 6000),
                (ENTRY_PAYMENT, -6000),
            ],
        )
        assert_application_fields(setup.read_application(env["app_id"]), fee_balance_cents=0)
