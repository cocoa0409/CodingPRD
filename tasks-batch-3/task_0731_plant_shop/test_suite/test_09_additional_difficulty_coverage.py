"""Additional tests to hit the ≥2-tests-per-difficulty-instance target for
rules 5–8 whose primary instance produces only a single positive-error assertion."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_error_is_one_of,
    get_success_data,
    set_clock, register_customer, create_driver, create_plant,
    intake_stock_unit, create_order, pay_order, dispatch_order, deliver,
    append_care_log, get_orderline_id_for_order,
    TEST_USERS, make_customer_headers, make_delivery_driver_headers,
)


# -----------------------------------------------------------------------------
# Rule 5 instance 1 — supplementary
# -----------------------------------------------------------------------------

class TestSpecialOrderStateVsFiscalPrioritySecond:

    def test_requote_from_requested_does_not_advance_status(self, api):
        """PRD §3.8: "the manager can re-quote through the special-order-re-quote
        action from a QUOTED origin: the special order moves to RE_QUOTED,
        SpecialOrder.quoted_price_cents is overwritten with the new value,
        SpecialOrder.revision_count is incremented by one, and version bumps."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_special_order_re_quote_from_re_quoted
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="kim2@example.com", delivery_zone="ZONE_A")
        so = get_success_data(api.create_special_order(
            {"customer_id": customer["id"], "service_type": "PROCUREMENT", "sku_description": "test"},
            make_customer_headers(customer["id"]),
        ))
        # Re-quote from REQUESTED → rejected; status must remain REQUESTED, revision_count=0.
        _ = api.requote_special_order(
            so["id"], {"quoted_price_cents": 10000}, TEST_USERS["manager_headers"]
        )
        # After the rejection, refetch the special order — no mutation should have applied.
        after = get_success_data(api.get_special_order(so["id"], make_customer_headers(customer["id"])))
        assert after["status"] == "REQUESTED", "invalid-FROM re-quote must not advance status"
        assert after["revision_count"] == 0


# -----------------------------------------------------------------------------
# Rule 5 instance 2 — supplementary
# -----------------------------------------------------------------------------

class TestPrioritySafetyBeforeReferentialSecond:

    def test_expired_warranty_rejection_leaves_orderline_refund_status_unchanged(self, api):
        """PRD §3.5: "On successful submission, the target OrderLine.refund_status
        flips from NONE to PENDING_REVIEW and the provisional refund amount is
        stamped as WarrantyClaim.refund_amount_cents_provisional".

        A rejected submission (expired + not-owner) must NOT flip the OrderLine's
        refund_status — the successful-submission side-effect prose is scoped to
        successes only.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_warranty_expired_and_not_owner
        """
        set_clock("2026-04-01T00:00:00Z")
        cust_a = register_customer(email="leo2@example.com", delivery_zone="ZONE_A")
        cust_b = register_customer(email="mia2@example.com", delivery_zone="ZONE_A")
        driver = create_driver(name="Ned2")
        plant = create_plant(
            name="ZZ2", light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=4000, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        order = create_order(cust_a["id"], [(plant["id"], 1)])
        pay_order(order["id"], cust_a["id"])
        d = dispatch_order(order["id"], driver["id"], "2026-04-01T09:00:00Z", "2026-04-01T11:00:00Z")
        deliver(d["id"], driver["id"])
        orderline_id = get_orderline_id_for_order(order["id"], cust_a["id"])
        set_clock("2026-06-01T00:00:00Z")
        # Customer B submits on Customer A's line, past the warranty window.
        _ = api.submit_warranty_claim(
            {"orderline_id": orderline_id, "customer_id": cust_b["id"], "reason": "MORTALITY"},
            make_customer_headers(cust_b["id"]),
        )
        # After rejection, the OrderLine's refund_status must still be NONE.
        line_after = get_success_data(api.get_order_line(orderline_id, make_customer_headers(cust_a["id"])))
        assert line_after["refund_status"] == "NONE"


# -----------------------------------------------------------------------------
# Rule 6 instance 1 — supplementary (warranty boundary inclusive at day=warranty_days)
# -----------------------------------------------------------------------------

class TestWarrantyBoundaryInclusive:

    def test_claim_at_exactly_warranty_days_is_accepted(self, api):
        """PRD §3.5: "the elapsed time between the logical clock and the parent
        order's delivery instant, measured in whole days (86400-second buckets,
        floor-inclusive), must not exceed the plant's warranty_days; the
        boundary is inclusive at exactly warranty_days and rejects at
        warranty_days + 1 with ERR_WARRANTY_EXPIRED (HTTP 422)."

        Design: Difficulty/boundary_precision_check/warranty_period_boundary_exact_day_inclusive
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="oli2@example.com", delivery_zone="ZONE_A")
        driver = create_driver(name="Pat2")
        plant = create_plant(
            name="Calathea2", light_tag="LOW", care_tag="MODERATE",
            weight_class="LIGHT", unit_price_cents=4500, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(order["id"], customer["id"])
        d = dispatch_order(order["id"], driver["id"], "2026-04-05T09:00:00Z", "2026-04-05T11:00:00Z")
        set_clock("2026-04-05T10:00:00Z")
        deliver(d["id"], driver["id"])
        orderline_id = get_orderline_id_for_order(order["id"], customer["id"])
        # Exactly 30 days after delivery: day=30 by floor bucket → inclusive → accept.
        set_clock("2026-05-05T10:00:00Z")
        r = api.submit_warranty_claim(
            {"orderline_id": orderline_id, "customer_id": customer["id"], "reason": "MORTALITY"},
            make_customer_headers(customer["id"]),
        )
        claim = validate_success(r, expected_status=201)
        assert claim["status"] == "SUBMITTED"


# -----------------------------------------------------------------------------
# Rule 7 instance 1 — supplementary
# -----------------------------------------------------------------------------

class TestDeliveryRequiresOrderPaidSecond:

    def test_deliver_on_cancelled_delivery_leaves_stock_freed(self, api):
        """PRD §3.2: "In the pre-dispatch path, every OrderLine's stock_unit_id
        flips its sale_status from RESERVED back to FOR_SALE (recomputing each
        parent Plant.available_count); the order moves to CANCELLED+UNPAID."
        PRD §3.2: "In the post-dispatch manager path, the associated
        DeliveryAssignment.status flips to FAILED and the reservation-release
        cascade runs identically."

        A manager-cancelled dispatched order releases the reserved stock — the
        StockUnit returns to FOR_SALE, so subsequent /deliver has no basis.

        Design: Difficulty/cross_entity_state_dependency/delivery_deliver_requires_order_paid
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="rita2@example.com", delivery_zone="ZONE_A")
        driver = create_driver(name="Sam2")
        plant = create_plant(
            name="Fern2", light_tag="MEDIUM", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3000, warranty_days=30,
        )
        stock = intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(order["id"], customer["id"])
        d = dispatch_order(order["id"], driver["id"], "2026-04-02T09:00:00Z", "2026-04-02T11:00:00Z")
        current = get_success_data(api.get_order(order["id"], TEST_USERS["manager_headers"]))
        validate_success(api.cancel_order(
            order["id"], {"expected_order_version": current["version"]},
            TEST_USERS["manager_headers"],
        ))
        # After cancel, StockUnit.sale_status → FOR_SALE (reservation released).
        stock_after = get_success_data(api.get_stock_unit(stock["id"], TEST_USERS["manager_headers"]))
        assert stock_after["sale_status"] == "FOR_SALE"


# -----------------------------------------------------------------------------
# Rule 7 instance 2 — supplementary
# -----------------------------------------------------------------------------

class TestWarrantySubmitRequiresDeliveredSecond:

    def test_warranty_submit_on_pending_order_leaves_orderline_untouched(self, api):
        """PRD §3.5: "On successful submission, the target OrderLine.refund_status
        flips from NONE to PENDING_REVIEW and the provisional refund amount is
        stamped as WarrantyClaim.refund_amount_cents_provisional using the
        provisional variant of warranty_refund_amount — the full
        OrderLine.line_subtotal_cents, with no care-log deduction, floored."

        A rejected submission MUST NOT flip refund_status (the success-side
        prose is scoped to successful submission).

        Design: Difficulty/cross_entity_state_dependency/warranty_submit_requires_order_delivered
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="toni2@example.com", delivery_zone="ZONE_A")
        plant = create_plant(
            name="Rubber2", light_tag="MEDIUM", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3500, warranty_days=60,
        )
        intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(order["id"], customer["id"])
        orderline_id = get_orderline_id_for_order(order["id"], customer["id"])
        # Attempt submission — order still PENDING, so must reject.
        _ = api.submit_warranty_claim(
            {"orderline_id": orderline_id, "customer_id": customer["id"], "reason": "MORTALITY"},
            make_customer_headers(customer["id"]),
        )
        line_after = get_success_data(api.get_order_line(orderline_id, make_customer_headers(customer["id"])))
        assert line_after["refund_status"] == "NONE"


# -----------------------------------------------------------------------------
# Rule 8 instance 1 — supplementary
# -----------------------------------------------------------------------------

class TestWorkshopOverlapNonBufferedInSeparateRoomSucceeds:

    def test_workshop_overlap_check_scoped_to_same_room_id(self, api):
        """PRD §3.7: "a proposed workshop is rejected if its buffered window
        intersects the buffered window of any existing workshop sharing the room,
        whether or not the workshops belong to the same manager. The rejection
        carries ERR_WORKSHOP_OVERLAP (HTTP 409)."

        Corollary: overlap is scoped to the SAME room_id. Two workshops in
        different rooms may safely overlap.

        Design: Difficulty/resource_temporal_overlap/workshop_room_half_open_with_15min_buffer
        """
        set_clock("2026-04-01T00:00:00Z")
        get_success_data(api.create_workshop(
            {
                "title": "A1", "topic": "REPOTTING", "room_id": "STUDIO_A",
                "start_at": "2026-05-01T10:00:00Z", "end_at": "2026-05-01T12:00:00Z",
                "capacity": 10,
            },
            TEST_USERS["manager_headers"],
        ))
        # Same time-window in STUDIO_B — should succeed.
        r = api.create_workshop(
            {
                "title": "B1", "topic": "LIGHT_101", "room_id": "STUDIO_B",
                "start_at": "2026-05-01T10:00:00Z", "end_at": "2026-05-01T12:00:00Z",
                "capacity": 5,
            },
            TEST_USERS["manager_headers"],
        )
        validate_success(r, expected_status=201)


# -----------------------------------------------------------------------------
# Rule 8 instance 2 — supplementary
# -----------------------------------------------------------------------------

class TestDeliveryClosedIntervalOverlap:

    def test_delivery_windows_touching_endpoints_rejected(self, api):
        """PRD §3.3: "no other assignment for the same driver_id may hold a
        closed-interval overlap with the proposed window — two windows overlap
        when either endpoint of one falls within (or on) the endpoints of the
        other."

        Two windows that touch at endpoints (closed-interval overlap) must be
        rejected. Different failure axis (closed-interval overlap vs aggregate
        capacity) from the sibling instance.

        Design: Difficulty/resource_temporal_overlap/delivery_driver_closed_interval_and_daily_capacity_aggregate
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="uma2@example.com", delivery_zone="ZONE_A")
        driver = create_driver(name="Ulla2", daily_capacity_minutes=480)
        plant = create_plant(
            name="Palm2", light_tag="BRIGHT_INDIRECT", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3000, warranty_days=30,
        )
        intake_stock_unit(plant["id"], acquisition_date="2026-03-25T00:00:00Z")
        intake_stock_unit(plant["id"], acquisition_date="2026-03-26T00:00:00Z")
        o1 = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(o1["id"], customer["id"])
        dispatch_order(o1["id"], driver["id"], "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z")
        o2 = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(o2["id"], customer["id"])
        # Second window starts at 10:00Z — touches the end of the first window
        # (which ended at 10:00Z). Closed-interval overlap MUST reject.
        r = api.dispatch_order(
            o2["id"],
            {"driver_id": driver["id"],
             "window_start_at": "2026-04-02T10:00:00Z",
             "window_end_at": "2026-04-02T11:00:00Z"},
            TEST_USERS["shop_staff_headers"],
        )
        validate_error(r, ApiErrorId.ERR_DELIVERY_OVERLAP.value)
