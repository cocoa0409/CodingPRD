"""Pricing, commission, and refund calculations.

Effective listing price (FIXED and DYNAMIC), tiered seller commission, and the
buyer-protection refund re-issuance rule (PRD §3.3, §3.5, §3.7).
"""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_seller_headers, make_buyer_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]
TRUST = TEST_USERS["trust_safety_headers"]


def test_fixed_price_within_cap_effective_equals_ask(api):
    """PRD §3.3: "For a `FIXED` listing, the raw price is simply the
    `ask_price_cents`. ... In both modes the price cap is applied last: the
    `effective_price_cents` is the smaller of the raw price and the cap."

    Design: Corner/calculations/fixed_price_within_cap_effective_equals_ask
    """
    # face 10000, cap_mult 3 → cap 30000; FIXED ask 20000 <= cap → effective 20000.
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1)
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=1, ask_price_cents=20000, barcode_prefix="FP",
    )
    assert listing["effective_price_cents"] == 20000, \
        f"FIXED within cap → effective equals ask 20000, got {listing['effective_price_cents']}"


def test_dynamic_price_clamped_to_cap_when_demand_exceeds(api):
    """PRD §3.3: "In both modes the price cap is applied last: the
    `effective_price_cents` is the smaller of the raw price and the cap. The
    evaluation order is fixed — scarcity first, then the floor, then the cap
    clamp."

    Design: Corner/calculations/dynamic_price_clamped_to_cap_when_demand_exceeds
    """
    # face 10000, cap_mult 3 → cap 30000. A DYNAMIC listing's ask may not exceed
    # the cap at creation (PRD §3.3), so the cap clamp can only bind via scarcity:
    # ask 30000 (== cap), floor 10000, sell 2 of 4 → sold_ratio 0.5 → demand 1.25 →
    # raw floor(30000*1.25)=37500; max(floor 10000, 37500)=37500; cap 30000 → 30000.
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=4)
    listing, _ = fx.create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=4, pricing_mode="DYNAMIC", ask_price_cents=30000,
        dynamic_floor_cents=10000, barcode_prefix="DC",
    )
    order = fx.reserve_order(listing["id"], base["buyer_id"], 2, listing["version"])
    fx.charge_order(order["id"], base["buyer_id"])

    read = validate_success(api.get_listing(listing["id"], make_seller_headers(base["seller_id"])))
    assert read["available_seat_count"] == 2
    assert read["effective_price_cents"] == 30000, \
        f"raw 37500 clamped to cap 30000, got {read['effective_price_cents']}"


def test_seller_fee_verified_tier_rate_applied(api):
    """PRD §3.5: "Its `seller_fee_rate` is selected by the seller's `trust_tier` at
    charge time: 0.15 for `NEW`, 0.12 for `VERIFIED`, 0.10 for `TRUSTED`, and 0.20
    for `RESTRICTED`. The `seller_fee_cents` is the floor of the `gross_sale_cents`
    times that `seller_fee_rate`. The `net_payout_cents` is the `gross_sale_cents`
    minus the `seller_fee_cents` minus any `clawback_cents`."

    Design: Corner/calculations/seller_fee_verified_tier_rate_applied
    """
    # VERIFIED seller, qty2 gross 40000 → fee floor(40000*0.12)=4800, net 35200.
    ctx = fx.setup_charged_order(quantity=2, seat_count=2, trust_tier="VERIFIED")
    payout = ctx["payout"]
    assert payout["seller_fee_rate"] == 0.12
    assert payout["seller_fee_cents"] == 4800, \
        f"floor(40000*0.12)=4800, got {payout['seller_fee_cents']}"
    assert payout["net_payout_cents"] == 35200, \
        f"40000-4800=35200, got {payout['net_payout_cents']}"


def test_protection_refund_reissues_applied_credit(api):
    """PRD §3.7: "for a buyer-protection reason (`NOT_DELIVERED`, `INVALID_BARCODE`,
    or `DUPLICATE_SEAT`), in addition to the cash refund, a fresh `ISSUED` event
    credit for the order's `applied_credit_cents` is re-issued back to the buyer's
    wallet, so the credit is not lost."
    PRD §3.7: "For all reasons the refund equals the order's `final_total_cents` —
    what the buyer actually paid after credit."

    Design: Corner/calculations/protection_refund_reissues_applied_credit
    """
    # Buyer earns a 22400 credit from a qty1 cancelled-event order.
    earned = fx.setup_credit_earning_order(quantity=1, seat_count=1)
    buyer_id = earned["buyer_id"]
    seller_id = earned["seller_id"]
    venue_id = earned["venue_id"]
    section_id = earned["section_id"]
    assert earned["credit"]["amount_cents"] == 22400

    # New event/listing; apply full 22400 on a qty2 order (gross 44800, final 22400).
    event2 = fx.create_event(venue_id, doors_open_at="2027-09-01T19:00:00.000Z", title="E2")
    event2 = fx.open_sales(event2["id"])
    listing2, _ = fx.create_active_listing(
        event2["id"], seller_id, section_id, seat_count=2, barcode_prefix="PRF",
    )
    seller_h = make_seller_headers(seller_id)
    buyer_h = make_buyer_headers(buyer_id)
    order = fx.reserve_order(listing2["id"], buyer_id, 2, listing2["version"],
                             applied_credit_cents=22400)
    charged = fx.charge_order(order["id"], buyer_id)
    assert charged["final_total_cents"] == 22400

    transfer = get_success_data(api.initiate_transfer(order["id"], seller_h))
    get_success_data(api.fail_transfer(transfer["id"], seller_h))
    claim = get_success_data(api.create_guarantee_claim(
        F.create_guarantee_claim_payload(order["id"], reason="INVALID_BARCODE"), buyer_h))
    get_success_data(api.investigate_claim(claim["id"], TRUST))

    resolved = validate_success(api.refund_claim(claim["id"], TRUST))
    assert resolved["refund_amount_cents"] == 22400, \
        f"refund equals final 22400, got {resolved['refund_amount_cents']}"

    buyer = validate_success(api.get_buyer(buyer_id, ADMIN))
    assert buyer["wallet_credit_cents"] == 22400, \
        f"applied credit re-issued → wallet 22400, got {buyer['wallet_credit_cents']}"
