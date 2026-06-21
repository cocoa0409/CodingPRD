"""Difficulty Rule 4 — transitive_cascade.

Multi-hop side-effect cascades where each hop is caused by the previous one,
not by the original trigger: clock advance → ledger DELINQUENT → case protection
lapses; first interval on APPROVED case → case ACTIVE → employee ON_LEAVE.
"""
from test_helpers import (
    get_case,
    get_employee,
    record_interval,
    set_clock,
    setup_active_case_with_first_interval,
    setup_approved_case,
)


class TestClockAdvanceCascadeToProtectionLapses:
    """PRD §3.7: clock advance past period_end + 30 days drives any unpaid ledger to
    DELINQUENT; each newly-DELINQUENT row cascades to LeaveCase.job_restoration_protected
    = false.
    """

    def test_clock_advance_past_grace_marks_ledger_delinquent_and_lapses_protection(self, api):
        """PRD §3.7: "When the server's logical clock advances past `period_end` plus thirty days and `employee_owes_cents` is strictly greater than zero, the row transitions from `PENDING` or `PARTIAL` to `DELINQUENT`."
        PRD §3.7: "It also cascades: each newly-`DELINQUENT` row sets the corresponding `LeaveCase.job_restoration_protected` to false, because employer-paid coverage has lapsed for the period and statutory restoration protection lapses with it."
        PRD §3.8: "on success the response carries the new `current_utc` and the `delinquent_ledger_ids` array of every ledger row that flipped to `DELINQUENT` as a side effect"

        Design: Difficulty/transitive_cascade/clock_advance_cascade_to_employee_restoration_deadline
        """
        # Build approved + ACTIVE case with one interval. Ledger row covers
        # 2026-06-01..2026-07-01; no payment made. Then advance clock past
        # 2026-07-31 (period_end + 30 days).
        bundle = setup_active_case_with_first_interval(
            employer_state="FED",
            employer_premium_share_pct=0.50,
            monthly_premium_total_cents=100000,
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            interval_start="2026-06-01T00:00:00.000Z",
            interval_end="2026-06-30T00:00:00.000Z",
            interval_hours=160,
            cert_expected_duration_weeks=10,
        )
        # Advance clock past 2026-07-31 (period_end of 2026-07-01 + 30 days).
        clock_resp = set_clock("2026-08-15T00:00:00.000Z")
        # Hop 1: ledger row(s) flipped to DELINQUENT.
        assert isinstance(clock_resp["delinquent_ledger_ids"], list), (
            "clock response must carry delinquent_ledger_ids array"
        )
        assert len(clock_resp["delinquent_ledger_ids"]) >= 1, (
            f"expected at least one ledger to flip DELINQUENT; got {clock_resp['delinquent_ledger_ids']!r}"
        )
        # Hop 2: case.job_restoration_protected is false (caused by hop 1).
        case_after = get_case(bundle["case"]["id"])
        assert case_after["job_restoration_protected"] is False, (
            f"DELINQUENT cascade must lapse job_restoration_protected on the case; "
            f"got {case_after['job_restoration_protected']!r}"
        )

    def test_clock_advance_without_outstanding_balance_does_not_mark_delinquent(self, api):
        """PRD §3.7: "When the server's logical clock advances past `period_end` plus thirty days and `employee_owes_cents` is strictly greater than zero, the row transitions from `PENDING` or `PARTIAL` to `DELINQUENT`."

        Design: Difficulty/transitive_cascade/clock_advance_cascade_to_employee_restoration_deadline
        """
        # If employee_owes_cents is zero (no outstanding obligation), advancing
        # the clock past period_end + 30 days must NOT flip the row to DELINQUENT
        # and must NOT lapse protection. Use an employee who is not enrolled in
        # the health plan so no ledger row is ever created.
        from test_helpers import create_employee, create_employer, create_provider

        employer = create_employer(state_code="FED")
        create_provider()
        emp = create_employee(
            employer["id"], health_plan_enrolled=False, home_state_code="FED"
        )
        # Reuse setup machinery by toggling enrollment off — easier: build the
        # bundle without health plan via setup_approved_case override.
        bundle = setup_approved_case(
            employer_state="FED",
            health_plan_enrolled=False,
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            cert_expected_duration_weeks=10,
        )
        set_clock("2026-06-01T00:00:00.000Z")
        record_interval(
            bundle.case["id"],
            "2026-06-01T00:00:00.000Z",
            "2026-06-30T00:00:00.000Z",
            160,
        )
        clock_resp = set_clock("2026-08-15T00:00:00.000Z")
        assert clock_resp["delinquent_ledger_ids"] == [], (
            f"With no ledger rows (health_plan_enrolled=false), nothing flips DELINQUENT; "
            f"got {clock_resp['delinquent_ledger_ids']!r}"
        )
        case_after = get_case(bundle.case["id"])
        # Without DELINQUENT cascade, protection remains true (no flip).
        assert case_after["job_restoration_protected"] is True


class TestFirstIntervalCascadeToEmployeeOnLeave:
    """PRD §3.6: first interval on an APPROVED case drives the case to ACTIVE and
    the employee to ON_LEAVE; same trigger sets job_restoration_deadline to
    requested_start_at + 84 days.
    """

    def test_first_interval_drives_case_to_active_and_employee_to_on_leave(self, api):
        """PRD §3.6: "The first interval recorded against an `APPROVED` case drives the case to `ACTIVE` and sets `Employee.employment_status` to `ON_LEAVE`; at the same moment the server sets the employee's `job_restoration_deadline` to `requested_start_at` plus 84 days (which is twelve weeks)."

        Design: Difficulty/transitive_cascade/first_interval_cascade_to_employee_on_leave
        """
        bundle = setup_approved_case(
            employer_state="FED",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            cert_expected_duration_weeks=10,
        )
        set_clock("2026-06-01T00:00:00.000Z")
        record_interval(
            bundle.case["id"],
            "2026-06-01T00:00:00.000Z",
            "2026-06-08T00:00:00.000Z",
            40,
        )
        # Hop 1: case ACTIVE.
        case_after = get_case(bundle.case["id"])
        assert case_after["status"] == "ACTIVE", (
            f"first interval on APPROVED case must drive to ACTIVE; got {case_after['status']!r}"
        )
        # Hop 2: employee ON_LEAVE; deadline = requested_start_at + 84 days.
        emp_after = get_employee(bundle.employee["id"])
        assert emp_after["employment_status"] == "ON_LEAVE", (
            f"employment_status must become ON_LEAVE; got {emp_after['employment_status']!r}"
        )
        assert emp_after["job_restoration_deadline"] == "2026-08-24T00:00:00.000Z", (
            f"job_restoration_deadline must be requested_start_at + 84 days = 2026-08-24; "
            f"got {emp_after['job_restoration_deadline']!r}"
        )

    def test_first_interval_required_to_advance_subsequent_intervals_keep_case_active(self, api):
        """PRD §3.6: "Subsequent intervals leave the case in `ACTIVE`."

        Design: Difficulty/transitive_cascade/first_interval_cascade_to_employee_on_leave
        """
        bundle = setup_approved_case(
            employer_state="FED",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            cert_expected_duration_weeks=10,
        )
        set_clock("2026-06-01T00:00:00.000Z")
        record_interval(
            bundle.case["id"],
            "2026-06-01T00:00:00.000Z",
            "2026-06-08T00:00:00.000Z",
            40,
        )
        # Subsequent (second) interval — case must remain ACTIVE.
        record_interval(
            bundle.case["id"],
            "2026-06-08T00:00:00.000Z",
            "2026-06-15T00:00:00.000Z",
            40,
        )
        case_after = get_case(bundle.case["id"])
        assert case_after["status"] == "ACTIVE", (
            f"subsequent interval must leave case in ACTIVE; got {case_after['status']!r}"
        )
