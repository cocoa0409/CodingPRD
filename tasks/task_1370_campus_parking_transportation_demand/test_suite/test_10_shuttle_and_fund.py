"""Shuttle route planning/activation and the transportation fund ledger."""
from test_helpers import (
    ApiErrorId,
    create_fund,
    create_route,
    get_fund,
    get_route,
    issue_citation,
    create_lot,
    pay_citation,
    setup_patron_with_permit,
    validate_error,
    validate_success,
)


def _funded_setup():
    """Fund created first, then one full-term purchase (84000) so the fund's
    ledger observes the fee_paid cash event (PRD §3.10: balances "start at 0"
    at creation and thereafter track cash events)."""
    fund = create_fund()
    ctx = setup_patron_with_permit(name="B", plate="B111", campus_role="STUDENT",
                                   lot_code="LB")
    return ctx, fund


class TestFleetWindowBuffer:
    def _setup(self):
        fund = create_fund()
        r1 = create_route(fund["id"], route_code="BLUE_LOOP", fleet_group="FLEET_A",
                          service_window_start_minutes=480,
                          service_window_end_minutes=720,
                          projected_daily_ridership=400,
                          annual_operating_cost_cents=10000)
        return fund, r1

    def test_fleet_window_zero_gap_rejected(self, api, admin_headers):
        """PRD §3.8: "Routes sharing a `fleet_group` must respect a
        thirty-minute buffer between daily service windows: the gap between
        any two routes' windows in the same fleet group must be at least `30`
        minutes. This rule is checked against non-terminal routes (those in
        `PLANNED`, `ACTIVE`, or `SUSPENDED` status) at creation and re-checked
        against `ACTIVE` routes at activation; violations are rejected with
        `ERR_FLEET_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/fleet_window_buffer_conflict
        """
        fund, _ = self._setup()
        resp = api.create_shuttle_route(
            {
                "fund_id": fund["id"],
                "route_code": "RED_LOOP",
                "fleet_group": "FLEET_A",
                "service_window_start_minutes": 720,  # gap 720-720 = 0 < 30
                "service_window_end_minutes": 750,
                "headway_minutes": 30,
                "vehicle_capacity": 25,
                "projected_daily_ridership": 25,
                "annual_operating_cost_cents": 5000,
            },
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FLEET_WINDOW_CONFLICT, 409)

    def test_fleet_window_exact_buffer_accepted(self, api, admin_headers):
        """PRD §3.8: "the gap between any two routes' windows in the same
        fleet group must be at least `30` minutes."

        Design: Difficulty/resource_temporal_overlap/fleet_window_buffer_conflict
        """
        fund, _ = self._setup()
        resp = api.create_shuttle_route(
            {
                "fund_id": fund["id"],
                "route_code": "GREEN_LOOP",
                "fleet_group": "FLEET_A",
                "service_window_start_minutes": 750,  # gap 750-720 = 30 == buffer
                "service_window_end_minutes": 780,
                "headway_minutes": 30,
                "vehicle_capacity": 25,
                "projected_daily_ridership": 25,
                "annual_operating_cost_cents": 5000,
            },
            admin_headers,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "PLANNED", (
            f"a gap of exactly 30 minutes satisfies the buffer, got {data['status']}"
        )


class TestShuttleCoverageBoundary:
    def test_shuttle_coverage_equality_boundary(self, api, admin_headers):
        """PRD §3.8.1: "**Seat coverage** — `daily_capacity` must be greater
        than or equal to `projected_daily_ridership`; equality is sufficient.
        Failure is rejected with `ERR_INSUFFICIENT_SHUTTLE_CAPACITY`
        (HTTP 422)."
        PRD §3.8: "`planned_daily_runs` is the service window length in
        minutes (end minus start) divided by `headway_minutes`, with the
        quotient rounded down to the nearest whole number; `daily_capacity` is
        `planned_daily_runs` multiplied by `vehicle_capacity`."

        Design: Corner/calculations/shuttle_coverage_equality_boundary
        """
        _, fund = _funded_setup()  # 84000 available
        r1 = create_route(fund["id"], route_code="BLUE_LOOP", fleet_group="FLEET_A",
                          service_window_start_minutes=480,
                          service_window_end_minutes=960,
                          projected_daily_ridership=400,
                          annual_operating_cost_cents=10000)
        # floor(480 / 30) = 16 runs * 25 seats = 400 == projected 400.
        assert r1["daily_capacity"] == 400, (
            f"derived capacity must be 400, got {r1['daily_capacity']}"
        )
        r2 = create_route(fund["id"], route_code="RED_LOOP", fleet_group="FLEET_B",
                          service_window_start_minutes=480,
                          service_window_end_minutes=960,
                          projected_daily_ridership=401,
                          annual_operating_cost_cents=10000)

        ok = api.activate_shuttle_route(r1["id"], admin_headers)
        assert validate_success(ok, 200)["status"] == "ACTIVE", (
            "equality of capacity and projection is sufficient"
        )
        err = api.activate_shuttle_route(r2["id"], admin_headers)
        validate_error(err, ApiErrorId.ERR_INSUFFICIENT_SHUTTLE_CAPACITY, 422)


class TestFundingCheck:
    def test_insufficient_funding_rejected(self, api, admin_headers):
        """PRD §3.8.1: "**Funding** — the fund's `available_balance_cents`
        must be greater than or equal to `annual_operating_cost_cents`.
        Failure is rejected with `ERR_INSUFFICIENT_FUNDING` (HTTP 402)."

        Design: Corner/errors/insufficient_funding_rejected
        """
        fund = create_fund()  # all balances 0
        route = create_route(fund["id"], route_code="BLUE_LOOP", fleet_group="FLEET_A",
                             service_window_start_minutes=480,
                             service_window_end_minutes=960,
                             projected_daily_ridership=300,
                             annual_operating_cost_cents=100000)
        resp = api.activate_shuttle_route(route["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDING, 402)
        after = get_route(route["id"])
        assert after["status"] == "PLANNED", (
            f"a rejected activation leaves the route PLANNED, got {after['status']}"
        )


class TestSuspendResumeCommitment:
    def test_route_suspend_resume_keeps_single_commitment(self, api, admin_headers):
        """PRD §3.8.1: "On a first activation (`PLANNED → ACTIVE`) the fund's
        `committed_shuttle_funding_cents` increases by
        `annual_operating_cost_cents`. On a resume (`SUSPENDED → ACTIVE`) the
        commitment is unchanged — the route's cost was already committed at
        first activation and is not double-committed."
        PRD §3.8.1: "Suspending an `ACTIVE` route transitions it to
        `SUSPENDED`. The funding commitment is retained while the route is
        `SUSPENDED` — committed funding is the sum of
        `annual_operating_cost_cents` over routes with status `ACTIVE` or
        `SUSPENDED`, so suspension does not free the budget."

        Design: Corner/state_machines/route_suspend_resume_keeps_single_commitment
        """
        _, fund = _funded_setup()  # 84000 available
        route = create_route(fund["id"], route_code="BLUE_LOOP", fleet_group="FLEET_A",
                             service_window_start_minutes=480,
                             service_window_end_minutes=960,
                             projected_daily_ridership=300,
                             annual_operating_cost_cents=10000)

        r1 = validate_success(api.activate_shuttle_route(route["id"], admin_headers), 200)
        assert r1["status"] == "ACTIVE"
        r2 = validate_success(api.suspend_shuttle_route(route["id"], admin_headers), 200)
        assert r2["status"] == "SUSPENDED"
        r3 = validate_success(api.activate_shuttle_route(route["id"], admin_headers), 200)
        assert r3["status"] == "ACTIVE", "resume from SUSPENDED must succeed"

        fund_after = get_fund(fund["id"])
        assert fund_after["committed_shuttle_funding_cents"] == 10000, (
            f"a single commitment is retained through suspend/resume, "
            f"got {fund_after['committed_shuttle_funding_cents']}"
        )


class TestRidershipLogs:
    def test_ridership_logs_aggregate(self, api, admin_headers):
        """PRD §3.8.1: "A `ParkingAdmin` logs one day of boardings against a
        route by submitting `log_date` and `boardings`; the route's
        `ridership_total` increases by `boardings`."

        Design: Corner/endpoints/ridership_logs_aggregate
        """
        fund = create_fund()
        route = create_route(fund["id"], route_code="BLUE_LOOP", fleet_group="FLEET_A",
                             service_window_start_minutes=480,
                             service_window_end_minutes=960,
                             projected_daily_ridership=300,
                             annual_operating_cost_cents=10000)
        assert route["ridership_total"] == 0
        validate_success(
            api.create_ridership_log(route["id"],
                                     {"log_date": "2026-08-03", "boardings": 120},
                                     admin_headers),
            201,
        )
        resp = api.create_ridership_log(route["id"],
                                        {"log_date": "2026-08-04", "boardings": 85},
                                        admin_headers)
        data = validate_success(resp, 201)
        assert data["ridership_total"] == 205, (
            f"120 + 85 boardings must aggregate to 205, got {data['ridership_total']}"
        )


class TestFundAggregation:
    def test_fund_balance_aggregation(self, api, admin_headers):
        """PRD §3.10: "`permit_revenue_cents` increases by `fee_paid_cents` at
        every permit purchase and waitlist claim, and decreases by
        `refund_cents` at every permit cancellation." and
        "`citation_revenue_cents` increases by `fine_amount_cents` at citation
        payment only — cash basis." and "`committed_shuttle_funding_cents` is
        the sum of `annual_operating_cost_cents` over shuttle routes with
        status `ACTIVE` or `SUSPENDED` on this fund." and
        "`available_balance_cents` is `permit_revenue_cents` plus
        `citation_revenue_cents` minus `committed_shuttle_funding_cents`."

        Design: Corner/calculations/fund_balance_aggregation
        """
        fund = create_fund()  # created first so its ledger observes the cash events below
        ctx = setup_patron_with_permit(name="A", plate="A111", campus_role="STUDENT",
                                       lot_code="LA")  # permit revenue 84000
        lot_b = create_lot(lot_code="LB", name="Lot B", zone="REMOTE")
        citation = issue_citation(lot_b["id"], "A111", "NO_VALID_PERMIT")
        pay_citation(citation["id"], ctx["patron"]["id"])  # citation revenue 7500

        route = create_route(fund["id"], route_code="BLUE_LOOP", fleet_group="FLEET_A",
                             service_window_start_minutes=480,
                             service_window_end_minutes=960,
                             projected_daily_ridership=300,
                             annual_operating_cost_cents=10000)
        validate_success(api.activate_shuttle_route(route["id"], admin_headers), 200)

        f = get_fund(fund["id"])
        assert f["permit_revenue_cents"] == 84000, (
            f"got {f['permit_revenue_cents']}"
        )
        assert f["citation_revenue_cents"] == 7500, (
            f"cash-basis recognition at payment, got {f['citation_revenue_cents']}"
        )
        assert f["committed_shuttle_funding_cents"] == 10000, (
            f"got {f['committed_shuttle_funding_cents']}"
        )
        assert f["available_balance_cents"] == 81500, (
            f"84000 + 7500 - 10000 = 81500, got {f['available_balance_cents']}"
        )
