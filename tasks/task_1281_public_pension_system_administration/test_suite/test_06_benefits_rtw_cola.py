"""Benefits in payment: return-to-work surveillance, reinstatement, COLA."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_retirement_app,
    assert_benefit,
    create_employer,
    create_fund,
    create_member,
    create_retirement_app,
    current_application_version,
    five_year_line_specs,
    make_member_headers,
    reconcile_member_history,
    record_death,
    review_retirement_app,
    set_clock,
    setup_approved_retirement,
    six_year_line_specs,
    submit_retirement_app,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST


class TestReturnToWorkBoundary:
    def test_earnings_exactly_at_limit_do_not_suspend(self, api):
        """PRD §3.7: "Landing exactly on the limit does not suspend — the
        comparison is strict."
        PRD §3.1: "it is the calendar-year ceiling on what a retiree may earn
        before the benefit suspends, and suspension triggers only when
        year-to-date earnings strictly exceed it — a retiree whose earnings
        land exactly on the limit keeps the benefit."

        Design: Difficulty/boundary_precision_check/rtw_earnings_exactly_at_limit_does_not_suspend
        """
        ctx = setup_approved_retirement(full_name="Boundary Beth")
        member, benefit = ctx["member"], ctx["benefit"]
        headers = make_member_headers(member["id"])
        validate_success(api.report_earnings(
            benefit["id"], {"calendar_year": 2026, "amount_cents": 1_500_000},
            headers), 200)
        at_limit = validate_success(api.report_earnings(
            benefit["id"], {"calendar_year": 2026, "amount_cents": 1_500_000},
            headers), 200)
        assert at_limit["rtw_ytd_earnings_cents"] == 3_000_000
        assert at_limit["status"] == "ACTIVE", (
            "YTD exactly equal to the limit must NOT suspend (strict >)")
        member_after = validate_success(api.get_member(member["id"], ANALYST),
                                        200)
        assert member_after["status"] == "RETIRED"

    def test_one_cent_over_limit_suspends_benefit_and_member(self, api):
        """PRD §3.7: "If the resulting total strictly exceeds the fund's
        `earnings_limit_annual_cents`, the benefit moves `ACTIVE → SUSPENDED`
        and the member moves `RETIRED → SUSPENDED_RTW` in the same stroke."

        Design: Difficulty/boundary_precision_check/rtw_earnings_exactly_at_limit_does_not_suspend
        """
        ctx = setup_approved_retirement(full_name="Boundary Beth")
        member, benefit = ctx["member"], ctx["benefit"]
        headers = make_member_headers(member["id"])
        validate_success(api.report_earnings(
            benefit["id"], {"calendar_year": 2026, "amount_cents": 3_000_000},
            headers), 200)
        over = validate_success(api.report_earnings(
            benefit["id"], {"calendar_year": 2026, "amount_cents": 1},
            headers), 200)
        assert over["rtw_ytd_earnings_cents"] == 3_000_001
        assert over["status"] == "SUSPENDED"
        member_after = validate_success(api.get_member(member["id"], ANALYST),
                                        200)
        assert member_after["status"] == "SUSPENDED_RTW"


class TestSuspendReinstateCycle:
    def test_new_year_reset_then_reinstate_completes_cycle(self, api):
        """PRD §3.7: "Earnings reports are accepted on benefits in `ACTIVE` or
        `SUSPENDED` — a suspended retiree may still be working and still
        accruing toward the limit"
        PRD §3.7: "When the report's `calendar_year` differs from the
        benefit's `rtw_calendar_year`, the bucket resets: `rtw_calendar_year`
        takes the new year and `rtw_ytd_earnings_cents` starts again from 0."
        PRD §3.7: "Reinstatement moves the benefit `SUSPENDED → ACTIVE` and
        the member `SUSPENDED_RTW → RETIRED` in the same request."

        Design: Corner/state_machines/benefit_suspend_reinstate_cycle
        """
        ctx = setup_approved_retirement(full_name="Suspend Sue")
        member, benefit = ctx["member"], ctx["benefit"]
        headers = make_member_headers(member["id"])
        suspended = validate_success(api.report_earnings(
            benefit["id"], {"calendar_year": 2026, "amount_cents": 3_000_001},
            headers), 200)
        assert suspended["status"] == "SUSPENDED"

        set_clock("2027-01-05T00:00:00Z")
        reset = validate_success(api.report_earnings(
            benefit["id"], {"calendar_year": 2027, "amount_cents": 100_000},
            headers), 200)
        assert reset["rtw_calendar_year"] == 2027
        assert reset["rtw_ytd_earnings_cents"] == 100_000
        assert reset["status"] == "SUSPENDED", (
            "100,000 <= 3,000,000: the reset report alone must not unsuspend")

        reinstated = validate_success(
            api.reinstate_benefit(benefit["id"], ANALYST), 200)
        assert reinstated["status"] == "ACTIVE"
        member_after = validate_success(api.get_member(member["id"], ANALYST),
                                        200)
        assert member_after["status"] == "RETIRED"

    def test_reinstate_active_benefit_returns_invalid_state(self, api):
        """PRD §3.7: "A suspended benefit can be reinstated by an analyst when
        two conditions hold: the benefit is in `SUSPENDED` (reinstating an
        `ACTIVE` benefit is `ERR_INVALID_STATE`), and the
        `rtw_ytd_earnings_cents` for the current calendar year is within —
        that is, at most — the fund's `earnings_limit_annual_cents`."

        Design: Corner/validations/reinstate_active_benefit_returns_invalid_state
        """
        ctx = setup_approved_retirement(full_name="Reinstate Rex",
                                        line_specs_fn=five_year_line_specs)
        res = api.reinstate_benefit(ctx["benefit"]["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_benefit(ctx["benefit"]["id"], ANALYST),
                                 200)
        assert after["status"] == "ACTIVE"


class TestEarningsOnTerminatedBenefit:
    def test_earnings_report_on_terminated_benefit_rejected(self, api):
        """PRD §3.7: "a report against a `TERMINATED` benefit is
        `ERR_BENEFIT_NOT_ACTIVE` (HTTP 409)."
        PRD §3.7: "Every Benefit of the member in `ACTIVE` or `SUSPENDED`
        moves to `TERMINATED`."

        Design: Corner/validations/earnings_on_terminated_benefit_returns_error
        """
        ctx = setup_approved_retirement(full_name="Terminated Tom",
                                        line_specs_fn=five_year_line_specs)
        member, benefit = ctx["member"], ctx["benefit"]
        record_death(member["id"], "2026-08-01")
        terminated = validate_success(api.get_benefit(benefit["id"], ANALYST),
                                      200)
        assert terminated["status"] == "TERMINATED"
        res = api.report_earnings(
            benefit["id"], {"calendar_year": 2026, "amount_cents": 100},
            ANALYST)
        validate_error(res, ApiErrorId.ERR_BENEFIT_NOT_ACTIVE)
        after = validate_success(api.get_benefit(benefit["id"], ANALYST), 200)
        assert after["rtw_ytd_earnings_cents"] == 0


def _approve_member_at(api, employer_id, full_name, line_specs_fn):
    """Enroll, credit six years, and approve a SINGLE_LIFE retirement at the
    current logical clock. Returns (member, benefit)."""
    member = create_member(employer_id, full_name=full_name,
                           date_of_birth="1965-01-01", hire_date="2016-01-01")
    reconcile_member_history(employer_id, line_specs_fn(member["id"]))
    app = create_retirement_app(member["id"], "SINGLE_LIFE")
    submit_retirement_app(app["id"], member["id"])
    review_retirement_app(app["id"], "REVIEW_OK", "analyst-1")
    approve_retirement_app(app["id"], current_application_version(app["id"]),
                           "approver-1")
    benefits, _meta = validate_paginated(
        api.list_member_benefits(member["id"], ANALYST))
    return member, benefits[0]


class TestColaBoundary:
    def test_twelve_months_active_is_eligible_eleven_is_skipped(self, api):
        """PRD §3.7: "a benefit is adjusted only when `months_active` is at
        least 12; exactly 12 is eligible."
        PRD §3.7: "Each eligible benefit's `monthly_amount_cents` becomes its
        prior amount times one plus the `cola_rate_pct`, rounded half-up to
        whole cents, its `cola_applied_count` increments by 1, and its
        `version` increments by 1. Ineligible benefits are skipped. The run
        reports back `applied_count` and `skipped_count`."

        Design: Corner/calculations/cola_twelve_month_boundary_and_rounding
        """
        set_clock("2025-08-15T00:00:00Z")
        fund = create_fund()
        employer_a = create_employer(name="City Hall", employer_code="CH")
        _ma, benefit_a = _approve_member_at(api, employer_a["id"], "Cola Ann",
                                            six_year_line_specs)
        assert benefit_a["effective_date"] == "2025-08-01"
        assert benefit_a["monthly_amount_cents"] == 46_750

        set_clock("2025-09-15T00:00:00Z")
        employer_b = create_employer(name="County Library", employer_code="CL")
        _mb, benefit_b = _approve_member_at(api, employer_b["id"], "Cola Bob",
                                            six_year_line_specs)
        assert benefit_b["effective_date"] == "2025-09-01"

        set_clock("2026-08-01T00:00:00Z")
        result = validate_success(api.run_cola(fund["id"], ADMIN), 200)
        assert result["applied_count"] == 1
        assert result["skipped_count"] == 1

        after_a = validate_success(api.get_benefit(benefit_a["id"], ANALYST),
                                   200)
        assert after_a["monthly_amount_cents"] == 47_919, (
            f"round_half_up(46,750 * 1.025) = 47,919, "
            f"got {after_a['monthly_amount_cents']}")
        assert after_a["cola_applied_count"] == 1

        after_b = validate_success(api.get_benefit(benefit_b["id"], ANALYST),
                                   200)
        assert after_b["monthly_amount_cents"] == 46_750, (
            "11 months active at run time: benefit must be skipped")
        assert after_b["cola_applied_count"] == 0
