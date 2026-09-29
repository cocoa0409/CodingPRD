"""Composed formulas: the nested-maximum required servicing margin, the pinned
per-period rounding order inside the net present value, and the liquidation fee
base pinned to gross rather than net proceeds.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    NPV_MOD_NPV_CONTRACTUAL,
    NPV_MOD_PV_CONTRACTUAL,
    WATERFALL_CONTROLLING_NOTIONAL,
    WATERFALL_EXPENSES,
    WATERFALL_GROSS,
    WATERFALL_LIQUIDATION_FEE,
    WATERFALL_REALIZED_LOSS,
)
from test_helpers.test_users import ASSET_MANAGER, MASTER_SERVICER


# ==========================================================================
# The required servicing standard margin: max(absolute floor, relative test)
# ==========================================================================
def _request_under_analysis_on(api, trust_id, loan_payload):
    loan = validate_success(api.create_loan(loan_payload, MASTER_SERVICER), 201)
    fx.record_bankruptcy_event(api, loan["id"])
    fx.transfer_to_special_servicing(api, loan["id"])
    request = fx.submit_modification_request(api, loan["id"])
    fx.set_request_status(api, request["id"], "UNDER_ANALYSIS")
    return request["id"]


def test_relative_branch_governs_a_large_loan_and_admits_the_exact_margin(api):
    """On a 19,500,000.00 balance the relative branch demands 97,500.00.

    The PRD: "It then derives the margin the standard demands: the greater of a
    fixed floor of fifty thousand dollars and one half of one percent of the
    loan's `current_principal_balance_usd` rounded half up to two decimal
    places."

    Design: Difficulty/combinatorial_formula/servicing_standard_required_margin_nested_max_three_way_branch
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-M1")
    request_id = _request_under_analysis_on(
        api, trust["id"], f.loan_payload(trust["id"], loan_number="L-BIG1")
    )

    analysed = validate_success(
        api.record_borrower_request_analysis(
            request_id,
            f.analysis_payload(
                npv_recovery_with_request_usd=21597500,
                npv_recovery_without_request_usd=21500000,
            ),
            ASSET_MANAGER,
        )
    )
    a.assert_money(
        analysed["servicing_standard_margin_usd"], 97500.00, "servicing_standard_margin_usd"
    )
    a.assert_status(
        analysed, "SERVICING_STANDARD_MET", "servicing_standard_conclusion"
    )


def test_relative_branch_rejects_a_margin_above_the_absolute_floor(api):
    """A 60,000.00 margin clears the 50,000.00 floor and still fails.

    The PRD: "When the achieved margin is greater than or equal to the demanded
    margin, `servicing_standard_conclusion` is `SERVICING_STANDARD_MET`; when it
    is strictly below, the conclusion is `SERVICING_STANDARD_NOT_MET`."

    Design: Difficulty/combinatorial_formula/servicing_standard_required_margin_nested_max_three_way_branch
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-M1")
    request_id = _request_under_analysis_on(
        api, trust["id"], f.loan_payload(trust["id"], loan_number="L-BIG2")
    )

    analysed = validate_success(
        api.record_borrower_request_analysis(
            request_id,
            f.analysis_payload(
                npv_recovery_with_request_usd=21560000,
                npv_recovery_without_request_usd=21500000,
            ),
            ASSET_MANAGER,
        )
    )
    a.assert_money(
        analysed["servicing_standard_margin_usd"], 60000.00, "servicing_standard_margin_usd"
    )
    a.assert_status(
        analysed, "SERVICING_STANDARD_NOT_MET", "servicing_standard_conclusion"
    )


def test_absolute_floor_governs_a_small_loan_where_the_relative_test_is_tiny(api):
    """On a 1,000,000.00 balance the 50,000.00 floor still governs.

    The PRD: "the two components of the demanded margin swap dominance with loan
    size: on a small loan the absolute floor governs, on a large loan the
    relative test does."

    Design: Difficulty/combinatorial_formula/servicing_standard_required_margin_nested_max_three_way_branch
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-M1")
    request_id = _request_under_analysis_on(
        api, trust["id"], f.small_loan_payload(trust["id"])
    )

    analysed = validate_success(
        api.record_borrower_request_analysis(
            request_id,
            f.analysis_payload(
                npv_recovery_with_request_usd=1006000,
                npv_recovery_without_request_usd=1000000,
            ),
            ASSET_MANAGER,
        )
    )
    a.assert_money(
        analysed["servicing_standard_margin_usd"], 6000.00, "servicing_standard_margin_usd"
    )
    a.assert_status(
        analysed, "SERVICING_STANDARD_NOT_MET", "servicing_standard_conclusion"
    )


def test_both_margin_branches_are_live_on_the_same_deployment(api):
    """The same 6,000.00-scale margin passes on neither loan size for the same
    reason from a different branch.

    The PRD: "The service derives `servicing_standard_margin_usd` as
    `npv_recovery_without_request_usd` subtracted from
    `npv_recovery_with_request_usd`, rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/servicing_standard_required_margin_nested_max_three_way_branch
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-M1")
    big = _request_under_analysis_on(
        api, trust["id"], f.loan_payload(trust["id"], loan_number="L-BIG2")
    )
    small = _request_under_analysis_on(
        api, trust["id"], f.small_loan_payload(trust["id"])
    )

    big_analysed = validate_success(
        api.record_borrower_request_analysis(
            big,
            f.analysis_payload(
                npv_recovery_with_request_usd=21560000,
                npv_recovery_without_request_usd=21500000,
            ),
            ASSET_MANAGER,
        )
    )
    small_analysed = validate_success(
        api.record_borrower_request_analysis(
            small,
            f.analysis_payload(
                npv_recovery_with_request_usd=1006000,
                npv_recovery_without_request_usd=1000000,
            ),
            ASSET_MANAGER,
        )
    )
    a.assert_money(big_analysed["servicing_standard_margin_usd"], 60000.00, "big margin")
    a.assert_money(small_analysed["servicing_standard_margin_usd"], 6000.00, "small margin")
    a.assert_status(big_analysed, "SERVICING_STANDARD_NOT_MET", "servicing_standard_conclusion")
    a.assert_status(small_analysed, "SERVICING_STANDARD_NOT_MET", "servicing_standard_conclusion")


# ==========================================================================
# Per-period rounding before summation
# ==========================================================================
def _single_modification_alternative_plan(api):
    built_loan = fx.loan_in_special_servicing(
        api,
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-P01"},
    )
    return fx.scored_plan(
        api,
        built_loan["loan_id"],
        alternative_builders=[fx.add_modification_alternative],
        npv_basis="CONTRACTUAL",
    )


def test_each_period_is_rounded_before_it_joins_the_running_total(api):
    """The four rounded periods sum to 8,341,266.34.

    The PRD: "The entries are processed in ascending `period_index` order, and —
    as §2.6 insists — **each period's discounted figure is rounded half up to two
    decimal places before it is added to the running total**, which becomes
    `discounted_pv_usd`."

    Design: Difficulty/combinatorial_formula/npv_per_period_rounding_before_summation_one_cent_divergence
    """
    built = _single_modification_alternative_plan(api)
    alternative = validate_success(
        api.get_workout_alternative(built["alternative_ids"][0], ASSET_MANAGER)
    )
    a.assert_money(
        alternative["discounted_pv_usd"], NPV_MOD_PV_CONTRACTUAL, "discounted_pv_usd"
    )
    a.assert_money(alternative["npv_usd"], NPV_MOD_NPV_CONTRACTUAL, "npv_usd")


def test_summing_at_full_precision_and_rounding_once_is_one_cent_wrong(api):
    """The sum-then-round order is refused by exactly one cent.

    The PRD: "Discounting the whole stream and rounding once at the end is
    wrong; it can differ by one cent, and one cent is enough to reorder two
    alternatives and change which one the servicing standard obliges the special
    servicer to put forward."

    Design: Difficulty/combinatorial_formula/npv_per_period_rounding_before_summation_one_cent_divergence
    """
    built = _single_modification_alternative_plan(api)
    alternative = validate_success(
        api.get_workout_alternative(built["alternative_ids"][0], ASSET_MANAGER)
    )
    assert abs(float(alternative["npv_usd"]) - 8221266.33) > 0.005, (
        "npv_usd must not be the sum-then-round figure 8221266.33"
    )
    a.assert_money(alternative["npv_usd"], NPV_MOD_NPV_CONTRACTUAL, "npv_usd")


def test_the_sole_alternative_is_scored_ranked_and_recommended(api):
    """Scoring writes rank 1 and the plan's recommendation.

    The PRD: "Ranks are assigned as consecutive integers starting at 1 in that
    order, `rank` is written on every alternative in the pool, superseded
    alternatives keep a null `rank`, and the plan's `recommended_alternative_id`
    is set to the identifier of the rank-1 alternative."

    Design: Difficulty/combinatorial_formula/npv_per_period_rounding_before_summation_one_cent_divergence
    """
    built = _single_modification_alternative_plan(api)
    alternative = validate_success(
        api.get_workout_alternative(built["alternative_ids"][0], ASSET_MANAGER)
    )
    assert alternative["rank"] == 1
    a.assert_status(alternative, "SCORED")
    a.assert_status(built["plan"], "SCORED")
    assert built["plan"]["recommended_alternative_id"] == alternative["id"]


# ==========================================================================
# The liquidation fee base
# ==========================================================================
def _executed_note_sale_ready_to_liquidate(api):
    """A trust, a loan with two advances and an EXECUTED NOTE_SALE plan."""
    trust = fx.create_trust(
        api,
        deal_name="CMBS 2026-W1",
        original_controlling_class_balance_usd=8000000,
        liquidation_fee_rate_pct=1.0,
        advance_interest_rate_pct=5.0,
    )
    loan = validate_success(
        api.create_loan(
            f.loan_payload(
                trust["id"],
                loan_number="L-W01",
                original_balance_usd=11000000,
                current_principal_balance_usd=10000000,
                accrued_unpaid_interest_usd=250000,
                note_rate_pct=6.0,
                monthly_debt_service_usd=65000,
                maturity_date="2028-06-01T00:00:00Z",
                securitization_value_usd=14000000,
            ),
            MASTER_SERVICER,
        ),
        201,
    )
    fx.record_transfer_event(api, loan["id"])
    fx.transfer_to_special_servicing(api, loan["id"])
    advances = fx.two_advances(api, loan["id"])
    fx.accepted_appraisal(api, loan["id"], value_usd=8000000)

    def note_sale(client, plan_id):
        return fx.add_note_sale_alternative(
            client,
            plan_id,
            projected_cash_flows=[{"period_index": 1, "amount_usd": 7000000}],
            upfront_cost_usd=420000,
        )

    built = fx.executed_plan(
        api, trust["id"], loan["id"], alternative_builders=[note_sale]
    )
    fx.set_clock(api, "2026-10-01T00:00:00Z")
    return {
        "trust_id": trust["id"],
        "loan_id": loan["id"],
        "advance_a_id": advances["advance_a"]["id"],
        "advance_b_id": advances["advance_b"]["id"],
        "plan_id": built["plan_id"],
    }


def test_liquidation_fee_is_taken_on_gross_proceeds_not_on_the_net_figure(api):
    """One percent of 7,000,000.00 is 70,000.00, never 65,800.00.

    The PRD: "The base is pinned to **gross** proceeds and never to the net
    figure, because taking the fee on a post-fee amount would be circular."

    Design: Difficulty/combinatorial_formula/liquidation_fee_base_pinned_to_gross_not_net_proceeds
    """
    scenario = _executed_note_sale_ready_to_liquidate(api)

    validate_success(
        api.set_loan_servicing_status(
            scenario["loan_id"],
            f.liquidation_payload(
                WATERFALL_GROSS, WATERFALL_EXPENSES, "2026-10-01T00:00:00Z"
            ),
            ASSET_MANAGER,
        )
    )

    fees, _ = validate_paginated(
        api.list_fee_accruals(
            ASSET_MANAGER,
            {"loan_id": scenario["loan_id"], "fee_type": "LIQUIDATION_FEE"},
        )
    )
    assert len(fees) == 1, "the waterfall creates exactly one liquidation fee accrual"
    fee = fees[0]
    a.assert_status(fee, "ACCRUED")
    a.assert_money(fee["basis_amount_usd"], WATERFALL_GROSS, "basis_amount_usd")
    a.assert_rate_pct(fee["rate_pct"], 1.0)
    a.assert_money(fee["amount_usd"], WATERFALL_LIQUIDATION_FEE, "amount_usd")
    assert abs(float(fee["amount_usd"]) - 65800.00) > 0.005, (
        "one percent of net proceeds is the wrong base"
    )


def test_the_gross_fee_base_carries_through_to_principal_and_realized_loss(api):
    """Available proceeds of 6,510,000.00 walk the seven waterfall steps.

    The PRD: "**Available proceeds.** Subtract `liquidation_expenses_usd` and the
    fee from `gross_proceeds_usd`."

    Design: Difficulty/combinatorial_formula/liquidation_fee_base_pinned_to_gross_not_net_proceeds
    """
    scenario = _executed_note_sale_ready_to_liquidate(api)

    liquidated = validate_success(
        api.set_loan_servicing_status(
            scenario["loan_id"],
            f.liquidation_payload(
                WATERFALL_GROSS, WATERFALL_EXPENSES, "2026-10-01T00:00:00Z"
            ),
            ASSET_MANAGER,
        )
    )
    a.assert_status(liquidated, "LIQUIDATED", "servicing_status")
    a.assert_money(liquidated["accrued_unpaid_interest_usd"], 0.00, "accrued_unpaid_interest_usd")
    a.assert_money(
        liquidated["current_principal_balance_usd"],
        WATERFALL_REALIZED_LOSS,
        "current_principal_balance_usd",
    )
    a.assert_money(liquidated["realized_loss_usd"], WATERFALL_REALIZED_LOSS, "realized_loss_usd")

    advance_a = validate_success(api.get_advance(scenario["advance_a_id"], ASSET_MANAGER))
    advance_b = validate_success(api.get_advance(scenario["advance_b_id"], ASSET_MANAGER))
    a.assert_status(advance_a, "REIMBURSED")
    a.assert_money(advance_a["reimbursed_interest_usd"], 6666.67, "advance A interest")
    a.assert_money(advance_a["reimbursed_principal_usd"], 200000.00, "advance A principal")
    a.assert_status(advance_b, "REIMBURSED")
    a.assert_money(advance_b["reimbursed_interest_usd"], 3750.00, "advance B interest")
    a.assert_money(advance_b["reimbursed_principal_usd"], 150000.00, "advance B principal")


def test_the_waterfall_feeds_the_trust_realized_loss_and_the_control_test(api):
    """The trust records the loss and re-runs the control test on it.

    The PRD: "The loan's `realized_loss_usd` is that sum added to whatever
    `current_principal_balance_usd` remains, rounded half up to two decimal
    places, and the trust's `realized_loss_usd` increases by the loan's figure."

    Design: Difficulty/combinatorial_formula/liquidation_fee_base_pinned_to_gross_not_net_proceeds
    """
    scenario = _executed_note_sale_ready_to_liquidate(api)

    validate_success(
        api.set_loan_servicing_status(
            scenario["loan_id"],
            f.liquidation_payload(
                WATERFALL_GROSS, WATERFALL_EXPENSES, "2026-10-01T00:00:00Z"
            ),
            ASSET_MANAGER,
        )
    )

    trust = validate_success(api.get_trust(scenario["trust_id"], ASSET_MANAGER))
    a.assert_money(trust["realized_loss_usd"], WATERFALL_REALIZED_LOSS, "realized_loss_usd")
    a.assert_money(
        trust["excess_liquidation_proceeds_usd"], 0.00, "excess_liquidation_proceeds_usd"
    )
    a.assert_money(
        trust["controlling_class_notional_usd"],
        WATERFALL_CONTROLLING_NOTIONAL,
        "controlling_class_notional_usd",
    )
    a.assert_status(trust, "CONTROLLING", "control_status")
