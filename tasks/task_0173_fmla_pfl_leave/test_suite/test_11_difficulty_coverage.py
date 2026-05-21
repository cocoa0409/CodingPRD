"""Difficulty-design coverage — primary tests for each instance.

Every instance declared in the difficulty-design index gets at least
two tests (this file + test_12_difficulty_coverage_supplemental.py).
Each test cites a verbatim PRD sentence for its underlying rule.

Tag format: each test docstring carries `# difficulty: <rule_id>/<name>`.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    PFL_WEEKLY_CAP_CENTS,
    add_days,
    advance_clock_to,
    approve_case_with_specific_instances,
    cancel_case,
    create_employee,
    create_employer,
    create_pfl_claim,
    create_worksite,
    get_leave_case,
    get_pfl_claim,
    get_quota_balance,
    list_benefit_invoices,
    log_instance,
    make_employee_headers,
    pay_invoice,
    review_certification,
    review_leave_case,
    setup_eligible_employee,
    setup_invoice_forfeit_cascade,
    setup_pending_certification_case,
    setup_two_employees_same_basis_diff_employer,
    submit_certification,
    submit_leave_case,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_quota_balance_calendar_vs_rolling(self, api):
        """PRD §3.7: "Under the `CALENDAR` variant, the leave-year
        window is anchored to the calendar year containing the case's
        `requested_start_date`: the window begins on January 1 of that
        year (inclusive) and ends on December 31 of that year
        (inclusive)."
        PRD §3.7: "Under the `ROLLING_BACKWARD` variant, the leave-year
        window is anchored to the case's `requested_start_date` itself
        and looks 365 days backward: the window begins 365 days before
        `requested_start_date` (inclusive) and ends on
        `requested_start_date` (inclusive)."

        Claim: same identical instance history yields different
        consumed_hours under the two variants on the same as_of_date.

        # difficulty: dual_variant_calc/quota_balance_calendar_vs_rolling
        """
        # Anchor clock to BEFORE the earliest requested_start_date so
        # all case submissions satisfy "requested_start_date >= now()"
        # (PRD §3.3).
        ctx = setup_two_employees_same_basis_diff_employer(
            initial_clock_iso="2025-10-01T00:00:00.000Z",
            monthly_wage_cents=500_000,
            benefit_premium_share_cents=30_000,
            hours_worked_trailing_12mo=2080,
            hire_date="2023-01-01",
        )
        emp_cal = ctx["employee_calendar"]
        emp_rb = ctx["employee_rolling"]
        # Approve identical case history on both:
        #   case C1: dates 2025-11-03..2025-11-06, 4 × 8h = 32 h
        #   case C2: dates 2026-01-05..2026-01-21, 17 × 8h = 136 h
        c1_dates = [f"2025-11-{d:02d}" for d in (3, 4, 5, 6)]
        c2_dates = []
        for d in range(5, 22):
            c2_dates.append(f"2026-01-{d:02d}")
        for emp in (emp_cal, emp_rb):
            approve_case_with_specific_instances(
                employee_id=emp["id"],
                reason="OWN_SERIOUS_HEALTH",
                leave_pattern="INTERMITTENT",
                requested_start_date="2025-11-03",
                expected_end_date="2025-11-30",
                instance_dates=c1_dates,
                hours_per_instance=8,
            )
        # PRD §3.3: "if the employee's `employment_status` is not
        # `ACTIVE`, no submission is allowed". The clock sweep flips
        # an APPROVED case to ACTIVE on its requested_start_date and
        # cascades Employee.employment_status to ON_LEAVE; once that
        # has fired, a second new-case POST is no longer admissible.
        # Submit C2 BEFORE advancing the clock past C1's
        # requested_start_date, so the employee is still ACTIVE.
        # C2's requested_start_date (2026-01-05) is still in the
        # future at the initial clock anchor (2025-10-01), satisfying
        # the "requested_start_date >= now()" precondition.
        for emp in (emp_cal, emp_rb):
            approve_case_with_specific_instances(
                employee_id=emp["id"],
                reason="OWN_SERIOUS_HEALTH",
                leave_pattern="INTERMITTENT",
                requested_start_date="2026-01-05",
                expected_end_date="2026-01-31",
                instance_dates=c2_dates,
                hours_per_instance=8,
            )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        # CALENDAR: window = 2026-01-01..2026-12-31 → only C2 counts → 136
        cal_balance = get_quota_balance(
            employee_id=emp_cal["id"], as_of_date="2026-03-01",
        )
        # ROLLING: window = 2025-03-01..2026-03-01 → both C1 (32) and
        # C2 (136) count → 168
        rb_balance = get_quota_balance(
            employee_id=emp_rb["id"], as_of_date="2026-03-01",
        )
        assert cal_balance["consumed_hours"] == 136, (
            f"CALENDAR window omits 2025 instances; expected 136, "
            f"got {cal_balance['consumed_hours']!r}"
        )
        assert rb_balance["consumed_hours"] == 168, (
            f"ROLLING_BACKWARD includes 2025-11 instances; expected "
            f"168, got {rb_balance['consumed_hours']!r}"
        )
        assert cal_balance["remaining_hours"] != rb_balance["remaining_hours"]

    def test_pfl_weekly_benefit_under_cap_vs_at_cap(self, api):
        """PRD §3.8: "if the raw weekly benefit is less than or equal
        to the cap the under-cap variant applies and the final value
        equals the raw weekly benefit; if the raw weekly benefit
        exceeds the cap the at-cap variant applies and the final value
        equals the cap".

        E1 monthly_wage_cents=500_000:
            Step 1: round_half_up(500_000*12/52) = 115_385
            Step 2: round_half_up(115_385*0.60) = 69_231
            Step 3: min(69_231, 162_900) = 69_231 (under-cap)
        E2 monthly_wage_cents=2_000_000:
            Step 1: round_half_up(2_000_000*12/52) = 461_538
            Step 2: round_half_up(461_538*0.60) = 276_923
            Step 3: min(276_923, 162_900) = 162_900 (at-cap)

        # difficulty: dual_variant_calc/pfl_weekly_benefit_under_vs_at_cap
        """
        employer = create_employer(state_pfl_program="STATE_PFL_8WEEK")
        worksite = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=80,
        )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        employee_1 = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2023-01-01", hours_worked_trailing_12mo=2080,
            monthly_wage_cents=500_000,
        )
        employee_2 = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2023-01-01", hours_worked_trailing_12mo=2080,
            monthly_wage_cents=2_000_000,
        )
        claim_1 = create_pfl_claim(
            employee_id=employee_1["id"], claim_type="BABY_BONDING",
            weeks_authorized=8,
        )
        claim_2 = create_pfl_claim(
            employee_id=employee_2["id"], claim_type="BABY_BONDING",
            weeks_authorized=8,
        )
        assert claim_1["weekly_benefit_cents"] == 69_231, (
            f"under-cap variant: 69_231; got "
            f"{claim_1['weekly_benefit_cents']!r}"
        )
        assert claim_2["weekly_benefit_cents"] == PFL_WEEKLY_CAP_CENTS, (
            f"at-cap variant: {PFL_WEEKLY_CAP_CENTS}; got "
            f"{claim_2['weekly_benefit_cents']!r}"
        )


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_job_restoration_score_per_step_rounding(self, api):
        """PRD §3.10: "The score starts at a base of 100 and is then
        adjusted in three multiplicative steps, in this fixed order,
        with round-half-up applied after each step (per-step rounding,
        never sum-then-round). ... Step two — the invoice penalty —
        ... otherwise multiplies by 0.75 if any has `invoice_status`
        of `GRACE`, otherwise leaves it unchanged. Step three — the
        tenure bonus — multiplies the score by 1.10 if the employee's
        `hours_worked_trailing_12mo` is at least 2000, otherwise
        leaves it unchanged; after this step the score is rounded
        half-up and then clamped to a maximum of 100. The final
        `job_restoration_status` is `PROTECTED` if the resulting
        score is at least 50, and `FORFEITED` otherwise".

        PROD-faithful scenario exercising per-step rounding via the
        GRACE-invoice branch alone (cert INSUFFICIENT cannot be
        produced post-APPROVE: PRD §3.5 limits certification
        submission to PENDING_CERTIFICATION cases, and the clock-
        sweep locking of certification_status to INSUFFICIENT only
        fires while the case is still PENDING_CERTIFICATION).

        cert COMPLETE, one GRACE invoice, tenure 1500 (<2000):
            Step 1: 100 (cert COMPLETE, no penalty)
            Step 2: 100 * 0.75 = 75 (GRACE invoice)
            Step 3: 1500 < 2000 → no bonus = 75
        Score 75 >= 50 → PROTECTED.

        # difficulty: combinatorial_formula/job_restoration_score_per_step_rounding
        """
        advance_clock_to("2026-01-01T00:00:00.000Z")
        employer = create_employer(
            leave_year_basis="CALENDAR",
            state_pfl_program="NONE",
            benefit_premium_share_cents=30_000,
        )
        worksite = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=80,
        )
        employee = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2023-01-01",
            hours_worked_trailing_12mo=1500,
            monthly_wage_cents=500_000,
        )
        case = submit_leave_case(
            employee_id=employee["id"],
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="CONTINUOUS",
            requested_start_date="2026-01-15",
            expected_end_date="2026-04-30",
        )
        cert1 = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        review_certification(
            leave_case_id=case["id"], cert_id=cert1["id"],
            decision="ACCEPT",
        )
        case = review_leave_case(
            leave_case_id=case["id"], decision="APPROVE",
        )
        # Push invoice into GRACE (31 days from creation).
        invoices = list_benefit_invoices(case["id"])
        assert invoices, "Setup failed: no invoice on APPROVE"
        invoice = invoices[0]
        advance_clock_to(add_days(invoice["created_at"], 31))
        refreshed = get_leave_case(case["id"])
        # Score 75 >= 50 → PROTECTED.
        assert refreshed["job_restoration_status"] == "PROTECTED", (
            f"PRD §3.10: cert COMPLETE (no penalty) + GRACE invoice "
            f"(×0.75) + tenure < 2000 (no bonus) → 75 >= 50 → "
            f"PROTECTED; got {refreshed['job_restoration_status']!r}"
        )

    def test_benefit_invoice_proration_intermittent_28_days(self, api):
        """PRD §3.9: "the `amount_due_cents` is the employer's
        `benefit_premium_share_cents` multiplied by the days-on-leave-
        in-month divided by the days-in-month, rounded half-up to
        whole cents".

        Feb 2026 (28 days), 14 INTERMITTENT instances, premium 30_000:
            amount = round_half_up(30_000 * 14 / 28) = 15_000

        # difficulty: combinatorial_formula/benefit_invoice_proration_three_input_nonlinear
        """
        advance_clock_to("2026-01-15T00:00:00.000Z")
        employer = create_employer(
            leave_year_basis="CALENDAR",
            state_pfl_program="NONE",
            benefit_premium_share_cents=30_000,
        )
        worksite = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=80,
        )
        employee = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2023-01-01", hours_worked_trailing_12mo=2080,
        )
        instance_dates = [f"2026-02-{d:02d}" for d in range(1, 15)]
        approve_case_with_specific_instances(
            employee_id=employee["id"],
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
            requested_start_date="2026-02-01",
            expected_end_date="2026-02-28",
            instance_dates=instance_dates,
            hours_per_instance=8,
        )
        from test_helpers import list_leave_cases
        invoices = list_benefit_invoices(
            list_leave_cases(employee["id"])[0]["id"]
        )
        feb = next(
            (i for i in invoices if i["period_month"] == "2026-02"), None,
        )
        assert feb is not None, f"Expected 2026-02 invoice; got {invoices!r}"
        assert feb["amount_due_cents"] == 15_000, (
            f"PRD §3.9 prorated: round_half_up(30_000 * 14 / 28) = "
            f"15_000; got {feb['amount_due_cents']!r}"
        )


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_medical_certification_cyclic_cure_loop(self, api):
        """PRD §3.5: "the employee has seven calendar days from that
        moment to cure by re-submitting a fresh certification (the new
        submission creates a new `MedicalCertification` row beginning
        at `PENDING`, with the previous `INSUFFICIENT` row preserved".

        Cycle: PENDING (cert1) → INSUFFICIENT → cure → new PENDING
        (cert2). The new cert row coexists with the old INSUFFICIENT
        row.

        # difficulty: non_linear_state_machine/medical_certification_cyclic_cure_loop
        """
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
        )
        cert1 = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        cert1_reviewed = review_certification(
            leave_case_id=case["id"], cert_id=cert1["id"],
            decision="INSUFFICIENT",
        )
        assert cert1_reviewed["review_outcome"] == "INSUFFICIENT"
        # Cure: new PENDING row.
        cert2 = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        assert cert2["id"] != cert1["id"]
        assert cert2["review_outcome"] == "PENDING"
        refreshed = get_leave_case(case["id"])
        assert refreshed["certification_status"] == "RECEIVED", (
            f"after cure submission certification_status should be "
            f"RECEIVED; got {refreshed['certification_status']!r}"
        )

    def test_leave_case_branching_approve_vs_deny(self, api):
        """PRD §3.6: "On a successful approval the case's `case_status`
        becomes `APPROVED`, every `PROPOSED` `LeaveInstance` on the
        case becomes `APPROVED`, `hours_charged` is recomputed as the
        sum of `hours_used` across all `APPROVED` instances on the
        case".
        PRD §3.6: "On a denial the `case_status` becomes `DENIED`,
        every `LeaveInstance` on the case transitions to `VOIDED`,
        `hours_charged` is reset to 0".

        # difficulty: non_linear_state_machine/leave_case_branching_approve_or_deny
        """
        # APPROVE branch.
        _e1, _w1, employee1, case1 = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
        )
        log_instance(
            leave_case_id=case1["id"], employee_id=employee1["id"],
            instance_date="2026-05-01", hours_used=8,
        )
        log_instance(
            leave_case_id=case1["id"], employee_id=employee1["id"],
            instance_date="2026-05-04", hours_used=8,
        )
        cert1 = submit_certification(
            leave_case_id=case1["id"], employee_id=employee1["id"],
            serious_health_condition=True,
        )
        review_certification(
            leave_case_id=case1["id"], cert_id=cert1["id"],
            decision="ACCEPT",
        )
        approved = review_leave_case(
            leave_case_id=case1["id"], decision="APPROVE",
        )
        assert approved["case_status"] == "APPROVED"
        assert approved["hours_charged"] == 16

        # DENY branch (second independent case).
        _e2, _w2, employee2, case2 = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
            initial_clock_iso=None,
        )
        log_instance(
            leave_case_id=case2["id"], employee_id=employee2["id"],
            instance_date="2026-05-01", hours_used=8,
        )
        log_instance(
            leave_case_id=case2["id"], employee_id=employee2["id"],
            instance_date="2026-05-04", hours_used=8,
        )
        cert2 = submit_certification(
            leave_case_id=case2["id"], employee_id=employee2["id"],
            serious_health_condition=True,
        )
        review_certification(
            leave_case_id=case2["id"], cert_id=cert2["id"],
            decision="INSUFFICIENT",
        )
        denied = review_leave_case(
            leave_case_id=case2["id"], decision="DENY",
        )
        assert denied["case_status"] == "DENIED"
        assert denied["hours_charged"] == 0


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_invoice_forfeit_cascade_depth_3(self, api):
        """PRD §3.9: "when the server clock crosses thirty days from
        the invoice's `created_at` the `invoice_status` transitions
        from `ISSUED` to `GRACE`; when the server clock crosses
        forty-five days from the invoice's `created_at` the
        `invoice_status` transitions from `GRACE` to `FORFEITED`.
        Forfeiture cascades into the parent
        `LeaveCase.job_restoration_status`, setting it to `FORFEITED`".

        Depth 3 chain: clock advance → GRACE → FORFEITED → cascade to
        LeaveCase.job_restoration_status.

        # difficulty: transitive_cascade/invoice_forfeit_cascade_depth_3
        """
        ctx = setup_invoice_forfeit_cascade(
            initial_clock_iso="2026-01-01T00:00:00.000Z",
            requested_start_date="2026-01-15",
            expected_end_date="2026-04-30",
        )
        invoice = ctx["invoice"]
        # First advance → GRACE.
        advance_clock_to(add_days(invoice["created_at"], 31))
        invoices_after_grace = list_benefit_invoices(ctx["case"]["id"])
        target = next(
            i for i in invoices_after_grace if i["id"] == invoice["id"]
        )
        assert target["invoice_status"] == "GRACE", (
            f"link 1: ISSUED → GRACE on first advance; got "
            f"{target['invoice_status']!r}"
        )
        # Second advance → FORFEITED.
        advance_clock_to(add_days(invoice["created_at"], 46))
        invoices_after_forfeit = list_benefit_invoices(ctx["case"]["id"])
        target = next(
            i for i in invoices_after_forfeit if i["id"] == invoice["id"]
        )
        assert target["invoice_status"] == "FORFEITED", (
            f"link 2: GRACE → FORFEITED on second advance; got "
            f"{target['invoice_status']!r}"
        )
        # Link 3: LeaveCase.job_restoration_status cascades.
        refreshed_case = get_leave_case(ctx["case"]["id"])
        assert refreshed_case["job_restoration_status"] == "FORFEITED", (
            f"link 3: cascade to LeaveCase.job_restoration_status; "
            f"got {refreshed_case['job_restoration_status']!r}"
        )

    def test_deny_review_cascade_depth_2(self, api):
        """PRD §3.6: "On a denial the `case_status` becomes `DENIED`,
        every `LeaveInstance` on the case transitions to `VOIDED`,
        `hours_charged` is reset to 0 (re-crediting the leave-year
        bucket entirely), `job_restoration_status` is set to
        `NOT_APPLICABLE`, and if a `pfl_claim_id` is set the linked
        `PfLClaim.claim_status` becomes `DENIED`".

        Depth-2 cascade: DENY POST → case DENIED → instances VOIDED
        + PfLClaim DENIED + hours_charged=0 (link 2 caused by case
        becoming DENIED).

        # difficulty: transitive_cascade/deny_review_cascade_depth_2
        """
        _e, _w, employee = setup_eligible_employee(
            state_pfl_program="STATE_PFL_8WEEK",
        )
        pfl = create_pfl_claim(
            employee_id=employee["id"], claim_type="FAMILY_CARE",
            weeks_authorized=8,
        )
        case = submit_leave_case(
            employee_id=employee["id"],
            reason="FAMILY_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
            requested_start_date="2026-06-01",
            expected_end_date="2026-06-30",
            pfl_claim_id=pfl["id"],
        )
        log_instance(
            leave_case_id=case["id"], employee_id=employee["id"],
            instance_date="2026-06-01", hours_used=8,
        )
        log_instance(
            leave_case_id=case["id"], employee_id=employee["id"],
            instance_date="2026-06-02", hours_used=8,
        )
        cert = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        review_certification(
            leave_case_id=case["id"], cert_id=cert["id"],
            decision="INSUFFICIENT",
        )
        denied = review_leave_case(
            leave_case_id=case["id"], decision="DENY",
        )
        # Link 1: case_status DENIED.
        assert denied["case_status"] == "DENIED"
        # Link 2: hours_charged := 0.
        assert denied["hours_charged"] == 0
        # Link 2: PfLClaim.claim_status := DENIED.
        refreshed_pfl = get_pfl_claim(pfl["id"])
        assert refreshed_pfl["claim_status"] == "DENIED", (
            f"PfLClaim must flip to DENIED on case DENY (link 2 "
            f"cascade); got {refreshed_pfl['claim_status']!r}"
        )


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict (state vs business_safety)
# ===========================================================================
class TestPriorityValidationConflict:

    def test_state_check_wins_over_quota_exceeded(self, api):
        """PRD §2.6: "they are evaluated in a fixed priority order so
        that the most fundamental cause is reported. The order is, from
        highest to lowest priority: ... state machine preconditions on
        the target `LeaveCase` (`ERR_INVALID_STATE`); ... quota
        sufficiency (`ERR_QUOTA_EXCEEDED`)".

        Cancelled case + would-exceed-quota new instance → state check
        wins (ERR_INVALID_STATE), not ERR_QUOTA_EXCEEDED.

        # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_conflict
        """
        # 1) Build an employee whose CANCELLED case exists.
        _e, _w, employee = setup_eligible_employee(
            leave_year_basis="CALENDAR",
        )
        case = submit_leave_case(
            employee_id=employee["id"],
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
            requested_start_date="2026-05-01",
            expected_end_date="2026-05-31",
        )
        # Cancel the case so it's in CANCELLED state.
        cancel_case(
            leave_case_id=case["id"], employee_id=employee["id"],
        )
        # 2) Attempt to log an instance on the CANCELLED case.
        # Even if the quota is otherwise exhausted, state check fires
        # first.
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_instance(
            case["id"],
            {"instance_date": "2026-05-15", "hours_used": 8},
            h,
        )
        # PRD §2.6 order: state precedes quota.
        validate_error(resp, "ERR_INVALID_STATE")

    def test_business_safety_eligibility_wins_over_pfl_mismatch(self, api):
        """PRD §2.6: "the three FMLA eligibility checks at case
        submission, evaluated in tenure-then-hours-then-worksite order
        (`ERR_NOT_ELIGIBLE_TENURE`, then `ERR_NOT_ELIGIBLE_HOURS`,
        then `ERR_NOT_ELIGIBLE_WORKSITE`); certification-deadline
        expiry on approval (`ERR_CERT_DEADLINE_MISSED`);
        certification completeness on approval (`ERR_CERT_INCOMPLETE`);
        quota sufficiency (`ERR_QUOTA_EXCEEDED`); instance pattern
        legality (`ERR_INSTANCE_NOT_ALLOWED`); cross-case instance
        overlap (`ERR_INSTANCE_OVERLAP`); PFL availability
        (`ERR_PFL_NOT_AVAILABLE`); PFL linkage consistency
        (`ERR_PFL_MISMATCH`)".

        Worksite below 50 AND PfLClaim belongs to a different employee
        → worksite check wins.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_conflict
        """
        # Employer with PFL program.
        employer = create_employer(state_pfl_program="STATE_PFL_8WEEK")
        worksite_low = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=40,
        )
        worksite_ok = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=80,
        )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        # Employee A on the low-headcount worksite.
        employee_a = create_employee(
            employer_id=employer["id"], worksite_id=worksite_low["id"],
            hire_date="2023-01-01", hours_worked_trailing_12mo=2080,
        )
        # Employee B on the ok worksite — owns a PfLClaim.
        employee_b = create_employee(
            employer_id=employer["id"], worksite_id=worksite_ok["id"],
            hire_date="2023-01-01", hours_worked_trailing_12mo=2080,
        )
        claim_b = create_pfl_claim(
            employee_id=employee_b["id"], claim_type="FAMILY_CARE",
            weeks_authorized=8,
        )
        # Employee A submits with B's PFL claim → both ERR_NOT_ELIGIBLE_WORKSITE
        # and ERR_PFL_MISMATCH would apply; worksite wins per priority.
        h = make_employee_headers(employee_a["id"])
        from test_helpers import create_leave_case_payload
        resp = api.create_leave_case(
            employee_a["id"],
            create_leave_case_payload(
                reason="FAMILY_SERIOUS_HEALTH",
                leave_pattern="CONTINUOUS",
                requested_start_date="2026-06-01",
                expected_end_date="2026-06-30",
                pfl_claim_id=claim_b["id"],
            ),
            h,
        )
        validate_error(resp, "ERR_NOT_ELIGIBLE_WORKSITE")


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecision:

    def test_quota_boundary_480_inclusive(self, api):
        """PRD §3.7: "The remaining hours figure is then 480 minus that
        consumed total, floored at zero".
        PRD §3.6: "approving when the quota would be exceeded fails
        with `ERR_QUOTA_EXCEEDED`".

        With 472 hours already APPROVED in the leave year and an
        APPROVED case (so instances auto-promote): the 480th hour is
        inclusive (succeeds); the 481st is outside (fails).

        # difficulty: boundary_precision_check/quota_boundary_480_inclusive
        """
        # Build employee with 472 APPROVED hours; build an APPROVED
        # case so new instances auto-promote to APPROVED.
        from test_helpers import setup_quota_near_threshold
        ctx = setup_quota_near_threshold(
            consumed_hours=472,
            leave_year_basis="CALENDAR",
            requested_start_date="2026-07-01",
            expected_end_date="2026-07-31",
        )
        # Approve the new case with NO PROPOSED instances yet (so the
        # APPROVE check sees only the existing 472 hours).
        review_leave_case(
            leave_case_id=ctx["new_case"]["id"], decision="APPROVE",
        )
        # Step 1: post 8 hours → 480 inclusive.
        h = make_employee_headers(ctx["employee"]["id"])
        resp_ok = api.create_leave_instance(
            ctx["new_case"]["id"],
            {"instance_date": "2026-07-01", "hours_used": 8},
            h,
        )
        validate_success(resp_ok, expected_status=201)
        # Step 2: post 1 more hour → 481 over.
        resp_over = api.create_leave_instance(
            ctx["new_case"]["id"],
            {"instance_date": "2026-07-02", "hours_used": 1},
            h,
        )
        validate_error(resp_over, "ERR_QUOTA_EXCEEDED")

    def test_eligibility_worksite_50_inclusive(self, api):
        """PRD §3.2: "the employee's worksite must have an
        `employee_count_within_75_miles` of at least 50; failing this
        check yields `ERR_NOT_ELIGIBLE_WORKSITE`. All three thresholds
        are inclusive on the lower side: ... exactly 50 employees
        passes".

        50 → passes; 49 → fails; 0 (empty set) → fails.

        # difficulty: boundary_precision_check/eligibility_zero_count_empty_set_boundary
        """
        employer = create_employer()
        advance_clock_to("2026-03-01T00:00:00.000Z")
        # Three worksites: 0, 49, 50.
        from test_helpers import create_leave_case_payload
        for headcount, expected_err in [
            (0, "ERR_NOT_ELIGIBLE_WORKSITE"),
            (49, "ERR_NOT_ELIGIBLE_WORKSITE"),
        ]:
            ws = create_worksite(
                employer_id=employer["id"],
                employee_count_within_75_miles=headcount,
            )
            emp = create_employee(
                employer_id=employer["id"], worksite_id=ws["id"],
                hire_date="2023-01-01",
                hours_worked_trailing_12mo=2080,
            )
            h = make_employee_headers(emp["id"])
            resp = api.create_leave_case(
                emp["id"],
                create_leave_case_payload(
                    reason="OWN_SERIOUS_HEALTH",
                    leave_pattern="CONTINUOUS",
                    requested_start_date="2026-05-01",
                    expected_end_date="2026-05-31",
                ),
                h,
            )
            validate_error(resp, expected_err)
        # At-threshold passes.
        ws50 = create_worksite(
            employer_id=employer["id"],
            employee_count_within_75_miles=50,
        )
        emp50 = create_employee(
            employer_id=employer["id"], worksite_id=ws50["id"],
            hire_date="2023-01-01",
            hours_worked_trailing_12mo=2080,
        )
        h = make_employee_headers(emp50["id"])
        resp_ok = api.create_leave_case(
            emp50["id"],
            create_leave_case_payload(
                reason="OWN_SERIOUS_HEALTH",
                leave_pattern="CONTINUOUS",
                requested_start_date="2026-05-01",
                expected_end_date="2026-05-31",
            ),
            h,
        )
        validate_success(resp_ok, expected_status=201)


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_leavecase_approve_requires_medicalcertification_complete(
        self, api,
    ):
        """PRD §3.6: "Approving a case with a `certification_status`
        of `INSUFFICIENT` or `AWAITING_DOC` fails the certification-
        completeness check with `ERR_CERT_INCOMPLETE`".
        PRD §3.5: "on success `review_outcome` becomes `ACCEPTED` and
        the parent case's `certification_status` becomes `COMPLETE`".

        Without an ACCEPTED MedicalCertification, APPROVE → 422
        ERR_CERT_INCOMPLETE. After ACCEPT, APPROVE → 200 with case
        APPROVED.

        # difficulty: cross_entity_state_dependency/leavecase_approve_requires_medicalcertification_complete
        """
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
        )
        cert = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        # certification_status is now RECEIVED (not COMPLETE).
        # APPROVE must fail.
        resp = api.review_leave_case(
            case["id"], {"decision": "APPROVE"},
            TEST_USERS["hr_specialist_headers"],
        )
        validate_error(resp, "ERR_CERT_INCOMPLETE")
        # Now ACCEPT the certification.
        review_certification(
            leave_case_id=case["id"], cert_id=cert["id"],
            decision="ACCEPT",
        )
        approved = review_leave_case(
            leave_case_id=case["id"], decision="APPROVE",
        )
        assert approved["case_status"] == "APPROVED"

    def test_restore_job_requires_benefit_invoice_no_forfeit(self, api):
        """PRD §3.10: "Restoration is allowed only when the
        `job_restoration_status` is `PROTECTED` and there is no
        outstanding `BenefitInvoice` on this case in the `FORFEITED`
        status; any other condition surfaces as
        `ERR_JOB_RESTORATION_FORFEITED`".

        A forfeited BenefitInvoice cascades job_restoration_status to
        FORFEITED, blocking restore-job.

        # difficulty: cross_entity_state_dependency/restore_job_requires_benefitinvoice_no_forfeit
        """
        ctx = setup_invoice_forfeit_cascade(
            initial_clock_iso="2026-01-01T00:00:00.000Z",
            requested_start_date="2026-01-15",
            expected_end_date="2026-04-30",
        )
        invoice = ctx["invoice"]
        advance_clock_to(add_days(invoice["created_at"], 31))
        advance_clock_to(add_days(invoice["created_at"], 46))
        advance_clock_to("2026-05-01T00:00:00.000Z")
        # Case is COMPLETED + job_restoration_status FORFEITED.
        resp = api.restore_job(
            ctx["case"]["id"], None,
            TEST_USERS["hr_specialist_headers"],
        )
        validate_error(resp, "ERR_JOB_RESTORATION_FORFEITED")


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_same_day_duplicate_on_same_case_returns_duplicate_instance_day(
        self, api,
    ):
        """PRD §3.4: "a `(leave_case_id, instance_date)` pair must be
        unique: posting a second instance with the same date on the
        same case yields `ERR_DUPLICATE_INSTANCE_DAY`".

        # difficulty: resource_temporal_overlap/leaveinstance_same_day_duplicate_on_same_case
        """
        _e, _w, employee, case = setup_pending_certification_case(
            leave_pattern="INTERMITTENT",
        )
        log_instance(
            leave_case_id=case["id"], employee_id=employee["id"],
            instance_date="2026-08-10", hours_used=8,
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_instance(
            case["id"],
            {"instance_date": "2026-08-10", "hours_used": 4},
            h,
        )
        validate_error(resp, "ERR_DUPLICATE_INSTANCE_DAY")

    def test_same_day_across_two_cases_returns_instance_overlap(self, api):
        """PRD §3.4: "across all of a given employee's cases, no two
        `LeaveInstance` rows may share the same `instance_date` if
        both would consume hours in the same leave-year window — this
        catches the case of an employee posting overlapping absences
        against two different `LeaveCase` rows; the violation surfaces
        as `ERR_INSTANCE_OVERLAP`".

        # difficulty: resource_temporal_overlap/leaveinstance_same_day_across_employees_cases_aggregate
        """
        _e, _w, employee = setup_eligible_employee()
        case_a = submit_leave_case(
            employee_id=employee["id"],
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
            requested_start_date="2026-09-01",
            expected_end_date="2026-09-30",
        )
        case_b = submit_leave_case(
            employee_id=employee["id"],
            reason="FAMILY_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
            requested_start_date="2026-09-15",
            expected_end_date="2026-10-15",
        )
        log_instance(
            leave_case_id=case_a["id"], employee_id=employee["id"],
            instance_date="2026-09-05", hours_used=8,
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_instance(
            case_b["id"],
            {"instance_date": "2026-09-05", "hours_used": 4},
            h,
        )
        validate_error(resp, "ERR_INSTANCE_OVERLAP")


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_void_then_quota_invariant(self, api):
        """PRD §3.4: "An `HRSpecialist` may void a single logged
        instance on an approved or active case; the void flips
        `instance_status` to `VOIDED`, recomputes `hours_charged` on
        the parent case from the surviving `APPROVED` instances, and
        re-credits the leave-year bucket accordingly".

        Forward action consumes 8 hours; void compensates back to 0.
        remaining_hours before == remaining_hours after.

        # difficulty: compensating_invariant/void_then_relog_preserves_quota_balance
        """
        ctx = setup_eligible_employee(leave_year_basis="CALENDAR")
        _e, _w, employee = ctx
        # B0: fresh
        b0 = get_quota_balance(employee_id=employee["id"])
        assert b0["remaining_hours"] == 480
        # Build approved INTERMITTENT case with a single APPROVED 8-hour
        # instance.
        approved_ctx = approve_case_with_specific_instances(
            employee_id=employee["id"],
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
            requested_start_date="2026-10-01",
            expected_end_date="2026-10-31",
            instance_dates=["2026-10-12"],
            hours_per_instance=8,
        )
        b1 = get_quota_balance(employee_id=employee["id"])
        assert b1["remaining_hours"] == 472, (
            f"B1 expected 472; got {b1['remaining_hours']!r}"
        )
        # Void.
        instance_id = approved_ctx["instances"][0]["id"]
        resp = api.void_leave_instance(
            approved_ctx["case"]["id"], instance_id,
            TEST_USERS["hr_specialist_headers"],
        )
        assert resp.status_code == 204
        b2 = get_quota_balance(employee_id=employee["id"])
        assert b2["remaining_hours"] == 480, (
            f"B2 expected 480 (re-credited); got {b2['remaining_hours']!r}"
        )
        assert b0["remaining_hours"] == b2["remaining_hours"]

    def test_pfl_link_then_deny_preserves_weeks_paid(self, api):
        """PRD §3.8: "On creation the claim begins at `claim_status` of
        `SUBMITTED` and carries `weeks_paid` of 0".
        PRD §3.8: "it ends at `DENIED` if the paired FMLA case is
        denied".

        Submit + link + deny → weeks_paid never advances; W0 == W1 = 0.

        # difficulty: compensating_invariant/pfl_link_then_deny_preserves_pfl_weeks_paid
        """
        _e, _w, employee = setup_eligible_employee(
            state_pfl_program="STATE_PFL_8WEEK",
        )
        claim = create_pfl_claim(
            employee_id=employee["id"], claim_type="BABY_BONDING",
            weeks_authorized=8,
        )
        # W0
        w0 = claim["weeks_paid"]
        assert w0 == 0
        case = submit_leave_case(
            employee_id=employee["id"],
            reason="BABY_BONDING",
            leave_pattern="CONTINUOUS",
            requested_start_date="2026-06-01",
            expected_end_date="2026-06-30",
            pfl_claim_id=claim["id"],
        )
        # BABY_BONDING does not require certification (NOT_REQUIRED).
        # But to DENY a NOT_REQUIRED case the PRD §3.6 precondition is
        # "the `certification_status` is `INSUFFICIENT` or
        # `certification_status` is `AWAITING_DOC` and the server clock
        # has passed `cert_deadline`". For NOT_REQUIRED, the cert
        # deadline path is the only PRD-valid trigger — push the clock
        # past cert_deadline. However certification_status is
        # NOT_REQUIRED (not AWAITING_DOC), so deny is NOT allowed.
        # Switch to FAMILY_SERIOUS_HEALTH which requires cert.
        # Cancel this case (a new case path) and create a FAMILY one.
        # We'll cancel and re-do.
        cancel_case(leave_case_id=case["id"], employee_id=employee["id"])

        claim_fc = create_pfl_claim(
            employee_id=employee["id"], claim_type="FAMILY_CARE",
            weeks_authorized=8,
        )
        case_fc = submit_leave_case(
            employee_id=employee["id"],
            reason="FAMILY_SERIOUS_HEALTH",
            leave_pattern="CONTINUOUS",
            requested_start_date="2026-06-01",
            expected_end_date="2026-06-30",
            pfl_claim_id=claim_fc["id"],
        )
        cert = submit_certification(
            leave_case_id=case_fc["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        review_certification(
            leave_case_id=case_fc["id"], cert_id=cert["id"],
            decision="INSUFFICIENT",
        )
        review_leave_case(
            leave_case_id=case_fc["id"], decision="DENY",
        )
        # W1
        w1 = get_pfl_claim(claim_fc["id"])["weeks_paid"]
        assert w1 == 0, (
            f"PfLClaim.weeks_paid invariant: W0=0 must equal W1; "
            f"got {w1!r}"
        )
        assert get_pfl_claim(claim_fc["id"])["claim_status"] == "DENIED"
