"""Order lifecycle integrity: facility gating, validation priority pairs,
terminal-state lockdown, the facility exposure ledger, stock reservation
conservation, and the credit boundary."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_facility,
    create_order_draft,
    create_product,
    deliver_order,
    invoice_order,
    make_facility_manager_headers,
    order_line,
    place_order,
    setup_facility_with_product,
    setup_placed_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["distributor_admin_headers"]


class TestFacilityGateOnPlacement:
    def test_place_rejected_while_facility_suspended(self, api):
        """PRD: "the order must be `DRAFT` (`ERR_INVALID_STATE` otherwise);
        the facility must be `ACTIVE` (`ERR_FACILITY_INACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/order_place_requires_facility_active
        """
        facility, product = setup_facility_with_product(facility_name="Fac L")
        resp = api.suspend_facility(facility["id"], ADMIN)
        validate_success(resp)
        order = create_order_draft(
            facility, [order_line(product["id"], 1)],
            delivery_date="2026-08-05T00:00:00Z", fuel_index=2.50)
        resp = api.place_order(
            order["id"], make_facility_manager_headers(facility["id"]))
        validate_error(resp, ApiErrorId.ERR_FACILITY_INACTIVE)
        after = validate_success(api.get_order(order["id"], ADMIN))
        assert after["status"] == "DRAFT", (
            "The order stays DRAFT while its facility is SUSPENDED")

    def test_place_succeeds_after_reinstatement(self, api):
        """PRD: "Reinstatement performs the mirror-image conditional cascade:
        a `SUSPENDED` → `ACTIVE` transition flips only the suspension-paused
        standing orders back to `ACTIVE`"
        PRD: "the facility must be `ACTIVE` (`ERR_FACILITY_INACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/order_place_requires_facility_active
        """
        facility, product = setup_facility_with_product(facility_name="Fac L")
        validate_success(api.suspend_facility(facility["id"], ADMIN))
        order = create_order_draft(
            facility, [order_line(product["id"], 1)],
            delivery_date="2026-08-05T00:00:00Z", fuel_index=2.50)
        resp = api.place_order(
            order["id"], make_facility_manager_headers(facility["id"]))
        validate_error(resp, ApiErrorId.ERR_FACILITY_INACTIVE)

        validate_success(api.reinstate_facility(facility["id"], ADMIN))
        placed = place_order(order["id"], facility)
        assert placed["status"] == "PLACED"
        assert placed["total_cents"] == 5200, (
            "subtotal 1000 + fee 4000 + surcharge 200")


class TestFacilityInactiveBeatsCreditExceeded:
    def test_suspended_facility_place_returns_facility_inactive(self, api):
        """PRD: "When several checks could reject the same request, the system
        evaluates them in the following fixed order, and the first failing
        check determines the response:"
        PRD: "8. **Facility gate.** The facility must be `ACTIVE` for order
        placement, order cancellation, standing-order activation,
        standing-order resumption, dispenser completion, trial conversion, and
        usage-record creation; otherwise `ERR_FACILITY_INACTIVE` (409)."
        PRD: "20. **Credit limit.** The facility's `committed_cents` plus the
        order's `total_cents` must not exceed `credit_limit_cents`, with
        equality passing; this check guards order placement and trial
        conversion; otherwise `ERR_CREDIT_LIMIT_EXCEEDED` (409)."

        Design: Difficulty/priority_pair_validation_conflict/facility_inactive_beats_credit_exceeded
        """
        facility, product = setup_facility_with_product(
            facility_name="Fac H", credit_limit_cents=1000)
        order = create_order_draft(
            facility, [order_line(product["id"], 5)], fuel_index=2.50)
        validate_success(api.suspend_facility(facility["id"], ADMIN))
        resp = api.place_order(
            order["id"], make_facility_manager_headers(facility["id"]))
        validate_error(resp, ApiErrorId.ERR_FACILITY_INACTIVE)

    def test_rejected_place_leaves_order_in_draft(self, api):
        """PRD: "8. **Facility gate.** The facility must be `ACTIVE` for order
        placement, order cancellation, standing-order activation,
        standing-order resumption, dispenser completion, trial conversion, and
        usage-record creation; otherwise `ERR_FACILITY_INACTIVE` (409)."
        PRD: "When several checks could reject the same request, the system
        evaluates them in the following fixed order, and the first failing
        check determines the response:"

        Design: Difficulty/priority_pair_validation_conflict/facility_inactive_beats_credit_exceeded
        """
        facility, product = setup_facility_with_product(
            facility_name="Fac H", credit_limit_cents=1000)
        order = create_order_draft(
            facility, [order_line(product["id"], 5)], fuel_index=2.50)
        validate_success(api.suspend_facility(facility["id"], ADMIN))
        resp = api.place_order(
            order["id"], make_facility_manager_headers(facility["id"]))
        validate_error(resp, ApiErrorId.ERR_FACILITY_INACTIVE)
        after = validate_success(api.get_order(order["id"], ADMIN))
        assert after["status"] == "DRAFT"
        refreshed = validate_success(api.get_facility(facility["id"], ADMIN))
        assert refreshed["committed_cents"] == 0, (
            "The rejected place commits no credit")


class TestPlaceIdempotencyAndLockdown:
    def test_place_order_twice_rejected(self, api):
        """PRD: "the order must be `DRAFT` (`ERR_INVALID_STATE` otherwise)"
        PRD: "7. **State-machine legality.** The resource's current state must
        allow the attempted transition, and terminal states accept no further
        transitions; otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/place_order_twice_rejected
        """
        facility, product, order = setup_placed_order(qty=1)
        resp = api.place_order(
            order["id"], make_facility_manager_headers(facility["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_product(product["id"], ADMIN))
        assert after["qty_on_hand"] == 99
        assert after["qty_allocated"] == 1, (
            "No double allocation from the repeated place")

    def test_cancel_invoiced_order_returns_invalid_state(self, api):
        """PRD: "Cancellation is a compensated unwind available to a
        `FacilityManager` or `DistributorAdmin` from `DRAFT`, `PLACED`, or
        `PARTIALLY_BLOCKED`"
        PRD: "Both `INVOICED` and `CANCELLED` are terminal."

        Design: Corner/state_machines/cancel_invoiced_order_returns_invalid_state
        """
        facility, _product, order = setup_placed_order(qty=1)
        deliver_order(order["id"], fuel_index_at_delivery=2.5)
        invoiced = invoice_order(order["id"])
        assert invoiced["status"] == "INVOICED"
        resp = api.cancel_order(
            order["id"], make_facility_manager_headers(facility["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_order(order["id"], ADMIN))
        assert after["status"] == "INVOICED"


class TestInvoiceLedgerMovement:
    def test_invoice_moves_committed_to_outstanding(self, api):
        """PRD: "Invoicing, also by a `DistributorAdmin`, moves `DELIVERED →
        INVOICED` and shifts the money across the ledger: `committed_cents`
        falls by the order's `total_cents` and `outstanding_cents` rises by
        the same amount."

        Design: Corner/state_machines/invoice_moves_committed_to_outstanding
        """
        facility, _product, order = setup_placed_order(
            qty=1, facility_name="Fac X")
        deliver_order(order["id"], fuel_index_at_delivery=2.5)
        invoiced = invoice_order(order["id"])
        assert invoiced["status"] == "INVOICED"
        assert invoiced["total_cents"] == 5200, (
            "1 x 1000 at index 2.50: subtotal 1000 + fee 4000 + surcharge 200")
        refreshed = validate_success(api.get_facility(facility["id"], ADMIN))
        assert refreshed["committed_cents"] == 0
        assert refreshed["outstanding_cents"] == 5200


class TestCreditBoundary:
    def test_credit_boundary_at_limit_passes(self, api):
        """PRD: "At order placement the system requires that the facility's
        current `committed_cents` plus the new order's `total_cents` not
        exceed `credit_limit_cents`; a sum exactly equal to the limit passes,
        and anything above it is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/validations/credit_boundary_at_limit_passes_then_exceeds
        """
        facility, product = setup_facility_with_product(
            facility_name="Fac AH", credit_limit_cents=5200)
        order = create_order_draft(
            facility, [order_line(product["id"], 5)], fuel_index=2.50)
        placed = place_order(order["id"], facility)
        assert placed["status"] == "PLACED"
        assert placed["total_cents"] == 5200
        refreshed = validate_success(api.get_facility(facility["id"], ADMIN))
        assert refreshed["committed_cents"] == 5200, (
            "A sum exactly equal to the limit passes")

    def test_credit_boundary_one_cent_over_rejected(self, api):
        """PRD: "At order placement the system requires that the facility's
        current `committed_cents` plus the new order's `total_cents` not
        exceed `credit_limit_cents`; a sum exactly equal to the limit passes,
        and anything above it is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/validations/credit_boundary_at_limit_passes_then_exceeds
        """
        facility, product = setup_facility_with_product(
            facility_name="Fac AH", credit_limit_cents=5200)
        penny = create_product(sku="SKU-AH2", name="AH2",
                               base_price_cents=1, unit_of_measure="EACH")
        first = create_order_draft(
            facility, [order_line(product["id"], 5)], fuel_index=2.50)
        place_order(first["id"], facility)
        second = create_order_draft(
            facility, [order_line(penny["id"], 1)], fuel_index=2.50)
        resp = api.place_order(
            second["id"], make_facility_manager_headers(facility["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        after = validate_success(api.get_order(second["id"], ADMIN))
        assert after["status"] == "DRAFT", (
            "5200 + 5200 exceeds the 5200 limit; the order stays DRAFT")


class TestStockAllocation:
    def test_allocation_exact_stock_then_insufficient(self, api):
        """PRD: "Allocation is all-or-nothing at placement: every line must be
        satisfiable from `qty_on_hand` before any line allocates, and a line
        whose requested quantity exactly equals the available `qty_on_hand`
        does allocate."
        PRD: "10. **Stock sufficiency.** Allocation requires `qty_on_hand` of
        at least the requested quantity, with equality allocating; this check
        guards order placement and substitution-proposal acceptance; otherwise
        `ERR_INSUFFICIENT_STOCK` (409)."

        Design: Corner/validations/allocation_exact_stock_then_insufficient
        """
        facility, product = setup_facility_with_product(
            facility_name="Fac AI", qty_on_hand=5)
        first = create_order_draft(
            facility, [order_line(product["id"], 5)], fuel_index=2.50)
        place_order(first["id"], facility)
        after_first = validate_success(api.get_product(product["id"], ADMIN))
        assert after_first["qty_on_hand"] == 0
        assert after_first["qty_allocated"] == 5, "Equality allocates"

        second = create_order_draft(
            facility, [order_line(product["id"], 1)], fuel_index=2.50)
        resp = api.place_order(
            second["id"], make_facility_manager_headers(facility["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)
        after_second = validate_success(api.get_order(second["id"], ADMIN))
        assert after_second["status"] == "DRAFT"

    def test_place_shortage_product_returns_product_unavailable(self, api):
        """PRD: "9. **Product availability at placement.** Every line's
        product must be `ACTIVE`; otherwise `ERR_PRODUCT_UNAVAILABLE` (409)."

        Design: Corner/validations/place_shortage_product_returns_product_unavailable
        """
        facility, product = setup_facility_with_product(facility_name="Fac AJ")
        validate_success(api.declare_shortage(product["id"], ADMIN))
        order = create_order_draft(
            facility, [order_line(product["id"], 1)], fuel_index=2.50)
        resp = api.place_order(
            order["id"], make_facility_manager_headers(facility["id"]))
        validate_error(resp, ApiErrorId.ERR_PRODUCT_UNAVAILABLE)
        after = validate_success(api.get_order(order["id"], ADMIN))
        assert after["status"] == "DRAFT"


class TestInventoryConservation:
    def test_allocation_moves_units_on_place(self, api):
        """PRD: "Allocation moves units from `qty_on_hand` into
        `qty_allocated`; cancellation releases the reservation by returning
        units to `qty_on_hand`"

        Design: Difficulty/compensating_invariant/inventory_allocation_conserved_on_cancel
        """
        _facility, product, order = setup_placed_order(
            qty=30, qty_on_hand=100, category="EQUIPMENT",
            unit_of_measure="EACH", facility_name="Fac O")
        assert order["status"] == "PLACED"
        after = validate_success(api.get_product(product["id"], ADMIN))
        assert after["qty_on_hand"] == 70
        assert after["qty_allocated"] == 30
        assert after["qty_on_hand"] + after["qty_allocated"] == 100

    def test_cancel_releases_reservation_without_drift(self, api):
        """PRD: "Allocation moves units from `qty_on_hand` into
        `qty_allocated`; cancellation releases the reservation by returning
        units to `qty_on_hand`"
        PRD: "Every line still `PENDING`, `ALLOCATED`, or
        `SUBSTITUTION_PENDING` moves to `CANCELLED`; allocated reservations
        are released back to `qty_on_hand`"

        Design: Difficulty/compensating_invariant/inventory_allocation_conserved_on_cancel
        """
        facility, product, order = setup_placed_order(
            qty=30, qty_on_hand=100, category="EQUIPMENT",
            unit_of_measure="EACH", facility_name="Fac O")
        cancelled = validate_success(api.cancel_order(
            order["id"], make_facility_manager_headers(facility["id"])))
        assert cancelled["status"] == "CANCELLED"
        after = validate_success(api.get_product(product["id"], ADMIN))
        assert after["qty_on_hand"] == 100
        assert after["qty_allocated"] == 0, (
            "The allocate/cancel pair conserves units with no drift")


class TestCommittedCreditConservation:
    def test_place_commits_order_total(self, api):
        """PRD: "Both counters start at zero and are recomputed — or adjusted
        by the exact delta — on every order event that moves money: placement
        adds the new order's total to `committed_cents`"

        Design: Difficulty/compensating_invariant/committed_credit_conserved_on_place_cancel
        """
        facility, _product, order = setup_placed_order(
            qty=5, base_price_cents=1000, fuel_index=2.50,
            facility_name="Fac P")
        assert order["total_cents"] == 5200
        refreshed = validate_success(api.get_facility(facility["id"], ADMIN))
        assert refreshed["committed_cents"] == 5200

    def test_cancel_restores_committed_exactly(self, api):
        """PRD: "cancellation or a shortage-cascade recompute removes the
        affected total from `committed_cents`"
        PRD: "when the cancelled order was `PLACED` or `PARTIALLY_BLOCKED`,
        the facility's `committed_cents` falls by the order's `total_cents`."

        Design: Difficulty/compensating_invariant/committed_credit_conserved_on_place_cancel
        """
        facility, _product, order = setup_placed_order(
            qty=5, base_price_cents=1000, fuel_index=2.50,
            facility_name="Fac P")
        validate_success(api.cancel_order(
            order["id"], make_facility_manager_headers(facility["id"])))
        refreshed = validate_success(api.get_facility(facility["id"], ADMIN))
        assert refreshed["committed_cents"] == 0, (
            "Committed credit is restored exactly")
        assert refreshed["outstanding_cents"] == 0, "No ledger drift"
