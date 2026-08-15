"""Order allocation selector, inventory locks, and optimistic concurrency."""
from test_helpers import (
    FLEET,
    PLANT,
    SALES,
    ApiErrorId,
    add_route_stop,
    api_client,
    confirm_order,
    create_allocated_order,
    create_confirmed_order,
    create_order,
    create_route,
    get_lot,
    get_order,
    get_route,
    list_order_lines,
    setup_sellable_world,
    validate_error,
    validate_success,
)


class TestHeatTreatmentAllocationGate:

    def _setup_ht_required_order(self):
        """NON-certified lot of 100 + CONFIRMED order needing HT stock."""
        spec, lot, customer = setup_sellable_world(
            "ExporterIntl", lot_quantity=100)
        # The spec does not require HT by default; the lot is NOT_REQUIRED.
        assert lot["heat_treat_status"] == "NOT_REQUIRED"
        order = create_order(customer["id"], spec["id"], 50, "NEW",
                             heat_treatment_required=True)
        confirmed = confirm_order(order["id"], order["version"])
        return spec, lot, confirmed

    def test_allocate_ht_required_line_against_non_certified_stock_rejected(self):
        """PRD §3.6: "When the candidate set is empty the allocation fails with
        `ERR_INSUFFICIENT_STOCK`; when candidates exist but every one fails the
        heat-treatment filter, the failure surfaces as `ERR_HT_REQUIRED`
        instead."
        PRD §3.6: "a line with `heat_treatment_required` true further demands
        `HT_CERTIFIED` lots, while a line without it accepts `NOT_REQUIRED`,
        `HT_CERTIFIED`, or `PENDING_HT` stock."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_allocate
        """
        _spec, lot, order = self._setup_ht_required_order()
        resp = api_client.allocate_order(
            order["id"], {"expected_order_version": order["version"]}, SALES)
        validate_error(resp, ApiErrorId.ERR_HT_REQUIRED)
        assert resp.status_code == 422

    def test_failed_ht_allocation_commits_no_reservation(self):
        """PRD §3.6: "when candidates exist but every one fails the
        heat-treatment filter, the failure surfaces as `ERR_HT_REQUIRED`
        instead."
        PRD §3.5: "Lots are born `AVAILABLE`, with `quantity_available` — a
        read-only figure equal to `quantity_total` minus the sum of active
        reservations against the lot — starting equal to `quantity_total`."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_allocate
        """
        _spec, lot, order = self._setup_ht_required_order()
        resp = api_client.allocate_order(
            order["id"], {"expected_order_version": order["version"]}, SALES)
        validate_error(resp, ApiErrorId.ERR_HT_REQUIRED)
        lot_after = get_lot(lot["id"])
        assert lot_after["quantity_available"] == 100, (
            f"a rejected allocation must commit no reservation, "
            f"got quantity_available {lot_after['quantity_available']}"
        )
        order_after = get_order(order["id"])
        assert order_after["fulfillment_status"] == "CONFIRMED"


class TestLotQuantityConservation:

    def _setup_two_unit_lot_world(self):
        spec, lot, customer = setup_sellable_world(
            "StockWatch", lot_quantity=2)
        return spec, lot, customer

    def test_quantity_available_decrements_with_each_allocation(self):
        """PRD §3.5: "Lots are born `AVAILABLE`, with `quantity_available` — a
        read-only figure equal to `quantity_total` minus the sum of active
        reservations against the lot — starting equal to `quantity_total`."
        PRD §3.6: "the winner's identity lands in the line's `allocated_lot_id`
        as the line moves to `ALLOCATED` and the lot's `quantity_available` is
        debited by the reservation."

        Design: Difficulty/compensating_invariant/lot_quantity_conservation_through_allocation_depletion
        """
        spec, lot, customer = self._setup_two_unit_lot_world()
        assert lot["quantity_available"] == 2
        o1 = create_allocated_order(customer["id"], spec["id"], 1)
        mid = get_lot(lot["id"])
        assert mid["quantity_available"] == 1, (
            f"2 total - 1 allocated = 1 available, "
            f"got {mid['quantity_available']}"
        )
        assert mid["status"] == "AVAILABLE"
        lines = list_order_lines(o1["id"])
        assert lines[0]["allocated_lot_id"] == lot["id"]
        assert lines[0]["status"] == "ALLOCATED"

    def test_lot_depletes_exactly_at_zero_available(self):
        """PRD §3.5: "When an allocation drains `quantity_available` to zero,
        the lot automatically transitions to `DEPLETED` and drops out of the
        allocation selector."
        PRD §3.6: "Lots drained to zero auto-transition to `DEPLETED`."

        Design: Difficulty/compensating_invariant/lot_quantity_conservation_through_allocation_depletion
        """
        spec, lot, customer = self._setup_two_unit_lot_world()
        o1 = create_allocated_order(customer["id"], spec["id"], 1)
        o2 = create_allocated_order(customer["id"], spec["id"], 1)
        end = get_lot(lot["id"])
        assert end["quantity_available"] == 0
        assert end["status"] == "DEPLETED", (
            f"DEPLETED fires exactly when availability reaches 0, "
            f"got {end['status']}"
        )
        # conservation: quantity_total(2) == allocated(2) + available(0)
        assert end["quantity_total"] == 2


class TestQuarantineGate:

    def test_quarantine_allocated_lot_rejected(self):
        """PRD §3.5: "A `PlantManager` may also quarantine a lot, moving it to
        `QUARANTINED`, but only while it is `AVAILABLE` (else
        `ERR_LOT_NOT_AVAILABLE`) and no order line currently holds an
        `ALLOCATED` reservation against it (else `ERR_LOT_HAS_ALLOCATIONS`); a
        quarantined lot is likewise excluded from the selector."

        Design: Corner/errors/error_lot_has_allocations_on_quarantine
        """
        spec, lot, customer = setup_sellable_world(
            "QuarCust", lot_quantity=100)
        create_allocated_order(customer["id"], spec["id"], 1)
        resp = api_client.quarantine_lot(lot["id"], PLANT)
        validate_error(resp, ApiErrorId.ERR_LOT_HAS_ALLOCATIONS)
        assert resp.status_code == 409
        after = get_lot(lot["id"])
        assert after["status"] == "AVAILABLE", (
            f"rejected quarantine must leave the lot AVAILABLE, "
            f"got {after['status']}"
        )


class TestOptimisticConcurrency:

    def test_confirm_with_stale_version_rejected(self):
        """PRD §2.7: "Confirming a sales order requires the request to carry
        `expected_order_version`, holding the client's last observed `version`
        of the order. If the order's current `version` has advanced since that
        observation, the confirm is rejected with `ERR_STALE_VERSION` (HTTP
        412), because the stale writer's view of pool-credit application no
        longer reflects the order."
        PRD §2.8: "This check is pinned before state preconditions so that a
        stale writer always receives 412 even when the requested transition
        would also be state-invalid."

        Design: Corner/cross_cutting_layers/occ_stale_order_version_on_confirm
        """
        spec, _lot, customer = setup_sellable_world("OCC1", lot_quantity=500)
        order = create_order(customer["id"], spec["id"], 1, "NEW")
        stale_v = order["version"]
        first = validate_success(api_client.confirm_order(
            order["id"], {"expected_order_version": stale_v}, SALES))
        assert first["version"] == stale_v + 1
        # The second confirm replays the pre-confirm version: stale AND
        # state-invalid, and the stale check is pinned first.
        resp = api_client.confirm_order(
            order["id"], {"expected_order_version": stale_v}, SALES)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
        after = get_order(order["id"])
        assert after["version"] == stale_v + 1, (
            "exactly one increment from the single successful confirm"
        )

    def test_dispatch_with_pre_stop_version_rejected(self):
        """PRD §2.7: "Dispatching a delivery route requires
        `expected_route_version`. If the route's `version` no longer matches —
        another writer having advanced it, freezing a different cube and load
        composition — the dispatch is rejected with `ERR_STALE_VERSION` (HTTP
        412)."
        PRD §3.8: "Adding a stop also increments the route's `version`."

        Design: Corner/cross_cutting_layers/occ_stale_route_version_on_dispatch
        """
        spec, _lot, customer = setup_sellable_world("OCC2", lot_quantity=500)
        order = create_allocated_order(customer["id"], spec["id"], 1)
        route = create_route()
        pre_stop_version = route["version"]
        add_route_stop(route["id"], 1, "DELIVERY", order_id=order["id"])
        resp = api_client.dispatch_route(
            route["id"], {"expected_route_version": pre_stop_version}, FLEET)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
        after = get_route(route["id"])
        assert after["status"] == "PLAN"
        assert after["version"] > pre_stop_version, (
            "adding the stop bumped the route version past the stale view"
        )

    def test_allocate_with_current_version_succeeds(self):
        """PRD §2.7: "Allocating stock against a sales order likewise requires
        `expected_order_version`. A mismatch with the order's current `version`
        is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting lot
        reservations from being committed against an order the client has not
        re-read."
        PRD §2.7: "Successful confirm, allocate, and dispatch operations each
        increment the corresponding resource's `version` by one, as does every
        other mutation in the system per §2.4."

        Design: Corner/cross_cutting_layers/occ_correct_version_succeeds
        """
        spec, lot, customer = setup_sellable_world("OCC3", lot_quantity=500)
        order = create_order(customer["id"], spec["id"], 2, "NEW")
        confirmed = confirm_order(order["id"], order["version"])
        resp = api_client.allocate_order(
            order["id"], {"expected_order_version": confirmed["version"]},
            SALES)
        allocated = validate_success(resp)
        assert allocated["fulfillment_status"] == "ALLOCATED"
        assert allocated["version"] == confirmed["version"] + 1
        lines = list_order_lines(order["id"])
        assert lines[0]["allocated_lot_id"] == lot["id"]
        assert lines[0]["status"] == "ALLOCATED"


class TestDraftGatedOrderMutations:

    def test_add_line_to_confirmed_order_rejected(self):
        """PRD §3.6: "Further lines join only while the order is `DRAFT`;
        adding a line to an order in any other state fails with
        `ERR_INVALID_STATE`."

        Design: Corner/endpoints/add_line_to_non_draft_order_rejected
        """
        spec, _lot, customer = setup_sellable_world("LineLock",
                                                    lot_quantity=500)
        order = create_confirmed_order(customer["id"], spec["id"], 1)
        resp = api_client.add_order_line(
            order["id"],
            {"spec_id": spec["id"], "quantity": 1,
             "quality_grade_requested": "A"},
            SALES,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

    def test_second_confirm_rejected_not_draft(self):
        """PRD §3.6: "The confirm action requires the order to be `DRAFT` (else
        `ERR_ORDER_NOT_DRAFT`), at least one `OPEN` line (else
        `ERR_ORDER_EMPTY`), and an `ACTIVE` customer off credit hold (else
        `ERR_CUSTOMER_CREDIT_HOLD`)"

        Design: Corner/endpoints/double_confirm_rejected_not_draft
        """
        spec, _lot, customer = setup_sellable_world("TwiceConfirm",
                                                    lot_quantity=500)
        order = create_order(customer["id"], spec["id"], 1, "NEW")
        confirmed = confirm_order(order["id"], order["version"])
        subtotal = confirmed["subtotal_cents"]
        # Carry the CURRENT version so the state gate (not OCC) is exercised.
        resp = api_client.confirm_order(
            order["id"], {"expected_order_version": confirmed["version"]},
            SALES)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DRAFT)
        assert resp.status_code == 409
        after = get_order(order["id"])
        assert after["subtotal_cents"] == subtotal, (
            "a rejected re-confirm must not recompute pricing"
        )
