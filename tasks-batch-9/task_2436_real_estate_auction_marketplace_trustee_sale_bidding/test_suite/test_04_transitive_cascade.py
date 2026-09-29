"""Chains where each link is caused by the state change the previous link produced:
the county postponement, and the compensating unwind of a fallen-out contract."""

from test_helpers import (
    CLOCK_EVENT_OPEN,
    assert_deposit_pool_conserved,
    assert_forfeiture_conserved,
    assert_settlement_conserved,
    assert_timestamp_equals,
    expected_forfeiture_split,
    fallen_out_contract,
    funded_bidder,
    list_holds,
    live_lot,
    place_bid,
    postpone_sale,
    read_bid,
    read_bidder,
    read_contract,
    read_event,
    read_listing,
    read_lot,
    read_sale,
    read_seller,
    set_clock,
)

SIERRA_POINT = {
    "org_name": "Sierra Point Bank",
    "seller_type": "BANK",
    "contact_email": "reo@sierrapoint.example",
    "settlement_account_ref": "ACH-SIERRA-6",
    "street_address": "1201 Peralta St",
    "city": "Oakland",
    "estimated_value_cents": 30000000,
}

UNION_CREST = {
    "org_name": "Union Crest Servicing",
    "seller_type": "SERVICER",
    "contact_email": "reo@unioncrest.example",
    "settlement_account_ref": "ACH-UNION-8",
    "default_commission_bps": 500,
    "street_address": "62 Chestnut St",
    "city": "Oakland",
    "estimated_value_cents": 27000000,
}

POSTPONED_AT = "2026-09-15T17:30:00Z"


def _postponement_mid_session():
    """A live trustee-linked lot carrying one standing bid and one encumbered hold, at
    the moment the trustee pushes the county sale out by a week."""
    scenario = live_lot(
        occupancy_status="TENANT_OCCUPIED",
        title_condition="JUNIOR_LIENS",
        event_title="Alameda Peralta Trustee Sale",
        opening_bid_cents=20000000,
        reserve_price_cents=20000000,
        trustee_sale_at="2026-09-15T18:00:00Z",
        **SIERRA_POINT,
    )
    bidder = funded_bidder(
        3000000, legal_name="Peralta Yield Partners", email="ops@peraltayield.example"
    )
    scenario.bidders = [bidder]

    set_clock(CLOCK_EVENT_OPEN)
    scenario.bids = [place_bid(scenario.lot_id, bidder["id"], 20000000)]

    set_clock(POSTPONED_AT)
    scenario.sale = postpone_sale(
        scenario.sale_id,
        "2026-09-22T18:00:00Z",
        reason="borrower filed for loss mitigation review",
    )
    return scenario


class TestPostponementCascade:
    def test_the_sale_event_and_lot_move_in_one_request(self):
        """One trustee action walks three entity types: the sale is postponed, the live
        session it backs is postponed with it, and that session's open lot is suspended.

        PRD: "A **postponement** runs a five-link chain: the sale itself moves to
        `POSTPONED`; every auction event bound to it that is `SCHEDULED` or `LIVE` moves to
        `POSTPONED`; every lot of those events that is `OPEN` or `EXTENDED` moves to
        `SUSPENDED`; every deposit hold on those lots that is `HELD` or `EXTENDED` is
        re-aged under the hold-extension policy of §3.2; and every bidder touched by a hold
        change has their deposit ledger recomputed."

        Design: Difficulty/transitive_cascade/postponement_cascades_sale_event_lot_hold_ledger
        """
        scenario = _postponement_mid_session()

        sale = read_sale(scenario.sale_id)
        assert sale["status"] == "POSTPONED"
        assert sale["postponement_count"] == 1
        assert_timestamp_equals(sale["sale_scheduled_at"], "2026-09-22T18:00:00Z")

        assert read_event(scenario.event_id)["event_status"] == "POSTPONED"

        lot = read_lot(scenario.lot_id)
        assert lot["lot_status"] == "SUSPENDED"
        assert lot["current_high_bid_cents"] == 20000000

    def test_the_hold_is_re_aged_and_the_ledger_recomputed(self):
        """The fourth and fifth links: the encumbered hold takes its first extension and
        expires thirty days from the postponement instant, and the bidder's ledger follows.

        PRD: "If the incremented value is at most 2 — the platform grants a hold no more
        than two postponement-driven extensions — the hold becomes `EXTENDED` and its
        `expires_at` is rewritten to the logical clock advanced by thirty days."

        Design: Difficulty/transitive_cascade/postponement_cascades_sale_event_lot_hold_ledger
        """
        scenario = _postponement_mid_session()

        holds = list_holds(auction_lot_id=scenario.lot_id)
        assert len(holds) == 1
        assert holds[0]["status"] == "EXTENDED"
        assert holds[0]["extension_count"] == 1
        assert holds[0]["amount_cents"] == 1250000
        assert_timestamp_equals(holds[0]["expires_at"], "2026-10-15T17:30:00Z")

        bidder = read_bidder(scenario.bidder_id)
        assert bidder["deposit_available_cents"] == 1750000
        assert bidder["deposit_funded_cents"] == 3000000
        assert bidder["deposit_forfeited_cents"] == 0
        assert_deposit_pool_conserved(bidder, 1250000)

    def test_the_chain_stops_before_the_asset_and_leaves_the_bid_standing(self):
        """A postponement is not a failed auction: the asset keeps its marketplace status
        and the standing bid is still merely `ACTIVE`, since no lot has closed.

        PRD: "A postponement is not a failed auction, so no asset listing changes
        `listing_status`: the asset stays `LISTED`."

        Design: Difficulty/transitive_cascade/postponement_cascades_sale_event_lot_hold_ledger
        """
        scenario = _postponement_mid_session()

        assert read_listing(scenario.listing_id)["listing_status"] == "LISTED"
        assert read_bid(scenario.bids[0]["id"])["bid_status"] == "ACTIVE"


def _fallout_of_a_sole_bidder_contract():
    """An executed, posted contract on a lot with exactly one bidder, taken through
    fallout five days into its twenty-one-day closing window."""
    return fallen_out_contract(
        occupancy_status="TENANT_OCCUPIED",
        title_condition="UNKNOWN",
        clearance_outcome="CLOUDED_DISCLOSED",
        verified_title_condition="CLOUDED",
        event_title="Alameda REO Block F",
        opening_bid_cents=20000000,
        reserve_price_cents=20000000,
        bid_amount_cents=20000000,
        funded_cents=2000000,
        bidder_legal_name="Chestnut Row Investors",
        bidder_email="desk@chestnutrow.example",
        closing_window_days=21,
        fallout_at="2026-09-20T00:00:00Z",
        **UNION_CREST,
    )


class TestFalloutCascade:
    def test_the_contract_voids_and_the_hold_is_captured(self):
        """The first two links: the contract falls out with its settlement voided, and
        the winner's deposit hold is captured rather than released.

        PRD: "The winning bidder's deposit hold on the lot, whose `status` is `HELD` or
        `EXTENDED`, becomes `CAPTURED` with a `released_reason` of `FORFEITED`, and the
        contract's `forfeited_deposit_cents` is set to that hold's `amount_cents`."

        Design: Difficulty/transitive_cascade/fallout_cascades_contract_hold_bidder_listing_with_seller_compensation
        """
        scenario = _fallout_of_a_sole_bidder_contract()
        contract = read_contract(scenario.contract_id)

        assert contract["contract_status"] == "FALLOUT"
        assert contract["settlement_status"] == "VOID"
        assert_timestamp_equals(contract["fallout_at"], "2026-09-20T00:00:00Z")

        holds = list_holds(auction_lot_id=scenario.lot_id)
        assert len(holds) == 1
        assert holds[0]["status"] == "CAPTURED"
        assert holds[0]["released_reason"] == "FORFEITED"

    def test_the_forfeiture_is_split_and_the_bidder_ledger_moves(self):
        """The captured 1250000 splits sixty-forty with the remainder to the platform,
        and the buyer's ledger records the forfeiture and the freed balance.

        PRD: "`forfeiture_seller_net_cents` is the `forfeited_deposit_cents` multiplied by
        6000 basis points and divided by ten thousand — sixty percent — rounded half up to
        whole cents, and `forfeiture_platform_fee_cents` is whatever remains after
        subtracting the seller's share from the forfeited amount."

        Design: Difficulty/transitive_cascade/fallout_cascades_contract_hold_bidder_listing_with_seller_compensation
        """
        scenario = _fallout_of_a_sole_bidder_contract()
        contract = read_contract(scenario.contract_id)

        seller_share, platform_share = expected_forfeiture_split(1250000)
        assert contract["forfeited_deposit_cents"] == 1250000
        assert contract["forfeiture_seller_net_cents"] == seller_share == 750000
        assert contract["forfeiture_platform_fee_cents"] == platform_share == 500000
        assert_forfeiture_conserved(contract)

        buyer = read_bidder(scenario.bidder_id)
        assert buyer["deposit_forfeited_cents"] == 1250000
        assert buyer["deposit_available_cents"] == 750000
        assert buyer["fallout_count"] == 1
        assert buyer["registration_status"] == "REGISTERED"
        assert_deposit_pool_conserved(buyer, 0)

    def test_the_seller_ledger_is_reversed_then_credited_in_order(self):
        """The seller's balance ends at 750000, which is only reachable by first backing
        out the posted 18885000 and then crediting the forfeiture share.

        PRD: "The seller is credited for its share: `settled_net_cents` rises by
        `forfeiture_seller_net_cents`, having just been reduced by the voided
        `seller_net_cents`."

        Design: Difficulty/transitive_cascade/fallout_cascades_contract_hold_bidder_listing_with_seller_compensation
        """
        scenario = _fallout_of_a_sole_bidder_contract()
        contract = read_contract(scenario.contract_id)

        assert contract["seller_net_cents"] == 18885000
        assert contract["platform_fee_cents"] == 1115000
        assert contract["buyer_premium_cents"] == 2150000
        assert contract["settlement_gross_cents"] == 22150000
        assert contract["doc_fee_cents"] == 95000
        assert contract["total_due_cents"] == 22245000
        assert_settlement_conserved(contract)
        assert read_seller(scenario.seller_id)["settled_net_cents"] == 750000

    def test_the_asset_is_queued_to_go_round_again_with_no_backup_pool(self):
        """The last link reopens the asset, and with only the defaulting buyer having
        ever bid there is no qualifying backup pool to flag.

        PRD: "Finally the asset is queued to go round again: `listing_status` moves
        `SOLD_PENDING_CONTRACT → RELIST_PENDING`, and `second_chance_eligible` is
        recomputed against the backup pool described below."

        Design: Difficulty/transitive_cascade/fallout_cascades_contract_hold_bidder_listing_with_seller_compensation
        """
        scenario = _fallout_of_a_sole_bidder_contract()

        listing = read_listing(scenario.listing_id)
        assert listing["listing_status"] == "RELIST_PENDING"
        assert listing["second_chance_eligible"] is False
        assert read_bid(scenario.bids[0]["id"])["bid_status"] == "WINNING"
