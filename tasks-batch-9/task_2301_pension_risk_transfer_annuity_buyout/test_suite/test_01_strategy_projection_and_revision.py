"""Dual-basis strategy projection, per-participant rounding order and the bounded
return-for-revision loop.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import actuary_alt_headers, api_errors, fiduciary_headers
from test_helpers.constants import (
    ACCOUNTING_FACTOR_BP,
    SETTLEMENT_EXPENSE_LOAD_BP,
    SETTLEMENT_FACTOR_BP,
    accounting_liability,
    annualise,
    apply_bp,
    projected_accounting_cost,
    projected_settlement_base,
    projected_settlement_cost,
    round_half_up,
    settlement_liability,
)
from test_helpers.fixtures import (
    create_participant,
    create_plan,
    create_strategy,
    decide_strategy,
    read_participant,
    read_strategy,
    submit_strategy,
)

RETIREE = "RETIREE_IN_PAY"

#: The three stated monthly benefits that make the settlement product land on a
#: true half for the first participant.
BENEFITS = (250001, 180003, 99999)


def _plan_with_three_retirees(api):
    plan = create_plan(
        api,
        total_liability_cents=100000000,
        plan_assets_cents=92000000,
        service_cost_cents=3000000,
        interest_cost_cents=9000000,
        unrecognized_actuarial_loss_cents=4000000,
        discount_rate_bps=510,
    )
    participants = [
        create_participant(
            api,
            plan["id"],
            cohort=RETIREE,
            stated_monthly_benefit_cents=benefit,
            final_average_monthly_earnings_cents=fame,
            credited_service_months=400,
        )
        for benefit, fame in zip(BENEFITS, (500000, 360000, 200000))
    ]
    return plan, participants


# ---------------------------------------------------------------------------
# Design: Difficulty/dual_variant_calc/strategy_dual_basis_projected_cost_diverges
# ---------------------------------------------------------------------------


def test_strategy_submission_prices_one_population_on_two_divergent_bases(api):
    """One submission prices the same population twice and stores divergent totals.

    PRD: "For each participant in the population, and separately for each basis,
    the effective monthly benefit is multiplied by twelve to give an annual amount,
    that annual amount is multiplied by the basis factor for the participant's
    `cohort`, and the product is rounded half up over 10,000."

    PRD: "The accounting total is stored in `projected_accounting_cost_cents`, the
    settlement total in `projected_settlement_cost_cents`, and
    `projected_basis_gap_cents` is the settlement total minus the accounting total
    — the de-risking premium the sponsor must fund out of its own resources."

    Design: Difficulty/dual_variant_calc/strategy_dual_basis_projected_cost_diverges
    """
    plan, participants = _plan_with_three_retirees(api)
    strategy = create_strategy(api, plan["id"], "ANNUITY_BUYOUT")

    submitted = submit_strategy(api, strategy["id"])

    population = [(benefit, RETIREE) for benefit in BENEFITS]
    expected_accounting = projected_accounting_cost(population)
    expected_settlement = projected_settlement_cost(population)

    assert submitted["strategy_status"] == "UNDER_EVALUATION"
    assert submitted["in_scope_participant_count"] == 3
    assert submitted["projected_accounting_cost_cents"] == expected_accounting
    assert submitted["projected_settlement_cost_cents"] == expected_settlement
    assert submitted["projected_basis_gap_cents"] == expected_settlement - expected_accounting
    assert (
        submitted["projected_settlement_cost_cents"]
        != submitted["projected_accounting_cost_cents"]
    )

    for participant, benefit in zip(participants, BENEFITS):
        stored = read_participant(api, participant["id"])
        assert stored["accounting_liability_cents"] == accounting_liability(benefit, RETIREE)
        assert stored["settlement_liability_cents"] == settlement_liability(benefit, RETIREE)
        assert stored["accounting_liability_cents"] == apply_bp(
            annualise(benefit), ACCOUNTING_FACTOR_BP[RETIREE]
        )
        assert stored["settlement_liability_cents"] == apply_bp(
            annualise(benefit), SETTLEMENT_FACTOR_BP[RETIREE]
        )


def test_expense_load_lifts_only_the_settlement_basis_total(api):
    """The 350 bp load is added on the settlement basis and contributes nothing on the other.

    PRD: "On the settlement basis only, an expense load is then added: the base
    amount multiplied by 350 basis points and rounded half up over 10,000, an
    additional three and a half percent for the carrier's transaction expenses."

    PRD: "On the accounting basis the expense load contributes nothing."

    Design: Difficulty/dual_variant_calc/strategy_dual_basis_projected_cost_diverges
    """
    plan, _participants = _plan_with_three_retirees(api)
    strategy = create_strategy(api, plan["id"], "ANNUITY_BUYOUT")

    submitted = submit_strategy(api, strategy["id"])

    population = [(benefit, RETIREE) for benefit in BENEFITS]
    settlement_base = projected_settlement_base(population)
    expense_load = apply_bp(settlement_base, SETTLEMENT_EXPENSE_LOAD_BP)

    assert submitted["projected_settlement_cost_cents"] == settlement_base + expense_load
    # The accounting total is the bare sum of its own per-participant amounts.
    assert submitted["projected_accounting_cost_cents"] == sum(
        accounting_liability(benefit, RETIREE) for benefit in BENEFITS
    )
    assert submitted["projected_basis_gap_cents"] == (
        settlement_base + expense_load - submitted["projected_accounting_cost_cents"]
    )
    assert expense_load > 0


def test_annuity_buyout_scope_admits_exactly_the_retiree_cohort(api):
    """The strategy type, not the plan roster, fixes which cohort is in scope.

    PRD: "A `LUMP_SUM_WINDOW` strategy addresses only `DEFERRED_VESTED`
    participants; an `ANNUITY_BUYOUT` strategy addresses only `RETIREE_IN_PAY`
    participants; a `HYBRID_WINDOW_AND_BUYOUT` strategy addresses both cohorts; an
    `LDI_GLIDEPATH` strategy addresses neither cohort, so its in-scope population
    is always empty."

    Design: Difficulty/dual_variant_calc/strategy_dual_basis_projected_cost_diverges
    """
    plan, _participants = _plan_with_three_retirees(api)
    create_participant(
        api,
        plan["id"],
        cohort="DEFERRED_VESTED",
        stated_monthly_benefit_cents=140000,
    )
    strategy = create_strategy(api, plan["id"], "ANNUITY_BUYOUT")

    submitted = submit_strategy(api, strategy["id"])

    retiree_population = [(benefit, RETIREE) for benefit in BENEFITS]
    assert submitted["in_scope_participant_count"] == 3
    assert submitted["projected_accounting_cost_cents"] == projected_accounting_cost(
        retiree_population
    )
    assert submitted["projected_settlement_cost_cents"] == projected_settlement_cost(
        retiree_population
    )


# ---------------------------------------------------------------------------
# Design: Difficulty/combinatorial_formula/per_participant_rounding_order_pinned
# ---------------------------------------------------------------------------


def test_settlement_basis_rounds_each_participant_before_summing(api):
    """Rounding per participant and rounding the summed products differ by one cent.

    PRD: "The per-participant amounts are rounded **before** they are summed;
    summing the exact products and rounding the total once produces a different
    integer and is explicitly not the contract."

    Design: Difficulty/combinatorial_formula/per_participant_rounding_order_pinned
    """
    plan, participants = _plan_with_three_retirees(api)
    strategy = create_strategy(api, plan["id"], "ANNUITY_BUYOUT")

    submitted = submit_strategy(api, strategy["id"])

    round_then_sum_base = sum(settlement_liability(benefit, RETIREE) for benefit in BENEFITS)
    sum_then_round_base = round_half_up(
        sum(annualise(benefit) * SETTLEMENT_FACTOR_BP[RETIREE] for benefit in BENEFITS),
        10000,
    )
    # The two orders genuinely disagree on this population.
    assert round_then_sum_base == sum_then_round_base + 1

    expected = round_then_sum_base + apply_bp(round_then_sum_base, SETTLEMENT_EXPENSE_LOAD_BP)
    rejected = sum_then_round_base + apply_bp(sum_then_round_base, SETTLEMENT_EXPENSE_LOAD_BP)

    assert submitted["projected_settlement_cost_cents"] == expected
    assert submitted["projected_settlement_cost_cents"] != rejected

    for participant, benefit in zip(participants, BENEFITS):
        stored = read_participant(api, participant["id"])
        assert stored["settlement_liability_cents"] == settlement_liability(benefit, RETIREE)


def test_exact_half_settlement_product_rounds_half_up(api):
    """The first participant's settlement product is a true half and rounds away from zero.

    PRD: "For each participant in the population, and separately for each basis,
    the effective monthly benefit is multiplied by twelve to give an annual amount,
    that annual amount is multiplied by the basis factor for the participant's
    `cohort`, and the product is rounded half up over 10,000."

    Design: Difficulty/combinatorial_formula/per_participant_rounding_order_pinned
    """
    plan, participants = _plan_with_three_retirees(api)
    strategy = create_strategy(api, plan["id"], "ANNUITY_BUYOUT")
    submit_strategy(api, strategy["id"])

    exact_product = annualise(BENEFITS[0]) * SETTLEMENT_FACTOR_BP[RETIREE]
    # The product is an exact half of 10,000 -- the decisive rounding case.
    assert exact_product % 10000 == 5000

    stored = read_participant(api, participants[0]["id"])
    assert stored["settlement_liability_cents"] == exact_product // 10000 + 1
    assert stored["settlement_liability_cents"] == settlement_liability(BENEFITS[0], RETIREE)


# ---------------------------------------------------------------------------
# Design: Difficulty/non_linear_state_machine/strategy_revision_cycle_bounded_at_two_rounds
# ---------------------------------------------------------------------------


def _submitted_strategy_after_two_returns(api):
    plan = create_plan(
        api,
        total_liability_cents=100000000,
        plan_assets_cents=92000000,
        service_cost_cents=3000000,
        interest_cost_cents=9000000,
        unrecognized_actuarial_loss_cents=4000000,
        discount_rate_bps=500,
    )
    for benefit, fame in ((250001, 500000), (99999, 200000)):
        create_participant(
            api,
            plan["id"],
            cohort=RETIREE,
            stated_monthly_benefit_cents=benefit,
            final_average_monthly_earnings_cents=fame,
            credited_service_months=400,
        )
    strategy = create_strategy(api, plan["id"], "ANNUITY_BUYOUT")
    first = submit_strategy(api, strategy["id"])
    strategy["plan_id"] = plan["id"]
    after_first_return = decide_strategy(
        api,
        strategy["id"],
        "RETURN_FOR_REVISION",
        decision_rationale="Round one: the mortality assumption predates the improvement scale.",
    )
    submit_strategy(api, strategy["id"], actuary_alt_headers())
    after_second_return = decide_strategy(
        api,
        strategy["id"],
        "RETURN_FOR_REVISION",
        decision_rationale="Round two: the expense load still excludes the expert fee.",
    )
    third = submit_strategy(api, strategy["id"])
    return strategy, first, after_first_return, after_second_return, third


def test_third_return_for_revision_is_rejected_and_leaves_the_strategy_under_evaluation(api):
    """The loop is bounded at two returns; the third is refused with no state change.

    PRD: "Returning the strategy for revision moves it `UNDER_EVALUATION → DRAFT`,
    and carries the same segregation-of-duties requirement plus a bound on how many
    times the loop may run: `revision_count` must be below 2, and a third attempt to
    return the same strategy is rejected with `ERR_STRATEGY_STATE_INVALID`."

    Design: Difficulty/non_linear_state_machine/strategy_revision_cycle_bounded_at_two_rounds
    """
    strategy, _first, _r1, after_second_return, third = _submitted_strategy_after_two_returns(api)

    assert after_second_return["revision_count"] == 2
    assert third["strategy_status"] == "UNDER_EVALUATION"

    response = api.post_strategy_decision(
        strategy["id"],
        {
            "decision": "RETURN_FOR_REVISION",
            "decision_rationale": "Round three: the committee wants another pass.",
        },
        fiduciary_headers(),
    )
    validate_error(response, api_errors.ERR_STRATEGY_STATE_INVALID)

    current = read_strategy(api, strategy["plan_id"], strategy["id"])
    assert current["strategy_status"] == "UNDER_EVALUATION"
    assert current["revision_count"] == 2


def test_a_successful_return_clears_the_projections_and_zeroes_the_scope_count(api):
    """Each return is lossy: the three projected totals and the scope count are wiped.

    PRD: "A successful return increments `revision_count` by one, clears
    `projected_accounting_cost_cents`, `projected_settlement_cost_cents`, and
    `projected_basis_gap_cents`, resets `in_scope_participant_count` to 0, clears
    `submitted_by_user_id` so the next submitter is captured afresh, and bumps the
    `version`."

    Design: Difficulty/non_linear_state_machine/strategy_revision_cycle_bounded_at_two_rounds
    """
    plan = create_plan(api)
    for benefit, fame in ((250001, 500000), (99999, 200000)):
        create_participant(
            api,
            plan["id"],
            cohort=RETIREE,
            stated_monthly_benefit_cents=benefit,
            final_average_monthly_earnings_cents=fame,
            credited_service_months=400,
        )
    strategy = create_strategy(api, plan["id"], "ANNUITY_BUYOUT")

    submitted = submit_strategy(api, strategy["id"])
    population = [(250001, RETIREE), (99999, RETIREE)]
    assert submitted["in_scope_participant_count"] == 2
    assert submitted["projected_accounting_cost_cents"] == projected_accounting_cost(population)
    assert submitted["projected_settlement_cost_cents"] == projected_settlement_cost(population)

    returned = decide_strategy(
        api,
        strategy["id"],
        "RETURN_FOR_REVISION",
        decision_rationale="Round one: the mortality assumption predates the improvement scale.",
    )

    assert returned["strategy_status"] == "DRAFT"
    assert returned["revision_count"] == 1
    assert returned["projected_accounting_cost_cents"] is None
    assert returned["projected_settlement_cost_cents"] is None
    assert returned["projected_basis_gap_cents"] is None
    assert returned["in_scope_participant_count"] == 0
    assert returned["submitted_by_user_id"] is None
    assert returned["version"] > submitted["version"]


def test_return_clears_the_submitter_so_the_loop_is_value_stable_and_approval_remains(api):
    """A cleared submitter lets any actuary re-submit, and the recomputation is identical.

    PRD: "A successful return increments `revision_count` by one, clears
    `projected_accounting_cost_cents`, `projected_settlement_cost_cents`, and
    `projected_basis_gap_cents`, resets `in_scope_participant_count` to 0, clears
    `submitted_by_user_id` so the next submitter is captured afresh, and bumps the
    `version`."

    Design: Difficulty/non_linear_state_machine/strategy_revision_cycle_bounded_at_two_rounds
    """
    strategy, first, _r1, _r2, third = _submitted_strategy_after_two_returns(api)

    for field in (
        "projected_accounting_cost_cents",
        "projected_settlement_cost_cents",
        "projected_basis_gap_cents",
        "in_scope_participant_count",
    ):
        assert third[field] == first[field]

    approved = decide_strategy(
        api,
        strategy["id"],
        "APPROVE",
        decision_rationale="The committee accepts the third-round projections.",
    )
    assert approved["strategy_status"] == "APPROVED"
    assert approved["revision_count"] == 2
