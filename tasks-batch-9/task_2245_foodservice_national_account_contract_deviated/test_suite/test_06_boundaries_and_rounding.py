"""Three load-bearing numeric boundaries: the inclusive 95.00 rebate band, the
inclusive 500,000-cent service fee waiver, and the half-cent rounding of an
indexed cost reset.
"""
from test_helpers import (
    AUG_05,
    AUG_08,
    SEP_START,
    api_client,
    assert_pct,
    bootstrap_partners,
    build_signed_contract,
    close_rebate_period,
    create_notice,
    create_order_line,
    create_product,
    invoice_order_line,
    open_rebate_period,
    set_clock,
    validate_success,
)
from test_helpers.fixtures import NAM

PHOENIX_DC = {
    "dc_code": "DC-PHX",
    "name": "Phoenix DC",
    "in_market_state_codes": ["AZ"],
    "out_of_market_fee_per_case_cents": 275,
}

CHICAGO_DC = {
    "dc_code": "DC-CHI",
    "name": "Chicago DC",
    "in_market_state_codes": ["IL", "IN"],
    "out_of_market_fee_per_case_cents": 200,
}

FIVE_THOUSAND_PER_CASE_TIERS = [
    {
        "product_class_code": "PROTEIN",
        "cost_basis": "AVG_COST",
        "markup_type": "DOLLARS_PER_CASE",
        "markup_value": 150,
        "counts_as_contracted": True,
    },
    {
        "product_class_code": "DISPOSABLES",
        "cost_basis": "AVG_COST",
        "markup_type": "DOLLARS_PER_CASE",
        "markup_value": 150,
        "counts_as_contracted": False,
    },
]


def _build_boundary_compliance_worlds():
    """Two contracts of the same shape, both grossing exactly 500000 cents, one
    split 95 contracted cases to 5 and the other 94 to 6."""
    world = bootstrap_partners(
        operator={"legal_name": "Boundary Dining Group", "operator_code": "BND"},
        manufacturer={"name": "Sonoran Foods", "manufacturer_code": "SNF"},
        distribution_center=PHOENIX_DC,
    )
    contracted_item = create_product(
        world["manufacturer_id"],
        sku="P-BOUND",
        description="Beef Patty 4/10#",
        last_cost_cents=4900,
        avg_cost_cents=4850,
        replacement_cost_cents=4950,
    )
    other_item = create_product(
        world["manufacturer_id"],
        sku="P-CUP-BIG",
        description="32oz Cups 500ct",
        product_class_code="DISPOSABLES",
        pack_size=1,
        last_cost_cents=4900,
        avg_cost_cents=4850,
        replacement_cost_cents=4950,
    )

    built = {}
    for key, code, contracted_cases, other_cases in (
        ("at", "BND-95", 95, 5),
        ("below", "BND-94", 94, 6),
    ):
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=FIVE_THOUSAND_PER_CASE_TIERS,
            contract_code=code,
            compliance_basis="DOLLAR_WEIGHTED",
        )
        built[key] = signed
        built[key]["rebate_period_id"] = open_rebate_period(signed["contract_id"])["id"]
        built[key]["case_split"] = (contracted_cases, other_cases)

    set_clock(AUG_05)
    for key in ("at", "below"):
        contracted_cases, other_cases = built[key]["case_split"]
        for product, cases, line_key in (
            (contracted_item, contracted_cases, "contracted_line"),
            (other_item, other_cases, "other_line"),
        ):
            line = create_order_line(
                built[key]["contract_id"],
                product["id"],
                world["dc_id"],
                world["operator_id"],
                cases,
            )
            built[key][line_key] = invoice_order_line(line["id"])

    set_clock(SEP_START)
    world["at"] = built["at"]
    world["below"] = built["below"]
    return world


class TestComplianceAtTheTopRebateBand:
    def test_exactly_ninety_five_percent_takes_the_four_percent_band(self):
        """PRD §3.7: "`rebate_rate_pct` comes from a four-band table read against
        `compliance_pct` with inclusive lower bounds: 4.00 percent at 95.00 or
        above, 3.00 percent at 90.00 or above, 1.50 percent at 80.00 or above,
        and 0.00 percent below that."

        Design: Difficulty/boundary_precision_check/compliance_pct_exactly_95_selects_top_rebate_band
        """
        world = _build_boundary_compliance_worlds()
        boundary = world["at"]

        assert boundary["contracted_line"]["list_unit_price_cents"] == 5000
        assert boundary["contracted_line"]["extended_price_cents"] == 475000
        assert boundary["contracted_line"]["service_fee_cents"] == 0
        assert boundary["other_line"]["extended_price_cents"] == 25000
        assert boundary["other_line"]["is_contracted_item"] is False

        closed = close_rebate_period(boundary["rebate_period_id"])

        assert closed["gross_purchases_cents"] == 500000
        assert closed["contracted_purchases_cents"] == 475000
        assert_pct(closed["compliance_pct"], 95.00, "compliance_pct")
        assert_pct(closed["rebate_rate_pct"], 4.00, "rebate_rate_pct")
        assert closed["operator_rebate_cents"] == 19000
        assert closed["manufacturer_funded_cents"] == 11400
        assert closed["distributor_funded_cents"] == 7600

    def test_one_case_short_of_the_boundary_drops_to_the_three_percent_band(self):
        """PRD §2.6: "Where a threshold comparison is inclusive or strict, the
        text below says so explicitly; those boundaries are load-bearing and no
        tolerance is applied around them."

        Design: Difficulty/boundary_precision_check/compliance_pct_exactly_95_selects_top_rebate_band
        """
        world = _build_boundary_compliance_worlds()

        at_boundary = close_rebate_period(world["at"]["rebate_period_id"])
        below = close_rebate_period(world["below"]["rebate_period_id"])

        assert below["gross_purchases_cents"] == 500000
        assert below["contracted_purchases_cents"] == 470000
        assert_pct(below["compliance_pct"], 94.00, "compliance_pct")
        assert_pct(below["rebate_rate_pct"], 3.00, "rebate_rate_pct")
        assert below["operator_rebate_cents"] == 14100
        assert below["manufacturer_funded_cents"] == 8460
        assert below["distributor_funded_cents"] == 5640

        # One percentage point of compliance is worth 4900 cents of rebate here.
        assert at_boundary["operator_rebate_cents"] - below["operator_rebate_cents"] == 4900

        for key in ("at", "below"):
            contract = validate_success(
                api_client.get_contract(world[key]["contract_id"], NAM)
            )
            assert contract["compliance_posture"] == "OPEN"


def _build_fee_threshold_world():
    """An out-of-market contract whose only possible waiver is the extended-value
    threshold, with three lines at 99, 100 and 101 cases of 5000 each."""
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
    world["lines"] = {
        cases: create_order_line(
            signed["contract_id"],
            product["id"],
            world["dc_id"],
            world["operator_id"],
            cases,
        )
        for cases in (99, 100, 101)
    }
    return world


class TestServiceFeeWaiverBoundary:
    def test_waiver_starts_at_exactly_five_hundred_thousand_cents(self):
        """PRD §3.5: "`service_fee_cents` is 0 when the coverage row's
        `coverage_type` is `IN_MARKET`, or when its `service_fee_waived` is true,
        or when `extended_price_cents` is at or above five thousand dollars —
        500,000 cents."

        Design: Difficulty/boundary_precision_check/service_fee_waiver_threshold_inclusive_at_500000
        """
        lines = _build_fee_threshold_world()["lines"]

        assert lines[99]["extended_price_cents"] == 495000
        assert lines[99]["service_fee_cents"] == 27225
        assert lines[99]["invoice_total_cents"] == 522225

        assert lines[100]["extended_price_cents"] == 500000
        assert lines[100]["service_fee_cents"] == 0
        assert lines[100]["invoice_total_cents"] == 500000

        assert lines[101]["extended_price_cents"] == 505000
        assert lines[101]["service_fee_cents"] == 0
        assert lines[101]["invoice_total_cents"] == 505000

    def test_the_total_is_the_extended_value_plus_whatever_fee_survived(self):
        """PRD §3.5: "Only after the fee is settled is the total formed:
        `invoice_total_cents` is `extended_price_cents` plus `service_fee_cents`."

        Design: Difficulty/boundary_precision_check/service_fee_waiver_threshold_inclusive_at_500000
        """
        lines = _build_fee_threshold_world()["lines"]

        for cases, line in lines.items():
            assert line["cost_basis_snapshot_cents"] == 4850
            # The single unbounded tier never re-bands as volume accumulates.
            assert line["list_unit_price_cents"] == 5000
            assert line["extended_price_cents"] == 5000 * cases
            assert line["invoice_total_cents"] == (
                line["extended_price_cents"] + line["service_fee_cents"]
            )


def _build_indexed_notice_pair():
    """Two market-indexed dry-grocery items whose index resets land on an
    inexact and on an exact half cent respectively."""
    world = bootstrap_partners(
        operator={"legal_name": "Indexed Kitchens", "operator_code": "IDX"},
        manufacturer={"name": "Midwest Milling", "manufacturer_code": "MWM"},
        distribution_center=CHICAGO_DC,
    )
    inexact = create_product(
        world["manufacturer_id"],
        sku="P-INDEX",
        description="Indexed Flour 50#",
        product_class_code="DRY_GROCERY",
        pack_size=1,
        last_cost_cents=1234,
        avg_cost_cents=1234,
        replacement_cost_cents=1234,
        is_market_indexed=True,
        index_baseline_value=100.00,
        index_baseline_cost_cents=1234,
    )
    half_cent = create_product(
        world["manufacturer_id"],
        sku="P-HALF",
        description="Indexed Semolina 50#",
        product_class_code="DRY_GROCERY",
        pack_size=1,
        last_cost_cents=1000,
        avg_cost_cents=1000,
        replacement_cost_cents=1000,
        is_market_indexed=True,
        index_baseline_value=100.00,
        index_baseline_cost_cents=1000,
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
            }
        ],
        contract_code="INDEX-2026",
        notice_period_days=30,
    )
    world.update(signed)
    world["inexact"] = inexact
    world["half_cent"] = half_cent
    return world


class TestIndexedCostResetRounding:
    def test_a_fractional_reset_rounds_up_rather_than_truncating(self):
        """PRD §3.6: "`new_cost_cents` for an indexed item is the product's
        `index_baseline_cost_cents` multiplied by the supplied
        `published_index_value`, divided by the product's `index_baseline_value`,
        rounded half up to whole cents; for a non-indexed item it is simply
        `proposed_cost_cents`."

        Design: Difficulty/boundary_precision_check/indexed_cost_reset_rounds_half_up_at_exact_half_cent
        """
        world = _build_indexed_notice_pair()

        notice = create_notice(
            world["contract_id"],
            world["inexact"]["id"],
            AUG_08,
            published_index_value=107.75,
        )

        # 1234 * 107.75 / 100.00 = 1329.635, which is 1330 rather than 1329.
        assert notice["new_cost_cents"] == 1330
        assert notice["new_cost_cents"] != 1329
        assert_pct(notice["delta_pct"], 7.78, "delta_pct")
        assert notice["notice_required_days"] == 7
        assert notice["earliest_effective_at"].startswith("2026-08-08T00:00:00")
        assert notice["status"] == "PENDING"

        # A pending notice has not moved the catalogue cost.
        product = validate_success(
            api_client.get_product(world["inexact"]["id"], NAM)
        )
        assert product["last_cost_cents"] == 1234

    def test_an_exact_half_cent_reset_rounds_away_from_zero(self):
        """PRD §2.6: "Wherever a money value is produced by a multiplication or a
        division, it is rounded to whole cents with round half up **immediately
        after** that operation rather than at the end of a chain, and the pinned
        order of operations in each calculation below is part of the contract, not
        an implementation detail."

        Design: Difficulty/boundary_precision_check/indexed_cost_reset_rounds_half_up_at_exact_half_cent
        """
        world = _build_indexed_notice_pair()

        notice = create_notice(
            world["contract_id"],
            world["half_cent"]["id"],
            AUG_08,
            published_index_value=100.05,
        )

        # 1000 * 100.05 / 100.00 = 1000.5, an exact half cent.
        assert notice["new_cost_cents"] == 1001
        assert notice["new_cost_cents"] != 1000
        assert_pct(notice["delta_pct"], 0.10, "delta_pct")
        assert notice["notice_required_days"] == 7
