"""The arithmetic of the service, band by band: tier selection and markup, the
volume input set, compliance percentages, rebate bands, substitute selection,
bill-back deltas, the cash waterfall, notice windows, audit tolerance, posture
selection, cost-plus resolution and service fees.
"""
from test_helpers import (
    AUG_05,
    AUG_06,
    AUG_08,
    AUG_30,
    AUG_31,
    NOV_START,
    OCT_05,
    OCT_START,
    SEP_05,
    SEP_15,
    SEP_START,
    TERM_START,
    add_substitution_rule,
    api_client,
    assert_pct,
    bootstrap_partners,
    build_active_deviation,
    build_signed_contract,
    build_submitted_claim,
    close_rebate_period,
    create_claim,
    create_deviation,
    create_dispute,
    create_distribution_center,
    create_invoiced_line,
    create_notice,
    create_order_line,
    create_product,
    create_remittance,
    deviation_agreement_payload,
    dc_coverage_payload,
    open_rebate_period,
    price_change_notice_payload,
    read_contract_version,
    resolve_dispute,
    set_availability,
    set_clock,
    start_audit,
    substitute_order_line,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ACCOUNTANT, ANALYST, AUDITOR, NAM, add_coverage

AUG_02 = "2026-08-02T00:00:00Z"
AUG_07 = "2026-08-07T00:00:00Z"
NOV_01 = NOV_START

PROTEIN_LOW = {
    "product_class_code": "PROTEIN",
    "cost_basis": "LAST_COST",
    "markup_type": "PERCENT_OF_COST",
    "markup_value": 12.50,
    "min_case_volume": 0,
    "max_case_volume": 500,
}
PROTEIN_HIGH = {
    "product_class_code": "PROTEIN",
    "cost_basis": "LAST_COST",
    "markup_type": "PERCENT_OF_COST",
    "markup_value": 9.00,
    "min_case_volume": 500,
}
# 4000 of cost lists at 5000 under either markup type.
PROTEIN_QUARTER = {
    "product_class_code": "PROTEIN",
    "cost_basis": "LAST_COST",
    "markup_type": "PERCENT_OF_COST",
    "markup_value": 25.00,
    "min_case_volume": 0,
}
DISPOSABLES_FLAT = {
    "product_class_code": "DISPOSABLES",
    "cost_basis": "LAST_COST",
    "markup_type": "DOLLARS_PER_CASE",
    "markup_value": 1000,
    "min_case_volume": 0,
    "counts_as_contracted": False,
}

FLAT_COST = {"last_cost_cents": 4000, "avg_cost_cents": 4000, "replacement_cost_cents": 4000}


def _chicken(manufacturer_id, **overrides):
    return create_product(manufacturer_id, **dict(FLAT_COST, **overrides))


def _napkins(manufacturer_id):
    return create_product(
        manufacturer_id,
        sku="P-NAP",
        description="Dinner Napkins 6/1000",
        product_class_code="DISPOSABLES",
        pack_size=6,
        **FLAT_COST,
    )


class TestTierBandAndCostBasisMatrix:
    def test_the_band_flips_at_five_hundred_and_each_class_reads_its_own_cost(self):
        """PRD §3.5: "The tier is then the single `ACTIVE` tier of this contract
        for that product class whose `min_case_volume` is at most the accumulated
        volume and whose `max_case_volume` is either null or strictly greater than
        that volume; its id is recorded as `applied_tier_id`."

        PRD §3.5: "Under `PERCENT_OF_COST`, `list_unit_price_cents` is the frozen
        cost multiplied by one hundred plus `markup_value`, divided by one
        hundred, rounded half up to whole cents."

        Design: Corner/Calculations/tier_band_boundary_and_cost_basis_markup_matrix
        """
        world = bootstrap_partners()
        chicken = create_product(world["manufacturer_id"])
        milk = create_product(
            world["manufacturer_id"],
            sku="P-MILK",
            description="Whole Milk 4/1gal",
            product_class_code="BEVERAGE",
        )
        lettuce = create_product(
            world["manufacturer_id"],
            sku="P-LETT",
            description="Romaine 24ct",
            product_class_code="PRODUCE",
            pack_size=24,
        )
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[
                PROTEIN_LOW,
                PROTEIN_HIGH,
                {
                    "product_class_code": "BEVERAGE",
                    "cost_basis": "AVG_COST",
                    "markup_type": "DOLLARS_PER_CASE",
                    "markup_value": 150,
                    "min_case_volume": 0,
                },
                {
                    "product_class_code": "PRODUCE",
                    "cost_basis": "REPLACEMENT_COST",
                    "markup_type": "PERCENT_OF_COST",
                    "markup_value": 7.25,
                    "min_case_volume": 0,
                },
            ],
        )
        tier_low_id, tier_high_id, tier_beverage_id, tier_produce_id = signed["tier_ids"]
        open_rebate_period(signed["contract_id"], TERM_START, SEP_START)

        def line(product_id, quantity):
            return create_order_line(
                signed["contract_id"],
                product_id,
                world["dc_id"],
                world["operator_id"],
                quantity,
            )

        set_clock(AUG_05)
        first = line(chicken["id"], 499)
        set_clock(AUG_06)
        second = line(chicken["id"], 1)
        set_clock(AUG_07)
        third = line(chicken["id"], 1)
        beverage = line(milk["id"], 1)
        produce = line(lettuce["id"], 1)

        # 0 prior cases and then 499 prior cases both sit under the 500 floor.
        assert first["list_unit_price_cents"] == 4725
        assert first["applied_tier_id"] == tier_low_id
        assert second["list_unit_price_cents"] == 4725
        assert second["applied_tier_id"] == tier_low_id
        # Exactly 500 prior cases reaches the higher band's lower markup.
        assert third["list_unit_price_cents"] == 4578
        assert third["applied_tier_id"] == tier_high_id

        assert first["extended_price_cents"] == 2357775
        assert third["extended_price_cents"] == 4578

        assert beverage["cost_basis_snapshot_cents"] == 4100
        assert beverage["list_unit_price_cents"] == 4250
        assert beverage["applied_tier_id"] == tier_beverage_id

        # 4300 * 1.0725 is 4611.75, which rounds half up to 4612.
        assert produce["cost_basis_snapshot_cents"] == 4300
        assert produce["list_unit_price_cents"] == 4612
        assert produce["applied_tier_id"] == tier_produce_id

        for booked in (first, second, third, beverage, produce):
            assert booked["service_fee_cents"] == 0


class TestVolumeInputSetScope:
    def test_only_same_contract_same_class_live_lines_move_the_band(self):
        """PRD §3.5: "The server sums `quantity_cases` over the contract's other
        order lines whose product shares this line's `product_class_code`, whose
        `pricing_status` is `DRAFT_PRICED`, `INVOICED` or `REPRICED` — lines that
        have gone to `CREDITED` are excluded — and whose `order_date` is at or
        after the contract's `effective_from` and strictly earlier than this
        line's own `order_date`, excluding the line itself; the sweep runs in
        `order_date` ascending order and then `created_at` ascending order so that
        a replay is deterministic."

        Design: Corner/Calculations/tier_volume_input_set_is_scoped_by_contract_class_and_status
        """
        world = bootstrap_partners()
        chicken = create_product(world["manufacturer_id"])
        milk = create_product(
            world["manufacturer_id"],
            sku="P-MILK",
            description="Whole Milk 4/1gal",
            product_class_code="BEVERAGE",
        )
        beverage_tier = {
            "product_class_code": "BEVERAGE",
            "cost_basis": "LAST_COST",
            "markup_type": "PERCENT_OF_COST",
            "markup_value": 12.50,
            "min_case_volume": 0,
        }
        contract_a = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_LOW, PROTEIN_HIGH, beverage_tier],
            contract_code="HLG-A",
        )
        contract_b = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_LOW, PROTEIN_HIGH],
            contract_code="HLG-B",
        )
        for contract in (contract_a, contract_b):
            open_rebate_period(contract["contract_id"], TERM_START, SEP_START)

        def line(contract, product_id, quantity):
            return create_order_line(
                contract["contract_id"],
                product_id,
                world["dc_id"],
                world["operator_id"],
                quantity,
            )

        set_clock(AUG_05)
        beverage_line = line(contract_a, milk["id"], 600)
        set_clock(AUG_06)
        first_protein = line(contract_a, chicken["id"], 500)
        set_clock(AUG_07)
        second_protein = line(contract_a, chicken["id"], 1)
        sibling_protein = line(contract_b, chicken["id"], 1)

        # 600 BEVERAGE cases never enter the PROTEIN band.
        assert first_protein["pricing_status"] == "DRAFT_PRICED"
        assert first_protein["list_unit_price_cents"] == 4725
        # An uninvoiced DRAFT_PRICED line still counts toward the volume.
        assert second_protein["list_unit_price_cents"] == 4578
        assert second_protein["applied_tier_id"] == contract_a["tier_ids"][1]
        # Contract A's 501 PROTEIN cases are invisible to contract B.
        assert sibling_protein["list_unit_price_cents"] == 4725
        assert sibling_protein["applied_tier_id"] == contract_b["tier_ids"][0]

        assert beverage_line["list_unit_price_cents"] == 4725
        assert beverage_line["applied_tier_id"] == contract_a["tier_ids"][2]


def _build_two_class_world(**contract_overrides):
    """One contract pricing a contracted PROTEIN class and a non-contracted
    DISPOSABLES class, both at 5000 cents per case."""
    world = bootstrap_partners()
    world["chicken"] = _chicken(world["manufacturer_id"])
    world["napkins"] = _napkins(world["manufacturer_id"])
    signed = build_signed_contract(
        world["operator_id"],
        world["manufacturer_id"],
        world["dc_id"],
        tiers=[PROTEIN_QUARTER, DISPOSABLES_FLAT],
        **contract_overrides,
    )
    world.update(signed)
    return world


class TestCompliancePercentage:
    def test_draft_lines_are_outside_the_set_and_an_empty_set_reads_zero(self):
        """PRD §3.7: "The qualifying line set is the contract's order lines whose
        `pricing_status` is `INVOICED` or `REPRICED` — lines still `DRAFT_PRICED`
        and lines that have gone to `CREDITED` are both excluded — and whose
        `order_date` lies at or after `period_start` and strictly before
        `period_end`."

        PRD §3.7: "`compliance_pct` is the numerator multiplied by one hundred,
        divided by the denominator, rounded half up to two decimals — and when the
        denominator is zero, because the qualifying set was empty, `compliance_pct`
        is exactly `0.00`, never null and never an error."

        Design: Corner/Calculations/compliance_pct_excludes_unbilled_lines_and_empty_set_is_zero
        """
        world = _build_two_class_world()
        august = open_rebate_period(world["contract_id"], TERM_START, SEP_START)
        september = open_rebate_period(world["contract_id"], SEP_START, OCT_START)

        empty_report = validate_success(
            api_client.get_compliance_report(world["contract_id"], ACCOUNTANT)
        )
        assert empty_report["closed_period_count"] == 0
        assert empty_report["latest_compliance_pct"] is None

        contracted = create_invoiced_line(
            world["contract_id"],
            world["chicken"]["id"],
            world["dc_id"],
            world["operator_id"],
            6,
            order_clock=AUG_05,
        )
        uncontracted = create_invoiced_line(
            world["contract_id"],
            world["napkins"]["id"],
            world["dc_id"],
            world["operator_id"],
            1,
        )
        assert contracted["extended_price_cents"] == 30000
        assert uncontracted["extended_price_cents"] == 5000
        assert uncontracted["is_contracted_item"] is False

        set_clock(SEP_START)
        closed_august = close_rebate_period(august["id"])
        # 30000 contracted of 35000 gross is 85.714…, rounded half up at 2 dp.
        assert_pct(closed_august["compliance_pct"], 85.71, "compliance_pct")
        assert_pct(closed_august["rebate_rate_pct"], 1.50, "rebate_rate_pct")
        assert closed_august["operator_rebate_cents"] == 450

        report = validate_success(
            api_client.get_compliance_report(world["contract_id"], ACCOUNTANT)
        )
        assert report["closed_period_count"] == 1
        assert report["latest_period_id"] == august["id"]
        assert_pct(report["latest_compliance_pct"], 85.71, "latest_compliance_pct")
        assert_pct(report["shortfall_pct"], -0.71, "shortfall_pct")
        assert report["compliance_basis"] == "DOLLAR_WEIGHTED"

        # A line that never leaves DRAFT_PRICED keeps September's set empty.
        set_clock(SEP_05)
        unbilled = create_order_line(
            world["contract_id"],
            world["chicken"]["id"],
            world["dc_id"],
            world["operator_id"],
            6,
        )
        assert unbilled["pricing_status"] == "DRAFT_PRICED"

        set_clock(OCT_START)
        closed_september = close_rebate_period(september["id"])
        assert closed_september["gross_purchases_cents"] == 0
        assert closed_september["qualifying_cases"] == 0
        assert_pct(closed_september["compliance_pct"], 0.00, "compliance_pct")
        assert_pct(closed_september["rebate_rate_pct"], 0.00, "rebate_rate_pct")
        assert closed_september["operator_rebate_cents"] == 0


class TestRebateRateBands:
    def test_eighty_earns_the_band_and_watch_while_seventy_nine_earns_nothing(self):
        """PRD §3.7: "`rebate_rate_pct` comes from a four-band table read against
        `compliance_pct` with inclusive lower bounds: 4.00 percent at 95.00 or
        above, 3.00 percent at 90.00 or above, 1.50 percent at 80.00 or above, and
        0.00 percent below that."

        PRD §3.7: "Both comparisons are strict, so a period at exactly 80.00 is
        not `RESTRICTED` and a period exactly at the target is not `WATCH`."

        Design: Corner/Calculations/rebate_rate_band_at_eighty_and_below_eighty
        """
        world = bootstrap_partners()
        chicken = _chicken(world["manufacturer_id"])
        napkins = _napkins(world["manufacturer_id"])

        built = {}
        for key, code in (("at", "HLG-80"), ("below", "HLG-79")):
            signed = build_signed_contract(
                world["operator_id"],
                world["manufacturer_id"],
                world["dc_id"],
                tiers=[PROTEIN_QUARTER, DISPOSABLES_FLAT],
                contract_code=code,
            )
            built[key] = signed
            built[key]["period"] = open_rebate_period(
                signed["contract_id"], TERM_START, SEP_START
            )

        set_clock(AUG_05)
        for key, contracted_cases, other_cases in (("at", 80, 20), ("below", 79, 21)):
            for product_id, cases in (
                (chicken["id"], contracted_cases),
                (napkins["id"], other_cases),
            ):
                create_invoiced_line(
                    built[key]["contract_id"],
                    product_id,
                    world["dc_id"],
                    world["operator_id"],
                    cases,
                )

        set_clock(SEP_START)
        at_band = close_rebate_period(built["at"]["period"]["id"])
        below_band = close_rebate_period(built["below"]["period"]["id"])

        # 400000 contracted of 500000 gross.
        assert_pct(at_band["compliance_pct"], 80.00, "compliance_pct")
        assert_pct(at_band["rebate_rate_pct"], 1.50, "rebate_rate_pct")
        assert at_band["operator_rebate_cents"] == 6000
        assert at_band["manufacturer_funded_cents"] == 3600
        assert at_band["distributor_funded_cents"] == 2400

        # 395000 contracted of 500000 gross.
        assert_pct(below_band["compliance_pct"], 79.00, "compliance_pct")
        assert_pct(below_band["rebate_rate_pct"], 0.00, "rebate_rate_pct")
        assert below_band["operator_rebate_cents"] == 0
        assert below_band["manufacturer_funded_cents"] == 0
        assert below_band["distributor_funded_cents"] == 0

        at_contract = validate_success(
            api_client.get_contract(built["at"]["contract_id"], NAM)
        )
        assert at_contract["rebate_payable_cents"] == 6000
        assert at_contract["compliance_posture"] == "WATCH"

        below_contract = validate_success(
            api_client.get_contract(built["below"]["contract_id"], NAM)
        )
        assert below_contract["rebate_payable_cents"] == 0
        assert below_contract["compliance_posture"] == "RESTRICTED"

        manufacturer = validate_success(
            api_client.get_manufacturer(world["manufacturer_id"], NAM)
        )
        assert manufacturer["rebate_funding_payable_cents"] == 3600


def _build_substitution_world():
    """A 5000-cent primary and four candidate rules: one blocked on stock, one
    blocked on the price gap, and two tied at rank 3."""
    world = bootstrap_partners()
    group = {"substitution_group_code": "CHKN-BREAST"}
    world["primary"] = _chicken(world["manufacturer_id"], **group)
    world["out_of_stock_sub"] = create_product(
        world["manufacturer_id"],
        sku="P-SUB1",
        description="Chicken Breast Sub One 4/10#",
        last_cost_cents=4000,
        avg_cost_cents=4000,
        replacement_cost_cents=4000,
        **group,
    )
    world["expensive_sub"] = create_product(
        world["manufacturer_id"],
        sku="P-SUB2",
        description="Chicken Breast Sub Two 4/10#",
        last_cost_cents=4400,
        avg_cost_cents=4400,
        replacement_cost_cents=4400,
        **group,
    )
    world["winning_sub"] = create_product(
        world["manufacturer_id"],
        sku="P-SUB3",
        description="Chicken Breast Sub Three 4/10#",
        last_cost_cents=4160,
        avg_cost_cents=4160,
        replacement_cost_cents=4160,
        **group,
    )
    world["late_sub"] = create_product(
        world["manufacturer_id"],
        sku="P-SUB4",
        description="Chicken Breast Sub Four 4/10#",
        last_cost_cents=4200,
        avg_cost_cents=4200,
        replacement_cost_cents=4200,
        **group,
    )
    world["beef"] = create_product(
        world["manufacturer_id"],
        sku="P-BEEF",
        description="Beef Chuck 4/10#",
        last_cost_cents=4000,
        avg_cost_cents=4000,
        replacement_cost_cents=4000,
    )
    signed = build_signed_contract(
        world["operator_id"],
        world["manufacturer_id"],
        world["dc_id"],
        tiers=[PROTEIN_QUARTER],
    )
    world.update(signed)
    open_rebate_period(signed["contract_id"], TERM_START, SEP_START)

    def rule(substitute_id, rank):
        return add_substitution_rule(
            signed["contract_id"],
            world["primary"]["id"],
            substitute_id,
            rank=rank,
            price_protection_mode="SUBSTITUTE_OWN_PRICE",
            max_price_delta_pct=5.00,
        )

    world["rule_stock"] = rule(world["out_of_stock_sub"]["id"], 1)
    world["rule_gap"] = rule(world["expensive_sub"]["id"], 2)
    world["rule_winner"] = rule(world["winning_sub"]["id"], 3)
    world["rule_late"] = rule(world["late_sub"]["id"], 3)
    return world


class TestSubstituteSelection:
    def test_stock_gap_rank_and_created_at_decide_the_fill_in_one_call(self):
        """PRD §3.5: "Surviving candidates are ordered by `rank` ascending and,
        when two rules share a rank, by `created_at` ascending; ties are never
        broken by id."

        Design: Corner/Calculations/substitute_selection_filters_ranks_and_breaks_ties_by_created_at
        """
        world = _build_substitution_world()
        set_clock(AUG_05)
        line = create_order_line(
            world["contract_id"],
            world["primary"]["id"],
            world["dc_id"],
            world["operator_id"],
            10,
        )
        assert line["list_unit_price_cents"] == 5000

        # Substitution is only for an item that has actually run out.
        validate_error(
            api_client.substitute_order_line(
                line["id"], world["buyer"], {"reason": "Speculative fill"}
            ),
            "ERR_PRODUCT_IN_STOCK",
            409,
        )

        set_availability(world["primary"]["id"], stock_status="OUT_OF_STOCK")
        set_availability(world["out_of_stock_sub"]["id"], stock_status="OUT_OF_STOCK")

        filled = substitute_order_line(
            line["id"], world["operator_id"], reason="Primary item unavailable"
        )
        assert filled["substitution_rule_id"] == world["rule_winner"]["id"]
        assert filled["product_id"] == world["winning_sub"]["id"]
        assert filled["substituted_from_product_id"] == world["primary"]["id"]
        assert filled["invoiced_unit_price_cents"] == 5200
        assert filled["extended_price_cents"] == 52000
        assert filled["is_contracted_item"] is False
        # The fill is a self-loop on the pricing dimension.
        assert filled["pricing_status"] == "DRAFT_PRICED"
        assert (
            world["rule_winner"]["created_at"] <= world["rule_late"]["created_at"]
        )

        beef_line = create_order_line(
            world["contract_id"],
            world["beef"]["id"],
            world["dc_id"],
            world["operator_id"],
            10,
        )
        set_availability(world["beef"]["id"], stock_status="OUT_OF_STOCK")
        validate_error(
            api_client.substitute_order_line(
                beef_line["id"], world["buyer"], {"reason": "No candidates exist"}
            ),
            "ERR_NO_ELIGIBLE_SUBSTITUTE",
            409,
        )
        unchanged = validate_success(api_client.get_order_line(beef_line["id"], NAM))
        assert unchanged["product_id"] == world["beef"]["id"]

    def test_a_gap_of_exactly_the_cap_still_wins_the_candidate_set(self):
        """PRD §3.5: "The gap is computed from the two list prices the markup step
        produces for the primary item and for the substitute under the same tier
        lookup and the same `order_date`: it is the absolute difference between the
        substitute's list price and the primary's list price, multiplied by one
        hundred, divided by the primary's list price, rounded half up to two
        decimals, and the rule survives when that figure is less than or equal to
        its `max_price_delta_pct` — the comparison is inclusive."

        Design: Corner/Calculations/substitute_selection_filters_ranks_and_breaks_ties_by_created_at
        """
        world = _build_substitution_world()
        # A second contract carrying only the 5.00-gap rule.
        cap_contract = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_QUARTER],
            contract_code="HLG-CAP",
        )
        add_substitution_rule(
            cap_contract["contract_id"],
            world["primary"]["id"],
            world["late_sub"]["id"],
            rank=1,
            price_protection_mode="SUBSTITUTE_OWN_PRICE",
            max_price_delta_pct=5.00,
        )
        open_rebate_period(cap_contract["contract_id"], TERM_START, SEP_START)

        set_clock(AUG_05)
        line = create_order_line(
            cap_contract["contract_id"],
            world["primary"]["id"],
            world["dc_id"],
            world["operator_id"],
            10,
        )
        set_availability(world["primary"]["id"], stock_status="OUT_OF_STOCK")

        filled = substitute_order_line(
            line["id"], world["operator_id"], reason="Primary item unavailable"
        )
        # 5250 against 5000 is exactly 5.00 percent, which the cap admits.
        assert filled["product_id"] == world["late_sub"]["id"]
        assert filled["invoiced_unit_price_cents"] == 5250
        assert filled["extended_price_cents"] == 52500


def _build_clamped_claim_world():
    """One deviation priced above list and a sibling priced below it, each with a
    single ten-case invoiced line."""
    world = bootstrap_partners()
    world["chicken"] = _chicken(world["manufacturer_id"])
    world["beef"] = create_product(
        world["manufacturer_id"],
        sku="P-BEEF",
        description="Beef Chuck 4/10#",
        last_cost_cents=4000,
        avg_cost_cents=4000,
        replacement_cost_cents=4000,
    )
    signed = build_signed_contract(
        world["operator_id"],
        world["manufacturer_id"],
        world["dc_id"],
        tiers=[PROTEIN_QUARTER],
    )
    world.update(signed)
    open_rebate_period(signed["contract_id"], TERM_START, SEP_START)

    world["above_list"] = build_active_deviation(
        signed["contract_id"],
        world["chicken"]["id"],
        world["manufacturer_id"],
        5300,
        TERM_START,
        SEP_START,
        requested_net_price_cents=5200,
    )
    world["below_list"] = build_active_deviation(
        signed["contract_id"],
        world["beef"]["id"],
        world["manufacturer_id"],
        5000,
        TERM_START,
        SEP_START,
        requested_net_price_cents=4200,
    )
    world["high_line"] = create_invoiced_line(
        signed["contract_id"],
        world["chicken"]["id"],
        world["dc_id"],
        world["operator_id"],
        10,
        order_clock=AUG_05,
    )
    world["low_line"] = create_invoiced_line(
        signed["contract_id"],
        world["beef"]["id"],
        world["dc_id"],
        world["operator_id"],
        10,
    )
    return world


class TestBillBackDeltaClamp:
    def test_a_deviation_above_list_recovers_zero_rather_than_a_negative(self):
        """PRD §3.8: "`claimed_amount_cents` accumulates, over the same lines
        iterated in `order_date` ascending order and then `created_at` ascending
        order, the greater of zero and the difference between the line's
        `list_unit_price_cents` and its `invoiced_unit_price_cents`, multiplied by
        that line's `quantity_cases`; clamping each per-line delta at zero means a
        held contract price above list can never produce a negative claim."

        Design: Corner/Calculations/bill_back_delta_is_clamped_at_zero_per_line
        """
        world = _build_clamped_claim_world()
        assert world["high_line"]["list_unit_price_cents"] == 5000
        assert world["high_line"]["invoiced_unit_price_cents"] == 5200

        zero_claim = create_claim(world["above_list"]["id"], TERM_START, SEP_START)
        assert zero_claim["claimed_cases"] == 10
        # max(0, 5000 - 5200) is 0, never -200.
        assert zero_claim["claimed_amount_cents"] == 0
        assert zero_claim["status"] == "ACCRUED"

        normal_claim = build_submitted_claim(
            world["below_list"]["id"], TERM_START, SEP_START
        )
        assert normal_claim["claimed_amount_cents"] == 8000
        assert normal_claim["status"] == "SUBMITTED"

        for key in ("high_line", "low_line"):
            line = validate_success(
                api_client.get_order_line(world[key]["id"], NAM)
            )
            assert line["billback_status"] == "CLAIMED"

        manufacturer = validate_success(
            api_client.get_manufacturer(world["manufacturer_id"], NAM)
        )
        # The accrued zero claim contributes nothing to the exposure.
        assert manufacturer["open_claim_exposure_cents"] == 8000


def _build_waterfall_world():
    """Three claims of one manufacturer: a disputed one starting 2026-08-01, a
    submitted 8000 starting 2026-08-05 and a submitted 16000 starting
    2026-09-01, the September claim created first."""
    world = bootstrap_partners()
    world["chicken"] = _chicken(world["manufacturer_id"])
    world["beef"] = create_product(
        world["manufacturer_id"],
        sku="P-BEEF",
        description="Beef Chuck 4/10#",
        last_cost_cents=4000,
        avg_cost_cents=4000,
        replacement_cost_cents=4000,
    )
    signed = build_signed_contract(
        world["operator_id"],
        world["manufacturer_id"],
        world["dc_id"],
        tiers=[PROTEIN_QUARTER],
    )
    world.update(signed)
    open_rebate_period(signed["contract_id"], TERM_START, SEP_START)
    open_rebate_period(signed["contract_id"], SEP_START, OCT_START)

    world["chicken_deviation"] = build_active_deviation(
        signed["contract_id"],
        world["chicken"]["id"],
        world["manufacturer_id"],
        5000,
        TERM_START,
        OCT_START,
        requested_net_price_cents=4200,
    )
    world["beef_deviation"] = build_active_deviation(
        signed["contract_id"],
        world["beef"]["id"],
        world["manufacturer_id"],
        5000,
        TERM_START,
        OCT_START,
        requested_net_price_cents=4200,
    )

    world["beef_line"] = create_invoiced_line(
        signed["contract_id"],
        world["beef"]["id"],
        world["dc_id"],
        world["operator_id"],
        10,
        order_clock=AUG_02,
    )
    world["august_line"] = create_invoiced_line(
        signed["contract_id"],
        world["chicken"]["id"],
        world["dc_id"],
        world["operator_id"],
        10,
        order_clock=AUG_05,
    )
    world["september_line"] = create_invoiced_line(
        signed["contract_id"],
        world["chicken"]["id"],
        world["dc_id"],
        world["operator_id"],
        20,
        order_clock=SEP_05,
    )

    # Created newest-window-first on purpose.
    world["claim_september"] = build_submitted_claim(
        world["chicken_deviation"]["id"], SEP_START, OCT_START
    )
    world["claim_august"] = build_submitted_claim(
        world["chicken_deviation"]["id"], AUG_05, SEP_START
    )
    disputed = build_submitted_claim(
        world["beef_deviation"]["id"], TERM_START, AUG_05
    )
    world["claim_disputed"] = validate_success(
        api_client.dispute_bill_back_claim(
            disputed["id"],
            {"note": "Program terms under review"},
            world["rep"],
        )
    )
    return world


class TestRemittanceWaterfall:
    def test_cash_fills_the_earliest_window_first_and_skips_the_disputed_claim(self):
        """PRD §3.8: "The cash is then poured through a waterfall over that
        manufacturer's claims whose status is `SUBMITTED` or
        `PARTIALLY_RECOVERED` — claims that are `ACCRUED`, `DISPUTED`, `RECOVERED`
        or `WRITTEN_OFF` are skipped — taken in `claim_period_start` ascending
        order and then `created_at` ascending order, never by id, so the oldest
        claim period is satisfied first."

        PRD §3.8: "Attempting to reverse a remittance that is already `REVERSED`
        is `ERR_REMITTANCE_INVALID_STATE`."

        Design: Corner/Calculations/remittance_waterfall_fills_oldest_period_first_and_skips_disputed
        """
        world = _build_waterfall_world()
        august = world["claim_august"]
        september = world["claim_september"]
        disputed = world["claim_disputed"]

        assert august["claimed_amount_cents"] == 8000
        assert september["claimed_amount_cents"] == 16000
        assert disputed["claimed_amount_cents"] == 8000
        assert disputed["status"] == "DISPUTED"

        remittance = create_remittance(
            world["manufacturer_id"], 10000, remittance_reference="CPC-WIRE-0001"
        )
        assert remittance["applied_amount_cents"] == 10000
        assert remittance["unapplied_amount_cents"] == 0

        filled = validate_success(api_client.get_bill_back_claim(august["id"], NAM))
        assert filled["recovered_amount_cents"] == 8000
        assert filled["status"] == "RECOVERED"

        partial = validate_success(
            api_client.get_bill_back_claim(september["id"], NAM)
        )
        assert partial["recovered_amount_cents"] == 2000
        assert partial["status"] == "PARTIALLY_RECOVERED"

        skipped = validate_success(
            api_client.get_bill_back_claim(disputed["id"], NAM)
        )
        assert skipped["recovered_amount_cents"] == 0
        assert skipped["version"] == disputed["version"]

        assert (
            validate_success(
                api_client.get_order_line(world["august_line"]["id"], NAM)
            )["billback_status"]
            == "RECOVERED"
        )
        assert (
            validate_success(
                api_client.get_order_line(world["september_line"]["id"], NAM)
            )["billback_status"]
            == "CLAIMED"
        )

        reversed_remittance = validate_success(
            api_client.reverse_bill_back_remittance(
                remittance["id"], {"reason": "Wire recalled by the manufacturer"},
                ACCOUNTANT,
            )
        )
        assert reversed_remittance["status"] == "REVERSED"

        for claim_id in (august["id"], september["id"]):
            restored = validate_success(api_client.get_bill_back_claim(claim_id, NAM))
            assert restored["recovered_amount_cents"] == 0
            assert restored["status"] == "SUBMITTED"

        assert (
            validate_success(
                api_client.get_order_line(world["august_line"]["id"], NAM)
            )["billback_status"]
            == "CLAIMED"
        )
        assert (
            validate_success(
                api_client.get_manufacturer(world["manufacturer_id"], NAM)
            )["total_remitted_cents"]
            == 0
        )

        validate_error(
            api_client.reverse_bill_back_remittance(
                remittance["id"], {"reason": "Second attempt"}, ACCOUNTANT
            ),
            "ERR_REMITTANCE_INVALID_STATE",
            409,
        )


def _build_notice_world():
    """Four items at 4000 cents of cost on one live contract, three plain and one
    market-indexed off a 4000 / 100.00 baseline."""
    world = bootstrap_partners()
    world["plain_a"] = _chicken(world["manufacturer_id"], sku="P-CHKN-A")
    world["plain_b"] = _chicken(world["manufacturer_id"], sku="P-CHKN-B")
    world["plain_c"] = _chicken(world["manufacturer_id"], sku="P-CHKN-C")
    world["indexed"] = _chicken(
        world["manufacturer_id"],
        sku="P-CHKN-I",
        is_market_indexed=True,
        index_baseline_cost_cents=4000,
        index_baseline_value=100.00,
    )
    signed = build_signed_contract(
        world["operator_id"],
        world["manufacturer_id"],
        world["dc_id"],
        tiers=[PROTEIN_QUARTER],
    )
    world.update(signed)
    return world


class TestNoticeWindowThreshold:
    def test_ten_percent_is_major_on_both_the_plain_and_the_indexed_path(self):
        """PRD §3.6: "`notice_required_days` follows from that delta: when the
        magnitude of `delta_pct` is at or above ten percent the change is major and
        the contract's own `notice_period_days` applies; below that magnitude, the
        minor-change window of seven days applies."

        PRD §3.6: "`new_cost_cents` for an indexed item is the product's
        `index_baseline_cost_cents` multiplied by the supplied
        `published_index_value`, divided by the product's `index_baseline_value`,
        rounded half up to whole cents; for a non-indexed item it is simply
        `proposed_cost_cents`."

        Design: Corner/Calculations/notice_window_flips_at_exactly_ten_percent_on_both_cost_paths
        """
        world = _build_notice_world()

        minor = create_notice(
            world["contract_id"],
            world["plain_a"]["id"],
            AUG_08,
            proposed_cost_cents=4396,
        )
        assert minor["new_cost_cents"] == 4396
        assert_pct(minor["delta_pct"], 9.90, "delta_pct")
        assert minor["notice_required_days"] == 7
        assert minor["earliest_effective_at"].startswith("2026-08-08T00:00:00")

        # 30 days from 2026-08-01 lands on 2026-08-31, so 2026-08-30 is short.
        validate_error(
            api_client.create_price_change_notice(
                price_change_notice_payload(
                    world["contract_id"],
                    world["plain_b"]["id"],
                    AUG_30,
                    proposed_cost_cents=4400,
                ),
                ANALYST,
            ),
            "ERR_NOTICE_PERIOD_TOO_SHORT",
            422,
        )

        at_threshold = create_notice(
            world["contract_id"],
            world["plain_b"]["id"],
            AUG_31,
            proposed_cost_cents=4400,
        )
        assert_pct(at_threshold["delta_pct"], 10.00, "delta_pct")
        assert at_threshold["notice_required_days"] == 30
        assert at_threshold["earliest_effective_at"].startswith("2026-08-31T00:00:00")

        above_threshold = create_notice(
            world["contract_id"],
            world["plain_c"]["id"],
            SEP_15,
            proposed_cost_cents=4404,
        )
        assert_pct(above_threshold["delta_pct"], 10.10, "delta_pct")
        assert above_threshold["notice_required_days"] == 30

        # An indexed item must be priced through its index, not a flat cost.
        validate_error(
            api_client.create_price_change_notice(
                price_change_notice_payload(
                    world["contract_id"],
                    world["indexed"]["id"],
                    OCT_START,
                    proposed_cost_cents=4400,
                ),
                ANALYST,
            ),
            "ERR_INDEX_VALUE_REQUIRED",
            422,
        )

        indexed = create_notice(
            world["contract_id"],
            world["indexed"]["id"],
            AUG_31,
            published_index_value=110.00,
        )
        # 4000 * 110.00 / 100.00 is 4400.
        assert indexed["new_cost_cents"] == 4400
        assert_pct(indexed["delta_pct"], 10.00, "delta_pct")
        assert indexed["notice_required_days"] == 30

        for notice in (minor, at_threshold, above_threshold, indexed):
            assert notice["status"] == "PENDING"

        # A pending notice moves no cost at all.
        assert (
            validate_success(
                api_client.get_product(world["plain_a"]["id"], NAM)
            )["last_cost_cents"]
            == 4000
        )


def _build_tolerance_contract(world, product_id, high_band_markup, contract_code):
    """A single 500-case line invoiced from the entry band, whose retroactive
    band is `high_band_markup` cents above cost."""
    signed = build_signed_contract(
        world["operator_id"],
        world["manufacturer_id"],
        world["dc_id"],
        tiers=[
            {
                "product_class_code": "PROTEIN",
                "cost_basis": "LAST_COST",
                "markup_type": "DOLLARS_PER_CASE",
                "markup_value": 1000,
                "min_case_volume": 0,
                "max_case_volume": 500,
            },
            {
                "product_class_code": "PROTEIN",
                "cost_basis": "LAST_COST",
                "markup_type": "DOLLARS_PER_CASE",
                "markup_value": high_band_markup,
                "min_case_volume": 500,
            },
        ],
        contract_code=contract_code,
    )
    period = open_rebate_period(signed["contract_id"], TERM_START, SEP_START)
    signed["rebate_period_id"] = period["id"]
    signed["line"] = create_invoiced_line(
        signed["contract_id"],
        product_id,
        world["dc_id"],
        world["operator_id"],
        500,
        order_clock=AUG_05,
    )
    return signed


class TestAuditTolerance:
    def test_exactly_half_a_percent_is_upheld_and_a_shade_under_is_refused(self):
        """PRD §3.9: "The `UPHELD` branch is gated twice: `variance_pct` must be at
        or above the audit tolerance of 0.50 percent — the comparison is inclusive
        — and `variance_cents_per_case` must be strictly greater than zero, meaning
        the operator really was overcharged rather than favoured."

        Design: Corner/Calculations/audit_tolerance_is_inclusive_at_half_a_percent
        """
        world = bootstrap_partners()
        product = create_product(
            world["manufacturer_id"],
            last_cost_cents=3000,
            avg_cost_cents=3000,
            replacement_cost_cents=3000,
        )
        inside = _build_tolerance_contract(world, product["id"], 980, "HLG-IN")
        outside = _build_tolerance_contract(world, product["id"], 981, "HLG-OUT")

        assert inside["line"]["invoiced_unit_price_cents"] == 4000
        assert outside["line"]["invoiced_unit_price_cents"] == 4000

        set_clock(SEP_START)
        close_rebate_period(inside["rebate_period_id"])
        close_rebate_period(outside["rebate_period_id"])

        inside_dispute = create_dispute(
            inside["line"]["id"], world["operator_id"], 3980, "TIER_MISAPPLIED"
        )
        inside_audited = start_audit(inside_dispute["id"])
        assert inside_audited["audited_correct_unit_price_cents"] == 3980
        assert inside_audited["variance_cents_per_case"] == 20
        assert_pct(inside_audited["variance_pct"], 0.50, "variance_pct")

        upheld = resolve_dispute(
            inside_dispute["id"], "UPHELD", "Retroactive band applies"
        )
        assert upheld["status"] == "UPHELD"

        outside_dispute = create_dispute(
            outside["line"]["id"], world["operator_id"], 3981, "TIER_MISAPPLIED"
        )
        outside_audited = start_audit(outside_dispute["id"])
        assert outside_audited["audited_correct_unit_price_cents"] == 3981
        assert outside_audited["variance_cents_per_case"] == 19
        # 19 * 100 / 4000 is 0.475, which rounds half up to 0.48.
        assert_pct(outside_audited["variance_pct"], 0.48, "variance_pct")

        validate_error(
            api_client.resolve_pricing_dispute(
                outside_dispute["id"],
                {"resolution": "UPHELD", "note": "Below tolerance"},
                AUDITOR,
            ),
            "ERR_VARIANCE_BELOW_AUDIT_TOLERANCE",
            422,
        )
        still_auditing = validate_success(
            api_client.get_pricing_dispute(outside_dispute["id"], AUDITOR)
        )
        assert still_auditing["status"] == "UNDER_AUDIT"

        rejected = resolve_dispute(
            outside_dispute["id"], "REJECTED", "Variance inside tolerance"
        )
        assert rejected["status"] == "REJECTED"

        # Resolving alone issues no credit.
        assert (
            validate_success(
                api_client.get_order_line(inside["line"]["id"], NAM)
            )["pricing_status"]
            == "INVOICED"
        )


class TestPostureSelectsLatestPeriod:
    def test_the_greatest_period_start_wins_over_the_most_recent_close(self):
        """PRD §3.7: "The posture reads the single most recent rebate period of the
        contract whose status is `CLOSED` or `SETTLED`, ordered by `period_start`
        descending and then `created_at` descending; periods that are `OPEN`,
        including ones an audit credit has reopened, are ignored entirely."

        Design: Corner/Calculations/posture_reads_latest_period_by_period_start_not_close_order
        """
        world = _build_two_class_world()
        august = open_rebate_period(world["contract_id"], TERM_START, SEP_START)
        september = open_rebate_period(world["contract_id"], SEP_START, OCT_START)
        october = open_rebate_period(world["contract_id"], OCT_START, NOV_01)

        def book(clock, contracted_cases, other_cases):
            set_clock(clock)
            create_invoiced_line(
                world["contract_id"],
                world["chicken"]["id"],
                world["dc_id"],
                world["operator_id"],
                contracted_cases,
            )
            if other_cases:
                create_invoiced_line(
                    world["contract_id"],
                    world["napkins"]["id"],
                    world["dc_id"],
                    world["operator_id"],
                    other_cases,
                )

        book(AUG_05, 85, 15)
        book(SEP_05, 60, 40)
        book(OCT_05, 100, 0)

        set_clock(NOV_01)
        closed_august = close_rebate_period(august["id"])
        assert_pct(closed_august["compliance_pct"], 85.00, "compliance_pct")
        assert_pct(closed_august["rebate_rate_pct"], 1.50, "rebate_rate_pct")
        assert closed_august["operator_rebate_cents"] == 6375

        first_report = validate_success(
            api_client.get_compliance_report(world["contract_id"], ACCOUNTANT)
        )
        # 85.00 is neither below the 80.00 floor nor below the 85.00 target.
        assert first_report["compliance_posture"] == "OPEN"
        assert first_report["closed_period_count"] == 1
        assert first_report["latest_period_id"] == august["id"]

        closed_october = close_rebate_period(october["id"])
        assert_pct(closed_october["compliance_pct"], 100.00, "compliance_pct")
        assert_pct(closed_october["rebate_rate_pct"], 4.00, "rebate_rate_pct")
        assert closed_october["operator_rebate_cents"] == 20000

        closed_september = close_rebate_period(september["id"])
        assert_pct(closed_september["compliance_pct"], 60.00, "compliance_pct")
        assert_pct(closed_september["rebate_rate_pct"], 0.00, "rebate_rate_pct")
        assert closed_september["operator_rebate_cents"] == 0

        second_report = validate_success(
            api_client.get_compliance_report(world["contract_id"], ACCOUNTANT)
        )
        # September was closed last, but October starts later.
        assert second_report["latest_period_id"] == october["id"]
        assert_pct(
            second_report["latest_compliance_pct"], 100.00, "latest_compliance_pct"
        )
        assert second_report["compliance_posture"] == "OPEN"
        assert second_report["closed_period_count"] == 3

        contract = validate_success(
            api_client.get_contract(world["contract_id"], NAM)
        )
        assert contract["rebate_payable_cents"] == 26375
        assert (
            validate_success(
                api_client.get_manufacturer(world["manufacturer_id"], NAM)
            )["rebate_funding_payable_cents"]
            == 15825
        )


class TestCostPlusEntryBand:
    def test_the_protected_price_reads_the_zero_volume_tier_and_nothing_else(self):
        """PRD §3.4: "Under `COST_PLUS_PROTECTED` the analyst supplies
        `protected_discount_cents`, greater than zero, and must leave
        `requested_net_price_cents` null; `deviated_price_cents` is then the item's
        current cost on the relevant basis minus that protected discount, where the
        cost basis is the one named by the contract's entry-band tier — the single
        `ACTIVE` tier of this contract covering the product's class at case volume
        zero, that is, the tier whose `min_case_volume` is 0."

        Design: Corner/Calculations/cost_plus_deviation_resolves_from_the_entry_band_tier
        """
        world = bootstrap_partners()
        chicken = create_product(world["manufacturer_id"])
        beef = create_product(
            world["manufacturer_id"],
            sku="P-BEEF",
            description="Beef Chuck 4/10#",
            last_cost_cents=6000,
            avg_cost_cents=5900,
            replacement_cost_cents=6100,
        )
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[
                {
                    "product_class_code": "PROTEIN",
                    "cost_basis": "AVG_COST",
                    "markup_type": "PERCENT_OF_COST",
                    "markup_value": 12.50,
                    "min_case_volume": 0,
                    "max_case_volume": 500,
                },
                {
                    "product_class_code": "PROTEIN",
                    "cost_basis": "LAST_COST",
                    "markup_type": "PERCENT_OF_COST",
                    "markup_value": 12.50,
                    "min_case_volume": 500,
                },
            ],
        )
        entry_tier_id, high_tier_id = signed["tier_ids"]

        cost_plus = create_deviation(
            signed["contract_id"],
            chicken["id"],
            world["manufacturer_id"],
            4500,
            TERM_START,
            SEP_START,
            bill_back_basis="COST_PLUS_PROTECTED",
            protected_discount_cents=300,
        )
        # The entry band names AVG_COST 4100, so 3800 and never 4200 - 300.
        assert cost_plus["deviated_price_cents"] == 3800
        assert cost_plus["price_revision_count"] == 0
        assert entry_tier_id != high_tier_id

        validate_error(
            api_client.create_deviation_agreement(
                deviation_agreement_payload(
                    signed["contract_id"],
                    chicken["id"],
                    world["manufacturer_id"],
                    read_contract_version(signed["contract_id"]),
                    4500,
                    TERM_START,
                    SEP_START,
                    bill_back_basis="COST_PLUS_PROTECTED",
                    protected_discount_cents=4100,
                ),
                ANALYST,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        fixed = create_deviation(
            signed["contract_id"],
            beef["id"],
            world["manufacturer_id"],
            5900,
            TERM_START,
            SEP_START,
            requested_net_price_cents=3700,
        )
        # A pinned net price involves no cost basis at all.
        assert fixed["deviated_price_cents"] == 3700
        assert fixed["status"] == "DRAFT"

        rows, meta = validate_paginated(
            api_client.list_deviation_agreements(ANALYST, {"product_id": chicken["id"]})
        )
        # The refused create left no row behind.
        assert meta["total_count"] == 1
        assert rows[0]["id"] == cost_plus["id"]


class TestServiceFeeConditions:
    def test_coverage_type_and_the_waiver_flag_alone_decide_the_fee(self):
        """PRD §3.5: "`service_fee_cents` is 0 when the coverage row's
        `coverage_type` is `IN_MARKET`, or when its `service_fee_waived` is true,
        or when `extended_price_cents` is at or above five thousand dollars —
        500,000 cents."

        PRD §3.2: "`IN_MARKET` waives the per-case service fee outright;
        `OUT_OF_MARKET` makes it chargeable and is permitted only when the
        contract's `allow_out_of_market` is true — otherwise the request is
        rejected with `ERR_OUT_OF_MARKET_NOT_PERMITTED`."

        Design: Corner/Calculations/service_fee_depends_on_coverage_type_and_waiver_flag
        """
        world = bootstrap_partners()
        chicken = _chicken(world["manufacturer_id"])
        boise = create_distribution_center(
            dc_code="DC-BOI",
            name="Boise DC",
            in_market_state_codes=["ID"],
            out_of_market_fee_per_case_cents=300,
        )
        portland = create_distribution_center(
            dc_code="DC-PDX",
            name="Portland DC",
            in_market_state_codes=["OR"],
            out_of_market_fee_per_case_cents=300,
        )
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_QUARTER],
            allow_out_of_market=True,
        )
        chargeable = add_coverage(
            signed["contract_id"], boise["id"], coverage_type="OUT_OF_MARKET"
        )
        waived = add_coverage(
            signed["contract_id"],
            portland["id"],
            coverage_type="OUT_OF_MARKET",
            service_fee_waived=True,
        )
        assert chargeable["service_fee_waived"] is False
        assert waived["coverage_type"] == "OUT_OF_MARKET"
        open_rebate_period(signed["contract_id"], TERM_START, SEP_START)

        set_clock(AUG_05)
        lines = {}
        for label, dc_id in (
            ("in_market", world["dc_id"]),
            ("chargeable", boise["id"]),
            ("waived", portland["id"]),
        ):
            lines[label] = create_order_line(
                signed["contract_id"],
                chicken["id"],
                dc_id,
                world["operator_id"],
                10,
            )

        for line in lines.values():
            assert line["extended_price_cents"] == 50000

        assert lines["in_market"]["service_fee_cents"] == 0
        assert lines["in_market"]["invoice_total_cents"] == 50000
        # 300 per case over 10 cases.
        assert lines["chargeable"]["service_fee_cents"] == 3000
        assert lines["chargeable"]["invoice_total_cents"] == 53000
        assert lines["waived"]["service_fee_cents"] == 0
        assert lines["waived"]["invoice_total_cents"] == 50000

        strict = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_QUARTER],
            contract_code="HLG-STRICT",
        )
        validate_error(
            api_client.create_dc_coverage(
                dc_coverage_payload(
                    strict["contract_id"], boise["id"], coverage_type="OUT_OF_MARKET"
                ),
                NAM,
            ),
            "ERR_OUT_OF_MARKET_NOT_PERMITTED",
            409,
        )
        _, meta = validate_paginated(
            api_client.list_dc_coverages(
                NAM,
                {"contract_id": strict["contract_id"], "distribution_center_id": boise["id"]},
            )
        )
        assert meta["total_count"] == 0
