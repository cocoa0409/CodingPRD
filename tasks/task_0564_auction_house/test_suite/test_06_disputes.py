"""Authenticity disputes: the OPEN<->UNDER_REVIEW cycle, resolution-state guards,
the upheld void/rescind/settlement cascade, and the money-conservation invariants.
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
    create_dispute_payload,
    make_bidder_headers,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]
SETTLEMENT = TEST_USERS["settlement_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]


# ─── Corner: dispute filing / resolution guards ──────────────────────────

def test_duplicate_open_dispute_rejected(api):
    """PRD §3.8: "A line may carry only one live dispute at a time — if an `OPEN`
    or `UNDER_REVIEW` dispute already exists for that line, the new filing is
    rejected with `ERR_LINE_ALREADY_DISPUTED` (HTTP 409)."

    Design: Corner/validations/corner_duplicate_open_dispute_returns_conflict
    """
    bag = setup_single_hammer(250_000, starting_bid_cents=200_000)
    raise_dispute(bag["line"]["id"], bag["bidder"]["id"], reason="First")
    res = api.create_dispute(
        create_dispute_payload(bag["line"]["id"], reason="Second"),
        make_bidder_headers(bag["bidder"]["id"]),
    )
    validate_error(res, "ERR_LINE_ALREADY_DISPUTED")


def test_resolve_dispute_from_open_rejected(api):
    """PRD §3.8: "Resolution requires the dispute to be `UNDER_REVIEW`; a
    transition attempted from any other state yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_dispute_resolve_from_open_invalid
    """
    bag = setup_single_hammer(250_000, starting_bid_cents=200_000)
    dispute = raise_dispute(bag["line"]["id"], bag["bidder"]["id"])
    res = api.resolve_dispute(
        dispute["id"], {"outcome": "UPHELD", "resolution_notes": "x"}, APPRAISER
    )
    validate_error(res, "ERR_INVALID_STATE")


# ─── Difficulty: OPEN <-> UNDER_REVIEW cycle then terminal reject ────────

def test_dispute_cycles_open_and_under_review(api):
    """PRD §3.8: "Reviewing a dispute advances it `OPEN → UNDER_REVIEW` and is
    permitted only while it is `OPEN`."
    PRD §3.8: "the appraiser may request further provenance, optionally supplying
    a `note`, which bounces the dispute back `UNDER_REVIEW → OPEN` so the buyer can
    respond — this is the cyclic path that lets a dispute move between `OPEN` and
    `UNDER_REVIEW` more than once."

    Design: Difficulty/non_linear_state_machine/nl_dispute_cycle_review_requestinfo_review
    """
    bag = setup_single_hammer(250_000, starting_bid_cents=200_000)
    dispute = raise_dispute(bag["line"]["id"], bag["bidder"]["id"])
    s1 = validate_success(api.review_dispute(dispute["id"], APPRAISER), 200)
    assert s1["status"] == "UNDER_REVIEW"
    s2 = validate_success(
        api.request_info_dispute(dispute["id"], {"note": "Need certificate"}, APPRAISER), 200
    )
    assert s2["status"] == "OPEN"
    s3 = validate_success(api.review_dispute(dispute["id"], APPRAISER), 200)
    assert s3["status"] == "UNDER_REVIEW"


def test_dispute_rejected_after_cycle(api):
    """PRD §3.8: "A resolution `outcome` of `REJECTED` moves the dispute
    `UNDER_REVIEW → REJECTED`, records the `resolution_notes`, and makes no change
    to the line, lot, invoice, or settlement."

    Design: Difficulty/non_linear_state_machine/nl_dispute_cycle_review_requestinfo_review
    """
    bag = setup_single_hammer(250_000, starting_bid_cents=200_000)
    dispute = raise_dispute(bag["line"]["id"], bag["bidder"]["id"])
    review_dispute(dispute["id"])
    validate_success(
        api.request_info_dispute(dispute["id"], {"note": "Need certificate"}, APPRAISER), 200
    )
    review_dispute(dispute["id"])
    s4 = validate_success(
        api.resolve_dispute(dispute["id"], {"outcome": "REJECTED",
                                            "resolution_notes": "Authentic"}, APPRAISER), 200
    )
    assert s4["status"] == "REJECTED"


# ─── Difficulty: upheld dispute void -> rescind -> settlement cascade ────

def test_upheld_dispute_voids_line_and_rescinds_lot(api):
    """PRD §3.8: "The line is voided, transitioning its `status` `ACTIVE → VOID`."
    PRD §3.8: "The line's lot is rescinded, transitioning `sale_status`
    `HAMMERED → RESCINDED` and incrementing the lot's `version` by one."

    Design: Difficulty/transitive_cascade/tc_uphold_dispute_to_void_to_rescind_to_settlement
    """
    bag = setup_single_hammer(500_000, starting_bid_cents=400_000)
    make_settlement(bag["consignment"]["id"])
    dispute = raise_dispute(bag["line"]["id"], bag["bidder"]["id"])
    review_dispute(dispute["id"])
    resolve_dispute(dispute["id"], "UPHELD", "Confirmed forgery")
    line = validate_success(api.get_invoice_line(bag["line"]["id"], STAFF), 200)
    lot = validate_success(api.get_lot(bag["lot"]["id"], STAFF), 200)
    assert line["status"] == "VOID"
    assert lot["sale_status"] == "RESCINDED"


def test_upheld_dispute_zeroes_draft_settlement(api):
    """PRD §3.8: "if a `DRAFT` settlement exists for that lot's consignment, its
    `gross_hammer_cents`, `seller_commission_cents`, `net_payout_cents`, and
    `lot_count` are recomputed to exclude the now-rescinded lot".

    Design: Difficulty/transitive_cascade/tc_uphold_dispute_to_void_to_rescind_to_settlement
    """
    bag = setup_single_hammer(500_000, starting_bid_cents=400_000)
    settlement = make_settlement(bag["consignment"]["id"])
    dispute = raise_dispute(bag["line"]["id"], bag["bidder"]["id"])
    review_dispute(dispute["id"])
    resolve_dispute(dispute["id"], "UPHELD", "Confirmed forgery")
    data = validate_success(api.get_settlement(settlement["id"], SETTLEMENT), 200)
    assert data["gross_hammer_cents"] == 0
    assert data["net_payout_cents"] == 0


# ─── Difficulty: buyer-invoice money conservation on refund ──────────────

def test_upheld_dispute_records_line_refund(api):
    """PRD §3.8: "First, the dispute's `refund_cents` is set to the line's
    `line_total_cents` and its `resolution_notes` are recorded."
    PRD §3.8: "its `total_refunded_cents` grows by the line's `line_total_cents`".

    Design: Difficulty/compensating_invariant/ci_dispute_refund_conserves_invoice_billed
    """
    bag = setup_two_hammers_one_bidder(500_000, 250_000,
                                       starting1=400_000, starting2=200_000)
    dispute = raise_dispute(bag["line2"]["id"], bag["bidder"]["id"])
    review_dispute(dispute["id"])
    resolve_dispute(dispute["id"], "UPHELD", "Reproduction")
    invoice = validate_success(api.get_invoice(bag["invoice"]["id"], STAFF), 200)
    assert invoice["total_refunded_cents"] == 312_500


def test_invoice_due_plus_refunded_conserves_billed(api):
    """PRD §3.8: "its `hammer_subtotal_cents`, `premium_subtotal_cents`, and
    `total_due_cents` are recomputed over the remaining non-void lines, its
    `payment_status` is refreshed".

    Design: Difficulty/compensating_invariant/ci_dispute_refund_conserves_invoice_billed
    """
    bag = setup_two_hammers_one_bidder(500_000, 250_000,
                                       starting1=400_000, starting2=200_000)
    due_before = bag["invoice"]["total_due_cents"]
    assert due_before == 927_500
    dispute = raise_dispute(bag["line2"]["id"], bag["bidder"]["id"])
    review_dispute(dispute["id"])
    resolve_dispute(dispute["id"], "UPHELD", "Reproduction")
    invoice = validate_success(api.get_invoice(bag["invoice"]["id"], STAFF), 200)
    assert invoice["total_due_cents"] == 615_000
    assert invoice["total_due_cents"] + invoice["total_refunded_cents"] == due_before


# ─── Difficulty: seller-proceeds conservation on rescission ──────────────

def test_settlement_gross_excludes_rescinded_lot(api):
    """PRD §3.7: "The `gross_hammer_cents` is the sum of `hammer_price_cents` over
    the consignment's lots whose `sale_status` is `HAMMERED`, excluding any lot
    that has been rescinded."
    PRD §3.7: "`lot_count` is the number of `HAMMERED` (non-rescinded) lots
    included."

    Design: Difficulty/compensating_invariant/ci_dispute_rescind_conserves_settlement_gross
    """
    bag = setup_two_hammers_one_bidder(500_000, 250_000,
                                       starting1=400_000, starting2=200_000,
                                       commission_rate=0.15)
    settlement = make_settlement(bag["consignment"]["id"])
    dispute = raise_dispute(bag["line2"]["id"], bag["bidder"]["id"])
    review_dispute(dispute["id"])
    resolve_dispute(dispute["id"], "UPHELD", "Not genuine")
    data = validate_success(api.get_settlement(settlement["id"], SETTLEMENT), 200)
    assert data["gross_hammer_cents"] == 500_000
    assert data["lot_count"] == 1


def test_surviving_lot_remains_hammered_and_net_payout(api):
    """PRD §3.7: "The `net_payout_cents` is the gross hammer minus the commission".
    PRD §3.8: "A resolution `outcome` of `UPHELD` requires the challenged line's
    `status` to still be `ACTIVE`, moves the dispute `UNDER_REVIEW → UPHELD`, and
    triggers the system's most far-reaching cascade."

    Design: Difficulty/compensating_invariant/ci_dispute_rescind_conserves_settlement_gross
    """
    bag = setup_two_hammers_one_bidder(500_000, 250_000,
                                       starting1=400_000, starting2=200_000,
                                       commission_rate=0.15)
    settlement = make_settlement(bag["consignment"]["id"])
    dispute = raise_dispute(bag["line2"]["id"], bag["bidder"]["id"])
    review_dispute(dispute["id"])
    resolve_dispute(dispute["id"], "UPHELD", "Not genuine")
    data = validate_success(api.get_settlement(settlement["id"], SETTLEMENT), 200)
    assert data["net_payout_cents"] == 425_000
    lot1 = validate_success(api.get_lot(bag["lot1"]["id"], STAFF), 200)
    assert lot1["sale_status"] == "HAMMERED"
