"""Pricing, cancellation-credit, fundraiser-donation, and payment-waterfall
calculations — the studio's money math.

Difficulty queue (A): dual_variant_calc, combinatorial_formula, boundary_precision_check.
Corner queue (B): calculations / consistency_model claims.
"""
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    make_customer_headers, TEST_USERS,
    create_studio, create_artist, create_customer, create_gift_card,
    setup_open_event_with_customer, book_reservation,
    pay_reservation, confirm_reservation, add_attendees, event_current_version,
    set_clock,
)

MANAGER = TEST_USERS["manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


def _payment_rows(api, reservation_id):
    """List the SETTLED/REVERSED Payment rows for a reservation (data array)."""
    data, _meta = validate_paginated(
        api.list_payments(MANAGER, params={"reservation_id": reservation_id}))
    return data


# ─── dual_variant_calc ──────────────────────────────────────────────────────

def test_credit_ladder_customer_cancel_under_24h_zero_credit(api):
    """PRD §3.9: "a cancellation fewer than 24 hours before start earns 0 percent.
    The granted credit credit_granted_cents is the reservation's total_cents
    multiplied by that percentage and divided by 100 by floor division."
    PRD §3.9: "the system records cancelled_at_hours_before: the whole number of
    hours between the cancellation moment (the current logical clock) and the
    event's start_utc, computed as the difference in seconds divided by 3600 and
    floored, which may be negative if the event has already started."

    Design: Difficulty/dual_variant_calc/dvc_cancellation_credit_ladder_vs_studio_override
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=30, seats_capacity=30, price_cents_per_seat=4500,
        clock=None, start_utc="2026-04-01T10:00:00Z", end_utc="2026-04-01T12:00:00Z",
        kit_fee_cents=1200)
    res = book_reservation(event["id"], customer["id"], seats=5, include_supply_kit=True)
    assert res["total_cents"] == 26250, f"expected total 26250, got {res['total_cents']}"

    cancelled = get_success_data(
        api.cancel_reservation(res["id"], make_customer_headers(customer["id"])))
    assert cancelled["credit_granted_cents"] == 0, (
        f"expected 0 credit at 10h (<24h), got {cancelled['credit_granted_cents']}")
    assert cancelled["cancelled_at_hours_before"] == 10, (
        f"expected 10 hours before, got {cancelled['cancelled_at_hours_before']}")


def test_credit_studio_event_cancel_forces_full_credit_under_24h(api):
    """PRD §3.11: "each reservation in HELD, CONFIRMED, or CHECKED_IN is cancelled
    to CANCELLED with full credit — the credit ladder is bypassed and the
    percentage is forced to 100 regardless of how many hours remain before start,
    so each such reservation's credit_granted_cents equals its full total_cents
    (studio-fault full credit)."

    Design: Difficulty/dual_variant_calc/dvc_cancellation_credit_ladder_vs_studio_override
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=30, seats_capacity=30, price_cents_per_seat=4500,
        clock=None, start_utc="2026-04-01T10:00:00Z", end_utc="2026-04-01T12:00:00Z",
        kit_fee_cents=1200)
    res = book_reservation(event["id"], customer["id"], seats=5, include_supply_kit=True)
    assert res["total_cents"] == 26250

    get_success_data(api.cancel_event(event["id"], MANAGER))
    after = get_success_data(api.get_reservation(res["id"], MANAGER))
    assert after["status"] == "CANCELLED"
    assert after["credit_granted_cents"] == 26250, (
        f"studio-override must grant 100% (26250) despite <24h timing, "
        f"got {after['credit_granted_cents']}")


def test_fundraiser_pledged_over_held_confirmed_before_close(api):
    """PRD §3.8: "The provisional pledged_donation_cents is forward-looking and is
    recomputed on every reservation create and cancel for fundraiser events. It is
    the event's fundraiser_donation_pct applied once to the aggregated base: first
    sum the total_cents of every reservation on the event whose status is HELD or
    CONFIRMED, then multiply that sum by fundraiser_donation_pct and divide by 100
    by floor division."

    Design: Difficulty/dual_variant_calc/dvc_fundraiser_pledged_vs_settled
    """
    set_clock("2026-04-01T00:00:00Z")
    studio = create_studio(room_capacity_seats=40, name="Gala Room")
    artist = create_artist(full_name="Bo")
    event = get_success_data(api.create_event({
        "studio_id": studio["id"], "title": "Charity Night", "event_type": "FUNDRAISER",
        "start_utc": "2026-04-02T10:00:00Z", "end_utc": "2026-04-02T12:00:00Z",
        "seats_capacity": 30, "price_cents_per_seat": 4500, "kit_fee_cents": 1200,
        "fundraiser_donation_pct": 40}, MANAGER))
    get_success_data(api.create_assignment(
        {"event_id": event["id"], "artist_id": artist["id"]}, MANAGER))
    get_success_data(api.schedule_event(event["id"], MANAGER))
    get_success_data(api.open_event(event["id"], MANAGER))
    customer = create_customer(email="fa@x.com")
    ch = make_customer_headers(customer["id"])

    # A=3 seats (13500), B=5 seats+kit (26250), C=4 seats gp10 (16200) — all HELD.
    a = book_reservation(event["id"], customer["id"], seats=3)
    b = book_reservation(event["id"], customer["id"], seats=5, include_supply_kit=True)
    c = book_reservation(event["id"], customer["id"], seats=4)
    assert (a["total_cents"], b["total_cents"], c["total_cents"]) == (13500, 26250, 16200)

    ev = get_success_data(api.get_event(event["id"], MANAGER))
    assert ev["pledged_donation_cents"] == 22380, (
        f"pledged must be 40% of 13500+26250+16200=56250 -> 22380, "
        f"got {ev['pledged_donation_cents']}")


def test_fundraiser_settled_over_checked_in_only_at_close(api):
    """PRD §3.8: "The final settled_donation_cents is computed once, at the moment
    the event closes, over actual attendance: sum the total_cents of every
    reservation on the event whose status is CHECKED_IN, then multiply by
    fundraiser_donation_pct and divide by 100 by floor division ... No-shows and
    cancellations are excluded from the settled figure."

    Design: Difficulty/dual_variant_calc/dvc_fundraiser_pledged_vs_settled
    """
    set_clock("2026-04-01T00:00:00Z")
    studio = create_studio(room_capacity_seats=40, name="Gala Room")
    artist = create_artist(full_name="Bo")
    event = get_success_data(api.create_event({
        "studio_id": studio["id"], "title": "Charity Night", "event_type": "FUNDRAISER",
        "start_utc": "2026-04-02T10:00:00Z", "end_utc": "2026-04-02T12:00:00Z",
        "seats_capacity": 30, "price_cents_per_seat": 4500, "kit_fee_cents": 1200,
        "fundraiser_donation_pct": 40}, MANAGER))
    get_success_data(api.create_assignment(
        {"event_id": event["id"], "artist_id": artist["id"]}, MANAGER))
    get_success_data(api.schedule_event(event["id"], MANAGER))
    get_success_data(api.open_event(event["id"], MANAGER))
    customer = create_customer(email="fa@x.com")
    cid = customer["id"]

    a = book_reservation(event["id"], cid, seats=3)            # 13500 -> NO_SHOW at close
    b = book_reservation(event["id"], cid, seats=5, include_supply_kit=True)  # 26250
    c = book_reservation(event["id"], cid, seats=4)            # 16200

    # B and C are paid, confirmed, fully rostered, and checked in; A is left HELD.
    pay_reservation(b["id"], cid)
    confirm_reservation(b["id"], cid)
    pay_reservation(c["id"], cid)
    confirm_reservation(c["id"], cid)
    add_attendees(b["id"], cid, 5)
    add_attendees(c["id"], cid, 4)
    get_success_data(api.check_in_reservation(b["id"], FRONT_DESK))
    get_success_data(api.check_in_reservation(c["id"], FRONT_DESK))

    set_clock("2026-04-02T11:00:00Z")
    closed = get_success_data(api.close_event(event["id"], MANAGER))
    assert closed["settled_donation_cents"] == 16980, (
        f"settled must be 40% of CHECKED_IN totals 26250+16200=42450 -> 16980, "
        f"got {closed['settled_donation_cents']}")
    a_after = get_success_data(api.get_reservation(a["id"], MANAGER))
    assert a_after["status"] == "NO_SHOW", "the un-checked-in HELD reservation is swept to NO_SHOW"


# ─── combinatorial_formula ──────────────────────────────────────────────────

def test_pricing_large_tier_discount_then_kit_add(api):
    """PRD §3.4: "a reservation of 8 or more seats earns 15 percent ... First the
    discount is applied to the whole-cent base by integer floor division — the
    discounted base is base_cents minus the quantity (base_cents multiplied by
    group_discount_pct, then divided by 100 discarding any remainder). Then the
    kit charge is computed ... The reservation's total_cents is the discounted base
    plus kit_charge_cents. The kit charge is never discounted."

    Design: Difficulty/combinatorial_formula/cf_tiered_group_discount_then_kit_add
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=40, seats_capacity=30, price_cents_per_seat=4500,
        clock=None, kit_fee_cents=1200)
    res = book_reservation(event["id"], customer["id"], seats=8, include_supply_kit=True)
    assert res["base_cents"] == 36000, f"base 8*4500, got {res['base_cents']}"
    assert res["group_discount_pct"] == 15, f"15% at >=8 seats, got {res['group_discount_pct']}"
    assert res["kit_charge_cents"] == 9600, f"kit 8*1200, got {res['kit_charge_cents']}"
    assert res["total_cents"] == 40200, (
        f"discount-then-add: (36000 - 5400) + 9600 = 40200, got {res['total_cents']}")


def test_pricing_kit_charge_is_never_discounted(api):
    """PRD §3.4: "Then the kit charge is computed: kit_charge_cents is the requested
    seats multiplied by the event's kit_fee_cents when include_supply_kit is true,
    and 0 otherwise. The reservation's total_cents is the discounted base plus
    kit_charge_cents. The kit charge is never discounted."

    Design: Difficulty/combinatorial_formula/cf_tiered_group_discount_then_kit_add
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=40, seats_capacity=30, price_cents_per_seat=4500,
        clock=None, kit_fee_cents=1000)
    # 10 seats -> 15% tier. base 45000, discounted 38250; kit 10*1000=10000 (full).
    res = book_reservation(event["id"], customer["id"], seats=10, include_supply_kit=True)
    assert res["group_discount_pct"] == 15
    assert res["base_cents"] == 45000
    assert res["kit_charge_cents"] == 10000, (
        f"kit charge is seats*kit_fee with no discount, got {res['kit_charge_cents']}")
    assert res["total_cents"] == 48250, (
        f"(45000 - 6750) + 10000 = 48250 (kit undiscounted), got {res['total_cents']}")


def test_payment_waterfall_giftcards_then_card_order(api):
    """PRD §3.5: "First come the supplied gift cards, processed in ascending order of
    each card's created_at: for each card the amount drawn is the smaller of the
    card's balance_cents and the still-uncovered remainder ... Third, any remainder
    still uncovered after gift cards and credit is charged to card: a single Payment
    with method of CARD is recorded for the whole remainder."
    PRD §3.1: "The moment a redemption brings balance_cents to exactly 0, the card
    automatically transitions to DEPLETED and is no longer tappable."

    Design: Difficulty/combinatorial_formula/cf_giftcard_credit_card_waterfall
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=30, seats_capacity=30, price_cents_per_seat=4500,
        clock=None, kit_fee_cents=1200)
    gc1 = create_gift_card(code="GC-1", issued_value_cents=10000)
    gc2 = create_gift_card(code="GC-2", issued_value_cents=5000)
    res = book_reservation(event["id"], customer["id"], seats=5, include_supply_kit=True)
    assert res["total_cents"] == 26250

    paid = pay_reservation(res["id"], customer["id"],
                           gift_card_ids=[gc1["id"], gc2["id"]], use_studio_credit=False)
    assert paid["payment_status"] == "PAID"
    assert paid["amount_paid_cents"] == 26250

    gc1_after = get_success_data(api.get_gift_card(gc1["id"], MANAGER))
    gc2_after = get_success_data(api.get_gift_card(gc2["id"], MANAGER))
    assert gc1_after["balance_cents"] == 0 and gc1_after["status"] == "DEPLETED"
    assert gc2_after["balance_cents"] == 0 and gc2_after["status"] == "DEPLETED"

    rows = _payment_rows(api, res["id"])
    by_method = {}
    for p in rows:
        by_method.setdefault(p["method"], []).append(p)
    gc_amounts = sorted(p["amount_cents"] for p in by_method.get("GIFT_CARD", []))
    assert gc_amounts == [5000, 10000], f"gift-card draws gc1=10000, gc2=5000, got {gc_amounts}"
    card_rows = by_method.get("CARD", [])
    assert len(card_rows) == 1 and card_rows[0]["amount_cents"] == 11250, (
        f"CARD covers remainder 26250-15000=11250, got {card_rows}")


def test_payment_waterfall_first_card_partial_second_card_untouched(api):
    """PRD §3.5: "First come the supplied gift cards, processed in ascending order of
    each card's created_at: for each card the amount drawn is the smaller of the
    card's balance_cents and the still-uncovered remainder ... Because the card
    source always absorbs whatever is left, a well-formed payment always reaches full
    coverage."

    Design: Difficulty/combinatorial_formula/cf_giftcard_credit_card_waterfall
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=30, seats_capacity=30, price_cents_per_seat=4500, clock=None)
    # total for 3 seats = 13500. gc1 (first) 20000 covers it all; gc2 untouched.
    gc1 = create_gift_card(code="GC-BIG", issued_value_cents=20000)
    gc2 = create_gift_card(code="GC-SECOND", issued_value_cents=5000)
    res = book_reservation(event["id"], customer["id"], seats=3)
    assert res["total_cents"] == 13500

    paid = pay_reservation(res["id"], customer["id"],
                           gift_card_ids=[gc1["id"], gc2["id"]], use_studio_credit=False)
    assert paid["amount_paid_cents"] == 13500

    gc1_after = get_success_data(api.get_gift_card(gc1["id"], MANAGER))
    gc2_after = get_success_data(api.get_gift_card(gc2["id"], MANAGER))
    assert gc1_after["balance_cents"] == 6500, (
        f"first card drawn down by 13500 (20000 -> 6500), got {gc1_after['balance_cents']}")
    assert gc2_after["balance_cents"] == 5000, (
        f"second card untouched once remainder hit 0, got {gc2_after['balance_cents']}")

    rows = _payment_rows(api, res["id"])
    gc_rows = [p for p in rows if p["method"] == "GIFT_CARD"]
    assert len(gc_rows) == 1 and gc_rows[0]["amount_cents"] == 13500, (
        f"only the first card produces a Payment row, got {gc_rows}")
    assert not [p for p in rows if p["method"] == "CARD"], "no CARD remainder when a card covers all"


# ─── boundary_precision_check ───────────────────────────────────────────────

def test_credit_ladder_48h_boundary_grants_full_credit(api):
    """PRD §3.9: "a cancellation at 48 or more hours before start earns 100 percent;
    a cancellation from 24 hours up to but not including 48 hours before start earns
    50 percent ... The granted credit credit_granted_cents is the reservation's
    total_cents multiplied by that percentage and divided by 100 by floor division."

    Design: Difficulty/boundary_precision_check/bpc_credit_ladder_48h_boundary
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500,
        clock=None, start_utc="2026-04-03T00:00:00Z", end_utc="2026-04-03T02:00:00Z")
    res = book_reservation(event["id"], customer["id"], seats=3)
    assert res["total_cents"] == 13500

    cancelled = get_success_data(
        api.cancel_reservation(res["id"], make_customer_headers(customer["id"])))
    assert cancelled["cancelled_at_hours_before"] == 48, (
        f"exactly 48h before start, got {cancelled['cancelled_at_hours_before']}")
    assert cancelled["credit_granted_cents"] == 13500, (
        f"48 >= 48 earns 100% -> 13500, got {cancelled['credit_granted_cents']}")


def test_credit_ladder_47h_just_below_boundary_is_half_credit(api):
    """PRD §3.9: "a cancellation from 24 hours up to but not including 48 hours before
    start earns 50 percent ... The granted credit credit_granted_cents is the
    reservation's total_cents multiplied by that percentage and divided by 100 by
    floor division."

    Design: Difficulty/boundary_precision_check/bpc_credit_ladder_48h_boundary
    """
    # Start exactly 48h out, then advance the clock 1 hour so 47h remain at cancel.
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500,
        clock=None, start_utc="2026-04-03T00:00:00Z", end_utc="2026-04-03T02:00:00Z")
    res = book_reservation(event["id"], customer["id"], seats=3)
    assert res["total_cents"] == 13500
    set_clock("2026-04-01T01:00:00Z")  # now 47h before start

    cancelled = get_success_data(
        api.cancel_reservation(res["id"], make_customer_headers(customer["id"])))
    assert cancelled["cancelled_at_hours_before"] == 47, (
        f"47h before start, got {cancelled['cancelled_at_hours_before']}")
    assert cancelled["credit_granted_cents"] == 6750, (
        f"24 <= 47 < 48 earns 50% -> 6750, got {cancelled['credit_granted_cents']}")


# ─── Corner: calculations / consistency_model ───────────────────────────────

def test_pricing_mid_tier_4_seats_10pct(api):
    """PRD §3.4: "a reservation of 4 to 7 seats inclusive earns 10 percent ... First
    the discount is applied to the whole-cent base by integer floor division — the
    discounted base is base_cents minus the quantity (base_cents multiplied by
    group_discount_pct, then divided by 100 discarding any remainder)."

    Design: Corner/calculations/pricing_mid_tier_seats4_10pct
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=5000, clock=None)
    res = book_reservation(event["id"], customer["id"], seats=4)
    assert res["group_discount_pct"] == 10
    assert res["base_cents"] == 20000
    assert res["total_cents"] == 18000, f"20000 - 2000 = 18000, got {res['total_cents']}"


def test_pricing_small_tier_3_seats_no_discount(api):
    """PRD §3.4: "a reservation of 3 or fewer seats earns 0 percent. The rounding
    order is pinned to discount-then-add ... The reservation's total_cents is the
    discounted base plus kit_charge_cents."

    Design: Corner/calculations/pricing_no_discount_seats3
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=5000, clock=None)
    res = book_reservation(event["id"], customer["id"], seats=3)
    assert res["group_discount_pct"] == 0
    assert res["total_cents"] == 15000, f"3*5000 with no discount, got {res['total_cents']}"


def test_payment_waterfall_studio_credit_only(api):
    """PRD §3.5: "Second, if use_studio_credit was requested and the customer's
    credit_balance_cents is positive, the amount drawn is the smaller of that
    balance and the remaining uncovered amount; when positive, a Payment with method
    of STUDIO_CREDIT is recorded, the customer's credit_balance_cents decreases by
    the draw and their credit_redeemed_cents increases by the same amount."

    Design: Corner/calculations/studio_credit_only_waterfall
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500,
        clock=None, credit_cents=20000)
    res = book_reservation(event["id"], customer["id"], seats=3)
    assert res["total_cents"] == 13500

    paid = pay_reservation(res["id"], customer["id"], use_studio_credit=True)
    assert paid["payment_status"] == "PAID"
    assert paid["amount_paid_cents"] == 13500

    cust_after = get_success_data(api.get_customer(customer["id"], MANAGER))
    assert cust_after["credit_balance_cents"] == 6500, (
        f"20000 - 13500 = 6500, got {cust_after['credit_balance_cents']}")
    assert cust_after["credit_redeemed_cents"] == 13500

    data = _payment_rows(api, res["id"])
    methods = sorted(p["method"] for p in data)
    assert methods == ["STUDIO_CREDIT"], f"only a STUDIO_CREDIT row, no CARD, got {methods}"
    credit_rows = [p for p in data if p["method"] == "STUDIO_CREDIT"]
    assert credit_rows[0]["amount_cents"] == 13500


def test_reservation_pricing_visible_in_create_response(api):
    """PRD §2.11: "The system is immediately consistent: every derived field is
    recomputed within the same operation that changes its inputs, with no deferred
    reconciliation."
    PRD §3.4: "Pricing is computed at creation and recorded on the reservation."

    Design: Corner/consistency_model/immediate_visibility_of_pricing_on_create
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500,
        clock=None, kit_fee_cents=1000)
    ver = event_current_version(event["id"])
    resp = api.create_reservation({
        "event_id": event["id"], "customer_id": customer["id"],
        "booking_mode": "PUBLIC", "seats": 2, "include_supply_kit": True,
        "expected_event_version": ver}, make_customer_headers(customer["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["total_cents"] == 11000, (
        f"create response itself carries total 9000 base + 2000 kit = 11000, "
        f"got {data['total_cents']}")
