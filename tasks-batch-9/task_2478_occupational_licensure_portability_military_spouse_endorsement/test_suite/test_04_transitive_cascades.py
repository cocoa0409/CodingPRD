"""The two long causal chains: a disciplinary posting that reaches through the
applicant flag to the application, its permit and its ledger, and an approval that
reaches through the minted licence to permit conversion and the prorated credit."""

import pytest

from test_helpers import (
    APP_APPROVED,
    APP_SUSPENDED_REVIEW,
    ASSIGNMENT_COMPLETED,
    ASSIGNMENT_RELEASED,
    DECISION_APPROVE,
    DEPUTY_HEADERS,
    DEPUTY_USER_ID,
    ENTRY_ASSESSMENT,
    ENTRY_CONVERSION_CREDIT,
    ENTRY_PAYMENT,
    ENTRY_PERMIT_FEE,
    ENTRY_PERMIT_FEE_REVERSAL,
    ENTRY_WAIVER_CREDIT,
    MEMO_CONVERSION_CREDIT,
    MEMO_PERMIT_FEE_REVERSAL,
    MILITARY_VETERAN,
    PERMIT_CONVERTED,
    PERMIT_REVOKED,
    REASON_DISCIPLINARY_ACTION,
    SEVERITY_SUSPENSION,
    assert_applicant_fields,
    assert_application_fields,
    assert_assignment_fields,
    assert_evaluator_fields,
    assert_hours_conserved,
    assert_instant_equals,
    assert_ledger_signature,
    assert_license_number,
    assert_memo,
    assert_permit_fields,
    ledger_signature,
)

PT_PROFESSION = {
    "profession_code": "PT",
    "title": "Physical Therapist",
    "required_scope_elements": ["EVAL", "MANUAL", "MODALITY"],
    "critical_scope_elements": [],
    "required_practice_hours": 1000,
    "requirement_hours_total": 200.0,
    "exam_waiver_min_score": 70.00,
    "jurisprudence_exam_required": False,
    "universal_recognition_min_residency_months": 12,
    "standard_processing_days": 60,
    "base_fee_cents": 30000,
    "endorsement_fee_cents": 12000,
    "exam_fee_cents": 6000,
    "jurisprudence_fee_cents": 5000,
    "permit_fee_cents": 9000,
    "expedite_surcharge_pct": 0.10,
}


@pytest.fixture
def bridged_nurse(setup):
    """A settled RN file under review, with a reviewer booked and an ACTIVE permit
    bridging the review period."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Marta Krause", state_code="TX", residency_months=24)
    credential = setup.credential(
        applicant["id"], license_number="OK-70031", scope_elements=["ASSESS", "TREAT", "SUPERVISE"]
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    setup.pay(application["id"], applicant["id"], 48000)
    setup.evaluation(application["id"], credential["id"])
    evaluator = setup.evaluator(full_name="Priya Raman", profession_code="RN")
    assignment = setup.review_assignment(
        evaluator["id"], application["id"], "2026-08-02T00:00:00Z", "2026-08-09T00:00:00Z"
    )
    permit = setup.permit(application["id"], "2026-08-01T00:00:00Z")
    return {
        "ap_id": applicant["id"],
        "app_id": application["id"],
        "evr_id": evaluator["id"],
        "assignment_id": assignment["id"],
        "permit": permit,
    }


@pytest.fixture
def approvable_therapist(setup):
    """A PT file cleared through every approval gate, holding an ACTIVE permit issued
    a month before the board sits."""
    profession = setup.profession(**PT_PROFESSION)
    applicant = setup.applicant(
        full_name="Jonah Petit",
        state_code="TX",
        residency_months=24,
        military_status=MILITARY_VETERAN,
    )
    credential = setup.credential(
        applicant["id"],
        issuing_state="NM",
        license_number="NM-88001",
        scope_elements=["EVAL", "MANUAL", "MODALITY"],
        practice_hours=1000,
        issued_at="2018-07-02T00:00:00Z",
    )
    first_record = setup.training_record(
        applicant["id"], documented_hours=133, source_document="JST-PT-133"
    )
    second_record = setup.training_record(
        applicant["id"], documented_hours=137, source_document="JST-PT-137"
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    setup.credit_award(application["id"], first_record["id"])
    setup.credit_award(application["id"], second_record["id"])
    evaluation = setup.evaluation(application["id"], credential["id"])
    setup.scope_review(evaluation["id"])
    evaluator = setup.evaluator(full_name="Hugo Beltran", profession_code="PT")
    assignment = setup.review_assignment(
        evaluator["id"], application["id"], "2026-08-01T00:00:00Z", "2026-08-20T00:00:00Z"
    )
    setup.discipline_finding(evaluation["id"], evaluator["id"])
    setup.finalize(evaluation["id"])
    setup.pay(application["id"], applicant["id"], 21000)
    permit = setup.permit(application["id"], "2026-08-01T00:00:00Z")
    setup.pay(application["id"], applicant["id"], 4500)
    setup.set_clock("2026-09-01T00:00:00Z")
    return {
        "ap_id": applicant["id"],
        "app_id": application["id"],
        "eval_id": evaluation["id"],
        "evr_id": evaluator["id"],
        "assignment_id": assignment["id"],
        "permit": permit,
    }


class TestDisciplinaryPostingCascade:
    def test_a_suspension_posting_pulls_the_application_out_of_the_reviewable_set(
        self, bridged_nurse, setup
    ):
        """PRD §3.3: "Every application of that applicant sitting in `SUBMITTED`,
        `UNDER_REVIEW` or `DEFICIENT` is moved to `SUSPENDED_REVIEW` — three separate
        transitions, `SUBMITTED → SUSPENDED_REVIEW`, `UNDER_REVIEW → SUSPENDED_REVIEW`
        and `DEFICIENT → SUSPENDED_REVIEW`, each incrementing the application's
        `version` — and each suspended application then sheds its dependents exactly
        as §2.9 prescribes: its `ACTIVE` temporary permits become `REVOKED` with
        `revocation_reason_code` set to the literal `DISCIPLINARY_ACTION`, each
        revocation appending its `PERMIT_FEE_REVERSAL` entry and forcing a
        recomputation of `fee_balance_cents`, and its `ASSIGNED` review assignments
        become `RELEASED` with the affected evaluators' `open_assignment_count`
        refreshed."

        Design: Difficulty/transitive_cascade/disciplinary_post_cascades_flag_to_suspension_to_permit_revocation_to_ledger
        """
        setup.disciplinary_record(
            bridged_nurse["ap_id"],
            source_state="OK",
            source_database="NURSYS",
            severity=SEVERITY_SUSPENSION,
            action_effective_at="2026-05-01T00:00:00Z",
            reported_at="2026-07-15T00:00:00Z",
        )

        applicant = setup.read_applicant(bridged_nurse["ap_id"])
        assert_applicant_fields(
            applicant,
            good_standing_flag=False,
            disciplinary_risk_index_reported=30.00,
            disciplinary_risk_index_effective=30.00,
        )
        application = setup.read_application(bridged_nurse["app_id"])
        assert_application_fields(application, status=APP_SUSPENDED_REVIEW)

    def test_the_cascade_revokes_the_bridging_permit_with_the_disciplinary_reason_code(
        self, bridged_nurse, setup
    ):
        """PRD §3.8: "However it is triggered, revocation sets `status` to `REVOKED`,
        sets `revoked_at` to the logical clock, truncates `expires_at` down to
        `revoked_at`, appends a `PERMIT_FEE_REVERSAL` entry whose `amount_cents` is
        the exact negative of the permit's frozen `permit_fee_cents`, recomputes the
        application's `fee_balance_cents` and increments both the permit's `version`
        and the application's `version`."

        Design: Difficulty/transitive_cascade/disciplinary_post_cascades_flag_to_suspension_to_permit_revocation_to_ledger
        """
        assert_permit_fields(bridged_nurse["permit"], expires_at="2026-10-30T00:00:00Z")

        setup.disciplinary_record(
            bridged_nurse["ap_id"],
            source_state="OK",
            source_database="NURSYS",
            severity=SEVERITY_SUSPENSION,
            action_effective_at="2026-05-01T00:00:00Z",
            reported_at="2026-07-15T00:00:00Z",
        )

        permits = setup.read_permits(bridged_nurse["app_id"])
        assert len(permits) == 1
        assert_permit_fields(
            permits[0],
            status=PERMIT_REVOKED,
            revoked_at="2026-08-01T00:00:00Z",
            expires_at="2026-08-01T00:00:00Z",
            revocation_reason_code=REASON_DISCIPLINARY_ACTION,
        )

    def test_the_full_reversal_returns_the_balance_to_its_pre_issuance_value(
        self, bridged_nurse, setup
    ):
        """PRD §3.8: "The reversal is full and never prorated: it is the compensating
        action of the `PERMIT_FEE` entry and returns the balance to precisely its
        pre-issuance value."

        Design: Difficulty/transitive_cascade/disciplinary_post_cascades_flag_to_suspension_to_permit_revocation_to_ledger
        """
        setup.disciplinary_record(
            bridged_nurse["ap_id"],
            source_state="OK",
            source_database="NURSYS",
            severity=SEVERITY_SUSPENSION,
            action_effective_at="2026-05-01T00:00:00Z",
            reported_at="2026-07-15T00:00:00Z",
        )

        ledger = setup.read_ledger(bridged_nurse["app_id"])
        assert_ledger_signature(
            ledger,
            [
                (ENTRY_ASSESSMENT, 48000),
                (ENTRY_WAIVER_CREDIT, 0),
                (ENTRY_PAYMENT, -48000),
                (ENTRY_PERMIT_FEE, 6000),
                (ENTRY_PERMIT_FEE_REVERSAL, -6000),
            ],
        )
        assert_memo(ledger[4], MEMO_PERMIT_FEE_REVERSAL)
        application = setup.read_application(bridged_nurse["app_id"])
        assert_application_fields(application, fee_balance_cents=0)

    def test_the_cascade_also_releases_the_booked_reviewer(self, bridged_nurse, setup):
        """PRD §3.6: "`ASSIGNED → COMPLETED` fires when the application the assignment
        serves is approved; `ASSIGNED → RELEASED` fires when that application enters
        `SUSPENDED_REVIEW` or `DENIED`."

        Design: Difficulty/transitive_cascade/disciplinary_post_cascades_flag_to_suspension_to_permit_revocation_to_ledger
        """
        setup.disciplinary_record(
            bridged_nurse["ap_id"],
            source_state="OK",
            source_database="NURSYS",
            severity=SEVERITY_SUSPENSION,
            action_effective_at="2026-05-01T00:00:00Z",
            reported_at="2026-07-15T00:00:00Z",
        )

        assignment = setup.read_assignment(bridged_nurse["assignment_id"])
        assert_assignment_fields(
            assignment, status=ASSIGNMENT_RELEASED, closed_at="2026-08-01T00:00:00Z"
        )
        assert_evaluator_fields(setup.read_evaluator(bridged_nurse["evr_id"]), open_assignment_count=0)


class TestApprovalCascade:
    def test_approval_mints_exactly_one_licence_on_the_documented_number_and_term(
        self, approvable_therapist, setup
    ):
        """PRD §3.9: "Its `license_number` is minted as the profession's
        `profession_code`, then a hyphen, then a zero-padded six-digit mint sequence;
        the sequence advances by one for each licence row in `created_at` ascending
        order and begins at `000001`."

        Design: Difficulty/transitive_cascade/approval_cascades_license_mint_to_permit_conversion_to_conversion_credit
        """
        setup.decide(approvable_therapist["app_id"], DECISION_APPROVE)

        application = setup.read_application(approvable_therapist["app_id"])
        assert_application_fields(
            application,
            status=APP_APPROVED,
            decided_at="2026-09-01T00:00:00Z",
            decided_by_user_id=DEPUTY_USER_ID,
        )
        licenses = setup.read_licenses()
        assert len(licenses) == 1, "one approval mints one licence and no more"
        licence = licenses[0]
        assert_license_number(licence["license_number"], "PT", 1)
        assert_instant_equals(licence["issued_at"], "2026-09-01T00:00:00Z", "licence.issued_at")
        assert_instant_equals(
            licence["expires_at"],
            "2028-08-31T00:00:00Z",
            "licence.expires_at is issued_at advanced by a 730-day term of two 365-day years",
        )
        assert licence["converted_from_permit_id"] == approvable_therapist["permit"]["id"]

    def test_the_licence_makes_the_bridging_permit_redundant_and_converts_it(
        self, approvable_therapist, setup
    ):
        """PRD §3.9: "The application's temporary permit whose `status` is `ACTIVE`
        takes `ACTIVE → CONVERTED`: its `converted_at` is set to the logical clock,
        its `expires_at` is truncated down to `converted_at`, and the newly minted
        licence records that permit's identifier in `converted_from_permit_id`."

        Design: Difficulty/transitive_cascade/approval_cascades_license_mint_to_permit_conversion_to_conversion_credit
        """
        assert_permit_fields(
            approvable_therapist["permit"],
            expires_at="2026-10-30T00:00:00Z",
            permit_fee_cents=4500,
        )

        setup.decide(approvable_therapist["app_id"], DECISION_APPROVE)

        permits = setup.read_permits(approvable_therapist["app_id"])
        assert len(permits) == 1
        assert_permit_fields(
            permits[0],
            status=PERMIT_CONVERTED,
            converted_at="2026-09-01T00:00:00Z",
            expires_at="2026-09-01T00:00:00Z",
            revoked_at=None,
        )

    def test_the_truncated_window_is_refunded_pro_rata_on_the_unused_days(
        self, approvable_therapist, setup
    ):
        """PRD §3.9: "When the total days is zero — a permit converted at the very
        instant it began — the credit is exactly zero cents and no drift is
        introduced; otherwise the credit is the permit's frozen `permit_fee_cents`
        multiplied by the unused days, divided by the total days, and rounded half up
        to a whole cent."

        Design: Difficulty/transitive_cascade/approval_cascades_license_mint_to_permit_conversion_to_conversion_credit
        """
        setup.decide(approvable_therapist["app_id"], DECISION_APPROVE)

        ledger = setup.read_ledger(approvable_therapist["app_id"])
        credits = [row for row in ledger if row["entry_type"] == ENTRY_CONVERSION_CREDIT]
        assert len(credits) == 1, f"expected one conversion credit, got {ledger_signature(ledger)}"
        assert credits[0]["amount_cents"] == -2950, (
            "4500 cents over a 90-day window with 59 days unused: 4500 * 59 / 90 = 2950"
        )
        assert_memo(credits[0], MEMO_CONVERSION_CREDIT)
        application = setup.read_application(approvable_therapist["app_id"])
        assert_application_fields(application, fee_balance_cents=-2950)

    def test_the_approval_completes_the_assignment_and_frees_the_evaluator(
        self, approvable_therapist, setup
    ):
        """PRD §3.9: "Alongside link one, and caused by it, every review assignment of
        this application whose `status` is `ASSIGNED` moves `ASSIGNED → COMPLETED`
        with the evaluator bookkeeping of §3.6."

        Design: Difficulty/transitive_cascade/approval_cascades_license_mint_to_permit_conversion_to_conversion_credit
        """
        setup.decide(approvable_therapist["app_id"], DECISION_APPROVE, DEPUTY_HEADERS)

        assignment = setup.read_assignment(approvable_therapist["assignment_id"])
        assert_assignment_fields(
            assignment, status=ASSIGNMENT_COMPLETED, closed_at="2026-09-01T00:00:00Z"
        )
        assert_evaluator_fields(
            setup.read_evaluator(approvable_therapist["evr_id"]), open_assignment_count=0
        )

    def test_the_processing_metrics_freeze_on_the_decision_instant(
        self, approvable_therapist, setup
    ):
        """PRD §3.4: "`processing_elapsed_days` is 0 whenever `submitted_at` is null,
        and is otherwise the number of whole days from `submitted_at` to that
        reference instant, discarding any partial day."

        Design: Difficulty/transitive_cascade/approval_cascades_license_mint_to_permit_conversion_to_conversion_credit
        """
        setup.decide(approvable_therapist["app_id"], DECISION_APPROVE)

        application = setup.read_application(approvable_therapist["app_id"])
        assert_application_fields(
            application,
            processing_elapsed_days=31,
            processing_standard_met=True,
            requirement_hours_satisfied=200.0,
            requirement_hours_remaining=0.0,
        )
        assert_hours_conserved(application, 200.0)
