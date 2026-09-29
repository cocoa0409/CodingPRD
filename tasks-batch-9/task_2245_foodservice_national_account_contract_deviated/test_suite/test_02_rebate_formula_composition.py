"""Two money formulas whose value depends on the order in which their steps are
composed: the rebate accrual, which rounds each contracted line before adding,
and the out-of-market service fee, whose waiver threshold is read off the
pre-fee line value.
"""
import pytest

from test_helpers import (
    AUG_04,
    AUG_05,
    AUG_06,
    AUG_08,
    SEP_START,
    api_client,
    assert_rebate_liability_conserved,
    assert_rebate_split,
    bootstrap_partners,
    build_signed_contract,
    close_rebate_period,
    create_order_line,
    create_product,
    invoice_order_line,
    open_rebate_period,
    set_clock,
    validate_success,
)
from test_helpers.fixtures import NAM

CHICAGO_DC = {
    "dc_code": "DC-CHI",
    "name": "Chicago DC",
    "in_market_state_codes": ["IL", "IN"],
    "out_of_market_fee_per_case_cents": 200,
}

PHOENIX_DC = {
    "dc_code": "DC-PHX",
    "name": "Phoenix DC",
    "in_market_state_codes": ["AZ"],
    "out_of_market_fee_per_case_cents": 275,
}


def _build_pantry_world():
    """Three single-case lines whose per-case rebate lands on a half cent: two
    contracted dry-grocery lines at 100 and 300 cents extended and one
    non-contracted disposables line at 100 cents.
    """
    world = bootstrap_partners(
        operator={"legal_name": "Pantry Republic", "operator_code": "PRB"},
        manufacturer={"name": "Great Lakes Provisions", "manufacturer_code": "GLP"},
        distribution_center=CHICAGO_DC,
    )
    flour = create_product(
        world["manufacturer_id"],
        sku="P-FLOUR",
        description="AP Flour 50#",
        product_class_code="DRY_GROCERY",
        pack_size=1,
        last_cost_cents=100,
        avg_cost_cents=100,
        replacement_cost_cents=100,
    )
    sugar = create_product(
        world["manufacturer_id"],
        sku="P-SUGAR",
        description="Granulated Sugar 50#",
        product_class_code="DRY_GROCERY",
        pack_size=1,
        last_cost_cents=300,
        avg_cost_cents=300,
        replacement_cost_cents=300,
    )
    cup = create_product(
        world["manufacturer_id"],
        sku="P-CUP",
        description="16oz Cups 1000ct",
        product_class_code="DISPOSABLES",
        pack_size=1,
        last_cost_cents=100,
        avg_cost_cents=100,
        replacement_cost_cents=100,
    )

    signed = build_signed_contract(
        world["operator_id"],
        world["manufacturer_id"],
        world["dc_id"],
        tiers=[
            {
                "product_class_code": "DRY_GROCERY",
                "markup_type": "DOLLARS_PER_CASE",
                "markup_value": 0,
                "counts_as_contracted": True,
            },
            {
                "product_class_code": "DISPOSABLES",
                "markup_type": "DOLLARS_PER_CASE",
                "markup_value": 0,
                "counts_as_contracted": False,
            },
        ],
        contract_code="PANTRY-2026",
        compliance_basis="DOLLAR_WEIGHTED",
    )
    world.update(signed)

    period = open_rebate_period(signed["contract_id"])
    world["rebate_period_id"] = period["id"]

    for product, clock, key in (
        (flour, AUG_04, "flour_line"),
        (sugar, AUG_06, "sugar_line"),
        (cup, AUG_08, "cup_line"),
    ):
        set_clock(clock)
        line = create_order_line(
            signed["contract_id"],
            product["id"],
            world["dc_id"],
            world["operator_id"],
            1,
        )
        world[key] = invoice_order_line(line["id"])

    set_clock(SEP_START)
    return world


class TestRebateRoundedPerLine:
    def test_two_half_cent_lines_round_up_separately_before_they_are_added(self):
        """PRD §3.7: "for each line in the contracted subset, iterated in
        `order_date` ascending order and then `created_at` ascending order, the
        line's `extended_price_cents` is multiplied by `rebate_rate_pct`, divided
        by one hundred, and rounded half up to whole cents, and those per-line
        amounts are added together."

        Design: Difficulty/combinatorial_formula/rebate_rounding_per_line_then_sum_beats_sum_then_round
        """
        world = _build_pantry_world()

        assert world["flour_line"]["extended_price_cents"] == 100
        assert world["sugar_line"]["extended_price_cents"] == 300
        assert world["cup_line"]["extended_price_cents"] == 100
        assert world["cup_line"]["is_contracted_item"] is False

        closed = close_rebate_period(world["rebate_period_id"])

        assert closed["gross_purchases_cents"] == 500
        assert closed["contracted_purchases_cents"] == 400
        assert closed["compliance_pct"] == 80.00
        assert closed["rebate_rate_pct"] == 1.50

        # 100 * 1.50 / 100 = 1.5 -> 2 and 300 * 1.50 / 100 = 4.5 -> 5, so 7.
        # Rounding the 400-cent contracted total once would have yielded 6.
        assert closed["operator_rebate_cents"] == 7
        assert closed["operator_rebate_cents"] != 6

    def test_funding_split_is_taken_once_off_the_already_rounded_total(self):
        """PRD §3.7: "The funding split is then applied once to that
        already-rounded total: `manufacturer_funded_cents` is
        `operator_rebate_cents` multiplied by sixty, divided by one hundred,
        rounded half up to whole cents — the manufacturer funds sixty percent of
        the operator rebate — and `distributor_funded_cents` is
        `operator_rebate_cents` minus `manufacturer_funded_cents`, which absorbs
        the rounding remainder."

        Design: Difficulty/combinatorial_formula/rebate_rounding_per_line_then_sum_beats_sum_then_round
        """
        world = _build_pantry_world()

        closed = close_rebate_period(world["rebate_period_id"])

        # 7 * 60 / 100 = 4.2 -> 4, and the distributor absorbs the remaining 3.
        assert closed["manufacturer_funded_cents"] == 4
        assert closed["distributor_funded_cents"] == 3
        assert_rebate_split(closed)

        contract = validate_success(
            api_client.get_contract(world["contract_id"], NAM)
        )
        assert contract["rebate_payable_cents"] == 7
        assert contract["compliance_posture"] == "WATCH"
        assert_rebate_liability_conserved(contract, [closed])

        manufacturer = validate_success(
            api_client.get_manufacturer(world["manufacturer_id"], NAM)
        )
        assert manufacturer["rebate_funding_payable_cents"] == 4


def _build_desert_line(quantity_cases):
    """One out-of-market line of `quantity_cases` cases priced at exactly 5000
    per case, on coverage whose service fee has not been waived."""
    world = bootstrap_partners(
        operator={"legal_name": "Desert Table Group", "operator_code": "DTG"},
        manufacturer={"name": "Sonoran Foods", "manufacturer_code": "SNF"},
        distribution_center=PHOENIX_DC,
    )
    product = create_product(
        world["manufacturer_id"],
        sku="P-BOUND",
        description="Beef Patty 4/10#",
        last_cost_cents=4900,
        avg_cost_cents=4850,
        replacement_cost_cents=4950,
    )
    signed = build_signed_contract(
        world["operator_id"],
        world["manufacturer_id"],
        world["dc_id"],
        tiers=[
            {
                "cost_basis": "AVG_COST",
                "markup_type": "DOLLARS_PER_CASE",
                "markup_value": 150,
            }
        ],
        coverages=[{"coverage_type": "OUT_OF_MARKET", "service_fee_waived": False}],
        contract_code="DESERT-2026",
        allow_out_of_market=True,
    )
    world.update(signed)
    open_rebate_period(signed["contract_id"])

    set_clock(AUG_05)
    world["order_line"] = create_order_line(
        signed["contract_id"],
        product["id"],
        world["dc_id"],
        world["operator_id"],
        quantity_cases,
    )
    return world


class TestServiceFeeWaiverReadsThePreFeeValue:
    def test_ninety_nine_case_line_below_the_threshold_pays_the_per_case_fee(self):
        """PRD §3.5: "`service_fee_cents` is 0 when the coverage row's
        `coverage_type` is `IN_MARKET`, or when its `service_fee_waived` is true,
        or when `extended_price_cents` is at or above five thousand dollars —
        500,000 cents."

        Design: Difficulty/combinatorial_formula/service_fee_waiver_threshold_evaluated_pre_fee_not_on_total
        """
        line = _build_desert_line(99)["order_line"]

        assert line["cost_basis_snapshot_cents"] == 4850
        assert line["list_unit_price_cents"] == 5000
        assert line["invoiced_unit_price_cents"] == 5000
        assert line["extended_price_cents"] == 495000
        assert line["service_fee_cents"] == 27225
        assert line["invoice_total_cents"] == 522225

    @pytest.mark.parametrize("quantity_cases", [95, 99])
    def test_a_total_that_crosses_the_threshold_does_not_waive_its_own_fee(
        self, quantity_cases
    ):
        """PRD §3.5: "The threshold is tested against `extended_price_cents` and
        never against `invoice_total_cents`, even though `invoice_total_cents` is
        what the operator ultimately pays; testing the total would let the fee
        decide whether the fee applies, and that reading is forbidden."

        Design: Difficulty/combinatorial_formula/service_fee_waiver_threshold_evaluated_pre_fee_not_on_total
        """
        line = _build_desert_line(quantity_cases)["order_line"]

        assert line["extended_price_cents"] == 5000 * quantity_cases
        assert line["extended_price_cents"] < 500000
        assert line["service_fee_cents"] == 275 * quantity_cases
        assert line["invoice_total_cents"] == (
            line["extended_price_cents"] + line["service_fee_cents"]
        )
        # The total is at or above the threshold, yet the fee still stands.
        assert line["invoice_total_cents"] >= 500000
        assert line["service_fee_cents"] != 0
