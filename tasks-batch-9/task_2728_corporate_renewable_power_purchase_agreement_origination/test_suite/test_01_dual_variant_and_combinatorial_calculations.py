"""Two-variant credit scoring, two-variant netting and the assembled formulas.

Every scenario here is arithmetic: the same inputs read through two different
selectors, or one formula whose evaluation order decides the answer.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import assertions as asserts  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402

# ---------------------------------------------------------------------------
# The guarantor family: one AA parent carried to QUALIFIED, one BBB parent left
# in DRAFT, and two byte-identical BB subsidiaries hanging one off each.
# ---------------------------------------------------------------------------


def _guarantor_family(api):
    """Build the parent pair and the two identical subsidiaries."""
    guarantor = fx.create_qualified_offtaker(
        api,
        anchor=False,
        legal_name="Northwind Global Holdings plc",
        credit_rating="AA",
        rating_agency="SP",
        reported_ebitda_usd=400000000.00,
        net_debt_to_ebitda=1.0,
        disclosure_framework="TCFD_ONLY",
        has_science_based_target=True,
        re100_member=True,
        scope2_target_year=2030,
    )
    unqualified_parent = fx.create_offtaker(
        api,
        legal_name="Weakling Parent SA",
        credit_rating="BBB",
        rating_agency="FITCH",
        reported_ebitda_usd=90000000.00,
        net_debt_to_ebitda=3.0,
        disclosure_framework="TCFD_ONLY",
        has_science_based_target=True,
        re100_member=True,
        scope2_target_year=2030,
    )
    subsidiary_inputs = dict(
        credit_rating="BB",
        rating_agency="SP",
        reported_ebitda_usd=20000000.00,
        net_debt_to_ebitda=4.0,
        disclosure_framework="CDP_ONLY",
        has_science_based_target=False,
        re100_member=False,
    )
    supported = fx.create_offtaker(
        api, legal_name="Northwind Retail Iberia SL",
        parent_guarantor_offtaker_id=guarantor["id"], **subsidiary_inputs)
    standalone = fx.create_offtaker(
        api, legal_name="Northwind Retail Nordics AB",
        parent_guarantor_offtaker_id=unqualified_parent["id"],
        **subsidiary_inputs)
    return {"guarantor": guarantor, "unqualified_parent": unqualified_parent,
            "supported": supported, "standalone": standalone}


def test_01_guarantor_supported_subsidiary_outscores_its_standalone_twin_by_24_95(api):
    """Identical BB subsidiaries diverge by 24.95 points on the variant alone.

    "the effective rating component becomes the greater of the buyer's own
    rating points and the guarantor's rating points reduced by 8 notch-points,
    while the effective leverage component becomes the greater of the buyer's
    own leverage points and the guarantor's leverage points."

    Design: Difficulty/dual_variant_calc/credit_score_guarantor_supported_versus_standalone_diverges_by_24_95
    """
    family = _guarantor_family(api)

    asserts.assert_score(family["guarantor"]["credit_score"], 89.60,
                         "guarantor credit_score")
    assert family["guarantor"]["credit_tier"] == "PRIME"

    supported = fx.submit_offtaker(api, family["supported"]["id"])
    standalone = fx.submit_offtaker(api, family["standalone"]["id"])

    assert supported["credit_score_variant"] == "GUARANTOR_SUPPORTED"
    asserts.assert_score(supported["credit_score"], 83.70, "supported score")
    assert supported["credit_tier"] == "PRIME"

    assert standalone["credit_score_variant"] == "STANDALONE"
    asserts.assert_score(standalone["credit_score"], 58.75, "standalone score")
    assert standalone["credit_tier"] == "SUBPRIME"

    divergence = float(supported["credit_score"]) - float(standalone["credit_score"])
    assert abs(divergence - 24.95) < 0.005, (
        f"the two variants must diverge by exactly 24.95, got {divergence}"
    )


def test_02_guarantor_linkage_alone_does_not_select_the_supported_variant(api):
    """A link to an unqualified parent leaves the subsidiary standalone.

    "The variant is `STANDALONE` whenever `parent_guarantor_offtaker_id` is
    null, **or** whenever the linked guarantor's own `qualification_status` is
    anything other than `QUALIFIED` — mere linkage is not enough, the parent
    must itself have cleared qualification."

    Design: Difficulty/dual_variant_calc/credit_score_guarantor_supported_versus_standalone_diverges_by_24_95
    """
    family = _guarantor_family(api)
    assert family["unqualified_parent"]["qualification_status"] == "DRAFT"
    assert family["standalone"]["parent_guarantor_offtaker_id"] == \
        family["unqualified_parent"]["id"]

    supported = fx.submit_offtaker(api, family["supported"]["id"])
    standalone = fx.submit_offtaker(api, family["standalone"]["id"])

    # The EBITDA limb binds under both variants: 20,000,000.00 at 5 percent for
    # PRIME and at one-half of one percent for SUBPRIME.
    asserts.assert_money(supported["unsecured_credit_limit_usd"], 1000000.00,
                         "supported unsecured_credit_limit_usd")
    asserts.assert_money(standalone["unsecured_credit_limit_usd"], 100000.00,
                         "standalone unsecured_credit_limit_usd")

    # "The disclosure component is **never** inherited", and neither is any
    # sustainability commitment, so the two twins stay identical on that axis.
    asserts.assert_score(supported["sustainability_score"], 10.00,
                         "supported sustainability_score")
    asserts.assert_score(standalone["sustainability_score"], 10.00,
                         "standalone sustainability_score")


# ---------------------------------------------------------------------------
# The netting pair: two agreements identical but for `settlement_frequency`,
# each carrying the same four metered hours over July 2027.
# ---------------------------------------------------------------------------

#: `hour_start`, `metered_mwh`, `node_price_usd_per_mwh`, `hub_price_usd_per_mwh`
JULY_HOURS = [
    ("2027-07-01T00:00:00Z", 30.50, 47.25, 50.00),
    ("2027-07-01T01:00:00Z", 20.20, 33.10, 30.00),
    ("2027-07-01T02:00:00Z", 12.75, 42.00, 44.15),
    ("2027-07-01T03:00:00Z", 10.00, -6.00, -5.00),
]

NETTING_TERMS = dict(
    product_type="VIRTUAL_CFD",
    contracted_mw=25.000,
    term_years=12,
    first_delivery_year=2027,
    commercial_operation_deadline="2027-12-31T00:00:00Z",
    base_fixed_price_usd_per_mwh=42.50,
    escalation_pct_per_year=2.0,
    shape_product="AS_GENERATED",
    basis_responsibility="SHARED",
)


def _sign_and_settle(api, deal, buyer_id):
    """Carry one deal from DRAFT to EFFECTIVE and open its July 2027 period."""
    deal_id = deal["id"]
    round_row = fx.table_round(
        api, deal_id,
        proposed_fixed_price_usd_per_mwh=deal["base_fixed_price_usd_per_mwh"],
        proposed_escalation_pct_per_year=deal["escalation_pct_per_year"],
        proposed_shape_product=deal["shape_product"],
        proposed_basis_responsibility=deal["basis_responsibility"])
    fx.confirmed_allocation(api, deal_id, buyer_id, deal["contracted_mw"])
    fx.respond_accept(api, round_row["id"], buyer_id)
    fx.submit_credit(api, deal_id)
    fx.decide_credit(api, deal_id, "APPROVE")
    signed = fx.execute_deal(api, deal_id)
    period = fx.open_period(api, deal_id, "2027-07-01T00:00:00Z",
                            "2027-08-01T00:00:00Z")
    for hour_start, metered, node_price, hub_price in JULY_HOURS:
        fx.post_interval(api, period["id"], hour_start, metered,
                         node_price_usd_per_mwh=node_price,
                         hub_price_usd_per_mwh=hub_price,
                         curtailment_flag="NONE")
    return signed, period


def _netting_pair(api):
    """One project and one buyer carrying an HOURLY deal and a MONTHLY deal."""
    hub = fx.create_hub(api)
    node = fx.create_node(api)
    buyer = fx.create_qualified_offtaker(api)
    project = fx.create_operational_project(
        api, node["id"], cod_target_date="2027-06-01T00:00:00Z")

    hourly = fx.create_deal(api, project["id"], buyer["id"], hub["id"],
                            settlement_frequency="HOURLY", **NETTING_TERMS)
    hourly, hourly_period = _sign_and_settle(api, hourly, buyer["id"])

    monthly = fx.create_deal(api, project["id"], buyer["id"], hub["id"],
                             settlement_frequency="MONTHLY", **NETTING_TERMS)
    monthly, monthly_period = _sign_and_settle(api, monthly, buyer["id"])

    return {"buyer": buyer, "project": project, "hub": hub,
            "hourly_deal": hourly, "monthly_deal": monthly,
            "hourly_period": hourly_period, "monthly_period": monthly_period}


def test_03_hourly_netting_floors_each_negative_hour_while_monthly_averages_it_in(api):
    """The same four hours settle 50.00 apart under the two netting variants.

    "The effective index for an hour is that hour's index floored at 0.00,
    because the buyer never pays a negative index under a contract for
    differences."

    Design: Difficulty/dual_variant_calc/settlement_netting_hourly_versus_monthly_diverges_by_50_00
    """
    pair = _netting_pair(api)

    asserts.assert_money(pair["hourly_deal"]["contract_price_usd_per_mwh"],
                         44.10, "hourly contract_price_usd_per_mwh")
    asserts.assert_money(pair["monthly_deal"]["contract_price_usd_per_mwh"],
                         44.10, "monthly contract_price_usd_per_mwh")

    hourly = fx.calculate_period(api, pair["hourly_period"]["id"])
    monthly = fx.calculate_period(api, pair["monthly_period"]["id"])

    assert hourly["netting_method"] == "HOURLY"
    assert monthly["netting_method"] == "MONTHLY"
    assert hourly["status"] == "CALCULATED"
    assert monthly["status"] == "CALCULATED"

    # Both variants "begin from the same index choice and the same three
    # totals", and the weighted average is unfloored under both.
    asserts.assert_mwh(hourly["total_delivered_mwh"], 73.4500,
                       "hourly total_delivered_mwh")
    asserts.assert_mwh(monthly["total_delivered_mwh"], 73.4500,
                       "monthly total_delivered_mwh")
    asserts.assert_index_price(hourly["weighted_avg_index_usd_per_mwh"], 35.9961)
    asserts.assert_index_price(monthly["weighted_avg_index_usd_per_mwh"], 35.9961)

    asserts.assert_money(hourly["energy_settlement_usd"], -545.23,
                         "hourly energy_settlement_usd")
    asserts.assert_money(monthly["energy_settlement_usd"], -595.23,
                         "monthly energy_settlement_usd")
    divergence = (float(hourly["energy_settlement_usd"])
                  - float(monthly["energy_settlement_usd"]))
    assert abs(divergence - 50.00) < 0.005, (
        f"the zero floor is worth exactly 50.00 here, got {divergence}"
    )


def test_04_both_netting_variants_share_one_basis_leg_and_one_mintable_count(api):
    """The basis leg, the payables split and the mintable count are variant-blind.

    "The basis leg is identical under both variants."

    Design: Difficulty/dual_variant_calc/settlement_netting_hourly_versus_monthly_diverges_by_50_00
    """
    pair = _netting_pair(api)
    hourly = fx.calculate_period(api, pair["hourly_period"]["id"])
    monthly = fx.calculate_period(api, pair["monthly_period"]["id"])

    asserts.assert_money(hourly["basis_adjustment_usd"], -29.33,
                         "hourly basis_adjustment_usd")
    asserts.assert_money(monthly["basis_adjustment_usd"], -29.33,
                         "monthly basis_adjustment_usd")

    asserts.assert_money(hourly["net_settlement_usd"], -574.56,
                         "hourly net_settlement_usd")
    asserts.assert_money(monthly["net_settlement_usd"], -624.56,
                         "monthly net_settlement_usd")
    asserts.assert_money(hourly["buyer_pays_usd"], 574.56, "hourly buyer_pays_usd")
    asserts.assert_money(hourly["seller_pays_usd"], 0.00, "hourly seller_pays_usd")
    asserts.assert_money(monthly["buyer_pays_usd"], 624.56, "monthly buyer_pays_usd")
    asserts.assert_money(monthly["seller_pays_usd"], 0.00, "monthly seller_pays_usd")
    asserts.assert_settlement_sign_convention(hourly)
    asserts.assert_settlement_sign_convention(monthly)

    # "`mintable_attributes_mwh` is `total_metered_mwh` truncated to a whole
    # number — a floor, never a half-up round".
    assert hourly["mintable_attributes_mwh"] == 73, hourly
    assert monthly["mintable_attributes_mwh"] == 73, monthly


# ---------------------------------------------------------------------------
# The tier-selection pair: two agreements whose escalated base straddles the
# 40.00 edge, both on a shape product whose premium is keyed by the tier.
# ---------------------------------------------------------------------------

TIER_TERMS = dict(
    product_type="PHYSICAL_DELIVERY",
    contracted_mw=10.000,
    term_years=10,
    first_delivery_year=2027,
    commercial_operation_deadline="2027-12-31T00:00:00Z",
    settlement_frequency="MONTHLY",
    shape_product="BASELOAD_FIRM",
    basis_responsibility="SHARED",
)


def _priced_deal(api, base_fixed_price_usd_per_mwh, escalation_pct_per_year):
    """Price one 10.000 MW agreement off a pre-development solar project."""
    hub = fx.create_hub(api)
    node = fx.create_node(api)
    buyer = fx.create_qualified_offtaker(api)
    project = fx.create_project(api, node["id"],
                                cod_target_date="2027-06-01T00:00:00Z")
    return fx.create_deal(
        api, project["id"], buyer["id"], hub["id"],
        base_fixed_price_usd_per_mwh=base_fixed_price_usd_per_mwh,
        escalation_pct_per_year=escalation_pct_per_year, **TIER_TERMS)


def test_05_a_base_of_38_05_escalated_to_39_1915_still_prices_at_the_low_tier(api):
    """The tier comes off the escalated base, never off the finished price.

    "Step two selects `price_tier` **from the escalated base alone**: an
    escalated base below 40.00 is `LOW`, an escalated base of at least 40.00 but
    below 60.00 is `MID`, and an escalated base of 60.00 or more is `HIGH`."

    Design: Difficulty/combinatorial_formula/contract_price_tier_selected_from_escalated_base_not_final_price
    """
    deal = _priced_deal(api, 38.05, 3.0)

    assert deal["price_tier"] == "LOW", deal
    asserts.assert_money(deal["contract_price_usd_per_mwh"], 44.44,
                         "contract_price_usd_per_mwh")
    # Reading the tier off the finished 44.44 price would charge the MID
    # baseload premium of 6.25 and land on 46.19 instead.
    assert abs(float(deal["contract_price_usd_per_mwh"]) - 46.19) > 0.005, deal

    asserts.assert_mwh(deal["expected_annual_mwh"], 24528.00,
                       "expected_annual_mwh", places=2)
    asserts.assert_money(deal["exposure_usd"], 1090024.32, "exposure_usd")
    asserts.assert_money(deal["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")
    assert deal["status"] == "DRAFT"
    assert deal["credit_status"] == "NOT_SUBMITTED"


def test_06_escalation_over_the_forty_dollar_edge_lifts_the_tier_keyed_shape_premium(api):
    """A 39.50 base escalated to 40.2900 crosses into MID and pays 6.25.

    "The shape premium is keyed on **both** `shape_product` and the `price_tier`
    just selected: `AS_GENERATED` costs nothing at any tier; `SOLAR_SHAPED_16X5`
    adds 2.00 at `LOW`, 3.10 at `MID` and 4.00 at `HIGH`; `BASELOAD_FIRM` adds
    4.50 at `LOW`, 6.25 at `MID` and 8.00 at `HIGH`, all in USD per MWh."

    Design: Difficulty/combinatorial_formula/contract_price_tier_selected_from_escalated_base_not_final_price
    """
    deal = _priced_deal(api, 39.50, 2.0)

    assert deal["price_tier"] == "MID", deal
    asserts.assert_money(deal["contract_price_usd_per_mwh"], 47.29,
                         "contract_price_usd_per_mwh")
    # Selecting the tier from the 39.50 pre-escalation base would charge the LOW
    # premium of 4.50 and land on 45.54 instead.
    assert abs(float(deal["contract_price_usd_per_mwh"]) - 45.54) > 0.005, deal

    asserts.assert_mwh(deal["expected_annual_mwh"], 24528.00,
                       "expected_annual_mwh", places=2)
    asserts.assert_money(deal["exposure_usd"], 1159929.12, "exposure_usd")
    asserts.assert_money(deal["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")


# ---------------------------------------------------------------------------
# The aggregated attribute split: three confirmed buyers at 25/15/10 MW on one
# 50.000 MW agreement, and two batches whose leftovers land differently.
# ---------------------------------------------------------------------------

AGGREGATED_TERMS = dict(
    product_type="AGGREGATED",
    contracted_mw=50.000,
    term_years=12,
    first_delivery_year=2026,
    commercial_operation_deadline="2027-12-31T00:00:00Z",
    settlement_frequency="MONTHLY",
    base_fixed_price_usd_per_mwh=22.00,
    escalation_pct_per_year=0.0,
    shape_product="AS_GENERATED",
    basis_responsibility="SHARED",
)


def _flat_period(api, deal_id, period_start, period_end, hours):
    """Open one period, post flat-priced hours into it, and calculate."""
    period = fx.open_period(api, deal_id, period_start, period_end)
    for offset, metered in enumerate(hours):
        fx.post_interval(api, period["id"],
                         fx.iso_plus(period_start, hours=offset), metered,
                         node_price_usd_per_mwh=25.00,
                         hub_price_usd_per_mwh=25.00,
                         curtailment_flag="NONE")
    return fx.calculate_period(api, period["id"])


def _aggregated_batches(api):
    """Three confirmed slices, two calculated periods and two minted batches."""
    hub = fx.create_hub(api)
    node = fx.create_node(api)
    buyer_a = fx.create_qualified_offtaker(
        api, legal_name="Aggregate Buyer A Corp",
        reported_ebitda_usd=60000000.00, registry_account_id="WREGIS-ACC-A001")
    buyer_b = fx.create_qualified_offtaker(
        api, legal_name="Aggregate Buyer B Corp",
        reported_ebitda_usd=50000000.00, registry_account_id="WREGIS-ACC-B001")
    buyer_c = fx.create_qualified_offtaker(
        api, legal_name="Aggregate Buyer C Corp",
        reported_ebitda_usd=40000000.00, registry_account_id="WREGIS-ACC-C001")
    project = fx.create_operational_project(
        api, node["id"], cod_target_date="2027-06-01T00:00:00Z")

    deal = fx.create_deal(api, project["id"], buyer_a["id"], hub["id"],
                          **AGGREGATED_TERMS)
    deal_id = deal["id"]
    round_row = fx.table_round(
        api, deal_id, proposed_fixed_price_usd_per_mwh=22.00,
        proposed_escalation_pct_per_year=0.0,
        proposed_shape_product="AS_GENERATED",
        proposed_basis_responsibility="SHARED")

    slices = {}
    for buyer, megawatts in ((buyer_a, 25.000), (buyer_b, 15.000),
                             (buyer_c, 10.000)):
        slices[buyer["id"]] = fx.propose_allocation(
            api, deal_id, buyer["id"], megawatts, joint_and_several=False)
    for buyer_id, slice_row in slices.items():
        fx.confirm_allocation(api, slice_row["id"], buyer_id)

    fx.respond_accept(api, round_row["id"], buyer_a["id"])
    fx.submit_credit(api, deal_id)
    fx.decide_credit(api, deal_id, "APPROVE")
    deal = fx.execute_deal(api, deal_id)

    july = _flat_period(api, deal_id, "2027-07-01T00:00:00Z",
                        "2027-08-01T00:00:00Z", [40.00, 40.00, 23.00])
    august = _flat_period(api, deal_id, "2027-08-01T00:00:00Z",
                          "2027-09-01T00:00:00Z", [40.00, 40.00, 25.00])

    return {
        "deal": deal, "buyer_a": buyer_a, "buyer_b": buyer_b, "buyer_c": buyer_c,
        "july": july, "august": august,
        "batch_103": fx.mint_batch(api, july["id"], 103),
        "batch_105": fx.mint_batch(api, august["id"], 105),
    }


def test_07_a_batch_of_one_hundred_and_three_breaks_by_largest_remainder_and_conserves(api):
    """Flooring first then distributing the leftover conserves the batch exactly.

    "The leftover to distribute is `quantity_mwh` less the sum of all the
    floors. The confirmed slices are then sorted by remainder descending; ties
    are broken by `allocated_mw` descending; and any remaining tie is broken by
    `created_at` ascending, which is the final arbiter — the chain never falls
    through to the row identifier."

    Design: Difficulty/combinatorial_formula/attribute_allocation_largest_remainder_conserves_batch_of_103_and_105
    """
    state = _aggregated_batches(api)

    asserts.assert_mwh(state["july"]["total_metered_mwh"], 103.0000,
                       "total_metered_mwh")
    assert state["july"]["mintable_attributes_mwh"] == 103, state["july"]

    conveyed = fx.transfer_batch(
        api, state["batch_103"]["id"], state["buyer_a"]["id"],
        registry_serial_range="WREGIS-2027-07-000001-000103")

    assert conveyed["status"] == "TRANSFERRED"
    # Remainders are 0.9 for the 15 MW slice, 0.6 for the 10 MW slice and 0.5
    # for the 25 MW slice, so the two leftover units go to the first two.
    asserts.assert_breakdown_rows(conveyed["allocation_breakdown"], [
        (state["buyer_b"]["id"], 31),
        (state["buyer_c"]["id"], 21),
        (state["buyer_a"]["id"], 51),
    ])
    assert sum(row["quantity_mwh"]
               for row in conveyed["allocation_breakdown"]) == 103


def test_08_a_remainder_tie_on_a_batch_of_one_hundred_and_five_is_broken_by_allocated_mw(api):
    """Two slices tie at 0.5, and the larger slice takes the single leftover.

    "One additional whole megawatt-hour is given to each of the first slices in
    that order, as many as the leftover count."

    Design: Difficulty/combinatorial_formula/attribute_allocation_largest_remainder_conserves_batch_of_103_and_105
    """
    state = _aggregated_batches(api)

    asserts.assert_mwh(state["august"]["total_metered_mwh"], 105.0000,
                       "total_metered_mwh")
    assert state["august"]["mintable_attributes_mwh"] == 105, state["august"]

    fx.transfer_batch(api, state["batch_103"]["id"], state["buyer_a"]["id"],
                      registry_serial_range="WREGIS-2027-07-000001-000103")
    conveyed = fx.transfer_batch(
        api, state["batch_105"]["id"], state["buyer_a"]["id"],
        registry_serial_range="WREGIS-2027-08-000001-000105")

    assert conveyed["status"] == "TRANSFERRED"
    asserts.assert_breakdown_rows(conveyed["allocation_breakdown"], [
        (state["buyer_a"]["id"], 53),
        (state["buyer_b"]["id"], 31),
        (state["buyer_c"]["id"], 21),
    ])
    assert sum(row["quantity_mwh"]
               for row in conveyed["allocation_breakdown"]) == 105

    deal = fx.read_deal(api, state["deal"]["id"])
    assert deal["attributes_minted_mwh"] == 208, deal
    assert deal["attributes_transferred_mwh"] == 208, deal
    asserts.assert_money(deal["contract_price_usd_per_mwh"], 22.75,
                         "contract_price_usd_per_mwh")
    assert deal["price_tier"] == "LOW"
    asserts.assert_money(deal["exposure_usd"], 2790060.00, "exposure_usd")
    asserts.assert_money(deal["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")
