"""Route planning, sequencing, the curbside exchange, and route/stop listing
filters (PRD 3.3)."""
from test_helpers import (
    ApiErrorId,
    add_active_subscription,
    assert_stop,
    complete_stop,
    create_pause,
    create_route,
    create_route_payload,
    create_route_stop_payload,
    create_zone,
    drive_route_to_in_progress,
    find_stop,
    read_route,
    read_subscription,
    sequence_route,
    set_clock,
    setup_active_subscription,
    setup_route_in_progress,
    stop_event,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers.fixtures import ADMIN, DRIVER


class TestRouteCompletionGate:
    def test_route_complete_with_open_stop_returns_invalid_state(self, api):
        """PRD 3.3: "Completion moves `IN_PROGRESS` → `COMPLETED` only when every
        stop on the route has reached a terminal state — `COMPLETED`, `MISSED` is not
        terminal, so the terminal set is `COMPLETED`, `SKIPPED`, `FORFEITED`, or
        `RESCHEDULED` — and is otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/route_complete_with_open_stop_returns_invalid_state
        """
        ctx = setup_active_subscription()
        setup_route_in_progress(ctx)
        route_id = ctx["route"]["id"]

        blocked = _client.route_event(route_id, {"event_type": "COMPLETE"}, ADMIN)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE.value)

        stop_event(ctx["stop"]["id"], "SKIP")
        completed = validate_success(_client.route_event(route_id, {"event_type": "COMPLETE"}, ADMIN))
        assert completed["status"] == "COMPLETED", (
            "once every stop is terminal, COMPLETE moves the route to COMPLETED"
        )


class TestCutoffAndLockGuards:
    def test_sequence_after_cutoff_returns_cutoff_passed(self, api):
        """PRD 3.3: "Sequencing is a `PlatformAdmin` action available while the route
        is `PLANNED` or `SEQUENCED`, and it is gated by the zone's cutoff: the current
        logical time must be earlier than midnight UTC of the `route_date` minus the
        zone's `stop_cutoff_hours`, else `ERR_CUTOFF_PASSED`."

        Design: Corner/validations/sequence_after_cutoff_returns_cutoff_passed
        """
        ctx = setup_active_subscription()
        route = create_route(ctx["zone"], "2026-08-03")
        # Cutoff for a 2026-08-03 route with stop_cutoff_hours 24 is 2026-08-02T00:00:00Z.
        set_clock("2026-08-02T12:00:00Z")

        response = _client.sequence_route(route["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_CUTOFF_PASSED.value)

        after = read_route(route["id"])
        assert after["status"] == "PLANNED", "a rejected sequence leaves the route PLANNED"
        stop = find_stop(route["id"], ctx["subscription"]["id"])
        assert stop["stop_seq"] is None, "stop_seq stays null until sequencing"

    def test_stop_add_to_locked_route_returns_route_locked(self, api):
        """PRD 3.3: "The target route must be `PLANNED` or `SEQUENCED`
        (`ERR_ROUTE_LOCKED` otherwise), and the new window must clear the scheduling
        buffer against every non-terminal stop already on the route"

        Design: Corner/validations/stop_add_to_locked_route_returns_route_locked
        """
        ctx = setup_active_subscription()
        route = create_route(ctx["zone"], "2026-08-03")
        sequence_route(route["id"])
        validate_success(_client.route_event(route["id"], {"event_type": "LOCK"}, ADMIN))

        response = _client.create_route_stop(
            create_route_stop_payload(route["id"], ctx["subscription"]["id"], 800, 900),
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_ROUTE_LOCKED.value)

    def test_route_capacity_exceeded_on_complete(self, api):
        """PRD 3.3: "and the completion must not push the route past its capacity —
        `total_clean_items_delivered` plus this stop's `clean_items_delivered` must
        stay at or under 4000 items (`ERR_ROUTE_CAPACITY_EXCEEDED`)."

        Design: Corner/validations/route_capacity_exceeded_on_complete
        """
        ctx = setup_active_subscription()
        setup_route_in_progress(ctx)

        response = _client.complete_stop(
            ctx["stop"]["id"],
            {
                "soiled_bags_collected": 30,
                "clean_items_delivered": 4001,
                "expected_route_version": ctx["route_version"],
            },
            DRIVER,
        )
        validate_error(response, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED.value)

        stop = validate_success(_client.get_route_stop(ctx["stop"]["id"], ADMIN))
        assert stop["status"] == "PLANNED", "a rejected completion leaves the stop PLANNED"
        route = read_route(ctx["route"]["id"])
        assert route["total_clean_items_delivered"] == 0


class TestRouteStopGeneration:
    def test_route_generation_excludes_pending_and_paused(self, api):
        """PRD 3.3: "Creation auto-generates one `PLANNED` stop per eligible
        subscription — eligible meaning `service_status` `ACTIVE`, home zone matching
        the route's zone, no `SCHEDULED` or `ACTIVE` pause covering the route date,
        and no stop already existing for that subscription and date."

        Design: Corner/calculations/route_generation_excludes_pending_and_paused
        """
        ctx = setup_active_subscription()
        member_a = {
            "subscription": ctx["subscription"],
            "customer": ctx["customer"],
        }
        # B never has its kit issued, so it stays PENDING_START.
        from test_helpers.fixtures import create_customer, create_subscription

        cust_b = create_customer(ctx["zone"]["id"], full_name="Pending B")
        sub_b = create_subscription(cust_b, ctx["plan"], ctx["zone"])
        # C is ACTIVE but pauses over the route date.
        member_c = add_active_subscription(ctx, customer_overrides={"full_name": "Paused C"})
        pause = create_pause(
            member_c["subscription"]["id"],
            "2026-08-04",
            "2026-08-07",
            member_c["subscription_version"],
            member_c["customer_headers"],
        )
        assert pause["status"] == "SCHEDULED"

        route = validate_success(
            _client.create_route(
                create_route_payload(ctx["zone"]["id"], "2026-08-06"), ADMIN
            ),
            201,
        )
        assert route["planned_stop_count"] == 1, (
            f"only the plain ACTIVE subscription is eligible, got "
            f"{route['planned_stop_count']} planned stops"
        )
        stops = validate_success(
            _client.list_route_stops(ADMIN, params={"route_id": route["id"]})
        )
        assert len(stops) == 1
        assert stops[0]["subscription_id"] == member_a["subscription"]["id"], (
            "the single auto-created stop belongs to the ACTIVE, unpaused subscription"
        )
        assert sub_b["service_status"] == "PENDING_START"

    def test_sequencing_tiebreak_by_subscription_created_at(self, api):
        """PRD 3.3: "Sequencing assigns `stop_seq` 1 through N to every `PLANNED`
        stop, ordered by `window_start_minutes` ascending with ties broken by the
        subscription's `created_at` ascending — the earlier-created subscription's
        stop goes first, and a stop's own `id` never participates in the ordering."

        Design: Corner/calculations/sequencing_tiebreak_by_subscription_created_at
        """
        ctx = setup_active_subscription()
        sub_a = ctx["subscription"]
        # Tick the logical clock so the second subscription's created_at is
        # strictly later regardless of how the server stamps creation time.
        set_clock("2026-08-01T00:00:01Z")
        member_b = add_active_subscription(ctx, customer_overrides={"full_name": "Second B"})
        sub_b = member_b["subscription"]

        route = create_route(ctx["zone"], "2026-08-03")
        sequence_route(route["id"])

        stop_a = find_stop(route["id"], sub_a["id"])
        stop_b = find_stop(route["id"], sub_b["id"])
        assert_stop(stop_a)
        assert_stop(stop_b)
        assert stop_a["stop_seq"] == 1, (
            f"the earlier-created subscription's stop sequences first, got "
            f"{stop_a['stop_seq']}"
        )
        assert stop_b["stop_seq"] == 2


class TestListingFilters:
    def test_stops_list_filter_by_status(self, api):
        """PRD 4: "List route stops; optional `route_id`, `subscription_id`, and
        `status` filters"
        PRD 3.3: "the stop is marked missed — again requiring the route to be
        `IN_PROGRESS` (`ERR_INVALID_STATE`) — moving `PLANNED` → `MISSED`, recording
        the driver's `miss_reason`, adding one to the subscription's
        `missed_stop_count`, dropping `planned_stop_count` by one, and bumping the
        route's `version`."

        Design: Corner/complexity_layers/stops_list_filter_by_status
        """
        ctx = setup_active_subscription()
        member_b = add_active_subscription(ctx, customer_overrides={"full_name": "Filter B"})
        route = create_route(ctx["zone"], "2026-08-03")
        stop_a = find_stop(route["id"], ctx["subscription"]["id"])
        stop_b = find_stop(route["id"], member_b["subscription"]["id"])
        route_v = drive_route_to_in_progress(route["id"], "2026-08-03")

        complete_stop(stop_a["id"], route_v, clean_items=80)
        stop_event(stop_b["id"], "MISS", miss_reason="GATE_LOCKED")

        data, meta = validate_paginated(
            _client.list_route_stops(
                ADMIN, params={"route_id": route["id"], "status": "MISSED"}
            )
        )
        assert meta["total_count"] == 1, f"exactly one MISSED stop, got {meta['total_count']}"
        assert len(data) == 1
        assert data[0]["id"] == stop_b["id"]

        sub_a_after = read_subscription(ctx["subscription"]["id"])
        sub_b_after = read_subscription(member_b["subscription"]["id"])
        assert sub_b_after["missed_stop_count"] == 1
        assert sub_a_after["missed_stop_count"] == 0

    def test_routes_list_filter_by_zone_and_status(self, api):
        """PRD 4: "List routes; optional `service_zone_id`, `route_date`, and
        `status` filters"

        Design: Corner/complexity_layers/routes_list_filter_by_zone_and_status
        """
        set_clock()
        zone_n = create_zone(zone_code="Z-NORTH")
        zone_s = create_zone(zone_code="Z-SOUTH", service_weekdays=["TUE"])
        route_n = create_route(zone_n, "2026-08-03")
        create_route(zone_s, "2026-08-04")

        data, meta = validate_paginated(
            _client.list_routes(
                ADMIN, params={"service_zone_id": zone_n["id"], "status": "PLANNED"}
            )
        )
        assert meta["total_count"] == 1, (
            f"the combined filter returns exactly the north route, got {meta['total_count']}"
        )
        assert len(data) == 1
        assert data[0]["id"] == route_n["id"]


class TestImmediateConsistency:
    def test_immediate_consistency_on_complete_response(self, api):
        """PRD 3.3: "A successful completion moves the stop `PLANNED` → `COMPLETED`,
        adds its figures into the route's totals, moves one count from
        `planned_stop_count` to `completed_stop_count`, and increments the route's
        `version`."

        Design: Corner/consistency_model/immediate_consistency_on_complete_response
        """
        ctx = setup_active_subscription()
        setup_route_in_progress(ctx)

        completed = validate_success(
            _client.complete_stop(
                ctx["stop"]["id"],
                {
                    "soiled_bags_collected": 1,
                    "clean_items_delivered": 80,
                    "expected_route_version": ctx["route_version"],
                },
                DRIVER,
            )
        )
        assert completed["status"] == "COMPLETED"
        assert completed["clean_items_delivered"] == 80, (
            "the completion response itself carries the recorded figures"
        )

        route = read_route(ctx["route"]["id"])
        assert route["completed_stop_count"] == 1
        assert route["planned_stop_count"] == 0
        assert route["total_clean_items_delivered"] == 80, (
            "the immediately following read shows the updated manifest — no lag"
        )
