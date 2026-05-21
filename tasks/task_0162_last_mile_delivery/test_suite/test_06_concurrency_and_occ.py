"""Optimistic concurrency control (PRD §2.10) and the four high-leverage
races PRD §3.6 explicitly serializes.

PRD §3.6 names a specific error_id for each race; tests assert that
error_id on the loser per the PRD prose.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    add_stop,
    api_client,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    check_in_driver,
    create_driver,
    create_parcel,
    create_route,
    deliver_signed,
    dispatch_route,
    make_customer_headers,
    make_driver_headers,
    move_clock_into_window,
    run_race,
    setup_baseline,
    setup_three_sorted_parcels_one_route,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    walk_parcel_to_out_for_delivery,
    walk_parcel_to_sorted,
    with_version,
)


# ---------------------------------------------------------------------------
# OCC — PRD §2.10
# ---------------------------------------------------------------------------
class TestOptimisticConcurrencyControl:

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.10: 'When version is supplied, the server compares
        it to the current version of the resource and, on mismatch,
        rejects the request with ERR_VERSION_CONFLICT without applying
        any side effect.'"""
        base = setup_baseline()
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        stale_version = parcel["version"]
        # Apply a mutation (no version) to bump version.
        validate_success(api.patch_parcel(
            parcel["id"], {"signature_required": True},
            TEST_USERS["dispatcher_headers"],
        ), 200)
        # Now the parcel version is stale_version + 1. Submit with
        # stale.
        res = api.patch_parcel(
            parcel["id"], with_version(
                {"weight_kg": 5.0}, version=stale_version,
            ), TEST_USERS["dispatcher_headers"],
        )
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_patch_with_current_version_succeeds(self, api):
        """PRD §2.10: 'When version is supplied, the server compares
        it to the current version of the resource' — matching version
        proceeds normally."""
        base = setup_baseline()
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        res = api.patch_parcel(
            parcel["id"],
            with_version({"weight_kg": 4.5}, version=parcel["version"]),
            TEST_USERS["dispatcher_headers"],
        )
        updated = validate_success(res, 200)
        assert updated["weight_kg"] == pytest.approx(4.5, abs=0.001)

    def test_patch_without_version_proceeds_unconditionally(self, api):
        """PRD §2.10: 'When version is omitted, the server processes
        the mutation unconditionally — there is no implicit OCC
        check.'"""
        base = setup_baseline()
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        # Mutate once to bump version, then PATCH again without
        # supplying version.
        validate_success(api.patch_parcel(
            parcel["id"], {"signature_required": True},
            TEST_USERS["dispatcher_headers"],
        ), 200)
        res = api.patch_parcel(
            parcel["id"], {"weight_kg": 4.0},
            TEST_USERS["dispatcher_headers"],
        )
        validate_success(res, 200)


# ---------------------------------------------------------------------------
# Race 1 — two stops for the same parcel
# ---------------------------------------------------------------------------
class TestParcelAlreadyOnRouteRace:

    def test_two_simultaneous_stop_adds_same_parcel(self, api):
        """PRD §3.6: 'Two simultaneous attempts to load the same parcel
        onto two different routes serialize on the uniqueness of
        RouteStop.parcel_id while the parcel is in ON_VEHICLE.
        Exactly one loader wins; the loser receives
        ERR_PARCEL_ALREADY_ON_ROUTE.'"""
        base = setup_baseline()
        parcel = walk_parcel_to_sorted(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        driver2 = create_driver(home_center_id=base["center"]["id"])
        route_a = create_route(base["center"]["id"], base["driver"]["id"])
        route_b = create_route(base["center"]["id"], driver2["id"])

        results = run_race(
            lambda: api.create_stop(
                route_a["id"], {"parcel_id": parcel["id"]},
                TEST_USERS["dispatcher_headers"],
            ),
            lambda: api.create_stop(
                route_b["id"], {"parcel_id": parcel["id"]},
                TEST_USERS["dispatcher_headers"],
            ),
        )
        outcomes = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcomes["failures"][0]
        # PRD §3.6 explicitly names ERR_PARCEL_ALREADY_ON_ROUTE for
        # the loser.
        validate_error(loser, "ERR_PARCEL_ALREADY_ON_ROUTE")


# ---------------------------------------------------------------------------
# Race 2 — two close attempts
# ---------------------------------------------------------------------------
class TestRouteCloseRace:

    def test_two_simultaneous_route_closes(self, api):
        """PRD §3.6: 'Two drivers trying to close the same route
        serialize on Route.status. The first writer wins; the second
        writer observes a route already in CLOSED and receives
        ERR_INVALID_STATE.'"""
        ctx = walk_parcel_to_out_for_delivery()
        # Bring stops to terminal so close is admissible.
        deliver_signed(ctx["parcel"], ctx["stop"], ctx["driver"]["id"])
        # Fire two close requests in parallel.
        results = run_race(
            lambda: api.close_route(
                ctx["route"]["id"],
                make_driver_headers(ctx["driver"]["id"]),
            ),
            lambda: api.close_route(
                ctx["route"]["id"],
                make_driver_headers(ctx["driver"]["id"]),
            ),
        )
        outcomes = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcomes["failures"][0]
        validate_error(loser, "ERR_INVALID_STATE")


# ---------------------------------------------------------------------------
# Race 3 — cancel-route vs add-stop on the same PLANNED route
# ---------------------------------------------------------------------------
class TestCancelVsAddStopRace:

    def test_cancel_vs_add_stop_one_succeeds_one_fails(self, api):
        """PRD §3.6: 'A cancel-route and an add-stop arriving
        simultaneously on a planned route serialize on Route.status.
        The first writer wins. If the cancel wins, the add-stop sees
        a non-planned route and receives ERR_ROUTE_NOT_PLANNED. If
        the add-stop wins, the cancel still completes because
        cancelling a planned route is admissible regardless of
        stop_count.'"""
        base = setup_baseline()
        parcel = walk_parcel_to_sorted(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        route = create_route(base["center"]["id"], base["driver"]["id"])
        results = run_race(
            lambda: api.cancel_route(
                route["id"], TEST_USERS["dispatcher_headers"],
            ),
            lambda: api.create_stop(
                route["id"], {"parcel_id": parcel["id"]},
                TEST_USERS["dispatcher_headers"],
            ),
        )
        # Per PRD: both branches admit a different outcome — if cancel
        # wins, add-stop fails ERR_ROUTE_NOT_PLANNED; if add-stop wins,
        # cancel still completes. So at least one succeeds, and any
        # failure must be ERR_ROUTE_NOT_PLANNED.
        successes = [r for r in results if 200 <= r.status_code < 300]
        failures = [r for r in results if r.status_code >= 400]
        assert len(successes) >= 1, \
            "PRD §3.6: at least one operation must succeed in this race"
        for f in failures:
            validate_error(f, "ERR_ROUTE_NOT_PLANNED")
