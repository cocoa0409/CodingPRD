"""Seller settlement: provisional-vs-final net payout, the invoices-paid gate on
approval, and the auction-open precondition for opening a lot.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_single_hammer,
    setup_two_hammers_one_bidder,
    make_settlement,
    raise_dispute,
    review_dispute,
    resolve_dispute,
    make_saleroom,
    make_auction,
    make_consignor,
    make_accepted_consignment,
    make_lot,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]
SETTLEMENT = TEST_USERS["settlement_headers"]


# ─── Difficulty: settlement net payout provisional vs final ──────────────

def test_settlement_net_provisional_counts_all_hammered(api):
    """PRD §3.7: "The `seller_commission_cents` is the gross hammer multiplied by
    the consignment's `commission_rate`, rounded half-up to whole cents. The
    `net_payout_cents` is the gross hammer minus the commission".
    PRD §3.7: "At creation and on interim recomputes it is provisional: the gross
    counts every lot that is `HAMMERED` at that moment, including lots whose
    authenticity dispute is still `OPEN` or `UNDER_REVIEW`."

    Design: Difficulty/dual_variant_calc/dv_settlement_net_provisional_vs_final
    """
    bag = setup_two_hammers_one_bidder(500_000, 250_000,
                                       starting1=400_000, starting2=200_000,
                                       commission_rate=0.15)
    settlement = make_settlement(bag["consignment"]["id"])
    assert settlement["gross_hammer_cents"] == 750_000
    assert settlement["net_payout_cents"] == 637_500


def test_settlement_net_final_after_upheld_dispute(api):
    """PRD §3.7: "At approval it is final: the gross counts only lots that remain
    `HAMMERED` after any upheld dispute has rescinded its lot, so an upheld dispute
    lowers the final gross relative to the provisional figure."
    PRD §3.8: "The line's lot is rescinded, transitioning `sale_status`
    `HAMMERED → RESCINDED` and incrementing the lot's `version` by one."

    Design: Difficulty/dual_variant_calc/dv_settlement_net_provisional_vs_final
    """
    bag = setup_two_hammers_one_bidder(500_000, 250_000,
                                       starting1=400_000, starting2=200_000,
                                       commission_rate=0.15)
    settlement = make_settlement(bag["consignment"]["id"])
    dispute = raise_dispute(bag["line2"]["id"], bag["bidder"]["id"])
    review_dispute(dispute["id"])
    resolve_dispute(dispute["id"], "UPHELD", "not authentic")
    updated = validate_success(api.get_settlement(settlement["id"], SETTLEMENT), 200)
    assert updated["gross_hammer_cents"] == 500_000
    assert updated["net_payout_cents"] == 425_000


# ─── Difficulty: settlement approval requires related invoices paid ──────

def test_settlement_approve_blocked_by_unpaid_invoice(api):
    """PRD §3.7: "it additionally requires that every invoice which includes a
    non-void line for one of this consignment's `HAMMERED` lots has
    `payment_status` equal to `PAID`; if any such invoice is unpaid, approval is
    rejected with `ERR_INVOICES_UNPAID` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cd_settlement_approve_requires_invoices_paid
    """
    bag = setup_single_hammer(250_000, starting_bid_cents=200_000)
    settlement = make_settlement(bag["consignment"]["id"])
    res = api.approve_settlement(settlement["id"], SETTLEMENT)
    validate_error(res, "ERR_INVOICES_UNPAID")


def test_settlement_approve_succeeds_once_invoice_paid(api):
    """PRD §3.7: "A settlement officer approves a draft statement, advancing it
    `DRAFT → APPROVED`."
    PRD §3.6: "`payment_status` is set to `PAID` when `amount_paid_cents` equals
    `total_due_cents`".

    Design: Difficulty/cross_entity_state_dependency/cd_settlement_approve_requires_invoices_paid
    """
    bag = setup_single_hammer(250_000, starting_bid_cents=200_000)
    settlement = make_settlement(bag["consignment"]["id"])
    validate_success(
        api.pay_invoice(bag["invoice"]["id"], {"amount_cents": 312_500}, STAFF), 200
    )
    data = validate_success(api.approve_settlement(settlement["id"], SETTLEMENT), 200)
    assert data["status"] == "APPROVED"


# ─── Difficulty: opening a lot requires its auction OPEN ─────────────────

def test_open_lot_blocked_when_auction_scheduled(api):
    """PRD §3.3: "This is permitted only when the lot is `CATALOGED` (otherwise
    `ERR_INVALID_STATE`) and its auction (`auction_id`) is currently `OPEN`; if
    the auction is not open, the request is rejected with `ERR_AUCTION_NOT_OPEN`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cd_lot_open_requires_auction_open
    """
    saleroom = make_saleroom()
    auction = make_auction(saleroom["id"])  # left SCHEDULED
    consignor = make_consignor()
    consignment = make_accepted_consignment(consignor["id"])
    lot = make_lot(consignment["id"], auction["id"])
    res = api.open_lot(lot["id"], STAFF)
    validate_error(res, "ERR_AUCTION_NOT_OPEN")


def test_open_lot_succeeds_after_auction_opens(api):
    """PRD §3.3: "Operations staff open a cataloged lot for bidding, advancing
    `sale_status` from `CATALOGED` to `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/cd_lot_open_requires_auction_open
    """
    saleroom = make_saleroom()
    auction = make_auction(saleroom["id"])
    consignor = make_consignor()
    consignment = make_accepted_consignment(consignor["id"])
    lot = make_lot(consignment["id"], auction["id"])
    validate_success(api.open_auction(auction["id"], STAFF), 200)
    data = validate_success(api.open_lot(lot["id"], STAFF), 200)
    assert data["sale_status"] == "OPEN"
