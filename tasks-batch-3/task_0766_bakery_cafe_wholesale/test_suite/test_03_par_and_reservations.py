"""Par-pool reservation: the availability boundary, conservation on cancel, and immediacy."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, setup_committed_line_with_account, make_delivery_order,
    get_line, assert_par_partition, TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]


class TestParAvailabilityZeroBoundary:
    def test_reserving_exactly_available_leaves_zero_available(self, api):
        """PRD 2.7: "a line's reserved_qty equals the sum of the qty of every one of that
        line's delivery orders whose fulfillment_status is anything other than CANCELLED,
        and its available_qty equals par_qty minus reserved_qty."

        Design: Difficulty/boundary_precision_check/par_availability_zero_boundary
        """
        ctx = setup_committed_line_with_account(api, par_qty=5,
                                                production_date="2026-07-11T00:00:00Z")
        make_delivery_order(api, ctx["account"]["id"], ctx["product"]["id"], ctx["line"]["id"],
                            qty=5, delivery_date="2026-07-11T10:00:00Z")
        line = get_line(api, ctx["line"]["id"])
        assert line["reserved_qty"] == 5, line
        assert line["available_qty"] == 0, line
        assert_par_partition(line)

    def test_reserving_beyond_available_is_rejected(self, api):
        """PRD 3.7: "The reservation must not drive the line's available_qty negative —
        the ordered quantity must not exceed the currently available quantity — else
        ERR_INSUFFICIENT_PAR."

        Design: Difficulty/boundary_precision_check/par_availability_zero_boundary
        """
        ctx = setup_committed_line_with_account(api, par_qty=5,
                                                production_date="2026-07-11T00:00:00Z")
        make_delivery_order(api, ctx["account"]["id"], ctx["product"]["id"], ctx["line"]["id"],
                            qty=5, delivery_date="2026-07-11T10:00:00Z")
        validate_error(api.create_delivery_order({
            "wholesale_account_id": ctx["account"]["id"], "product_id": ctx["product"]["id"],
            "bake_plan_line_id": ctx["line"]["id"], "delivery_date": "2026-07-11T10:00:00Z",
            "qty": 1}, MANAGER), ApiErrorId.ERR_INSUFFICIENT_PAR.value)
        line = get_line(api, ctx["line"]["id"])
        assert line["reserved_qty"] == 5, line
        assert line["available_qty"] == 0, line


class TestParConservationOnCancel:
    def test_partition_holds_while_order_is_open(self, api):
        """PRD 2.7: "The invariant reserved_qty + available_qty == par_qty therefore holds
        continuously."

        Design: Difficulty/compensating_invariant/par_pool_conservation_on_order_cancel
        """
        ctx = setup_committed_line_with_account(api, par_qty=40,
                                                production_date="2026-06-15T00:00:00Z")
        make_delivery_order(api, ctx["account"]["id"], ctx["product"]["id"], ctx["line"]["id"],
                            qty=10, delivery_date="2026-06-15T10:00:00Z")
        line = get_line(api, ctx["line"]["id"])
        assert line["reserved_qty"] == 10, line
        assert line["available_qty"] == 30, line
        assert line["par_qty"] == 40, line

    def test_cancel_releases_reservation_restoring_par_pool(self, api):
        """PRD 3.7: "Cancelling an order that is PENDING, PACKED, or OUT_FOR_DELIVERY sets
        it to CANCELLED, releases its par (its qty leaves the line's reserved_qty, and
        available_qty is recomputed)."

        Design: Difficulty/compensating_invariant/par_pool_conservation_on_order_cancel
        """
        ctx = setup_committed_line_with_account(api, par_qty=40,
                                                production_date="2026-06-15T00:00:00Z")
        order = make_delivery_order(api, ctx["account"]["id"], ctx["product"]["id"],
                                    ctx["line"]["id"], qty=10,
                                    delivery_date="2026-06-15T10:00:00Z")
        validate_success(api.cancel_delivery_order(order["id"], MANAGER))
        line = get_line(api, ctx["line"]["id"])
        assert line["reserved_qty"] == 0, line
        assert line["available_qty"] == 40, line
        assert line["par_qty"] == 40, line


class TestReservationVisibleImmediately:
    def test_order_create_reserves_par_visible_on_next_read(self, api):
        """PRD 3.7: "reserves its quantity against the line (raising reserved_qty and
        lowering available_qty)."

        Design: Corner/consistency_model/order_create_reserves_par_visible_immediately
        """
        ctx = setup_committed_line_with_account(api, par_qty=20,
                                                production_date="2026-07-01T00:00:00Z")
        make_delivery_order(api, ctx["account"]["id"], ctx["product"]["id"], ctx["line"]["id"],
                            qty=3, delivery_date="2026-07-01T10:00:00Z")
        line = get_line(api, ctx["line"]["id"])
        assert line["reserved_qty"] == 3, line
        assert line["available_qty"] == 17, line
