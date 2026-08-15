"""Reference data (programs, catalog, overhead schedules), the accounting
calendar (period creation, adjacency, reopen guards), authentication, and
read-access rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    create_accounting_period_payload,
    create_capital_program_payload,
    create_catalog_entry,
    create_overhead_schedule_payload,
    create_period,
    create_program,
    create_schedule,
    create_work_order_payload,
    create_ciac,
    create_reg_asset,
    close_period,
    get_success_data,
    reopen_period,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
CLERK = TEST_USERS["clerk_headers"]
RATES = TEST_USERS["rates_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestAuthentication:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or not one of these seven values, or whose `X-User-ID` header is missing or empty on any mutating endpoint, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        payload = create_capital_program_payload(code="CAP-NOAUTH")
        resp = api.create_capital_program(payload, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

        resp2 = api.create_capital_program(
            payload, headers=build_user_headers("x-1", "SuperUser"))
        validate_error(resp2, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestProgramClose:
    def test_program_close_blocked_by_open_work_orders(self, api):
        """PRD §3.1: "Closing a program is a `Controller` action and is only possible once every work order raised against it has reached a terminal state: if any work order of the program still stands at `DRAFT`, `SUBMITTED`, `RETURNED`, `AUTHORIZED`, `IN_PROGRESS`, `SUSPENDED`, or `COMPLETED`, the close is rejected with `ERR_PROGRAM_HAS_OPEN_WORK_ORDERS`."

        Design: Corner/validations/program_close_blocked_by_open_work_orders
        """
        program = create_program(code="CAP-PCLOSE", authorized_amount_cents=5_000_000)
        wo = get_success_data(api.create_work_order(
            create_work_order_payload(program_id=program["id"],
                                      title="Blocking order",
                                      initial_estimated_cost_cents=100_000),
            ENGINEER))
        assert wo["status"] == "DRAFT"

        resp = api.close_capital_program(program["id"], CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_HAS_OPEN_WORK_ORDERS, 422)

        cancelled = get_success_data(api.cancel_work_order(wo["id"], SUPERVISOR))
        assert cancelled["status"] == "CANCELLED"

        closed = validate_success(api.close_capital_program(program["id"], CONTROLLER))
        assert closed["status"] == "CLOSED"


class TestAuditorReadAccess:
    def test_auditor_read_access_allowed(self, api):
        """PRD §2.1: "All seven roles may read any resource; write capabilities are partitioned as described below and summarized per endpoint in §4."

        Design: Corner/rbac/auditor_read_access_allowed
        """
        program = create_program(code="CAP-AUD", authorized_amount_cents=5_000_000)
        fetched = validate_success(api.get_capital_program(program["id"], AUDITOR))
        assert fetched["code"] == "CAP-AUD"


class TestUnitCatalogPagination:
    def test_unit_catalog_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order; fixed-asset-unit lists additionally break ties by `line_no` ascending, so the lines of a single closeout appear in their submitted order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/unit_catalog_list_pagination_envelope
        """
        create_catalog_entry(asset_class="POLE", standard_cost_cents=10_000,
                             annual_depreciation_rate_pct=4.0)
        create_catalog_entry(asset_class="TRANSFORMER", standard_cost_cents=50_000,
                             annual_depreciation_rate_pct=12.0)
        create_catalog_entry(asset_class="METER", standard_cost_cents=8_000,
                             annual_depreciation_rate_pct=6.0)

        page1, meta1 = validate_paginated(
            api.list_unit_catalog(AUDITOR, params={"limit": 2, "offset": 0}))
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2

        page2, meta2 = validate_paginated(
            api.list_unit_catalog(AUDITOR, params={"limit": 2, "offset": 2}))
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert len(page2) == 1


class TestInitialStates:
    def test_child_entities_start_in_initial_states(self, api):
        """PRD §3.6: "The agreement is born `PLEDGED` with `received_cents`, `applied_cents`, `forfeited_cents`, and `refunded_cents` all unset."
        PRD §3.7: "The proposal is born `PROPOSED` with `remaining_cents` initialized to the full `original_cents`, the caller recorded as `proposed_by_user_id`, and `approved_by_user_id` unset."
        PRD §3.2: "A period's `status` cycles `OPEN` → `CLOSED` → `REOPENED` → `CLOSED` under the `Controller`'s close and reopen actions, whose full mechanics — accrual, compensation, and the CIAC sweep — are detailed in §3.9."

        Design: Corner/state_machines/child_entities_start_in_initial_states
        """
        program = create_program(code="CAP-INI")
        wo = get_success_data(api.create_work_order(
            create_work_order_payload(program_id=program["id"], title="Init order",
                                      initial_estimated_cost_cents=100_000),
            ENGINEER))

        ciac = create_ciac(wo["id"], pledged_cents=50_000,
                           pledge_expiry_at="2026-12-31T00:00:00Z")
        assert ciac["status"] == "PLEDGED"

        ra = create_reg_asset(description="Deferral", original_cents=9_000,
                              amortization_months=3)
        assert ra["status"] == "PROPOSED"
        assert ra["remaining_cents"] == 9_000

        period = create_period()
        assert period["status"] == "OPEN"


class TestOverheadScheduleOverlap:
    def test_overhead_schedule_touching_bounds_and_gaps_allowed(self, api):
        """PRD §3.1: "Intervals for the same cost-type-and-order-type pair must never overlap; a new schedule whose interval intersects an existing one for the same pair is rejected with `ERR_OVERHEAD_SCHEDULE_OVERLAP`, while intervals that merely touch — one row's `effective_to` equal to another's `effective_from` — do not constitute an overlap."

        Design: Difficulty/resource_temporal_overlap/overhead_schedule_half_open_overlap_rules
        """
        s1 = create_schedule(cost_type="LABOR", order_type="CAPITAL",
                             rate_pct=15.0, effective_from="2026-01-01",
                             effective_to="2026-07-01")
        assert s1["status"] == "ACTIVE"

        # Touching bound: new.effective_from == existing.effective_to (half-open).
        s2 = validate_success(api.create_overhead_schedule(
            create_overhead_schedule_payload(
                cost_type="LABOR", order_type="CAPITAL", rate_pct=16.0,
                effective_from="2026-07-01"), ADMIN), 201)
        assert s2["effective_from"] == "2026-07-01"

        # Same dates, different cost_type: a different pair, so no conflict.
        s3 = validate_success(api.create_overhead_schedule(
            create_overhead_schedule_payload(
                cost_type="EQUIPMENT", order_type="CAPITAL", rate_pct=14.0,
                effective_from="2026-06-01", effective_to="2026-08-01"),
            ADMIN), 201)
        assert s3["cost_type"] == "EQUIPMENT"

        # Gaps are allowed: two MATERIAL rows with a hole between them.
        s4 = validate_success(api.create_overhead_schedule(
            create_overhead_schedule_payload(
                cost_type="MATERIAL", order_type="CAPITAL", rate_pct=5.0,
                effective_from="2026-01-01", effective_to="2026-03-01"),
            ADMIN), 201)
        s5 = validate_success(api.create_overhead_schedule(
            create_overhead_schedule_payload(
                cost_type="MATERIAL", order_type="CAPITAL", rate_pct=6.0,
                effective_from="2026-06-01"), ADMIN), 201)
        assert s4["effective_to"] == "2026-03-01"
        assert s5["effective_from"] == "2026-06-01"

    def test_overhead_schedule_interior_overlap_rejected(self, api):
        """PRD §3.1: "Intervals for the same cost-type-and-order-type pair must never overlap; a new schedule whose interval intersects an existing one for the same pair is rejected with `ERR_OVERHEAD_SCHEDULE_OVERLAP`, while intervals that merely touch — one row's `effective_to` equal to another's `effective_from` — do not constitute an overlap."

        Design: Difficulty/resource_temporal_overlap/overhead_schedule_half_open_overlap_rules
        """
        create_schedule(cost_type="LABOR", order_type="CAPITAL", rate_pct=15.0,
                        effective_from="2026-01-01", effective_to="2026-07-01")
        # Interior intersection with the existing LABOR/CAPITAL row.
        resp = api.create_overhead_schedule(
            create_overhead_schedule_payload(
                cost_type="LABOR", order_type="CAPITAL", rate_pct=14.0,
                effective_from="2026-06-01", effective_to="2026-08-01"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_OVERHEAD_SCHEDULE_OVERLAP, 422)


class TestPeriodAdjacency:
    def test_period_gap_and_overlap_rejected(self, api):
        """PRD §3.2: "Every subsequent period must adjoin its predecessor exactly: its `start_date` must be precisely one day after the latest existing period's `end_date`, with gaps and overlaps alike rejected as `ERR_PERIOD_NOT_ADJACENT`."

        Design: Difficulty/resource_temporal_overlap/accounting_period_strict_adjacency_rules
        """
        p1 = create_period()
        close_period(p1["id"])

        # One-day gap: starts 2026-09-02 instead of 2026-09-01.
        resp_gap = api.create_accounting_period(
            create_accounting_period_payload(period_no=9,
                                             start_date="2026-09-02",
                                             end_date="2026-09-30"), ADMIN)
        validate_error(resp_gap, ApiErrorId.ERR_PERIOD_NOT_ADJACENT, 422)

        # Overlap: starts inside the closed period.
        resp_overlap = api.create_accounting_period(
            create_accounting_period_payload(period_no=9,
                                             start_date="2026-08-15",
                                             end_date="2026-09-15"), ADMIN)
        validate_error(resp_overlap, ApiErrorId.ERR_PERIOD_NOT_ADJACENT, 422)

    def test_period_exact_adjacency_accepted(self, api):
        """PRD §3.2: "Every subsequent period must adjoin its predecessor exactly: its `start_date` must be precisely one day after the latest existing period's `end_date`, with gaps and overlaps alike rejected as `ERR_PERIOD_NOT_ADJACENT`."
        PRD §3.2: "The first period of the calendar may begin on any date."

        Design: Difficulty/resource_temporal_overlap/accounting_period_strict_adjacency_rules
        """
        p1 = create_period()
        close_period(p1["id"])

        p2 = validate_success(api.create_accounting_period(
            create_accounting_period_payload(period_no=9,
                                             start_date="2026-09-01",
                                             end_date="2026-09-30"), ADMIN), 201)
        assert p2["status"] == "OPEN"
        assert p2["start_date"] == "2026-09-01"


class TestPeriodReopenGuards:
    def test_period_reopen_guards(self, api):
        """PRD §3.2: "Creation additionally requires that every existing period already be `CLOSED`; attempting to open a new period while another stands `OPEN` or `REOPENED` fails with `ERR_PERIOD_ALREADY_OPEN`, since at most one period may occupy `OPEN` or `REOPENED` at any time."
        PRD §3.9: "Reopening is the compensating mirror, available to a `Controller` under two guards: no accounting period may currently stand `OPEN` or `REOPENED`, else `ERR_PERIOD_ALREADY_OPEN`, and the target must be the most recently created `CLOSED` period, else `ERR_PERIOD_REOPEN_NOT_LATEST`."

        Design: Corner/state_machines/period_reopen_guards
        """
        p1 = create_period()
        # Create while P1 is still OPEN.
        resp_create = api.create_accounting_period(
            create_accounting_period_payload(period_no=9,
                                             start_date="2026-09-01",
                                             end_date="2026-09-30"), ADMIN)
        validate_error(resp_create, ApiErrorId.ERR_PERIOD_ALREADY_OPEN, 409)

        close_period(p1["id"])
        p2 = create_period(period_no=9, start_date="2026-09-01",
                           end_date="2026-09-30")
        close_period(p2["id"])
        p3 = create_period(period_no=10, start_date="2026-10-01",
                           end_date="2026-10-31")

        # Reopen while P3 is OPEN.
        resp_open = api.reopen_accounting_period(p2["id"], CONTROLLER)
        validate_error(resp_open, ApiErrorId.ERR_PERIOD_ALREADY_OPEN, 409)

        close_period(p3["id"])
        # P1 is closed but is not the most recently created CLOSED period.
        resp_latest = api.reopen_accounting_period(p1["id"], CONTROLLER)
        validate_error(resp_latest, ApiErrorId.ERR_PERIOD_REOPEN_NOT_LATEST, 409)

        reopened = validate_success(api.reopen_accounting_period(p3["id"], CONTROLLER))
        assert reopened["status"] == "REOPENED"
