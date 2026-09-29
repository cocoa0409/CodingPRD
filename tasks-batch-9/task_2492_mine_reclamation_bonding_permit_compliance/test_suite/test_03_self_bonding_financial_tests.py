"""Self-bonding: the two elected financial tests and their capacity ledgers."""
from test_helpers import (
    BOND_SPECIALIST_ACCEPTER,
    PROGRAM_DIRECTOR,
    ApiErrorId,
    api_client as api,
    assert_money,
    assert_operator,
    chain_estimate_accepted,
    propose_instrument,
    refresh_operator,
    register_operator,
    validate_error,
    validate_success,
)

TWO_RIVERS = {
    "legal_name": "Two Rivers Mining Co",
    "tangible_net_worth": 24000000.00,
    "fixed_assets_in_state": 30000000.00,
    "total_liabilities": 9600000.00,
    "net_income_prior_year": 3000000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}


def test_net_worth_test_capacity_is_a_quarter_of_tangible_net_worth():
    """Under `NET_WORTH_TEST`, the operator passes when the leverage condition
    holds, the profitability condition holds, and `tangible_net_worth` is at
    least ten million dollars (10000000.00); on passing,
    `self_bond_capacity_amount` becomes `tangible_net_worth` multiplied by 0.25
    and rounded half up to two decimals.

    Design: Difficulty/dual_variant_calc/self_bond_capacity_net_worth_vs_fixed_asset_variant_divergence
    """
    operator = register_operator(**TWO_RIVERS)
    assert operator["self_bond_status"] == "UNTESTED", "no test has been run yet"

    tested = validate_success(
        api.run_financial_test(operator["id"], BOND_SPECIALIST_ACCEPTER)
    )
    assert_operator(tested)

    assert tested["elected_financial_test"] == "NET_WORTH_TEST"
    assert tested["self_bond_status"] == "QUALIFIED", (
        "leverage holds at equality (9600000.00 x 2.5 == 24000000.00), income is "
        "positive, and net worth clears ten million"
    )
    assert_money(tested["self_bond_capacity_amount"], 6000000.00, "self_bond_capacity_amount")
    assert_money(tested["self_bond_exposure_amount"], 0.00, "self_bond_exposure_amount")
    assert tested["version"] == operator["version"] + 1, "the outcome bumps the version"


def test_fixed_asset_test_capacity_is_a_tenth_of_in_state_fixed_assets():
    """Under `FIXED_ASSET_TEST`, the operator passes when the leverage condition
    holds, the profitability condition holds, and `fixed_assets_in_state` is at
    least twenty million dollars (20000000.00); on passing,
    `self_bond_capacity_amount` becomes `fixed_assets_in_state` multiplied by
    0.10 and rounded half up to two decimals.

    Design: Difficulty/dual_variant_calc/self_bond_capacity_net_worth_vs_fixed_asset_variant_divergence
    """
    operator = register_operator(**TWO_RIVERS)
    net_worth_capacity = validate_success(
        api.run_financial_test(operator["id"], BOND_SPECIALIST_ACCEPTER)
    )["self_bond_capacity_amount"]
    assert_money(net_worth_capacity, 6000000.00, "NET_WORTH_TEST capacity")

    reelected = validate_success(
        api.patch_operator_financials(
            operator["id"], {"elected_financial_test": "FIXED_ASSET_TEST"}, PROGRAM_DIRECTOR
        )
    )
    assert reelected["elected_financial_test"] == "FIXED_ASSET_TEST"
    assert reelected["self_bond_status"] == "UNTESTED", (
        "restating the election invalidates the previous conclusion"
    )
    assert_money(reelected["self_bond_capacity_amount"], 0.00, "self_bond_capacity_amount")

    retested = validate_success(
        api.run_financial_test(operator["id"], BOND_SPECIALIST_ACCEPTER)
    )
    assert retested["self_bond_status"] == "QUALIFIED", (
        "thirty million in state fixed assets clears the twenty-million floor"
    )
    assert_money(retested["self_bond_capacity_amount"], 3000000.00, "self_bond_capacity_amount")
    assert_money(
        net_worth_capacity - retested["self_bond_capacity_amount"],
        3000000.00,
        "divergence between the two elected tests",
    )


def test_leverage_condition_holds_at_exact_equality():
    """The **leverage condition** holds when `tangible_net_worth` is greater than
    or equal to the operator's `total_liabilities` multiplied by 2.5 and then
    rounded half up to two decimals; note that the comparison is made against
    the *rounded* product, and the rounding is load-bearing at the boundary.

    Design: Difficulty/boundary_precision_check/self_bond_leverage_ratio_equality_qualifies_one_cent_fails
    """
    operator = register_operator(
        legal_name="Exact Edge Aggregates",
        tangible_net_worth=10000000.00,
        fixed_assets_in_state=6000000.00,
        total_liabilities=4000000.00,
        net_income_prior_year=1000000.00,
        elected_financial_test="NET_WORTH_TEST",
    )

    tested = validate_success(
        api.run_financial_test(operator["id"], BOND_SPECIALIST_ACCEPTER)
    )

    # 4000000.00 x 2.5 == 10000000.00, exactly the tangible net worth.
    assert tested["self_bond_status"] == "QUALIFIED", (
        "the comparison is greater-than-or-equal, so equality qualifies"
    )
    assert_money(tested["self_bond_capacity_amount"], 2500000.00, "self_bond_capacity_amount")
    assert tested["registry_status"] == "ACTIVE"
    assert_money(tested["self_bond_exposure_amount"], 0.00, "self_bond_exposure_amount")


def test_one_cent_of_extra_liability_fails_the_leverage_condition():
    """A passing test moves `self_bond_status` to `QUALIFIED`; a failing test
    moves it to `FAILED` and sets `self_bond_capacity_amount` to 0.00.

    Design: Difficulty/boundary_precision_check/self_bond_leverage_ratio_equality_qualifies_one_cent_fails
    """
    operator = register_operator(
        legal_name="One Cent Over Aggregates",
        tangible_net_worth=10000000.00,
        fixed_assets_in_state=6000000.00,
        total_liabilities=4000000.01,
        net_income_prior_year=1000000.00,
        elected_financial_test="NET_WORTH_TEST",
    )

    tested = validate_success(
        api.run_financial_test(operator["id"], BOND_SPECIALIST_ACCEPTER)
    )

    # 4000000.01 x 2.5 == 10000000.025, which rounds half up to 10000000.03.
    assert tested["self_bond_status"] == "FAILED", (
        "the rounded product 10000000.03 exceeds the tangible net worth"
    )
    assert_money(tested["self_bond_capacity_amount"], 0.00, "self_bond_capacity_amount")
    assert tested["registry_status"] == "ACTIVE", "failing a test is not disqualification"
    assert_money(tested["self_bond_exposure_amount"], 0.00, "self_bond_exposure_amount")


def test_restating_any_financial_figure_resets_the_qualification():
    """Financial figures go stale, so a `ProgramDirector` may replace any subset
    of the five financial inputs — `tangible_net_worth`, `fixed_assets_in_state`,
    `total_liabilities`, `net_income_prior_year`, and `elected_financial_test` —
    on an existing operator. Replacing them invalidates whatever the last
    self-bonding test concluded: `self_bond_status` resets to `UNTESTED` from
    either `QUALIFIED` or `FAILED`, and `self_bond_capacity_amount` resets to
    0.00.

    Design: Corner/endpoints/operator_financials_patch_resets_self_bond_qualification
    """
    operator = register_operator(
        legal_name="Restated Books Mining",
        tangible_net_worth=40000000.00,
        fixed_assets_in_state=22000000.00,
        total_liabilities=8000000.00,
        net_income_prior_year=2500000.00,
        elected_financial_test="NET_WORTH_TEST",
    )
    qualified = validate_success(
        api.run_financial_test(operator["id"], BOND_SPECIALIST_ACCEPTER)
    )
    assert qualified["self_bond_status"] == "QUALIFIED"
    assert_money(qualified["self_bond_capacity_amount"], 10000000.00, "self_bond_capacity_amount")

    patched = validate_success(
        api.patch_operator_financials(
            operator["id"], {"tangible_net_worth": 30000000.00}, PROGRAM_DIRECTOR
        )
    )
    assert_operator(patched)

    assert_money(patched["tangible_net_worth"], 30000000.00, "tangible_net_worth")
    assert patched["self_bond_status"] == "UNTESTED", "a fresh test is now required"
    assert_money(patched["self_bond_capacity_amount"], 0.00, "self_bond_capacity_amount")
    assert patched["registry_status"] == "ACTIVE"
    assert_money(patched["self_bond_exposure_amount"], 0.00, "self_bond_exposure_amount")
    assert patched["version"] == qualified["version"] + 1, "the restatement is one mutation"


def test_self_bond_from_an_untested_operator_cannot_be_accepted():
    """A `SELF_BOND` instrument requires the holding operator's
    `self_bond_status` to be exactly `QUALIFIED`, else
    `ERR_SELF_BOND_NOT_QUALIFIED`.

    Design: Corner/errors/self_bond_acceptance_for_untested_operator_rejected
    """
    ctx = chain_estimate_accepted(
        operator_overrides={
            "legal_name": "Untested Self Bonder",
            "tangible_net_worth": 40000000.00,
            "fixed_assets_in_state": 22000000.00,
            "total_liabilities": 8000000.00,
            "net_income_prior_year": 2500000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={
            "name": "Untested Self Bond Pit", "county": "Nye", "total_acres": 244.00,
        },
        mining_plan_acres=120.00,
    )
    operator = refresh_operator(ctx["operator"]["id"])
    assert operator["self_bond_status"] == "UNTESTED", "the test was never run"
    assert_money(operator["self_bond_capacity_amount"], 0.00, "self_bond_capacity_amount")

    proposed = propose_instrument(
        ctx["permit"]["id"], ctx["operator_headers"],
        instrument_type="SELF_BOND", face_amount=900000.00,
    )

    response = api.accept_bond_instrument(proposed["id"], BOND_SPECIALIST_ACCEPTER)
    validate_error(response, ApiErrorId.ERR_SELF_BOND_NOT_QUALIFIED, 409)

    unchanged = validate_success(
        api.get_bond_instrument(proposed["id"], BOND_SPECIALIST_ACCEPTER)
    )
    assert unchanged["status"] == "PROPOSED", "the refused acceptance changed nothing"
    assert_money(unchanged["credited_amount"], 0.00, "credited_amount")

    permit = validate_success(api.get_permit(ctx["permit"]["id"], BOND_SPECIALIST_ACCEPTER))
    assert_money(permit["bond_held_amount"], 0.00, "bond_held_amount")
    assert_money(
        refresh_operator(ctx["operator"]["id"])["self_bond_exposure_amount"],
        0.00,
        "self_bond_exposure_amount",
    )
