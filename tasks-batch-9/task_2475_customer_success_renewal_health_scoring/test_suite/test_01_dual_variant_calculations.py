"""Paired derivations that the PRD keeps deliberately separate.

Three pairs are exercised here: the point-in-time and trailing health variants
over one signal stream, the bottom-up and top-down renewal amounts over one
account, and the contractual and activation time-to-value figures over one
onboarding plan. Each member of each pair is pinned independently, because an
implementation that collapses a pair into a single number passes neither.
"""

import pytest

from test_helpers import (
    ASSIGNMENT_COMMITTED,
    CODE_DATA_INTEGRATION,
    CODE_FIRST_VALUE,
    CODE_GO_LIVE,
    CODE_KICKOFF,
    CS_STATE_SUBMITTED,
    FINANCE_STATE_RECONCILED,
    FINANCE_STATE_VARIANCE_FLAGGED,
    HEALTH_AMBER,
    LIFECYCLE_ADOPTING,
    LIKELIHOOD_AT_RISK,
    LIKELIHOOD_UPSIDE,
    MILESTONE_ACTION_COMPLETE,
    MILESTONE_ACTION_WAIVE,
    MILESTONE_COMPLETED,
    MILESTONE_WAIVED,
    NEWEST_USAGE_ROW,
    OPS_ADMIN_HEADERS,
    RECONCILE_ACTION_RECONCILE,
    add_milestone,
    add_usage_signal,
    assert_cents_fields,
    assert_field,
    assert_fields,
    assert_null,
    assert_scores,
    data_of,
    factories,
    open_coverage,
    open_forecast,
    read_account,
    read_health_summary,
    read_milestone,
    reconcile_forecast,
    submit_forecast,
    transition_milestone,
)

# The onboarding plan the time-to-value tests share: four milestone codes at
# their fixed sequence positions with the due dates the plan was written to.
MILESTONE_PLAN = (
    (CODE_KICKOFF, 1, "2026-01-15"),
    (CODE_DATA_INTEGRATION, 2, "2026-02-15"),
    (CODE_FIRST_VALUE, 3, "2026-03-01"),
    (CODE_GO_LIVE, 4, "2026-03-15"),
)

# The completion dates each milestone is closed on when it is completed rather
# than waived: every one runs five days past its due date.
COMPLETION_DATES = {
    CODE_KICKOFF: "2026-01-20",
    CODE_DATA_INTEGRATION: "2026-02-20",
    CODE_FIRST_VALUE: "2026-03-05",
    CODE_GO_LIVE: "2026-03-20",
}


def _build_plan(api, state):
    """Add the four-milestone onboarding plan and return code -> id."""
    return {
        code: add_milestone(
            api, state["account_id"], state["csm_id"], sequence_index, due_date, code
        )["id"]
        for code, sequence_index, due_date in MILESTONE_PLAN
    }


def _waive(api, milestone_id):
    """Waive a milestone as CS operations."""
    return data_of(
        api.transition_milestone(
            milestone_id,
            factories.milestone_transition(MILESTONE_ACTION_WAIVE),
            OPS_ADMIN_HEADERS,
        )
    )


class TestAccountHealthVariants:
    """Both health variants read one signal stream through different adoption terms."""

    def test_three_rising_usage_rows_split_the_two_health_variants(
        self, api, clock, trending_account
    ):
        """Newest-row adoption gives 73.85 while the trailing mean gives 67.20.

        PRD §3.2: "`usage_row_index` blends utilisation and breadth: 0.60 of `seat_utilisation_pct` plus 0.40 of `feature_depth_pct`, rounded half up to two decimal places."
        PRD §3.2: "`adoption_index` is the sum of each row's `usage_row_index` multiplied by its weight, divided by the sum of **only the weights actually used**, rounded half up to two decimal places once after the division."
        PRD §3.2: "For the point-in-time view the adoption term is the `usage_row_index` of the single most recent usage row (again `period_end_date` descending, `created_at` ascending as tie-break), or 0.00 when the account has no usage row at all."
        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."
        PRD §3.2: "Consider an account whose three usage rows read 36.00, 56.00 and 86.00 with 86.00 newest, and which has no sponsors, tickets or goals: its point-in-time adoption term is 86.00 giving a `snapshot_health_score` of 73.85, while its trailing adoption term is 67.00 giving a `trended_health_score` of 67.20."
        PRD §3.2: "`health_tier` is derived from `snapshot_health_score` **only**: the tier is `RED` when `snapshot_health_score` is below 50.00, `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at least 75.00."

        Design: Difficulty/dual_variant_calc/account_health_snapshot_variant_diverges_from_trended_variant
        """
        account = read_account(api, trending_account["account_id"])
        assert_scores(
            account,
            {
                "adoption_index": 67.00,
                "support_risk_penalty": 0.00,
                "exec_engagement_score": 25.00,
                "outcome_attainment_index": 60.00,
                "snapshot_health_score": 73.85,
                "trended_health_score": 67.20,
            },
        )
        assert_field(account, "health_tier", HEALTH_AMBER)

        summary = read_health_summary(api, trending_account["account_id"])
        assert_scores(
            summary,
            {
                "adoption_index": 67.00,
                "support_component": 100.00,
                "snapshot_health_score": 73.85,
                "trended_health_score": 67.20,
                "variant_delta": 6.65,
            },
        )
        assert_field(summary, "usage_rows_considered", 3)
        assert_field(summary, "health_tier", HEALTH_AMBER)

    def test_single_usage_row_renormalises_and_collapses_the_two_variants(
        self, api, clock, roster_and_account
    ):
        """One usage row is both the newest row and the whole trailing mean.

        PRD §3.2: "`adoption_index` is the sum of each row's `usage_row_index` multiplied by its weight, divided by the sum of **only the weights actually used**, rounded half up to two decimal places once after the division."
        PRD §3.2: "Renormalising by the weights in play rather than by 1.00 is what makes a one-row or two-row account comparable to a three-row account: three rows reading 86.00, 56.00 and 36.00 newest-first give a numerator of 43.00 plus 16.80 plus 7.20, a denominator of 1.00, and an `adoption_index` of 67.00; a lone row reading 40.00 gives a numerator of 20.00 over a denominator of 0.50, and an `adoption_index` of 40.00 rather than 20.00."
        PRD §3.2: "A row with 90 weekly active users against 100 licensed seats and a `feature_depth_pct` of 80.00 therefore yields `seat_utilisation_pct` 90.00 and `usage_row_index` 86.00."
        PRD §3.2: "For inspection there is a read-only health projection that adds no state of its own and exposes the model's internals side by side: `adoption_index`, `support_component` (the complement of `support_risk_penalty`), `exec_engagement_score`, `outcome_attainment_index`, `snapshot_health_score`, `trended_health_score`, `variant_delta` (the point-in-time figure minus the trailing figure), `health_tier`, and `usage_rows_considered` (the number of usage rows the adoption calculation actually used, which is the smaller of 3 and the account's usage-row count)."

        Design: Difficulty/dual_variant_calc/account_health_snapshot_variant_diverges_from_trended_variant
        """
        signal = add_usage_signal(
            api,
            roster_and_account["account_id"],
            roster_and_account["csm_id"],
            NEWEST_USAGE_ROW["period_end_date"],
            NEWEST_USAGE_ROW["weekly_active_users"],
            NEWEST_USAGE_ROW["licensed_seats"],
            NEWEST_USAGE_ROW["feature_depth_pct"],
        )
        assert_scores(signal, {"seat_utilisation_pct": 90.00, "usage_row_index": 86.00})

        account = read_account(api, roster_and_account["account_id"])
        assert_scores(
            account,
            {
                "adoption_index": 86.00,
                "snapshot_health_score": 73.85,
                "trended_health_score": 73.85,
            },
        )
        assert_field(account, "health_tier", HEALTH_AMBER)

        summary = read_health_summary(api, roster_and_account["account_id"])
        assert_scores(summary, {"variant_delta": 0.00})
        assert_field(summary, "usage_rows_considered", 1)

    def test_fourth_oldest_usage_row_is_excluded_from_the_trailing_variant(
        self, api, clock, trending_account
    ):
        """A row beyond the third-most-recent moves neither variant.

        PRD §3.2: "The input set is the three most recent usage rows of the account, ordered by `period_end_date` descending with `created_at` ascending as the only tie-break; support rows are excluded, and any usage row beyond the third-most-recent is excluded entirely."
        PRD §3.2: "The newest of those rows is weighted 0.50, the second 0.30 and the third 0.20."
        PRD §3.2: "For inspection there is a read-only health projection that adds no state of its own and exposes the model's internals side by side: `adoption_index`, `support_component` (the complement of `support_risk_penalty`), `exec_engagement_score`, `outcome_attainment_index`, `snapshot_health_score`, `trended_health_score`, `variant_delta` (the point-in-time figure minus the trailing figure), `health_tier`, and `usage_rows_considered` (the number of usage rows the adoption calculation actually used, which is the smaller of 3 and the account's usage-row count)."

        Design: Difficulty/dual_variant_calc/account_health_snapshot_variant_diverges_from_trended_variant
        """
        add_usage_signal(
            api,
            trending_account["account_id"],
            trending_account["csm_id"],
            "2026-04-30",
            10,
            100,
            10.00,
        )

        account = read_account(api, trending_account["account_id"])
        assert_scores(
            account,
            {
                "adoption_index": 67.00,
                "snapshot_health_score": 73.85,
                "trended_health_score": 67.20,
            },
        )

        summary = read_health_summary(api, trending_account["account_id"])
        assert_scores(summary, {"variant_delta": 6.65})
        assert_field(summary, "usage_rows_considered", 3)


class TestRenewalForecastAmountVariants:
    """The CS bottom-up amount and the finance top-down amount over one account."""

    def test_upside_bottom_up_diverges_from_the_enterprise_top_down_number(
        self, api, clock, open_account
    ):
        """0.70 of ARR against 0.90 of the same ARR leaves a flagged variance.

        PRD §3.2: "Otherwise, if `trended_health_score` is at least 60.00 and the days-to-renewal figure is strictly greater than 60, the category is `UPSIDE`."
        PRD §3.6: "The new row starts with `cs_state` `DRAFT` and `finance_state` `PENDING`, with `finance_amount_cents`, `variance_cents`, `submitted_at` and `reconciled_at` all null, and it snapshots the account's current `renewal_likelihood` into `likelihood_category` — the forecast records the judgement of the moment it was written and does not track the account afterwards."
        PRD §3.6: "When `cs_amount_cents` is omitted it is computed bottom up as the CS organisation's own number: the account's `arr_cents` multiplied by the likelihood weight for the snapshotted `likelihood_category` — 0.95 for `COMMIT`, 0.70 for `UPSIDE`, 0.35 for `AT_RISK` and 0.00 for `OMIT` — rounded half up to whole cents."
        PRD §3.6: "Finance's number is derived quite differently, top down from a flat segment retention rate that ignores account-level health entirely: `arr_cents` multiplied by 0.90 for `ENTERPRISE`, 0.80 for `MIDMARKET` or 0.65 for `SMB`, again rounded half up to whole cents."
        PRD §3.6: "It establishes `finance_amount_cents` from the request, or from the top-down segment method when the field is omitted, sets `variance_cents` to `finance_amount_cents` minus `cs_amount_cents` — keeping its sign, so an under-call by finance is negative — and stamps `reconciled_at` with the logical clock."
        PRD §3.6: "The variance is then judged against a tolerance of 500 basis points of the CS number, tested purely in integers by cross-multiplication so that no division or floating point is involved: when the absolute value of `variance_cents` multiplied by 10,000 is **strictly greater** than 500 multiplied by `cs_amount_cents`, `finance_state` becomes `VARIANCE_FLAGGED`; otherwise it becomes `RECONCILED`."
        PRD §3.6: "Note the shape this leaves in between: a row may legitimately rest at `cs_state` `SUBMITTED` with `finance_state` `VARIANCE_FLAGGED` indefinitely, because the finance axis cannot force the CS axis to move."

        Design: Difficulty/dual_variant_calc/renewal_amount_cs_bottom_up_variant_diverges_from_finance_top_down
        """
        account = read_account(api, open_account["account_id"])
        assert_field(account, "renewal_likelihood", LIKELIHOOD_UPSIDE)

        forecast = open_forecast(
            api, open_account["account_id"], open_account["csm_id"], "2026Q3"
        )
        assert_field(forecast, "likelihood_category", LIKELIHOOD_UPSIDE)
        assert_cents_fields(forecast, {"cs_amount_cents": 21_000_000})
        assert_null(forecast, "finance_amount_cents", "variance_cents")

        submit_forecast(api, forecast["id"], open_account["csm_id"])
        reconciled = reconcile_forecast(
            api, forecast["id"], RECONCILE_ACTION_RECONCILE
        )
        assert_cents_fields(
            reconciled,
            {
                "cs_amount_cents": 21_000_000,
                "finance_amount_cents": 27_000_000,
                "variance_cents": 6_000_000,
            },
        )
        assert_fields(
            reconciled,
            {
                "cs_state": CS_STATE_SUBMITTED,
                "finance_state": FINANCE_STATE_VARIANCE_FLAGGED,
            },
        )

    def test_at_risk_bottom_up_widens_the_gap_against_the_same_top_down_number(
        self, api, clock, roster_and_account
    ):
        """0.35 of ARR against the unchanged 0.90 of ARR gives a 16,500,000 gap.

        PRD §3.1: "Because a freshly registered account has no usage, no tickets, no sponsors and no goals, this deterministic first pass always produces `adoption_index` 0.00, `support_risk_penalty` 0.00, `exec_engagement_score` 25.00, `outcome_attainment_index` 60.00, `snapshot_health_score` and `trended_health_score` both 43.75, `health_tier` `RED`, `renewal_likelihood` `AT_RISK` and `coverage_posture` `RESTRICTED`."
        PRD §3.6: "When `cs_amount_cents` is omitted it is computed bottom up as the CS organisation's own number: the account's `arr_cents` multiplied by the likelihood weight for the snapshotted `likelihood_category` — 0.95 for `COMMIT`, 0.70 for `UPSIDE`, 0.35 for `AT_RISK` and 0.00 for `OMIT` — rounded half up to whole cents."
        PRD §3.6: "The two methods are meant to disagree, and the gap is the whole point of reconciliation: an `ENTERPRISE` account at 30,000,000 cents currently judged `AT_RISK` produces a bottom-up figure of 10,500,000 and a top-down figure of 27,000,000, a gap of 16,500,000 cents, whereas the same account judged `COMMIT` produces 28,500,000 bottom up against the same 27,000,000 top down, a gap of −1,500,000."
        PRD §3.6: "The variance is then judged against a tolerance of 500 basis points of the CS number, tested purely in integers by cross-multiplication so that no division or floating point is involved: when the absolute value of `variance_cents` multiplied by 10,000 is **strictly greater** than 500 multiplied by `cs_amount_cents`, `finance_state` becomes `VARIANCE_FLAGGED`; otherwise it becomes `RECONCILED`."

        Design: Difficulty/dual_variant_calc/renewal_amount_cs_bottom_up_variant_diverges_from_finance_top_down
        """
        state = open_coverage(api, roster_and_account)
        account = read_account(api, state["account_id"])
        assert_field(account, "renewal_likelihood", LIKELIHOOD_AT_RISK)

        forecast = open_forecast(api, state["account_id"], state["csm_id"], "2026Q3")
        assert_field(forecast, "likelihood_category", LIKELIHOOD_AT_RISK)
        assert_cents_fields(forecast, {"cs_amount_cents": 10_500_000})

        submit_forecast(api, forecast["id"], state["csm_id"])
        reconciled = reconcile_forecast(
            api, forecast["id"], RECONCILE_ACTION_RECONCILE
        )
        assert_cents_fields(
            reconciled,
            {
                "cs_amount_cents": 10_500_000,
                "finance_amount_cents": 27_000_000,
                "variance_cents": 16_500_000,
            },
        )
        assert_field(reconciled, "finance_state", FINANCE_STATE_VARIANCE_FLAGGED)

    @pytest.mark.parametrize(
        "finance_amount_cents, expected_variance_cents, expected_finance_state",
        [
            (11_025_000, 525_000, FINANCE_STATE_RECONCILED),
            (11_025_001, 525_001, FINANCE_STATE_VARIANCE_FLAGGED),
        ],
    )
    def test_variance_of_exactly_five_percent_reconciles_and_one_cent_more_flags(
        self,
        api,
        clock,
        roster_and_account,
        finance_amount_cents,
        expected_variance_cents,
        expected_finance_state,
    ):
        """The tolerance is judged by cross-multiplication against the CS number.

        PRD §3.6: "When `cs_amount_cents` is omitted it is computed bottom up as the CS organisation's own number: the account's `arr_cents` multiplied by the likelihood weight for the snapshotted `likelihood_category` — 0.95 for `COMMIT`, 0.70 for `UPSIDE`, 0.35 for `AT_RISK` and 0.00 for `OMIT` — rounded half up to whole cents."
        PRD §3.6: "It establishes `finance_amount_cents` from the request, or from the top-down segment method when the field is omitted, sets `variance_cents` to `finance_amount_cents` minus `cs_amount_cents` — keeping its sign, so an under-call by finance is negative — and stamps `reconciled_at` with the logical clock."
        PRD §3.6: "A variance of exactly five percent of the CS number reconciles."
        PRD §3.6: "Against a `cs_amount_cents` of 10,500,000, a `finance_amount_cents` of 11,025,000 gives a `variance_cents` of 525,000, whose cross-product of 5,250,000,000 equals the tolerance product exactly and therefore reconciles; one cent more, at 11,025,001, gives 525,001 and a cross-product of 5,250,010,000, which exceeds it and flags."

        Design: Difficulty/dual_variant_calc/renewal_amount_cs_bottom_up_variant_diverges_from_finance_top_down
        """
        state = open_coverage(api, roster_and_account)
        forecast = open_forecast(api, state["account_id"], state["csm_id"], "2026Q3")
        assert_cents_fields(forecast, {"cs_amount_cents": 10_500_000})

        submit_forecast(api, forecast["id"], state["csm_id"])
        reconciled = reconcile_forecast(
            api,
            forecast["id"],
            RECONCILE_ACTION_RECONCILE,
            finance_amount_cents=finance_amount_cents,
        )
        assert_cents_fields(
            reconciled,
            {
                "finance_amount_cents": finance_amount_cents,
                "variance_cents": expected_variance_cents,
            },
        )
        assert_field(reconciled, "finance_state", expected_finance_state)


class TestTimeToValueVariants:
    """The contractual and activation time-to-value figures over one plan."""

    def test_contractual_and_activation_figures_share_go_live_but_not_the_baseline(
        self, api, clock, roster_and_account
    ):
        """The contract start gives 78 days where the kickoff date gives 59.

        PRD §2.5: "Differences between two calendar dates are counted in whole days."
        PRD §3.1: "On success the milestone moves `PENDING → COMPLETED` or `OVERDUE → COMPLETED`, its `completed_date` is stored, and `days_late` is set to the number of whole days from `due_date` to `completed_date`, floored at 0 — an early or on-time completion records 0 rather than a negative number."
        PRD §3.1: "`contractual_ttv_days` is the number of whole days from the account's `contract_start_date` to the `completed_date` of its `GO_LIVE` milestone, and is null unless that milestone is in state `COMPLETED`; measured from the commercial start of the term, it charges integration delay that precedes kickoff against the vendor, which is why it is the figure compared against the segment's target for reporting."
        PRD §3.1: "`activation_ttv_days` is the number of whole days from the `completed_date` of the `KICKOFF` milestone to the `completed_date` of the `GO_LIVE` milestone, and is null unless **both** of those milestones are `COMPLETED`; measured from kickoff, it excludes pre-kickoff customer-side delay and therefore grades CSM execution."
        PRD §3.1: "It fires when the account has at least one onboarding milestone and every one of them is in state `COMPLETED` or `WAIVED`."
        PRD §3.1: "Its side effects are to recompute both time-to-value figures, set `ttv_breach_flag` to false, recompute `coverage_posture`, and increment the account's `version` by 1 while refreshing its `updated_at`."

        Design: Difficulty/dual_variant_calc/time_to_value_contractual_variant_diverges_from_activation_variant
        """
        state = open_coverage(api, roster_and_account)
        assert_field(state["assignment"], "state", ASSIGNMENT_COMMITTED)
        milestones = _build_plan(api, state)

        for code, _sequence_index, _due_date in MILESTONE_PLAN:
            transition_milestone(
                api,
                milestones[code],
                state["csm_id"],
                MILESTONE_ACTION_COMPLETE,
                completed_date=COMPLETION_DATES[code],
            )

        account = read_account(api, state["account_id"])
        assert_fields(
            account,
            {
                "contractual_ttv_days": 78,
                "activation_ttv_days": 59,
                "lifecycle_state": LIFECYCLE_ADOPTING,
                "ttv_breach_flag": False,
            },
        )

        kickoff = read_milestone(api, state["account_id"], milestones[CODE_KICKOFF])
        go_live = read_milestone(api, state["account_id"], milestones[CODE_GO_LIVE])
        assert_fields(
            kickoff,
            {
                "state": MILESTONE_COMPLETED,
                "completed_date": COMPLETION_DATES[CODE_KICKOFF],
                "days_late": 5,
            },
        )
        assert_fields(
            go_live,
            {
                "state": MILESTONE_COMPLETED,
                "completed_date": COMPLETION_DATES[CODE_GO_LIVE],
                "days_late": 5,
            },
        )

    def test_waived_go_live_leaves_both_time_to_value_figures_null(
        self, api, clock, roster_and_account
    ):
        """Neither figure survives a waiver of the milestone they both read.

        PRD §3.1: "CS operations may instead waive a milestone, moving it `PENDING → WAIVED`, `OVERDUE → WAIVED` or `BLOCKED → WAIVED` with no preconditions at all."
        PRD §3.1: "A `GO_LIVE` milestone that is waived rather than completed leaves both figures null."
        PRD §3.1: "It fires when the account has at least one onboarding milestone and every one of them is in state `COMPLETED` or `WAIVED`."

        Design: Difficulty/dual_variant_calc/time_to_value_contractual_variant_diverges_from_activation_variant
        """
        state = open_coverage(api, roster_and_account)
        milestones = _build_plan(api, state)

        for code in (CODE_KICKOFF, CODE_DATA_INTEGRATION, CODE_FIRST_VALUE):
            transition_milestone(
                api,
                milestones[code],
                state["csm_id"],
                MILESTONE_ACTION_COMPLETE,
                completed_date=COMPLETION_DATES[code],
            )
        waived = _waive(api, milestones[CODE_GO_LIVE])
        assert_field(waived, "state", MILESTONE_WAIVED)

        account = read_account(api, state["account_id"])
        assert_null(account, "contractual_ttv_days", "activation_ttv_days")
        assert_fields(
            account,
            {"lifecycle_state": LIFECYCLE_ADOPTING, "ttv_breach_flag": False},
        )

    def test_waived_kickoff_keeps_the_contractual_figure_and_voids_the_activation_one(
        self, api, clock, roster_and_account
    ):
        """Only the activation figure needs the kickoff completion date.

        PRD §3.1: "CS operations may instead waive a milestone, moving it `PENDING → WAIVED`, `OVERDUE → WAIVED` or `BLOCKED → WAIVED` with no preconditions at all."
        PRD §3.1: "`contractual_ttv_days` is the number of whole days from the account's `contract_start_date` to the `completed_date` of its `GO_LIVE` milestone, and is null unless that milestone is in state `COMPLETED`; measured from the commercial start of the term, it charges integration delay that precedes kickoff against the vendor, which is why it is the figure compared against the segment's target for reporting."
        PRD §3.1: "`activation_ttv_days` is the number of whole days from the `completed_date` of the `KICKOFF` milestone to the `completed_date` of the `GO_LIVE` milestone, and is null unless **both** of those milestones are `COMPLETED`; measured from kickoff, it excludes pre-kickoff customer-side delay and therefore grades CSM execution."
        PRD §2.9: "For a `COMPLETE` milestone action, every onboarding milestone of the same account whose `sequence_index` is strictly lower is already in state `COMPLETED` or `WAIVED`."

        Design: Difficulty/dual_variant_calc/time_to_value_contractual_variant_diverges_from_activation_variant
        """
        state = open_coverage(api, roster_and_account)
        milestones = _build_plan(api, state)

        waived = _waive(api, milestones[CODE_KICKOFF])
        assert_field(waived, "state", MILESTONE_WAIVED)
        for code in (CODE_DATA_INTEGRATION, CODE_FIRST_VALUE, CODE_GO_LIVE):
            transition_milestone(
                api,
                milestones[code],
                state["csm_id"],
                MILESTONE_ACTION_COMPLETE,
                completed_date=COMPLETION_DATES[code],
            )

        account = read_account(api, state["account_id"])
        assert_field(account, "contractual_ttv_days", 78)
        assert_null(account, "activation_ttv_days")
        assert_field(account, "lifecycle_state", LIFECYCLE_ADOPTING)
