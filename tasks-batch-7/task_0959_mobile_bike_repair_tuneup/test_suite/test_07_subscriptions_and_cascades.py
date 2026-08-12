"""Subscription allowance accounting and the two deep cascades."""
from test_helpers import (
    STANDARD_TIER,
    arrive_stop,
    assert_subscription,
    complete_request,
    dispatch_stop,
    get_request,
    get_route_day,
    get_route_stop,
    get_subscription,
    make_bike,
    make_mechanic,
    make_request,
    make_route_day,
    make_van,
    setup_dispatched_request,
    setup_quoted_request,
    start_service,
    validate_success,
)


class TestAllowanceViews:
    """FLEET customer; subscription included_tunes_per_period=4, discount 0.10."""

    def _setup_two_open(self, api, dispatcher_headers):
        ctx = setup_quoted_request(
            customer_kind="FLEET",
            subscription={"included_tunes_per_period": 4, "discount_pct": 0.10},
            window=("2026-05-02T10:00:00Z", "2026-05-02T12:00:00Z"))
        bike2 = make_bike(ctx["customer"]["id"])
        req2 = make_request(ctx["customer"]["id"], bike2["id"], ctx["zone"]["id"],
                            ctx["tier"]["id"], subscription_id=ctx["subscription"]["id"],
                            window=("2026-05-02T13:00:00Z", "2026-05-02T15:00:00Z"))
        return ctx, req2

    def test_reserved_and_settled_views_diverge_while_open(self, api, dispatcher_headers):
        """PRD §3.5: "The forward-looking view, `allowance_remaining`, subtracts
        both reserved and consumed units from `included_tunes_per_period`; it is
        the booking-time gate and the customer-facing remainder. The settled view,
        `settled_allowance_remaining`, subtracts only consumed units; it is the
        accounting view of tunes actually delivered, and it diverges from the
        reserved view whenever any covered request is still open."

        Design: Difficulty/dual_variant_calc/subscription_allowance_reserved_vs_settled_views
        """
        ctx, _req2 = self._setup_two_open(api, dispatcher_headers)
        sub = get_subscription(ctx["subscription"]["id"])
        assert_subscription(sub)
        assert sub["allowance_reserved"] == 2
        assert sub["allowance_consumed"] == 0
        assert sub["allowance_remaining"] == 2, (
            f"reserved view must be 4 - 2 - 0 = 2, got {sub['allowance_remaining']}")
        assert sub["settled_allowance_remaining"] == 4, (
            f"settled view must be 4 - 0 = 4, got {sub['settled_allowance_remaining']}")
        assert sub["allowance_remaining"] != sub["settled_allowance_remaining"], (
            "the two views must diverge while covered requests are open")

    def test_settlement_moves_one_unit_reserved_to_consumed(self, api, dispatcher_headers):
        """PRD §3.5: "completing a covered request settles it, moving one unit
        from reserved to consumed."

        Design: Difficulty/dual_variant_calc/subscription_allowance_reserved_vs_settled_views
        """
        ctx, _req2 = self._setup_two_open(api, dispatcher_headers)
        # Drive the first covered request through the full dispatch chain.
        mech = make_mechanic(ctx["zone"]["id"])
        van = make_van(ctx["zone"]["id"], mechanic_id=mech["id"])
        rd = make_route_day(van["id"])
        stop = dispatch_stop(rd["id"], ctx["request"]["id"],
                             "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")
        arrive_stop(stop["id"], mech["id"])
        start_service(ctx["request"]["id"], mech["id"])
        complete_request(ctx["request"]["id"], mech["id"], 40)

        sub = get_subscription(ctx["subscription"]["id"])
        assert sub["allowance_reserved"] == 1
        assert sub["allowance_consumed"] == 1
        assert sub["allowance_remaining"] == 2, (
            f"reserved view must be 4 - 1 - 1 = 2, got {sub['allowance_remaining']}")
        assert sub["settled_allowance_remaining"] == 3, (
            f"settled view must be 4 - 1 = 3, got {sub['settled_allowance_remaining']}")


class TestSubscriptionSuspendCascade:
    def _setup_covered_quoted(self):
        return setup_quoted_request(
            tier=STANDARD_TIER, customer_kind="FLEET",
            subscription={"included_tunes_per_period": 5, "discount_pct": 0.10})

    def test_suspend_clears_coverage_and_releases_allowance(self, api, dispatcher_headers):
        """PRD §3.5: "Suspending or cancelling from a live state triggers a
        decoupling cascade: every request pointing at this subscription whose
        `work_status` is `QUOTED`, `DISPATCHED`, `ON_SITE`, `IN_SERVICE`, or
        `ON_HOLD_PARTS` has `covered_by_subscription` set false, its allowance
        reservation released by one, and its `quoted_total_cents` recomputed
        without the subscription discount per §3.4."

        Design: Difficulty/transitive_cascade/subscription_suspend_releases_allowance_and_requotes
        """
        ctx = self._setup_covered_quoted()
        assert ctx["request"]["covered_by_subscription"] is True
        assert ctx["request"]["quoted_total_cents"] == 11891

        sub = validate_success(api.subscription_event(
            ctx["subscription"]["id"], {"event_type": "SUSPEND"}, dispatcher_headers), 200)
        assert sub["status"] == "SUSPENDED"
        assert sub["allowance_reserved"] == 0, "suspension must release the open reservation"

        req = get_request(ctx["request"]["id"])
        assert req["covered_by_subscription"] is False

    def test_suspend_recomputes_quote_without_discount(self, api, dispatcher_headers):
        """PRD §3.4: "The quote is recomputed under the same rules whenever a
        subscription decoupling cascade strips coverage from the request."
        PRD §3.5: "Suspending or cancelling from a live state triggers a
        decoupling cascade: every request pointing at this subscription whose
        `work_status` is `QUOTED`, `DISPATCHED`, `ON_SITE`, `IN_SERVICE`, or
        `ON_HOLD_PARTS` has `covered_by_subscription` set false, its allowance
        reservation released by one, and its `quoted_total_cents` recomputed
        without the subscription discount per §3.4."

        Design: Difficulty/transitive_cascade/subscription_suspend_releases_allowance_and_requotes
        """
        ctx = self._setup_covered_quoted()
        quoted_pre = ctx["request"]["quoted_total_cents"]
        assert quoted_pre == 11891

        validate_success(api.subscription_event(
            ctx["subscription"]["id"], {"event_type": "SUSPEND"}, dispatcher_headers), 200)
        req = get_request(ctx["request"]["id"])
        # Without the 10% discount: subtotal 2500 + 8900 = 11400; surcharge 500;
        # tax round(11900 * 0.08) = 952; total 11400 + 500 + 952 = 12852.
        assert req["quoted_total_cents"] == 12852, (
            f"decoupled quote must recompute to 12852, got {req['quoted_total_cents']}")
        assert req["quoted_total_cents"] != quoted_pre


class TestMechanicSuspendCascade:
    def _setup_locked_day_with_stop(self, api, dispatcher_headers):
        """One DISPATCHED request on a route day that is then LOCKED."""
        ctx = setup_dispatched_request(
            window=("2026-05-02T10:00:00Z", "2026-05-02T12:00:00Z"),
            planned=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        validate_success(api.route_day_event(
            ctx["route_day"]["id"], {"event_type": "LOCK"}, dispatcher_headers), 200)
        return ctx

    def test_suspend_unassigns_stop_and_reverts_request(self, api, dispatcher_headers):
        """PRD §3.3: "When a mechanic moves from `ACTIVE` to `SUSPENDED`, three
        things happen in order. First, every stop still `PLANNED` on a non-closed
        route day belonging to a van assigned to that mechanic becomes
        `UNASSIGNED`. Second, each affected stop's linked request reverts from
        `DISPATCHED` to `QUOTED` and its `scheduled_mechanic_id` is cleared to
        null."

        Design: Difficulty/transitive_cascade/mechanic_suspend_unassigns_stops_reverts_requests_unlocks_route
        """
        ctx = self._setup_locked_day_with_stop(api, dispatcher_headers)
        mech = validate_success(api.mechanic_event(
            ctx["mechanic"]["id"], {"event_type": "SUSPEND", "reason": "injury"},
            dispatcher_headers), 200)
        assert mech["status"] == "SUSPENDED"

        stop = get_route_stop(ctx["stop"]["id"])
        assert stop["status"] == "UNASSIGNED", (
            f"hop 1: stop must become UNASSIGNED, got {stop['status']}")
        req = get_request(ctx["request"]["id"])
        assert req["work_status"] == "QUOTED", (
            f"hop 2: request must revert to QUOTED, got {req['work_status']}")
        assert req["scheduled_mechanic_id"] is None

    def test_suspend_emptied_locked_day_auto_unlocks(self, api, dispatcher_headers):
        """PRD §3.3: "Third, every affected route day recomputes its
        `active_stop_count` and bumps its `version`; a route day that was `LOCKED`
        and is thereby emptied auto-transitions from `LOCKED` to `OPEN`, per
        §2.9."

        Design: Difficulty/transitive_cascade/mechanic_suspend_unassigns_stops_reverts_requests_unlocks_route
        """
        ctx = self._setup_locked_day_with_stop(api, dispatcher_headers)
        assert get_route_day(ctx["route_day"]["id"])["status"] == "LOCKED"

        validate_success(api.mechanic_event(
            ctx["mechanic"]["id"], {"event_type": "SUSPEND", "reason": "injury"},
            dispatcher_headers), 200)

        day = get_route_day(ctx["route_day"]["id"])
        assert day["active_stop_count"] == 0, (
            f"hop 3: emptied day must report active_stop_count 0, got {day['active_stop_count']}")
        assert day["status"] == "OPEN", (
            f"hop 3: emptied LOCKED day must auto-unlock to OPEN, got {day['status']}")
