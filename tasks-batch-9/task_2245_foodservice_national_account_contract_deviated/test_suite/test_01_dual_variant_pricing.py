"""Two calculations in this service each exist in two variants that must not be
interchanged: the order line's unit price (prospective versus retroactive tier
selection) and the rebate period's compliance percentage (dollar weighted
versus case weighted).
"""
from test_helpers import (
    SEP_START,
    add_substitution_rule,
    api_client,
    bootstrap_partners,
    build_signed_contract,
    build_two_band_pricing_world,
    close_rebate_period,
    create_dispute,
    create_order_line,
    create_product,
    invoice_order_line,
    open_rebate_period,
    set_availability,
    set_clock,
    start_audit,
    substitute_order_line,
    validate_success,
)
from test_helpers.fixtures import ACCOUNTANT, NAM

AUG_10 = "2026-08-10T00:00:00Z"


class TestProspectiveVersusRetroactiveTier:
    def test_early_line_keeps_the_low_volume_band_markup(self):
        """PRD §3.5: "Because the accumulated volume counts only strictly earlier
        lines, an early line keeps the low-volume band's higher markup for the
        rest of the period rather than being retroactively repriced."

        Design: Difficulty/dual_variant_calc/order_line_price_prospective_vs_retroactive_tier
        """
        world = build_two_band_pricing_world()

        line_a = validate_success(
            api_client.get_order_line(world["line_a_id"], NAM)
        )
        assert line_a["list_unit_price_cents"] == 4725
        assert line_a["invoiced_unit_price_cents"] == 4725
        assert line_a["extended_price_cents"] == 1417500
        assert line_a["applied_tier_id"] == world["tier_low_id"]

        # The second line's own prospective volume is still only the 300 cases
        # that came strictly before it, so it too sits in the [0, 500) band.
        line_b = validate_success(
            api_client.get_order_line(world["line_b_id"], NAM)
        )
        assert line_b["list_unit_price_cents"] == 4725
        assert line_b["applied_tier_id"] == world["tier_low_id"]

    def test_audit_reprices_the_same_line_over_the_whole_period_volume(self):
        """PRD §3.9: "instead of counting only lines strictly earlier than the
        disputed line, the accumulated class volume counts every line of the same
        contract and product class whose `order_date` is strictly before the
        period's `period_end`, the disputed line itself included."

        Design: Difficulty/dual_variant_calc/order_line_price_prospective_vs_retroactive_tier
        """
        world = build_two_band_pricing_world(close_clock=SEP_START)

        dispute = create_dispute(
            world["line_a_id"], world["operator_id"], 4578, "TIER_MISAPPLIED"
        )
        audited = start_audit(dispute["id"])

        assert audited["status"] == "UNDER_AUDIT"
        assert audited["audited_correct_unit_price_cents"] == 4578
        assert audited["variance_cents_per_case"] == 147
        assert audited["variance_pct"] == 3.11

        # The retroactive price is not the price the line was invoiced at.
        line_a = validate_success(api_client.get_order_line(world["line_a_id"], NAM))
        assert (
            audited["audited_correct_unit_price_cents"]
            != line_a["list_unit_price_cents"]
        )


def _build_two_basis_worlds():
    """Two contracts for the same operator over the same term with the same
    four-line purchase history, differing only in `compliance_basis`."""
    world = bootstrap_partners()
    primary = create_product(
        world["manufacturer_id"], substitution_group_code="CHKN-BREAST"
    )
    alternate = create_product(
        world["manufacturer_id"],
        sku="P-CHKN-ALT",
        description="Chicken Breast Alt 4/10#",
        last_cost_cents=4400,
        avg_cost_cents=4300,
        replacement_cost_cents=4500,
        substitution_group_code="CHKN-BREAST",
    )

    built = {}
    for key, code, basis in (
        ("dollar", "HLG-DOLLAR", "DOLLAR_WEIGHTED"),
        ("case", "HLG-CASE", "CASE_WEIGHTED"),
    ):
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[{"markup_value": 12.50, "min_case_volume": 0, "max_case_volume": 500}],
            contract_code=code,
            compliance_basis=basis,
        )
        built[key] = signed
        # The substitute is priced off its own cost, so the filled line lands at
        # 4400 * 1.125 = 4950 rather than holding the primary's 4725.
        add_substitution_rule(
            signed["contract_id"],
            primary["id"],
            alternate["id"],
            rank=1,
            price_protection_mode="SUBSTITUTE_OWN_PRICE",
        )
        built[key]["rebate_period"] = open_rebate_period(
            signed["contract_id"], "2026-08-01T00:00:00Z", SEP_START
        )

    # One contracted line each on 2026-08-05.
    set_clock("2026-08-05T00:00:00Z")
    for key in ("dollar", "case"):
        line = create_order_line(
            built[key]["contract_id"],
            primary["id"],
            world["dc_id"],
            world["operator_id"],
            300,
        )
        built[key]["line_a_id"] = line["id"]

    # One line each on 2026-08-10 that will be filled from the substitute.
    set_clock(AUG_10)
    for key in ("dollar", "case"):
        line = create_order_line(
            built[key]["contract_id"],
            primary["id"],
            world["dc_id"],
            world["operator_id"],
            300,
        )
        built[key]["line_b_id"] = line["id"]

    set_availability(primary["id"], stock_status="OUT_OF_STOCK")
    for key in ("dollar", "case"):
        built[key]["line_b"] = substitute_order_line(
            built[key]["line_b_id"],
            world["operator_id"],
            reason="Primary item unavailable at DC-SEA",
        )

    for key in ("dollar", "case"):
        invoice_order_line(built[key]["line_a_id"])
        invoice_order_line(built[key]["line_b_id"])

    set_clock(SEP_START)
    world["primary"] = primary
    world["alternate"] = alternate
    world["dollar"] = built["dollar"]
    world["case"] = built["case"]
    return world


class TestDollarWeightedVersusCaseWeightedCompliance:
    def test_dollar_weighted_basis_is_depressed_by_the_expensive_substitution(self):
        """PRD §3.7: "The contract's `compliance_basis` then chooses the ratio:
        under `DOLLAR_WEIGHTED` the numerator is `contracted_purchases_cents` and
        the denominator `gross_purchases_cents`, so an expensive non-contracted
        substitution depresses the percentage more than a cheap one; under
        `CASE_WEIGHTED` the numerator is `contracted_cases` and the denominator
        `qualifying_cases`, so the very same lines yield a different percentage
        whenever contracted and non-contracted lines differ in price per case."

        Design: Difficulty/dual_variant_calc/compliance_pct_dollar_weighted_vs_case_weighted
        """
        world = _build_two_basis_worlds()

        substituted = world["dollar"]["line_b"]
        assert substituted["product_id"] == world["alternate"]["id"]
        assert substituted["substituted_from_product_id"] == world["primary"]["id"]
        assert substituted["invoiced_unit_price_cents"] == 4950
        assert substituted["extended_price_cents"] == 1485000
        assert substituted["is_contracted_item"] is False

        closed = close_rebate_period(world["dollar"]["rebate_period"]["id"])
        assert closed["gross_purchases_cents"] == 2902500
        assert closed["contracted_purchases_cents"] == 1417500
        assert closed["qualifying_cases"] == 600
        assert closed["contracted_cases"] == 300
        assert closed["compliance_pct"] == 48.84
        assert closed["rebate_rate_pct"] == 0.00

        contract = validate_success(
            api_client.get_contract(world["dollar"]["contract_id"], NAM)
        )
        assert contract["compliance_posture"] == "RESTRICTED"

    def test_case_weighted_basis_reads_the_same_lines_as_an_even_split(self):
        """PRD §3.7: "under `CASE_WEIGHTED` the numerator is `contracted_cases`
        and the denominator `qualifying_cases`, so the very same lines yield a
        different percentage whenever contracted and non-contracted lines differ
        in price per case."

        Design: Difficulty/dual_variant_calc/compliance_pct_dollar_weighted_vs_case_weighted
        """
        world = _build_two_basis_worlds()

        dollar_closed = validate_success(
            api_client.close_rebate_period(
                world["dollar"]["rebate_period"]["id"], ACCOUNTANT
            )
        )
        case_closed = validate_success(
            api_client.close_rebate_period(
                world["case"]["rebate_period"]["id"], ACCOUNTANT
            )
        )

        assert case_closed["compliance_pct"] == 50.00
        assert case_closed["gross_purchases_cents"] == 2902500
        assert case_closed["compliance_pct"] != dollar_closed["compliance_pct"]
