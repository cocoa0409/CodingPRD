"""Carrier events, the shipment EXCEPTION recovery loop, direction-dependent
LOST_IN_TRANSIT cascades, and the projected-vs-finalized late-fee pair."""

from test_helpers import (
    assert_same_instant,
    list_box_fees,
    list_box_shipments,
    list_ledger,
    make_member_headers,
    read_box,
    read_copy,
    read_member,
    read_subscription,
    record_event,
    set_clock,
    setup_delivered_box,
    setup_planned_box,
    ship_box,
    validate_success,
)


class TestShipmentExceptionRecovery:
    def test_exception_recovery_loop_then_delivery(self, api):
        """PRD §3.5: "The shipment machine runs `LABEL_CREATED` → `IN_TRANSIT`
        → (`DELIVERED` | `EXCEPTION` | `LOST_IN_TRANSIT`), with an `EXCEPTION`
        → `IN_TRANSIT` recovery loop; an event that does not match the
        shipment's current state is rejected with `ERR_INVALID_STATE`."
        PRD §3.5: "An operator records events with an `event_type` and an
        `occurred_at` instant, appended in recorded order to the shipment's
        `events` log."
        PRD §3.5: "a `DELIVERED` event recorded while the shipment is
        `IN_TRANSIT` moves the box `SHIPPED` → `DELIVERED`, stamping
        `delivered_at` with the event's `occurred_at` and computing `due_date`
        as that instant plus the plan's `rental_period_days`."

        Design: Corner/state_machines/shipment_exception_recovery_loop
        """
        ctx = setup_planned_box(member_email="m.exc@x.com", barcode="BC-EXC-1")
        member, box = ctx["member"], ctx["box"]
        # Drive the outbound leg manually so the loop lands mid-flight.
        shipment = ship_box(box["id"], "UPS", "1Z-EXC")
        record_event(shipment["id"], "IN_TRANSIT", "2026-05-02T00:00:00Z")

        record_event(shipment["id"], "EXCEPTION", "2026-05-03T00:00:00Z")
        record_event(shipment["id"], "IN_TRANSIT", "2026-05-04T00:00:00Z")
        final = record_event(shipment["id"], "DELIVERED", "2026-05-05T00:00:00Z")
        assert final["status"] == "DELIVERED"

        shipments = list_box_shipments(box["id"], member)
        assert len(shipments) == 1
        events = shipments[0]["events"]
        assert [e["event_type"] for e in events] == [
            "IN_TRANSIT", "EXCEPTION", "IN_TRANSIT", "DELIVERED"]
        assert [e["occurred_at"][:10] for e in events] == [
            "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05"]

        box_now = read_box(box["id"], member)
        assert box_now["status"] == "DELIVERED"
        assert_same_instant(box_now["delivered_at"], "2026-05-05T00:00:00Z",
                            "delivered_at")
        assert_same_instant(box_now["due_date"], "2026-06-02T00:00:00Z",
                            "due_date (delivered_at + 28 rental days)")


class TestOutboundLostInTransit:
    def test_outbound_loss_cancels_box_without_member_fees(self, api):
        """PRD §3.5: "On the `OUTBOUND` leg, the box — still `SHIPPED` — is
        cancelled outright: every slotted copy becomes `LOST`, no fees are
        charged to the member, and the subscription's `next_cycle_due_at`
        resets to the current clock plus the plan's `rotation_cadence_days` so
        a replacement cycle can begin."

        Design: Corner/state_machines/outbound_lost_in_transit_cancels_box
        """
        ctx = setup_planned_box(member_email="m.lost@x.com", barcode="BC-LOST-1",
                                with_child=True)
        member, box, copy = ctx["member"], ctx["box"], ctx["copy"]
        shipment = ship_box(box["id"], "UPS", "1Z-LOST")
        record_event(shipment["id"], "IN_TRANSIT", "2026-05-02T00:00:00Z")

        record_event(shipment["id"], "LOST_IN_TRANSIT", "2026-05-04T00:00:00Z")

        box_now = read_box(box["id"], member)
        assert box_now["status"] == "CANCELLED"
        assert read_copy(copy["id"])["status"] == "LOST"
        assert list_box_fees(box["id"], member) == []
        # The logical clock never moved from its 2026-05-01 startup default.
        sub_now = read_subscription(ctx["subscription"]["id"], member)
        assert_same_instant(sub_now["next_cycle_due_at"], "2026-05-29T00:00:00Z",
                            "next_cycle_due_at (clock + 28 cadence days)")


class TestReturnLostInTransit:
    def test_return_loss_assesses_loss_fees(self, api):
        """PRD §3.5: "On the `RETURN` leg, the box moves `RETURNING` →
        `INSPECTED` directly: every item still `PENDING_RETURN` becomes
        `LOST_REPORTED` with `resolution_status` `FEE_ASSESSED`, a `LOSS` fee
        at the item's full `replacement_value_cents` is invoiced per item with
        the accompanying `FEE_CHARGE` ledger append, and every slotted copy
        becomes `LOST`."

        Design: Corner/state_machines/return_lost_in_transit_assesses_loss_fees
        """
        ctx = setup_delivered_box(member_email="m.rlost@x.com", barcode="BC-RLOST-1")
        member, box, copy, item = (
            ctx["member"], ctx["box"], ctx["copy"], ctx["item"])
        headers = make_member_headers(member["id"])
        ret = validate_success(api.initiate_return(
            box["id"], {"carrier": "UPS", "tracking_number": "1Z-RLOST-RET"},
            headers), 201)
        record_event(ret["id"], "IN_TRANSIT", "2026-05-05T00:00:00Z")

        record_event(ret["id"], "LOST_IN_TRANSIT", "2026-05-06T00:00:00Z")

        item_now = validate_success(api.get_box_item(item["id"], headers))
        assert item_now["loan_status"] == "LOST_REPORTED"
        assert item_now["resolution_status"] == "FEE_ASSESSED"

        fees = list_box_fees(box["id"], member)
        assert len(fees) == 1
        assert fees[0]["fee_type"] == "LOSS"
        assert fees[0]["amount_cents"] == 1500
        assert fees[0]["status"] == "INVOICED"

        assert read_member(member["id"])["wallet_credit_cents"] == -1500
        assert read_box(box["id"], member)["status"] == "INSPECTED"
        assert read_copy(copy["id"])["status"] == "LOST"
        # The box was never RECEIVED, so no late fee can exist.
        assert all(f["fee_type"] != "LATE_RETURN" for f in fees)


class TestProjectedLateFee:
    def test_projection_is_zero_before_due(self, api):
        """PRD §3.5: "Boxes of a subscription can be listed, and while a box is
        `DELIVERED` its reads expose `projected_late_fee_cents`, a
        forward-looking estimate described below; it reads zero in every other
        state and before the box is late."
        PRD §3.5: "the projected late fee answers "what would the late fee be
        right now": the whole days between `due_date` and the current logical
        clock (never below zero), multiplied by 150 cents per day"

        Design: Corner/calculations/projected_late_fee_zero_before_due
        """
        ctx = setup_delivered_box(member_email="m.plf@x.com", barcode="BC-PLF-1",
                                  delivered_at="2026-05-03T00:00:00Z",
                                  in_transit_at="2026-05-02T00:00:00Z")
        box_now = read_box(ctx["box"]["id"], ctx["member"])
        assert box_now["status"] == "DELIVERED"
        assert_same_instant(box_now["due_date"], "2026-05-31T00:00:00Z", "due_date")
        # Clock 2026-05-01 is earlier than the due date: max(0, ...) floors at 0.
        assert box_now["projected_late_fee_cents"] == 0

    def test_projection_reads_from_moving_clock(self, api):
        """PRD §3.5: "the projected late fee answers "what would the late fee
        be right now": the whole days between `due_date` and the current
        logical clock (never below zero), multiplied by 150 cents per day, then
        capped at the sum of `replacement_value_cents` across the catalog items
        of every box item whose `loan_status` is `PENDING_RETURN` or `RETURNED`
        at evaluation time. Because the projection rides the moving clock, it
        grows daily and typically differs from the fee eventually finalized."

        Delivered 2026-05-03 -> due 2026-05-31; at clock 2026-06-02 the box is
        2 days late, so the projection reads 2 x 150 = 300 cents.

        Design: Difficulty/dual_variant_calc/late_return_fee_projected_vs_finalized
        """
        ctx = setup_delivered_box(member_email="m.late@x.com", barcode="BC-LATE-1",
                                  item_overrides={"title": "Blocks", "piece_count": 10,
                                                  "retail_value_cents": 10000,
                                                  "replacement_value_cents": 8000},
                                  delivered_at="2026-05-03T00:00:00Z",
                                  in_transit_at="2026-05-02T00:00:00Z")
        set_clock("2026-06-02T00:00:00Z")
        box_now = read_box(ctx["box"]["id"], ctx["member"])
        assert_same_instant(box_now["due_date"], "2026-05-31T00:00:00Z", "due_date")
        assert box_now["projected_late_fee_cents"] == 300

    def test_finalized_fee_frozen_at_receipt_differs_from_projection(self, api):
        """PRD §3.5: "When the return shipment's `DELIVERED` event lands, the
        box moves `RETURNING` → `RECEIVED`, `received_at` is stamped with the
        event instant, every slotted copy moves `OUT_ON_LOAN` → `RETURNED`, and
        the late fee finalizes: the whole days between `due_date` and
        `received_at` (never below zero), times 150 cents per day, capped by
        the same replacement-value sum as the projection. When the finalized
        fee is positive, a `LATE_RETURN` fee assessment is created in
        `INVOICED` with a null `box_item_id` — it belongs to the box, not an
        item — a `FEE_CHARGE` ledger entry for the amount is appended to the
        member's wallet, and the wallet recompute may trigger the suspension
        cascade of §2.9."
        PRD §3.5: "Identical inputs up to the receipt instant can therefore
        produce a finalized number different from any earlier projection."

        The projection at clock 2026-06-02 read 300 (2 days); receipt lands at
        2026-06-04, freezing the finalized fee at 4 x 150 = 600 — same formula,
        same due_date, a different evaluation instant, different money.

        Design: Difficulty/dual_variant_calc/late_return_fee_projected_vs_finalized
        """
        ctx = setup_delivered_box(member_email="m.late@x.com", barcode="BC-LATE-1",
                                  item_overrides={"title": "Blocks", "piece_count": 10,
                                                  "retail_value_cents": 10000,
                                                  "replacement_value_cents": 8000},
                                  delivered_at="2026-05-03T00:00:00Z",
                                  in_transit_at="2026-05-02T00:00:00Z")
        member, box = ctx["member"], ctx["box"]
        headers = make_member_headers(member["id"])
        set_clock("2026-06-02T00:00:00Z")
        projected = read_box(box["id"], member)["projected_late_fee_cents"]
        assert projected == 300

        ret = validate_success(api.initiate_return(
            box["id"], {"carrier": "UPS", "tracking_number": "1Z-RET"}, headers), 201)
        record_event(ret["id"], "IN_TRANSIT", "2026-06-03T00:00:00Z")
        record_event(ret["id"], "DELIVERED", "2026-06-04T00:00:00Z")

        box_now = read_box(box["id"], member)
        assert box_now["status"] == "RECEIVED"
        assert_same_instant(box_now["received_at"], "2026-06-04T00:00:00Z",
                            "received_at")

        fees = list_box_fees(box["id"], member)
        late_fees = [f for f in fees if f["fee_type"] == "LATE_RETURN"]
        assert len(late_fees) == 1
        assert late_fees[0]["amount_cents"] == 600  # 4 days late x 150
        assert late_fees[0]["status"] == "INVOICED"
        assert late_fees[0].get("box_item_id") is None
        assert late_fees[0]["rotation_box_id"] == box["id"]

        assert read_member(member["id"])["wallet_credit_cents"] == -600
        reasons = [e["reason"] for e in list_ledger(member["id"])]
        assert reasons == ["FEE_CHARGE"]
