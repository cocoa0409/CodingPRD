"""Allocation waterfall, backorder auto-fill, and stock reservation invariants."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_available_qty_identity,
    create_branch,
    create_central,
    create_customer,
    create_item,
    get_location_balance,
    get_order,
    get_order_lines,
    place_order,
    restock,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
BRANCH_MANAGER = TEST_USERS["branch_manager_headers"]


def _partial_allocation_setup(api):
    """Customer credit 10,000,000; STOCKED item list 5,000 with 3 on hand;
    WILL_CALL order for 5 units confirmed (3 allocated, 2 backordered)."""
    customer = create_customer(
        account_number="PD-1", credit_limit_cents=10000000,
        primary_ship_to_state="OH",
    )
    item = create_item(sku="PD-1", list_price_cents=5000)
    branch = create_branch(location_code="BR-6")
    restock(branch["id"], item["id"], 3)
    order = place_order(
        customer["id"], branch["id"], [{"item_id": item["id"], "qty": 5}]
    )
    confirmed = validate_success(api.confirm_order(order["id"], ADMIN), 200)
    return customer, item, branch, confirmed


class TestOrderParallelStatusDimensions:
    def test_backorder_fill_advances_only_fulfillment_dimension(
        self, api, admin_headers
    ):
        """PRD §3.6: "the order's `fulfillment_status` becomes `ALLOCATED` when no
        line carries a backorder, else `PARTIALLY_ALLOCATED`."
        PRD §3.3: "When a line's `qty_backordered` reaches zero and no other line
        of that order still awaits stock, the parent order's `fulfillment_status`
        recomputes from `PARTIALLY_ALLOCATED` to `ALLOCATED` automatically, with
        no client request on the order itself."

        Design: Difficulty/non_linear_state_machine/order_parallel_status_dimensions
        """
        customer, item, branch, confirmed = _partial_allocation_setup(api)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["fulfillment_status"] == "PARTIALLY_ALLOCATED"

        restock(branch["id"], item["id"], 5)
        after = get_order(confirmed["id"])
        assert after["status"] == "CONFIRMED"
        assert after["fulfillment_status"] == "ALLOCATED"

    def test_mark_ready_moves_fulfillment_while_commercial_status_pinned(
        self, api, admin_headers, branch_manager_headers
    ):
        """PRD §3.7: "A `BranchManager` marks a `CONFIRMED` order ready: for
        `WILL_CALL` orders the `fulfillment_status` moves to
        `READY_FOR_WILL_CALL`, and for `SAME_DAY` or `STANDARD` orders to
        `SHIPPED`."
        PRD §3.7: "Both moves are allowed from `ALLOCATED` and from
        `PARTIALLY_ALLOCATED` alike"

        Design: Difficulty/non_linear_state_machine/order_parallel_status_dimensions
        """
        customer, item, branch, confirmed = _partial_allocation_setup(api)
        restock(branch["id"], item["id"], 5)

        readied = validate_success(
            api.mark_order_ready(confirmed["id"], branch_manager_headers), 200
        )
        assert readied["fulfillment_status"] == "READY_FOR_WILL_CALL"
        after = get_order(confirmed["id"])
        assert after["status"] == "CONFIRMED"


class TestCancelReleaseBackorderFillCascade:
    def _setup(self, api):
        """Order A (qty 5) confirmed against 5 on hand; order B (qty 3) confirmed
        into the empty branch bucket -> 3 backordered, PARTIALLY_ALLOCATED."""
        customer = create_customer(
            account_number="BO-1", credit_limit_cents=10000000,
            primary_ship_to_state="OH",
        )
        item = create_item(sku="BO-1", list_price_cents=1000)
        branch = create_branch(location_code="BR-8")
        restock(branch["id"], item["id"], 5)
        order_a = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 5}]
        )
        validate_success(api.confirm_order(order_a["id"], ADMIN), 200)
        order_b = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 3}]
        )
        confirmed_b = validate_success(api.confirm_order(order_b["id"], ADMIN), 200)
        return customer, item, branch, order_a, confirmed_b

    def test_cancel_releases_reservations_and_recomputes_balance(
        self, api, admin_headers
    ):
        """PRD §3.7: "Cancellation of a `CONFIRMED` order runs the mirror image:
        each line releases its reservations — the branch balance's `reserved_qty`
        falls by `qty_branch`, the selected central's by `qty_central`, with
        `available_qty` recomputed on every touched balance — the freed
        availability immediately triggers the backorder auto-fill chain of §3.3"

        Design: Difficulty/transitive_cascade/cancel_release_backorder_fill_cascade
        """
        customer, item, branch, order_a, confirmed_b = self._setup(api)
        assert confirmed_b["fulfillment_status"] == "PARTIALLY_ALLOCATED"

        cancelled = validate_success(api.cancel_order(order_a["id"], admin_headers))
        assert cancelled["status"] == "CANCELLED"

        balance = get_location_balance(branch["id"], item["id"])
        assert balance["on_hand_qty"] == 5
        assert balance["reserved_qty"] == 3
        assert balance["available_qty"] == 2
        assert_available_qty_identity(balance)

    def test_freed_units_autofill_oldest_backordered_line(self, api, admin_headers):
        """PRD §3.3: "Each fill decrements the line's `qty_backordered`,
        increments its `qty_branch` or `qty_central` as appropriate, and
        re-increments the touched balance's `reserved_qty` by the filled units.
        When a line's `qty_backordered` reaches zero and no other line of that
        order still awaits stock, the parent order's `fulfillment_status`
        recomputes from `PARTIALLY_ALLOCATED` to `ALLOCATED` automatically"

        Design: Difficulty/transitive_cascade/cancel_release_backorder_fill_cascade
        """
        _customer, item, _branch, order_a, confirmed_b = self._setup(api)
        validate_success(api.cancel_order(order_a["id"], admin_headers), 200)

        lines_b = get_order_lines(confirmed_b["id"])
        assert lines_b[0]["qty_branch"] == 3
        assert lines_b[0]["qty_backordered"] == 0

        order_b_after = get_order(confirmed_b["id"])
        assert order_b_after["fulfillment_status"] == "ALLOCATED"


class TestStockReserveReleaseConservation:
    def _setup(self, api):
        """STOCKED item with 5 on hand; WILL_CALL order for 2 confirmed."""
        customer = create_customer(
            account_number="INV-1", credit_limit_cents=10000000,
            primary_ship_to_state="OH",
        )
        item = create_item(sku="INV-1", list_price_cents=1000)
        branch = create_branch(location_code="BR-15")
        restock(branch["id"], item["id"], 5)
        order = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 2}]
        )
        validate_success(api.confirm_order(order["id"], ADMIN), 200)
        return customer, item, branch, order

    def test_reserve_moves_only_the_reservation_column(self, api, admin_headers):
        """PRD §2.9: "The identity `available_qty` equals `on_hand_qty` minus
        `reserved_qty` holds at all times and is recomputed on every mutation —
        restock, reservation, release, fulfillment, and return putaway alike."
        PRD §3.6: "Reservations land as `reserved_qty` increments on the branch
        and selected central balances"

        Design: Difficulty/compensating_invariant/stock_reserve_release_conservation
        """
        _customer, item, branch, _order = self._setup(api)
        balance = get_location_balance(branch["id"], item["id"])
        assert balance["on_hand_qty"] == 5
        assert balance["reserved_qty"] == 2
        assert balance["available_qty"] == 3
        assert_available_qty_identity(balance)

    def test_release_restores_pre_confirm_reservation(self, api, admin_headers):
        """PRD §3.7: "each line releases its reservations — the branch balance's
        `reserved_qty` falls by `qty_branch`, the selected central's by
        `qty_central`, with `available_qty` recomputed on every touched balance"
        PRD §2.9: "The identity `available_qty` equals `on_hand_qty` minus
        `reserved_qty` holds at all times and is recomputed on every mutation"

        Design: Difficulty/compensating_invariant/stock_reserve_release_conservation
        """
        _customer, item, branch, order = self._setup(api)
        cancelled = validate_success(api.cancel_order(order["id"], admin_headers))
        assert cancelled["status"] == "CANCELLED"

        balance = get_location_balance(branch["id"], item["id"])
        assert balance["on_hand_qty"] == 5
        assert balance["reserved_qty"] == 0
        assert balance["available_qty"] == 5
        assert_available_qty_identity(balance)


class TestCentralSelector:
    def test_central_selector_prefers_highest_available(self, api, admin_headers):
        """PRD §3.6: "If units remain, exactly one central depot is chosen —
        eligible depots are `CENTRAL` locations whose balance for the item has
        positive availability, ranked by `available_qty` descending with ties
        broken by the location's `created_at` ascending, never by identifier"
        PRD §3.6: "`SPLIT_STOCK` when branch plus central exactly covered it"

        Design: Corner/calculations/central_selector_prefers_highest_available
        """
        customer = create_customer(
            account_number="CS-1", credit_limit_cents=100000,
            primary_ship_to_state="OH",
        )
        item = create_item(sku="CS-1", list_price_cents=800)
        branch = create_branch(location_code="BR-CS")
        central_a = create_central(location_code="CN-A", region_state="OH")
        central_b = create_central(location_code="CN-B", region_state="OH")
        restock(central_a["id"], item["id"], 4)
        restock(central_b["id"], item["id"], 9)

        order = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 5}],
            fulfillment_method="STANDARD",
        )
        confirmed = validate_success(api.confirm_order(order["id"], admin_headers))
        assert confirmed["fulfillment_status"] == "ALLOCATED"

        line = get_order_lines(order["id"])[0]
        assert line["qty_branch"] == 0
        assert line["qty_central"] == 5
        assert line["fulfillment_source"] == "SPLIT_STOCK"

        balance_b = get_location_balance(central_b["id"], item["id"])
        balance_a = get_location_balance(central_a["id"], item["id"])
        assert balance_b["reserved_qty"] == 5
        assert balance_a["reserved_qty"] == 0
