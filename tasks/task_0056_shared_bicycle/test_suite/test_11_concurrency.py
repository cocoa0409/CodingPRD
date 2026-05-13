"""Concurrency races serialized by PRD §3.13.

PRD §3.13 names five races and pins outcomes:
- two unlocks on same bike → exactly one wins; loser ERR_BIKE_NOT_AVAILABLE
- end vs. void → exactly one wins; loser ERR_RIDE_NOT_ACTIVE
- two assigns on same OPEN WO → exactly one wins; loser ERR_WORKORDER_NOT_OPEN
- PATCH /bikes with stale version → ERR_VERSION_CONFLICT
- two transfer dispatches on same bike → exactly one wins;
  loser ERR_BIKE_NOT_AVAILABLE_FOR_TRANSFER
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assign_workorder_payload,
    create_bike,
    create_funded_rider,
    create_ride_payload,
    create_transfer_payload,
    create_workorder,
    create_workorder_payload,
    end_ride_payload,
    get_bike,
    make_rider_headers,
    patch_bike_payload,
    run_race,
    setup_basic_ride_scenario,
    setup_region_at_posture,
    setup_region_with_bikes,
    shelf_bike_on,
    start_ride,
    validate_error,
    validate_success,
    validate_error_is_one_of,
    ADMIN,
    OPERATOR,
)


class TestUnlockRace:
    """PRD §3.13: 'Two riders attempting to unlock the same AVAILABLE
    bike at the same moment: at most one ride is created, the bike
    transitions AVAILABLE → IN_USE exactly once, and the loser sees
    the post-state (bike no longer AVAILABLE) and is rejected with
    ERR_BIKE_NOT_AVAILABLE (HTTP 409).'"""

    def test_two_riders_unlock_same_bike_one_wins(self, api):
        region, bikes = setup_region_with_bikes(num_bikes=1)
        rider_a = create_funded_rider()
        rider_b = create_funded_rider()
        bike = bikes[0]

        def call_a():
            return api.create_ride(
                create_ride_payload(rider_id=rider_a["id"],
                                    bike_id=bike["id"]),
                make_rider_headers(rider_a["id"]),
            )

        def call_b():
            return api.create_ride(
                create_ride_payload(rider_id=rider_b["id"],
                                    bike_id=bike["id"]),
                make_rider_headers(rider_b["id"]),
            )

        results = run_race(call_a, call_b)
        successes = [r for r in results if 200 <= r.status_code < 300]
        failures = [r for r in results if r.status_code >= 400]
        assert len(successes) == 1, (
            "PRD §3.13: 'at most one ride is created'"
        )
        assert len(failures) == 1
        # PRD names the loser's error_id explicitly.
        validate_error(
            failures[0], ApiErrorId.ERR_BIKE_NOT_AVAILABLE.value, 409,
        )
        bike_after = get_bike(bike["id"])
        assert bike_after["status"] == "IN_USE"


class TestEndVsVoidRace:
    """PRD §3.13: 'A rider's end-of-ride and an admin's void on the
    same ACTIVE ride: exactly one succeeds, and the loser ... is
    rejected with ERR_RIDE_NOT_ACTIVE (HTTP 409).'"""

    def test_end_versus_void_exactly_one_succeeds(self, api):
        ctx = setup_basic_ride_scenario(wallet_balance_cents=10000)
        ride = start_ride(ctx["rider"], ctx["bike"])
        advance_clock(5)

        def call_end():
            return api.end_ride(
                ride["id"],
                end_ride_payload(end_lat=10.0, end_lng=10.0),
                make_rider_headers(ctx["rider"]["id"]),
            )

        def call_void():
            return api.void_ride(ride["id"], ADMIN)

        results = run_race(call_end, call_void)
        successes = [r for r in results if 200 <= r.status_code < 300]
        failures = [r for r in results if r.status_code >= 400]
        assert len(successes) == 1, (
            "PRD §3.13: 'exactly one succeeds'"
        )
        assert len(failures) == 1
        validate_error(failures[0], ApiErrorId.ERR_RIDE_NOT_ACTIVE.value, 409)


class TestAssignWorkOrderRace:
    """PRD §3.13: 'Two operators attempting to assign the same OPEN
    work order: exactly one assignment lands, and the loser sees the
    post-state and is rejected with ERR_WORKORDER_NOT_OPEN.'"""

    def test_two_assigns_one_wins(self, api):
        region, bikes = setup_region_with_bikes(num_bikes=1)
        wo = create_workorder(bike_id=bikes[0]["id"])

        def call_a():
            return api.assign_workorder(
                wo["id"],
                assign_workorder_payload(assigned_operator_id="op-A"),
                OPERATOR,
            )

        def call_b():
            return api.assign_workorder(
                wo["id"],
                assign_workorder_payload(assigned_operator_id="op-B"),
                OPERATOR,
            )

        results = run_race(call_a, call_b)
        successes = [r for r in results if 200 <= r.status_code < 300]
        failures = [r for r in results if r.status_code >= 400]
        assert len(successes) == 1
        assert len(failures) == 1
        validate_error(
            failures[0], ApiErrorId.ERR_WORKORDER_NOT_OPEN.value, 409,
        )


class TestOcc:
    """PRD §3.13: 'A bike-update attempt with a stale version in the
    body: the stale write is rejected with ERR_VERSION_CONFLICT.'"""

    def test_stale_patch_version_rejected(self, api):
        region, bikes = setup_region_with_bikes(num_bikes=1)
        bike = bikes[0]
        v0 = bike["version"]
        # First patch: bump version
        from test_helpers import patch_bike
        patch_bike(bike["id"], battery_pct=80)
        # Stale patch with old version
        resp = api.patch_bike(
            bike["id"],
            patch_bike_payload(battery_pct=70, version=v0),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value, 409)


class TestTransferDispatchRace:
    """PRD §3.13: 'Two transfer dispatches that reference the same
    bike_id: only the first dispatch can move the bike — the second
    observes the bike's region_id and shelf_state already updated and
    fails with ERR_BIKE_NOT_AVAILABLE_FOR_TRANSFER.'"""

    def test_dispatch_race_on_same_bike(self, api):
        # Build a HIGH source + a LOW destination so REPLENISH plan
        # can dispatch. Then build two PLANNED transfers using the
        # same bike id, and race their dispatches.
        r_low, _ = setup_region_at_posture(
            "LOW", deployment_quota=20,
            low_density_threshold=4, high_density_threshold=10,
            available_count_override=2,
        )
        r_src, src_bikes = setup_region_at_posture(
            "HIGH", deployment_quota=20,
            low_density_threshold=0, high_density_threshold=5,
            available_count_override=6,
        )
        bike_id = src_bikes[0]["id"]
        from test_helpers import create_transfer
        t1 = create_transfer(
            from_region_id=r_src["id"], to_region_id=r_low["id"],
            bike_ids=[bike_id],
        )
        t2 = create_transfer(
            from_region_id=r_src["id"], to_region_id=r_low["id"],
            bike_ids=[bike_id],
        )

        def disp_a():
            return api.dispatch_transfer(t1["id"], OPERATOR)

        def disp_b():
            return api.dispatch_transfer(t2["id"], OPERATOR)

        results = run_race(disp_a, disp_b)
        successes = [r for r in results if 200 <= r.status_code < 300]
        failures = [r for r in results if r.status_code >= 400]
        assert len(successes) == 1, (
            "PRD §3.13: 'only the first dispatch can move the bike'"
        )
        assert len(failures) == 1
        validate_error(
            failures[0],
            ApiErrorId.ERR_BIKE_NOT_AVAILABLE_FOR_TRANSFER.value,
            409,
        )
