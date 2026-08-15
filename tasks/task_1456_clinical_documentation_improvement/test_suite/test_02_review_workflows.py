"""CDIReview lifecycle: activation guards, hold/resume cycle, close guards."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_review,
    advance_clock,
    assert_cdi_review,
    close_review,
    create_and_activate_review,
    create_case,
    create_program,
    create_provider,
    create_query,
    create_review,
    get_case,
    setup_basic_scenario,
    setup_finalized_case,
    validate_error,
    validate_success,
)


class TestActivationCaseGuard:
    def test_activate_on_final_coded_case_rejected(self, api, cdi_specialist_headers):
        """PRD §3.3: "its parent case must be in `OPEN` or `UNDER_REVIEW` (else
        `ERR_CASE_NOT_REVIEWABLE`)"

        Design: Difficulty/cross_entity_state_dependency/review_activate_requires_case_open_or_under_review
        """
        scenario = setup_finalized_case(discharge_period=1)
        review = create_review(scenario["case"]["id"])
        resp = api.activate_cdi_review(review["id"], cdi_specialist_headers)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_REVIEWABLE)

    def test_activate_on_open_case_succeeds(self, api, cdi_specialist_headers):
        """PRD §3.3: "Activation moves a review from `DRAFT` to `ACTIVE`."
        PRD §3.3: "its parent case must be in `OPEN` or `UNDER_REVIEW` (else
        `ERR_CASE_NOT_REVIEWABLE`)"

        Design: Difficulty/cross_entity_state_dependency/review_activate_requires_case_open_or_under_review
        """
        scenario = setup_basic_scenario(discharge_period=5)
        review = create_review(scenario["case"]["id"])
        activated = validate_success(
            api.activate_cdi_review(review["id"], cdi_specialist_headers)
        )
        assert_cdi_review(activated)
        assert activated["status"] == "ACTIVE"
        case = get_case(scenario["case"]["id"])
        assert case["status"] == "UNDER_REVIEW"


class TestSingleActiveReviewPerCase:
    def test_second_activate_rejected_while_first_active(self, api, cdi_specialist_headers):
        """PRD §3.3: "no other review on the same case may already be `ACTIVE`
        (else `ERR_REVIEW_ALREADY_ACTIVE`)"

        Design: Difficulty/resource_temporal_overlap/single_active_review_per_case_overlap
        """
        scenario = setup_basic_scenario(discharge_period=5)
        r1 = create_review(scenario["case"]["id"])
        r2 = create_review(scenario["case"]["id"])
        validate_success(api.activate_cdi_review(r1["id"], cdi_specialist_headers))
        resp = api.activate_cdi_review(r2["id"], cdi_specialist_headers)
        validate_error(resp, ApiErrorId.ERR_REVIEW_ALREADY_ACTIVE)

    def test_activate_after_first_closes_succeeds(self, api, cdi_specialist_headers):
        """PRD §3.3: "no other review on the same case may already be `ACTIVE`
        (else `ERR_REVIEW_ALREADY_ACTIVE`)"
        PRD §3.3: "When the last `ACTIVE` review on a case closes and no `OPEN`
        reconciliation event exists for that case, the case cascades back to
        `OPEN` with its `version` incremented."

        Design: Difficulty/resource_temporal_overlap/single_active_review_per_case_overlap
        """
        scenario = setup_basic_scenario(discharge_period=5)
        r1 = create_and_activate_review(scenario["case"]["id"])
        close_review(r1["id"], closed_reason="NO_OPPORTUNITY")
        r2 = create_review(scenario["case"]["id"])
        activated = validate_success(
            api.activate_cdi_review(r2["id"], cdi_specialist_headers)
        )
        assert activated["status"] == "ACTIVE"


class TestHoldResumeCycle:
    def test_hold_resume_cycle_returns_to_active(self, api, cdi_specialist_headers):
        """PRD §3.3: "An `ACTIVE` review may be placed `ON_HOLD` ... Resuming
        returns an `ON_HOLD` review to `ACTIVE`"
        PRD §2.4: "`version`, an integer that increments by exactly 1 on every
        modification."

        Design: Difficulty/non_linear_state_machine/cdi_review_active_hold_active_cycle
        """
        scenario = setup_basic_scenario(discharge_period=5)
        review = create_and_activate_review(scenario["case"]["id"])
        held = validate_success(api.hold_cdi_review(review["id"], cdi_specialist_headers))
        assert held["status"] == "ON_HOLD"
        resumed = validate_success(api.resume_cdi_review(review["id"], cdi_specialist_headers))
        assert resumed["status"] == "ACTIVE"
        # create (v1) -> activate (v2) -> hold (v3) -> resume (v4)
        assert resumed["version"] == 4

    def test_hold_on_hold_returns_invalid_state(self, api, cdi_specialist_headers):
        """PRD §3.3: "Any review state precondition failure on these transitions
        surfaces as `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/cdi_review_active_hold_active_cycle
        """
        scenario = setup_basic_scenario(discharge_period=5)
        review = create_and_activate_review(scenario["case"]["id"])
        validate_success(api.hold_cdi_review(review["id"], cdi_specialist_headers))
        resp = api.hold_cdi_review(review["id"], cdi_specialist_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestReviewCloseGuards:
    def test_close_blocked_by_draft_query(self, api, cdi_specialist_headers):
        """PRD §3.3: "no query of the review may remain in `DRAFT`, `SENT`, or
        `ESCALATED` status (else `ERR_UNRESOLVED_QUERY_EXISTS`)."

        Design: Corner/state_machines/cdi_review_close_blocked_by_draft_query
        """
        scenario = setup_basic_scenario(discharge_period=5)
        review = create_and_activate_review(scenario["case"]["id"])
        create_query(review["id"], scenario["provider"]["id"], scenario["policy"]["id"])
        current = validate_success(api.get_cdi_review(review["id"], cdi_specialist_headers))
        resp = api.close_cdi_review(
            review["id"],
            {"closed_reason": "NO_OPPORTUNITY",
             "expected_review_version": current["version"]},
            cdi_specialist_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_QUERY_EXISTS)
