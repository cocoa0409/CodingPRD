"""The two conservation identities: a bidder's deposit pool across a hold release,
and a posted settlement across the voiding that fallout performs."""

from test_helpers import (
    assert_deposit_pool_conserved,
    assert_forfeiture_conserved,
    assert_settlement_conserved,
    executed_contract,
    expected_buyer_premium,
    expected_doc_fee,
    expected_forfeiture_split,
    expected_platform_fee,
    fallen_out_contract,
    funded_bidder,
    holds_for_bidder,
    list_bids,
    live_lot,
    place_bid,
    read_bid,
    read_bidder,
    read_contract,
    read_listing,
    read_lot,
    read_seller,
    set_clock,
    sole_hold,
)

LAKEVIEW = {
    "org_name": "Lakeview Servicing",
    "seller_type": "SERVICER",
    "contact_email": "reo@lakeviewsvc.example",
    "settlement_account_ref": "ACH-LAKE-4",
    "default_commission_bps": 500,
    "street_address": "44 Lakeshore Dr",
    "estimated_value_cents": 27000000,
}


def _outbid_pair():
    """A live lot where a 3000000-funded bidder's 20000000 bid has just been topped
    by a 2500000-funded bidder's 20500000 bid."""
    scenario = live_lot(
        org_name="Northgate REO",
        seller_type="BANK",
        contact_email="reo@northgate.example",
        settlement_account_ref="ACH-NORTH-6",
        street_address="150 Northgate Ave",
        estimated_value_cents=27500000,
        event_title="Alameda Outbid Session",
        opening_bid_cents=20000000,
        reserve_price_cents=20000000,
        min_increment_cents=500000,
    )
    first = funded_bidder(
        3000000, legal_name="Northgate Partners LLC", email="bids@northgatepartners.example"
    )
    second = funded_bidder(
        2500000,
        legal_name="Estuary Capital LLC",
        email="bids@estuarycapital.example",
        document_reference="KYC-7788",
        funding_reference="WIRE-24680",
    )
    scenario.bidders = [first, second]

    set_clock("2026-09-15T17:10:00Z")
    scenario.bids.append(place_bid(scenario.lot_id, first["id"], 20000000))
    set_clock("2026-09-15T17:20:00Z")
    scenario.bids.append(place_bid(scenario.lot_id, second["id"], 20500000))
    return scenario


class TestDepositPoolConservation:
    def test_outbid_hold_is_released_and_the_new_hold_is_created(self):
        """Acceptance demotes the standing bid, releases that bidder's hold with an
        `OUTBID` reason, and encumbers the incoming bidder for the same amount.

        PRD: "The bid that was standing — the one bid on the lot whose `bid_status` is
        `ACTIVE` — becomes `OUTBID`, and that displaced bidder's deposit hold on the lot
        is `RELEASED` with a `released_reason` of `OUTBID`, returning their money to
        their available balance immediately rather than at the end of the session."

        Design: Difficulty/compensating_invariant/deposit_pool_conserved_when_outbid_hold_is_released
        """
        scenario = _outbid_pair()
        first, second = scenario.bidders
        first_bid, second_bid = scenario.bids

        assert read_bid(first_bid["id"])["bid_status"] == "OUTBID"
        assert read_bid(second_bid["id"])["bid_status"] == "ACTIVE"

        released = sole_hold(first["id"])
        assert released["status"] == "RELEASED"
        assert released["released_reason"] == "OUTBID"
        assert released["amount_cents"] == 1000000

        live = sole_hold(second["id"])
        assert live["status"] == "HELD"
        assert live["amount_cents"] == 1000000

        lot = read_lot(scenario.lot_id)
        assert lot["current_high_bid_cents"] == 20500000
        assert lot["lot_status"] == "OPEN"
        assert len(list_bids(auction_lot_id=scenario.lot_id)) == 2

    def test_the_pool_identity_holds_for_both_bidders_after_the_release(self):
        """The released hold contributes to none of the three terms, so the displaced
        bidder's whole wallet is available again while the new leader's is encumbered.

        PRD: "A bidder's deposit pool always satisfies: available deposit plus the
        total amount held plus the total amount forfeited equals the total amount
        funded — where released holds contribute to none of those three terms."

        Design: Difficulty/compensating_invariant/deposit_pool_conserved_when_outbid_hold_is_released
        """
        scenario = _outbid_pair()
        first, second = scenario.bidders

        displaced = read_bidder(first["id"])
        assert displaced["deposit_available_cents"] == 3000000
        assert displaced["deposit_funded_cents"] == 3000000
        assert displaced["deposit_forfeited_cents"] == 0
        assert_deposit_pool_conserved(displaced, 0)
        assert len(holds_for_bidder(first["id"])) == 1

        leader = read_bidder(second["id"])
        assert leader["deposit_available_cents"] == 1500000
        assert leader["deposit_funded_cents"] == 2500000
        assert leader["deposit_forfeited_cents"] == 0
        assert_deposit_pool_conserved(leader, 1000000)


class TestSettlementIdentityAcrossFallout:
    def test_posted_settlement_satisfies_the_gross_identity(self):
        """A tenant-occupied asset whose verified title came back clouded prices its
        premium at 2150000 and its platform fee at 1115000, and the three settlement
        buckets add back to the gross.

        PRD: "`settlement_gross_cents` is `contract_price_cents` plus
        `final_buyer_premium_cents`, and the conservation identity of §2.8 — seller net
        plus platform fee plus buyer premium equalling the gross — must hold on every
        contract."

        Design: Difficulty/compensating_invariant/settlement_identity_survives_fallout_void
        """
        scenario = executed_contract(
            occupancy_status="TENANT_OCCUPIED",
            title_condition="UNKNOWN",
            clearance_outcome="CLOUDED_DISCLOSED",
            verified_title_condition="CLOUDED",
            event_title="Alameda Clouded Title Session",
            bid_amount_cents=20000000,
            funded_cents=2000000,
            closing_window_days=21,
            **LAKEVIEW,
        )
        contract = scenario.contract

        premium = expected_buyer_premium(20000000, "TENANT_OCCUPIED", "CLOUDED")
        assert contract["final_buyer_premium_cents"] == premium == 2150000
        assert contract["buyer_premium_cents"] == 2150000
        assert (
            contract["platform_fee_cents"]
            == expected_platform_fee(20000000, 500, "CLOUDED")
            == 1115000
        )
        assert contract["seller_net_cents"] == 18885000
        assert contract["settlement_gross_cents"] == 22150000
        assert contract["doc_fee_cents"] == expected_doc_fee(20000000, premium) == 95000
        assert contract["total_due_cents"] == 22245000
        assert contract["settlement_status"] == "POSTED"
        assert_settlement_conserved(contract)
        assert read_seller(scenario.seller_id)["settled_net_cents"] == 18885000

    def test_void_retains_the_sale_numbers_and_splits_the_forfeited_deposit(self):
        """Fallout voids the settlement axis without rewriting a single sale figure,
        and the captured deposit splits sixty-forty with the remainder to the platform.

        PRD: "The settlement is unwound on the settlement axis alone:
        `settlement_status` moves `POSTED → VOID` and the seller's `settled_net_cents`
        is reduced by this contract's `seller_net_cents`, while the sale numbers
        themselves — `contract_price_cents`, `final_buyer_premium_cents`,
        `doc_fee_cents`, `total_due_cents`, `settlement_gross_cents`, `seller_net_cents`,
        `platform_fee_cents` and `buyer_premium_cents` — are all **retained unchanged**
        as the record of what was contracted."

        Design: Difficulty/compensating_invariant/settlement_identity_survives_fallout_void
        """
        scenario = fallen_out_contract(
            occupancy_status="TENANT_OCCUPIED",
            title_condition="UNKNOWN",
            clearance_outcome="CLOUDED_DISCLOSED",
            verified_title_condition="CLOUDED",
            event_title="Alameda Clouded Title Session",
            bid_amount_cents=20000000,
            funded_cents=2000000,
            closing_window_days=21,
            fallout_at="2026-09-21T00:00:00Z",
            **LAKEVIEW,
        )
        contract = read_contract(scenario.contract_id)

        assert contract["contract_status"] == "FALLOUT"
        assert contract["settlement_status"] == "VOID"
        assert contract["contract_price_cents"] == 20000000
        assert contract["final_buyer_premium_cents"] == 2150000
        assert contract["doc_fee_cents"] == 95000
        assert contract["total_due_cents"] == 22245000
        assert contract["settlement_gross_cents"] == 22150000
        assert contract["seller_net_cents"] == 18885000
        assert contract["platform_fee_cents"] == 1115000
        assert_settlement_conserved(contract)

        seller_share, platform_share = expected_forfeiture_split(1250000)
        assert contract["forfeited_deposit_cents"] == 1250000
        assert contract["forfeiture_seller_net_cents"] == seller_share == 750000
        assert contract["forfeiture_platform_fee_cents"] == platform_share == 500000
        assert_forfeiture_conserved(contract)

        # The seller keeps only its share of the forfeiture once the sale is unwound.
        assert read_seller(scenario.seller_id)["settled_net_cents"] == 750000
        buyer = read_bidder(scenario.bidder_id)
        assert buyer["deposit_forfeited_cents"] == 1250000
        assert buyer["deposit_available_cents"] == 750000
        assert buyer["deposit_funded_cents"] == 2000000
        assert_deposit_pool_conserved(buyer, 0)
        assert read_listing(scenario.listing_id)["listing_status"] == "RELIST_PENDING"
