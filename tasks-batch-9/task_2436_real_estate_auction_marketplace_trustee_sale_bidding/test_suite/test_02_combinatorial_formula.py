"""Money formulas whose answer depends on the order the terms are combined: the
three-component settlement split and the three-step document fee."""

from test_helpers import (
    assert_settlement_conserved,
    executed_contract,
    expected_buyer_premium,
    expected_doc_fee,
    expected_platform_fee,
    expected_total_due,
    read_contract,
    read_seller,
)

MERIDIAN = {
    "org_name": "Meridian Loan Servicing",
    "seller_type": "SERVICER",
    "contact_email": "reo@meridian.example",
    "settlement_account_ref": "ACH-MERIDIAN-7",
    "default_commission_bps": 500,
    "street_address": "3300 Grand Ave",
    "city": "Oakland",
    "estimated_value_cents": 39000000,
}

NORTHGATE_GSE = {
    "org_name": "Northgate GSE Disposition",
    "seller_type": "GSE",
    "contact_email": "disp@northgate.example",
    "settlement_account_ref": "ACH-NORTHGATE-3",
    "default_commission_bps": 500,
    "street_address": "58 Kestrel Ln",
    "city": "Fremont",
    "estimated_value_cents": 28000000,
}


def _clouded_contract_at_the_rounding_seam():
    """A clouded-title REO contract priced at 32081229 — a figure where the commission
    and the marketing recovery each round down while their combined rate rounds up."""
    return executed_contract(
        occupancy_status="VACANT",
        title_condition="UNKNOWN",
        clearance_outcome="CLOUDED_DISCLOSED",
        verified_title_condition="CLOUDED",
        event_title="Alameda REO Block C",
        opening_bid_cents=30000000,
        reserve_price_cents=30000000,
        bid_amount_cents=32081229,
        funded_cents=2000000,
        bidder_legal_name="Stonegate Property Fund",
        bidder_email="desk@stonegate.example",
        closing_window_days=None,
        **MERIDIAN,
    )


class TestSettlementSplitRoundsPerComponent:
    def test_platform_fee_is_the_sum_of_three_separately_rounded_components(self):
        """Rounding the commission and the marketing recovery on their own before
        adding the flat title service fee gives 1761345, one cent below what a single
        combined-rate multiplication would produce.

        PRD: "Three components are computed independently and each is rounded to whole
        cents on its own."

        Design: Difficulty/combinatorial_formula/settlement_split_rounds_each_component_before_summing
        """
        scenario = _clouded_contract_at_the_rounding_seam()
        contract = scenario.contract

        assert contract["contract_price_cents"] == 32081229
        assert (
            contract["platform_fee_cents"]
            == expected_platform_fee(32081229, 500, "CLOUDED")
            == 1761345
        )
        assert contract["seller_net_cents"] == 30319884

        # The one-cent gap: combining the basis points before rounding is not accepted.
        assert contract["platform_fee_cents"] != 1761346
        assert contract["seller_net_cents"] != 30319883

    def test_the_posted_settlement_balances_and_credits_the_seller(self):
        """Every other settlement figure follows from that fee, and the gross identity
        closes exactly on the per-component answer.

        PRD: "`platform_fee_cents` is the exact integer sum of those three rounded
        components."

        Design: Difficulty/combinatorial_formula/settlement_split_rounds_each_component_before_summing
        """
        scenario = _clouded_contract_at_the_rounding_seam()
        contract = read_contract(scenario.contract_id)

        premium = expected_buyer_premium(32081229, "VACANT", "CLOUDED")
        assert contract["final_buyer_premium_cents"] == premium == 3127920
        assert contract["buyer_premium_cents"] == 3127920
        assert contract["settlement_gross_cents"] == 35209149
        assert contract["doc_fee_cents"] == expected_doc_fee(32081229, premium) == 71250
        assert contract["total_due_cents"] == 35280399
        assert contract["settlement_status"] == "POSTED"
        assert (
            contract["seller_net_cents"] + contract["platform_fee_cents"]
            + contract["buyer_premium_cents"]
            == contract["settlement_gross_cents"]
        )
        assert_settlement_conserved(contract)
        assert read_seller(scenario.seller_id)["settled_net_cents"] == 30319884

    def test_the_seller_net_is_the_residual_of_the_summed_components(self):
        """The seller's proceeds are the contract price less the summed fee, so the
        one-cent rounding decision lands on the seller's side of the ledger too.

        PRD: "`seller_net_cents` is `contract_price_cents` less `platform_fee_cents`."

        Design: Difficulty/combinatorial_formula/settlement_split_rounds_each_component_before_summing
        """
        scenario = _clouded_contract_at_the_rounding_seam()
        contract = scenario.contract

        assert (
            contract["seller_net_cents"]
            == contract["contract_price_cents"] - contract["platform_fee_cents"]
        )
        assert contract["total_due_cents"] == expected_total_due(
            32081229, contract["final_buyer_premium_cents"], contract["doc_fee_cents"]
        )


def _contract_priced_just_over_the_doc_fee_tier_floor():
    """A cleared-title contract priced at 23064815, where the step-one provisional
    total lands at 25005000 — barely at the tier floor that grants the discount."""
    return executed_contract(
        occupancy_status="VACANT",
        title_condition="CLEAR",
        clear_title_before_close=True,
        clearance_outcome="CLEARED",
        verified_title_condition="CLEAR",
        event_title="Alameda REO Block D",
        opening_bid_cents=20000000,
        reserve_price_cents=20000000,
        bid_amount_cents=23064815,
        funded_cents=1500000,
        bidder_legal_name="Kestrel Homes LLC",
        bidder_email="acq@kestrelhomes.example",
        closing_window_days=None,
        **NORTHGATE_GSE,
    )


class TestDocFeeTierKeyedOnProvisionalTotal:
    def test_the_discount_is_keyed_on_the_provisional_total_not_the_final_one(self):
        """The base fee plus price plus premium reaches the 25000000 floor, so the
        0.25 discount applies and the fee is 71250 rather than the base 95000.

        PRD: "Step two keys the discount on that provisional total: a discount of 0.40
        when the provisional total is at least 50000000 cents, a discount of 0.25 when it
        is at least 25000000 cents but below that, and no discount otherwise;
        `doc_fee_cents` is then the base fee of 95000 cents multiplied by one minus the
        discount, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/doc_fee_tier_keyed_on_provisional_total_only
        """
        scenario = _contract_priced_just_over_the_doc_fee_tier_floor()
        contract = scenario.contract

        premium = expected_buyer_premium(23064815, "VACANT", "CLEAR")
        assert contract["contract_price_cents"] == 23064815
        assert contract["final_buyer_premium_cents"] == premium == 1845185
        assert 23064815 + premium + 95000 == 25005000
        assert contract["doc_fee_cents"] == expected_doc_fee(23064815, premium) == 71250

    def test_total_due_ends_below_the_floor_that_granted_its_discount(self):
        """The step-three total is 24981250 — under the tier floor — and the platform
        neither re-keys the tier nor iterates to a fixed point.

        PRD: "A consequence to preserve rather than correct: `total_due_cents` may end up
        **below** the tier floor that granted its discount, because the tier is keyed on
        the step-one provisional total and is never re-keyed on the step-three result."

        Design: Difficulty/combinatorial_formula/doc_fee_tier_keyed_on_provisional_total_only
        """
        scenario = _contract_priced_just_over_the_doc_fee_tier_floor()
        contract = read_contract(scenario.contract_id)

        assert contract["total_due_cents"] == 24981250
        assert contract["total_due_cents"] < 25000000

        # A re-keyed or iterated reading would settle on the undiscounted fee.
        assert contract["doc_fee_cents"] != 95000
        assert contract["total_due_cents"] != 25005000

    def test_the_cleared_title_settlement_charges_no_title_service_fee(self):
        """With the verified condition `CLEAR` the flat title service fee drops out, so
        the platform fee is just commission plus marketing recovery.

        PRD: "The third is a flat title service fee of 45000 cents (four hundred and
        fifty dollars), charged when and only when the asset's `title_condition` at
        execution time is anything other than `CLEAR`, and zero when it is `CLEAR`."

        Design: Difficulty/combinatorial_formula/doc_fee_tier_keyed_on_provisional_total_only
        """
        scenario = _contract_priced_just_over_the_doc_fee_tier_floor()
        contract = scenario.contract

        assert (
            contract["platform_fee_cents"]
            == expected_platform_fee(23064815, 500, "CLEAR")
            == 1233968
        )
        assert contract["seller_net_cents"] == 21830847
        assert contract["settlement_gross_cents"] == 24910000
        assert_settlement_conserved(contract)
