"""Independent validation engagements, the retest loop, and review-window overlap
semantics (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    complete_engagement,
    create_approved_model,
    create_engagement_payload,
    create_model,
    create_model_with_approved_doc,
    create_retired_pair,
    get_model,
    open_engagement,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

OWNER_A = TEST_USERS["model_owner_a_headers"]
OWNER_B = TEST_USERS["model_owner_b_headers"]
VALIDATOR = TEST_USERS["model_validator_headers"]
OFFICER = TEST_USERS["risk_officer_headers"]


class TestEngagementCreation:
    def test_engagement_creation_stamps_validator_and_testing(self, api):
        """PRD §3.4: "The creating validator's `X-User-ID` is stored as
        `validator_user_id`, and the engagement is born in `TESTING` with `outcome`,
        `assessed_complexity`, and `completed_at` unset."

        Design: Corner/entities/engagement_creation_stamps_validator_and_testing
        """
        model, _doc = create_model_with_approved_doc(name="Eng M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        eng = validate_success(
            api.create_engagement(
                model["id"],
                create_engagement_payload(
                    period_start="2026-08-02T00:00:00Z", period_end="2026-08-09T00:00:00Z",
                    scope_outcomes_analysis=False,
                ),
                VALIDATOR,
            ),
            expected_status=201,
        )
        assert eng["status"] == "TESTING"
        assert eng["validator_user_id"] == "u_val"
        assert eng.get("completed_at") is None
        assert eng.get("outcome") is None

    def test_engagement_with_no_scope_selected_rejected(self, api):
        """PRD §3.4: "Independent validation begins when a `ModelValidator` opens an
        engagement against a model, choosing its scope through
        `scope_conceptual_soundness` and `scope_outcomes_analysis` — at least one of
        the two must be selected — and fixing a review window with `period_start` and
        `period_end`, where the end must be strictly after the start. Scope and period
        violations are request-shape failures (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/engagement_with_no_scope_selected_rejected
        """
        model, _doc = create_model_with_approved_doc(name="Scope M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        err = validate_error(
            api.create_engagement(
                model["id"],
                create_engagement_payload(
                    period_start="2026-08-02T00:00:00Z", period_end="2026-08-09T00:00:00Z",
                    scope_conceptual_soundness=False, scope_outcomes_analysis=False,
                ),
                VALIDATOR,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )
        assert err["error_id"] == "ERR_INVALID_REQUEST"

    def test_engagement_period_end_not_after_start_rejected(self, api):
        """PRD §3.4: "Independent validation begins when a `ModelValidator` opens an
        engagement against a model, choosing its scope through
        `scope_conceptual_soundness` and `scope_outcomes_analysis` — at least one of
        the two must be selected — and fixing a review window with `period_start` and
        `period_end`, where the end must be strictly after the start. Scope and period
        violations are request-shape failures (`ERR_INVALID_REQUEST`)."

        Equal endpoints fail the strictly-after rule too.

        Design: Corner/validations/engagement_period_end_not_after_start_rejected
        """
        model, _doc = create_model_with_approved_doc(name="Period M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        err = validate_error(
            api.create_engagement(
                model["id"],
                create_engagement_payload(
                    period_start="2026-08-09T00:00:00Z", period_end="2026-08-09T00:00:00Z",
                    scope_outcomes_analysis=False,
                ),
                VALIDATOR,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )
        assert err["error_id"] == "ERR_INVALID_REQUEST"

    def test_engagement_creation_requires_approved_documentation(self, api):
        """PRD §3.4: "Before the constraint gate, three earlier gates apply in pipeline
        order: the model must not be retired (`ERR_MODEL_ALREADY_RETIRED`), the
        validator must be independent of the owner (`ERR_SOD_VALIDATION_INDEPENDENCE`),
        and the model must have at least one `APPROVED` documentation package
        (`ERR_NO_COMPLETED_VALIDATION`'s sibling gate, `ERR_NO_APPROVED_DOCUMENTATION`)."

        Design: Corner/validations/engagement_creation_requires_approved_documentation
        """
        model = create_model(name="NoDocEng M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        err = validate_error(
            api.create_engagement(
                model["id"],
                create_engagement_payload(
                    period_start="2026-08-02T00:00:00Z", period_end="2026-08-09T00:00:00Z",
                    scope_outcomes_analysis=False,
                ),
                VALIDATOR,
            ),
            ApiErrorId.ERR_NO_APPROVED_DOCUMENTATION,
        )
        assert err["error_id"] == "ERR_NO_APPROVED_DOCUMENTATION"


class TestEngagementStateMachine:
    def test_engagement_reopen_from_testing_returns_not_completed(self, api):
        """PRD §3.4: "Reopening — allowed only from `COMPLETED`, else
        `ERR_ENGAGEMENT_NOT_COMPLETED` — returns the engagement to `TESTING` and clears
        `completed_at` and `outcome` back to unset".

        Design: Corner/state_machines/engagement_reopen_from_testing_returns_not_completed
        """
        model, _doc = create_model_with_approved_doc(name="Reopen M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        eng = open_engagement(model["id"], period_start="2026-08-02T00:00:00Z",
                              period_end="2026-08-09T00:00:00Z", scope_outcomes_analysis=False)
        err = validate_error(api.reopen_engagement(eng["id"], VALIDATOR),
                             ApiErrorId.ERR_ENGAGEMENT_NOT_COMPLETED)
        assert err["error_id"] == "ERR_ENGAGEMENT_NOT_COMPLETED"

    def test_engagement_complete_twice_returns_not_in_testing(self, api):
        """PRD §3.4: "Completing an engagement — allowed only while it is in `TESTING`,
        else `ERR_ENGAGEMENT_NOT_IN_TESTING` — records the validator's `outcome` (one
        of `EFFECTIVE`, `EFFECTIVE_WITH_FINDINGS`, or `INEFFECTIVE`) and
        `assessed_complexity` (`LOW`, `MEDIUM`, or `HIGH`), stamps `completed_at` with
        the logical-clock now, and moves the engagement to `COMPLETED`."

        Design: Corner/state_machines/engagement_complete_twice_returns_not_in_testing
        """
        model, _doc = create_model_with_approved_doc(name="Comp M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        eng = open_engagement(model["id"], period_start="2026-08-02T00:00:00Z",
                              period_end="2026-08-09T00:00:00Z", scope_outcomes_analysis=False)
        complete_engagement(eng["id"], outcome="EFFECTIVE", assessed_complexity="LOW")
        err = validate_error(
            api.complete_engagement(eng["id"], {"outcome": "INEFFECTIVE", "assessed_complexity": "HIGH"},
                                    VALIDATOR),
            ApiErrorId.ERR_ENGAGEMENT_NOT_IN_TESTING,
        )
        assert err["error_id"] == "ERR_ENGAGEMENT_NOT_IN_TESTING"
        engs, _ = validate_paginated(api.list_engagements(model["id"], OFFICER))
        assert engs[0]["outcome"] == "EFFECTIVE", "the first completion stands"


class TestEngagementRetestCycle:
    def test_reopen_clears_completion_fields_without_reverting_model(self, api):
        """PRD §3.4: "Reopening — allowed only from `COMPLETED`, else
        `ERR_ENGAGEMENT_NOT_COMPLETED` — returns the engagement to `TESTING` and clears
        `completed_at` and `outcome` back to unset, but deliberately does not revert
        the model: `last_validated_at`, `assessed_complexity`, and the derived
        `risk_score` all remain as the last completion left them."

        LOW/SINGLE_DESK/100 -> 30; completed with assessed MEDIUM -> 25*2 + 10*0 + 10*1
        = 60, TIER_2; reopening must not revert that.

        Design: Difficulty/non_linear_state_machine/validation_engagement_reopen_cycle_retest
        """
        model, _doc = create_model_with_approved_doc(name="Retest M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        eng = open_engagement(model["id"], period_start="2026-08-02T00:00:00Z",
                              period_end="2026-08-10T00:00:00Z", scope_outcomes_analysis=False)
        complete_engagement(eng["id"], outcome="EFFECTIVE_WITH_FINDINGS", assessed_complexity="MEDIUM")
        mid = get_model(model["id"])
        assert mid["risk_score"] == 60 and mid["risk_tier"] == "TIER_2"

        reopened = validate_success(api.reopen_engagement(eng["id"], VALIDATOR))
        assert reopened["status"] == "TESTING"
        assert reopened.get("completed_at") is None
        assert reopened.get("outcome") is None
        after = get_model(model["id"])
        assert after["risk_score"] == 60, "reopen deliberately does not revert the model"
        assert after["assessed_complexity"] == "MEDIUM"
        assert after.get("last_validated_at") is not None

    def test_second_completion_after_reopen_recomputes_model(self, api):
        """PRD §3.4: "Retesting is a first-class cycle rather than an exception."
        PRD §3.4: "Completion ripples into the model: the model's `assessed_complexity`
        takes the engagement's value, `last_validated_at` becomes the completion
        timestamp, `risk_score` is recomputed under the validator-assessed variant of
        §3.1, `risk_tier` is re-derived, and `validation_due_at` is reset to the
        completion time plus the new tier's revalidation interval."

        TESTING -> COMPLETED -> TESTING -> COMPLETED on one engagement: the second
        completion with assessed LOW yields 25*1 + 10*0 + 10*1 = 35, TIER_3.

        Design: Difficulty/non_linear_state_machine/validation_engagement_reopen_cycle_retest
        """
        model, _doc = create_model_with_approved_doc(name="Retest M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        eng = open_engagement(model["id"], period_start="2026-08-02T00:00:00Z",
                              period_end="2026-08-10T00:00:00Z", scope_outcomes_analysis=False)
        first = complete_engagement(eng["id"], outcome="EFFECTIVE_WITH_FINDINGS",
                                    assessed_complexity="MEDIUM")
        assert first["status"] == "COMPLETED"
        validate_success(api.reopen_engagement(eng["id"], VALIDATOR))
        second = validate_success(
            api.complete_engagement(eng["id"], {"outcome": "EFFECTIVE", "assessed_complexity": "LOW"},
                                    VALIDATOR)
        )
        assert second["status"] == "COMPLETED", "the cycle looped back to COMPLETED"
        data = get_model(model["id"])
        assert data["risk_score"] == 35, f"expected 25*1 + 10*0 + 10*1 = 35, got {data['risk_score']}"
        assert data["risk_tier"] == "TIER_3"
        assert data["assessed_complexity"] == "LOW"


class TestEngagementWindowOverlap:
    def test_adjacent_window_start_equals_end_allowed(self, api):
        """PRD §3.4: "Review windows are treated as half-open intervals: a window
        includes its `period_start` and excludes its `period_end`, so a new engagement
        whose start exactly equals an existing engagement's end does not overlap it;
        any true overlap with another engagement of the same model is rejected with
        `ERR_VALIDATION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/engagement_windows_half_open_adjacency_allowed
        """
        model, _doc = create_model_with_approved_doc(name="Overlap M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        open_engagement(model["id"], period_start="2026-08-02T00:00:00Z",
                        period_end="2026-08-10T00:00:00Z")
        adjacent = validate_success(
            api.create_engagement(
                model["id"],
                create_engagement_payload(
                    period_start="2026-08-10T00:00:00Z", period_end="2026-08-20T00:00:00Z",
                    scope_conceptual_soundness=False, scope_outcomes_analysis=True,
                ),
                VALIDATOR,
            ),
            expected_status=201,
        )
        assert adjacent["id"], "start == existing end is allowed under half-open semantics"

    def test_window_one_second_into_existing_rejected(self, api):
        """PRD §3.4: "Review windows are treated as half-open intervals: a window
        includes its `period_start` and excludes its `period_end`, so a new engagement
        whose start exactly equals an existing engagement's end does not overlap it;
        any true overlap with another engagement of the same model is rejected with
        `ERR_VALIDATION_WINDOW_OVERLAP`."

        Start one second before the existing window's end falls inside
        [2026-08-02, 2026-08-10) and is rejected.

        Design: Difficulty/resource_temporal_overlap/engagement_windows_half_open_adjacency_allowed
        """
        model, _doc = create_model_with_approved_doc(name="Overlap M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        open_engagement(model["id"], period_start="2026-08-02T00:00:00Z",
                        period_end="2026-08-10T00:00:00Z")
        err = validate_error(
            api.create_engagement(
                model["id"],
                create_engagement_payload(
                    period_start="2026-08-09T23:59:59Z", period_end="2026-08-21T00:00:00Z",
                    scope_conceptual_soundness=True, scope_outcomes_analysis=False,
                ),
                VALIDATOR,
            ),
            ApiErrorId.ERR_VALIDATION_WINDOW_OVERLAP,
        )
        assert err["error_id"] == "ERR_VALIDATION_WINDOW_OVERLAP"


class TestEngagementGatePriority:
    def test_engagement_on_retired_model_reports_state_error(self, api):
        """PRD §3.4: "Before the constraint gate, three earlier gates apply in pipeline
        order: the model must not be retired (`ERR_MODEL_ALREADY_RETIRED`), the
        validator must be independent of the owner (`ERR_SOD_VALIDATION_INDEPENDENCE`),
        and the model must have at least one `APPROVED` documentation package
        (`ERR_NO_COMPLETED_VALIDATION`'s sibling gate, `ERR_NO_APPROVED_DOCUMENTATION`)."

        A request that both targets a RETIRED model and overlaps an existing window
        must surface ERR_MODEL_ALREADY_RETIRED.

        Design: Difficulty/priority_pair_validation_conflict/engagement_create_state_beats_window_overlap
        """
        retired, _replacement = create_retired_pair()
        err = validate_error(
            api.create_engagement(
                retired["id"],
                create_engagement_payload(
                    period_start="2026-08-05T00:00:00Z", period_end="2026-08-15T00:00:00Z",
                    scope_conceptual_soundness=True, scope_outcomes_analysis=False,
                ),
                VALIDATOR,
            ),
            ApiErrorId.ERR_MODEL_ALREADY_RETIRED,
        )
        assert err["error_id"] == "ERR_MODEL_ALREADY_RETIRED"

    def test_retired_state_masks_window_overlap_conflict(self, api):
        """PRD §2.8: "Every request passes through a fixed pipeline of validation
        stages, and a rejection at an earlier stage masks every later stage — the
        caller always sees the earliest applicable error."
        PRD §3.4: "Before the constraint gate, three earlier gates apply in pipeline
        order: the model must not be retired (`ERR_MODEL_ALREADY_RETIRED`), the
        validator must be independent of the owner (`ERR_SOD_VALIDATION_INDEPENDENCE`),
        and the model must have at least one `APPROVED` documentation package
        (`ERR_NO_COMPLETED_VALIDATION`'s sibling gate, `ERR_NO_APPROVED_DOCUMENTATION`)."

        The retired model's existing engagement window [2026-08-01, 2026-08-01T06:00)
        overlaps the requested [2026-08-01, 2026-08-05), yet the reported error is the
        state error, never ERR_VALIDATION_WINDOW_OVERLAP, and no engagement is created.

        Design: Difficulty/priority_pair_validation_conflict/engagement_create_state_beats_window_overlap
        """
        retired, _replacement = create_retired_pair()
        resp = api.create_engagement(
            retired["id"],
            create_engagement_payload(
                period_start="2026-08-01T00:00:00Z", period_end="2026-08-05T00:00:00Z",
                scope_conceptual_soundness=True, scope_outcomes_analysis=False,
            ),
            VALIDATOR,
        )
        err = validate_error(resp, ApiErrorId.ERR_MODEL_ALREADY_RETIRED)
        assert err["error_id"] == "ERR_MODEL_ALREADY_RETIRED"
        assert err["error_id"] != "ERR_VALIDATION_WINDOW_OVERLAP"
        engs, _ = validate_paginated(api.list_engagements(retired["id"], OFFICER))
        assert len(engs) == 1, "the rejected request must not persist an engagement"
