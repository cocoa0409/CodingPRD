"""Boundary precision on the thresholds PRD §2.6 declares inclusivity for.

Four separate boundaries are exercised here, each with the on-boundary case and
the case one indivisible step across it: the inclusive `AMBER` floor of the
health tier, the inclusive capacity admission test, the strict variance
tolerance of forecast reconciliation, and the empty-input-set edge of the
outcome attainment index.
"""

from typing import Any, Dict

from test_helpers import (
    ASSIGNMENT_COMMITTED,
    ASSIGNMENT_QUEUED,
    CS_STATE_SUBMITTED,
    FINANCE_STATE_RECONCILED,
    FINANCE_STATE_VARIANCE_FLAGGED,
    GOAL_IN_PROGRESS,
    GOAL_WAIVED,
    HEALTH_AMBER,
    HEALTH_RED,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    RECONCILE_ACTION_RECONCILE,
    TIER_HIGH_TOUCH,
    ApiClient,
    add_buyer_sponsor,
    add_outcome_goal,
    add_usage_signal,
    assert_capacity_conserved,
    assert_cents,
    assert_field,
    assert_fields,
    assert_score,
    assert_scores,
    build_roster_and_account,
    build_submitted_forecast,
    build_trending_account,
    open_coverage,
    read_account,
    read_csm,
    read_goal,
    recompute_health,
    reconcile_forecast,
    record_goal_progress,
)

State = Dict[str, Any]


def _account_at_the_amber_floor(api: ApiClient) -> State:
    """An account whose `snapshot_health_score` lands on exactly 50.00.

    One usage period of 40 weekly active users against 100 licensed seats and a
    `feature_depth_pct` of 40.00 gives a `usage_row_index` of 40.00; an active
    `CXO` economic buyer with no engagements gives an `exec_engagement_score` of
    50.00; no support ticket leaves the support component at 100.00; and one
    goal at 14 against a target of 100 gives an `outcome_attainment_index` of
    14.00. The weighted sum is 14.00 + 25.00 + 7.50 + 3.50 = 50.00.
    """
    state = build_roster_and_account(api)
    add_usage_signal(
        api, state["account_id"], state["csm_id"], "2026-07-31", 40, 100, 40.00
    )
    state = add_buyer_sponsor(api, state)
    goal = add_outcome_goal(
        api, state["account_id"], state["csm_id"], 10_000, 100, actual_value=14
    )
    state["goal"] = goal
    state["goal_id"] = goal["id"]
    state["account"] = read_account(api, state["account_id"])
    return state


def _amber_account_with_coverage(api: ApiClient, capacity_units_total: int) -> State:
    """A `HIGH_TOUCH`, `ENTERPRISE`, `AMBER` account staffed by one manager.

    The three rising usage periods leave the newest `usage_row_index` at 86.00
    and `snapshot_health_score` at 73.85, so the account is `AMBER`; at
    30,000,000 cents it segments to `HIGH_TOUCH` and its assignment costs 17
    units. The manager's `capacity_units_total` is the only input that varies.
    """
    state = build_trending_account(api, capacity_units_total=capacity_units_total)
    return open_coverage(api, state)


def _account_with_one_live_goal(api: ApiClient) -> State:
    """A trending account carrying exactly one non-waived outcome goal.

    The goal takes the full 10,000 basis points at 14 against a target of 100,
    so `outcome_attainment_index` is 14.00 while the goal is live.
    """
    state = build_trending_account(api)
    goal = add_outcome_goal(
        api, state["account_id"], state["csm_id"], 10_000, 100, actual_value=14
    )
    state["goal"] = goal
    state["goal_id"] = goal["id"]
    state["account"] = read_account(api, state["account_id"])
    return state


def _submitted_forecast_at_twenty_one_million(api: ApiClient) -> State:
    """A submitted forecast whose bottom-up CS number is 21,000,000 cents.

    The account is `UPSIDE` at 30,000,000 cents of revenue, so the bottom-up
    method yields 30,000,000 × 0.70 = 21,000,000 cents, and five percent of that
    number is exactly 1,050,000 cents.
    """
    state = build_submitted_forecast(api, fiscal_period="2026Q4")
    forecast = state["forecast"]
    assert_cents(forecast["cs_amount_cents"], 21_000_000, "cs_amount_cents")
    assert_field(forecast, "cs_state", CS_STATE_SUBMITTED)
    return state


class TestHealthTierAmberFloor:
    """The `AMBER` floor of PRD §3.2 is an inclusive lower bound at 50.00."""

    def test_snapshot_health_score_of_exactly_fifty_is_amber(self, api: ApiClient):
        """A snapshot score sitting exactly on the floor tiers AMBER, not RED.

        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."
        PRD §3.2: "`health_tier` is derived from `snapshot_health_score` **only**: the tier is `RED` when `snapshot_health_score` is below 50.00, `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at least 75.00."
        PRD §3.2: "Both floors are inclusive lower bounds, so exactly 50.00 is `AMBER` rather than `RED` and exactly 75.00 is `GREEN` rather than `AMBER`."
        PRD §3.3: "Each goal's `attainment_pct` is its `actual_value` divided by its `target_value`, multiplied by 100, capped at 100.00, and rounded half up to two decimal places."

        Design: Difficulty/boundary_precision_check/health_tier_floor_is_inclusive_at_exactly_fifty
        """
        state = _account_at_the_amber_floor(api)
        account = state["account"]

        assert_scores(
            account,
            {
                "adoption_index": 40.00,
                "support_risk_penalty": 0.00,
                "exec_engagement_score": 50.00,
                "outcome_attainment_index": 14.00,
                "snapshot_health_score": 50.00,
            },
        )
        assert_field(account, "health_tier", HEALTH_AMBER)

    def test_one_point_of_attainment_below_the_floor_tiers_red(self, api: ApiClient):
        """Dropping the attainment to 13.00 puts the snapshot at 49.75 and RED.

        PRD §3.3: "Supplying `IN_PROGRESS` carries the goal `DEFINED → IN_PROGRESS` or, when it is already there, `IN_PROGRESS → IN_PROGRESS` as a repeatable update; either form requires that the account's `lifecycle_state` be neither `CHURNED` nor `ARCHIVED`, stores the supplied `actual_value`, recomputes `attainment_pct`, and then recomputes the account's `outcome_attainment_index` and both health variants."
        PRD §3.3: "Each goal's `attainment_pct` is its `actual_value` divided by its `target_value`, multiplied by 100, capped at 100.00, and rounded half up to two decimal places."
        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."
        PRD §3.2: "`health_tier` is derived from `snapshot_health_score` **only**: the tier is `RED` when `snapshot_health_score` is below 50.00, `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at least 75.00."

        Design: Difficulty/boundary_precision_check/health_tier_floor_is_inclusive_at_exactly_fifty
        """
        state = _account_at_the_amber_floor(api)
        assert_score(
            state["account"]["snapshot_health_score"], 50.00, "snapshot_health_score"
        )

        record_goal_progress(
            api, state["goal_id"], state["csm_id"], GOAL_IN_PROGRESS, actual_value=13
        )

        goal = read_goal(api, state["account_id"], state["goal_id"])
        assert_field(goal, "status", GOAL_IN_PROGRESS)
        assert_score(goal["attainment_pct"], 13.00, "attainment_pct")

        account = read_account(api, state["account_id"])
        assert_scores(
            account,
            {
                "outcome_attainment_index": 13.00,
                "snapshot_health_score": 49.75,
            },
        )
        assert_field(account, "health_tier", HEALTH_RED)


class TestCoverageAdmissionCapacityBoundary:
    """The admission test of PRD §3.4 compares available capacity inclusively."""

    def test_an_exact_capacity_fit_is_admitted_and_leaves_zero_available(
        self, api: ApiClient
    ):
        """17 units of capacity admit a 17-unit assignment and land on 0 available.

        PRD §3.4: "The single ceiling is load-bearing: a `HIGH_TOUCH`, `ENTERPRISE`, `AMBER` account at 30,000,000 cents gives 9 × 1.50 × 1.10 = 14.85, plus a surcharge of 2, giving 16.85, whose ceiling is `load_units` 17 — whereas taking a ceiling of the 13.50 sub-product before applying the risk multiplier would give 18, a different and incorrect cost."
        PRD §3.4: "The test admits the row to `COMMITTED` when the chosen manager's `status` is `ACTIVE` and their `capacity_units_total` minus `capacity_units_committed` is greater than or equal to the assignment's `load_units`; the comparison is inclusive, so an exact fit is admitted and `capacity_units_available` may legitimately reach exactly 0."
        PRD §3.4: "On admission the manager's `capacity_units_committed` rises by the assignment's `load_units`, `capacity_units_available` is recomputed, the assignment's `committed_at` is stamped with the logical clock, the account's `assigned_csm_id` is set to the assignment's `csm_id`, and `coverage_posture` is re-derived — which is how an otherwise clean account finally reaches `OPEN`."

        Design: Difficulty/boundary_precision_check/csm_capacity_admission_accepts_an_exact_fit_and_queues_one_unit_short
        """
        state = _amber_account_with_coverage(api, capacity_units_total=17)

        assert_field(state["account"], "health_tier", HEALTH_AMBER)
        assert_field(state["account"], "coverage_tier", TIER_HIGH_TOUCH)

        assignment = state["assignment"]
        assert_field(assignment, "load_units", 17)
        assert_field(assignment, "state", ASSIGNMENT_COMMITTED)

        csm = read_csm(api, state["csm_id"])
        assert_fields(
            csm,
            {
                "capacity_units_total": 17,
                "capacity_units_committed": 17,
                "capacity_units_available": 0,
            },
        )
        assert_capacity_conserved(csm)

        account = read_account(api, state["account_id"])
        assert_field(account, "assigned_csm_id", state["csm_id"])
        assert_field(account, "coverage_posture", POSTURE_OPEN)

    def test_one_unit_short_of_the_load_leaves_the_assignment_queued(
        self, api: ApiClient
    ):
        """16 units of capacity refuse the same 17-unit load and move no counter.

        PRD §3.4: "The test admits the row to `COMMITTED` when the chosen manager's `status` is `ACTIVE` and their `capacity_units_total` minus `capacity_units_committed` is greater than or equal to the assignment's `load_units`; the comparison is inclusive, so an exact fit is admitted and `capacity_units_available` may legitimately reach exactly 0."
        PRD §3.4: "When the capacity does not fit, the row simply **stays** in `QUEUED`; an over-capacity assignment is not an error, and no counter moves."
        PRD §2.8: "Otherwise, if `open_save_play_count` is greater than zero, **or** at least one escalation case of the account is in state `OPEN`, `COMMITTED` or `DISPUTED`, **or** the account has no coverage assignment in state `COMMITTED`, the posture is `RESTRICTED`."

        Design: Difficulty/boundary_precision_check/csm_capacity_admission_accepts_an_exact_fit_and_queues_one_unit_short
        """
        state = _amber_account_with_coverage(api, capacity_units_total=16)

        assignment = state["assignment"]
        assert_field(assignment, "load_units", 17)
        assert_field(assignment, "state", ASSIGNMENT_QUEUED)

        csm = read_csm(api, state["csm_id"])
        assert_fields(
            csm,
            {
                "capacity_units_total": 16,
                "capacity_units_committed": 0,
                "capacity_units_available": 16,
            },
        )
        assert_capacity_conserved(csm)

        account = read_account(api, state["account_id"])
        assert_field(account, "assigned_csm_id", None)
        assert_field(account, "coverage_posture", POSTURE_RESTRICTED)


class TestForecastVarianceTolerance:
    """The variance tolerance of PRD §3.6 is a strict cross-multiplied test."""

    def test_a_variance_of_exactly_five_percent_reconciles(self, api: ApiClient):
        """A variance whose cross-product equals the tolerance product reconciles.

        PRD §3.6: "When `cs_amount_cents` is omitted it is computed bottom up as the CS organisation's own number: the account's `arr_cents` multiplied by the likelihood weight for the snapshotted `likelihood_category` — 0.95 for `COMMIT`, 0.70 for `UPSIDE`, 0.35 for `AT_RISK` and 0.00 for `OMIT` — rounded half up to whole cents."
        PRD §3.6: "It establishes `finance_amount_cents` from the request, or from the top-down segment method when the field is omitted, sets `variance_cents` to `finance_amount_cents` minus `cs_amount_cents` — keeping its sign, so an under-call by finance is negative — and stamps `reconciled_at` with the logical clock."
        PRD §3.6: "The variance is then judged against a tolerance of 500 basis points of the CS number, tested purely in integers by cross-multiplication so that no division or floating point is involved: when the absolute value of `variance_cents` multiplied by 10,000 is **strictly greater** than 500 multiplied by `cs_amount_cents`, `finance_state` becomes `VARIANCE_FLAGGED`; otherwise it becomes `RECONCILED`."
        PRD §3.6: "A variance of exactly five percent of the CS number reconciles."

        Design: Difficulty/boundary_precision_check/variance_tolerance_uses_strict_greater_than_at_exactly_five_percent
        """
        state = _submitted_forecast_at_twenty_one_million(api)

        forecast = reconcile_forecast(
            api,
            state["forecast_id"],
            RECONCILE_ACTION_RECONCILE,
            finance_amount_cents=22_050_000,
        )

        assert_cents(
            forecast["finance_amount_cents"], 22_050_000, "finance_amount_cents"
        )
        assert_cents(forecast["variance_cents"], 1_050_000, "variance_cents")
        assert_field(forecast, "finance_state", FINANCE_STATE_RECONCILED)
        assert_field(forecast, "cs_state", CS_STATE_SUBMITTED)

    def test_one_cent_beyond_five_percent_flags_the_variance(self, api: ApiClient):
        """One cent past the tolerance product flags the finance axis instead.

        PRD §3.6: "The variance is then judged against a tolerance of 500 basis points of the CS number, tested purely in integers by cross-multiplication so that no division or floating point is involved: when the absolute value of `variance_cents` multiplied by 10,000 is **strictly greater** than 500 multiplied by `cs_amount_cents`, `finance_state` becomes `VARIANCE_FLAGGED`; otherwise it becomes `RECONCILED`."
        PRD §3.6: "It establishes `finance_amount_cents` from the request, or from the top-down segment method when the field is omitted, sets `variance_cents` to `finance_amount_cents` minus `cs_amount_cents` — keeping its sign, so an under-call by finance is negative — and stamps `reconciled_at` with the logical clock."
        PRD §3.6: "Note the shape this leaves in between: a row may legitimately rest at `cs_state` `SUBMITTED` with `finance_state` `VARIANCE_FLAGGED` indefinitely, because the finance axis cannot force the CS axis to move."

        Design: Difficulty/boundary_precision_check/variance_tolerance_uses_strict_greater_than_at_exactly_five_percent
        """
        state = _submitted_forecast_at_twenty_one_million(api)

        forecast = reconcile_forecast(
            api,
            state["forecast_id"],
            RECONCILE_ACTION_RECONCILE,
            finance_amount_cents=22_050_001,
        )

        assert_cents(
            forecast["finance_amount_cents"], 22_050_001, "finance_amount_cents"
        )
        assert_cents(forecast["variance_cents"], 1_050_001, "variance_cents")
        assert_field(forecast, "finance_state", FINANCE_STATE_VARIANCE_FLAGGED)
        assert_field(forecast, "cs_state", CS_STATE_SUBMITTED)


class TestOutcomeIndexEmptyInputSet:
    """The empty-input-set edge of PRD §3.3 substitutes 60.00 rather than 0.00."""

    def test_waiving_the_only_goal_substitutes_sixty_for_the_empty_set(
        self, api: ApiClient
    ):
        """Waiving the last live goal empties the input set and yields 60.00.

        PRD §3.3: "Supplying `WAIVED` carries the goal `DEFINED → WAIVED` or `IN_PROGRESS → WAIVED`, again with no precondition; a waived goal leaves the attainment input set entirely, and its `weight_bp` leaves the weight denominator, which re-scores every remaining goal on the account."
        PRD §3.3: "Its input set is the account's goals whose `status` is `DEFINED`, `IN_PROGRESS`, `ATTAINED` or `MISSED`; waived goals are excluded from both the numerator and the weight denominator."
        PRD §3.3: "When the input set is empty, `outcome_attainment_index` takes the substitute value 60.00 rather than 0.00, so that an account which has simply not yet defined its goals is not punished as though it had missed them."

        Design: Difficulty/boundary_precision_check/waiving_the_last_outcome_goal_empties_the_input_set_and_substitutes_sixty
        """
        state = _account_with_one_live_goal(api)
        assert_score(
            state["account"]["outcome_attainment_index"],
            14.00,
            "outcome_attainment_index",
        )

        record_goal_progress(api, state["goal_id"], state["csm_id"], GOAL_WAIVED)

        goal = read_goal(api, state["account_id"], state["goal_id"])
        assert_field(goal, "status", GOAL_WAIVED)

        account = read_account(api, state["account_id"])
        assert_score(
            account["outcome_attainment_index"], 60.00, "outcome_attainment_index"
        )

    def test_the_substitute_lifts_both_health_variants_off_the_waived_goal(
        self, api: ApiClient
    ):
        """The 60.00 substitute, not 0.00, is what both health variants consume.

        PRD §3.3: "When the input set is empty, `outcome_attainment_index` takes the substitute value 60.00 rather than 0.00, so that an account which has simply not yet defined its goals is not punished as though it had missed them."
        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."
        PRD §3.2: "It recomputes `adoption_index`, `support_risk_penalty`, `exec_engagement_score` and `outcome_attainment_index` in that order; then both health variants; then re-derives `health_tier` from the point-in-time variant; then recomputes `renewal_likelihood`; then evaluates the lifecycle transitions that depend on health; and finally recomputes `coverage_posture`."
        PRD §3.2: "`health_tier` is derived from `snapshot_health_score` **only**: the tier is `RED` when `snapshot_health_score` is below 50.00, `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at least 75.00."

        Design: Difficulty/boundary_precision_check/waiving_the_last_outcome_goal_empties_the_input_set_and_substitutes_sixty
        """
        state = _account_with_one_live_goal(api)

        # While the single goal is live the outcome term is 14.00, so the two
        # variants read 62.35 point-in-time and 55.70 trailing.
        assert_scores(
            state["account"],
            {
                "outcome_attainment_index": 14.00,
                "snapshot_health_score": 62.35,
                "trended_health_score": 55.70,
            },
        )

        record_goal_progress(api, state["goal_id"], state["csm_id"], GOAL_WAIVED)
        account = recompute_health(api, state["account_id"])

        assert_scores(
            account,
            {
                "adoption_index": 67.00,
                "exec_engagement_score": 25.00,
                "outcome_attainment_index": 60.00,
                "snapshot_health_score": 73.85,
                "trended_health_score": 67.20,
            },
        )
        assert_field(account, "health_tier", HEALTH_AMBER)
