"""Optimistic concurrency, race conditions per PRD §2.7 and §2.10."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_completed_ride,
    create_dispute_payload,
    create_driver,
    create_grid,
    create_open_dispute,
    create_requested_ride,
    create_rider,
    create_and_online_driver,
    get_dispute,
    get_grid,
    join_airport_queue,
    list_airport_queue,
    make_driver_headers,
    make_rider_headers,
    patch_grid_payload,
    run_race,
    setup_disputed_ride,
    setup_grid_with_supply,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Optimistic concurrency on PATCH endpoints — PRD §2.7.
# ===========================================================================
class TestOptimisticConcurrency:

    def test_patch_grid_stale_version_rejected(self, api, admin_headers):
        """PRD §2.7: "When version is provided, the server compares it
        against the resource's current version; on a mismatch the
        request is rejected with ERR_VERSION_CONFLICT."
        """
        grid = create_grid()
        v0 = grid["version"]
        # First patch succeeds and bumps version.
        api.patch_grid(grid["id"],
                       patch_grid_payload(version=v0, name="First"),
                       admin_headers)
        # Second patch with stale version v0 is rejected.
        resp = api.patch_grid(
            grid["id"],
            patch_grid_payload(version=v0, name="Second"),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_patch_grid_omitting_version_skips_check(self, api,
                                                    admin_headers):
        """PRD §2.7: "When version is omitted, the server processes
        the mutation without performing the version check."
        """
        grid = create_grid()
        # First patch bumps version.
        api.patch_grid(grid["id"],
                       patch_grid_payload(version=grid["version"],
                                          name="First"),
                       admin_headers)
        # Second patch omits version — succeeds even though we'd be
        # "stale".
        resp = api.patch_grid(
            grid["id"], {"name": "Second"}, admin_headers,
        )
        validate_success(resp)


# ===========================================================================
# Race conditions — PRD §2.10.
# ===========================================================================
class TestConcurrentAssign:

    def test_two_assigns_on_same_ride_one_wins(self, api, admin_headers):
        """PRD §2.10: "Two simultaneous attempts to assign the same
        REQUESTED ride serialize as first-writer-wins on the ride's
        status field. Exactly one assigns; the loser receives
        ERR_INVALID_STATE because the ride is no longer in REQUESTED."
        """
        grid, _ = setup_grid_with_supply(num_drivers=1)
        rider = create_rider()
        ride = create_requested_ride(rider["id"], grid["code"])

        def assign_one():
            return api.assign_ride(ride["id"], admin_headers)

        results = run_race(assign_one, assign_one)
        outcome = assert_exactly_one_succeeds(*results)
        # The loser must be ERR_INVALID_STATE per PRD §2.10.
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)


class TestConcurrentDisputeResolve:

    def test_approve_vs_reject_race_one_wins(self, api,
                                              dispute_ops_headers):
        """PRD §2.10: "Two simultaneous approve and reject calls on
        the same OPEN dispute serialize the same way on the dispute's
        status: exactly one wins, and the loser receives
        ERR_INVALID_STATE."
        """
        scenario = setup_disputed_ride(distance_km=5.0,
                                       requested_refund_cents=200)
        d_id = scenario["dispute"]["id"]

        def do_approve():
            return api.approve_dispute(d_id, dispute_ops_headers)

        def do_reject():
            return api.reject_dispute(d_id, dispute_ops_headers)

        results = run_race(do_approve, do_reject)
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)


class TestConcurrentDisputeCreate:

    def test_duplicate_dispute_create_one_wins(self, api):
        """PRD §2.10: "Two riders trying to file a dispute against the
        same COMPLETED ride at the same time both attempt insertion,
        but the per-ride uniqueness constraint on disputes lets one
        through; the loser receives ERR_DISPUTE_ALREADY_EXISTS."
        """
        from test_helpers import setup_completed_ride_with_known_fare
        scenario = setup_completed_ride_with_known_fare(distance_km=5.0)
        rider_id = scenario["rider"]["id"]
        ride_id = scenario["ride"]["id"]

        def file_dispute():
            return api.create_dispute(
                create_dispute_payload(
                    ride_id=ride_id, requested_refund_cents=100,
                ),
                make_rider_headers(rider_id),
            )

        results = run_race(file_dispute, file_dispute)
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_DISPUTE_ALREADY_EXISTS.value)


class TestConcurrentAirportQueueJoin:

    def test_two_joins_both_succeed_with_distinct_positions(self, api):
        """PRD §2.10: "Two drivers calling the airport-queue join
        endpoint on the same airport grid at the same instant both
        succeed; each receives a distinct sequential position because
        positions are assigned atomically as one plus the current
        maximum position in that grid."
        """
        airport = create_grid(is_airport=True)
        d1 = create_and_online_driver(airport["code"])
        d2 = create_and_online_driver(airport["code"])
        from test_helpers import airport_queue_join_payload

        def join_d1():
            return api.airport_queue_join(
                airport_queue_join_payload(airport["code"]),
                make_driver_headers(d1["id"]),
            )

        def join_d2():
            return api.airport_queue_join(
                airport_queue_join_payload(airport["code"]),
                make_driver_headers(d2["id"]),
            )

        results = run_race(join_d1, join_d2)
        # PRD says BOTH succeed.
        outcome = assert_race_outcome(results, 2, 0)
        # Positions must be distinct.
        positions = []
        for resp in outcome["successes"]:
            body = resp.json()
            data = body.get("data", body)
            positions.append(data["position"])
        assert len(set(positions)) == 2, (
            f"PRD §2.10: positions must be distinct, got {positions}."
        )
        # And dense: {1, 2}.
        assert set(positions) == {1, 2}


class TestConcurrentRideRequest:

    def test_two_rides_one_driver_both_create_only_one_assigns(self, api):
        """PRD §2.10: "Two concurrent ride-requests in a grid that holds
        exactly one available driver are both accepted at the creation
        step; both rides are written in REQUESTED state, but only one
        will progress to ASSIGNED (the first request wins the
        assignment via the driver-selection policy of §3.3). The losing
        ride remains in REQUESTED until a new driver becomes available
        — no error is returned at creation time."
        """
        grid, _ = setup_grid_with_supply(num_drivers=1)
        rider1 = create_rider()
        rider2 = create_rider()
        from test_helpers import create_ride_payload

        def request_a():
            return api.create_ride(
                create_ride_payload(grid["code"], distance_km=3.0),
                make_rider_headers(rider1["id"]),
            )

        def request_b():
            return api.create_ride(
                create_ride_payload(grid["code"], distance_km=3.0),
                make_rider_headers(rider2["id"]),
            )

        results = run_race(request_a, request_b)
        # Both must succeed at creation per PRD §2.10.
        outcome = assert_race_outcome(results, 2, 0)
        # Now exactly one /assign attempt can succeed.
        from test_helpers import TEST_USERS
        admin_h = TEST_USERS["platform_admin_headers"]
        ride_ids = []
        for resp in outcome["successes"]:
            data = resp.json().get("data", {})
            ride_ids.append(data["id"])

        def assign_first():
            return api.assign_ride(ride_ids[0], admin_h)

        def assign_second():
            return api.assign_ride(ride_ids[1], admin_h)

        assign_results = run_race(assign_first, assign_second)
        # Only one ride can be assigned because there's only one
        # available driver. The other gets ERR_NO_DRIVERS_AVAILABLE.
        success_count = sum(
            1 for r in assign_results if 200 <= r.status_code < 300
        )
        assert success_count == 1, (
            f"PRD §2.10: only one assign succeeds with one driver. Got "
            f"{success_count} successes among {[r.status_code for r in assign_results]}."
        )
        for r in assign_results:
            if not (200 <= r.status_code < 300):
                validate_error(
                    r, ApiErrorId.ERR_NO_DRIVERS_AVAILABLE.value,
                )
