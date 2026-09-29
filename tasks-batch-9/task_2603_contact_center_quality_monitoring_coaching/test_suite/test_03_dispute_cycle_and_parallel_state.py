"""Two non-linear shapes on the same rows: the dispute information loop that
re-enters a state it has already left, and the evaluation that carries two
state dimensions moving independently."""
from test_helpers import (
    ApiErrorId,
    assert_parallel_state,
    assert_scores,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)


class TestDisputeInformationLoop:
    """The dispute cycles back to the agent, and the counter — not the state
    graph — is what finally stops it."""

    @staticmethod
    def _one_information_round(api, env) -> None:
        """One accepted round: the reviewer asks, the agent answers."""
        fx.resolve_dispute(
            api,
            env.dispute["id"],
            env.reviewer["id"],
            "NEEDS_MORE_INFO",
            outcome_note="Quote the customer's confirmation.",
        )
        fx.respond_dispute(
            api,
            env.dispute["id"],
            env.agent["id"],
            additional_rationale="At 08:42 the customer said the issue was solved.",
        )

    def test_the_second_pickup_exhausts_the_counter_and_the_next_request_is_refused(self, api):
        """Two pickups take round_count to two, and no further round may open.

        PRD: "An outcome of `NEEDS_MORE_INFO` sends the dispute back to the agent
        for more detail."
        PRD: "it is rejected with `ERR_DISPUTE_ROUND_LIMIT` when `round_count` has
        already reached two, since no further round may be opened."

        Design: Difficulty/non_linear_state_machine/cyclic_dispute_needs_more_info_round_limit
        """
        env = fx.under_review_dispute_env(api)
        assert env.dispute["round_count"] == 1

        self._one_information_round(api, env)
        second_pickup = fx.review_dispute(api, env.dispute["id"], env.reviewer["id"])
        assert second_pickup["round_count"] == 2
        assert second_pickup["status"] == "UNDER_REVIEW"

        response = api.resolve_dispute(
            env.dispute["id"],
            f.resolve_payload("NEEDS_MORE_INFO", outcome_note="One more clarification."),
            fx.make_evaluator_headers(env.reviewer["id"]),
        )

        validate_error(response, ApiErrorId.DISPUTE_ROUND_LIMIT.value, 422)
        after = fx.read_dispute(api, env.dispute["id"])
        assert after["round_count"] == 2
        assert after["status"] == "UNDER_REVIEW"
        assert_parallel_state(
            fx.read_evaluation(api, env.evaluation["id"]), "SUBMITTED", "DISPUTED"
        )

    def test_the_exhausted_dispute_can_still_be_settled_without_leaving_the_graph(self, api):
        """The counter stops the loop; it does not strand the dispute.

        PRD: "The dispute must be `UNDER_REVIEW`, else
        `ERR_DISPUTE_NOT_RESOLVABLE`, and the acting `X-User-ID` must equal the
        dispute's recorded `reviewer_evaluator_id`, else `ERR_NOT_RESOURCE_OWNER`;
        the segregation-of-duties check applies here as well."

        Design: Difficulty/non_linear_state_machine/cyclic_dispute_needs_more_info_round_limit
        """
        env = fx.under_review_dispute_env(api)
        self._one_information_round(api, env)
        fx.review_dispute(api, env.dispute["id"], env.reviewer["id"])
        validate_error(
            api.resolve_dispute(
                env.dispute["id"],
                f.resolve_payload("NEEDS_MORE_INFO", outcome_note="One more clarification."),
                fx.make_evaluator_headers(env.reviewer["id"]),
            ),
            ApiErrorId.DISPUTE_ROUND_LIMIT.value,
            422,
        )

        settled = fx.resolve_dispute(
            api,
            env.dispute["id"],
            env.reviewer["id"],
            "REJECTED",
            outcome_note="The confirmation does not cover the disputed behaviour.",
        )

        assert settled["status"] == "REJECTED"
        assert settled["round_count"] == 2

    def test_an_information_request_may_not_carry_a_replacement_scorecard(self, api):
        """Asking for detail and supplying scores at once is malformed.

        PRD: "It requires `adjusted_item_scores` to be absent — supplying scores
        alongside a request for information is a malformed request and answers
        `ERR_INVALID_REQUEST`"

        Design: Difficulty/non_linear_state_machine/cyclic_dispute_needs_more_info_round_limit
        """
        env = fx.under_review_dispute_env(api)

        response = api.resolve_dispute(
            env.dispute["id"],
            f.resolve_payload(
                "NEEDS_MORE_INFO",
                outcome_note="Quote the customer's confirmation.",
                adjusted_item_scores=f.HIGH_ITEM_SCORES_93,
            ),
            fx.make_evaluator_headers(env.reviewer["id"]),
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST.value)
        unchanged = fx.read_dispute(api, env.dispute["id"])
        assert unchanged["status"] == "UNDER_REVIEW"
        assert unchanged["adjusted_item_scores"] is None
        assert unchanged["round_count"] == 1

    def test_the_loop_returns_the_dispute_to_a_state_it_has_already_left(self, api):
        """SUBMITTED is re-entered, and responding does not spend a round.

        PRD: "Responding to an information request belongs to the `Agent` and
        moves the dispute `NEEDS_MORE_INFO → SUBMITTED`."
        PRD: "`reviewer_evaluator_id` is cleared to null, freeing the next round
        to be picked up by any other evaluator, and `round_count` is deliberately
        left unchanged by this transition — only a fresh pickup counts as a new
        round."

        Design: Difficulty/non_linear_state_machine/cyclic_dispute_needs_more_info_round_limit
        """
        env = fx.under_review_dispute_env(api)

        asked = fx.resolve_dispute(
            api,
            env.dispute["id"],
            env.reviewer["id"],
            "NEEDS_MORE_INFO",
            outcome_note="Quote the customer's confirmation.",
        )
        assert asked["status"] == "NEEDS_MORE_INFO"
        assert asked["reviewer_evaluator_id"] == env.reviewer["id"]
        assert asked["round_count"] == 1

        answered = fx.respond_dispute(
            api,
            env.dispute["id"],
            env.agent["id"],
            additional_rationale="Follow-up ticket TCK-5512.",
        )
        assert answered["status"] == "SUBMITTED"
        assert answered["reviewer_evaluator_id"] is None
        assert answered["round_count"] == 1
        assert answered["rationale"].endswith(" | Follow-up ticket TCK-5512.")
        assert_parallel_state(
            fx.read_evaluation(api, env.evaluation["id"]), "SUBMITTED", "DISPUTED"
        )


class TestParallelEvaluationDimensions:
    """One evaluation row, two state dimensions, and a combined state no single
    linear machine can express."""

    #: The adjusted cover an upheld dispute installs: DISCLOSE drops to four
    #: points while the not-applicable behaviour stays out of the denominator.
    ADJUSTED_SCORES = {"DISCLOSE": 4, "GREET": 4, "RESOLVE": 3, "SURVEY": "NA"}

    def test_filing_a_dispute_moves_only_the_feedback_dimension(self, api):
        """The feedback dimension advances twice while review stays put.

        PRD: "These two status fields form a **parallel state machine**:
        `review_status` moves through `DRAFT`, `SUBMITTED`, `FINALIZED` and
        `REOPENED` under the evaluator's scoring actions, while `feedback_status`
        moves through `PENDING`, `DELIVERED`, `ACKNOWLEDGED` and `DISPUTED` under
        the agent-facing actions of §3.6, and the two advance independently on the
        same row."
        PRD: "The evaluation's `feedback_status` moves to `DISPUTED` and its
        `version` is incremented."

        Design: Difficulty/non_linear_state_machine/parallel_evaluation_review_and_feedback_dimensions_move_independently
        """
        env = fx.delivered_evaluation_env(api, item_scores=f.NA_ITEM_SCORES)
        assert_parallel_state(env.evaluation, "SUBMITTED", "DELIVERED")

        env.reviewer = fx.create_evaluator(api, full_name="Ravi Reviewer")
        fx.file_dispute(
            api,
            env.evaluation["id"],
            env.agent["id"],
            env.evaluation["version"],
            disputed_behavior_codes=["DISCLOSE"],
            rationale="The disclosure was read at 00:12 of the recording.",
        )

        mid = fx.read_evaluation(api, env.evaluation["id"])
        assert_parallel_state(mid, "SUBMITTED", "DISPUTED")
        assert_scores(mid, weighted_score=78.82, adjusted_weighted_score=None)
        assert mid["feedback_delivered_at"] is not None

    def test_upholding_pushes_the_two_dimensions_in_opposite_directions(self, api):
        """Review advances to REOPENED while feedback falls back to PENDING.

        PRD: "**Hop one:** because the dispute was upheld, the evaluation's
        `adjusted_weighted_score` is computed as the renormalised weighted score
        over `adjusted_item_scores`, `compliance_result` is recomputed from those
        adjusted scores by the same step-five verdict rule of §3.5, `review_status`
        moves to `REOPENED`, `feedback_status` moves to `PENDING` and
        `feedback_delivered_at` is cleared to null — the adjusted score must be
        delivered again before it can be acknowledged or disputed."
        PRD: "A row may legitimately sit at `FINALIZED` on the review dimension
        while sitting at `DISPUTED` on the feedback dimension, or at `REOPENED`
        while back at `PENDING`."

        Design: Difficulty/non_linear_state_machine/parallel_evaluation_review_and_feedback_dimensions_move_independently
        """
        env = fx.under_review_dispute_env(
            api, item_scores=f.NA_ITEM_SCORES, disputed_behavior_codes=["DISCLOSE"]
        )

        dispute = fx.resolve_dispute(
            api,
            env.dispute["id"],
            env.reviewer["id"],
            "UPHELD",
            adjusted_item_scores=self.ADJUSTED_SCORES,
            outcome_note="Partial credit restored on the disclosure.",
        )

        assert dispute["status"] == "UPHELD"
        assert dispute["round_count"] == 1
        evaluation = fx.read_evaluation(api, env.evaluation["id"])
        assert_parallel_state(evaluation, "REOPENED", "PENDING")
        # 24.00 + 16.00 + 21.00 = 61.00 over an applicable weight of 85.00.
        assert_scores(
            evaluation,
            weighted_score=78.82,
            adjusted_weighted_score=71.76,
            compliance_result="PASS",
        )
        assert evaluation["feedback_delivered_at"] is None

    def test_rescoring_a_reopened_row_advances_review_and_leaves_feedback_alone(self, api):
        """The fresh score supersedes the adjustment and clears it.

        PRD: "Re-scoring after an upheld dispute runs the same machinery from a
        different origin. The `REOPENED → SUBMITTED` transition carries the
        identical precondition list, with the difference that the underlying
        selection is expected to be `EVALUATED` rather than `ASSIGNED`, and the
        identical ordered side effects, with two differences: step three is a
        no-op because the selection is already `EVALUATED`, and
        `adjusted_weighted_score` is reset to null because the fresh score
        supersedes the dispute's adjustment."
        PRD: "**Step two:** `review_status` becomes `SUBMITTED` and `submitted_at`
        takes the current logical-clock instant; `feedback_status` is untouched and
        stays `PENDING`."

        Design: Difficulty/non_linear_state_machine/parallel_evaluation_review_and_feedback_dimensions_move_independently
        """
        env = fx.under_review_dispute_env(
            api, item_scores=f.NA_ITEM_SCORES, disputed_behavior_codes=["DISCLOSE"]
        )
        fx.resolve_dispute(
            api,
            env.dispute["id"],
            env.reviewer["id"],
            "UPHELD",
            adjusted_item_scores=self.ADJUSTED_SCORES,
            outcome_note="Partial credit restored on the disclosure.",
        )
        assert fx.read_selection(api, env.selection["id"])["status"] == "EVALUATED"

        rescored = validate_success(
            api.submit_evaluation(
                env.evaluation["id"],
                f.submit_payload(f.PASSING_ITEM_SCORES),
                fx.make_evaluator_headers(env.evaluator["id"]),
            )
        )

        assert_parallel_state(rescored, "SUBMITTED", "PENDING")
        assert_scores(
            rescored,
            weighted_score=82.00,
            raw_weighted_score=82.00,
            adjusted_weighted_score=None,
            compliance_result="PASS",
        )
        assert fx.read_selection(api, env.selection["id"])["status"] == "EVALUATED"
