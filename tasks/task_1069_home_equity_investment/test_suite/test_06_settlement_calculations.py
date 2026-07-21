"""Settlement calculation engine: appreciation share (SALE cap vs BUYOUT
uncapped), the round-per-component fee, the zero-appreciation floor, and the
conserved waterfall.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS,
    assert_settlement_conserved,
    fixtures,
)

ANALYST = TEST_USERS["analyst_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# --------------------------------------------------------------------------
# dual_variant_calc: SALE APR-capped vs BUYOUT uncapped appreciation share
# --------------------------------------------------------------------------
def test_sale_appreciation_share_is_apr_capped(api):
    """PRD §3.7: "For a SALE, the appreciation share is the smaller of the raw
    share and the cap — the annual cap can bind and lower the share."

    Design: Difficulty/dual_variant_calc/appreciation_share_sale_vs_buyout
    """
    ctx = fixtures.setup_exit_initiated_agreement(api, clock="2028-07-01T00:00:00Z")
    settlement = fixtures.propose_sale_settlement(
        api, ctx["agreement"]["id"], 120000000, 40000000, ctx["agreement_version"]
    )
    assert settlement["appreciation_share_cents"] == 3800000


def test_buyout_appreciation_share_is_uncapped(api):
    """PRD §3.7: "For a BUYOUT, the appreciation share is the raw share with no
    cap applied; consequently, for an identical ending value, a buyout share can
    exceed the corresponding sale share whenever the cap would have bound."

    Design: Difficulty/dual_variant_calc/appreciation_share_sale_vs_buyout
    """
    ctx = fixtures.setup_exit_initiated_agreement(api, clock="2028-07-01T00:00:00Z")
    sale = fixtures.propose_sale_settlement(
        api, ctx["agreement"]["id"], 120000000, 40000000, ctx["agreement_version"]
    )
    version2 = fixtures.agreement_version(api, ctx["agreement"]["id"])
    buyout = fixtures.propose_buyout_settlement(
        api, ctx["agreement"]["id"], 120000000, 40000000, version2
    )
    assert buyout["appreciation_share_cents"] == 12000000
    assert buyout["appreciation_share_cents"] != sale["appreciation_share_cents"]


# --------------------------------------------------------------------------
# combinatorial_formula: nested min/max with the elapsed-months cap binding
# --------------------------------------------------------------------------
def test_sale_share_bound_by_six_month_cap(api):
    """PRD §3.7: "The annualized cap is the agreement's investment_amount_cents
    multiplied by its capped_annual_rate, multiplied by elapsed_months, divided
    by twelve months in a year, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/appreciation_share_nonlinear_cap_binds
    """
    ctx = fixtures.setup_exit_initiated_agreement(api, clock="2027-01-01T00:00:00Z")
    settlement = fixtures.propose_sale_settlement(
        api, ctx["agreement"]["id"], 120000000, 40000000, ctx["agreement_version"]
    )
    assert settlement["appreciation_share_cents"] == 950000


def test_settlement_records_six_elapsed_months(api):
    """PRD §3.7: "The elapsed term (elapsed_months) is the whole number of
    calendar months from the agreement's funded_at to the current logical-clock
    instant."

    Design: Difficulty/combinatorial_formula/appreciation_share_nonlinear_cap_binds
    """
    ctx = fixtures.setup_exit_initiated_agreement(api, clock="2027-01-01T00:00:00Z")
    settlement = fixtures.propose_sale_settlement(
        api, ctx["agreement"]["id"], 120000000, 40000000, ctx["agreement_version"]
    )
    assert settlement["elapsed_months"] == 6


# --------------------------------------------------------------------------
# combinatorial_formula: round-per-component-then-sum settlement fee
# --------------------------------------------------------------------------
def _fee_scenario(api):
    return fixtures.setup_exit_initiated_agreement(
        api, clock=None,
        fund_total_cents=5000000, valued_amount_cents=5000000,
        requested_investment_cents=1000050, existing_mortgage_balance_cents=2000000,
        property_type="TOWNHOUSE",
        offer_overrides={"investment_amount_cents": 1000050, "option_percentage": 0.20},
    )


def test_settlement_fee_rounds_each_component_then_sums(api):
    """PRD §3.7: "The settlement fee (settlement_fee_cents) is assembled by
    rounding each component individually and then summing: an origination
    component of three percent of the agreement's investment_amount_cents
    rounded half up to whole cents, plus a servicing component of one percent of
    the settlement's ending_value_cents rounded half up to whole cents, plus a
    flat administrative charge of fifty thousand cents."

    Design: Difficulty/combinatorial_formula/settlement_fee_round_then_sum
    """
    ctx = _fee_scenario(api)
    settlement = fixtures.propose_sale_settlement(
        api, ctx["agreement"]["id"], 12345650, 1000000, ctx["agreement_version"]
    )
    assert settlement["settlement_fee_cents"] == 203459


def test_net_proceeds_use_round_then_sum_fee(api):
    """PRD §3.7: "Net proceeds (`net_proceeds_cents`) are the ending value minus
    the `mortgage_payoff_cents` minus the `settlement_fee_cents`."

    Design: Difficulty/combinatorial_formula/settlement_fee_round_then_sum
    """
    ctx = _fee_scenario(api)
    settlement = fixtures.propose_sale_settlement(
        api, ctx["agreement"]["id"], 12345650, 1000000, ctx["agreement_version"]
    )
    # ending 12345650 - payoff 1000000 - fee 203459 = 11142191
    assert settlement["net_proceeds_cents"] == 11142191


# --------------------------------------------------------------------------
# boundary_precision_check: zero appreciation when ending == adjusted_start
# --------------------------------------------------------------------------
def test_sale_zero_appreciation_at_equal_value(api):
    """PRD §3.7: "The raw share is the agreement's option_percentage multiplied
    by the property's gain — the greater of zero and the ending value minus the
    agreement's adjusted_start_value_cents — rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/appreciation_zero_floor_at_equal_value
    """
    ctx = fixtures.setup_exit_initiated_agreement(api, clock="2028-07-01T00:00:00Z")
    settlement = fixtures.propose_sale_settlement(
        api, ctx["agreement"]["id"], 72000000, 40000000, ctx["agreement_version"]
    )
    assert settlement["appreciation_share_cents"] == 0


def test_buyout_zero_appreciation_at_equal_value(api):
    """PRD §3.7: "The raw share is the agreement's option_percentage multiplied
    by the property's gain — the greater of zero and the ending value minus the
    agreement's adjusted_start_value_cents — rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/appreciation_zero_floor_at_equal_value
    """
    ctx = fixtures.setup_exit_initiated_agreement(api, clock="2028-07-01T00:00:00Z")
    settlement = fixtures.propose_buyout_settlement(
        api, ctx["agreement"]["id"], 72000000, 40000000, ctx["agreement_version"]
    )
    assert settlement["appreciation_share_cents"] == 0


# --------------------------------------------------------------------------
# compensating_invariant: conserved settlement waterfall
# --------------------------------------------------------------------------
def test_waterfall_share_and_fee(api):
    """PRD §3.7: "The settlement fee (settlement_fee_cents) is assembled by
    rounding each component individually and then summing: an origination
    component of three percent of the agreement's investment_amount_cents
    rounded half up to whole cents, plus a servicing component of one percent of
    the settlement's ending_value_cents rounded half up to whole cents, plus a
    flat administrative charge of fifty thousand cents."

    Design: Difficulty/compensating_invariant/settlement_proceeds_conserved_waterfall
    """
    ctx = fixtures.setup_exit_initiated_agreement(api, clock="2028-07-01T00:00:00Z")
    settlement = fixtures.propose_sale_settlement(
        api, ctx["agreement"]["id"], 120000000, 40000000, ctx["agreement_version"]
    )
    assert settlement["appreciation_share_cents"] == 3800000
    assert settlement["settlement_fee_cents"] == 1550000


def test_waterfall_net_and_homeowner_payout_conserve(api):
    """PRD §3.7: "The homeowner payout is the balancing remainder: the mortgage
    payoff, the settlement fee, the investor's returned principal, the investor's
    appreciation share, and the homeowner payout together always sum back to the
    ending value."

    Design: Difficulty/compensating_invariant/settlement_proceeds_conserved_waterfall
    """
    ctx = fixtures.setup_exit_initiated_agreement(api, clock="2028-07-01T00:00:00Z")
    settlement = fixtures.propose_sale_settlement(
        api, ctx["agreement"]["id"], 120000000, 40000000, ctx["agreement_version"]
    )
    assert settlement["net_proceeds_cents"] == 78450000
    assert settlement["homeowner_payout_cents"] == 64650000
    assert_settlement_conserved(settlement, ctx["agreement"]["investment_amount_cents"])


# --------------------------------------------------------------------------
# Queue-B corner: SALE without sale_price
# --------------------------------------------------------------------------
def test_sale_settlement_missing_price_rejected(api):
    """PRD §3.7: "A proposal missing the value required by its type is rejected
    with ERR_VALIDATION."

    Design: Corner/endpoints/settlement_sale_missing_price_returns_validation
    """
    ctx = fixtures.setup_exit_initiated_agreement(api, clock="2028-07-01T00:00:00Z")
    resp = api.create_settlement(
        ctx["agreement"]["id"],
        {"settlement_type": "SALE", "mortgage_payoff_cents": 40000000,
         "expected_agreement_version": ctx["agreement_version"]},
        COMPLIANCE,
    )
    validate_error(resp, "ERR_VALIDATION", 400)
