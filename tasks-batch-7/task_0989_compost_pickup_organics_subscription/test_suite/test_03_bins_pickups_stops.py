"""Bin fleet dimensions, pickup generation, completion gating, listing and
pagination.

Covers PRD §2.3 (pagination), §3.3 (bins, stop generation), §3.4 (completion).
"""
from test_helpers import (
    ApiErrorId,
    assert_bin,
    assert_pickup,
    complete_pickup,
    create_bins,
    generate_and_get_pickups,
    generate_stops,
    get_bin,
    list_pickups_for_subscription,
    miss_pickup,
    setup_active_subscription,
    setup_completed_pickup,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPickupGeneration:
    def test_pickup_initial_state_scheduled(self, api):
        """PRD §3.3: "the system creates a **Pickup Event** in `SCHEDULED`
        status with its `subscription_id`, `route_id`, and `service_date` set."
        PRD §3.8: "each pickup contributes its `final_kg` once weighed and its
        `estimated_kg` otherwise" — before weighing no `final_kg` exists.

        Design: Corner/state_machines/pickup_initial_state_scheduled
        """
        env = setup_active_subscription(bin_count=1)
        pickups = generate_and_get_pickups(
            env["route"]["id"], env["subscription"]["id"], ["2026-06-01"]
        )
        assert len(pickups) == 1
        pickup = pickups[0]
        assert_pickup(pickup)
        assert pickup["status"] == "SCHEDULED"
        assert pickup["service_date"] == "2026-06-01"
        assert pickup.get("final_kg") is None
        assert pickup.get("collected_bin_id") is None
        assert pickup.get("replacement_bin_id") is None

    def test_generate_stops_replay_is_idempotent(self, api):
        """PRD §3.3: "Subscriptions are processed in ascending order of their
        own creation time, and generation is idempotent: subscriptions already
        covered for the date are skipped."

        Design: Corner/endpoints/generate_stops_replay_is_idempotent
        """
        env = setup_active_subscription(bin_count=1)
        route_id = env["route"]["id"]
        sub_id = env["subscription"]["id"]
        first = generate_stops(route_id, "2026-06-01")
        assert first["created_count"] == 1
        replay = generate_stops(route_id, "2026-06-01")
        assert replay["created_count"] == 0
        pickups = list_pickups_for_subscription(sub_id)
        assert len(pickups) == 1

    def test_generate_stops_weekday_mismatch_rejected(self, api, ops_headers):
        """PRD §3.3: "The weekday of that date must match the route's
        `weekday`, otherwise the request is rejected with
        `ERR_SERVICE_DATE_WEEKDAY_MISMATCH`."

        Design: Corner/validations/generate_stops_weekday_mismatch_returns_error
        """
        env = setup_active_subscription(bin_count=1)
        # 2026-06-02 is a Tuesday; the route serves MON.
        resp = api.generate_stops(
            env["route"]["id"], {"service_date": "2026-06-02"}, ops_headers
        )
        validate_error(resp, ApiErrorId.ERR_SERVICE_DATE_WEEKDAY_MISMATCH)
        pickups = list_pickups_for_subscription(env["subscription"]["id"])
        assert pickups == []


class TestPickupCompletionGates:
    def test_complete_missed_pickup_rejected(self, api, driver_headers):
        """PRD §3.4: "Only a pickup still in `SCHEDULED` may be completed,
        otherwise the request fails with `ERR_PICKUP_NOT_ACTIONABLE`."
        PRD §3.4: "Marking a pickup missed moves it from `SCHEDULED` to
        `MISSED`, recording driver fault: the week is not billed for that stop,
        and the pickup's `version` increments."

        Design: Corner/state_machines/complete_missed_pickup_rejected
        """
        env = setup_active_subscription(bin_count=2)
        pickup = generate_and_get_pickups(
            env["route"]["id"], env["subscription"]["id"], ["2026-06-01"]
        )[0]
        miss_pickup(pickup["id"])
        resp = api.complete_pickup(pickup["id"], {"fullness_pct": 0.5}, driver_headers)
        validate_error(resp, ApiErrorId.ERR_PICKUP_NOT_ACTIONABLE)
        subscriber = env["subscriber"]
        from test_helpers import get_subscriber
        assert get_subscriber(subscriber["id"])["credit_balance_cents"] == 0


class TestBinWash:
    def test_wash_clean_bin_returns_invalid_state(self, api, ops_headers):
        """PRD §3.3: "Washing is an `OperationsManager` action that requires
        the bin to be `IN_DEPOT` with condition `NEEDS_WASH` — any other
        combination is rejected with `ERR_INVALID_STATE` — and it sets the
        condition to `CLEAN`, leaves the status untouched, and increments the
        bin's `version`."

        Design: Corner/state_machines/wash_clean_bin_returns_invalid_state
        """
        bins = create_bins(1)
        resp = api.wash_bin(bins[0]["id"], ops_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_bin(bins[0]["id"])["condition"] == "CLEAN"


class TestBinParallelDimensions:
    def test_swap_flips_both_dimensions_and_selector_requires_clean(self, api, driver_headers):
        """PRD §3.3: "A bin evolves along two parallel dimensions: its `status`
        (`IN_DEPOT` or `AT_CUSTOMER`) and its `condition` (`CLEAN` or
        `NEEDS_WASH`) move independently, with two binding rules — only `CLEAN`
        bins may leave the depot, and any bin returning from a customer arrives
        with `NEEDS_WASH`."
        PRD §3.4: "If no such bin exists the completion is rejected with
        `ERR_NO_BIN_AVAILABLE` and nothing changes — the operation is atomic."

        Design: Difficulty/non_linear_state_machine/bin_parallel_status_condition_dimensions
        """
        env = setup_active_subscription(bin_count=2)
        bin1, bin2 = env["bins"][0]["id"], env["bins"][1]["id"]
        pickups = generate_and_get_pickups(
            env["route"]["id"], env["subscription"]["id"], ["2026-06-01", "2026-06-08"]
        )
        pk1, pk2 = pickups[0]["id"], pickups[1]["id"]

        complete_pickup(pk1, 0.5)
        b1 = get_bin(bin1)
        b2 = get_bin(bin2)
        assert (b1["status"], b1["condition"]) == ("IN_DEPOT", "NEEDS_WASH")
        assert (b2["status"], b2["condition"]) == ("AT_CUSTOMER", "CLEAN")

        # The only depot bin is dirty: the swap cannot select it.
        resp = api.complete_pickup(pk2, {"fullness_pct": 0.5}, driver_headers)
        validate_error(resp, ApiErrorId.ERR_NO_BIN_AVAILABLE)
        from test_helpers import get_pickup
        assert get_pickup(pk2)["status"] == "SCHEDULED"

    def test_wash_restores_condition_not_status_then_swap_cycles(self, api):
        """PRD §3.3: "it sets the condition to `CLEAN`, leaves the status
        untouched, and increments the bin's `version`."
        PRD §3.4: "The `collected_bin_id` records the subscription's outgoing
        bin, which returns to `IN_DEPOT` with condition `NEEDS_WASH` and its
        `current_subscription_id` cleared; the `replacement_bin_id` records the
        selected clean bin, which moves to `AT_CUSTOMER` with its
        `current_subscription_id` set to the served subscription."

        Design: Difficulty/non_linear_state_machine/bin_parallel_status_condition_dimensions
        """
        env = setup_active_subscription(bin_count=2)
        bin1, bin2 = env["bins"][0]["id"], env["bins"][1]["id"]
        pickups = generate_and_get_pickups(
            env["route"]["id"], env["subscription"]["id"], ["2026-06-01", "2026-06-08"]
        )
        pk1, pk2 = pickups[0]["id"], pickups[1]["id"]
        complete_pickup(pk1, 0.5)

        before_wash = get_bin(bin1)
        from test_helpers import TEST_USERS
        washed = validate_success(
            api.wash_bin(bin1, TEST_USERS["ops_headers"])
        )
        assert_bin(washed)
        assert washed["condition"] == "CLEAN"
        assert washed["status"] == "IN_DEPOT"
        assert washed["version"] == before_wash["version"] + 1

        complete_pickup(pk2, 0.5)
        assert get_bin(bin1)["status"] == "AT_CUSTOMER"
        b2 = get_bin(bin2)
        assert (b2["status"], b2["condition"]) == ("IN_DEPOT", "NEEDS_WASH")


class TestPickupListing:
    def test_pickups_filter_and_pagination(self, api, ops_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter tells the server how many items to skip and defaults
        to 0."
        PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §3.3: "Pickup events can be browsed through a list endpoint with
        optional filters on `subscription_id`, `route_id`, `collected_bin_id`,
        `replacement_bin_id`, and `status`, sorted by creation time ascending,
        and individual pickups can be read."

        Design: Corner/endpoints/pickups_list_filter_and_pagination
        """
        env = setup_active_subscription(bin_count=1)
        sub_id = env["subscription"]["id"]
        pickups = generate_and_get_pickups(
            env["route"]["id"], sub_id, ["2026-06-01", "2026-06-08", "2026-06-15"]
        )
        pk1 = pickups[0]["id"]
        miss_pickup(pk1)

        page1, meta1 = validate_paginated(
            api.list_pickups(
                ops_headers, params={"subscription_id": sub_id, "limit": 2, "offset": 0}
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_pickups(
                ops_headers, params={"subscription_id": sub_id, "limit": 2, "offset": 2}
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        missed, meta3 = validate_paginated(
            api.list_pickups(
                ops_headers, params={"subscription_id": sub_id, "status": "MISSED"}
            )
        )
        assert [p["id"] for p in missed] == [pk1]
        assert meta3["total_count"] == 1
