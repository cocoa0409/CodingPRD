"""Subscription creation rules, initial state, plan-change OCC, capacity, and
the pause/resume cycle.

Covers PRD §2.8 (OCC), §2.10 (validation order), §3.2 (creation checks,
plan-change), §3.5 (pause/resume windows).
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_subscription,
    cancel_subscription,
    create_bins,
    create_plan_res,
    create_route,
    create_subscriber,
    create_subscription,
    create_subscription_payload,
    generate_stops,
    get_bin,
    get_route,
    get_subscription,
    list_pickups_for_subscription,
    pause_subscription,
    resume_subscription,
    setup_active_subscription,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSubscriptionCreation:
    def test_missing_plan_id_returns_invalid_request(self, api, ops_headers):
        """PRD §2.10: "Third, request-body shape: required fields present, enums
        valid, ranges valid — `fullness_pct` between zero and one inclusive,
        `bags` at least one, `pause_end` later than `pause_start`,
        `week_start_date` a Monday, an adjustment's `amount_cents` nonzero —
        otherwise `ERR_INVALID_REQUEST`. Fourth, existence: every identifier
        referenced in the path and body — `plan_id`, `route_id`,
        `subscriber_id`, `new_plan_id`, and any path `id` — must resolve to an
        existing entity, otherwise `ERR_NOT_FOUND`" — the shape check precedes
        existence, so a missing plan_id reports 400 even though the supplied
        route_id would also fail.

        Design: Corner/entities/create_subscription_missing_required_plan_id_returns_invalid_request
        """
        sub = create_subscriber()
        resp = api.create_subscription(
            {
                "subscriber_id": sub["id"],
                "route_id": NON_EXISTENT_UUID,
                "start_date": "2026-05-01",
            },
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_subscriber_type_mismatch_returns_invalid_request(self, api, ops_headers):
        """PRD §3.2: "The plan's `subscriber_type` must equal the subscriber's
        own `subscriber_type`, otherwise the request is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_subscription_type_mismatch_returns_invalid_request
        """
        plan = create_plan_res(code="COM", name="Commercial", subscriber_type="COMMERCIAL",
                               bin_type="BIN_240L", weekly_price_cents=0,
                               metered_base_cents=3000, per_kg_rate_cents=7,
                               included_kg_per_week=40, credit_rate_cents_per_kg=5,
                               skip_allowance_per_quarter=4)
        route = create_route()
        sub = create_subscriber("RESIDENTIAL")
        resp = api.create_subscription(
            create_subscription_payload(sub["id"], plan["id"], route["id"]), ops_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_unknown_route_returns_not_found(self, api, ops_headers):
        """PRD §2.10: "Fourth, existence: every identifier referenced in the
        path and body — `plan_id`, `route_id`, `subscriber_id`, `new_plan_id`,
        and any path `id` — must resolve to an existing entity, otherwise
        `ERR_NOT_FOUND`; path identifiers are resolved left to right as they
        appear in the URL, and the first unresolvable identifier produces the
        404."

        Design: Corner/entities/create_subscription_unknown_route_returns_not_found
        """
        plan = create_plan_res()
        sub = create_subscriber()
        resp = api.create_subscription(
            create_subscription_payload(sub["id"], plan["id"], NON_EXISTENT_UUID),
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_subscription_initial_state_active(self, api):
        """PRD §3.2: "The subscription itself begins with `service_status`
        `ACTIVE`, a `strike_count` of zero, `skips_used_this_quarter` at zero,
        an empty `pause_windows` list, and `current_quarter` left to be stamped
        lazily at the first skip accounting."

        Design: Corner/state_machines/subscription_initial_state_active
        """
        env = setup_active_subscription(bin_count=1)
        data = validate_success(api.get_subscription(env["subscription"]["id"], TEST_OPS))
        assert_subscription(data)
        assert data["service_status"] == "ACTIVE"
        assert data["strike_count"] == 0
        assert data["skips_used_this_quarter"] == 0
        assert data["pause_windows"] == []

    def test_empty_depot_returns_no_bin_available(self, api, ops_headers):
        """PRD §3.2: "if the depot runs short, creation fails with
        `ERR_NO_BIN_AVAILABLE`."

        Design: Corner/validations/subscribe_with_empty_depot_returns_no_bin_available
        """
        plan = create_plan_res()
        route = create_route()
        sub = create_subscriber()
        resp = api.create_subscription(
            create_subscription_payload(sub["id"], plan["id"], route["id"]), ops_headers
        )
        validate_error(resp, ApiErrorId.ERR_NO_BIN_AVAILABLE)
        data, meta = validate_paginated(
            api.list_subscriptions(ops_headers, params={"subscriber_id": sub["id"]})
        )
        assert data == [] and meta["total_count"] == 0


class TestPlanChange:
    def test_occ_fresh_version_succeeds_and_stale_replay_rejected(self, api, ops_headers):
        """PRD §2.8: "If that value does not match the subscription's current
        `version` — because another accepted plan-change replaced the plan, or a
        pause, resume, or cancellation advanced the row since the caller read it
        — the caller's view is stale and the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.2: "On success the `plan_id` is replaced and the subscription's
        `version` increments by one."

        Design: Corner/complexity_layers/plan_change_occ_stale_and_fresh
        """
        plan1 = create_plan_res()
        plan2 = create_plan_res(code="RES2", name="Residential Plus",
                                weekly_price_cents=1500, credit_rate_cents_per_kg=12,
                                skip_allowance_per_quarter=3)
        route = create_route()
        create_bins(1)
        sub = create_subscriber()
        subscription = create_subscription(sub["id"], plan1["id"], route["id"])
        observed_version = subscription["version"]

        changed = validate_success(
            api.plan_change(
                subscription["id"],
                {"new_plan_id": plan2["id"],
                 "expected_subscription_version": observed_version},
                ops_headers,
            )
        )
        assert changed["plan_id"] == plan2["id"]
        assert changed["version"] == observed_version + 1

        replay = api.plan_change(
            subscription["id"],
            {"new_plan_id": plan1["id"],
             "expected_subscription_version": observed_version},
            ops_headers,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
        after = get_subscription(subscription["id"])
        assert after["plan_id"] == plan2["id"]

    def test_plan_change_to_fewer_bins_blocked(self, api, ops_headers):
        """PRD §3.2: "it must share the subscriber's `subscriber_type` while
        including at least as many bins as are currently assigned to the
        subscription; crossing the residential/commercial line or downsizing
        below the assigned bin count is rejected with
        `ERR_PLAN_DOWNGRADE_BLOCKED`."

        Design: Corner/validations/plan_change_to_smaller_bin_plan_returns_downgrade_blocked
        """
        env = setup_active_subscription(bin_count=1)
        plan0 = create_plan_res(code="RES0", name="No Bin", included_bins=0,
                                weekly_price_cents=900)
        sub = env["subscription"]
        resp = api.plan_change(
            sub["id"],
            {"new_plan_id": plan0["id"],
             "expected_subscription_version": sub["version"]},
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_DOWNGRADE_BLOCKED)
        after = get_subscription(sub["id"])
        assert after["plan_id"] == env["plan"]["id"]
        assert after["version"] == sub["version"], "version is not consumed on rejection"

    def test_plan_change_on_cancelled_subscription_state_conflict(self, api, ops_headers):
        """PRD §3.2: "Attempting a plan-change on a subscription that is not
        `ACTIVE` — including a terminal `CANCELLED` one — is rejected with
        `ERR_SUBSCRIPTION_STATE_CONFLICT`."

        Design: Corner/state_machines/terminal_subscription_rejects_plan_change
        """
        env = setup_active_subscription(bin_count=1)
        plan2 = create_plan_res(code="RES2", name="Residential Plus",
                                weekly_price_cents=1500, credit_rate_cents_per_kg=12,
                                skip_allowance_per_quarter=3)
        sub_id = env["subscription"]["id"]
        cancel_subscription(sub_id)
        final_version = get_subscription(sub_id)["version"]
        resp = api.plan_change(
            sub_id,
            {"new_plan_id": plan2["id"],
             "expected_subscription_version": final_version},
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_STATE_CONFLICT)

    def test_cancel_already_cancelled_returns_state_conflict(self, api, ops_headers):
        """PRD §3.5: "`CANCELLED` is terminal."
        PRD §2.10: "Sixth, state gates: the target resource must be in a valid
        from-state for the operation, otherwise the operation-specific conflict —
        `ERR_SUBSCRIPTION_STATE_CONFLICT`, `ERR_SUBSCRIPTION_NOT_ACTIVE`,
        `ERR_PICKUP_NOT_ACTIONABLE`, `ERR_TAG_NOT_RESOLVABLE`,
        `ERR_REDEMPTION_NOT_FULFILLABLE`, `ERR_INVOICE_NOT_PAYABLE`, or
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_already_cancelled_subscription_returns_state_conflict
        """
        env = setup_active_subscription(bin_count=1)
        sub_id = env["subscription"]["id"]
        cancel_subscription(sub_id)
        resp = api.cancel_subscription(sub_id, ops_headers)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_STATE_CONFLICT)
        assert get_subscription(sub_id)["service_status"] == "CANCELLED"


class TestRouteCapacity:
    def test_second_subscription_at_capacity_rejected(self, api, ops_headers):
        """PRD §3.2: "Second, the route must have a free weekly slot — its
        `active_subscriptions_count` must be below `max_stops` — otherwise
        creation fails with `ERR_ROUTE_CAPACITY`; once the subscription is
        active the count is recomputed."

        Design: Difficulty/resource_temporal_overlap/route_capacity_aggregate_weekly_slot
        """
        plan = create_plan_res()
        route = create_route(max_stops=1)
        create_bins(2)
        sub_a = create_subscriber(email="a@x.com")
        sub_b = create_subscriber(email="b@x.com", full_name="Sub B", address="2 B St")
        create_subscription(sub_a["id"], plan["id"], route["id"])
        resp = api.create_subscription(
            create_subscription_payload(sub_b["id"], plan["id"], route["id"]),
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY)

    def test_capacity_frees_after_cancel(self, api, ops_headers):
        """PRD §3.2: "Second, the route must have a free weekly slot — its
        `active_subscriptions_count` must be below `max_stops` — otherwise
        creation fails with `ERR_ROUTE_CAPACITY`; once the subscription is
        active the count is recomputed."
        PRD §3.5: "From `ACTIVE` or `PAUSED`, cancelling transitions all of the
        subscription's `SCHEDULED` pickups to `CANCELLED_SYSTEM` and returns
        every assigned bin to the depot — `status` to `IN_DEPOT`, `condition`
        to `NEEDS_WASH`, `current_subscription_id` cleared — then increments
        the subscription's `version`."

        Design: Difficulty/resource_temporal_overlap/route_capacity_aggregate_weekly_slot
        """
        plan = create_plan_res()
        route = create_route(max_stops=1)
        bins = create_bins(2)
        sub_a = create_subscriber(email="a@x.com")
        sub_b = create_subscriber(email="b@x.com", full_name="Sub B", address="2 B St")
        subs_a = create_subscription(sub_a["id"], plan["id"], route["id"])
        cancel_subscription(subs_a["id"])
        subs_b = validate_success(
            api.create_subscription(
                create_subscription_payload(sub_b["id"], plan["id"], route["id"]),
                ops_headers,
            ),
            201,
        )
        assert subs_b["service_status"] == "ACTIVE"
        returned = get_bin(bins[0]["id"])
        assert returned["status"] == "IN_DEPOT"
        assert returned["condition"] == "NEEDS_WASH"
        assert get_route(route["id"])["active_subscriptions_count"] == 1


class TestPauseResumeCycle:
    def test_generate_stops_respects_pause_state(self, api, ops_headers):
        """PRD §3.3: "For every subscription with `service_status` `ACTIVE`,
        assigned to this route, whose `start_date` falls on or before the
        service date, and that has no pickup already existing for that date,
        the system creates a **Pickup Event** in `SCHEDULED` status with its
        `subscription_id`, `route_id`, and `service_date` set."

        Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
        """
        env = setup_active_subscription(bin_count=1)
        sub_id = env["subscription"]["id"]
        route_id = env["route"]["id"]
        pause_subscription(sub_id, "2026-06-01", "2026-06-08")
        paused_gen = generate_stops(route_id, "2026-06-01")
        assert paused_gen["created_count"] == 0
        resume_subscription(sub_id)
        active_gen = generate_stops(route_id, "2026-06-01")
        assert active_gen["created_count"] == 1
        pickups = list_pickups_for_subscription(sub_id)
        assert len(pickups) == 1 and pickups[0]["status"] == "SCHEDULED"

    def test_pause_resume_loops_indefinitely(self, api):
        """PRD §3.5: "On success the window is appended to `pause_windows` (the
        list is append-only), every `SCHEDULED` pickup of the subscription whose
        `service_date` falls inside the window transitions to
        `CANCELLED_SYSTEM`, and the subscription's `version` increments by one."
        PRD §3.5: "The `ACTIVE`–`PAUSED` pair loops indefinitely."

        Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
        """
        env = setup_active_subscription(bin_count=1)
        sub_id = env["subscription"]["id"]
        pause_subscription(sub_id, "2026-06-01", "2026-06-08")
        resume_subscription(sub_id)
        pause_subscription(sub_id, "2026-07-06", "2026-07-13")
        data = get_subscription(sub_id)
        assert data["service_status"] == "PAUSED"
        assert len(data["pause_windows"]) == 2


class TestPauseWindowOverlap:
    def test_adjacent_pause_window_accepted(self, api, ops_headers):
        """PRD §3.5: "the new half-open window — inclusive of its start,
        exclusive of its end — must not overlap any window already recorded in
        `pause_windows`; adjacency is allowed, so a new window whose start
        equals an existing window's end is accepted, while any true overlap is
        rejected with `ERR_PAUSE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pause_windows_half_open_adjacency
        """
        env = setup_active_subscription(bin_count=1)
        sub_id = env["subscription"]["id"]
        pause_subscription(sub_id, "2026-06-01", "2026-06-08")
        resume_subscription(sub_id)
        data = validate_success(
            api.pause_subscription(
                sub_id, {"pause_start": "2026-06-08", "pause_end": "2026-06-15"},
                ops_headers,
            )
        )
        assert data["service_status"] == "PAUSED"
        assert len(data["pause_windows"]) == 2

    def test_overlapping_pause_window_rejected(self, api, ops_headers):
        """PRD §3.5: "adjacency is allowed, so a new window whose start equals
        an existing window's end is accepted, while any true overlap is
        rejected with `ERR_PAUSE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pause_windows_half_open_adjacency
        """
        env = setup_active_subscription(bin_count=1)
        sub_id = env["subscription"]["id"]
        pause_subscription(sub_id, "2026-06-01", "2026-06-08")
        resume_subscription(sub_id)
        pause_subscription(sub_id, "2026-06-08", "2026-06-15")
        resume_subscription(sub_id)
        resp = api.pause_subscription(
            sub_id, {"pause_start": "2026-06-07", "pause_end": "2026-06-14"},
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PAUSE_WINDOW_OVERLAP)
        assert len(get_subscription(sub_id)["pause_windows"]) == 2


# Imported late to keep the top import block readable.
from test_helpers import TEST_USERS

TEST_OPS = TEST_USERS["ops_headers"]
