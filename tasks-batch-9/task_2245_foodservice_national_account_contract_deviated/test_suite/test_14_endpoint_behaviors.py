"""What the endpoint surface itself guarantees: a reference-data round trip with
composed list filters, the clock endpoint's expiry sweep, foreign-key existence
on a link endpoint, and the compliance report as a pure derived read.
"""
from test_helpers import (
    AUG_05,
    NON_EXISTENT_UUID,
    SEP_START,
    TERM_START,
    add_tier,
    api_client,
    assert_pct,
    bootstrap_partners,
    build_active_deviation,
    build_signed_contract,
    close_rebate_period,
    create_contract_draft,
    create_invoiced_line,
    create_manufacturer,
    create_product,
    open_rebate_period,
    set_availability,
    set_clock,
    substitution_rule_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ACCOUNTANT, ANALYST, AUDITOR, NAM

SHORT_TERM_END = "2026-08-31T23:59:59Z"
SEP_02 = "2026-09-02T00:00:00Z"
NOV_START_LOCAL = "2026-11-01T00:00:00Z"

FLAT_COST = {
    "last_cost_cents": 4000,
    "avg_cost_cents": 4000,
    "replacement_cost_cents": 4000,
}
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


def _chicken(manufacturer_id, **overrides):
    return create_product(manufacturer_id, **dict(FLAT_COST, **overrides))


class TestReferenceDataRoundTrip:
    def test_a_product_survives_the_write_read_cycle_and_the_filters_compose(self):
        """PRD §3.1: "A product is registered with a unique `sku`, an invoice
        `description`, a `product_class_code` drawn from `PROTEIN`, `PRODUCE`,
        `FROZEN`, `DRY_GROCERY`, `DISPOSABLES`, `BEVERAGE` and `SPECIALTY`, a
        `manufacturer_id` naming the manufacturer that funds deviations on the
        item, and a `pack_size` of at least 1 giving units per case."

        PRD §2.3: "Results are always sorted by `created_at` ascending."

        PRD §3.1: "A `SystemAdmin` later adjusts availability by supplying
        `stock_status`, `status`, or both; that write increments the product's
        `version` by 1 and is exactly how an item is pushed out of stock so a
        substitution can be exercised."

        Design: Corner/Endpoints/reference_data_create_read_and_filtered_list_round_trip
        """
        manufacturer = create_manufacturer()
        chicken = create_product(
            manufacturer["id"], substitution_group_code="CHKN"
        )
        beef = create_product(
            manufacturer["id"],
            sku="P-BEEF",
            description="Beef Chuck 4/10#",
            last_cost_cents=5200,
            avg_cost_cents=5100,
            replacement_cost_cents=5300,
        )
        milk = create_product(
            manufacturer["id"],
            sku="P-MILK",
            description="Whole Milk 4/1gal",
            product_class_code="BEVERAGE",
            last_cost_cents=3200,
            avg_cost_cents=3100,
            replacement_cost_cents=3300,
        )
        assert chicken["stock_status"] == "IN_STOCK"
        assert chicken["status"] == "ACTIVE"
        assert chicken["version"] == 1
        assert chicken["cost_effective_at"] is None

        stored = validate_success(api_client.get_product(chicken["id"], NAM))
        assert stored["sku"] == "P-CHKN"
        assert stored["description"] == "Chicken Breast 4/10#"
        assert stored["product_class_code"] == "PROTEIN"
        assert stored["manufacturer_id"] == manufacturer["id"]
        assert stored["pack_size"] == 4
        assert stored["last_cost_cents"] == 4200
        assert stored["avg_cost_cents"] == 4100
        assert stored["replacement_cost_cents"] == 4300
        assert stored["substitution_group_code"] == "CHKN"

        proteins, protein_page = validate_paginated(
            api_client.list_products(
                ANALYST, {"product_class_code": "PROTEIN", "limit": 2, "offset": 0}
            )
        )
        assert [row["id"] for row in proteins] == [chicken["id"], beef["id"]]
        assert protein_page["total_count"] == 2
        assert protein_page["limit"] == 2
        assert protein_page["offset"] == 0
        assert protein_page["has_more"] is False

        beverages, beverage_page = validate_paginated(
            api_client.list_products(
                ANALYST,
                {
                    "manufacturer_id": manufacturer["id"],
                    "product_class_code": "BEVERAGE",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert [row["id"] for row in beverages] == [milk["id"]]
        assert beverage_page["total_count"] == 1

        # The availability write is the catalogue's only mutation path.
        pushed_out = set_availability(chicken["id"], stock_status="OUT_OF_STOCK")
        assert pushed_out["stock_status"] == "OUT_OF_STOCK"
        assert pushed_out["status"] == "ACTIVE"
        assert pushed_out["version"] == 2
        assert pushed_out["last_cost_cents"] == 4200


class TestClockSweep:
    def test_one_advance_past_the_term_ends_the_contract_and_its_dependents(self):
        """PRD §2.5: "It keeps a logical UTC clock whose startup value is exactly
        `2026-08-01T00:00:00Z`, and a `SystemAdmin` moves it by supplying a
        `to_iso8601` instant to the clock endpoint, which answers with the
        resulting `current_utc` together with `expired_contract_ids` and
        `expired_deviation_ids` — the rows the move swept into expiry."

        PRD §3.3: "When a `SystemAdmin` advances the logical clock past a
        contract's `effective_to` while that contract is `ACTIVE` or `SUSPENDED`,
        the contract moves to `EXPIRED`; its deviation agreements in any of the
        six non-terminal states listed above become `TERMINATED`, and its `ACTIVE`
        coverage rows become `ENDED`, but — unlike a termination — its markup
        tiers are left as they are."

        Design: Corner/Endpoints/clock_advance_sweeps_contract_coverage_and_deviations
        """
        world = bootstrap_partners()
        chicken = _chicken(world["manufacturer_id"])
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_QUARTER],
            coverages=[
                {"coverage_from": TERM_START, "coverage_to": SHORT_TERM_END}
            ],
            contract_code="HLG-SHORT",
            effective_from=TERM_START,
            effective_to=SHORT_TERM_END,
        )
        contract_id = signed["contract_id"]
        # The agreement's own window outlives the term, so only the contract
        # cascade can move it.
        deviation = build_active_deviation(
            contract_id,
            chicken["id"],
            world["manufacturer_id"],
            5000,
            TERM_START,
            NOV_START_LOCAL,
            requested_net_price_cents=4200,
        )
        assert deviation["status"] == "ACTIVE"

        swept = set_clock(SEP_START)
        assert swept["current_utc"].startswith("2026-09-01T00:00:00")
        assert swept["expired_contract_ids"] == [contract_id]
        assert swept["expired_deviation_ids"] == [deviation["id"]]

        assert (
            validate_success(api_client.get_contract(contract_id, NAM))["status"]
            == "EXPIRED"
        )
        assert (
            validate_success(
                api_client.get_deviation_agreement(deviation["id"], ANALYST)
            )["status"]
            == "TERMINATED"
        )
        assert (
            validate_success(
                api_client.get_dc_coverage(signed["coverage_ids"][0], NAM)
            )["status"]
            == "ENDED"
        )
        # Expiry ends coverage and deviations but never supersedes tiers.
        assert (
            validate_success(
                api_client.get_contract_tier(signed["tier_ids"][0], NAM)
            )["status"]
            == "ACTIVE"
        )

        again = set_clock(SEP_02)
        assert again["expired_contract_ids"] == []
        assert again["expired_deviation_ids"] == []


class TestLinkEndpointForeignKeys:
    def test_each_referenced_id_is_resolved_before_the_rule_is_compared(self):
        """PRD §2.8: "Existence of every referenced id, path parameters first (left
        to right), then body foreign keys in declaration order — the matching
        `*_NOT_FOUND` code (404)."

        PRD §2.4: "The same codes cover body foreign keys, which are resolved after
        the path parameters in the order they are declared in the endpoint's input
        list; `rebate_funding_manufacturer_id` resolves under
        `ERR_MANUFACTURER_NOT_FOUND`, and `primary_product_id` and
        `substitute_product_id` resolve under `ERR_PRODUCT_NOT_FOUND`."

        Design: Corner/Endpoints/substitution_rule_requires_both_products_and_the_contract_to_exist
        """
        world = bootstrap_partners()
        chicken = _chicken(world["manufacturer_id"], substitution_group_code="CHKN")
        alternate = _chicken(
            world["manufacturer_id"],
            sku="S1-CHKN",
            description="Chicken Breast Alternate 4/10#",
            last_cost_cents=4100,
            avg_cost_cents=4100,
            replacement_cost_cents=4100,
            substitution_group_code="CHKN",
        )
        contract = create_contract_draft(
            world["operator_id"], world["manufacturer_id"]
        )
        contract_id = contract["id"]
        add_tier(contract_id, markup_value=25.00)

        # An unknown substitute is a 404 long before the group comparison.
        validate_error(
            api_client.create_substitution_rule(
                substitution_rule_payload(
                    contract_id, chicken["id"], NON_EXISTENT_UUID
                ),
                NAM,
            ),
            "ERR_PRODUCT_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.create_substitution_rule(
                substitution_rule_payload(
                    NON_EXISTENT_UUID, chicken["id"], alternate["id"]
                ),
                NAM,
            ),
            "ERR_CONTRACT_NOT_FOUND",
            404,
        )

        rule = validate_success(
            api_client.create_substitution_rule(
                substitution_rule_payload(
                    contract_id, chicken["id"], alternate["id"]
                ),
                NAM,
            ),
            201,
        )
        assert rule["contract_id"] == contract_id
        assert rule["primary_product_id"] == chicken["id"]
        assert rule["substitute_product_id"] == alternate["id"]
        assert rule["price_protection_mode"] == "HOLD_CONTRACT_PRICE"
        assert rule["rank"] == 1
        assert rule["status"] == "ACTIVE"

        by_primary, primary_page = validate_paginated(
            api_client.list_substitution_rules(
                NAM,
                {
                    "primary_product_id": chicken["id"],
                    "status": "ACTIVE",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert [row["id"] for row in by_primary] == [rule["id"]]
        assert primary_page["total_count"] == 1

        by_contract, contract_page = validate_paginated(
            api_client.list_substitution_rules(
                world["buyer"], {"contract_id": contract_id, "limit": 10, "offset": 0}
            )
        )
        assert [row["id"] for row in by_contract] == [rule["id"]]
        assert contract_page["total_count"] == 1


class TestComplianceReportRead:
    def test_the_report_derives_every_figure_from_the_latest_closed_period(self):
        """PRD §3.3: "It answers with the `contract_id`, an `evaluated_at` equal to
        the logical clock, a `closed_period_count` giving the number of that
        contract's rebate periods in `CLOSED` or `SETTLED` status, the
        `latest_period_id` of the most recent such period (ordered by
        `period_start` descending, then `created_at` descending), that period's
        `latest_compliance_pct` and `latest_rebate_rate_pct`, the contract's own
        `contracted_purchase_pct_target`, a `shortfall_pct` equal to the target
        minus `latest_compliance_pct` rounded half up to two decimals — negative
        when the operator has beaten its commitment — and the contract's
        `compliance_basis` and `compliance_posture`."

        PRD §3.7: "`rebate_rate_pct` comes from a four-band table read against
        `compliance_pct` with inclusive lower bounds: 4.00 percent at 95.00 or
        above, 3.00 percent at 90.00 or above, 1.50 percent at 80.00 or above, and
        0.00 percent below that."

        Design: Corner/Endpoints/compliance_report_mirrors_the_latest_closed_period
        """
        world = bootstrap_partners()
        chicken = _chicken(world["manufacturer_id"])
        napkins = _chicken(
            world["manufacturer_id"],
            sku="P-NAP",
            description="Dinner Napkins 6/1000",
            product_class_code="DISPOSABLES",
            pack_size=6,
        )
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_QUARTER, DISPOSABLES_FLAT],
        )
        contract_id = signed["contract_id"]
        august = open_rebate_period(contract_id, TERM_START, SEP_START)

        # 90 contracted cases at 5000, then 10 non-contracted cases at 5000.
        create_invoiced_line(
            contract_id,
            chicken["id"],
            world["dc_id"],
            world["operator_id"],
            90,
            order_clock=AUG_05,
        )
        create_invoiced_line(
            contract_id, napkins["id"], world["dc_id"], world["operator_id"], 10
        )

        set_clock(SEP_START)
        closed = close_rebate_period(august["id"])
        assert closed["gross_purchases_cents"] == 500000
        assert closed["contracted_purchases_cents"] == 450000
        assert closed["qualifying_cases"] == 100
        assert closed["contracted_cases"] == 90
        assert_pct(closed["compliance_pct"], 90.00, "compliance_pct")
        assert_pct(closed["rebate_rate_pct"], 3.00, "rebate_rate_pct")
        assert closed["operator_rebate_cents"] == 13500
        assert closed["manufacturer_funded_cents"] == 8100
        assert closed["distributor_funded_cents"] == 5400

        report = validate_success(
            api_client.get_compliance_report(contract_id, AUDITOR)
        )
        assert report["contract_id"] == contract_id
        assert report["closed_period_count"] == 1
        assert report["latest_period_id"] == august["id"]
        # The report derives; it keeps no copy of its own.
        assert_pct(
            report["latest_compliance_pct"],
            closed["compliance_pct"],
            "latest_compliance_pct",
        )
        assert_pct(
            report["latest_rebate_rate_pct"],
            closed["rebate_rate_pct"],
            "latest_rebate_rate_pct",
        )
        assert_pct(
            report["contracted_purchase_pct_target"],
            85.00,
            "contracted_purchase_pct_target",
        )
        assert_pct(report["shortfall_pct"], -5.00, "shortfall_pct")
        assert report["compliance_basis"] == "DOLLAR_WEIGHTED"
        assert report["compliance_posture"] == "OPEN"
        assert report["evaluated_at"].startswith("2026-09-01T00:00:00")

        # Nothing in the report needed the accountant's own role to compute.
        accountant_view = validate_success(
            api_client.get_compliance_report(contract_id, ACCOUNTANT)
        )
        assert accountant_view["latest_period_id"] == august["id"]
        assert (
            validate_success(api_client.get_contract(contract_id, NAM))[
                "rebate_payable_cents"
            ]
            == 13500
        )
