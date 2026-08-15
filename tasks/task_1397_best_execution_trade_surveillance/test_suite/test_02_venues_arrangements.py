"""Venues and routing arrangements: lifecycle, cascades, half-open window
overlap semantics, and the venue safety gate (PRD §2.9, §3.2)."""
from test_helpers import (
    ApiErrorId,
    flat_tier,
    make_arrangement,
    make_employee,
    make_order,
    make_venue,
    setup_venue_with_active_arrangement,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_covered_employee_headers

CA = TEST_USERS["compliance_admin_headers"]
OPS = TEST_USERS["ops_admin_headers"]


class TestVenueLifecycle:
    def test_duplicate_venue_code_rejected(self, api):
        """PRD §3.2: "A `ComplianceAdmin` registers each execution venue with
        a unique `venue_code` (for example NYSE, ARCA, or XATS — a duplicate
        is rejected with `ERR_DUPLICATE_VENUE_CODE`)".

        Design: Corner/entities/duplicate_venue_code_rejected
        """
        make_venue(venue_code="NYSE", name="New York Stock Exchange")
        resp = api.create_venue({"venue_code": "NYSE", "name": "Duplicate", "venue_type": "ATS"}, CA)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VENUE_CODE)

    def test_venue_reinstate_does_not_restore_arrangements_or_orders(self, api):
        """PRD §3.2: "Reinstatement moves the venue from `SUSPENDED` back to
        `ACTIVE` and deliberately restores nothing else — arrangements remain
        suspended and cancelled orders remain cancelled."

        Design: Corner/state_machines/venue_reinstate_does_not_restore_arrangements_or_orders
        """
        venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
        order = make_order(arrangement_id=arrangement["id"], symbol="ACME")

        validate_success(api.venue_transition(venue["id"], {"to_status": "SUSPENDED"}, CA))
        back = validate_success(api.venue_transition(venue["id"], {"to_status": "ACTIVE"}, CA))
        assert back["status"] == "ACTIVE", "venue itself cycles back"

        arr_after = validate_success(api.get_arrangement(arrangement["id"], CA))
        assert arr_after["status"] == "SUSPENDED", "reinstatement must not restore the arrangement"
        orders, meta = validate_paginated(api.list_arrangement_orders(arrangement["id"], CA))
        assert meta["total_count"] == 1
        assert orders[0]["status"] == "CANCELLED", "reinstatement must not resurrect the cancelled order"
        assert order["status"] == "ROUTED", "setup sanity: order was routed before suspension"


class TestVenueSafetyGatePriority:
    def test_route_to_suspended_venue_reports_venue_error(self, api):
        """PRD §3.2: "Four gates apply, evaluated in order: the arrangement
        must exist (`ERR_NOT_FOUND`); the arrangement's venue must be `ACTIVE`
        (`ERR_VENUE_SUSPENDED`); no `ACTIVE` restricted-list entry for the
        order's symbol with `restriction_kind` of `ALL` or `CLIENT_ONLY` may
        exist (`ERR_SYMBOL_RESTRICTED`); and the arrangement itself must be
        `ACTIVE` with the logical now inside its half-open window
        (`ERR_NO_ACTIVE_ARRANGEMENT`)."

        Design: Difficulty/priority_pair_validation_conflict/venue_suspension_beats_arrangement_inactive_on_route
        """
        venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
        validate_success(api.venue_transition(venue["id"], {"to_status": "SUSPENDED"}, CA))
        order = make_order(symbol="ACME", quantity=10)

        resp = api.order_transition(
            order["id"], {"to_status": "ROUTED", "arrangement_id": arrangement["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_VENUE_SUSPENDED)

    def test_suspended_venue_cascade_suspends_arrangement(self, api):
        """PRD §3.2: "Suspending a venue moves it to `SUSPENDED` and fires the
        downward cascade of §2.9: every routing arrangement of that venue in
        `ACTIVE` moves to `SUSPENDED`". PRD §3.2: "the arrangement's venue
        must be `ACTIVE` (`ERR_VENUE_SUSPENDED`)" is evaluated before the
        gate where "the arrangement itself must be `ACTIVE` with the logical
        now inside its half-open window (`ERR_NO_ACTIVE_ARRANGEMENT`)".

        Design: Difficulty/priority_pair_validation_conflict/venue_suspension_beats_arrangement_inactive_on_route
        """
        venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
        validate_success(api.venue_transition(venue["id"], {"to_status": "SUSPENDED"}, CA))

        arr = validate_success(api.get_arrangement(arrangement["id"], CA))
        assert arr["status"] == "SUSPENDED", "venue suspension must cascade to the arrangement"

        order = make_order(symbol="ACME", quantity=10)
        resp = api.order_transition(
            order["id"], {"to_status": "ROUTED", "arrangement_id": arrangement["id"]}, OPS)
        err = validate_error(resp, ApiErrorId.ERR_VENUE_SUSPENDED)
        assert err["error_id"] != "ERR_NO_ACTIVE_ARRANGEMENT", (
            "the venue gate is evaluated before the arrangement-usability gate")

    def test_venue_suspended_blocks_arrangement_activation(self, api):
        """PRD §3.2: "Activation moves an arrangement from `NEGOTIATION` to
        `ACTIVE` and enforces three gates, in this order: the arrangement's
        venue must be `ACTIVE` (otherwise `ERR_VENUE_SUSPENDED`)".

        Design: Corner/errors/venue_suspended_blocks_arrangement_activation
        """
        venue = make_venue(venue_code="NYSE")
        arrangement = make_arrangement(venue["id"])
        validate_success(api.venue_transition(venue["id"], {"to_status": "SUSPENDED"}, CA))
        resp = api.arrangement_transition(arrangement["id"], {"to_status": "ACTIVE"}, CA)
        validate_error(resp, ApiErrorId.ERR_VENUE_SUSPENDED)


class TestArrangementWindows:
    def test_terminated_arrangement_admits_no_transition(self, api):
        """PRD §3.2: "from any non-terminal status — `NEGOTIATION`, `ACTIVE`,
        or `SUSPENDED` — the arrangement may move to the terminal
        `TERMINATED`". PRD §2.10: "Terminal states admit no further
        transitions anywhere in the system: executed or cancelled orders,
        terminated arrangements and employees, locked snapshots, superseded
        disclosures and policies, retired lexicon policies, completed or
        cancelled training assignments, denied, reconciled, or expired
        personal trades, expired restricted-list entries, and cleared or
        escalated communication items are all final."

        Design: Corner/state_machines/terminated_arrangement_admits_no_transition
        """
        venue = make_venue(venue_code="NYSE")
        arrangement = make_arrangement(venue["id"])
        validate_success(api.arrangement_transition(arrangement["id"], {"to_status": "TERMINATED"}, CA))
        resp = api.arrangement_transition(arrangement["id"], {"to_status": "ACTIVE"}, CA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_adjacent_arrangement_windows_allowed(self, api):
        """PRD §3.2: "Overlap is judged on half-open windows, so pure
        adjacency — one window's `effective_to` exactly equal to the next
        window's `effective_from` — is allowed."

        Design: Difficulty/resource_temporal_overlap/arrangement_window_half_open_adjacency
        """
        venue = make_venue(venue_code="NYSE")
        make_arrangement(venue["id"],
                         effective_from="2026-08-01T00:00:00Z",
                         effective_to="2026-11-01T00:00:00Z")
        resp = api.create_arrangement({
            "venue_id": venue["id"],
            "effective_from": "2026-11-01T00:00:00Z",
            "effective_to": "2027-02-01T00:00:00Z",
            "pfof_tiers": flat_tier(0.12),
            "routing_fee_bps": 2,
        }, CA)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "NEGOTIATION", "adjacent half-open windows do not intersect"

    def test_overlapping_arrangement_window_rejected(self, api):
        """PRD §3.2: "the new window must not overlap any other arrangement of
        the same venue whose status is `NEGOTIATION`, `ACTIVE`, or `SUSPENDED`
        (otherwise `ERR_ARRANGEMENT_WINDOW_OVERLAP`, HTTP 409)" and "the
        overlap rule is also enforced at creation".

        Design: Difficulty/resource_temporal_overlap/arrangement_window_half_open_adjacency
        """
        venue = make_venue(venue_code="NYSE")
        make_arrangement(venue["id"],
                         effective_from="2026-08-01T00:00:00Z",
                         effective_to="2026-11-01T00:00:00Z")
        # One second of real overlap with the incumbent window.
        resp = api.create_arrangement({
            "venue_id": venue["id"],
            "effective_from": "2026-10-31T23:59:59Z",
            "effective_to": "2027-01-31T00:00:00Z",
            "pfof_tiers": flat_tier(0.12),
            "routing_fee_bps": 2,
        }, CA)
        validate_error(resp, ApiErrorId.ERR_ARRANGEMENT_WINDOW_OVERLAP)


class TestEmployeeRoleCannotCreateVenue:
    def test_employee_cannot_create_venue_returns_403(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint — or, for transition endpoints, not permitted for
        the requested transition target — is rejected with `ERR_FORBIDDEN`
        (HTTP 403)." PRD §4: POST /surveillance/venues is ComplianceAdmin-only.

        Design: Corner/rbac/employee_cannot_create_venue_returns_403
        """
        employee = make_employee(employee_ref="EMP-R1", full_name="Role One")
        resp = api.create_venue(
            {"venue_code": "NYSE", "name": "New York Stock Exchange", "venue_type": "EXCHANGE"},
            make_covered_employee_headers(employee["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
