"""Legal review, privilege pinning/invalidation, and study closure (PRD §3.3, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_study,
    create_run,
    create_study,
    finalize_run,
    get_study,
    legal_approve,
    setup_analyzed_study,
    setup_privileged_final_study,
    setup_provisional_run_scenario,
    submit_legal_review,
    two_eng_member_specs,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["comp_analyst_headers"]
COUNSEL = TEST_USERS["legal_counsel_headers"]


class TestLegalReviewReworkCycle:
    def test_request_changes_returns_study_to_draft(self, api):
        """PRD §3.3: "A `decision` of `REQUEST_CHANGES` requires a non-empty `rationale` (otherwise `ERR_RATIONALE_REQUIRED`) and returns the study to `DRAFT`, clearing `privileged_model_run_ids` and making snapshots editable again — this is the rework loop."
        PRD §3.3: "Each entry into `UNDER_LEGAL_REVIEW` — whether by submission or by the privilege-invalidation path below — increments the study's `review_rounds` by one."

        Design: Difficulty/non_linear_state_machine/study_legal_review_rework_cycle
        """
        ctx = setup_analyzed_study(
            name="StudyR", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", member_specs=two_eng_member_specs(),
            group_name="GR", min_group_size=2, methodology="REGRESSION_OLS",
        )
        under_review = submit_legal_review(ctx["study"]["id"])
        assert under_review["status"] == "UNDER_LEGAL_REVIEW"
        assert under_review["review_rounds"] == 1
        # Counsel sends the study back: the rework loop lands it in DRAFT.
        rejected = validate_success(
            api.legal_decision(
                ctx["study"]["id"],
                {
                    "decision": "REQUEST_CHANGES",
                    "rationale": "Expand comparator scope before privilege",
                },
                COUNSEL,
            )
        )
        assert rejected["status"] == "DRAFT"
        assert rejected["privileged_model_run_ids"] == []

    def test_rework_loop_second_entry_increments_review_rounds(self, api):
        """PRD §3.3: "Each entry into `UNDER_LEGAL_REVIEW` — whether by submission or by the privilege-invalidation path below — increments the study's `review_rounds` by one."
        PRD §3.2: "Advancement requires the study to be in `DRAFT` (otherwise `ERR_STUDY_INVALID_STATE`) and at least one of its comparator groups to have a `member_count` of at least the study's `min_group_size` (otherwise `ERR_NO_QUALIFYING_GROUPS`)."

        Design: Difficulty/non_linear_state_machine/study_legal_review_rework_cycle
        """
        ctx = setup_analyzed_study(
            name="StudyR", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", member_specs=two_eng_member_specs(),
            group_name="GR", min_group_size=2, methodology="REGRESSION_OLS",
        )
        submit_legal_review(ctx["study"]["id"])
        rejected = validate_success(
            api.legal_decision(
                ctx["study"]["id"],
                {
                    "decision": "REQUEST_CHANGES",
                    "rationale": "Expand comparator scope before privilege",
                },
                COUNSEL,
            )
        )
        assert rejected["status"] == "DRAFT"
        # Re-advance succeeds: the still-populated group (member_count 2 >= 2)
        # satisfies the qualifying-group gate again.
        advanced = advance_study(ctx["study"]["id"])
        assert advanced["status"] == "MODELING"
        # The second entry into legal review proves the cycle re-traversed.
        second = submit_legal_review(ctx["study"]["id"])
        assert second["status"] == "UNDER_LEGAL_REVIEW"
        assert second["review_rounds"] == 2


class TestPrivilegePinningAndInvalidation:
    def test_privilege_invalidation_on_new_finalize(self, api):
        """PRD §3.3: "If any model run in the study finalizes while the study is `PRIVILEGED_FINAL`, the study automatically returns to `UNDER_LEGAL_REVIEW` with `privileged_model_run_ids` cleared and `review_rounds` incremented, exactly as described in §3.2 — new statistical evidence invalidates the previously pinned privilege set."
        PRD §3.3: "A `decision` of `APPROVE` moves the study from `UNDER_LEGAL_REVIEW` to `PRIVILEGED_FINAL` and version-pins the privileged work product: `privileged_model_run_ids` is set to the ids of all `FINAL` model runs in the study."

        Design: Corner/state_machines/privilege_invalidation_on_new_finalize
        """
        ctx = setup_provisional_run_scenario(
            name="PV", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", member_specs=two_eng_member_specs(),
            group_name="GPV", min_group_size=2, methodology="COHORT_MEDIAN",
        )
        r1 = finalize_run(ctx["run"]["id"])
        # A second run is created (PROVISIONAL) before legal review and left pending.
        r2 = create_run(ctx["group"]["id"], methodology="REGRESSION_OLS")
        submit_legal_review(ctx["study"]["id"])
        approved = legal_approve(ctx["study"]["id"])
        assert approved["status"] == "PRIVILEGED_FINAL"
        assert approved["privileged_model_run_ids"] == [r1["id"]]
        assert approved["review_rounds"] == 1

        # Finalizing the leftover run invalidates the pinned evidence set.
        r2_final = finalize_run(r2["id"])
        assert r2_final["status"] == "FINAL"
        study = get_study(ctx["study"]["id"])
        assert study["status"] == "UNDER_LEGAL_REVIEW"
        assert study["privileged_model_run_ids"] == []
        assert study["review_rounds"] == 2


class TestStudyClosure:
    def test_study_close_from_draft_rejected(self, api):
        """PRD §3.7: "a `LegalCounsel` closes a study from `MONITORING` (from any other state except `PRIVILEGED_FINAL`, where §3.3's clean-study path applies, the attempt is rejected with `ERR_STUDY_INVALID_STATE`) only when the latest `COMPLETED` cycle by `cycle_index` recorded a `retest_result` of `GAPS_CLOSED`; otherwise the closure is rejected with `ERR_GAPS_NOT_CLOSED`."

        Design: Corner/state_machines/study_close_from_draft_rejected
        """
        study = create_study(
            name="CD", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31",
        )
        res = api.close_study(study["id"], COUNSEL)
        validate_error(res, ApiErrorId.ERR_STUDY_INVALID_STATE)

    def test_clean_study_close_from_privileged_final(self, api):
        """PRD §3.3: "Alternatively, when a study's analysis shows nothing to fix, counsel may close the study directly from `PRIVILEGED_FINAL`, but only when the study's `actionable_finding_count` is zero; otherwise the closure is rejected with `ERR_GAPS_NOT_CLOSED`."
        PRD §3.3: "A `decision` of `APPROVE` moves the study from `UNDER_LEGAL_REVIEW` to `PRIVILEGED_FINAL` and version-pins the privileged work product: `privileged_model_run_ids` is set to the ids of all `FINAL` model runs in the study."

        Design: Corner/state_machines/clean_study_close_from_privileged_final
        """
        ctx = setup_privileged_final_study(
            name="CC", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", member_specs=two_eng_member_specs(),
            group_name="GCC", min_group_size=2, methodology="COHORT_MEDIAN",
        )
        # The single FINAL run is pinned at approval.
        assert ctx["study"]["privileged_model_run_ids"] == [ctx["run"]["id"]]
        # The only finding is non-actionable (p 0.0909 > 0.05 default ceiling),
        # so actionable_finding_count is zero and the clean-study path opens.
        study = get_study(ctx["study"]["id"])
        assert study["actionable_finding_count"] == 0
        closed = validate_success(api.close_study(study["id"], COUNSEL))
        assert closed["status"] == "CLOSED"

    def test_close_privileged_study_with_actionable_gaps_rejected(self, api):
        """PRD §3.3: "Alternatively, when a study's analysis shows nothing to fix, counsel may close the study directly from `PRIVILEGED_FINAL`, but only when the study's `actionable_finding_count` is zero; otherwise the closure is rejected with `ERR_GAPS_NOT_CLOSED`."

        Design: Corner/validations/close_privileged_study_with_actionable_gaps_rejected
        """
        ctx = setup_privileged_final_study(
            name="CA", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", member_specs=two_eng_member_specs(),
            group_name="GCA", min_group_size=2, significance_threshold=0.1,
            methodology="COHORT_MEDIAN",
        )
        # With the raised significance ceiling the finding IS actionable.
        assert ctx["findings"][0]["is_actionable"] is True
        res = api.close_study(ctx["study"]["id"], COUNSEL)
        validate_error(res, ApiErrorId.ERR_GAPS_NOT_CLOSED)
