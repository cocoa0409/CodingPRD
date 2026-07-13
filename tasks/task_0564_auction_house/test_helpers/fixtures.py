"""Composite setup helpers for multi-step Auction House test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup failed" errors, not confusing assertion failures. Entity-backed Bidder
calls thread the real Bidder.id through make_bidder_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_saleroom_payload,
    create_consignor_payload,
    create_bidder_payload,
    create_auction_payload,
    create_consignment_payload,
    create_lot_payload,
    create_bid_payload,
    create_dispute_payload,
)
from .test_users import TEST_USERS, make_bidder_headers

STAFF = TEST_USERS["staff_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]
SETTLEMENT = TEST_USERS["settlement_headers"]

DEFAULT_CLOCK = "2026-06-10T00:00:00Z"


# ─── Clock ─────────────────────────────────────────────────────────────────

def set_clock(iso: str):
    """Advance the server logical clock (PRD §2.6)."""
    return get_success_data(api_client.set_clock(iso, STAFF))


# ─── Single-entity blocks ────────────────────────────────────────────────

def make_saleroom(**overrides) -> dict:
    return get_success_data(
        api_client.create_saleroom(create_saleroom_payload(**overrides), STAFF)
    )


def make_consignor(**overrides) -> dict:
    return get_success_data(
        api_client.create_consignor(create_consignor_payload(**overrides), STAFF)
    )


def make_bidder(**overrides) -> dict:
    return get_success_data(
        api_client.create_bidder(create_bidder_payload(**overrides), STAFF)
    )


def make_auction(saleroom_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_auction(create_auction_payload(saleroom_id, **overrides), STAFF)
    )


def make_accepted_consignment(consignor_id, **overrides) -> dict:
    """Submit -> appraise -> decision(ACCEPT). Returns the ACCEPTED consignment."""
    cg = get_success_data(
        api_client.create_consignment(
            create_consignment_payload(consignor_id, **overrides), STAFF
        )
    )
    est_low = overrides.get("estimate_low_cents", 100_000)
    est_high = overrides.get("estimate_high_cents", 200_000)
    api_client.appraise_consignment(
        cg["id"],
        {"appraised_low_cents": est_low, "appraised_high_cents": est_high},
        APPRAISER,
    )
    return get_success_data(
        api_client.decide_consignment(cg["id"], {"outcome": "ACCEPT"}, STAFF)
    )


def make_lot(consignment_id, auction_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_lot(
            create_lot_payload(consignment_id, auction_id, **overrides), STAFF
        )
    )


def place_bid(lot_id, bidder_id, amount_cents, expected_lot_version,
              bid_type="LIVE", acting_user_id=None) -> dict:
    """Place a bid as the owning Bidder. acting_user_id overrides X-User-ID
    (used for the wrong-owner test)."""
    headers = make_bidder_headers(acting_user_id or bidder_id)
    return get_success_data(
        api_client.place_bid(
            lot_id,
            create_bid_payload(bidder_id, amount_cents, expected_lot_version,
                               bid_type=bid_type),
            headers,
        )
    )


def get_invoice_for(bidder_id, auction_id) -> dict:
    """Read the invoice cascade-created for a buyer in a sale."""
    data = get_success_data(
        api_client.list_invoices(
            STAFF, params={"bidder_id": bidder_id, "auction_id": auction_id}
        )
    )
    assert data, "Setup failed: no invoice found for bidder/auction"
    return data[0]


def get_line_for_lot(lot_id) -> dict:
    """Read the invoice line charging a hammered lot."""
    data = get_success_data(
        api_client.list_invoice_lines(STAFF, params={"lot_id": lot_id})
    )
    assert data, "Setup failed: no invoice line found for lot"
    return data[0]


def raise_dispute(line_id, bidder_id, reason="Authenticity challenged") -> dict:
    return get_success_data(
        api_client.create_dispute(
            create_dispute_payload(line_id, reason=reason),
            make_bidder_headers(bidder_id),
        )
    )


def review_dispute(dispute_id) -> dict:
    return get_success_data(api_client.review_dispute(dispute_id, APPRAISER))


def resolve_dispute(dispute_id, outcome, notes="resolved") -> dict:
    return get_success_data(
        api_client.resolve_dispute(
            dispute_id, {"outcome": outcome, "resolution_notes": notes}, APPRAISER
        )
    )


def make_settlement(consignment_id) -> dict:
    return get_success_data(api_client.create_settlement(consignment_id, SETTLEMENT))


# ─── Tier 1/2: reach an OPEN lot ready for bidding ───────────────────────

def setup_open_lot(reserve_cents=0, starting_bid_cents=100_000, commission_rate=0.15,
                   estimate_low_cents=100_000, estimate_high_cents=200_000,
                   clock=None) -> dict:
    """saleroom -> auction -> consignor -> accepted consignment -> lot ->
    open auction -> open lot. Returns a bag of ids; the lot is OPEN.
    """
    if clock is not None:
        set_clock(clock)
    saleroom = make_saleroom()
    auction = make_auction(saleroom["id"])
    consignor = make_consignor()
    consignment = make_accepted_consignment(
        consignor["id"], commission_rate=commission_rate,
        estimate_low_cents=estimate_low_cents, estimate_high_cents=estimate_high_cents,
    )
    lot = make_lot(
        consignment["id"], auction["id"],
        reserve_cents=reserve_cents, starting_bid_cents=starting_bid_cents,
        estimate_low_cents=estimate_low_cents, estimate_high_cents=estimate_high_cents,
    )
    get_success_data(api_client.open_auction(auction["id"], STAFF))
    opened = get_success_data(api_client.open_lot(lot["id"], STAFF))
    return {
        "saleroom": saleroom,
        "auction": auction,
        "consignor": consignor,
        "consignment": consignment,
        "lot": opened,
        "lot_version": opened["version"],
    }


# ─── Tier 3: single hammered lot -> invoice + line ───────────────────────

def setup_single_hammer(hammer_amount, reserve_cents=0, starting_bid_cents=None,
                        commission_rate=0.15, estimate_low_cents=100_000,
                        estimate_high_cents=900_000, deposit_cents=0,
                        bid_type="LIVE", clock=DEFAULT_CLOCK) -> dict:
    """Open lot -> one bidder bids `hammer_amount` -> hammer. Returns a bag with
    the hammered lot, bidder, winning bid, cascade-created invoice and line.
    """
    if starting_bid_cents is None:
        starting_bid_cents = hammer_amount
    bag = setup_open_lot(
        reserve_cents=reserve_cents, starting_bid_cents=starting_bid_cents,
        commission_rate=commission_rate, estimate_low_cents=estimate_low_cents,
        estimate_high_cents=estimate_high_cents, clock=clock,
    )
    bidder = make_bidder(deposit_cents=deposit_cents)
    bid = place_bid(bag["lot"]["id"], bidder["id"], hammer_amount,
                    bag["lot_version"], bid_type=bid_type)
    lot = get_success_data(api_client.hammer_lot(bag["lot"]["id"], STAFF))
    invoice = get_invoice_for(bidder["id"], bag["auction"]["id"])
    line = get_line_for_lot(bag["lot"]["id"])
    bag.update({
        "bidder": bidder,
        "bid": bid,
        "lot": lot,
        "invoice": invoice,
        "line": line,
    })
    return bag


# ─── Tier 4: two hammered lots, one bidder, one invoice, two lines ───────

def setup_two_hammers_one_bidder(amount1, amount2, starting1=None, starting2=None,
                                 commission_rate=0.15, estimate_low_cents=100_000,
                                 estimate_high_cents=900_000, clock=None) -> dict:
    """One consignment supplies L1 and L2; one bidder wins both in one auction;
    both HAMMERED into a single Invoice with two lines. Returns a bag.
    """
    if starting1 is None:
        starting1 = amount1
    if starting2 is None:
        starting2 = amount2
    if clock is not None:
        set_clock(clock)
    saleroom = make_saleroom()
    auction = make_auction(saleroom["id"])
    consignor = make_consignor()
    consignment = make_accepted_consignment(
        consignor["id"], commission_rate=commission_rate,
        estimate_low_cents=estimate_low_cents, estimate_high_cents=estimate_high_cents,
    )
    lot1 = make_lot(consignment["id"], auction["id"], title="L1",
                    starting_bid_cents=starting1, lot_number=1,
                    estimate_low_cents=estimate_low_cents,
                    estimate_high_cents=estimate_high_cents)
    lot2 = make_lot(consignment["id"], auction["id"], title="L2",
                    starting_bid_cents=starting2, lot_number=2,
                    estimate_low_cents=estimate_low_cents,
                    estimate_high_cents=estimate_high_cents)
    get_success_data(api_client.open_auction(auction["id"], STAFF))
    lot1 = get_success_data(api_client.open_lot(lot1["id"], STAFF))
    lot2 = get_success_data(api_client.open_lot(lot2["id"], STAFF))
    bidder = make_bidder()
    place_bid(lot1["id"], bidder["id"], amount1, lot1["version"])
    place_bid(lot2["id"], bidder["id"], amount2, lot2["version"])
    lot1 = get_success_data(api_client.hammer_lot(lot1["id"], STAFF))
    lot2 = get_success_data(api_client.hammer_lot(lot2["id"], STAFF))
    invoice = get_invoice_for(bidder["id"], auction["id"])
    line1 = get_line_for_lot(lot1["id"])
    line2 = get_line_for_lot(lot2["id"])
    return {
        "saleroom": saleroom,
        "auction": auction,
        "consignor": consignor,
        "consignment": consignment,
        "lot1": lot1,
        "lot2": lot2,
        "bidder": bidder,
        "invoice": invoice,
        "line1": line1,
        "line2": line2,
    }
