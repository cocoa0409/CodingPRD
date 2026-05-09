"""Order placement, payment, cancellation, dispense, ship, deliver, and
prescription cross-entity gating (PRD §2.10, §2.12, §3.5, §3.6).
"""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    ApiErrorId,
    setup_otc_purchase_scenario,
    setup_prescription_scenario,
    setup_approved_prescription_with_order,
    setup_otc_order_in_review,
    setup_order_in_review,
    create_platform,
    create_pharmacist,
    create_customer,
    create_two_pharmacists,
    create_otc_drug_on_shelf,
    create_prescription_drug_on_shelf,
    create_vendor,
    create_drug,
    upload_prescription,
    upload_and_approve_prescription,
    place_order,
    pay_order,
    cancel_order,
    open_pharmacist_review,
    approve_review,
    dispense_order,
    ship_order,
    deliver_order,
    setup_basic_platform,
    setup_platform_at_clock,
    get_order,
    get_prescription,
    get_audit_logs,
    get_external_events,
    find_audit_logs,
    find_external_events,
    prescription_item,
    order_item,
    create_order_payload,
    TEST_USERS,
    make_admin_headers,
    make_customer_headers,
    make_pharmacist_re_reviewer_headers,
    make_pharmacist_headers,
)


# ---------------------------------------------------------------------------
# Order placement (PRD §3.5, §2.12)
# ---------------------------------------------------------------------------

class TestOrderPlacement:
    """PRD §3.5: 'New orders begin with dispensing_status equal to
    PENDING_REVIEW and payment_status equal to UNPAID; paid_at,
    pharmacist_review_id, and cold_chain_shipment_id are all unset.'
    """

    def test_otc_order_placed_initial_state(self, api):
        """PRD §3.5: initial state UNPAID + PENDING_REVIEW."""
        s = setup_otc_purchase_scenario(api)
        order = place_order(api, s["platform"]["id"], s["customer"],
                              items=[order_item(s["drug"]["id"], qty=1, unit_price_cents=2500)])
        assert order["payment_status"] == "UNPAID"
        assert order["dispensing_status"] == "PENDING_REVIEW"

    def test_total_amount_cents_is_integer_sum(self, api):
        """PRD §2.12: 'The order total is the simple sum of qty multiplied
        by unit_price_cents across every line in items, accumulated as
        integer cents. No rounding occurs anywhere in this calculation —
        the inputs are integers and the output is an integer.'"""
        s = setup_otc_purchase_scenario(api)
        order = place_order(api, s["platform"]["id"], s["customer"],
                              items=[order_item(s["drug"]["id"], qty=3, unit_price_cents=12_999)])
        # 3 * 12999 = 38997
        assert order["total_amount_cents"] == 38_997

    def test_real_name_required_for_prescription_drug(self, api):
        """PRD §2.10: 'For any order that contains at least one prescription
        drug, the placing customer must have real_name_verified equal to
        true and a non-empty id_document_no; otherwise the order is
        rejected with ERR_REAL_NAME_REQUIRED.'"""
        s = setup_prescription_scenario(
            api,
            customer_overrides={"real_name_verified": False},
        )
        rx = upload_and_approve_prescription(
            api, s["platform"]["id"], s["customer"], s["pr_pharmacist"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=30,
        )
        resp = api.create_order(
            s["platform"]["id"],
            create_order_payload(s["customer"]["id"],
                                   items=[order_item(s["drug"]["id"], qty=1, unit_price_cents=5000)],
                                   prescription_id=rx["id"]),
            make_customer_headers(s["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REAL_NAME_REQUIRED.value)


# ---------------------------------------------------------------------------
# Payment (PRD §3.5)
# ---------------------------------------------------------------------------

class TestOrderPayment:
    """PRD §3.5: 'A Customer may pay an UNPAID order, transitioning
    payment_status to PAID, only when dispensing_status is PENDING_REVIEW,
    PHARMACIST_REVIEWING, or APPROVED — that is, not in REJECTED or
    CANCELLED, and not already PAID or REFUNDED (otherwise
    ERR_ORDER_NOT_PAYABLE). When at least one line is a prescription drug,
    the order's prescription_id must be set and the referenced
    Prescription.status must be APPROVED; otherwise
    ERR_PRESCRIPTION_NOT_APPROVED.'
    """

    def test_pay_unpaid_order_succeeds(self, api):
        """PRD §3.5: 'Successful payment sets paid_at to current_clock_iso
        and emits an ExternalEvent on channel PAYMENT with event_type
        order.paid.'"""
        s = setup_otc_purchase_scenario(api)
        order = place_order(api, s["platform"]["id"], s["customer"],
                              items=[order_item(s["drug"]["id"], qty=1, unit_price_cents=1000)])
        paid = pay_order(api, s["platform"]["id"], order)
        assert paid["payment_status"] == "PAID"
        assert paid.get("paid_at") is not None

    def test_pay_emits_order_paid_event(self, api):
        """PRD §3.5: external event on channel PAYMENT with event_type order.paid."""
        s = setup_otc_purchase_scenario(api)
        order = place_order(api, s["platform"]["id"], s["customer"],
                              items=[order_item(s["drug"]["id"], qty=1, unit_price_cents=1000)])
        pay_order(api, s["platform"]["id"], order)
        events = get_external_events(api, s["platform"]["id"])
        match = find_external_events(events, channel="PAYMENT",
                                         event_type="order.paid",
                                         subject_id=order["id"])
        assert len(match) >= 1, "Expected order.paid ExternalEvent"

    def test_pay_requires_prescription_approved(self, api):
        """PRD §3.5: 'When at least one line is a prescription drug, the
        order's prescription_id must be set and the referenced
        Prescription.status must be APPROVED; otherwise
        ERR_PRESCRIPTION_NOT_APPROVED.'

        # difficulty: cross_entity_state_dependency/order_pay_requires_prescription_approved
        """
        s = setup_prescription_scenario(api)
        # Upload BUT DO NOT APPROVE the prescription (status REVIEW_PENDING).
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=30,
        )
        order = place_order(
            api, s["platform"]["id"], s["customer"],
            items=[order_item(s["drug"]["id"], qty=1, unit_price_cents=5000)],
            prescription_id=rx["id"],
        )
        resp = api.pay_order(s["platform"]["id"], order["id"],
                                make_customer_headers(s["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_NOT_APPROVED.value)

    def test_pay_already_paid_order_rejected(self, api):
        """PRD §3.5: 'not already PAID or REFUNDED (otherwise
        ERR_ORDER_NOT_PAYABLE).'"""
        s = setup_otc_purchase_scenario(api)
        order = place_order(api, s["platform"]["id"], s["customer"],
                              items=[order_item(s["drug"]["id"], qty=1, unit_price_cents=1000)])
        pay_order(api, s["platform"]["id"], order)
        # Second pay attempt.
        resp = api.pay_order(s["platform"]["id"], order["id"],
                                make_customer_headers(s["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PAYABLE.value)

    def test_pay_cancelled_order_rejected(self, api):
        """PRD §3.5: 'not in REJECTED or CANCELLED ... (otherwise
        ERR_ORDER_NOT_PAYABLE).'"""
        s = setup_otc_purchase_scenario(api)
        order = place_order(api, s["platform"]["id"], s["customer"],
                              items=[order_item(s["drug"]["id"], qty=1, unit_price_cents=1000)])
        cancel_order(api, s["platform"]["id"], order)  # CANCELLED
        resp = api.pay_order(s["platform"]["id"], order["id"],
                                make_customer_headers(s["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PAYABLE.value)


# ---------------------------------------------------------------------------
# Cancellation (PRD §3.5)
# ---------------------------------------------------------------------------

class TestOrderCancellation:
    """PRD §3.5: 'A Customer may cancel an order only while dispensing_status
    is PENDING_REVIEW (otherwise ERR_ORDER_NOT_CANCELLABLE).'
    """

    def test_cancel_pending_review_succeeds(self, api):
        """PRD §3.5: cancel drives dispensing_status to CANCELLED."""
        s = setup_otc_purchase_scenario(api)
        order = place_order(api, s["platform"]["id"], s["customer"],
                              items=[order_item(s["drug"]["id"], qty=1, unit_price_cents=1000)])
        cancelled = cancel_order(api, s["platform"]["id"], order)
        assert cancelled["dispensing_status"] == "CANCELLED"

    def test_cancel_paid_order_runs_refund_cascade(self, api):
        """PRD §3.5: 'Cancellation drives dispensing_status to CANCELLED;
        if the order was PAID, the refund cascade described above runs.'

        # difficulty: compensating_invariant/paid_minus_refunded_invariant_on_cancel_cascade
        """
        s = setup_otc_purchase_scenario(api)
        order = place_order(api, s["platform"]["id"], s["customer"],
                              items=[order_item(s["drug"]["id"], qty=2, unit_price_cents=12_999)])
        # 2 * 12999 = 25998 — record total for invariant check.
        assert order["total_amount_cents"] == 25_998
        order = pay_order(api, s["platform"]["id"], order)

        cancelled = cancel_order(api, s["platform"]["id"], order)
        assert cancelled["dispensing_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "REFUNDED"

        # Exactly one ORDER_REFUNDED audit row + exactly one order.refunded event.
        logs = get_audit_logs(api, s["platform"]["id"])
        refund_logs = find_audit_logs(logs, subject_id=order["id"],
                                          subject_type="ORDER",
                                          action="ORDER_REFUNDED")
        assert len(refund_logs) == 1

        events = get_external_events(api, s["platform"]["id"])
        refund_events = find_external_events(events, channel="PAYMENT",
                                                 event_type="order.refunded",
                                                 subject_id=order["id"])
        assert len(refund_events) == 1, \
            "PRD §2.8: idempotency_key prevents duplicate emission"

    def test_cancel_pharmacist_reviewing_rejected(self, api):
        """PRD §3.5: cancel from PHARMACIST_REVIEWING is forbidden."""
        s = setup_otc_order_in_review(api)
        resp = api.cancel_order(s["platform"]["id"], s["order"]["id"],
                                   make_customer_headers(s["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE.value)


# ---------------------------------------------------------------------------
# Dispense / ship / deliver (PRD §3.6, §3.7)
# ---------------------------------------------------------------------------

class TestOrderFulfillment:
    """PRD §3.6: 'After a review is APPROVED, a Pharmacist (or the same
    PharmacistReReviewer operating in pharmacist capacity) dispenses the
    order, transitioning dispensing_status from APPROVED to DISPENSED. The
    dispense action requires dispensing_status equal to APPROVED (otherwise
    ERR_ORDER_NOT_APPROVED) and payment_status equal to PAID (otherwise
    ERR_ORDER_NOT_PAID); successful dispense appends an AuditLog row with
    action ORDER_DISPENSED.'
    """

    def test_dispense_approved_paid_order(self, api):
        """PRD §3.6: dispensing_status APPROVED + payment_status PAID → DISPENSED."""
        s = setup_otc_order_in_review(api, paid=True)
        approve_review(api, s["platform"]["id"], s["order"]["id"],
                          s["review"]["id"], s["rr_pharmacist"])
        dispensed = dispense_order(api, s["platform"]["id"], s["order"]["id"],
                                       s["rr_pharmacist"])
        assert dispensed["dispensing_status"] == "DISPENSED"

    def test_dispense_unpaid_order_rejected(self, api):
        """PRD §3.6: 'payment_status equal to PAID (otherwise ERR_ORDER_NOT_PAID).'"""
        s = setup_otc_order_in_review(api, paid=False)
        approve_review(api, s["platform"]["id"], s["order"]["id"],
                          s["review"]["id"], s["rr_pharmacist"])
        # Order is APPROVED but UNPAID.
        resp = api.dispense_order(
            s["platform"]["id"], s["order"]["id"],
            make_pharmacist_headers(s["rr_pharmacist"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PAID.value)

    def test_dispense_pending_review_rejected(self, api):
        """PRD §3.6: 'requires dispensing_status equal to APPROVED (otherwise
        ERR_ORDER_NOT_APPROVED).'"""
        s = setup_otc_purchase_scenario(api)
        order = place_order(api, s["platform"]["id"], s["customer"],
                              items=[order_item(s["drug"]["id"], qty=1, unit_price_cents=1000)])
        # Make a pharmacist for headers.
        from test_helpers import create_pharmacist
        ph = create_pharmacist(api, s["platform"]["id"])
        resp = api.dispense_order(
            s["platform"]["id"], order["id"],
            make_pharmacist_headers(ph["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_APPROVED.value)

    def test_full_fulfillment_path_otc(self, api):
        """End-to-end: pay → review → approve → dispense → ship → deliver
        for a non-cold-chain OTC order.

        PRD §3.6 for dispense, PRD §3.7 for ship/deliver.
        """
        s = setup_otc_order_in_review(api, paid=True)
        approve_review(api, s["platform"]["id"], s["order"]["id"],
                          s["review"]["id"], s["rr_pharmacist"])
        dispense_order(api, s["platform"]["id"], s["order"]["id"], s["rr_pharmacist"])
        ship_order(api, s["platform"]["id"], s["order"]["id"])
        delivered = deliver_order(api, s["platform"]["id"], s["order"]["id"])
        assert delivered["dispensing_status"] == "DELIVERED"

    def test_ship_from_dispensed_state(self, api):
        """PRD §3.7: 'A PlatformAdmin ships an order, transitioning
        dispensing_status from DISPENSED to SHIPPED, only if the order is
        currently DISPENSED (otherwise ERR_ORDER_NOT_DISPENSED).'"""
        s = setup_otc_order_in_review(api, paid=True)
        approve_review(api, s["platform"]["id"], s["order"]["id"],
                          s["review"]["id"], s["rr_pharmacist"])
        dispense_order(api, s["platform"]["id"], s["order"]["id"], s["rr_pharmacist"])
        shipped = ship_order(api, s["platform"]["id"], s["order"]["id"])
        assert shipped["dispensing_status"] == "SHIPPED"

    def test_ship_pending_review_rejected(self, api):
        """PRD §3.7: 'requires the order ... currently DISPENSED (otherwise
        ERR_ORDER_NOT_DISPENSED).'"""
        s = setup_otc_purchase_scenario(api)
        order = place_order(api, s["platform"]["id"], s["customer"],
                              items=[order_item(s["drug"]["id"], qty=1, unit_price_cents=1000)])
        resp = api.ship_order(s["platform"]["id"], order["id"],
                                 TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DISPENSED.value)

    def test_deliver_from_shipped_state(self, api):
        """PRD §3.7: 'Delivery moves dispensing_status from SHIPPED to
        DELIVERED.'"""
        s = setup_otc_order_in_review(api, paid=True)
        approve_review(api, s["platform"]["id"], s["order"]["id"],
                          s["review"]["id"], s["rr_pharmacist"])
        dispense_order(api, s["platform"]["id"], s["order"]["id"], s["rr_pharmacist"])
        ship_order(api, s["platform"]["id"], s["order"]["id"])
        delivered = deliver_order(api, s["platform"]["id"], s["order"]["id"])
        assert delivered["dispensing_status"] == "DELIVERED"

    def test_deliver_pending_review_rejected(self, api):
        """PRD §3.7: 'The order must be currently SHIPPED (otherwise
        ERR_ORDER_NOT_SHIPPED).'"""
        s = setup_otc_purchase_scenario(api)
        order = place_order(api, s["platform"]["id"], s["customer"],
                              items=[order_item(s["drug"]["id"], qty=1, unit_price_cents=1000)])
        resp = api.deliver_order(s["platform"]["id"], order["id"],
                                    TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SHIPPED.value)


# ---------------------------------------------------------------------------
# Prescription auto-archive (PRD §2.7, §3.4)
# ---------------------------------------------------------------------------

class TestPrescriptionAutoArchive:
    """PRD §2.7: 'The system also auto-archives a referenced approved
    prescription as soon as none of its referencing orders are in a
    non-terminal state. This evaluation runs at every transition that lands
    an order in DELIVERED, CANCELLED, REJECTED, or REFUNDED.'
    PRD §3.4: 'When the condition holds, archived_at is set to the platform
    clock, and an ExternalEvent on channel E_PRESCRIPTION_PLATFORM with
    event_type prescription.archived is emitted.'
    """

    def test_archive_after_delivery(self, api):
        """PRD §3.7: '[deliver] triggers the prescription auto-archive
        evaluation: if every sibling order under the same prescription is
        in a terminal state, the prescription transitions from APPROVED to
        ARCHIVED.'"""
        s = setup_order_in_review(api, paid=True)
        pf = s["platform"]
        approve_review(api, pf["id"], s["order"]["id"],
                          s["review"]["id"], s["rr_pharmacist"])
        dispense_order(api, pf["id"], s["order"]["id"], s["rr_pharmacist"])
        ship_order(api, pf["id"], s["order"]["id"])
        deliver_order(api, pf["id"], s["order"]["id"])

        rx_after = get_prescription(api, pf["id"], s["prescription"]["id"])
        assert rx_after["status"] == "ARCHIVED"
        assert rx_after.get("archived_at") is not None

    def test_archive_emits_prescription_archived_event(self, api):
        """PRD §3.4: 'an ExternalEvent on channel E_PRESCRIPTION_PLATFORM
        with event_type prescription.archived is emitted.'"""
        s = setup_order_in_review(api, paid=True)
        pf = s["platform"]
        approve_review(api, pf["id"], s["order"]["id"],
                          s["review"]["id"], s["rr_pharmacist"])
        dispense_order(api, pf["id"], s["order"]["id"], s["rr_pharmacist"])
        ship_order(api, pf["id"], s["order"]["id"])
        deliver_order(api, pf["id"], s["order"]["id"])

        events = get_external_events(api, pf["id"])
        match = find_external_events(events, channel="E_PRESCRIPTION_PLATFORM",
                                         event_type="prescription.archived",
                                         subject_id=s["prescription"]["id"])
        assert len(match) >= 1
