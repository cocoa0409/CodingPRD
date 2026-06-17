"""Multi-hop cascades and conserved-quantity invariants.

The event-cancel four-hop cascade, the guarantee-refund three-hop cascade, and
the escrow/wallet conservation invariants (PRD §3.4, §3.5, §3.7, §3.9, §2.5).
"""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_seller_headers, make_buyer_headers,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["platform_admin_headers"]
TRUST = TEST_USERS["trust_safety_headers"]


# ==========================================================================
# transitive_cascade
# ==========================================================================
def test_event_cancel_four_hop_cascade_listing_order_payout_seat(api):
    """PRD §3.9: "First, every listing on the event whose `status` is `ACTIVE`,
    `SOLD_OUT`, `DRAFT`, or `FROZEN` is delisted to `DELISTED`. Second, every order
    on the event whose `payment_status` is `CHARGED` has an `EventCredit` issued
    for it and its `payment_status` moves to `CREDITED`. Third, each such order's
    `ESCROWED` payout is clawed back, with `clawback_cents` set to the full
    `net_payout_cents`. Fourth, every seat on the credited orders is voided and
    all available counts reconcile."

    Design: Difficulty/transitive_cascade/event_cancel_four_hop_cascade_listing_order_payout_seat
    """
    ctx = fx.setup_charged_order(quantity=2, seat_count=2, ask_price_cents=20000, trust_tier="NEW")
    order = ctx["order"]
    payout = ctx["payout"]
    seat0 = ctx["seats"][0]
    # net for a NEW-tier qty2 sale: gross 40000, fee floor(40000*0.15)=6000, net 34000.
    assert payout["net_payout_cents"] == 34000

    get_success_data(api.cancel_event(ctx["event_id"], ADMIN))

    listing_after = validate_success(api.get_listing(ctx["listing"]["id"], ADMIN))
    order_after = validate_success(api.get_order(order["id"], ADMIN))
    payout_after = validate_success(api.get_payout(payout["id"], ADMIN))
    seat_after = validate_success(api.get_seat(seat0["id"], ADMIN))
    credit = fx.get_credit_for_source_order(order["id"])

    assert listing_after["status"] == "DELISTED"
    assert order_after["payment_status"] == "CREDITED"
    assert credit["amount_cents"] == 44800, \
        f"non-loyal credit equals final_total 44800, got {credit['amount_cents']}"
    assert payout_after["status"] == "CLAWED_BACK"
    assert payout_after["clawback_cents"] == 34000, \
        f"clawback equals net 34000, got {payout_after['clawback_cents']}"
    assert seat_after["status"] == "VOID"


def test_guarantee_refund_depth3_cascade_order_payout_seat(api):
    """PRD §3.7: "For all reasons the refund equals the order's `final_total_cents`
    — what the buyer actually paid after credit."
    PRD §3.7: "A refund resolution moves the order's `payment_status` from
    `CHARGED` to `REFUNDED`, claws back the `ESCROWED` or `RELEASABLE` payout, and
    voids the order's `SOLD` seats."

    Design: Difficulty/transitive_cascade/guarantee_refund_depth3_cascade_order_payout_seat
    """
    ctx = fx.setup_delivery_failed_with_claim(quantity=2, reason="NOT_DELIVERED")
    order = ctx["order"]
    payout = ctx["payout"]
    seat0 = ctx["seats"][0]
    claim_id = ctx["claim"]["id"]
    assert payout["net_payout_cents"] == 34000

    resolved = validate_success(api.refund_claim(claim_id, TRUST))
    assert resolved["refund_amount_cents"] == 44800, \
        f"refund equals final_total 44800, got {resolved['refund_amount_cents']}"

    order_after = validate_success(api.get_order(order["id"], ADMIN))
    payout_after = validate_success(api.get_payout(payout["id"], ADMIN))
    seat_after = validate_success(api.get_seat(seat0["id"], ADMIN))

    assert order_after["payment_status"] == "REFUNDED"
    assert payout_after["status"] == "CLAWED_BACK"
    assert payout_after["clawback_cents"] == 34000
    assert seat_after["status"] == "VOID"


# ==========================================================================
# compensating_invariant
# ==========================================================================
def test_escrow_balance_conserved_under_charge_then_clawback(api):
    """PRD §3.5: "its `clawback_cents` is set to the full `net_payout_cents` at that
    moment, its `net_payout_cents` is then driven to 0, and the seller's
    `escrow_balance_cents` is recomputed. This compensation is exact: a forward
    charge that added some amount to escrow, paired with a clawback that removes
    precisely that net, leaves `escrow_balance_cents` at its pre-charge value, so
    the escrow ledger never drifts."

    Design: Difficulty/compensating_invariant/escrow_balance_conserved_under_charge_then_clawback
    """
    ctx = fx.setup_delivery_failed_with_claim(quantity=2, reason="NOT_DELIVERED")
    seller_id = ctx["seller_id"]
    claim_id = ctx["claim"]["id"]

    seller_after_charge = validate_success(api.get_seller(seller_id, ADMIN))
    assert seller_after_charge["escrow_balance_cents"] == 34000, \
        f"escrow after charge should be net 34000, got {seller_after_charge['escrow_balance_cents']}"

    get_success_data(api.refund_claim(claim_id, TRUST))

    seller_after_clawback = validate_success(api.get_seller(seller_id, ADMIN))
    assert seller_after_clawback["escrow_balance_cents"] == 0, \
        f"escrow conserved to pre-charge 0 after clawback, got {seller_after_clawback['escrow_balance_cents']}"


def test_buyer_wallet_credit_conserved_issue_then_redeem(api):
    """PRD §3.4: "The applied event credits are then consumed FIFO by their
    `created_at` ascending, moving from `ISSUED` to `REDEEMED`, and the buyer's
    `wallet_credit_cents` is recomputed."
    PRD §2.5: "A buyer's `wallet_credit_cents` is the sum of `amount_cents` across
    that buyer's event credits whose `status` is `ISSUED`, and it never goes
    negative."

    Design: Difficulty/compensating_invariant/buyer_wallet_credit_conserved_issue_then_redeem
    """
    earned = fx.setup_credit_earning_order(quantity=2, seat_count=2)
    buyer_id = earned["buyer_id"]
    seller_id = earned["seller_id"]
    venue_id = earned["venue_id"]
    section_id = earned["section_id"]

    buyer_after_issue = validate_success(api.get_buyer(buyer_id, ADMIN))
    assert buyer_after_issue["wallet_credit_cents"] == 44800, \
        f"wallet after issue should be 44800, got {buyer_after_issue['wallet_credit_cents']}"

    # Spend the full credit on a new 44800 order.
    event2 = fx.create_event(venue_id, doors_open_at="2028-04-01T19:00:00.000Z", title="E2")
    event2 = fx.open_sales(event2["id"])
    listing2, _ = fx.create_active_listing(
        event2["id"], seller_id, section_id, seat_count=2, barcode_prefix="W2",
    )
    order2 = fx.reserve_order(listing2["id"], buyer_id, 2, listing2["version"],
                              applied_credit_cents=44800)
    charged = validate_success(api.charge_order(order2["id"], make_buyer_headers(buyer_id)))
    assert charged["final_total_cents"] == 0, \
        f"full credit applied → final 0, got {charged['final_total_cents']}"

    buyer_after_redeem = validate_success(api.get_buyer(buyer_id, ADMIN))
    assert buyer_after_redeem["wallet_credit_cents"] == 0, \
        f"wallet conserved to pre-issue 0 after redeem, got {buyer_after_redeem['wallet_credit_cents']}"


# ==========================================================================
# Companion tests (second test per Difficulty instance)
# ==========================================================================
def test_event_cancel_credits_order_and_voids_seats(api):
    """PRD §3.9: "every order on the event whose `payment_status` is `CHARGED` has
    an `EventCredit` issued for it and its `payment_status` moves to `CREDITED`."
    PRD §3.9: "every seat on the credited orders is voided and all available
    counts reconcile."

    Design: Difficulty/transitive_cascade/event_cancel_four_hop_cascade_listing_order_payout_seat
    """
    ctx = fx.setup_charged_order(quantity=2, seat_count=2, trust_tier="NEW")
    order = ctx["order"]
    seat1 = ctx["seats"][1]

    get_success_data(api.cancel_event(ctx["event_id"], ADMIN))

    order_after = validate_success(api.get_order(order["id"], ADMIN))
    seat_after = validate_success(api.get_seat(seat1["id"], ADMIN))
    credit = fx.get_credit_for_source_order(order["id"])
    assert order_after["payment_status"] == "CREDITED"
    assert credit["status"] == "ISSUED"
    assert seat_after["status"] == "VOID"


def test_guarantee_refund_voids_seats_and_clawsback_payout(api):
    """PRD §3.7: "A refund resolution moves the order's `payment_status` from
    `CHARGED` to `REFUNDED`, claws back the `ESCROWED` or `RELEASABLE` payout, and
    voids the order's `SOLD` seats."

    Design: Difficulty/transitive_cascade/guarantee_refund_depth3_cascade_order_payout_seat
    """
    ctx = fx.setup_delivery_failed_with_claim(quantity=2, reason="NOT_DELIVERED")
    seat1 = ctx["seats"][1]
    payout = ctx["payout"]
    claim_id = ctx["claim"]["id"]

    get_success_data(api.refund_claim(claim_id, TRUST))

    seat_after = validate_success(api.get_seat(seat1["id"], ADMIN))
    payout_after = validate_success(api.get_payout(payout["id"], ADMIN))
    assert seat_after["status"] == "VOID"
    assert payout_after["status"] == "CLAWED_BACK"


def test_escrow_balance_zero_net_after_clawback_drives_net_to_zero(api):
    """PRD §3.5: "its `clawback_cents` is set to the full `net_payout_cents` at that
    moment, its `net_payout_cents` is then driven to 0, and the seller's
    `escrow_balance_cents` is recomputed."

    Design: Difficulty/compensating_invariant/escrow_balance_conserved_under_charge_then_clawback
    """
    ctx = fx.setup_delivery_failed_with_claim(quantity=2, reason="NOT_DELIVERED")
    payout = ctx["payout"]
    claim_id = ctx["claim"]["id"]
    assert payout["net_payout_cents"] == 34000

    get_success_data(api.refund_claim(claim_id, TRUST))
    payout_after = validate_success(api.get_payout(payout["id"], ADMIN))
    assert payout_after["clawback_cents"] == 34000, \
        f"clawback equals full net 34000, got {payout_after['clawback_cents']}"
    assert payout_after["net_payout_cents"] == 0, \
        f"net driven to 0 after clawback, got {payout_after['net_payout_cents']}"


def test_wallet_credit_rises_by_issued_credit_amount(api):
    """PRD §2.5: "A buyer's `wallet_credit_cents` is the sum of `amount_cents`
    across that buyer's event credits whose `status` is `ISSUED`, and it never
    goes negative."

    Design: Difficulty/compensating_invariant/buyer_wallet_credit_conserved_issue_then_redeem
    """
    earned = fx.setup_credit_earning_order(quantity=2, seat_count=2)
    buyer_id = earned["buyer_id"]
    credit = earned["credit"]
    assert credit["amount_cents"] == 44800

    buyer = validate_success(api.get_buyer(buyer_id, ADMIN))
    assert buyer["wallet_credit_cents"] == 44800, \
        f"wallet equals sum of ISSUED credits 44800, got {buyer['wallet_credit_cents']}"
