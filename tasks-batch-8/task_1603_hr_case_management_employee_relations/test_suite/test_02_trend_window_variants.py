"""Trend snapshot dual-variant tests (Difficulty rule 1, instance 2)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    make_hr_analyst_headers,
    setup_intake_channel,
    setup_employee,
    setup_investigator,
    set_clock,
    run_case_to_closed,
    validate_success,
    get_success_data,
)


def _setup_location_with_workforce(location_code: str):
    """Create 5 ACTIVE + 3 ON_LEAVE employees in location; return (reporter, inv trio, subject).

    The investigators' bound employee records are placed in "HQ" — outside the
    measured location — because PRD §3.7 counts every in-scope employee record
    in the headcount ("the number of employees in scope — the same
    manager-chain or location test applied to employee records — whose
    employment_status is ACTIVE"); the pinned rates below are the PRD-derived
    figures for exactly 5 ACTIVE (ROLLING_90D) and 5 ACTIVE + 3 ON_LEAVE
    (CALENDAR_QUARTER) employees in the measured location.
    """
    actives = [setup_employee(location_code=location_code) for _ in range(5)]
    for _ in range(3):
        setup_employee(location_code=location_code, employment_status="ON_LEAVE")
    reporter = setup_employee(location_code="HQ", department="HR")
    _, inv1 = setup_investigator(location_code="HQ")
    _, inv2 = setup_investigator(location_code="HQ")
    _, inv3 = setup_investigator(location_code="HQ")
    subject = actives[0]
    return reporter, subject, inv1, inv2, inv3


class TestTrendWindowVariants:
    def test_rolling_90d_uses_active_headcount_only(self):
        """PRD §3.7: "Under `ROLLING_90D`, the headcount is the number of
        employees in scope — the same manager-chain or location test applied to
        employee records — whose `employment_status` is `ACTIVE`, evaluated as
        of the snapshot instant."

        Design: Difficulty/dual_variant_calc/trend_window_variants_diverge_on_same_cases
        """
        set_clock("2026-08-01T00:00:00Z")
        channel = setup_intake_channel(
            channel_code="WEB_PORTAL",
            display_name="Web Portal",
            default_category="POLICY_VIOLATION",
            default_severity="LOW",
            sla_business_days=10,
        )
        reporter, subject, inv1, inv2, inv3 = _setup_location_with_workforce("SF")
        # Drive one case to CLOSED
        run_case_to_closed(
            channel["id"], subject["id"], inv1, inv2, inv3,
            reporter_employee_id=reporter["id"],
            category="POLICY_VIOLATION", severity="LOW",
            action_type="NO_ACTION", severity_points=0,
            substantiation_outcome="UNSUBSTANTIATED",
        )
        set_clock("2026-08-20T00:00:00Z")
        resp = api_client.create_trend_snapshot(
            {"scope_type": "LOCATION", "scope_key": "SF", "window_kind": "ROLLING_90D"},
            make_hr_analyst_headers(),
        )
        ts = validate_success(resp, 201)
        assert ts["closed_case_count"] == 1
        # 1 case / 5 ACTIVE employees * 100 = 20.00
        assert ts["case_rate_per_100"] == pytest.approx(20.00, abs=1e-6), (
            f"ROLLING_90D rate expected 20.00 (1/5 ACTIVE), got {ts['case_rate_per_100']}"
        )

    def test_calendar_quarter_widens_denominator(self):
        """PRD §3.7: "Under `CALENDAR_QUARTER`, the denominator is wider:
        employees in scope whose `employment_status` is `ACTIVE` or `ON_LEAVE`
        and whose `hire_date` falls on or before the quarter's final day.
        Because the quarterly variant counts more people for identical case
        data, it generally yields the lower rate."

        Design: Difficulty/dual_variant_calc/trend_window_variants_diverge_on_same_cases
        """
        set_clock("2026-08-01T00:00:00Z")
        channel = setup_intake_channel(
            channel_code="WEB_PORTAL",
            display_name="Web Portal",
            default_category="POLICY_VIOLATION",
            default_severity="LOW",
            sla_business_days=10,
        )
        reporter, subject, inv1, inv2, inv3 = _setup_location_with_workforce("SF")
        run_case_to_closed(
            channel["id"], subject["id"], inv1, inv2, inv3,
            reporter_employee_id=reporter["id"],
            category="POLICY_VIOLATION", severity="LOW",
            action_type="NO_ACTION", severity_points=0,
            substantiation_outcome="UNSUBSTANTIATED",
        )
        set_clock("2026-08-20T00:00:00Z")
        resp = api_client.create_trend_snapshot(
            {"scope_type": "LOCATION", "scope_key": "SF", "window_kind": "CALENDAR_QUARTER"},
            make_hr_analyst_headers(),
        )
        ts = validate_success(resp, 201)
        assert ts["closed_case_count"] == 1
        # 1 case / (5 ACTIVE + 3 ON_LEAVE) * 100 = 12.50
        assert ts["case_rate_per_100"] == pytest.approx(12.50, abs=1e-6), (
            f"CALENDAR_QUARTER rate expected 12.50 (1/8), got {ts['case_rate_per_100']}"
        )

    def test_two_window_variants_diverge_on_same_closed_cases(self):
        """PRD §3.7: "The rate's denominator is where the two window variants
        diverge." Plus the pinned formula: "The per-scope `case_rate_per_100`
        divides the closed-case count by the headcount, multiplies by one
        hundred, and rounds half-up to two decimal places."

        Two cases closed in location SF (5 ACTIVE + 3 ON_LEAVE):
        - ROLLING_90D: 2/5 * 100 = 40.00
        - CALENDAR_QUARTER: 2/8 * 100 = 25.00

        Design: Difficulty/dual_variant_calc/trend_window_variants_diverge_on_same_cases
        """
        set_clock("2026-08-01T00:00:00Z")
        channel = setup_intake_channel(
            channel_code="WEB_PORTAL",
            display_name="Web Portal",
            default_category="POLICY_VIOLATION",
            default_severity="LOW",
            sla_business_days=10,
        )
        reporter, subject, inv1, inv2, inv3 = _setup_location_with_workforce("SF")
        for _ in range(2):
            run_case_to_closed(
                channel["id"], subject["id"], inv1, inv2, inv3,
                reporter_employee_id=reporter["id"],
                category="POLICY_VIOLATION", severity="LOW",
                action_type="NO_ACTION", severity_points=0,
                substantiation_outcome="UNSUBSTANTIATED",
            )
        set_clock("2026-08-20T00:00:00Z")
        r90 = validate_success(api_client.create_trend_snapshot(
            {"scope_type": "LOCATION", "scope_key": "SF", "window_kind": "ROLLING_90D"},
            make_hr_analyst_headers(),
        ), 201)
        cq = validate_success(api_client.create_trend_snapshot(
            {"scope_type": "LOCATION", "scope_key": "SF", "window_kind": "CALENDAR_QUARTER"},
            make_hr_analyst_headers(),
        ), 201)
        assert r90["closed_case_count"] == 2
        assert cq["closed_case_count"] == 2
        assert r90["case_rate_per_100"] == pytest.approx(40.00, abs=1e-6)
        assert cq["case_rate_per_100"] == pytest.approx(25.00, abs=1e-6)
        assert r90["case_rate_per_100"] != cq["case_rate_per_100"]
