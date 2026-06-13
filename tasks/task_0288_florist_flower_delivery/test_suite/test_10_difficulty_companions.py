"""Companion tests pairing a second case to each depth-targeted rule.

Each test exercises the same rule its paired primary test asserts, from a
complementary angle (the passing side of a boundary, the unsurged/other branch,
the verifiable side effect), so every targeted rule carries >= 2 tests.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    make_customer_headers, make_florist_headers,
    set_clock, create_zone, create_arrangement, create_holiday_window,
    create_customer, create_florist, create_draft_order, quote_order,
    mark_authorized, book_order, get_order_wire_fulfillment, accept_wire_fulfillment,
    set_loyalty_tier, credit_wallet, create_schedule, emit_schedule, get_emitted_order,
    setup_authorized_order, setup_accepted_order, setup_delivered_order,
    setup_booked_order, setup_approved_claim, file_claim, approve_claim, TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── dual_variant_calc ────────────────────────────────────────────────────

def test_final_total_equals_estimate_when_no_wire_or_subs(api):
    """PRD §3.5: "its divergence from `estimated_total_cents` is exactly the wire
    surcharge plus the accepted substitution deltas". With a zero wire surcharge and
    no substitutions, the final equals the estimate.

    Design: Difficulty/dual_variant_calc/order_estimate_vs_final_diverge_on_wire_and_subs
    """
    ctx, order, _wf = setup_accepted_order(
        "2026-02-11T08:00:00Z",
        zone_overrides={"zone_code": "Z1b", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A-PREMb", "display_name": "Lux Roses b",
                               "base_price_cents": 5000, "premium_tier": "STANDARD"},
        florist_overrides={"shop_name": "Shop Ab", "wire_surcharge_cents": 0},
        order_overrides={"delivery_date": "2026-02-20", "window_start_minute": 540,
                         "window_end_minute": 720})
    quoted = validate_success(api.get_order(order["id"], DISPATCHER), 200)
    dispatched = validate_success(
        api.dispatch_order(order["id"], make_florist_headers(ctx["florist"]["id"])), 200)
    assert dispatched["final_total_cents"] == dispatched["estimated_total_cents"]
    assert dispatched["final_total_cents"] == quoted["estimated_total_cents"]


def test_wrong_item_refund_full_captured_amount(api):
    """PRD §3.7: "The reason fractions are 0.50 for `WILTED`, 1.00 for `WRONG_ITEM`,
    0.25 for `LATE`, and 0.75 for `DAMAGED`".
    PRD §3.7: "the captured `final_total_cents` is multiplied by the reason's
    fraction and rounded half-up to a whole cent". WRONG_ITEM 1.00 of 5800 = 5800.

    Design: Difficulty/dual_variant_calc/claim_refund_vs_loyalty_promotion_distinct_subjects
    """
    ctx, order, claim = setup_approved_claim(
        "2026-03-02T08:00:00Z", "WRONG_ITEM", "REFUND",
        zone_overrides={"zone_code": "Z2b", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A-STDb", "display_name": "Daisy b",
                               "base_price_cents": 5000, "premium_tier": "STANDARD",
                               "substitution_policy": "NONE"},
        order_overrides={"delivery_date": "2026-03-06", "window_start_minute": 540,
                         "window_end_minute": 720})
    assert claim["refund_cents"] == 5800, claim["refund_cents"]


# ─── combinatorial_formula ────────────────────────────────────────────────

def test_premium_surge_with_gold_discount_and_credit(api):
    """PRD §3.2: "the surged subtotal is the base price multiplied by the window's
    `surge_multiplier`, rounded half-up to a whole cent".
    PRD §3.2: "The discounted subtotal is the surged subtotal multiplied by one
    minus the combined discount fraction, rounded half-up to a whole cent."
    PRD §3.2: "the zone's `base_delivery_fee_cents` is added after discounts".
    PREMIUM 10000*1.5=15000, GOLD 0.10 -> 13500, +800 = 14300.

    Design: Difficulty/combinatorial_formula/estimate_pinned_eval_order_surge_then_discount_then_delivery
    """
    set_clock("2026-02-10T08:00:00Z")
    zone = create_zone(zone_code="Z3b", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="A-P2b", display_name="Lux2b", base_price_cents=10000,
                             premium_tier="PREMIUM", substitution_policy="SAME_VALUE")
    create_holiday_window(name="Vday2b", start_date="2026-02-14", end_date="2026-02-14",
                          surge_multiplier=1.5, applies_to_standard=False, surge_cutoff_hour_utc=20)
    cust = create_customer(email="g3@x.com", full_name="Gold3")
    set_loyalty_tier(cust["id"], "GOLD")
    order = create_draft_order(cust, arr, zone, delivery_date="2026-02-14",
                               window_start_minute=540, window_end_minute=720)
    quoted = quote_order(order, cust)
    assert quoted["estimated_total_cents"] == 14300, quoted["estimated_total_cents"]


def test_silver_recurring_combined_discount_below_cap(api):
    """PRD §3.2: "The loyalty discount fraction is 0.00 for a `STANDARD` customer,
    0.05 for `SILVER`, and 0.10 for `GOLD`."
    PRD §3.2: "A recurring discount fraction is added only when the order was emitted
    by a schedule (its `parent_recurrence_id` is set), in which case it equals that
    schedule's `recurring_discount_pct`".
    PRD §3.2: "The loyalty and recurring fractions are summed, then the combined
    fraction is capped at 0.30." SILVER 0.05 + recurring 0.10 = 0.15; 8000*0.85=6800
    + delivery 600 = 7400.

    Design: Difficulty/combinatorial_formula/discount_stacking_additive_then_clamped_min_max
    """
    set_clock("2026-04-01T08:00:00Z")
    zone = create_zone(zone_code="Z4b", base_delivery_fee_cents=600,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="A-Rb", display_name="Recur Mix b", base_price_cents=8000,
                             premium_tier="STANDARD", substitution_policy="SAME_VALUE")
    cust = create_customer(email="sr@x.com", full_name="SilverRecur")
    set_loyalty_tier(cust["id"], "SILVER")
    sched = create_schedule(cust, arr, zone, cadence="MONTHLY", next_delivery_date="2026-04-10",
                            window_start_minute=540, window_end_minute=720,
                            occurrences_remaining=3, recurring_discount_pct=0.10)
    emit_schedule(sched)
    emitted = get_emitted_order(sched)
    quoted = validate_success(api.quote_order(emitted["id"], DISPATCHER), 200)
    assert quoted["estimated_total_cents"] == 7400, quoted["estimated_total_cents"]


# ─── non_linear_state_machine ─────────────────────────────────────────────

def test_dispatch_advances_fulfillment_and_captures_payment_independently(api):
    """PRD §3.5: "captures payment by advancing `payment_status` from `AUTHORIZED`
    to `CAPTURED` at the just-computed final amount". The two parallel dimensions
    move on dispatch: fulfillment BOOKED->IN_TRANSIT and payment AUTHORIZED->CAPTURED.

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    ctx, order, _wf = setup_accepted_order(
        "2026-05-03T08:00:00Z",
        zone_overrides={"zone_code": "Z5c", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A5c", "display_name": "Bouquet5c", "base_price_cents": 5000},
        florist_overrides={"wire_surcharge_cents": 0},
        order_overrides={"delivery_date": "2026-05-07", "window_start_minute": 540,
                         "window_end_minute": 720})
    dispatched = validate_success(
        api.dispatch_order(order["id"], make_florist_headers(ctx["florist"]["id"])), 200)
    assert dispatched["fulfillment_status"] == "IN_TRANSIT"
    assert dispatched["payment_status"] == "CAPTURED"


def test_redelivery_order_copies_card_and_occasion_and_is_unpaid(api):
    """PRD §3.7: "it copies the original's arrangement, zone, delivery window,
    `card_message`, and `occasion`, its `delivery_date` is set to the clock date
    plus one day, and it begins fresh at `DRAFT` fulfillment and `UNPAID` payment".

    Design: Difficulty/non_linear_state_machine/claim_branch_then_redelivery_cycles_new_order
    """
    ctx, order, claim = setup_approved_claim(
        "2026-05-11T08:00:00Z", "WILTED", "REDELIVERY",
        zone_overrides={"zone_code": "Z6b", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A6b", "display_name": "Bouquet6b", "base_price_cents": 5000},
        order_overrides={"card_message": "Recover soon", "occasion": "SYMPATHY",
                         "delivery_date": "2026-05-16", "window_start_minute": 540,
                         "window_end_minute": 720})
    current = validate_success(api.get_order(order["id"], DISPATCHER), 200)
    resolved = validate_success(api.resolve_claim(
        claim["id"], {"expected_order_version": current["version"]}, DISPATCHER), 200)
    redel = validate_success(api.get_order(resolved["redelivery_order_id"], DISPATCHER), 200)
    assert redel["card_message"] == "Recover soon"
    assert redel["occasion"] == "SYMPATHY"
    assert redel["payment_status"] == "UNPAID"


# ─── transitive_cascade ───────────────────────────────────────────────────

def test_cancel_booked_releases_slot_frees_zone_window(api):
    """PRD §3.6: "If a delivery slot exists and is not yet released, its `released`
    flag is set to true, freeing that zone-window capacity." A capacity-1 window
    re-opens for a new booking after the booked order is cancelled.

    Design: Difficulty/transitive_cascade/cancel_booked_cascades_slot_then_fulfillment_then_florist_load
    """
    ctx, order, _wf = setup_booked_order(
        "2026-06-02T08:00:00Z",
        zone_overrides={"zone_code": "Z7b", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 1},
        arrangement_overrides={"sku": "A7b", "display_name": "Bouquet7b", "base_price_cents": 5000},
        florist_overrides={"daily_capacity": 5},
        order_overrides={"delivery_date": "2026-06-06", "window_start_minute": 540,
                         "window_end_minute": 720})
    validate_success(api.cancel_order(order["id"], make_customer_headers(ctx["customer"]["id"])), 200)
    # Same (date, window) on a capacity-1 zone now books because the slot was freed.
    fresh = create_draft_order(ctx["customer"], ctx["arrangement"], ctx["zone"],
                               delivery_date="2026-06-06", window_start_minute=540,
                               window_end_minute=720)
    fresh = quote_order(fresh, ctx["customer"])
    fresh = mark_authorized(fresh["id"])
    rebooked = validate_success(api.book_order(
        fresh["id"], {"expected_order_version": fresh["version"]},
        make_customer_headers(ctx["customer"]["id"])), 200)
    assert rebooked["fulfillment_status"] == "BOOKED"


def test_refund_resolve_drives_order_to_refunded_terminal(api):
    """PRD §3.7: "When the remedy is `REFUND`, resolution drives the linked order's
    `payment_status` from `CAPTURED` to the terminal `REFUNDED` state".

    Design: Difficulty/transitive_cascade/claim_refund_resolve_cascades_payment_then_wallet
    """
    ctx, order, claim = setup_approved_claim(
        "2026-06-11T08:00:00Z", "DAMAGED", "REFUND",
        zone_overrides={"zone_code": "Z8b", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A8b", "display_name": "Bouquet8b", "base_price_cents": 5000},
        order_overrides={"delivery_date": "2026-06-16", "window_start_minute": 540,
                         "window_end_minute": 720})
    # DAMAGED 0.75 of 5800 = 4350 (floor 1000, cap 5800).
    assert claim["refund_cents"] == 4350, claim["refund_cents"]
    current = validate_success(api.get_order(order["id"], DISPATCHER), 200)
    validate_success(api.resolve_claim(
        claim["id"], {"expected_order_version": current["version"]}, DISPATCHER), 200)
    order_after = validate_success(api.get_order(order["id"], DISPATCHER), 200)
    assert order_after["payment_status"] == "REFUNDED"


# ─── priority_pair_validation_conflict ────────────────────────────────────

def test_unauthorized_book_state_error_before_capacity_check(api):
    """PRD §2.9: "first whether the requested state transition is defined from the
    resource's current state (`ERR_INVALID_STATE`), then the cross-dimension and
    cross-entity preconditions and the domain-specific temporal, capacity, and
    policy rules described in §3". A DRAFT order's state failure pre-empts capacity
    even when no florist is registered in the zone at all.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_capacity_on_book
    """
    set_clock("2026-07-01T09:00:00Z")
    zone = create_zone(zone_code="Z9b", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="A9b", display_name="Bouquet9b", base_price_cents=5000)
    cust = create_customer(email="cp2@x.com", full_name="Conf2 C")
    # No florist exists in the zone — capacity check would fail, but state fails first.
    draft = create_draft_order(cust, arr, zone, delivery_date="2026-07-05",
                               window_start_minute=540, window_end_minute=720)
    res = api.book_order(draft["id"], {"expected_order_version": draft["version"]},
                         make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_existence_beats_cutoff_for_nonexistent_order_before_cutoff_too(api):
    """PRD §2.9: "After authorization comes existence: every path identifier and
    body foreign key must resolve, or the request fails with `ERR_NOT_FOUND`." Even
    with the clock set well before any cutoff, a fabricated order id yields NOT_FOUND.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_temporal_cutoff_on_quote
    """
    set_clock("2026-07-02T08:00:00Z")  # 08:00 is before a 14 cutoff
    res = api.quote_order("00000000-0000-4000-8000-000000000abc", DISPATCHER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ─── boundary_precision_check ─────────────────────────────────────────────

def test_same_day_quote_before_cutoff_hour_succeeds(api):
    """PRD §3.3: "For a same-day order, the clock hour-of-day must be strictly less
    than the **effective cutoff hour**." Clock hour 13 < cutoff 14 passes;
    is_same_day is set true.

    Design: Difficulty/boundary_precision_check/same_day_cutoff_hour_exact_boundary
    """
    set_clock("2026-07-03T13:00:00Z")
    zone = create_zone(zone_code="Z10b", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="A10b", display_name="Bouquet10b", base_price_cents=5000)
    cust = create_customer(email="sd2@x.com", full_name="SameDay2 C")
    order = create_draft_order(cust, arr, zone, delivery_date="2026-07-03",
                               window_start_minute=900, window_end_minute=1000)
    quoted = validate_success(api.quote_order(order["id"], make_customer_headers(cust["id"])), 200)
    assert quoted["fulfillment_status"] == "QUOTED"
    assert quoted["is_same_day"] is True


def test_first_booking_into_capacity_one_window_succeeds(api):
    """PRD §3.4: "the number of existing non-released bookings sharing that same
    zone, that same date, and that same `[window_start_minute, window_end_minute)`
    window is strictly fewer than the zone's `window_capacity_per_slot`". With
    capacity 1 and zero existing, the first booking succeeds.

    Design: Difficulty/boundary_precision_check/zone_window_capacity_exact_fill_boundary
    """
    ctx, order = setup_authorized_order(
        "2026-07-04T08:00:00Z",
        zone_overrides={"zone_code": "Z11b", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 1},
        arrangement_overrides={"sku": "A11b", "display_name": "Bouquet11b", "base_price_cents": 5000},
        florist_overrides={"daily_capacity": 5},
        order_overrides={"delivery_date": "2026-07-08", "window_start_minute": 540,
                         "window_end_minute": 720})
    booked = validate_success(api.book_order(
        order["id"], {"expected_order_version": order["version"]},
        make_customer_headers(ctx["customer"]["id"])), 200)
    assert booked["fulfillment_status"] == "BOOKED"


# ─── cross_entity_state_dependency ────────────────────────────────────────

def test_dispatch_after_accept_succeeds(api):
    """PRD §3.5: "it carries the cross-entity precondition that the order's wire
    fulfillment has `status` `ACCEPTED`". Once accepted, dispatch is permitted and
    moves the order to IN_TRANSIT.

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_wire_fulfillment_accepted
    """
    ctx, order, _wf = setup_accepted_order(
        "2026-08-02T08:00:00Z",
        zone_overrides={"zone_code": "Z12b", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A12b", "display_name": "Bouquet12b", "base_price_cents": 5000},
        order_overrides={"delivery_date": "2026-08-06", "window_start_minute": 540,
                         "window_end_minute": 720})
    dispatched = validate_success(
        api.dispatch_order(order["id"], make_florist_headers(ctx["florist"]["id"])), 200)
    assert dispatched["fulfillment_status"] == "IN_TRANSIT"


def test_claim_allowed_on_delivered_order(api):
    """PRD §3.7: "A claim may only be filed against an order whose
    `fulfillment_status` is `DELIVERED`".
    PRD §3.7: "A new claim begins with `status` `OPEN`". A claim on a properly
    DELIVERED order is accepted.

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_order_delivered
    """
    ctx, order, _wf = setup_delivered_order(
        "2026-08-12T08:00:00Z",
        zone_overrides={"zone_code": "Z13b", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A13b", "display_name": "Bouquet13b", "base_price_cents": 5000},
        order_overrides={"delivery_date": "2026-08-16", "window_start_minute": 540,
                         "window_end_minute": 720})
    claim = validate_success(api.create_claim(
        {"order_id": order["id"], "customer_id": ctx["customer"]["id"],
         "reason": "WILTED", "requested_remedy": "REFUND"},
        make_customer_headers(ctx["customer"]["id"])), 201)
    assert claim["status"] == "OPEN"


# ─── resource_temporal_overlap ────────────────────────────────────────────

def test_same_halfopen_window_second_booking_collides(api):
    """PRD §3.4: "the number of existing non-released bookings sharing that same
    zone, that same date, and that same `[window_start_minute, window_end_minute)`
    window is strictly fewer than the zone's `window_capacity_per_slot`; if that
    window is already full, booking is rejected with `ERR_ZONE_WINDOW_FULL`." An
    identical [540,720) second booking on a capacity-1 zone collides.

    Design: Difficulty/resource_temporal_overlap/zone_window_same_halfopen_interval_collides
    """
    ctx, first = setup_authorized_order(
        "2026-09-01T08:00:00Z",
        zone_overrides={"zone_code": "Z14b", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 1},
        arrangement_overrides={"sku": "A14b", "display_name": "Bouquet14b", "base_price_cents": 5000},
        florist_overrides={"daily_capacity": 5},
        order_overrides={"delivery_date": "2026-09-05", "window_start_minute": 540,
                         "window_end_minute": 720})
    book_order(first, ctx["customer"], first["version"])
    second = create_draft_order(ctx["customer"], ctx["arrangement"], ctx["zone"],
                                delivery_date="2026-09-05", window_start_minute=540,
                                window_end_minute=720)
    second = quote_order(second, ctx["customer"])
    second = mark_authorized(second["id"])
    res = api.book_order(second["id"], {"expected_order_version": second["version"]},
                         make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_ZONE_WINDOW_FULL", expected_status=409)


def test_florist_daily_capacity_two_allows_two_same_date_bookings(api):
    """PRD §3.4: "whose count of non-released wire fulfillments for the order's
    `delivery_date` is strictly fewer than its `daily_capacity` (that is, the shop
    has headroom on that date)". With daily_capacity 2, two same-date orders book.

    Design: Difficulty/resource_temporal_overlap/florist_daily_aggregate_capacity_overlap
    """
    ctx, first = setup_authorized_order(
        "2026-09-08T08:00:00Z",
        zone_overrides={"zone_code": "Z15b", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A15b", "display_name": "Bouquet15b", "base_price_cents": 5000},
        florist_overrides={"daily_capacity": 2},
        order_overrides={"delivery_date": "2026-09-10", "window_start_minute": 540,
                         "window_end_minute": 600})
    book_order(first, ctx["customer"], first["version"])
    second = create_draft_order(ctx["customer"], ctx["arrangement"], ctx["zone"],
                                delivery_date="2026-09-10", window_start_minute=800,
                                window_end_minute=900)
    second = quote_order(second, ctx["customer"])
    second = mark_authorized(second["id"])
    booked = validate_success(api.book_order(
        second["id"], {"expected_order_version": second["version"]},
        make_customer_headers(ctx["customer"]["id"])), 200)
    assert booked["fulfillment_status"] == "BOOKED"


# ─── compensating_invariant ───────────────────────────────────────────────

def test_quote_with_wallet_credit_debits_then_cancel_restores(api):
    """PRD §3.2: "this amount is recorded on the order as
    `wallet_credit_applied_cents`, the customer's `wallet_credit_cents` is debited by
    exactly that amount". The debit is observable before cancellation restores it.

    Design: Difficulty/compensating_invariant/cancel_quoted_conserves_wallet_credit
    """
    set_clock("2026-10-01T08:00:00Z")
    zone = create_zone(zone_code="Z16b", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="A16b", display_name="Bouquet16b", base_price_cents=5000)
    cust = create_customer(email="wl2@x.com", full_name="Wallet2 C")
    credit_wallet(cust["id"], 1500)
    order = create_draft_order(cust, arr, zone, delivery_date="2026-10-05",
                               window_start_minute=540, window_end_minute=720,
                               apply_wallet_credit=True)
    order = quote_order(order, cust)
    cust_mid = validate_success(api.get_customer(cust["id"], DISPATCHER), 200)
    assert cust_mid["wallet_credit_cents"] == 0, "wallet debited at quote time"
    validate_success(api.cancel_order(order["id"], make_customer_headers(cust["id"])), 200)
    cust_after = validate_success(api.get_customer(cust["id"], DISPATCHER), 200)
    assert cust_after["wallet_credit_cents"] == 1500


def test_booked_consumes_florist_headroom_blocking_second(api):
    """PRD §3.4: "Booking increments the chosen florist's daily load for that date".
    PRD §3.4: "the booking is rejected with `ERR_NO_FLORIST_AVAILABLE`". On a
    capacity-1 florist a booking consumes the only unit, so a second same-date
    booking fails until the first is cancelled.

    Design: Difficulty/compensating_invariant/cancel_booked_conserves_florist_daily_capacity
    """
    ctx, first = setup_authorized_order(
        "2026-10-08T08:00:00Z",
        zone_overrides={"zone_code": "Z17b", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A17b", "display_name": "Bouquet17b", "base_price_cents": 5000},
        florist_overrides={"daily_capacity": 1},
        order_overrides={"delivery_date": "2026-10-12", "window_start_minute": 540,
                         "window_end_minute": 720})
    book_order(first, ctx["customer"], first["version"])  # consumes the 1 unit
    second = create_draft_order(ctx["customer"], ctx["arrangement"], ctx["zone"],
                                delivery_date="2026-10-12", window_start_minute=800,
                                window_end_minute=900)
    second = quote_order(second, ctx["customer"])
    second = mark_authorized(second["id"])
    res = api.book_order(second["id"], {"expected_order_version": second["version"]},
                         make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_NO_FLORIST_AVAILABLE", expected_status=409)
