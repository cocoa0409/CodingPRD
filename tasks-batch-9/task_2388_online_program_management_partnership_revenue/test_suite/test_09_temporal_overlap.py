"""Two contended resources under opposite interval conventions."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    make_bursar_headers,
    make_partner_account_lead_headers,
)


def _approved_cip_program(api, ps_id, name, window_start, window_end, course_code):
    """An APPROVED program on CIP 52.0201 with one non-required course and no scope requirements."""
    program = fixtures.create_program(
        api,
        ps_id,
        program_name=name,
        cip_code="52.0201",
        launch_window_start=window_start,
        launch_window_end=window_end,
        required_service_domains=[],
    )
    fixtures.add_course(
        api,
        ps_id,
        program["id"],
        course_code=course_code,
        title=f"{course_code} Foundations",
        design_cost_cents=900000,
        required_for_launch=False,
    )
    fixtures.submit_program(api, ps_id, program["id"])
    return fixtures.approve_program(api, program["id"])


class TestCipExclusivityWindowsAreHalfOpen:
    @pytest.fixture
    def three_approved_programs_on_one_cip(self, api):
        """MSIS-A launched, MSIS-B touching its window, MSIS-C genuinely overlapping it."""
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]

        first = _approved_cip_program(api, ps_id, "MSIS-A", "2026-08-01", "2026-10-01", "SIS-501")
        fixtures.launch_program(api, ps_id, first["id"])
        touching = _approved_cip_program(api, ps_id, "MSIS-B", "2026-10-01", "2026-12-31", "SIS-502")
        overlapping = _approved_cip_program(
            api, ps_id, "MSIS-C", "2026-09-15", "2026-11-15", "SIS-503"
        )
        fixtures.set_clock(api, fixtures.CLOCK_OCT_1)

        return {
            "ps_id": ps_id,
            "pgX_id": first["id"],
            "pgY_id": touching["id"],
            "pgZ_id": overlapping["id"],
        }

    def test_touching_launch_windows_may_both_hold_the_same_discipline(
        self, api, three_approved_programs_on_one_cip
    ):
        """One window's end equals the other's start, so the second launch is allowed.

        PRD: "Because both windows are half-open, two windows that merely touch — one's
        `launch_window_end` equal to the other's `launch_window_start` — do **not** overlap, and
        both may launch."
        PRD: "The logical clock's date must fall inside the half-open launch window — on or after
        `launch_window_start` and strictly before `launch_window_end` — with a date outside that
        interval refused as `ERR_OUTSIDE_LAUNCH_WINDOW`."

        Design: Difficulty/resource_temporal_overlap/cip_exclusivity_windows_are_half_open_so_touching_launch_windows_coexist
        """
        context = three_approved_programs_on_one_cip
        launched = fixtures.launch_program(api, context["ps_id"], context["pgY_id"])

        assert launched["status"] == "LAUNCHED"
        assert fixtures.read_program(api, context["pgX_id"])["status"] == "LAUNCHED"

    def test_genuinely_overlapping_window_is_refused_on_the_exclusive_discipline(
        self, api, three_approved_programs_on_one_cip
    ):
        """MSIS-C's window straddles both live windows and cannot take the exclusive slot.

        PRD: "When a program's `cip_code` appears in the `exclusivity_cip_codes` of either
        partnership involved, no other program may already hold that same discipline code at the
        same institution over an overlapping window: specifically, a launch is blocked when some
        other program in `LAUNCHED`, `SUSPENDED` or `TEACH_OUT`, belonging to any partnership
        sharing this partnership's `university_ipeds_id`, carries the same `cip_code` and has a
        half-open launch window that overlaps this program's own half-open window."
        PRD: "A genuine overlap is refused with `ERR_CIP_EXCLUSIVITY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/cip_exclusivity_windows_are_half_open_so_touching_launch_windows_coexist
        """
        context = three_approved_programs_on_one_cip
        fixtures.launch_program(api, context["ps_id"], context["pgY_id"])

        response = api.post_program_lifecycle_action(
            context["pgZ_id"],
            factories.lifecycle_action_payload("LAUNCH"),
            headers=make_partner_account_lead_headers(context["ps_id"]),
        )

        validate_error(response, ApiErrorId.CIP_EXCLUSIVITY_CONFLICT.value, 409)
        assert fixtures.read_program(api, context["pgZ_id"])["status"] == "APPROVED"


class TestStatementPeriodsAreFullyClosed:
    @pytest.fixture
    def september_statement_then_mid_october(self, api):
        """The CALCULATED September statement, with the clock advanced to 2026-10-16."""
        context = fixtures.build_september_statement(api)
        fixtures.set_clock(api, fixtures.CLOCK_OCT_16)
        return context

    def test_a_shared_boundary_date_collides_with_the_existing_period(
        self, api, september_statement_then_mid_october
    ):
        """A period starting on the day the September period ends overlaps it.

        PRD: "Because periods are fully closed, two periods that merely touch, one's
        `period_end` equal to the other's `period_start`, **do** overlap, and the second is
        refused with `ERR_STATEMENT_PERIOD_OVERLAP`."
        PRD: "The requested period must also not overlap any existing statement of the same
        partnership in `CALCULATED`, `UNIVERSITY_APPROVED`, `DISPUTED`, `RESOLVED_ADJUSTED`,
        `STALE` or `REMITTED` — that is, in any status at all."

        Design: Difficulty/resource_temporal_overlap/statement_periods_are_fully_closed_so_a_shared_boundary_date_collides
        """
        context = september_statement_then_mid_october
        ps_id = context["ps_id"]
        payload = factories.statement_payload(
            fixtures.current_partnership_version(api, ps_id),
            period_start="2026-09-30",
            period_end="2026-10-15",
        )
        response = api.create_remittance_statement(ps_id, payload, headers=make_bursar_headers())

        validate_error(response, ApiErrorId.STATEMENT_PERIOD_OVERLAP.value, 409)

    def test_the_refused_cut_leaves_one_statement_on_the_calendar(
        self, api, september_statement_then_mid_october
    ):
        """The existing September statement is untouched and remains the only one.

        PRD: "A new statement is created in `CALCULATED`, records the acting `X-User-ID` as
        `authored_by_user_id`, sets `partnership_id`, initialises `adjustment_delta_cents` to 0
        and `requires_recalculation` to false, leaves `approved_by_user_id`,
        `resolved_by_user_id`, `dispute_reason`, `remittance_reference` and `remitted_at` null,
        and increments the partnership's `version` by one. Statements may be listed filtered by
        `partnership_id` and `status`."

        Design: Difficulty/resource_temporal_overlap/statement_periods_are_fully_closed_so_a_shared_boundary_date_collides
        """
        context = september_statement_then_mid_october
        ps_id = context["ps_id"]
        payload = factories.statement_payload(
            fixtures.current_partnership_version(api, ps_id),
            period_start="2026-09-30",
            period_end="2026-10-15",
        )
        api.create_remittance_statement(ps_id, payload, headers=make_bursar_headers())

        existing = fixtures.read_statement(api, context["st_id"])
        assert existing["period_start"] == "2026-09-01"
        assert existing["period_end"] == "2026-09-30"
        assert existing["status"] == "CALCULATED"

        _, meta = validate_paginated(
            api.list_remittance_statements({"partnership_id": ps_id}, headers=make_bursar_headers())
        )
        assert meta["total_count"] == 1
