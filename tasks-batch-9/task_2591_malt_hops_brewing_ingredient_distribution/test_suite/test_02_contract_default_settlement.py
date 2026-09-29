"""Contract default settlement: the two damage algorithms and the fee tier."""
import pytest

from test_helpers import (
    ALLOC_1_HEADERS,
    assert_contract_conservation,
    create_brewer,
    create_contract,
    create_program,
    create_variety,
    get_brewer,
    pin_clock,
    report_harvest,
    validate_success,
)


@pytest.fixture
def settlement_pair():
    """Two identical 5,000 lb contracts at 250.00 cents, on differently-aged programs.

    Contract CM books against a 2026 program that has already reported a full
    harvest; contract CL books against a 2027 program still taking commitments.
    Nothing else differs, so the program status alone selects the algorithm.
    """
    pin_clock()
    d1 = create_brewer(name="Deltaworks Brewing", credit_limit_cents=5000000,
                       cold_chain_certified=True, legacy_trailing_lbs=0)
    d2 = create_brewer(name="Lockwood Brewing", credit_limit_cents=5000000,
                       cold_chain_certified=True, legacy_trailing_lbs=0)
    prog26 = create_program(crop_year=2026)
    prog27 = create_program(crop_year=2027)
    variety = create_variety(spot_price_cents_per_lb=51.00)
    contract_market = create_contract(
        d1["id"], variety["id"], prog26["id"], contracted_lbs=5000,
        price_per_lb_cents=250.00,
        delivery_window_start="2026-09-01T00:00:00Z",
        delivery_window_end="2026-12-31T00:00:00Z")
    contract_liquidated = create_contract(
        d2["id"], variety["id"], prog27["id"], contracted_lbs=5000,
        price_per_lb_cents=250.00,
        delivery_window_start="2027-09-01T00:00:00Z",
        delivery_window_end="2027-12-31T00:00:00Z")
    report_harvest(prog26["id"], harvest_yield_pct=100.00)
    return {"d1": d1, "d2": d2, "prog26": prog26, "prog27": prog27,
            "variety": variety, "contract_market": contract_market,
            "contract_liquidated": contract_liquidated}


def test_market_settled_damages_price_the_spread_over_current_spot(
        api, settlement_pair):
    """A reported harvest establishes a market reference, so damages are the spread.

    PRD §3.5: "Under `MARKET_SETTLED`, `settlement_damages_cents` is the
    defaulted poundage multiplied by the amount by which the contract's
    `price_per_lb_cents` exceeds the variety's current `spot_price_cents_per_lb`,
    with that per-pound difference floored at zero, rounded half up to whole
    cents"

    Design: Difficulty/dual_variant_calc/contract_default_settlement_market_vs_liquidated_damages
    """
    world = settlement_pair
    contract = validate_success(api.declare_default(
        world["contract_market"]["id"],
        {"default_reason": "brewer walked away from crop-year commitment"},
        ALLOC_1_HEADERS))

    assert contract["settlement_variant"] == "MARKET_SETTLED", (
        "the 2026 program has reported harvest, got "
        f"{contract['settlement_variant']}")
    assert contract["settlement_damages_cents"] == 995000, (
        f"5000 * (250.00 - 51.00) = 995000, got {contract['settlement_damages_cents']}")
    assert contract["settlement_admin_fee_cents"] == 19900, (
        f"995000 sits below the 1,000,000-cent tier so 2.0 percent applies, got "
        f"{contract['settlement_admin_fee_cents']}")
    assert contract["settlement_total_cents"] == 1014900, (
        f"995000 + 19900 = 1014900, got {contract['settlement_total_cents']}")
    assert contract["defaulted_lbs"] == 5000 and contract["remaining_lbs"] == 0, (
        "the whole undrawn balance moves into the defaulted bucket, got "
        f"defaulted {contract['defaulted_lbs']} remaining {contract['remaining_lbs']}")
    assert_contract_conservation(contract)

    brewer = get_brewer(world["d1"]["id"])
    assert brewer["ar_balance_cents"] == 1014900, (
        f"the settlement total posts to the ledger, got {brewer['ar_balance_cents']}")


def test_liquidated_damages_take_a_flat_share_of_contract_value_ignoring_spot(
        api, settlement_pair):
    """With no harvest reported there is no market reference, so 35 percent applies.

    PRD §3.5: "Under `LIQUIDATED`, `settlement_damages_cents` is the defaulted
    poundage multiplied by `price_per_lb_cents`, multiplied by 35 and divided by
    100, rounded half up to whole cents, with no reference to spot at all."

    Design: Difficulty/dual_variant_calc/contract_default_settlement_market_vs_liquidated_damages
    """
    world = settlement_pair
    contract = validate_success(api.declare_default(
        world["contract_liquidated"]["id"],
        {"default_reason": "brewer walked away from crop-year commitment"},
        ALLOC_1_HEADERS))

    assert contract["settlement_variant"] == "LIQUIDATED", (
        f"the 2027 program is still OPEN, got {contract['settlement_variant']}")
    assert contract["settlement_damages_cents"] == 437500, (
        f"5000 * 250.00 * 35 / 100 = 437500, got {contract['settlement_damages_cents']}")
    assert contract["settlement_admin_fee_cents"] == 8750, (
        f"437500 attracts the 2.0 percent rate, got {contract['settlement_admin_fee_cents']}")
    assert contract["settlement_total_cents"] == 446250, (
        f"437500 + 8750 = 446250, got {contract['settlement_total_cents']}")
    assert contract["defaulted_lbs"] == 5000 and contract["remaining_lbs"] == 0, (
        "the whole undrawn balance moves into the defaulted bucket, got "
        f"defaulted {contract['defaulted_lbs']} remaining {contract['remaining_lbs']}")
    assert_contract_conservation(contract)

    brewer = get_brewer(world["d2"]["id"])
    assert brewer["ar_balance_cents"] == 446250, (
        f"the settlement total posts to the ledger, got {brewer['ar_balance_cents']}")


def test_program_status_alone_makes_identical_contracts_settle_differently(
        api, settlement_pair):
    """Same poundage, same price, same variety — only the program status differs.

    PRD §3.5: "`settlement_variant` is `MARKET_SETTLED` when the contract's
    program `status` is `HARVEST_REPORTED` or `SETTLED`, and `LIQUIDATED`
    otherwise, because with no harvest reported no market reference price is
    considered established."

    Design: Difficulty/dual_variant_calc/contract_default_settlement_market_vs_liquidated_damages
    """
    world = settlement_pair
    market = validate_success(api.declare_default(
        world["contract_market"]["id"],
        {"default_reason": "brewer walked away from crop-year commitment"},
        ALLOC_1_HEADERS))
    liquidated = validate_success(api.declare_default(
        world["contract_liquidated"]["id"],
        {"default_reason": "brewer walked away from crop-year commitment"},
        ALLOC_1_HEADERS))

    assert market["settlement_total_cents"] != liquidated["settlement_total_cents"], (
        "the two algorithms must not coincide on this data, both settled at "
        f"{market['settlement_total_cents']}")
    assert (market["settlement_total_cents"], liquidated["settlement_total_cents"]) \
        == (1014900, 446250), (
        "expected 1014900 for the market spread and 446250 for the flat 35 "
        f"percent, got {market['settlement_total_cents']} and "
        f"{liquidated['settlement_total_cents']}")


@pytest.fixture
def pre_fee_tier_contract():
    """A contract whose pre-fee damages are 995,000 — 5,000 cents under the tier."""
    pin_clock()
    brewer = create_brewer(name="Kestrel Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    program = create_program(crop_year=2026)
    variety = create_variety(spot_price_cents_per_lb=51.00)
    contract = create_contract(brewer["id"], variety["id"], program["id"],
                               contracted_lbs=5000, price_per_lb_cents=250.00)
    report_harvest(program["id"], harvest_yield_pct=100.00)
    return {"brewer": brewer, "program": program, "variety": variety,
            "contract": contract}


def test_admin_fee_tier_is_read_from_the_pre_fee_damages_figure(
        api, pre_fee_tier_contract):
    """995,000 damages take the 2.0 percent rate even though 1,004,950 would not.

    PRD §3.5: "The tier selection is normative in one respect: the fee tier is
    chosen from the **pre-fee** damages figure. Choosing the tier from the
    fee-inclusive total is incorrect and flips the rate whenever damages sit just
    below the 1,000,000-cent threshold while damages-plus-fee sit at or above
    it."

    Design: Difficulty/combinatorial_formula/settlement_admin_fee_tier_read_from_pre_fee_damages_mode_c
    """
    world = pre_fee_tier_contract
    contract = validate_success(api.declare_default(
        world["contract"]["id"], {"default_reason": "non-performance"},
        ALLOC_1_HEADERS))

    assert contract["settlement_damages_cents"] == 995000, (
        f"5000 * (250.00 - 51.00) = 995000, got {contract['settlement_damages_cents']}")
    assert contract["settlement_admin_fee_cents"] == 19900, (
        f"2.0 percent of 995000, got {contract['settlement_admin_fee_cents']}")
    assert contract["settlement_admin_fee_cents"] != 9950, (
        "9950 would be 1.0 percent, the rate a fee-inclusive tier read would "
        "self-justify")
    assert contract["settlement_total_cents"] == 1014900, (
        f"995000 + 19900 = 1014900, got {contract['settlement_total_cents']}")
    assert contract["settlement_total_cents"] != 1004950, (
        "1004950 is the total produced by reading the tier from the "
        "fee-inclusive figure")


def test_the_lower_admin_percentage_belongs_to_the_larger_settlement(
        api, pre_fee_tier_contract):
    """The fee rate is inverted, so a sub-threshold settlement pays the higher rate.

    PRD §3.5: "The fee percentage is 1.0 when `settlement_damages_cents` is at
    least 1,000,000 cents and 2.0 otherwise — note the inverted direction, in
    which *larger* settlements attract the *lower* administration percentage"

    Design: Difficulty/combinatorial_formula/settlement_admin_fee_tier_read_from_pre_fee_damages_mode_c
    """
    world = pre_fee_tier_contract
    contract = validate_success(api.declare_default(
        world["contract"]["id"], {"default_reason": "non-performance"},
        ALLOC_1_HEADERS))

    damages = contract["settlement_damages_cents"]
    fee = contract["settlement_admin_fee_cents"]
    assert damages == 995000, f"expected 995000 damages, got {damages}"
    assert fee * 100 == damages * 2, (
        f"the fee must be 2.0 percent of {damages} because damages are below "
        f"1,000,000 cents, got {fee}")
    assert contract["settlement_total_cents"] == damages + fee, (
        "the settlement total is damages plus fee, got "
        f"{contract['settlement_total_cents']} against {damages} + {fee}")

    brewer = get_brewer(world["brewer"]["id"])
    assert brewer["ar_balance_cents"] == 1014900, (
        f"declaring the default posts the settlement total, got "
        f"{brewer['ar_balance_cents']}")
