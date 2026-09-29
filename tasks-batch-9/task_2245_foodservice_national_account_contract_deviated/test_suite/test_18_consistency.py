"""Read-your-writes: the close response already carries every derived figure, and
the reads that follow it — with no intervening call and no retry — already show
the increased payables on both sides of the ledger.
"""
from test_helpers import (
    AUG_05,
    SEP_START,
    TERM_START,
    api_client,
    assert_pct,
    assert_rebate_liability_conserved,
    bootstrap_partners,
    build_signed_contract,
    create_order_line,
    create_product,
    invoice_order_line,
    open_rebate_period,
    set_clock,
    validate_success,
)
from test_helpers.fixtures import ACCOUNTANT, NAM

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


class TestImmediateVisibility:
    def test_the_close_response_and_the_next_reads_already_agree(self):
        """PRD §3.7: "The period moves `OPEN → CLOSED`, `closed_at` is stamped from
        the logical clock and the period's `version` is incremented by 1."

        PRD §3.7: "The contract's `rebate_payable_cents` is increased by
        `operator_rebate_cents` and its `version` incremented by 1."

        PRD §3.7: "The manufacturer named by the contract's
        `rebate_funding_manufacturer_id` has its `rebate_funding_payable_cents`
        increased by `manufacturer_funded_cents` and its `version` incremented by
        1."

        PRD §2.10: "For any contract, `rebate_payable_cents` plus
        `rebate_settled_total_cents` equals the sum of `operator_rebate_cents` over
        that contract's rebate periods whose status is `CLOSED` or `SETTLED`."

        Design: Corner/Consistency Model/every_mutation_is_visible_in_the_same_response_and_the_next_read
        """
        world = bootstrap_partners()
        chicken = create_product(world["manufacturer_id"], **FLAT_COST)
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_QUARTER],
        )
        contract_id = signed["contract_id"]
        august = open_rebate_period(contract_id, TERM_START, SEP_START)
        assert august["status"] == "OPEN"
        assert august["operator_rebate_cents"] is None

        set_clock(AUG_05)
        # The create response itself is authoritative: no follow-up read.
        line = create_order_line(
            contract_id,
            chicken["id"],
            world["dc_id"],
            world["operator_id"],
            100,
        )
        assert line["list_unit_price_cents"] == 5000
        assert line["invoiced_unit_price_cents"] == 5000
        assert line["extended_price_cents"] == 500000
        assert line["service_fee_cents"] == 0
        assert line["invoice_total_cents"] == 500000
        assert line["rebate_period_id"] == august["id"]
        assert invoice_order_line(line["id"])["pricing_status"] == "INVOICED"

        set_clock(SEP_START)
        closed = validate_success(
            api_client.close_rebate_period(august["id"], ACCOUNTANT)
        )
        assert closed["status"] == "CLOSED"
        assert closed["gross_purchases_cents"] == 500000
        assert closed["contracted_purchases_cents"] == 500000
        assert_pct(closed["compliance_pct"], 100.00, "compliance_pct")
        assert_pct(closed["rebate_rate_pct"], 4.00, "rebate_rate_pct")
        assert closed["operator_rebate_cents"] == 20000
        assert closed["manufacturer_funded_cents"] == 12000
        assert closed["distributor_funded_cents"] == 8000
        assert closed["closed_at"].startswith("2026-09-01T00:00:00")

        # Both cascade targets are already updated on the very next read.
        contract = validate_success(api_client.get_contract(contract_id, ACCOUNTANT))
        assert contract["rebate_payable_cents"] == 20000
        assert contract["rebate_settled_total_cents"] == 0
        assert contract["compliance_posture"] == "OPEN"
        manufacturer = validate_success(
            api_client.get_manufacturer(world["manufacturer_id"], ACCOUNTANT)
        )
        assert manufacturer["rebate_funding_payable_cents"] == 12000

        # Nothing is eventually consistent: the re-read matches field for field.
        reread = validate_success(
            api_client.get_rebate_period(august["id"], NAM)
        )
        assert reread["status"] == closed["status"]
        assert reread["gross_purchases_cents"] == closed["gross_purchases_cents"]
        assert (
            reread["contracted_purchases_cents"]
            == closed["contracted_purchases_cents"]
        )
        assert reread["qualifying_cases"] == closed["qualifying_cases"]
        assert reread["contracted_cases"] == closed["contracted_cases"]
        assert_pct(
            reread["compliance_pct"], closed["compliance_pct"], "compliance_pct"
        )
        assert_pct(
            reread["rebate_rate_pct"], closed["rebate_rate_pct"], "rebate_rate_pct"
        )
        assert reread["operator_rebate_cents"] == closed["operator_rebate_cents"]
        assert (
            reread["manufacturer_funded_cents"]
            == closed["manufacturer_funded_cents"]
        )
        assert reread["distributor_funded_cents"] == closed["distributor_funded_cents"]
        assert reread["closed_at"] == closed["closed_at"]
        assert reread["version"] == closed["version"]
        assert_rebate_liability_conserved(contract, [reread])
