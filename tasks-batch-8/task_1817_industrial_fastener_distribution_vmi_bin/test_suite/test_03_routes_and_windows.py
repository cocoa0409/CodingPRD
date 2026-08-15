"""Route scheduling: OCC guard on the site version, half-open window
semantics, retired-site rejection, route start timing, cancellation cascade,
and close preconditions."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_route,
    create_route_payload,
    create_site,
    create_stop,
    get_site_version,
    get_success_data,
    setup_started_route_with_stop,
    setup_site_part_agreement,
    set_clock,
    submit_stop,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DRIVER = TEST_USERS["driver_headers"]


class TestRouteSchedulingOcc:
    def test_create_route_stale_site_version_rejected(self, api):
        """PRD §2.7: "If the site's current `version` has advanced — because
        another writer changed the site's credit or delivery configuration, or
        an earlier route scheduling advanced it — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412), so a route is never scheduled against a
        stale site snapshot."
        PRD §3.3: "A successful scheduling creates the route in `SCHEDULED`
        status and increments the site's `version` — which is precisely why the
        OCC guard exists."

        Design: Corner/endpoints/create_route_stale_site_version_rejected
        """
        site = create_site(api, ship_to_code="OC4-1", credit_limit_cents=100000)
        stale_v = site["version"]
        first = api.create_route(
            create_route_payload(
                site["id"], stale_v,
                window_start="2026-08-10T08:00:00Z",
                window_end="2026-08-10T10:00:00Z"),
            ADMIN)
        assert first.status_code == 201, (
            f"first route should schedule cleanly: {first.text}"
        )
        resp = api.create_route(
            create_route_payload(
                site["id"], stale_v,
                window_start="2026-08-10T12:00:00Z",
                window_end="2026-08-10T14:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


class TestRouteWindowSemantics:
    def _site_with_route(self, api, ship_to):
        site = create_site(api, ship_to_code=ship_to, credit_limit_cents=100000)
        route = create_route(api, site["id"],
                             window_start="2026-08-10T08:00:00Z",
                             window_end="2026-08-10T12:00:00Z")
        return site, route

    def test_route_window_inverted_rejected(self, api):
        """PRD §3.3: "A new route whose window overlaps an existing
        `SCHEDULED` or `IN_PROGRESS` route on the same site is rejected with
        `ERR_ROUTE_WINDOW_OVERLAP`, as is a window whose start is not strictly
        before its end."

        Design: Corner/endpoints/route_window_inverted_rejected
        """
        site = create_site(api, ship_to_code="INV-1", credit_limit_cents=100000)
        resp = api.create_route(
            create_route_payload(
                site["id"], site["version"],
                window_start="2026-08-10T12:00:00Z",
                window_end="2026-08-10T08:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_ROUTE_WINDOW_OVERLAP, 422)

    def test_overlapping_route_window_rejected(self, api):
        """PRD §3.3: "A new route whose window overlaps an existing
        `SCHEDULED` or `IN_PROGRESS` route on the same site is rejected with
        `ERR_ROUTE_WINDOW_OVERLAP`, as is a window whose start is not strictly
        before its end."

        Design: Corner/endpoints/overlapping_route_window_rejected
        """
        site, _route = self._site_with_route(api, "OV-1")
        resp = api.create_route(
            create_route_payload(
                site["id"], get_site_version(api, site["id"]),
                window_start="2026-08-10T11:59:00Z",
                window_end="2026-08-10T13:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_ROUTE_WINDOW_OVERLAP, 422)

    def test_route_starting_at_prior_window_end_allowed(self, api):
        """PRD §3.3: "Receiving windows are half-open — a route's window
        includes its start instant and excludes its end instant — so a route
        ending at a given moment does not overlap another route starting at
        that same moment, and back-to-back scheduling is allowed."

        Design: Difficulty/resource_temporal_overlap/route_windows_half_open_adjacency_allowed
        """
        site, _route = self._site_with_route(api, "S15")
        resp = api.create_route(
            create_route_payload(
                site["id"], get_site_version(api, site["id"]),
                window_start="2026-08-10T12:00:00Z",
                window_end="2026-08-10T14:00:00Z"),
            ADMIN)
        created = validate_success(resp, 201)
        assert created["status"] == "SCHEDULED", (
            "half-open boundary permits end == start adjacency"
        )

    def test_route_ending_at_prior_window_start_allowed(self, api):
        """PRD §3.3: "Receiving windows are half-open — a route's window
        includes its start instant and excludes its end instant — so a route
        ending at a given moment does not overlap another route starting at
        that same moment, and back-to-back scheduling is allowed."

        Design: Difficulty/resource_temporal_overlap/route_windows_half_open_adjacency_allowed
        """
        site, _route = self._site_with_route(api, "S15B")
        resp = api.create_route(
            create_route_payload(
                site["id"], get_site_version(api, site["id"]),
                window_start="2026-08-10T06:00:00Z",
                window_end="2026-08-10T08:00:00Z"),
            ADMIN)
        created = validate_success(resp, 201)
        assert created["status"] == "SCHEDULED", (
            "a route ending exactly at the existing window start is adjacent, "
            "not overlapping"
        )


class TestRouteCreateOnRetiredSite:
    def test_retired_site_beats_window_considerations(self, api):
        """PRD §3.3: "Scheduling against a `RETIRED` site is rejected with
        `ERR_AGREEMENT_OR_SITE_RETIRED`."
        PRD §2.8: "A request that would fail several stages receives the error
        from the earliest stage in this ordering."
        The earlier route here was cancelled before retirement, and the overlap
        rule of §3.3 only considers `SCHEDULED` or `IN_PROGRESS` routes, so the
        live-parent stage (6) is the only — and in any case earliest — stage
        that can fire.

        Design: Difficulty/priority_pair_validation_conflict/route_create_retired_site_beats_window_overlap
        """
        site = create_site(api, ship_to_code="S10", credit_limit_cents=100000000)
        route = create_route(api, site["id"],
                             window_start="2026-08-10T08:00:00Z",
                             window_end="2026-08-10T12:00:00Z")
        get_success_data(api.cancel_route(route["id"], DRIVER))
        get_success_data(api.retire_site(site["id"], ADMIN))
        site_v = get_site_version(api, site["id"])
        resp = api.create_route(
            create_route_payload(
                site["id"], site_v,
                window_start="2026-08-10T09:00:00Z",
                window_end="2026-08-10T10:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_OR_SITE_RETIRED, 409)

    def test_retired_site_rejects_any_new_route(self, api):
        """PRD §3.3: "Scheduling against a `RETIRED` site is rejected with
        `ERR_AGREEMENT_OR_SITE_RETIRED`."

        Design: Difficulty/priority_pair_validation_conflict/route_create_retired_site_beats_window_overlap
        """
        site = create_site(api, ship_to_code="S10B",
                           credit_limit_cents=100000000)
        get_success_data(api.retire_site(site["id"], ADMIN))
        site_v = get_site_version(api, site["id"])
        resp = api.create_route(
            create_route_payload(
                site["id"], site_v,
                route_date="2026-08-12T00:00:00Z",
                window_start="2026-08-12T08:00:00Z",
                window_end="2026-08-12T10:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_OR_SITE_RETIRED, 409)


class TestRouteLifecycle:
    def test_route_start_before_window_rejected(self, api):
        """PRD §3.3: "Starting requires that the logical clock has reached the
        route's `window_start` and that the site is still `ACTIVE`; the
        transition increments the route's `version`."
        PRD §2.8: "transition legality — the target resource must be in a state
        from which the requested transition exists, surfacing
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/route_start_before_window_rejected
        """
        site = create_site(api, ship_to_code="WS-1", credit_limit_cents=100000)
        route = create_route(api, site["id"],
                             window_start="2026-08-10T08:00:00Z",
                             window_end="2026-08-10T12:00:00Z")
        set_clock(api, "2026-08-09T09:00:00Z")
        resp = api.start_route(route["id"], DRIVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_success_data(api.get_route(route["id"], ADMIN))
        assert after["status"] == "SCHEDULED"

    def test_cancel_route_deletes_pending_stops(self, api):
        """PRD §3.3: "A scheduled route that will not run can instead be
        cancelled — `SCHEDULED` to `CANCELLED` — which deletes every one of its
        `PENDING` stops outright, since pending stops carry no side effects,
        and increments the route's `version`."

        Design: Corner/state_machines/cancel_route_deletes_pending_stops
        """
        ctx = setup_site_part_agreement(api, credit_limit_cents=100000,
                                        min_qty=1, max_qty=10)
        route = create_route(api, ctx["site"]["id"])
        stop = create_stop(api, route["id"], ctx["agreement"]["id"])
        cancelled = validate_success(api.cancel_route(route["id"], DRIVER))
        assert cancelled["status"] == "CANCELLED"
        resp = api.get_route_stop(stop["id"], DRIVER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_close_route_with_pending_stop_rejected(self, api):
        """PRD §3.3: "Closing the route — `IN_PROGRESS` to `CLOSED` — is
        allowed only when the route has produced work and no loose ends remain:
        at least one of its stops must be `SUBMITTED`, and no stop may remain
        `PENDING`. Closing an empty route or one with unsubmitted stops is
        rejected with `ERR_ROUTE_EMPTY` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/route_close_with_zero_submitted_stops_rejected
        """
        ctx = setup_site_part_agreement(api, min_qty=10, max_qty=100)
        rs = setup_started_route_with_stop(
            api, ctx["site"]["id"], ctx["agreement"]["id"])
        resp = api.close_route(rs["route"]["id"], DRIVER)
        validate_error(resp, ApiErrorId.ERR_ROUTE_EMPTY, 422)
        after = get_success_data(api.get_route(rs["route"]["id"], ADMIN))
        assert after["status"] == "IN_PROGRESS", (
            "a rejected close leaves the route in progress"
        )

    def test_close_route_with_one_submitted_stop_succeeds(self, api):
        """PRD §3.3: "Closing the route — `IN_PROGRESS` to `CLOSED` — is
        allowed only when the route has produced work and no loose ends remain:
        at least one of its stops must be `SUBMITTED`, and no stop may remain
        `PENDING`."

        Design: Difficulty/boundary_precision_check/route_close_with_zero_submitted_stops_rejected
        """
        ctx = setup_site_part_agreement(api, min_qty=10, max_qty=100)
        rs = setup_started_route_with_stop(
            api, ctx["site"]["id"], ctx["agreement"]["id"])
        submit_stop(api, rs["stop"]["id"], 50)
        closed = validate_success(api.close_route(rs["route"]["id"], DRIVER))
        assert closed["status"] == "CLOSED", (
            "exactly one submitted stop satisfies the close preconditions"
        )

    def test_initial_states_on_create(self, api):
        """PRD §3.1: "A new site begins in `ACTIVE` status with
        `outstanding_balance_cents` at zero."
        PRD §3.2: "A new agreement starts in `ACTIVE` status with
        `compliance_flag` `CLEAR`, `on_hand_qty` zero, and `open_order_qty`
        zero."
        PRD §3.3: "A successful scheduling creates the route in `SCHEDULED`
        status and increments the site's `version` — which is precisely why the
        OCC guard exists."
        PRD §3.3: "the new stop records its `route_id`, starts in `PENDING`
        status, and its `generated_order_id` is null."

        Design: Corner/state_machines/initial_states_on_create
        """
        ctx = setup_site_part_agreement(api, credit_limit_cents=100000,
                                        min_qty=1, max_qty=10)
        assert ctx["site"]["status"] == "ACTIVE"
        agr = ctx["agreement"]
        assert agr["status"] == "ACTIVE"
        assert agr["compliance_flag"] == "CLEAR"
        assert agr["on_hand_qty"] == 0
        assert agr["open_order_qty"] == 0
        route = create_route(api, ctx["site"]["id"])
        assert route["status"] == "SCHEDULED"
        stop = create_stop(api, route["id"], agr["id"])
        assert stop["status"] == "PENDING"
        assert stop["generated_order_id"] is None
        assert stop["route_id"] == route["id"]
