"""Order allocation selector, per-package rounding, shipment cascade, and cancel release."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    api_client, ApiErrorId,
    publish_price_list, place_order, get_order, get_contract, get_package,
    create_active_contract, setup_order_with_allocation,
    produce_stamped_packages,
    make_sales_rep_headers, make_grader_headers, make_sawyer_headers,
)


def _two_stamped_packages():
    """Two DF NO_2 len-12 packages, each measured dry 3.333, stamped an hour apart."""
    publish_price_list()
    run, packages = produce_stamped_packages(
        [{"green_mbf": 3.5}, {"green_mbf": 3.5}], [3.333, 3.333],
    )
    return packages


class TestAllocationRounding:
    def test_contract_unit_price_pinned_and_per_package_rounding(self, api):
        """PRD Section 3.7: "The pinned `unit_price_cents` is the contract's `contract_price_per_mbf_cents`."
        PRD Section 3.8: "The order then computes `allocated_mbf` as the sum of the selected packages' `dry_mbf`, and `total_cents` with a pinned two-step rule: for each selected package, multiply its `dry_mbf` by the order's `unit_price_cents` and round half-up to whole cents — per package first — then sum those per-package amounts."

        Design: Difficulty/combinatorial_formula/order_total_per_package_rounding_then_sum
        """
        contract = create_active_contract(customer_name="Cedarhurst",
                                          contract_price_per_mbf_cents=55001)
        order, packages, _run = setup_order_with_allocation(
            [{"green_mbf": 3.5}, {"green_mbf": 3.5}], [3.333, 3.333],
            order_overrides={"customer_name": "Cedarhurst", "volume_mbf": 6, "length_spec": 12},
            price_list=False, contract=contract,
        )
        assert order["unit_price_cents"] == 55001, (
            f"contract price pinned verbatim, no spot tiers; got {order['unit_price_cents']}"
        )
        # round(3.333 * 55001) = round(183318.333) = 183318 per package; 183318 + 183318 = 366636.
        # The rejected sum-then-round reading would give round(6.666 * 55001) = 366637.
        assert order["total_cents"] == 366636, (
            f"round-per-package then sum, got {order['total_cents']}"
        )

    def test_allocation_accumulates_whole_packages_to_volume(self, api):
        """PRD Section 3.8: "The walk accumulates whole packages in ranked order until the cumulative `dry_mbf` reaches or exceeds `volume_mbf`, and it stops immediately after the package that crosses the threshold: that crossing package is included whole, so an order over-allocates by at most one package and never splits a package."

        Design: Difficulty/combinatorial_formula/order_total_per_package_rounding_then_sum
        """
        contract = create_active_contract(customer_name="Cedarhurst",
                                          contract_price_per_mbf_cents=55001)
        order, packages, _run = setup_order_with_allocation(
            [{"green_mbf": 3.5}, {"green_mbf": 3.5}], [3.333, 3.333],
            order_overrides={"customer_name": "Cedarhurst", "volume_mbf": 6, "length_spec": 12},
            price_list=False, contract=contract,
        )
        assert order["allocated_mbf"] == pytest.approx(6.666, abs=1e-6)
        assert order["status"] == "ALLOCATED"
        for pkg in packages:
            after = get_package(pkg["id"])
            assert after["status"] == "ALLOCATED"
            assert after["sales_order_id"] == order["id"]


class TestImmediateConsistency:
    def test_immediate_consistency_on_allocate(self, api):
        """PRD Section 2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD Section 3.8: "The order then computes `allocated_mbf` as the sum of the selected packages' `dry_mbf`, and `total_cents` with a pinned two-step rule: for each selected package, multiply its `dry_mbf` by the order's `unit_price_cents` and round half-up to whole cents — per package first — then sum those per-package amounts."

        Design: Corner/consistency_model/immediate_consistency_on_allocate
        """
        _two_stamped_packages()
        order = place_order(volume_mbf=6, length_spec=12)
        allocated = validate_success(api.allocate_sales_order(order["id"], make_sales_rep_headers()), 200)
        assert allocated["status"] == "ALLOCATED"
        assert allocated["allocated_mbf"] == pytest.approx(6.666, abs=1e-6)
        # round(3.333 * 60000) = 199980 per package, summed twice.
        assert allocated["total_cents"] == 399960, (
            f"allocate response itself carries the totals, got {allocated['total_cents']}"
        )


class TestAllocationGuards:
    def test_allocate_cancelled_order_reports_invalid_state(self, api):
        """PRD Section 2.7: "Only after the request is well-formed does the server evaluate entity state preconditions for the invoked transition (`ERR_INVALID_STATE`, or `ERR_CONTRACT_NOT_ACTIVE` where a contract order is involved), then business-temporal rules (schedule windows), then business constraints (chamber and line occupancy, deck capacity, run log-set integrity), then referential linkage (species and grade agreement), and finally fiscal rules (contract volume, price-list availability, allocation pool sufficiency, byproduct on-hand)."

        Design: Difficulty/priority_pair_validation_conflict/allocate_state_beats_fiscal
        """
        publish_price_list()
        order = place_order(volume_mbf=10, length_spec=12)
        validate_success(api.cancel_sales_order(order["id"], make_sales_rep_headers()), 200)
        # The stamped pool is empty too, but the state rule is evaluated first.
        res = api.allocate_sales_order(order["id"], make_sales_rep_headers())
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(order["id"])["status"] == "CANCELLED"

    def test_allocate_placed_order_with_empty_pool_reports_fiscal(self, api):
        """PRD Section 3.8: "Before anything moves, the pool's total `dry_mbf` must be at least the order's `volume_mbf`; a shortfall rejects the allocation with `ERR_INSUFFICIENT_STAMPED_VOLUME` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/allocate_state_beats_fiscal
        """
        publish_price_list()
        order = place_order(volume_mbf=10, length_spec=12)
        # Same empty pool, but the order is still PLACED: the fiscal rule fires.
        res = api.allocate_sales_order(order["id"], make_sales_rep_headers())
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_STAMPED_VOLUME)

    def test_insufficient_stamped_pool_on_allocate(self, api):
        """PRD Section 3.8: "Before anything moves, the pool's total `dry_mbf` must be at least the order's `volume_mbf`; a shortfall rejects the allocation with `ERR_INSUFFICIENT_STAMPED_VOLUME` (HTTP 422)."

        Design: Corner/validations/insufficient_stamped_pool_on_allocate
        """
        publish_price_list()
        _run, packages = produce_stamped_packages([{"green_mbf": 5.3}], [5.0])
        order = place_order(volume_mbf=10, length_spec=12)
        res = api.allocate_sales_order(order["id"], make_sales_rep_headers())
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_STAMPED_VOLUME)
        after = get_package(packages[0]["id"])
        assert after["status"] == "STAMPED"
        assert after["sales_order_id"] is None


class TestCancelRelease:
    def test_allocate_then_cancel_releases_packages(self, api):
        """PRD Section 3.8: "Cancelling an `ALLOCATED` order additionally releases the held wood: every allocated package flips back from `ALLOCATED` to `STAMPED` with its `sales_order_id` cleared and its `version` incremented, the order's `allocated_mbf` and `total_cents` reset to zero, the contract reservation releases, and the order lands at `CANCELLED`."

        Design: Difficulty/compensating_invariant/allocate_cancel_allocation_conservation
        """
        packages = _two_stamped_packages()
        order = place_order(volume_mbf=6, length_spec=12)
        allocated = validate_success(api.allocate_sales_order(order["id"], make_sales_rep_headers()), 200)
        assert allocated["allocated_mbf"] == pytest.approx(6.666, abs=1e-6)
        cancelled = validate_success(api.cancel_sales_order(order["id"], make_sales_rep_headers()), 200)
        assert cancelled["status"] == "CANCELLED"
        for pkg in packages:
            after = get_package(pkg["id"])
            assert after["status"] == "STAMPED", f"full release, got {after['status']}"
            assert after["sales_order_id"] is None

    def test_allocate_then_cancel_zeroes_order_totals(self, api):
        """PRD Section 3.8: "Cancelling an `ALLOCATED` order additionally releases the held wood: every allocated package flips back from `ALLOCATED` to `STAMPED` with its `sales_order_id` cleared and its `version` incremented, the order's `allocated_mbf` and `total_cents` reset to zero, the contract reservation releases, and the order lands at `CANCELLED`."

        Design: Difficulty/compensating_invariant/allocate_cancel_allocation_conservation
        """
        _two_stamped_packages()
        order = place_order(volume_mbf=6, length_spec=12)
        validate_success(api.allocate_sales_order(order["id"], make_sales_rep_headers()), 200)
        cancelled = validate_success(api.cancel_sales_order(order["id"], make_sales_rep_headers()), 200)
        assert cancelled["allocated_mbf"] == 0, (
            f"allocated volume conserved back to 0, got {cancelled['allocated_mbf']}"
        )
        assert cancelled["total_cents"] == 0


class TestShipCascade:
    def _allocated_contract_order(self):
        """ACTIVE contract committed 10; one stamped package dry 10.5; order vol 10 allocated."""
        contract = create_active_contract(customer_name="Acme Builders", committed_mbf=10)
        order, packages, _run = setup_order_with_allocation(
            [{"green_mbf": 12.0}], [10.5],
            order_overrides={"customer_name": "Acme Builders", "volume_mbf": 10, "length_spec": 12},
            price_list=False, contract=contract,
        )
        return contract, order, packages[0]

    def test_ship_flips_order_and_package_to_shipped(self, api):
        """PRD Section 3.8: "Every allocated package flips from `ALLOCATED` to `SHIPPED` — allocation guarantees stamped origin, so only grade-stamped lumber ever ships — and each flip increments the package's `version`."

        Design: Difficulty/transitive_cascade/ship_order_cascade_to_contract_close
        """
        _contract, order, pkg = self._allocated_contract_order()
        shipped = validate_success(api.ship_sales_order(order["id"], make_sales_rep_headers()), 200)
        assert shipped["status"] == "SHIPPED"
        assert get_package(pkg["id"])["status"] == "SHIPPED"

    def test_ship_re_derives_contract_and_auto_closes(self, api):
        """PRD Section 3.8: "When a recomputed `shipped_mbf` reaches or exceeds the contract's `committed_mbf` while the contract is `ACTIVE`, the contract auto-transitions from `ACTIVE` to `CLOSED` and its `version` increments — no human action required."
        PRD Section 3.8: "The shipped order's own `volume_mbf` is released from the contract's `reserved_mbf`, since the order is no longer `PLACED` or `ALLOCATED`; the order moves to `SHIPPED` and its `version` increments."

        Design: Difficulty/transitive_cascade/ship_order_cascade_to_contract_close
        """
        contract, order, _pkg = self._allocated_contract_order()
        validate_success(api.ship_sales_order(order["id"], make_sales_rep_headers()), 200)
        after = get_contract(contract["id"])
        assert after["shipped_mbf"] == pytest.approx(10.5, abs=1e-6)
        assert after["status"] == "CLOSED", f"10.5 >= committed 10 auto-closes, got {after['status']}"
        assert after["reserved_mbf"] == 0, "order volume released on ship"


class TestTerminalLockdown:
    def test_ship_placed_order_returns_invalid_state(self, api):
        """PRD Section 3.8: "Shipping or cancelling an order in any other state is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/ship_placed_order_returns_invalid_state
        """
        publish_price_list()
        order = place_order(volume_mbf=5, length_spec=12)
        res = api.ship_sales_order(order["id"], make_sales_rep_headers())
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(order["id"])["status"] == "PLACED"

    def test_cancel_shipped_order_terminal_lockdown(self, api):
        """PRD Section 3.8: "Shipping or cancelling an order in any other state is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_shipped_order_terminal_lockdown
        """
        contract = create_active_contract(customer_name="Acme Builders", committed_mbf=100)
        order, packages, _run = setup_order_with_allocation(
            [{"green_mbf": 12.0}], [10.5],
            order_overrides={"customer_name": "Acme Builders", "volume_mbf": 10, "length_spec": 12},
            price_list=False, contract=contract,
        )
        validate_success(api.ship_sales_order(order["id"], make_sales_rep_headers()), 200)
        res = api.cancel_sales_order(order["id"], make_sales_rep_headers())
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_package(packages[0]["id"])["status"] == "SHIPPED", (
            "SHIPPED is terminal; nothing rolls back"
        )


class TestReverseReachability:
    def test_fk_reverse_reachability_lists(self, api):
        """PRD Section 3.9: "Log loads list with optional `status`, `species`, and `sawing_run_id` filters; lumber packages list with optional `status`, `species`, `grade`, `sales_order_id`, `kiln_charge_id`, and `sawing_run_id` filters; sales orders list with optional `contract_id` and `status` filters; and all lists paginate per §2.3."
        PRD Section 3.6: "Every inspection, stamp or restamp, appends an immutable grade inspection row carrying the `package_id`, the `inspector_grade`, the `action`, and the optional `note`; the history of a package is readable as this append-only list, and the list operation returns 200 while a newly recorded inspection returns 201."

        Design: Corner/entities/fk_reverse_reachability_lists
        """
        contract = create_active_contract(customer_name="Acme Builders")
        order, packages, run = setup_order_with_allocation(
            [{"green_mbf": 12.0}], [10.5],
            order_overrides={"customer_name": "Acme Builders", "volume_mbf": 10, "length_spec": 12},
            price_list=False, contract=contract,
        )
        pkg = packages[0]

        loads, _m = validate_paginated(
            api.list_log_loads(make_sawyer_headers(), params={"sawing_run_id": run["id"]})
        )
        assert len(loads) == 1 and loads[0]["sawing_run_id"] == run["id"], (
            "LogLoad.sawing_run_id reverse-reachable via the list filter"
        )

        pkgs, _m = validate_paginated(
            api.list_lumber_packages(make_sales_rep_headers(), params={"sales_order_id": order["id"]})
        )
        assert len(pkgs) == 1 and pkgs[0]["id"] == pkg["id"], (
            "LumberPackage.sales_order_id reverse-reachable via the list filter"
        )

        orders, _m = validate_paginated(
            api.list_sales_orders(make_sales_rep_headers(), params={"contract_id": contract["id"]})
        )
        assert len(orders) == 1 and orders[0]["id"] == order["id"], (
            "SalesOrder.contract_id reverse-reachable via the list filter"
        )

        inspections, _m = validate_paginated(
            api.list_grade_inspections(pkg["id"], make_grader_headers())
        )
        assert len(inspections) == 1 and inspections[0]["action"] == "STAMP", (
            "GradeInspection.package_id reverse-reachable via the sub-resource list"
        )
