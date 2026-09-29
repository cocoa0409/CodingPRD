"""Pro order lifecycle: the two state dimensions, the staging gate and cancellation.

Every test builds its own world from published endpoints against an empty database.
"""

from test_helpers import (
    ApiErrorId,
    CREDIT_MANAGER,
    PRO_DESK_ASSOCIATE,
    SKU_MORTAR_BAG,
    SKU_SHINGLE_BUNDLE,
    STORE_OPERATIONS,
    allocate_reservations,
    assert_order_dimensions,
    assert_store_stock_invariants,
    create_credit_line,
    create_draft_order,
    create_delivery_appointment_payload,
    create_delivery_truck,
    create_pro_account,
    create_store,
    create_store_stock,
    create_will_call_staging_payload,
    make_contractor_admin_headers,
    read_credit_line,
    read_pro_order,
    read_store_stock,
    reserve_order,
    setup_fulfilled_delivery_order,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Shared world builders (inlined per test; no cross-test state)                 #
# --------------------------------------------------------------------------- #


def _delivery_world():
    """Store + lift-gate truck + GOLD account + credit line + a 40-unit delivery order."""
    store = create_store(
        store_code="HD-101",
        region_code="MIDWEST",
        state_code="IL",
        distance_rank=1,
        will_call_bay_slots=2,
        lift_gate_available=True,
        tax_rate_pct=0.0825,
        max_stage_hours=48,
    )
    create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    truck = create_delivery_truck(
        store["id"],
        truck_code="T-1",
        lift_gate_equipped=True,
        access_types_supported=["CURBSIDE", "DRIVEWAY"],
        turnaround_buffer_minutes=30,
    )
    account = create_pro_account(
        store["id"],
        business_name="Ridgeline Roofing",
        po_required=False,
        job_name_required=False,
        tier_review_mode="PINNED_AT_REVIEW",
        baseline_volume_cents=6_000_000,
    )
    credit_line = create_credit_line(
        account["id"], limit_cents=100_000_000, terms_days=30
    )
    return store, truck, account, credit_line


def _two_line_will_call_world():
    """Store stocking two SKUs + MEMBER account + a reserved two-line will-call order."""
    store = create_store(
        store_code="HD-101",
        region_code="MIDWEST",
        state_code="IL",
        distance_rank=1,
        will_call_bay_slots=2,
        lift_gate_available=True,
        tax_rate_pct=0.0825,
        max_stage_hours=48,
    )
    create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    create_store_stock(
        store["id"], SKU_MORTAR_BAG, on_hand_units=500, list_unit_price_cents=2000
    )
    account = create_pro_account(
        store["id"],
        business_name="Corner Handyman",
        po_required=False,
        job_name_required=False,
        tier_review_mode="PINNED_AT_REVIEW",
        baseline_volume_cents=0,
    )
    order, order_lines = create_draft_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 5), (SKU_MORTAR_BAG, 5)],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
        lift_gate_required=False,
        job_lot_required=False,
        resale_purchase=False,
    )
    submit_order(order["id"], account["id"])
    reservations = reserve_order(order["id"])
    return store, account, order, reservations


def _allocated_will_call_world():
    """GOLD account, 40-unit credit-line order submitted, reserved and allocated."""
    store = create_store(
        store_code="HD-101",
        region_code="MIDWEST",
        state_code="IL",
        distance_rank=1,
        will_call_bay_slots=2,
        lift_gate_available=True,
        tax_rate_pct=0.0825,
        max_stage_hours=48,
    )
    stock = create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    account = create_pro_account(
        store["id"],
        business_name="Ridgeline Roofing",
        po_required=False,
        job_name_required=False,
        tier_review_mode="PINNED_AT_REVIEW",
        baseline_volume_cents=6_000_000,
    )
    credit_line = create_credit_line(account["id"], limit_cents=1_000_000, terms_days=30)
    order, _ = create_draft_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 40)],
        payment_method="CREDIT_LINE",
        delivery_mode="WILL_CALL",
        lift_gate_required=False,
        job_lot_required=False,
        resale_purchase=False,
    )
    submit_order(order["id"], account["id"])
    reservations = reserve_order(order["id"])
    allocate_reservations(reservations)
    return store, stock, account, credit_line, order, reservations


# --------------------------------------------------------------------------- #
# The order's two independent state dimensions                                  #
# --------------------------------------------------------------------------- #


class TestProOrderParallelStateDimensions:
    def test_physical_dimension_reaches_fulfilled_without_moving_credit_status(self, api):
        """PRD §2.10: "The two dimensions evolve independently. Reserving, staging and handing over material never move `credit_status`; invoicing and settling never move `fulfillment_status`."
        PRD §2.10: "Only two operations touch both: submission, which moves `fulfillment_status` from `DRAFT` to `SUBMITTED` and `credit_status` from `UNBILLED` to `AUTHORIZED`, and cancellation, which drives `fulfillment_status` to `CANCELLED` and, when the order was authorized, `credit_status` from `AUTHORIZED` to `VOIDED`."
        PRD §3.7: "A `ProDeskAssociate` runs the **reservation step**, which drives `fulfillment_status` from `SUBMITTED` to `RESERVED` and is the only place in this API where inventory is committed."
        PRD §3.8: "Completion moves the appointment from `CONFIRMED` to `DELIVERED`, requires the order still to be in `RESERVED` and all of its reservations still to be in `HELD` or `ALLOCATED`, sets `delivered_at` to the current clock, and fulfils the order by exactly the mechanism will-call pickup uses"

        Design: Difficulty/non_linear_state_machine/pro_order_parallel_dimensions_advance_independently
        """
        store, truck, account, _ = _delivery_world()
        admin_headers = make_contractor_admin_headers(account["id"])
        order, _ = create_draft_order(
            account["id"],
            store["id"],
            [(SKU_SHINGLE_BUNDLE, 40)],
            payment_method="CREDIT_LINE",
            delivery_mode="DELIVERY",
            lift_gate_required=True,
            job_lot_required=False,
            resale_purchase=False,
        )

        submitted = validate_success(api.submit_pro_order(order["id"], admin_headers))
        assert_order_dimensions(
            submitted, fulfillment_status="SUBMITTED", credit_status="AUTHORIZED"
        )

        reservations = validate_success(
            api.reserve_pro_order(order["id"], PRO_DESK_ASSOCIATE), expected_status=201
        )
        after_reserve = validate_success(
            api.get_pro_order(order["id"], PRO_DESK_ASSOCIATE)
        )
        assert_order_dimensions(
            after_reserve, fulfillment_status="RESERVED", credit_status="AUTHORIZED"
        )

        for reservation in reservations:
            validate_success(
                api.allocate_reservation(reservation["id"], STORE_OPERATIONS)
            )

        appointment = validate_success(
            api.create_delivery_appointment(
                create_delivery_appointment_payload(
                    order["id"],
                    truck["id"],
                    window_start="2026-08-05T09:00:00Z",
                    window_end="2026-08-05T11:00:00Z",
                    jobsite_access_type="CURBSIDE",
                ),
                STORE_OPERATIONS,
            ),
            expected_status=201,
        )
        validate_success(
            api.confirm_delivery_appointment(appointment["id"], STORE_OPERATIONS)
        )
        validate_success(
            api.complete_delivery_appointment(appointment["id"], STORE_OPERATIONS)
        )

        after_delivery = validate_success(api.get_pro_order(order["id"], CREDIT_MANAGER))
        assert_order_dimensions(
            after_delivery, fulfillment_status="FULFILLED", credit_status="AUTHORIZED"
        )

    def test_invoice_advances_credit_dimension_without_moving_fulfillment_status(self, api):
        """PRD §2.10: "The two dimensions evolve independently. Reserving, staging and handing over material never move `credit_status`; invoicing and settling never move `fulfillment_status`."
        PRD §2.10: "There is a one-way dependency between them: invoicing requires the physical dimension to have reached `FULFILLED`, but nothing in the physical dimension ever waits on the commercial one."
        PRD §3.9: "A `CreditManager` **invoices** a fulfilled order, moving `credit_status` from `AUTHORIZED` to `INVOICED`."

        Design: Difficulty/non_linear_state_machine/pro_order_parallel_dimensions_advance_independently
        """
        store, truck, account, _ = _delivery_world()
        bundle = setup_fulfilled_delivery_order(
            account["id"],
            store["id"],
            truck["id"],
            [(SKU_SHINGLE_BUNDLE, 40)],
            window_start="2026-08-05T09:00:00Z",
            window_end="2026-08-05T11:00:00Z",
            jobsite_access_type="CURBSIDE",
            payment_method="CREDIT_LINE",
            lift_gate_required=True,
        )
        order = bundle["order"]
        assert_order_dimensions(
            order, fulfillment_status="FULFILLED", credit_status="AUTHORIZED"
        )

        invoiced = validate_success(api.invoice_pro_order(order["id"], CREDIT_MANAGER))
        assert_order_dimensions(
            invoiced, fulfillment_status="FULFILLED", credit_status="INVOICED"
        )

    def test_settlement_pays_credit_dimension_and_returns_full_headroom(self, api):
        """PRD §3.6: "Otherwise the line is `TIER_DISCOUNTED` and `effective_unit_price_cents` is the line's `list_unit_price_cents` reduced by the tier discount and rounded half up to a whole cent."
        PRD §3.6: "A `DELIVERY` order starts from a base freight surcharge of $89.00, and a `WILL_CALL` order starts from zero and stays there"
        PRD §3.6: "`lift_gate_fee_cents` is $45.00 when the order's `delivery_mode` is `DELIVERY` and its `lift_gate_required` is true, and 0 otherwise."
        PRD §3.6: "When `tax_exempt_applied` is true, `tax_cents` is 0; otherwise `tax_cents` is the tax base multiplied by the fulfillment store's `tax_rate_pct`, rounded half up to a whole cent in a single rounding on the summed base, never per line."
        PRD §3.6: "Finally, `total_cents` is the sum of `subtotal_cents`, `freight_surcharge_cents`, `lift_gate_fee_cents` and `tax_cents`."
        PRD §3.9: "A `CreditManager` records payment against an invoiced order, moving `credit_status` from `INVOICED` to `PAID`, and must supply an `amount_cents` that equals the order's `total_cents` less its `credited_refund_cents` — exactly, to the cent — otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`."
        PRD §3.9: "Payment then recomputes the credit line's `exposure_cents` and `available_cents`, because `PAID` orders leave the exposure base."

        Design: Difficulty/non_linear_state_machine/pro_order_parallel_dimensions_advance_independently
        """
        store, truck, account, credit_line = _delivery_world()
        bundle = setup_fulfilled_delivery_order(
            account["id"],
            store["id"],
            truck["id"],
            [(SKU_SHINGLE_BUNDLE, 40)],
            window_start="2026-08-05T09:00:00Z",
            window_end="2026-08-05T11:00:00Z",
            jobsite_access_type="CURBSIDE",
            payment_method="CREDIT_LINE",
            lift_gate_required=True,
        )
        order = bundle["order"]
        assert order["subtotal_cents"] == 75960
        assert order["freight_surcharge_cents"] == 8900
        assert order["lift_gate_fee_cents"] == 4500
        assert order["tax_cents"] == 7372
        assert order["total_cents"] == 96732

        validate_success(api.invoice_pro_order(order["id"], CREDIT_MANAGER))
        paid = validate_success(
            api.pay_pro_order(order["id"], 96732, CREDIT_MANAGER)
        )
        assert_order_dimensions(
            paid, fulfillment_status="FULFILLED", credit_status="PAID"
        )

        line_after = read_credit_line(credit_line["id"])
        assert line_after["exposure_cents"] == 0
        assert line_after["available_cents"] == 100_000_000


# --------------------------------------------------------------------------- #
# Staging waits on every reservation of the order                               #
# --------------------------------------------------------------------------- #


class TestWillCallStagingReservationGate:
    def test_stage_refused_while_one_reservation_is_still_held(self, api):
        """PRD §3.8: "This requires the order to be in `RESERVED`, otherwise `ERR_INVALID_STATE`, and requires **every** reservation of the order to be in `ALLOCATED`, otherwise `ERR_RESERVATIONS_NOT_ALLOCATED` — a partially picked order cannot be staged."
        PRD §2.11: "**Reservations allocated** — every reservation of the order has reached `ALLOCATED`, otherwise `ERR_RESERVATIONS_NOT_ALLOCATED`. Applies to marking a will-call staging physically staged."

        Design: Difficulty/cross_entity_state_dependency/staging_stage_blocked_until_all_reservations_allocated
        """
        store, account, order, reservations = _two_line_will_call_world()
        assert len(reservations) == 2
        staging = validate_success(
            api.create_will_call_staging(
                create_will_call_staging_payload(
                    order["id"],
                    store["id"],
                    stage_start="2026-08-02T08:00:00Z",
                    stage_hours=6,
                ),
                STORE_OPERATIONS,
            ),
            expected_status=201,
        )
        validate_success(
            api.allocate_reservation(reservations[0]["id"], STORE_OPERATIONS)
        )

        validate_error(
            api.stage_will_call_staging(staging["id"], STORE_OPERATIONS),
            ApiErrorId.ERR_RESERVATIONS_NOT_ALLOCATED.value,
            expected_status=409,
        )

    def test_allocating_the_last_reservation_unblocks_the_same_stage_call(self, api):
        """PRD §3.7: "`StoreOperations` moves a reservation from `HELD` to `ALLOCATED` once the units are physically picked, which requires the owning order to be in `RESERVED` and otherwise fails with `ERR_INVALID_STATE`."
        PRD §3.8: "`StoreOperations` moves the staging from `SCHEDULED` to `STAGED` when the material is physically in the bay."
        PRD §3.8: "Staging drives the order's `fulfillment_status` from `RESERVED` to `STAGED` and increments both the staging's and the order's `version`."

        Design: Difficulty/cross_entity_state_dependency/staging_stage_blocked_until_all_reservations_allocated
        """
        store, account, order, reservations = _two_line_will_call_world()
        assert len(reservations) == 2
        staging = validate_success(
            api.create_will_call_staging(
                create_will_call_staging_payload(
                    order["id"],
                    store["id"],
                    stage_start="2026-08-02T08:00:00Z",
                    stage_hours=6,
                ),
                STORE_OPERATIONS,
            ),
            expected_status=201,
        )
        validate_success(
            api.allocate_reservation(reservations[0]["id"], STORE_OPERATIONS)
        )
        validate_error(
            api.stage_will_call_staging(staging["id"], STORE_OPERATIONS),
            ApiErrorId.ERR_RESERVATIONS_NOT_ALLOCATED.value,
            expected_status=409,
        )

        validate_success(
            api.allocate_reservation(reservations[1]["id"], STORE_OPERATIONS)
        )
        staged = validate_success(
            api.stage_will_call_staging(staging["id"], STORE_OPERATIONS)
        )
        assert staged["status"] == "STAGED"

        for reservation in reservations:
            refreshed = validate_success(
                api.get_reservation(reservation["id"], STORE_OPERATIONS)
            )
            assert refreshed["status"] == "ALLOCATED"

        order_after = read_pro_order(order["id"], account["id"])
        assert_order_dimensions(order_after, fulfillment_status="STAGED")


# --------------------------------------------------------------------------- #
# Cancellation conserves the store's unit ledger and the contractor's headroom   #
# --------------------------------------------------------------------------- #


class TestOrderCancellationConservesUnits:
    def test_cancel_returns_reserved_units_to_the_shelf_untouched_on_hand(self, api):
        """PRD §3.6: "Every reservation of the order that is not already terminal is released, with `released_reason_code` set to `ORDER_CANCELLED`, and each release recomputes `reserved_units` and `available_units` at the store that lost it."
        PRD §3.1: "`reserved_units` is always the sum of `qty_units` across the reservations at that store for that SKU whose status is `HELD` or `ALLOCATED`, and `available_units` is `on_hand_units` less `reserved_units`; both are recomputed whenever a reservation is created, released or consumed, and reads of a position always show live figures."
        PRD §3.7: "Consumption is the only operation in this API that reduces a store's `on_hand_units`: it decrements that figure by the reservation's `qty_units` and then recomputes `reserved_units` and `available_units` at that store, so the units leave both the on-hand base and the committed base in the same step."

        Design: Difficulty/compensating_invariant/order_cancel_conserves_store_stock_units
        """
        store, stock, account, _, order, reservations = _allocated_will_call_world()
        admin_headers = make_contractor_admin_headers(account["id"])

        before = read_store_stock(stock["id"])
        assert before["on_hand_units"] == 600
        assert before["reserved_units"] == 40
        assert before["available_units"] == 560

        validate_success(
            api.cancel_pro_order(order["id"], "JOB_POSTPONED", admin_headers)
        )

        released = validate_success(
            api.get_reservation(reservations[0]["id"], STORE_OPERATIONS)
        )
        assert released["status"] == "RELEASED"
        assert released["released_reason_code"] == "ORDER_CANCELLED"

        after = read_store_stock(stock["id"])
        assert after["on_hand_units"] == 600
        assert after["reserved_units"] == 0
        assert after["available_units"] == 600
        assert_store_stock_invariants(after)

        held_rows, held_meta = validate_paginated(
            api.list_reservations(
                STORE_OPERATIONS,
                params={"pro_order_id": order["id"], "status": "HELD"},
            )
        )
        assert held_rows == []
        assert held_meta["total_count"] == 0

    def test_cancel_voids_the_authorization_and_restores_credit_headroom(self, api):
        """PRD §3.6: "An order that had been authorized has its `credit_status` driven from `AUTHORIZED` to `VOIDED`, after which the credit line's `exposure_cents` and `available_cents` are recomputed — this is the compensating leg that returns the authorized amount to the contractor's headroom."
        PRD §3.6: "It carries a `reason_code` recorded as `cancel_reason_code`, drives `fulfillment_status` to `CANCELLED`, and increments the order's `version`."
        PRD §3.3: "Orders in `PAID` or `VOIDED` leave the exposure base entirely, and orders that have never been submitted never enter it."

        Design: Difficulty/compensating_invariant/order_cancel_conserves_store_stock_units
        """
        store, stock, account, credit_line, order, _ = _allocated_will_call_world()
        admin_headers = make_contractor_admin_headers(account["id"])

        priced = read_pro_order(order["id"], account["id"])
        assert priced["total_cents"] == 82227
        before_line = read_credit_line(credit_line["id"])
        assert before_line["exposure_cents"] == 82227

        cancelled = validate_success(
            api.cancel_pro_order(order["id"], "JOB_POSTPONED", admin_headers)
        )
        assert_order_dimensions(
            cancelled, fulfillment_status="CANCELLED", credit_status="VOIDED"
        )

        after_line = read_credit_line(credit_line["id"])
        assert after_line["exposure_cents"] == 0
        assert after_line["available_cents"] == 1_000_000
        assert after_line["status"] == "ACTIVE"
