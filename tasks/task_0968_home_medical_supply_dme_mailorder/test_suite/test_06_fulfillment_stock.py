"""Fulfillment: submit-time prescription dependency, release gates (backorder,
prior-auth), FIFO backorder allocation, and stock reserve/release conservation."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_stock_conservation,
    create_manual_order,
    add_order_line,
    submit_order,
    cancel_order,
    get_order,
    create_shipment_for_order,
    get_shipment,
    get_stock_level,
    restock,
    set_logical_clock,
    setup_active_patient_with_item,
    INTAKE,
    FULFIL,
    ADMIN,
    make_patient_headers,
)


class TestSubmitRequiresValidPrescription:
    def _setup_order_with_expiring_rx(self, api):
        ctx = setup_active_patient_with_item(
            rx_effective_date="2026-05-01", rx_expiration_date="2026-06-01",
        )
        set_logical_clock("2026-05-15T00:00:00Z")
        patient_id = ctx["patient"]["id"]
        order = create_manual_order(patient_id)
        add_order_line(order["id"], order["version"], ctx["item"]["id"],
                       size_code="45MM", quantity=5, patient_id=patient_id)
        # The covering prescription's half-open window ends 2026-06-01.
        set_logical_clock("2026-06-15T00:00:00Z")
        return ctx, order

    def test_submit_after_rx_expiry_rejected(self, api):
        """PRD §3.5: "requires every line's `hcpcs_code` to be covered by an
        `ACTIVE` prescription whose half-open window contains the current
        logical date — the effective date on or before today and the expiration
        date strictly after today — otherwise `ERR_NO_VALID_PRESCRIPTION`
        (HTTP 422)." PRD §2.7: "A `Prescription` in `ACTIVE` status flips to
        `EXPIRED` whenever it is read directly, or referenced by a validation,
        at a moment when the current logical date is on or after its
        `expiration_date`".

        Design: Difficulty/cross_entity_state_dependency/order_submit_requires_current_valid_prescription
        """
        ctx, order = self._setup_order_with_expiring_rx(api)
        resp = api.submit_order(order["id"], make_patient_headers(ctx["patient"]["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_VALID_PRESCRIPTION)

    def test_submit_rejection_leaves_order_draft(self, api):
        """PRD §3.5: "A successful submission moves fulfillment from `DRAFT` to
        `SUBMITTED`" — a rejected submission performs no such move; the order
        stays `DRAFT`.

        Design: Difficulty/cross_entity_state_dependency/order_submit_requires_current_valid_prescription
        """
        ctx, order = self._setup_order_with_expiring_rx(api)
        api.submit_order(order["id"], make_patient_headers(ctx["patient"]["id"]))
        after = get_order(order["id"])
        assert after["fulfillment_status"] == "DRAFT"


class TestShipmentReleaseGates:
    def test_release_backordered_shipment_rejected(self, api):
        """PRD §3.6: "Attempting to release a `BACKORDERED` shipment is rejected
        with `ERR_SHIPMENT_BACKORDERED` (HTTP 409)." PRD §3.6: "When every line
        is fully reserved the shipment is born `CREATED`; otherwise it is born
        `BACKORDERED`."

        Design: Corner/state_machines/release_backordered_shipment_rejected
        """
        ctx = setup_active_patient_with_item(on_hand_qty=2)
        patient_id = ctx["patient"]["id"]
        order = create_manual_order(patient_id)
        add_order_line(order["id"], order["version"], ctx["item"]["id"],
                       size_code="45MM", quantity=5, patient_id=patient_id)
        submit_order(order["id"], patient_id)
        shipment = create_shipment_for_order(order["id"])
        assert shipment["status"] == "BACKORDERED", (
            f"stock 2 < qty 5 must birth BACKORDERED, got {shipment['status']}"
        )

        resp = api.release_shipment(shipment["id"], FULFIL)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_BACKORDERED)
        assert get_shipment(shipment["id"])["status"] == "BACKORDERED"

    def _setup_pa_gated_shipment(self, api, pa_decision, pa_valid_to="2026-08-31"):
        ctx = setup_active_patient_with_item(
            hcpcs_code="A6250", category="WOUND", size_code="4X4", size_codes=("4X4",),
            pack_fee_cents=999, pack_size=8, retail_price_cents=650,
            max_units_per_cycle=30, requires_pa=True, diagnosis_codes=("L89.1",),
            on_hand_qty=100,
            with_pa=True, pa_approved_units=45,
            pa_valid_from="2026-05-01", pa_valid_to=pa_valid_to,
            pa_decision=pa_decision,
        )
        patient_id = ctx["patient"]["id"]
        order = create_manual_order(patient_id)
        add_order_line(order["id"], order["version"], ctx["item"]["id"],
                       size_code="4X4", quantity=5, patient_id=patient_id)
        submit_order(order["id"], patient_id)
        shipment = create_shipment_for_order(order["id"])
        assert shipment["status"] == "CREATED"
        return ctx, shipment

    def test_release_with_denied_pa_rejected(self, api):
        """PRD §3.6: "no `APPROVED` authorization at all rejects the release
        with `ERR_PRIOR_AUTH_REQUIRED` (HTTP 422)" — a DENIED authorization is
        not an APPROVED one.

        Design: Difficulty/cross_entity_state_dependency/shipment_release_requires_approved_prior_auth
        """
        ctx, shipment = self._setup_pa_gated_shipment(api, pa_decision="DENIED")
        resp = api.release_shipment(shipment["id"], FULFIL)
        validate_error(resp, ApiErrorId.ERR_PRIOR_AUTH_REQUIRED)

    def test_release_rejection_leaves_shipment_created(self, api):
        """PRD §3.6: "A `FulfillmentAgent` releases a shipment that is in
        `CREATED` status, moving it to `READY`" — a rejected release performs no
        such move; the shipment stays `CREATED`.

        Design: Difficulty/cross_entity_state_dependency/shipment_release_requires_approved_prior_auth
        """
        ctx, shipment = self._setup_pa_gated_shipment(api, pa_decision="DENIED")
        api.release_shipment(shipment["id"], FULFIL)
        assert get_shipment(shipment["id"])["status"] == "CREATED"

    def test_release_with_expired_approved_pa_rejected(self, api):
        """PRD §3.6: "an `APPROVED` authorization exists but the current date is
        strictly after its `valid_to` rejects the release with
        `ERR_PRIOR_AUTH_EXPIRED` (HTTP 422)". PRD §3.6: "release evaluates the
        stored authorization rows for the patient and the line's code — without
        applying the lazy expiry flip of §2.7".

        Design: Corner/validations/release_with_expired_approved_pa_rejected
        """
        ctx, shipment = self._setup_pa_gated_shipment(
            api, pa_decision="APPROVED", pa_valid_to="2026-05-31"
        )
        set_logical_clock("2026-06-15T00:00:00Z")
        resp = api.release_shipment(shipment["id"], FULFIL)
        validate_error(resp, ApiErrorId.ERR_PRIOR_AUTH_EXPIRED)
        assert get_shipment(shipment["id"])["status"] == "CREATED"


class TestBackorderFifoAllocation:
    def test_backorder_fifo_partial_allocation(self, api):
        """PRD §3.6: "Reservations are processed oldest first by reservation
        `created_at`, ties broken by the parent order's `created_at`." PRD §3.6:
        "A reservation whose pending count reaches zero moves to `ALLOCATED`;
        one that received some but not enough units moves to
        `PARTIALLY_ALLOCATED`. When every reservation of a `BACKORDERED`
        shipment has been fully allocated, the shipment flips back to
        `CREATED`".

        Design: Corner/calculations/backorder_fifo_partial_allocation
        """
        ctx = setup_active_patient_with_item(on_hand_qty=10)
        patient_id = ctx["patient"]["id"]
        item_id = ctx["item"]["id"]
        stock_id = ctx["stock"]["id"]

        def order_with_line(qty):
            o = create_manual_order(patient_id)
            line = add_order_line(o["id"], o["version"], item_id,
                                  size_code="45MM", quantity=qty, patient_id=patient_id)
            submit_order(o["id"], patient_id)
            return o, line

        # A takes 8 of 10 (fully reserved); B takes the last 2 + 3 backordered;
        # C finds 0 available and backorders all 4.
        oa, _la = order_with_line(8)
        create_shipment_for_order(oa["id"])
        ob, lb = order_with_line(5)
        sb = create_shipment_for_order(ob["id"])
        oc, lc = order_with_line(4)
        sc = create_shipment_for_order(oc["id"])
        assert sb["status"] == "BACKORDERED"
        assert sc["status"] == "BACKORDERED"

        restock(stock_id, 5)

        res_b = validate_success(
            api.list_line_backorder_reservations(lb["id"], FULFIL), expected_status=200
        )[0]
        assert res_b["status"] == "ALLOCATED"
        assert res_b["quantity_pending"] == 0
        assert res_b["quantity_allocated"] == 3

        res_c = validate_success(
            api.list_line_backorder_reservations(lc["id"], FULFIL), expected_status=200
        )[0]
        assert res_c["status"] == "PARTIALLY_ALLOCATED"
        assert res_c["quantity_pending"] == 2
        assert res_c["quantity_allocated"] == 2

        stock = get_stock_level(stock_id)
        assert stock["on_hand_qty"] == 15
        assert stock["reserved_qty"] == 15
        assert stock["available_qty"] == 0
        assert_stock_conservation(stock)

        assert get_shipment(sb["id"])["status"] == "CREATED"
        assert get_shipment(sc["id"])["status"] == "BACKORDERED"


class TestStockReserveReleaseConservation:
    def _setup_reserved_order(self, api):
        ctx = setup_active_patient_with_item(on_hand_qty=100)
        patient_id = ctx["patient"]["id"]
        order = create_manual_order(patient_id)
        add_order_line(order["id"], order["version"], ctx["item"]["id"],
                       size_code="45MM", quantity=30, patient_id=patient_id)
        submit_order(order["id"], patient_id)
        shipment = create_shipment_for_order(order["id"])
        return ctx, order, shipment

    def test_shipment_reservation_reduces_available(self, api):
        """PRD §3.6: "for each line, the stock row's `reserved_qty` increases by
        the smaller of the line quantity and the units currently available."
        PRD §3.1: "`available_qty`, which is always the on-hand quantity minus
        the reserved quantity." — reserving 30 of 100 leaves 70.

        Design: Difficulty/compensating_invariant/stock_reserve_release_conservation
        """
        ctx, order, shipment = self._setup_reserved_order(api)
        stock = get_stock_level(ctx["stock"]["id"])
        assert stock["reserved_qty"] == 30
        assert stock["available_qty"] == 70
        assert_stock_conservation(stock)

    def test_order_cancel_releases_reservation_exactly(self, api):
        """PRD §3.5: "That cancellation cascades: each such shipment moves to
        `CANCELLED`, each cancelled shipment releases its reservations (the
        stock row's `reserved_qty` is decremented by the units reserved plus the
        units already allocated for that line, and any `PENDING` or
        `PARTIALLY_ALLOCATED` backorder reservations move to `CANCELLED`)" —
        available returns exactly to 100 with reserved 0.

        Design: Difficulty/compensating_invariant/stock_reserve_release_conservation
        """
        ctx, order, shipment = self._setup_reserved_order(api)
        cancel_order(order["id"], ctx["patient"]["id"])

        stock = get_stock_level(ctx["stock"]["id"])
        assert stock["reserved_qty"] == 0
        assert stock["available_qty"] == 100
        assert_stock_conservation(stock)
        assert get_shipment(shipment["id"])["status"] == "CANCELLED"
