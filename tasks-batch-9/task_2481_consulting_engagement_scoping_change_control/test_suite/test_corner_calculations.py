"""Formulae: which rate, which input set, which rounding and which clamp."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import ConsultingApiClient
from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_economics_view,
    assert_fields,
    assert_money,
    assert_two_dp,
)

UNROUNDED_BUDGET_CENTS = 55555555
OVER_FULL_BUDGET_CENTS = 150000000

# A three-deep chain plus one unconnected singleton, 220.00 hours in total.
CHAIN_DELIVERABLES = [
    {
        "name": "dA current-state",
        "primary_grade": C.GRADE_CONSULTANT,
        "effort_hours_estimate": 100.0,
        "completion_weight_pct": 30.0,
        "acceptance_criteria": "Baseline model signed off",
        "planned_start_date": "2026-09-01",
        "planned_end_date": "2026-10-01",
    },
    {
        "name": "dB target-state",
        "primary_grade": C.GRADE_MANAGER,
        "effort_hours_estimate": 60.0,
        "completion_weight_pct": 25.0,
        "acceptance_criteria": "Design pack approved",
        "planned_start_date": "2026-10-01",
        "planned_end_date": "2026-11-01",
        "depends_on_index": 0,
    },
    {
        "name": "dC transition plan",
        "primary_grade": C.GRADE_ANALYST,
        "effort_hours_estimate": 50.0,
        "completion_weight_pct": 35.0,
        "acceptance_criteria": "Transition plan accepted",
        "planned_start_date": "2026-11-01",
        "planned_end_date": "2026-12-01",
        "depends_on_index": 1,
    },
    {
        "name": "dD steering support",
        "primary_grade": C.GRADE_PARTNER,
        "effort_hours_estimate": 10.0,
        "completion_weight_pct": 10.0,
        "acceptance_criteria": "Steering pack delivered",
        "planned_start_date": "2026-09-01",
        "planned_end_date": "2026-12-01",
    },
]


def test_one_timesheet_line_is_priced_from_two_different_rate_sources(
    api: ConsultingApiClient,
) -> None:
    """The internal cost rate and the grade billing rate are not interchangeable.

    PRD 3.7: "Its `cost_cents` is `hours` multiplied by the consultant's own
    `cost_rate_cents_per_hour`, rounded half up to whole cents — this is the
    internal figure that drives the burn ledger."

    PRD 3.7: "Its `billed_value_cents` is `hours` multiplied by the firm's hourly
    billing rate for the consultant's `grade`, multiplied by one minus the
    engagement's `pinned_scope_discount_pct`, rounded half up to whole cents;
    when `billable` is false, `billed_value_cents` is 0 instead."

    Design: Corner/calculations/time_entry_costing_uses_two_different_rates_on_one_line
    """
    sc = fx.build_started_engagement(api)

    entry = fx.log_time(sc, 60.0, C.SEED_WEEK_1)

    # 60.00 * 62000 internal cost, against 60.00 * 92500 * 0.95 billed value
    assert_money(entry, "cost_cents", 3720000)
    assert_money(entry, "billed_value_cents", 5272500)
    assert_fields(entry, status=C.TIME_ENTRY_SUBMITTED)
    assert_two_dp(fx.read_engagement(sc), "approved_hours_burned", 0.00)


def test_a_non_billable_line_bills_nothing_but_burns_everything(
    api: ConsultingApiClient,
) -> None:
    """The write-off flag switches the billed leg only, never the cost leg.

    PRD 3.7: "Setting `billable` to false marks the line as a write-off: it still
    consumes internal cost and still burns hours, but it never bills the
    client."

    Design: Corner/calculations/non_billable_line_bills_zero_but_still_burns_full_cost
    """
    sc = fx.build_started_engagement(api)

    entry = fx.log_time(sc, 60.0, C.SEED_WEEK_1, billable=False)
    assert_money(entry, "billed_value_cents", 0)
    assert_money(entry, "cost_cents", 3720000)
    fx.approve_time(sc, entry["id"])

    engagement = fx.read_engagement(sc)
    assert_two_dp(engagement, "approved_hours_burned", 60.00)
    assert_money(engagement, "burned_cost_cents", 3720000)

    view = get_success_data(api.get_economics(sc.engagement_id, sc.partner))
    assert_economics_view(
        view,
        hours_burn_pct=29.89,
        completion_pct=0.00,
        progress_variance_pct=29.89,
        projected_cost_cents=8505500,
        projected_margin_pct=17.26,
        economics_state=C.ECONOMICS_AT_RISK,
    )


def test_a_submitted_line_is_outside_the_economics_input_set(
    api: ConsultingApiClient,
) -> None:
    """The same row is invisible before the decision and decisive after it.

    PRD 3.7: "Only `APPROVED` timesheet lines count towards the burn: `SUBMITTED`
    lines are excluded, and `REJECTED` and `REVERSED` lines are excluded too."

    Design: Corner/calculations/economics_excludes_a_submitted_time_entry_until_it_is_approved
    """
    sc = fx.build_started_engagement(api)
    entry = fx.log_time(sc, 60.0, C.SEED_WEEK_1)

    before = get_success_data(api.get_economics(sc.engagement_id, sc.partner))
    assert_economics_view(
        before,
        hours_burn_pct=0.00,
        completion_pct=0.00,
        progress_variance_pct=0.00,
        projected_cost_cents=6825500,
        projected_margin_pct=33.61,
        economics_state=C.ECONOMICS_ON_TRACK,
    )
    assert_two_dp(fx.read_deliverable(sc, sc.d1_id), "hours_consumed", 0.00)

    fx.approve_time(sc, entry["id"])

    after = get_success_data(api.get_economics(sc.engagement_id, sc.partner))
    assert_economics_view(
        after,
        hours_burn_pct=29.89,
        completion_pct=0.00,
        progress_variance_pct=29.89,
        projected_cost_cents=8505500,
        projected_margin_pct=17.26,
        economics_state=C.ECONOMICS_AT_RISK,
    )
    assert_two_dp(fx.read_deliverable(sc, sc.d1_id), "hours_consumed", 60.00)


def test_the_blended_rate_prices_every_unburned_contracted_hour(
    api: ConsultingApiClient,
) -> None:
    """With nothing burned the forecast leg is the constant on its own.

    PRD 3.7: "Those remaining hours are multiplied by a blended forecast cost
    rate of 34,000 cents per hour — 340.00 currency units for every unburned
    contracted hour, regardless of who will actually work them — and that product
    is rounded half up to whole cents."

    Design: Corner/calculations/blended_forecast_rate_charges_every_unburned_contracted_hour
    """
    sc = fx.build_active_engagement(api)
    fx.start_deliverable(sc, sc.d1_id, lead_id=sc.consultant_id)
    fx.accept_deliverable(sc, sc.d1_id)

    view = get_success_data(api.get_economics(sc.engagement_id, sc.partner))

    # 0 burned cost plus 200.75 unburned hours at 34000 cents each
    assert_economics_view(
        view,
        hours_burn_pct=0.00,
        completion_pct=40.00,
        progress_variance_pct=-40.00,
        projected_cost_cents=6825500,
        projected_margin_pct=33.61,
        economics_state=C.ECONOMICS_ON_TRACK,
    )
    assert fx.list_escalations(sc) == []


def test_the_qualification_score_rounds_only_once_at_the_end(
    api: ConsultingApiClient,
) -> None:
    """A budget ratio of 0.55555555 is carried unrounded into the weighting.

    PRD 3.2: "The four contributions are added together and the sum is rounded
    half up to two decimal places; neither the budget ratio nor the relationship
    factor is pre-rounded, only the final total."

    Design: Corner/calculations/qualification_score_rounds_only_the_final_weighted_total
    """
    sc = fx.build_master_data(api)

    row = fx.open_pursuit(sc, stated_budget_cents=UNROUNDED_BUDGET_CENTS)

    # 24.00 + 40 * 0.55555555 + 20.00 + 0.00 rounded once, not 66.40
    assert_two_dp(row, "qualification_score_intake", 66.22)
    assert_fields(
        row,
        qualification_score_verified=None,
        verified_budget_cents=None,
        status="SCREENING",
    )


def test_the_budget_ratio_is_clamped_at_full_marks(
    api: ConsultingApiClient,
) -> None:
    """A budget half again the estimate earns the 40-point cap, nothing more.

    PRD 3.2: "The budget-coverage term contributes 40 points multiplied by the
    budget ratio, where the budget ratio is the applicable budget figure divided
    by `estimated_value_cents`, capped at 1 so that a budget exceeding the
    estimate earns no more than full marks."

    Design: Corner/calculations/qualification_budget_ratio_clamped_at_one
    """
    sc = fx.build_screening_pursuit(api)
    fx.screen_conflicts(sc)

    fx.verify_budget(sc, OVER_FULL_BUDGET_CENTS)
    decided = get_success_data(api.qualify(sc.opportunity_id, {}, sc.partner))

    # 24.00 + 40.00 + 20.00 + 0.00; the ten relationship points stay unearned
    assert_two_dp(decided, "qualification_score_verified", 84.00)
    assert_two_dp(decided, "qualification_score_intake", 68.00)
    assert_fields(decided, status="QUALIFIED")


def test_a_perfect_survey_with_a_referral_is_clamped_to_ten(
    api: ConsultingApiClient,
) -> None:
    """The bonus is added outside the weighting and the ceiling is applied after.

    PRD 3.9: "The result is clamped at a maximum of 10.00 and then rounded half up
    to two decimal places, so a perfect ten-ten-ten with a referral still reports
    exactly 10.00."

    Design: Corner/calculations/csat_clamped_at_ten_after_the_referral_bonus
    """
    sc = fx.build_closed_engagement(api)

    filed = fx.file_satisfaction(
        sc,
        delivery_score=10,
        value_score=10,
        communication_score=10,
        would_refer=True,
        comments="Outstanding",
    )

    # 4.00 + 3.50 + 2.50 + 0.25 computes 10.25 and is clamped, not truncated
    assert_two_dp(filed, "csat_score", 10.00)
    assert_fields(
        filed,
        would_refer=True,
        delivery_score=10,
        value_score=10,
        communication_score=10,
    )


def test_an_assessed_change_request_moves_no_contracted_figure_until_approved(
    api: ConsultingApiClient,
) -> None:
    """Assessment is a pure computation stored on the request, not on the contract.

    PRD 3.8: "That figure is frozen onto the request as
    `cumulative_change_pct_at_assessment`."

    PRD 3.8: "Then five contracted figures move on the engagement in one step:
    `fee_delta_cents` is added to `contracted_fee_cents`, `added_hours` is added
    to `contracted_hours`, `requested_schedule_days` is added to
    `schedule_relief_days`, `planned_end_date` is pushed out by that same number
    of calendar days, and `cumulative_change_pct` is overwritten with the
    request's frozen `cumulative_change_pct_at_assessment`; the engagement's
    `version` advances."

    Design: Corner/calculations/pending_change_request_does_not_move_the_forecast_until_approved
    """
    sc = fx.build_burned_engagement(api)
    request = fx.raise_change_request(sc)

    assessed = fx.assess_change_request(sc, request["id"])
    assert_money(assessed, "fee_delta_cents", 3921600)
    assert_two_dp(assessed, "cumulative_change_pct_at_assessment", 38.15)
    assert_fields(
        assessed,
        routing=C.ROUTING_LEADERSHIP_THEN_CLIENT,
        status=C.CR_PENDING_LEADERSHIP_APPROVAL,
    )

    engagement = fx.read_engagement(sc)
    assert_money(engagement, "contracted_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)
    assert_two_dp(engagement, "contracted_hours", C.CANON_TOTAL_ESTIMATED_HOURS)
    before = get_success_data(api.get_economics(sc.engagement_id, sc.partner))
    assert_economics_view(
        before,
        hours_burn_pct=49.81,
        completion_pct=40.00,
        progress_variance_pct=9.81,
        projected_cost_cents=9625500,
        projected_margin_pct=6.37,
        economics_state=C.ECONOMICS_AT_RISK,
    )

    fx.leadership_approve_change(sc, request["id"])
    fx.client_approve_change(sc, request["id"])

    after = get_success_data(api.get_economics(sc.engagement_id, sc.partner))
    assert_economics_view(
        after,
        # Not one hour was booked; the denominator moved instead
        hours_burn_pct=27.72,
        completion_pct=40.00,
        progress_variance_pct=-12.28,
        projected_cost_cents=15065500,
        projected_margin_pct=-6.08,
        economics_state=C.ECONOMICS_OVERRUN,
    )
    moved = fx.read_engagement(sc)
    assert_money(moved, "contracted_fee_cents", 14201978)
    assert_two_dp(moved, "contracted_hours", 360.75)


def test_the_lead_load_count_drops_only_when_a_deliverable_is_accepted(
    api: ConsultingApiClient,
) -> None:
    """SUBMITTED still consumes capacity; only the terminal state releases it.

    PRD 3.1: "The computed `active_lead_deliverable_count` begins at 0 and always
    equals the number of deliverables anywhere in the firm whose lead is this
    consultant and whose status has not yet reached `ACCEPTED`."

    Design: Corner/calculations/active_lead_load_counts_only_unaccepted_deliverables
    """
    sc = fx.build_active_engagement(api)
    fx.start_deliverable(sc, sc.d1_id, lead_id=sc.consultant_id)

    assert_fields(
        fx.read_consultant(sc, sc.consultant_id), active_lead_deliverable_count=1
    )

    fx.set_status(sc, sc.d1_id, C.DELIVERABLE_SUBMITTED)
    assert_fields(
        fx.read_consultant(sc, sc.consultant_id), active_lead_deliverable_count=1
    )

    fx.set_status(sc, sc.d1_id, C.DELIVERABLE_ACCEPTED, headers=sc.client_contact)
    assert_fields(
        fx.read_consultant(sc, sc.consultant_id), active_lead_deliverable_count=0
    )
    # The assignment itself survives; only the derived load count moved
    assert_fields(
        fx.read_deliverable(sc, sc.d1_id), lead_consultant_id=sc.consultant_id
    )


def test_the_dependency_chain_counts_nodes_on_the_deepest_path(
    api: ConsultingApiClient,
) -> None:
    """Four deliverables, a three-deep chain, and per-line rounding into the total.

    PRD 3.4: "The `longest_dependency_chain` is the number of deliverables on the
    longest path through the pursuit's `depends_on_deliverable_id` graph,
    counting nodes rather than edges — so a deliverable with no predecessor and
    no successor counts as a chain of 1, and a pair where one depends on the
    other counts as 2."

    PRD 3.4: "Only after every line has been individually rounded are the rounded
    lines added together, and that integer sum is stored as the pursuit's
    `baseline_effort_cost_cents`."

    Design: Corner/calculations/longest_dependency_chain_is_the_deepest_path_not_the_deliverable_count
    """
    sc = fx.build_scoped_pursuit(api, deliverables=CHAIN_DELIVERABLES)

    baselined = fx.baseline_scope(sc)

    assert_fields(
        baselined, status="SCOPE_BASELINED", longest_dependency_chain=3
    )
    assert_two_dp(baselined, "total_estimated_hours", 220.00)
    assert_two_dp(baselined, "scope_discount_pct", C.SCOPE_DISCOUNT_TIER_MID)

    expected_lines = [3467500, 3277500, 1021250, 878750]
    for deliverable_id, expected in zip(sc.deliverable_ids, expected_lines):
        assert_money(fx.read_deliverable(sc, deliverable_id), "line_cost_cents", expected)
    assert_money(baselined, "baseline_effort_cost_cents", sum(expected_lines))
