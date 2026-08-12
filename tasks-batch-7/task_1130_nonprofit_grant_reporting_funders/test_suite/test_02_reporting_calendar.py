"""Activation and the generated reporting calendar (PRD §3.2, §2.11, §2.3)."""
from test_helpers import (
    TEST_USERS,
    activate_grant,
    add_budget_line,
    add_fund,
    assert_report,
    create_funder,
    create_grant,
    list_reports,
    setup_active_grant,
    setup_draft_grant,
    start_report,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    ApiErrorId,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
DIRECTOR = TEST_USERS["director_headers"]


class TestReportingCalendar:
    def test_report_calendar_initial_state_scheduled(self, api):
        """PRD §3.2: "First, the system generates the grant's full reporting
        calendar: one `Report` row per period implied by the grant's
        `reporting_frequency`, tiling the inclusive range from `start_date`
        through `end_date`. Every generated row starts in `SCHEDULED` status.
        Rows are numbered by a 1-based `period_index`; each carries its
        `period_start` (inclusive) and `period_end` (inclusive date); the last
        period of the current calendar is marked `period_type` `FINAL` and every
        earlier period is `INTERIM`. Each row's `due_date` is computed as its
        `period_end` plus `interim_report_due_days` for an `INTERIM` row or plus
        `final_report_due_days` for the `FINAL` row."

        Design: Corner/state_machines/report_calendar_initial_state_scheduled
        """
        ctx = setup_draft_grant()
        resp = api.activate_grant(ctx["grant"]["id"], DIRECTOR)
        validate_success(resp)
        resp = api.list_reports(ctx["grant"]["id"], OFFICER)
        reports, meta = validate_paginated(resp)
        assert len(reports) == 4, f"QUARTERLY 1-year grant must yield 4 periods, got {len(reports)}"
        for row in reports:
            assert_report(row)
            assert row["status"] == "SCHEDULED"
        assert [r["period_index"] for r in reports] == [1, 2, 3, 4]
        assert reports[0]["period_type"] == "INTERIM"
        assert reports[0]["due_date"][:10] == "2026-09-30"  # 2026-08-31 + 30d
        assert reports[3]["period_type"] == "FINAL"
        assert reports[3]["due_date"][:10] == "2027-08-29"  # 2027-05-31 + 90d

    def test_report_start_before_period_rejected(self, api):
        """PRD §3.4: "Two preconditions guard the transition: the grant must be
        `ACTIVE` (otherwise `ERR_GRANT_NOT_ACTIVE`, or `ERR_GRANT_SUSPENDED` when
        the grant is suspended), and the current logical time must have reached
        the report's `period_start` (otherwise `ERR_INVALID_STATE`)."
        PRD §2.11: "At server startup the clock reads exactly
        `2026-05-01T00:00:00Z`; it never falls back to wall-clock time."

        Design: Corner/state_machines/report_start_before_period_rejected
        """
        ctx = setup_active_grant()
        r1 = ctx["reports"][0]
        # Clock is still at the server default 2026-05-01T00:00:00Z, which
        # precedes period_start 2026-06-01.
        resp = api.start_report(r1["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_report(r1["id"], OFFICER))
        assert after["status"] == "SCHEDULED"


class TestReportPagination:
    def test_reports_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned in a
        single page: it defaults to 10, with a minimum accepted value of 1 and a
        maximum of 100. The `offset` parameter specifies how many items to skip
        before the page begins and defaults to 0."
        PRD §2.3: "The reporting-calendar listing of a grant's reports is the one
        exception to the default presentation ordering: rows are returned ordered
        by `period_index` ascending. Paginated list responses carry `limit`,
        `offset`, `total_count`, and `has_more` inside the `meta` object of the
        envelope."

        Design: Corner/endpoints/reports_list_pagination_envelope
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]

        reports, meta = validate_paginated(api.list_reports(gid, OFFICER))
        assert len(reports) == 4
        assert meta["total_count"] == 4
        assert meta["has_more"] is False

        page1, meta1 = validate_paginated(
            api.list_reports(gid, OFFICER, params={"limit": 2})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 4
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_reports(gid, OFFICER, params={"limit": 2, "offset": 2})
        )
        assert meta2["has_more"] is False
        assert page2[0]["period_index"] == 3  # ordered by period_index ASC
