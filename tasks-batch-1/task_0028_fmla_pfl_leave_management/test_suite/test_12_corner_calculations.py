"""Corner — calculations section: eligibility threshold boundaries, pool-charge
filtering, certification response window.
"""
import datetime as _dt

from test_helpers import (
    ApiErrorId,
    create_employee,
    create_employer,
    create_provider,
    evaluate_eligibility,
    list_notices_for_case,
    record_interval,
    set_clock,
    setup_approved_case,
    submit_case,
    TEST_USERS,
    validate_error,
)


class TestTenureBoundaryExactly12MonthsPasses:
    def test_employee_hired_365_days_before_request_passes_tenure_check(self, api):
        """PRD §3.3: "The first threshold is twelve months of service: the difference between `requested_start_at` and the employee's `hire_date`, expressed in days divided by thirty and floored to a whole number of months, must be at least twelve."

        Design: Corner/calculations/tenure_boundary_exactly_12_months_passes
        """
        employer = create_employer(state_code="FED")
        emp = create_employee(
            employer["id"],
            hire_date="2025-06-01T00:00:00.000Z",
            hours_worked_trailing_12mo=2000,
            home_state_code="FED",
        )
        set_clock("2026-05-01T00:00:00.000Z")
        case = submit_case(
            emp["id"],
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        case_after = evaluate_eligibility(case["id"])
        # 2026-06-01 minus 2025-06-01 = 365 days; floor(365/30) = 12.
        assert case_after["status"] == "CERTIFICATION_PENDING", (
            f"hire_date 365 days before requested_start_at → tenure = 12 months exactly, passes; "
            f"got {case_after['status']!r}"
        )
        assert case_after["tenure_months_at_request"] == 12
        assert case_after["hours_at_request"] == 2000


class TestTenureBelow12MonthsReturnsIneligible:
    def test_employee_hired_9_months_before_request_returns_ineligible(self, api):
        """PRD §3.3: "The case advances to `CERTIFICATION_PENDING` only when both thresholds hold; otherwise the case is moved straight to `DENIED`."
        PRD §3.3: "The threshold-failure branch returns `ERR_INELIGIBLE` to the caller when the call was driven against an employee who fails one or both checks at the moment of evaluation."

        Design: Corner/calculations/tenure_below_12_months_returns_ineligible
        """
        employer = create_employer(state_code="FED")
        emp = create_employee(
            employer["id"],
            hire_date="2025-09-01T00:00:00.000Z",  # ~9 months before 2026-06-01
            hours_worked_trailing_12mo=2000,
            home_state_code="FED",
        )
        set_clock("2026-05-01T00:00:00.000Z")
        case = submit_case(
            emp["id"],
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        res = api.evaluate_eligibility(case["id"], TEST_USERS["hr_admin_headers"])
        validate_error(res, ApiErrorId.ERR_INELIGIBLE)


class TestPoolChargeNonConcurrentPflZero:
    def test_qualifying_exigency_with_fed_employer_pfl_charge_zero(self, api):
        """PRD §3.4: "`pfl_concurrent` is true when the employer's `pfl_enabled` is true, the employee's `home_state_code` equals the employer's `state_code`, and the case's `qualifying_reason` is one of `OWN_SERIOUS_HEALTH_CONDITION`, `FAMILY_SERIOUS_HEALTH_CONDITION`, or `NEW_CHILD_BONDING`"
        PRD §3.6: "When `pfl_concurrent` is false, the PFL charge is zero."

        Design: Corner/calculations/pool_charge_non_concurrent_pfl_zero
        """
        bundle = setup_approved_case(
            employer_state="FED",  # pfl_enabled false
            qualifying_reason="QUALIFYING_EXIGENCY",  # not in concurrent set
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
            cert_expected_duration_weeks=4,
        )
        assert bundle.case["pfl_concurrent"] is False
        set_clock("2026-06-01T00:00:00.000Z")
        interval = record_interval(
            bundle.case["id"],
            "2026-06-01T00:00:00.000Z",
            "2026-06-08T00:00:00.000Z",
            40,
        )
        assert interval["fmla_hours_charged"] == 40
        assert interval["pfl_hours_charged"] == 0, (
            f"non-concurrent case must have pfl_hours_charged = 0; "
            f"got {interval['pfl_hours_charged']!r}"
        )


class TestCertResponseWindow15Days:
    def test_certification_demand_notice_response_due_at_is_sent_at_plus_15_days(self, api):
        """PRD §3.4: "On entering `CERTIFICATION_PENDING`, the server auto-creates a `CERTIFICATION_DEMAND` notice whose `response_due_at` is fifteen days after `sent_at`"
        PRD §2.10: "The two demand-style notices — `CERTIFICATION_DEMAND` and `RECERTIFICATION_REQUEST` — set `response_due_at` to fifteen days after `sent_at`"

        Design: Corner/calculations/cert_response_window_15_days
        """
        employer = create_employer(state_code="FED")
        emp = create_employee(employer["id"])
        set_clock("2026-05-01T00:00:00.000Z")
        case = submit_case(
            emp["id"],
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        evaluate_eligibility(case["id"])
        notices = list_notices_for_case(case["id"], notice_type="CERTIFICATION_DEMAND")
        assert len(notices) == 1, (
            f"exactly 1 CERTIFICATION_DEMAND notice expected; got {len(notices)}"
        )
        notice = notices[0]
        sent = _dt.datetime.fromisoformat(notice["sent_at"].replace("Z", "+00:00"))
        due = _dt.datetime.fromisoformat(notice["response_due_at"].replace("Z", "+00:00"))
        delta = due - sent
        assert delta == _dt.timedelta(days=15), (
            f"response_due_at must equal sent_at + 15 days; got delta={delta!r}"
        )
