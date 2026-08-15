"""Depth-3 cascades: a customer suspension and a logical-clock pause activation
each ripple subscription -> stop -> route manifest (PRD 3.2, 3.7)."""
from test_helpers import (
    create_pause,
    create_route,
    customer_event,
    find_stop,
    read_pause,
    read_route,
    read_stop,
    read_subscription,
    set_clock,
    setup_active_subscription,
)


class TestCustomerSuspendCascade:
    def _setup_route_with_planned_stop(self):
        """ACTIVE subscription plus a freshly created route holding its
        auto-created PLANNED stop."""
        ctx = setup_active_subscription()
        route = create_route(ctx["zone"], "2026-08-03")
        stop = find_stop(route["id"], ctx["subscription"]["id"])
        assert stop["status"] == "PLANNED"
        ctx.update({"route": route, "stop": stop})
        return ctx

    def test_suspend_cascades_to_subscription_and_stops(self, api):
        """PRD 3.2: "A `PlatformAdmin` fires the customer event `SUSPEND`, moving the
        customer `ACTIVE` → `SUSPENDED`; every subscription of that customer whose
        `service_status` is `ACTIVE` cascades to `SUSPENDED`, every `PLANNED` stop of
        each such subscription cascades to `SKIPPED`, and each skip recomputes the
        parent route's manifest counters and increments the route's `version`."

        Design: Difficulty/transitive_cascade/customer_suspend_cascade_depth3
        """
        ctx = self._setup_route_with_planned_stop()

        customer = customer_event(ctx["customer"]["id"], "SUSPEND")
        assert customer["status"] == "SUSPENDED"

        subscription = read_subscription(ctx["subscription"]["id"])
        assert subscription["service_status"] == "SUSPENDED", (
            "link 1: the customer suspension cascades to the subscription"
        )
        stop = read_stop(ctx["stop"]["id"])
        assert stop["status"] == "SKIPPED", (
            "link 2: the subscription suspension skips its PLANNED stops"
        )

    def test_suspend_cascade_recomputes_route_manifest(self, api):
        """PRD 3.2: "and each skip recomputes the parent route's manifest counters
        and increments the route's `version`."
        PRD 2.4: "`version` (integer): starts at its initial value on creation and
        increments by one on every mutation of the resource, including mutations
        caused by cascades originating elsewhere."

        Design: Difficulty/transitive_cascade/customer_suspend_cascade_depth3
        """
        ctx = self._setup_route_with_planned_stop()
        route_before = read_route(ctx["route"]["id"])
        assert route_before["planned_stop_count"] == 1

        customer_event(ctx["customer"]["id"], "SUSPEND")

        route_after = read_route(ctx["route"]["id"])
        assert route_after["planned_stop_count"] == 0, (
            "link 3: the skip recompute drops the planned count"
        )
        assert route_after["version"] == route_before["version"] + 1, (
            f"one skipped stop bumps the route version by exactly one: "
            f"{route_before['version']} -> {route_after['version']}"
        )


class TestClockPauseActivationCascade:
    def _setup_pause_covering_route(self):
        """ACTIVE subscription; route for Thursday 2026-08-06 created BEFORE the
        pause exists (so its stop is PLANNED); then a SCHEDULED pause over
        [2026-08-05, 2026-08-10) covering the route date."""
        ctx = setup_active_subscription()
        route = create_route(ctx["zone"], "2026-08-06")
        stop = find_stop(route["id"], ctx["subscription"]["id"])
        assert stop["status"] == "PLANNED"
        pause = create_pause(
            ctx["subscription"]["id"], "2026-08-05", "2026-08-10",
            ctx["subscription_version"], ctx["customer_headers"],
        )
        assert pause["status"] == "SCHEDULED"
        ctx.update({"route": route, "stop": stop, "pause": pause})
        return ctx

    def test_clock_crossing_activates_pause_and_pauses_subscription(self, api):
        """PRD 2.5: "Setting the clock is not a passive read-through — it applies
        every system transition that has come due: scheduled pauses whose window
        contains the new date activate (cascading subscriptions into their paused
        state and skipping in-window stops), and active pauses whose window has ended
        complete (cascading subscriptions back into service and fixing their final
        credit amounts)."

        Design: Difficulty/transitive_cascade/clock_pause_activation_cascade
        """
        ctx = self._setup_pause_covering_route()

        set_clock("2026-08-06T07:00:00Z")

        pause = read_pause(ctx["pause"]["id"])
        assert pause["status"] == "ACTIVE", (
            "link 1: the clock entering the window activates the pause"
        )
        subscription = read_subscription(ctx["subscription"]["id"])
        assert subscription["service_status"] == "PAUSED", (
            "link 2: the pause activation pauses the subscription"
        )

    def test_pause_activation_skips_in_window_stop(self, api):
        """PRD 3.7: "When the clock's date enters a `SCHEDULED` pause's window, the
        pause moves `SCHEDULED` → `ACTIVE`; the subscription moves `ACTIVE` →
        `PAUSED`; every `PLANNED` stop of that subscription whose route's `route_date`
        falls inside the window moves to `SKIPPED`; and each skip recomputes the
        parent route's manifest counters and increments the route's `version`."

        Design: Difficulty/transitive_cascade/clock_pause_activation_cascade
        """
        ctx = self._setup_pause_covering_route()
        route_before = read_route(ctx["route"]["id"])
        assert route_before["planned_stop_count"] == 1

        set_clock("2026-08-06T07:00:00Z")

        stop = read_stop(ctx["stop"]["id"])
        assert stop["status"] == "SKIPPED", (
            "link 3: the in-window PLANNED stop is skipped by the cascade"
        )
        route_after = read_route(ctx["route"]["id"])
        assert route_after["planned_stop_count"] == 0
        assert route_after["version"] == route_before["version"] + 1
