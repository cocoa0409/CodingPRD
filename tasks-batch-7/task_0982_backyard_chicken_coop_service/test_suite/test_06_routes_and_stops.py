"""Sitting routes and stops: publish/cancel guards, engagement-cancel cascade,
committed_stops conservation, OCC on stop additions."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_household, create_coop, create_engagement, quote_engagement,
    confirm_engagement, list_engagement_stops, create_route, create_published_route,
    setup_household_with_grade_b_coop, setup_confirmed_engagement,
    make_customer_headers, add_route_stop_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


class TestEngagementCancelCascade:
    def _confirmed_engagement_on_route(self, api):
        household, coop = setup_household_with_grade_b_coop()
        route = create_published_route("tech-9", "2026-07-10T00:00:00Z", "URBAN", 4)
        engagement = create_engagement(household, coop, "2026-07-10T00:00:00Z",
                                       "2026-07-11T00:00:00Z")
        quote_engagement(engagement["id"])
        engagement = confirm_engagement(engagement["id"], household)
        stops = list_engagement_stops(engagement["id"])
        assert len(stops) == 1
        return household, route, engagement, stops[0]

    def test_cancel_removes_pending_stops(self, api):
        """PRD §3.6: "The fee is recorded in `cancellation_fee_cents` (0
        whenever the notice or source state makes it free), `cancelled_at` is
        stamped from the logical clock, and the engagement's cascade fires:
        every `PENDING` RouteStop of the engagement becomes `REMOVED`, and each
        removal decrements its route's `committed_stops` and increments the
        route's `version`; a `PUBLISHED` route whose committed count thereby
        reaches zero auto-demotes itself to `PLANNED` (§3.7)."
        PRD §3.6: "At least 72 hours of notice means no fee; at least 24 but
        under 72 hours means a fee of 25 percent of `quoted_price_cents`,
        rounded half up to whole cents; under 24 hours means 50 percent,
        likewise rounded."

        Design: Difficulty/transitive_cascade/engagement_cancel_cascade_depth2
        """
        household, route, engagement, stop = self._confirmed_engagement_on_route(api)
        cancelled = validate_success(api.cancel_engagement(
            engagement["id"], make_customer_headers(household["id"])), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_fee_cents"] == 0, (
            "notice far exceeds 72h at the default 2026-05-01 clock")

        stop_after = validate_success(api.get_route_stop(stop["id"], DISPATCHER), 200)
        assert stop_after["status"] == "REMOVED", "cascade link 1: PENDING -> REMOVED"

    def test_route_auto_demotes_when_last_stop_removed(self, api):
        """PRD §3.7: "The third terminal state, `REMOVED`, is never
        client-driven: it arrives only through the engagement-cancellation
        cascade, and each removal decrements the owning route's
        `committed_stops`, increments the route's `version`, and — when the
        committed count reaches zero on a `PUBLISHED` route — demotes the route
        back to `PLANNED` automatically."

        Design: Difficulty/transitive_cascade/engagement_cancel_cascade_depth2
        """
        household, route, engagement, stop = self._confirmed_engagement_on_route(api)
        validate_success(api.cancel_engagement(
            engagement["id"], make_customer_headers(household["id"])), 200)

        route_after = validate_success(api.get_sitting_route(route["id"], DISPATCHER), 200)
        assert route_after["committed_stops"] == 0, "cascade link 2: REMOVED decrements"
        assert route_after["status"] == "PLANNED", "auto-demotion fired at committed_stops == 0"


class TestCommittedStopsRoundTrip:
    def _two_confirmed_engagements(self, api):
        household1, coop1 = setup_household_with_grade_b_coop(name="H R1", address="17 Hen Ln")
        household2, coop2 = setup_household_with_grade_b_coop(name="H R2", address="18 Hen Ln")
        route = create_published_route("tech-9", "2026-08-01T00:00:00Z", "URBAN", 4)
        eng1 = create_engagement(household1, coop1, "2026-08-01T00:00:00Z",
                                 "2026-08-02T00:00:00Z", daily_window_start="08:00")
        quote_engagement(eng1["id"])
        confirm_engagement(eng1["id"], household1)
        eng2 = create_engagement(household2, coop2, "2026-08-01T00:00:00Z",
                                 "2026-08-02T00:00:00Z", daily_window_start="10:00")
        quote_engagement(eng2["id"])
        return route, eng2, household2

    def test_second_confirm_increments_committed_stops(self, api):
        """PRD §3.6: "On success the engagement becomes `CONFIRMED` and one
        `PENDING` RouteStop per stop date materializes on its selected route,
        each stop taking a planned window of 60 minutes from
        `daily_window_start`, a 1-based `sequence` equal to its route's
        `committed_stops` at insertion time plus one, and each creation
        incrementing its route's `committed_stops` and the route's `version`
        by 1."
        PRD §3.7: "The `committed_stops` counter reflects only stops in
        `PENDING` or `DONE` status; `SKIPPED` and `REMOVED` stops are excluded
        from the committed count."

        Design: Difficulty/compensating_invariant/route_committed_stops_assign_cancel_roundtrip
        """
        route, eng2, household2 = self._two_confirmed_engagements(api)
        baseline = validate_success(api.get_sitting_route(route["id"], DISPATCHER), 200)
        assert baseline["committed_stops"] == 1

        confirm_engagement(eng2["id"], household2)
        mid = validate_success(api.get_sitting_route(route["id"], DISPATCHER), 200)
        assert mid["committed_stops"] == 2, "forward action adds exactly one stop"

    def test_cancel_returns_route_to_baseline_without_demotion(self, api):
        """PRD §3.6: "the engagement's cascade fires: every `PENDING` RouteStop
        of the engagement becomes `REMOVED`, and each removal decrements its
        route's `committed_stops` and increments the route's `version`; a
        `PUBLISHED` route whose committed count thereby reaches zero
        auto-demotes itself to `PLANNED` (§3.7)."

        Design: Difficulty/compensating_invariant/route_committed_stops_assign_cancel_roundtrip
        """
        route, eng2, household2 = self._two_confirmed_engagements(api)
        confirm_engagement(eng2["id"], household2)
        validate_success(api.cancel_engagement(
            eng2["id"], make_customer_headers(household2["id"])), 200)

        after = validate_success(api.get_sitting_route(route["id"], DISPATCHER), 200)
        assert after["committed_stops"] == 1, (
            "compensating action restores the pre-engagement count")
        assert after["status"] == "PUBLISHED", "no zero-count demotion at committed 1"


class TestRouteGuards:
    def test_second_publish_rejected(self, api):
        """PRD §3.7: "Publishing moves a `PLANNED` route to `PUBLISHED` —
        publishing from any other state yields `ERR_ROUTE_NOT_PLANNED` — and
        increments the route's `version`."

        Design: Corner/state_machines/route_publish_twice_rejected_idempotency
        """
        route = create_published_route("tech-9", "2026-07-10T00:00:00Z", "URBAN", 4)
        res = api.publish_sitting_route(route["id"], DISPATCHER)
        validate_error(res, ApiErrorId.ERR_ROUTE_NOT_PLANNED)
        after = validate_success(api.get_sitting_route(route["id"], DISPATCHER), 200)
        assert after["status"] == "PUBLISHED"

    def test_cancel_with_committed_stops_rejected(self, api):
        """PRD §3.7: "A route itself can be cancelled by a `Dispatcher` only
        while `PLANNED` or `PUBLISHED` (otherwise `ERR_ROUTE_NOT_PUBLISHED`)
        and only when it holds no committed stops at all — a `committed_stops`
        above zero rejects the cancellation with `ERR_ROUTE_NOT_EMPTY`."

        Design: Corner/state_machines/route_cancel_with_committed_stops_rejected
        """
        household, coop, routes, engagement = setup_confirmed_engagement()
        route = routes[0]
        res = api.cancel_sitting_route(route["id"], DISPATCHER)
        validate_error(res, ApiErrorId.ERR_ROUTE_NOT_EMPTY)
        after = validate_success(api.get_sitting_route(route["id"], DISPATCHER), 200)
        assert after["status"] == "PUBLISHED"


class TestRouteStopOCC:
    def test_stale_then_fresh_version_on_stop_add(self, api):
        """PRD §2.7: "**Adding a stop to a sitting route.** The request must
        carry `expected_route_version` equal to the target route's current
        `version`.
        If another writer has advanced the route's version since the client
        last read it — for example by adding a stop, a legitimate mutation
        under the route's capacity rules — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.7: "A successful addition creates the stop in `PENDING`, assigns
        its `sequence` as the route's committed count at insertion plus one,
        and bumps `committed_stops` and the route `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/occ_route_stop_stale_then_fresh_version
        """
        household, coop = setup_household_with_grade_b_coop()
        route = create_route("tech-9", "2026-08-01T00:00:00Z", "URBAN", 4)
        published = validate_success(api.publish_sitting_route(route["id"], DISPATCHER), 200)
        publish_version = published["version"]

        engagement = create_engagement(household, coop, "2026-08-01T00:00:00Z",
                                       "2026-08-02T00:00:00Z")
        quote_engagement(engagement["id"])
        confirm_engagement(engagement["id"], household)

        stale = api.add_route_stop(
            route["id"],
            add_route_stop_payload(engagement["id"], publish_version,
                                   planned_start="2026-08-01T12:00:00Z",
                                   planned_end="2026-08-01T13:00:00Z"),
            DISPATCHER)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        current = validate_success(api.get_sitting_route(route["id"], DISPATCHER), 200)
        added = validate_success(api.add_route_stop(
            route["id"],
            add_route_stop_payload(engagement["id"], current["version"],
                                   planned_start="2026-08-01T12:00:00Z",
                                   planned_end="2026-08-01T13:00:00Z"),
            DISPATCHER), 201)
        assert added["sequence"] == 2
        route_after = validate_success(api.get_sitting_route(route["id"], DISPATCHER), 200)
        assert route_after["committed_stops"] == 2
