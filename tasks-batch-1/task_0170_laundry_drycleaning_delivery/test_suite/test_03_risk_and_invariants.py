"""Customer risk scoring, the order risk flag, and compensating invariants."""
import test_helpers as th


def test_customer_risk_note_lost_and_settle_accumulate(api):
    """PRD §3.8: "Logging a note adds the note's `severity` immediately. Marking
    a garment lost adds a fixed 15 points for the lost garment. Settling a claim
    adds a fixed 25 points on top of any earlier note contributions."

    STAIN note severity 5 (+5), then garment LOST (+15), then GARMENT claim
    declared 10000 settled (+25) => risk 45; settlement 8000.

    Design: Difficulty/dual_variant_calc/customer_risk_provisional_vs_settled
    """
    customer, pickup, delivery, order, garments = th.order_in_processing(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 3000}],
        actuals=[{"actual_weight_grams": 3000}],
    )
    th.validate_success(api.log_note(order["id"], garments[0]["id"],
                                     th.create_note_payload(note_kind="STAIN", severity=5, description="ink"),
                                     th.plant_headers()), expected_status=201)
    th.mark_lost(order, garments[0])
    settled = th.settle_garment_claim(order, customer, garments[0], declared_value_cents=10000)
    assert settled["settlement_cents"] == 8000, \
        f"settlement should be 8000, got {settled['settlement_cents']}"

    refreshed = th.validate_success(api.get_customer(customer["id"], th.admin_headers()))
    assert refreshed["risk_score"] == 45, \
        f"risk 5(note)+15(lost)+25(settle)=45, got {refreshed['risk_score']}"


def test_customer_risk_note_provisional_contribution(api):
    """PRD §3.8: "First, it contributes provisionally to the customer's running
    `risk_score`: the note's `severity` is added to the owning customer's
    `risk_score`."

    A single STAIN note of severity 5 raises risk to exactly 5 before any
    lost/settle contribution.

    Design: Difficulty/dual_variant_calc/customer_risk_provisional_vs_settled
    """
    customer, pickup, delivery, order, garments = th.order_in_processing(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 3000}],
        actuals=[{"actual_weight_grams": 3000}],
    )
    th.validate_success(api.log_note(order["id"], garments[0]["id"],
                                     th.create_note_payload(note_kind="STAIN", severity=5, description="ink"),
                                     th.plant_headers()), expected_status=201)
    refreshed = th.validate_success(api.get_customer(customer["id"], th.admin_headers()))
    assert refreshed["risk_score"] == 5, \
        f"note severity 5 adds 5 provisionally, got {refreshed['risk_score']}"


def test_order_risk_flag_set_at_threshold_exactly_12(api):
    """PRD §3.8: "the system sums the `severity` across all notes attached to any
    garment of the order, and sets `risk_flag` to true when that severity sum is
    at least the order-risk threshold of 12, and false otherwise - a severity sum
    of exactly 12 sets the flag, since the comparison is at-or-above the
    threshold, not strictly above it."

    Notes 7 + 5 = 12 (exactly the threshold) -> risk_flag true.

    Design: Difficulty/boundary_precision_check/order_risk_flag_threshold_exact_12
    """
    customer, pickup, delivery, order, garments = th.order_in_processing(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 3000}],
        actuals=[{"actual_weight_grams": 3000}],
    )
    th.validate_success(api.log_note(order["id"], garments[0]["id"],
                                     th.create_note_payload(note_kind="DAMAGE", severity=7, description="tear"),
                                     th.plant_headers()), expected_status=201)
    th.validate_success(api.log_note(order["id"], garments[0]["id"],
                                     th.create_note_payload(note_kind="STAIN", severity=5, description="grease"),
                                     th.plant_headers()), expected_status=201)
    th.finish_clean(order, garments[0])
    held = th.validate_success(api.qc_hold(order["id"], th.plant_headers()))
    assert held["risk_flag"] is True, \
        f"severity sum 12 (==threshold) sets risk_flag, got {held['risk_flag']}"


def test_order_risk_flag_below_threshold_stays_false(api):
    """PRD §3.8: "sets `risk_flag` to true when that severity sum is at least the
    order-risk threshold of 12, and false otherwise".

    Notes 7 + 4 = 11 (one below the threshold) -> risk_flag false. This pins the
    X-1 boundary point.

    Design: Difficulty/boundary_precision_check/order_risk_flag_threshold_exact_12
    """
    customer, pickup, delivery, order, garments = th.order_in_processing(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 3000}],
        actuals=[{"actual_weight_grams": 3000}],
    )
    th.validate_success(api.log_note(order["id"], garments[0]["id"],
                                     th.create_note_payload(note_kind="DAMAGE", severity=7, description="tear"),
                                     th.plant_headers()), expected_status=201)
    th.validate_success(api.log_note(order["id"], garments[0]["id"],
                                     th.create_note_payload(note_kind="STAIN", severity=4, description="spot"),
                                     th.plant_headers()), expected_status=201)
    th.finish_clean(order, garments[0])
    held = th.validate_success(api.qc_hold(order["id"], th.plant_headers()))
    assert held["risk_flag"] is False, \
        f"severity sum 11 (<threshold) leaves risk_flag false, got {held['risk_flag']}"


def test_cancel_restores_pickup_window_capacity(api):
    """PRD §3.3: "the pickup window's `booked_stops` is increased by one"
    PRD §3.7: "If a pickup stop was booked, the pickup window's `booked_stops` is
    decreased by one, and if that window was `FULL` it returns to `OPEN`."

    Schedule debits booked_stops to 1; cancel credits it back to 0, conserving
    free capacity.

    Design: Difficulty/compensating_invariant/cancel_restores_pickup_window_capacity
    """
    customer, pickup, delivery, order, garments = th.create_order_with_garments(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}])
    th.schedule_order(order, customer)
    ov = th.get_order(order["id"], customer["id"])["version"]
    th.validate_success(api.cancel_order(order["id"], {"expected_order_version": ov},
                                         th.make_customer_headers(customer["id"])))
    window = th.validate_success(api.get_route_window(pickup["id"], th.dispatch_headers()))
    assert window["booked_stops"] == 0, \
        f"booked_stops restored to 0, got {window['booked_stops']}"
    assert window["status"] == "OPEN", \
        f"window status restored to OPEN, got {window['status']}"


def test_cancel_full_pickup_window_reverts_to_open(api):
    """PRD §3.3: "if that brings `booked_stops` to equal `stop_capacity` the
    window's `status` flips to `FULL`."
    PRD §3.7: "If a pickup stop was booked, the pickup window's `booked_stops` is
    decreased by one, and if that window was `FULL` it returns to `OPEN`."

    A capacity-1 window goes FULL on schedule; cancelling the only booked order
    reverts it to OPEN with booked_stops 0 (conserving free capacity).

    Design: Difficulty/compensating_invariant/cancel_restores_pickup_window_capacity
    """
    pickup = th.create_pickup_window(zone_code="Z1", stop_capacity=1)
    delivery = th.create_delivery_window(zone_code="Z1", stop_capacity=5)
    customer = th.create_customer(zone_code="Z1")
    _, _, _, order, _ = th.create_order_with_garments(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}])
    th.schedule_order(order, customer)
    full = th.validate_success(api.get_route_window(pickup["id"], th.dispatch_headers()))
    assert full["status"] == "FULL", f"window should be FULL after schedule, got {full['status']}"
    ov = th.get_order(order["id"], customer["id"])["version"]
    th.validate_success(api.cancel_order(order["id"], {"expected_order_version": ov},
                                         th.make_customer_headers(customer["id"])))
    reverted = th.validate_success(api.get_route_window(pickup["id"], th.dispatch_headers()))
    assert reverted["status"] == "OPEN", f"window reverts to OPEN, got {reverted['status']}"
    assert reverted["booked_stops"] == 0, f"booked_stops back to 0, got {reverted['booked_stops']}"


def test_void_invoice_restores_wallet_credit(api):
    """PRD §3.6: "At draft creation the `wallet_applied_cents` is reserved by
    debiting it from the customer's `wallet_credit_cents`; this reservation is
    restored if the invoice is later voided"
    PRD §3.7: "Any `DRAFT` invoice for this order is voided, moving to `VOID`:
    voiding restores the reserved `wallet_applied_cents` back to the customer's
    `wallet_credit_cents`"

    Wallet seeded to 8000; a DOORSTEP order to READY reserves wallet against its
    gross; cancel voids the DRAFT invoice, restoring wallet to 8000.

    Design: Difficulty/compensating_invariant/void_invoice_restores_wallet_credit
    """
    customer, pickup, delivery = th.create_zone_setup()
    th.seed_wallet_via_settled_claim(customer, pickup, delivery, declared_value_cents=10000)
    before = th.validate_success(api.get_customer(customer["id"], th.admin_headers()))
    assert before["wallet_credit_cents"] == 8000, \
        f"wallet seeded to 8000, got {before['wallet_credit_cents']}"

    _, _, _, order, _ = th.order_at_ready(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 1}],
    )
    ov = th.get_order(order["id"], customer["id"])["version"]
    th.validate_success(api.cancel_order(order["id"], {"expected_order_version": ov},
                                         th.make_customer_headers(customer["id"])))
    after = th.validate_success(api.get_customer(customer["id"], th.admin_headers()))
    assert after["wallet_credit_cents"] == 8000, \
        f"wallet restored to 8000 after void, got {after['wallet_credit_cents']}"

    invoices, _ = th.validate_paginated(
        api.get_order_invoice(order["id"], th.make_customer_headers(customer["id"])))
    assert invoices[0]["status"] == "VOID", \
        f"invoice should be VOID, got {invoices[0]['status']}"


def test_void_invoice_wallet_reservation_was_debited_then_restored(api):
    """PRD §3.6: "At draft creation the `wallet_applied_cents` is reserved by
    debiting it from the customer's `wallet_credit_cents`"
    PRD §3.7: "voiding restores the reserved `wallet_applied_cents` back to the
    customer's `wallet_credit_cents`"

    Confirms the reserve-then-restore round trip is conservative: wallet is
    debited at READY (DRAFT created) and the full reservation comes back on the
    cancel/void, netting to the original 8000.

    Design: Difficulty/compensating_invariant/void_invoice_restores_wallet_credit
    """
    customer, pickup, delivery = th.create_zone_setup()
    th.seed_wallet_via_settled_claim(customer, pickup, delivery, declared_value_cents=10000)
    _, _, _, order, _ = th.order_at_ready(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 1}],
    )
    # at READY the DRAFT invoice has reserved wallet against its gross
    at_ready = th.validate_success(api.get_customer(customer["id"], th.admin_headers()))
    assert at_ready["wallet_credit_cents"] < 8000, \
        f"wallet partially reserved at DRAFT, got {at_ready['wallet_credit_cents']}"
    ov = th.get_order(order["id"], customer["id"])["version"]
    th.validate_success(api.cancel_order(order["id"], {"expected_order_version": ov},
                                         th.make_customer_headers(customer["id"])))
    after = th.validate_success(api.get_customer(customer["id"], th.admin_headers()))
    assert after["wallet_credit_cents"] == 8000, \
        f"void restores the full reservation to 8000, got {after['wallet_credit_cents']}"
