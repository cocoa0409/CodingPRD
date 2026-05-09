"""Concurrency: explicitly named PRD races (allocate, cycle-count schedule,
wave release, pick-task complete) and OCC version conflict."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_cycle_count_payload, create_pick_complete_payload,
    create_wave_payload, create_order_payload,
    create_warehouse, create_bin, create_lot, putaway_lot_units,
    setup_warehouse_with_inventory, create_allocated_order,
    setup_released_wave_for_order, get_pick_tasks_for_order,
    setup_picking_pick_task,
    run_race, assert_exactly_one_succeeds, assert_race_outcome,
    validate_error_is_one_of,
    TEST_USERS,
)


class TestAllocateRace:
    def test_concurrent_allocate_same_order_one_wins(self, api, staff_headers):
        """PRD §2.9: "Two callers attempting to allocate the same order at
        the same time serialize on Order.status: exactly one allocate
        succeeds, and the loser — which now observes a status other than
        CREATED — is rejected with ERR_INVALID_STATE and HTTP status 409."

        Claim: two concurrent /allocate calls on the same order — exactly
        one succeeds; the loser's response is ERR_INVALID_STATE.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=50, sku="PEN")
        order = validate_success(api.create_order(
            wh["id"],
            create_order_payload(
                requested_lines=[{"sku": "PEN", "qty_units": 5}],
                order_number="ORD-RACE-A", carrier="UPS"),
            staff_headers), 201)
        results = run_race(
            lambda: api.allocate_order(wh["id"], order["id"], staff_headers),
            lambda: api.allocate_order(wh["id"], order["id"], staff_headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # Loser is ERR_INVALID_STATE
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_INVALID_STATE")


class TestCycleCountRace:
    def test_concurrent_schedule_same_bin_one_wins(self, api, staff_headers):
        """PRD §2.9: "Two callers attempting to schedule a cycle count on
        the same (bin_id, lot_id) pair simultaneously serialize on
        Bin.frozen_by_cycle_count_id: at most one cycle count can hold a
        bin's freeze at a time, and the second caller is rejected with
        ERR_BIN_FROZEN and HTTP status 409."

        Claim: two concurrent /cycle_counts on the same (bin_id, lot_id) —
        exactly one succeeds; loser → ERR_BIN_FROZEN.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=30, sku="PEN")
        results = run_race(
            lambda: api.create_cycle_count(
                wh["id"], create_cycle_count_payload(b["id"], lot["id"]),
                staff_headers),
            lambda: api.create_cycle_count(
                wh["id"], create_cycle_count_payload(b["id"], lot["id"]),
                staff_headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_BIN_FROZEN")


class TestWaveReleaseRace:
    def test_concurrent_release_two_waves_one_wins(self, api, staff_headers):
        """PRD §2.9: "Two callers attempting to release different waves on
        the same warehouse at the same time serialize on the warehouse-level
        wave-exclusivity check: exactly one wave reaches RELEASED, and the
        loser receives ERR_WAVE_OVERLAP and HTTP status 409."

        Claim: two concurrent /release calls on different waves of the same
        warehouse — exactly one reaches RELEASED; loser → ERR_WAVE_OVERLAP.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=100, sku="PEN")
        order_a = create_allocated_order(wh["id"], sku="PEN", qty_units=5,
                                         order_number="WV-RACE-A")
        order_b = create_allocated_order(wh["id"], sku="PEN", qty_units=5,
                                         order_number="WV-RACE-B")
        wave_a = validate_success(api.create_wave(
            wh["id"], create_wave_payload([order_a["id"]], wave_code="WV_A"),
            staff_headers), 201)
        wave_b = validate_success(api.create_wave(
            wh["id"], create_wave_payload([order_b["id"]], wave_code="WV_B"),
            staff_headers), 201)
        results = run_race(
            lambda: api.release_wave(wh["id"], wave_a["id"], staff_headers),
            lambda: api.release_wave(wh["id"], wave_b["id"], staff_headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_WAVE_OVERLAP")


class TestPickTaskCompleteRace:
    def test_concurrent_complete_same_pick_task_one_wins(self, api, staff_headers):
        """PRD §2.9: "Two pickers attempting to complete the same pick task
        simultaneously serialize on PickTask.status: the first completion
        wins, and the second observes a status other than PICKING and is
        rejected with ERR_INVALID_STATE and HTTP status 409."

        Claim: two concurrent /complete on same pick task — exactly one
        succeeds; loser → ERR_INVALID_STATE.
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task(order_qty=5)
        results = run_race(
            lambda: api.complete_pick_task(
                wh["id"], pt["id"], create_pick_complete_payload(5),
                staff_headers),
            lambda: api.complete_pick_task(
                wh["id"], pt["id"], create_pick_complete_payload(5),
                staff_headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_INVALID_STATE")


class TestOptimisticConcurrency:
    def test_stale_version_rejected_with_version_conflict(self, api, manager_headers, staff_headers):
        """PRD §2.4: "When version is supplied, the server compares it to
        the current version of the target resource: if the values differ,
        the request is rejected with ERR_VERSION_CONFLICT and HTTP status
        409, and no state change occurs."

        Claim: a state-changing request with a stale version body field
        → ERR_VERSION_CONFLICT.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=30, sku="PEN")
        order = validate_success(api.create_order(
            wh["id"],
            create_order_payload(
                requested_lines=[{"sku": "PEN", "qty_units": 5}],
                order_number="ORD-OCC", carrier="UPS"),
            staff_headers), 201)
        stale_version = order["version"]
        # Mutate once → version bumps
        validate_success(api.allocate_order(wh["id"], order["id"], staff_headers), 200)
        # Now try cancel with stale version. The cancel endpoint takes no body
        # in the OpenAPI table, but PRD §2.4 says request body MAY include
        # an optional `version` field on every mutating endpoint. We send an
        # explicit body.
        cancel_with_stale = api._request(
            "POST", f"/warehouses/{wh['id']}/orders/{order['id']}/cancel",
            payload={"version": stale_version}, headers=staff_headers,
        )
        validate_error(cancel_with_stale, "ERR_VERSION_CONFLICT")
