"""Two places where one endpoint chooses between two different target states: the
deficiency recorder that denies once the cycle cap is exceeded, and the disciplinary
resolution that returns a suspended file to whichever reviewable state it came from."""

import pytest

from test_helpers import (
    ANALYST_USER_ID,
    APP_DENIED,
    APP_SUBMITTED,
    APP_UNDER_REVIEW,
    ASSIGNMENT_RELEASED,
    OVERALL_IN_PROGRESS,
    SEVERITY_SUSPENSION,
    assert_applicant_fields,
    assert_application_fields,
    assert_assignment_fields,
    assert_evaluation_fields,
    assert_evaluator_fields,
)


@pytest.fixture
def twice_cured_application(setup):
    """A file under review with an evaluator booked, that has already been through
    two full deficiency and cure cycles."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Tess Nakamura", state_code="TX", residency_months=24)
    credential = setup.credential(
        applicant["id"], license_number="OK-70010", scope_elements=["ASSESS", "TREAT", "SUPERVISE"]
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    evaluation = setup.evaluation(application["id"], credential["id"])
    evaluator = setup.evaluator(full_name="Vera Holt", profession_code="RN")
    assignment = setup.review_assignment(
        evaluator["id"], application["id"], "2026-08-02T00:00:00Z", "2026-08-20T00:00:00Z"
    )
    setup.record_deficiency(application["id"], reason_code="MISSING_VERIFICATION")
    setup.cure(application["id"], applicant["id"])
    setup.record_deficiency(application["id"], reason_code="MISSING_TRANSCRIPT")
    setup.cure(application["id"], applicant["id"])
    return {
        "ap_id": applicant["id"],
        "app_id": application["id"],
        "eval_id": evaluation["id"],
        "evr_id": evaluator["id"],
        "assignment_id": assignment["id"],
    }


@pytest.fixture
def two_suspended_applications(setup):
    """Two submitted files suspended by a SUSPENSION finding, one of which already
    carries a credential evaluation and one of which does not."""
    profession = setup.profession()
    arms = {}
    for key, name, license_number, with_evaluation in (
        ("e", "Ivo Larsen", "OK-70021", True),
        ("f", "Zora Adler", "OK-70022", False),
    ):
        applicant = setup.applicant(full_name=name, state_code="TX", residency_months=24)
        credential = setup.credential(
            applicant["id"],
            license_number=license_number,
            scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        )
        application = setup.application(applicant["id"], profession["id"], credential["id"])
        setup.submit(application["id"], applicant["id"])
        if with_evaluation:
            setup.evaluation(application["id"], credential["id"])
        record = setup.disciplinary_record(
            applicant["id"],
            source_state="OK",
            source_database="NURSYS",
            severity=SEVERITY_SUSPENSION,
            action_effective_at="2026-05-01T00:00:00Z",
            reported_at="2026-07-15T00:00:00Z",
        )
        arms[key] = {
            "ap_id": applicant["id"],
            "app_id": application["id"],
            "dr_id": record["id"],
        }
    return arms


class TestDeficiencyCycleCap:
    def test_two_cycles_loop_and_the_cure_never_decrements_the_cumulative_count(
        self, twice_cured_application, setup
    ):
        """PRD §3.9: "Curing increments the application's `version` and pointedly
        does **not** decrement `deficiency_cycle_count`: the cap of two cycles is
        cumulative across the life of the application, so an applicant who has
        already been through two deficiencies faces denial on the third finding
        rather than a third revision."

        Design: Difficulty/non_linear_state_machine/deficiency_cycle_cap_third_deficiency_denies_instead_of_looping
        """
        application = setup.read_application(twice_cured_application["app_id"])

        assert_application_fields(
            application, status=APP_UNDER_REVIEW, deficiency_cycle_count=2, decided_at=None
        )

    def test_the_third_deficiency_takes_the_denial_branch_instead_of_looping(
        self, twice_cured_application, setup
    ):
        """PRD §3.9: "When the incremented count is greater than 2 — that is, on the
        third deficiency — the application takes `UNDER_REVIEW → DENIED` instead of
        looping: `decided_at` is set to the logical clock, `decided_by_user_id` is
        set to the acting `X-User-ID`, `processing_elapsed_days` and
        `processing_standard_met` are computed as in §3.4, every `ACTIVE` temporary
        permit of the application is revoked with `revocation_reason_code`
        `APPLICATION_DENIED` and its full `PERMIT_FEE_REVERSAL`, every `ASSIGNED`
        review assignment is released, and the application's `version` increments."

        Design: Difficulty/non_linear_state_machine/deficiency_cycle_cap_third_deficiency_denies_instead_of_looping
        """
        setup.record_deficiency(twice_cured_application["app_id"], reason_code="MISSING_HOURS")

        application = setup.read_application(twice_cured_application["app_id"])
        assert_application_fields(
            application,
            status=APP_DENIED,
            deficiency_cycle_count=3,
            decided_at="2026-08-01T00:00:00Z",
            decided_by_user_id=ANALYST_USER_ID,
            processing_elapsed_days=0,
            processing_standard_met=True,
        )

    def test_the_denial_releases_the_open_assignment_and_frees_the_evaluator(
        self, twice_cured_application, setup
    ):
        """PRD §3.6: "`ASSIGNED → COMPLETED` fires when the application the
        assignment serves is approved; `ASSIGNED → RELEASED` fires when that
        application enters `SUSPENDED_REVIEW` or `DENIED`. In both cases `closed_at`
        is set to the logical clock, the assignment's `version` increments, the
        evaluator's `open_assignment_count` is recomputed, and the evaluator's
        `version` increments."

        Design: Difficulty/non_linear_state_machine/deficiency_cycle_cap_third_deficiency_denies_instead_of_looping
        """
        setup.record_deficiency(twice_cured_application["app_id"], reason_code="MISSING_HOURS")

        assignment = setup.read_assignment(twice_cured_application["assignment_id"])
        assert_assignment_fields(
            assignment, status=ASSIGNMENT_RELEASED, closed_at="2026-08-01T00:00:00Z"
        )
        evaluator = setup.read_evaluator(twice_cured_application["evr_id"])
        assert_evaluator_fields(evaluator, open_assignment_count=0)

    def test_the_denial_does_not_finalise_the_open_evaluation(
        self, twice_cured_application, setup
    ):
        """PRD §3.5: "it is `COMPLETE` exactly when `scope_review_status` is not
        `PENDING`, `discipline_review_status` is not `PENDING`, and `finalized_at` is
        not null, and it is `IN_PROGRESS` in every other case."

        Design: Difficulty/non_linear_state_machine/deficiency_cycle_cap_third_deficiency_denies_instead_of_looping
        """
        setup.record_deficiency(twice_cured_application["app_id"], reason_code="MISSING_HOURS")

        evaluation = setup.read_evaluation(twice_cured_application["eval_id"])
        assert_evaluation_fields(
            evaluation, overall_status=OVERALL_IN_PROGRESS, finalized_at=None
        )


class TestSuspendedReviewReentry:
    def test_reentry_lands_in_under_review_when_a_credential_evaluation_already_exists(
        self, two_suspended_applications, setup
    ):
        """PRD §3.3: "When the recomputation flips `good_standing_flag` from false to
        true, every application of that applicant in `SUSPENDED_REVIEW` re-enters the
        reviewable set, and where it lands depends on how far it had got: an
        application that already has a credential evaluation returns along
        `SUSPENDED_REVIEW → UNDER_REVIEW`, while an application with no credential
        evaluation at all returns along `SUSPENDED_REVIEW → SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/suspended_review_reentry_branches_on_evaluation_existence
        """
        arm = two_suspended_applications["e"]
        setup.resolve_disciplinary_record(arm["dr_id"])

        application = setup.read_application(arm["app_id"])
        assert_application_fields(
            application, status=APP_UNDER_REVIEW, submitted_at="2026-08-01T00:00:00Z"
        )

    def test_reentry_lands_in_submitted_when_no_evaluation_was_ever_opened(
        self, two_suspended_applications, setup
    ):
        """PRD §3.3: "Resolving a record sets its `resolved` flag to true and its
        `resolved_at` to the logical clock, then recomputes both risk-index variants
        and `good_standing_flag` and increments the applicant's `version`."

        Design: Difficulty/non_linear_state_machine/suspended_review_reentry_branches_on_evaluation_existence
        """
        arm = two_suspended_applications["f"]
        setup.resolve_disciplinary_record(arm["dr_id"])

        application = setup.read_application(arm["app_id"])
        assert_application_fields(
            application, status=APP_SUBMITTED, submitted_at="2026-08-01T00:00:00Z"
        )

    def test_resolved_rows_leave_both_sweeps_so_the_indexes_fall_back_to_zero(
        self, two_suspended_applications, setup
    ):
        """PRD §3.3: "Gather every disciplinary record belonging to the applicant
        whose `resolved` flag is false; resolved rows leave both sweeps entirely, and
        records are never filtered by `source_database`."

        Design: Difficulty/non_linear_state_machine/suspended_review_reentry_branches_on_evaluation_existence
        """
        for key in ("e", "f"):
            setup.resolve_disciplinary_record(two_suspended_applications[key]["dr_id"])

        first = setup.read_applicant(two_suspended_applications["e"]["ap_id"])
        second = setup.read_applicant(two_suspended_applications["f"]["ap_id"])
        assert_applicant_fields(
            first, good_standing_flag=True, disciplinary_risk_index_reported=0.00
        )
        assert_applicant_fields(
            second, good_standing_flag=True, disciplinary_risk_index_effective=0.00
        )
