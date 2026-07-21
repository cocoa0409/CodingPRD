"""Inventory reservations, quarantine/cancel cascades, and OCC (PRD §2.7, §2.9, §3.4, §3.6).

Covers the depth-3 quarantine cascade, the order-cancel release cascade, unit
and wallet conservation, empty-pool allocation rejection, and stale-version
optimistic concurrency on manual reservations.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, make_customer_headers,
    PROD, SALES, create_reservation_payload,
    create_customer, create_product, create_released_batch, create_order, add_line,
    setup_allocated_retail_order, setup_confirmed_retail_order,
)


def _reservation_for_line(api, line_id):
    data, _meta = validate_paginated(
        api.list_reservations(SALES, params={"order_line_id": line_id}))
    assert len(data) == 1, data
    return data[0]


class TestQuarantineCascade:
    """transitive_cascade / quarantine_voids_reservation_backorders_order —
    quarantining the batch VOIDs its reservation, drops the line's
    allocated_units below quantity, and moves the order ALLOCATED ->
    BACKORDERED."""

    def test_quarantine_backorders_order_and_zeroes_allocation(self, api):
        """PRD §3.4: "any order in `ALLOCATED` status that, as a result, now has
        at least one line whose `allocated_units` has fallen below its `quantity`
        transitions from `ALLOCATED` to `BACKORDERED`." PRD §3.4: "each voided
        reservation decrements the `allocated_units` of its owning order line by
        the reservation's `units`."

        Design: Difficulty/transitive_cascade/quarantine_voids_reservation_backorders_order
        """
        setup = setup_allocated_retail_order(batch_units=100, line_qty=30, base_price=1000)
        validate_success(api.quarantine_batch(setup["batch"]["id"], PROD, {"reason": "milk cross-contact"}))
        order = validate_success(api.get_order(setup["order"]["id"], SALES))
        assert order["status"] == "BACKORDERED", order
        line = validate_success(api.get_order_line(setup["line"]["id"], SALES))
        assert line["allocated_units"] == 0, line

    def test_quarantine_voids_the_reservation(self, api):
        """PRD §3.4: "every reservation drawing on the quarantined lot that is
        currently `ACTIVE` is set to `VOIDED`."

        Design: Difficulty/transitive_cascade/quarantine_voids_reservation_backorders_order
        """
        setup = setup_allocated_retail_order(batch_units=100, line_qty=30, base_price=1000)
        validate_success(api.quarantine_batch(setup["batch"]["id"], PROD, {"reason": "milk cross-contact"}))
        reservation = _reservation_for_line(api, setup["line"]["id"])
        assert reservation["status"] == "VOIDED", reservation


class TestCancelReleasesReservation:
    """transitive_cascade / cancel_order_releases_reservation_restores_batch —
    cancelling the order RELEASEs its reservation and restores the batch's
    available_units from 70 back to 100."""

    def test_cancel_restores_batch_available_units(self, api):
        """PRD §3.6: "An `ALLOCATED` order, on cancellation, additionally releases
        each `ACTIVE` reservation on the order by setting it to `RELEASED` and
        restoring its batch's `available_units` by the reservation's `units`".

        Design: Difficulty/transitive_cascade/cancel_order_releases_reservation_restores_batch
        """
        setup = setup_allocated_retail_order(batch_units=100, line_qty=30, base_price=1000)
        cust_headers = make_customer_headers(setup["customer"]["id"])
        order = validate_success(api.cancel_order(setup["order"]["id"], cust_headers))
        assert order["status"] == "CANCELLED", order
        batch = validate_success(api.get_batch(setup["batch"]["id"], PROD))
        assert batch["available_units"] == 100, batch

    def test_cancel_sets_reservation_released(self, api):
        """PRD §3.6: "releases each `ACTIVE` reservation on the order by setting it
        to `RELEASED` and restoring its batch's `available_units` by the
        reservation's `units`".

        Design: Difficulty/transitive_cascade/cancel_order_releases_reservation_restores_batch
        """
        setup = setup_allocated_retail_order(batch_units=100, line_qty=30, base_price=1000)
        cust_headers = make_customer_headers(setup["customer"]["id"])
        validate_success(api.cancel_order(setup["order"]["id"], cust_headers))
        reservation = _reservation_for_line(api, setup["line"]["id"])
        assert reservation["status"] == "RELEASED", reservation


class TestInventoryUnitsConserved:
    """compensating_invariant / inventory_units_conserved_reserve_then_release —
    after allocate (reserve 30) then cancel (release 30), Batch.available_units
    returns to initial_units=100 with zero drift."""

    def test_available_units_return_to_initial_after_cycle(self, api):
        """PRD §2.9: "For a lot in `RELEASED` status it equals the lot's
        `initial_units` minus the sum of `units` across all reservations on that
        lot in `ACTIVE` status". PRD §3.6: "restoring its batch's
        `available_units` by the reservation's `units`".

        Design: Difficulty/compensating_invariant/inventory_units_conserved_reserve_then_release
        """
        setup = setup_allocated_retail_order(batch_units=100, line_qty=30, base_price=1000)
        cust_headers = make_customer_headers(setup["customer"]["id"])
        validate_success(api.cancel_order(setup["order"]["id"], cust_headers))
        batch = validate_success(api.get_batch(setup["batch"]["id"], PROD))
        assert batch["available_units"] == 100, batch
        assert batch["available_units"] == batch["initial_units"], batch

    def test_reservation_draws_down_available_units(self, api):
        """PRD §2.9: "For a lot in `RELEASED` status it equals the lot's
        `initial_units` minus the sum of `units` across all reservations on that
        lot in `ACTIVE` status; reservations in `VOIDED`, `RELEASED`, or
        `CONSUMED` status do not subtract."

        Design: Difficulty/compensating_invariant/inventory_units_conserved_reserve_then_release
        """
        setup = setup_allocated_retail_order(batch_units=100, line_qty=30, base_price=1000)
        # Post-allocate: one ACTIVE reservation of 30 -> available = 100 - 30 = 70.
        batch = validate_success(api.get_batch(setup["batch"]["id"], PROD))
        assert batch["available_units"] == 70, batch


class TestAllocateEmptyInventoryPool:
    """boundary_precision_check / allocate_empty_inventory_pool — with zero
    RELEASED batches of the line product, the candidate pool is empty and the
    whole allocate is rejected."""

    def test_allocate_with_no_batches_rejected(self, api):
        """PRD §3.6: "If, after all candidates for a line are exhausted, any need
        remains, the entire allocation is rejected with
        `ERR_INSUFFICIENT_INVENTORY` and no reservations are committed —
        allocation is all-or-nothing."

        Design: Difficulty/boundary_precision_check/allocate_empty_inventory_pool
        """
        setup = setup_confirmed_retail_order(line_qty=1, base_price=1000)
        resp = api.allocate_order(setup["order"]["id"], SALES)
        validate_error(resp, "ERR_INSUFFICIENT_INVENTORY", 409)

    def test_order_stays_confirmed_after_empty_pool_reject(self, api):
        """PRD §3.6: "no reservations are committed — allocation is
        all-or-nothing." The rejected order remains CONFIRMED.

        Design: Difficulty/boundary_precision_check/allocate_empty_inventory_pool
        """
        setup = setup_confirmed_retail_order(line_qty=1, base_price=1000)
        api.allocate_order(setup["order"]["id"], SALES)
        order = validate_success(api.get_order(setup["order"]["id"], SALES))
        assert order["status"] == "CONFIRMED", order


def test_reservation_stale_batch_version_conflict(api):
    """PRD §2.7: "If that value does not equal the batch's current `version`, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no reservation is
    created." PRD §2.7: "On a successful reservation the batch's `version`
    advances by 1, which is precisely what causes a subsequent request holding
    the old value to be rejected."

    Design: Corner/cross_cutting/reservation_stale_batch_version_conflict
    """
    customer = create_customer(account_type="RETAIL")
    product = create_product(base_price_cents=1000, shelf_life_days=60, unit_weight_g=30)
    batch = create_released_batch(product["id"], 100)
    observed_version = batch["version"]
    order = create_order(customer["id"], "RETAIL")
    line = add_line(order["id"], customer["id"], product["id"], 40)
    first = api.create_reservation(
        batch["id"], create_reservation_payload(line["id"], 10, observed_version), SALES)
    validate_success(first, 201)
    stale = api.create_reservation(
        batch["id"], create_reservation_payload(line["id"], 10, observed_version), SALES)
    validate_error(stale, "ERR_STALE_VERSION", 412)
