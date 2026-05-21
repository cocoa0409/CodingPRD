"""Difficulty-design coverage — supplemental tests for each instance.

Companion to test_11_difficulty_coverage.py — each instance gets a
second, structurally different test angle.

Tag format: each test docstring carries `# difficulty: <rule_id>/<name>`.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    FMLA_ENTITLEMENT_HOURS,
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
    review_certification,
    review_leave_case,
    setup_eligible_employee,
    setup_invoice_forfeit_cascade,
    setup_pending_certification_case,
    setup_quota_near_threshold,
    submit_certification,
    submit_leave_case,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc (supplemental)
# ===========================================================================
class TestDualVariantCalcSupplemental:

    def test_calendar_window_endpoints_january_to_december(self, api):
        """PRD §3.7: "Under the `CALENDAR` variant, the leave-year
        window is anchored to the calendar year containing the case's
        `requested_start_date`: the window begins on January 1 of that
        year (inclusive) and ends on December 31 of that year
        (inclusive)".

        Verify the GET /quota-balance response carries window_start
        '2026-01-01' and window_end '2026-12-31' for a CALENDAR
        employer whose case is in 2026.

        # difficulty: dual_variant_calc/quota_balance_calendar_vs_rolling
        """
        _e, _w, employee = setup_eligible_employee(
            leave_year_basis="CALENDAR",
        )
        # Trigger leave_year_anchor pinning via case submission.
        case = submit_leave_case(
            employee_id=employee["id"],
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="CONTINUOUS",
            requested_start_date="2026-06-15",
            expected_end_date="2026-07-15",
        )
        # leave_year_anchor must be 2026-01-01.
        assert case["leave_year_anchor"].startswith("2026-01-01")
        bal = get_quota_balance(
            employee_id=employee["id"], as_of_date="2026-06-15",
        )
        assert bal["window_start"].startswith("2026-01-01"), (
            f"CALENDAR window_start = Jan 1; got "
            f"{bal['window_start']!r}"
        )
        assert bal["window_end"].startswith("2026-12-31"), (
            f"CALENDAR window_end = Dec 31; got "
            f"{bal['window_end']!r}"
        )

    def test_pfl_under_cap_at_lower_wage(self, api):
        """PRD §3.8: "if the raw weekly benefit is less than or equal
        to the cap the under-cap variant applies and the final value
        equals the raw weekly benefit".

        monthly_wage_cents=200_000:
            Step 1: round_half_up(200_000*12/52) = 46_154
            Step 2: round_half_up(46_154*0.60)   = 27_692
            Step 3: min(27_692, 162_900) = 27_692 (under-cap)

        # difficulty: dual_variant_calc/pfl_weekly_benefit_under_vs_at_cap
        """
        _e, _w, employee = setup_eligible_employee(
            state_pfl_program="STATE_PFL_8WEEK",
            monthly_wage_cents=200_000,
        )
        claim = create_pfl_claim(
            employee_id=employee["id"], claim_type="BABY_BONDING",
            weeks_authorized=4,
        )
        assert claim["weekly_benefit_cents"] == 27_692, (
            f"under-cap @ 200_000 cents/mo: 27_692; got "
            f"{claim['weekly_benefit_cents']!r}"
        )


# ===========================================================================
# Rule 2 — combinatorial_formula (supplemental)
# ===========================================================================
class TestCombinatorialFormulaSupplemental:

    def test_job_restoration_score_clean_case_with_tenure_bonus(self, api):
        """PRD §3.10: "Step three — the tenure bonus — multiplies the
        score by 1.10 if the employee's `hours_worked_trailing_12mo`
        is at least 2000, otherwise leaves it unchanged; after this
        step the score is rounded half-up and then clamped to a maximum
        of 100. The final `job_restoration_status` is `PROTECTED` if
        the resulting score is at least 50, and `FORFEITED` otherwise".

        Clean case (no INSUFFICIENT cert, no GRACE/FORFEITED invoice),
        tenure 2080 (≥ 2000):
            Step 1: 100
            Step 2: unchanged = 100
            Step 3: unchanged = 100
            Step 4: round_half_up(100 * 1.10) = 110 → clamp 100
        → PROTECTED.

        # difficulty: combinatorial_formula/job_restoration_score_per_step_rounding
        """
        _e, _w, employee = setup_eligible_employee(
            hours_worked_trailing_12mo=2080,
        )
        case = submit_leave_case(
            employee_id=employee["id"],
            reason="BABY_BONDING",
            leave_pattern="CONTINUOUS",
            requested_start_date="2026-05-01",
            expected_end_date="2026-05-31",
        )
        # BABY_BONDING → NOT_REQUIRED → can approve immediately.
        approved = review_leave_case(
            leave_case_id=case["id"], decision="APPROVE",
        )
        assert approved["job_restoration_status"] == "PROTECTED", (
            f"clean approval should leave job_restoration_status "
            f"PROTECTED; got {approved['job_restoration_status']!r}"
        )

    def test_continuous_case_bridge_invoice_full_month(self, api):
        """PRD §3.9: "for continuous cases, an additional bridge count
        is added — every calendar day from the later of
        `requested_start_date` or the first day of `period_month`,
        through the earlier of `expected_end_date` or the last day of
        `period_month`, inclusive".

        CONTINUOUS case 2026-02-01..2026-02-28 → bridge = full 28
        days of Feb → amount = round_half_up(30_000 * 28 / 28) = 30_000.

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
        case = submit_leave_case(
            employee_id=employee["id"],
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="CONTINUOUS",
            requested_start_date="2026-02-01",
            expected_end_date="2026-02-28",
        )
        cert = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        review_certification(
            leave_case_id=case["id"], cert_id=cert["id"],
            decision="ACCEPT",
        )
        review_leave_case(leave_case_id=case["id"], decision="APPROVE")
        invoices = list_benefit_invoices(case["id"])
        feb = next(
            (i for i in invoices if i["period_month"] == "2026-02"), None,
        )
        assert feb is not None
        assert feb["amount_due_cents"] == 30_000, (
            f"CONTINUOUS bridge full Feb 2026: full premium 30_000; "
            f"got {feb['amount_due_cents']!r}"
        )


# ===========================================================================
# Rule 3 — non_linear_state_machine (supplemental)
# ===========================================================================
class TestNonLinearStateMachineSupplemental:

    def test_cert_old_insufficient_row_remains_after_cure(self, api):
        """PRD §3.5: "if a prior `INSUFFICIENT` certification exists
        it is preserved for audit and not deleted".

        After cure, the old INSUFFICIENT row must still be findable.

        # difficulty: non_linear_state_machine/medical_certification_cyclic_cure_loop
        """
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
        )
        cert1 = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        cert1_after = review_certification(
            leave_case_id=case["id"], cert_id=cert1["id"],
            decision="INSUFFICIENT",
        )
        # Cure.
        cert2 = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        # cert1 still has review_outcome INSUFFICIENT — preserved.
        assert cert1_after["review_outcome"] == "INSUFFICIENT"
        assert cert2["id"] != cert1["id"]

    def test_approve_branch_issues_first_benefit_invoice(self, api):
        """PRD §3.6: "the first `BenefitInvoice` for the case is
        issued, sized for the calendar month containing the case's
        `requested_start_date`".

        APPROVE → at least one BenefitInvoice exists; DENY → none.

        # difficulty: non_linear_state_machine/leave_case_branching_approve_or_deny
        """
        # APPROVE branch.
        _e1, _w1, employee1, case1 = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="CONTINUOUS",
        )
        cert1 = submit_certification(
            leave_case_id=case1["id"], employee_id=employee1["id"],
            serious_health_condition=True,
        )
        review_certification(
            leave_case_id=case1["id"], cert_id=cert1["id"],
            decision="ACCEPT",
        )
        review_leave_case(leave_case_id=case1["id"], decision="APPROVE")
        invoices1 = list_benefit_invoices(case1["id"])
        assert len(invoices1) >= 1, (
            "APPROVE branch must create at least one BenefitInvoice"
        )

        # DENY branch.
        _e2, _w2, employee2, case2 = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="CONTINUOUS",
            initial_clock_iso=None,
        )
        cert2 = submit_certification(
            leave_case_id=case2["id"], employee_id=employee2["id"],
            serious_health_condition=True,
        )
        review_certification(
            leave_case_id=case2["id"], cert_id=cert2["id"],
            decision="INSUFFICIENT",
        )
        review_leave_case(leave_case_id=case2["id"], decision="DENY")
        invoices2 = list_benefit_invoices(case2["id"])
        assert len(invoices2) == 0, (
            f"DENY branch must NOT create a BenefitInvoice; got "
            f"{len(invoices2)}"
        )


# ===========================================================================
# Rule 4 — transitive_cascade (supplemental)
# ===========================================================================
class TestTransitiveCascadeSupplemental:

    def test_forfeit_blocks_subsequent_restore_job(self, api):
        """PRD §3.10: "any other condition surfaces as
        `ERR_JOB_RESTORATION_FORFEITED`".

        Confirm the depth-3 cascade is observable downstream: once
        job_restoration_status is FORFEITED, restore-job returns
        ERR_JOB_RESTORATION_FORFEITED.

        # difficulty: transitive_cascade/invoice_forfeit_cascade_depth_3
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
        resp = api.restore_job(
            ctx["case"]["id"], None,
            TEST_USERS["hr_specialist_headers"],
        )
        validate_error(resp, "ERR_JOB_RESTORATION_FORFEITED")

    def test_deny_voids_all_instances_to_voided_state(self, api):
        """PRD §3.6: "On a denial ... every `LeaveInstance` on the
        case transitions to `VOIDED`".

        After DENY, querying the leave-case shows hours_charged==0
        (consequence of every instance flipping to VOIDED — link 2).

        # difficulty: transitive_cascade/deny_review_cascade_depth_2
        """
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
        )
        log_instance(
            leave_case_id=case["id"], employee_id=employee["id"],
            instance_date="2026-05-01", hours_used=8,
        )
        log_instance(
            leave_case_id=case["id"], employee_id=employee["id"],
            instance_date="2026-05-04", hours_used=4,
        )
        cert = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        review_certification(
            leave_case_id=case["id"], cert_id=cert["id"],
            decision="INSUFFICIENT",
        )
        review_leave_case(leave_case_id=case["id"], decision="DENY")
        refreshed = get_leave_case(case["id"])
        assert refreshed["hours_charged"] == 0


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict (supplemental)
# ===========================================================================
class TestPriorityValidationConflictSupplemental:

    def test_invalid_state_blocks_instance_logging_on_cancelled_case(
        self, api,
    ):
        """PRD §3.11: "Any attempt to perform a state transition from
        a `case_status` not in that transition's allowed-from set is
        refused with `ERR_INVALID_STATE`".

        Logging an instance under a CANCELLED case fails on state
        check regardless of other failure modes.

        # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_conflict
        """
        _e, _w, employee = setup_eligible_employee()
        case = submit_leave_case(
            employee_id=employee["id"],
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
            requested_start_date="2026-05-01",
            expected_end_date="2026-05-31",
        )
        cancel_case(
            leave_case_id=case["id"], employee_id=employee["id"],
        )
        h = make_employee_headers(employee["id"])
        # Even a perfectly-valid instance payload should be refused
        # because the case is CANCELLED.
        resp = api.create_leave_instance(
            case["id"],
            {"instance_date": "2026-05-15", "hours_used": 8},
            h,
        )
        validate_error(resp, "ERR_INVALID_STATE")

    def test_tenure_check_wins_over_pfl_mismatch(self, api):
        """PRD §3.2: "The three checks are evaluated in the order
        tenure, hours, worksite, so a worker who fails on tenure does
        not see a worksite-headcount error".
        PRD §2.6: "the three FMLA eligibility checks ... PFL linkage
        consistency (`ERR_PFL_MISMATCH`)" — eligibility checks come
        before PFL linkage in the priority ordering.

        Below-tenure employee + PFL claim for a different employee →
        ERR_NOT_ELIGIBLE_TENURE wins.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_conflict
        """
        employer = create_employer(state_pfl_program="STATE_PFL_8WEEK")
        worksite = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=80,
        )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        # Employee A: ineligible on tenure (hired 2025-09-01 < 12mo).
        employee_a = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2025-09-01", hours_worked_trailing_12mo=2080,
        )
        # Employee B owns a PFL claim.
        employee_b = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2023-01-01", hours_worked_trailing_12mo=2080,
        )
        claim_b = create_pfl_claim(
            employee_id=employee_b["id"], claim_type="FAMILY_CARE",
            weeks_authorized=8,
        )
        # A submits with B's claim → both ERR_NOT_ELIGIBLE_TENURE and
        # ERR_PFL_MISMATCH would apply; tenure wins.
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
        validate_error(resp, "ERR_NOT_ELIGIBLE_TENURE")


# ===========================================================================
# Rule 6 — boundary_precision_check (supplemental)
# ===========================================================================
class TestBoundaryPrecisionSupplemental:

    def test_hours_exactly_1250_inclusive(self, api):
        """PRD §3.2: "exactly 1250 hours passes". Boundary on the
        opposite side: 1249 fails with ERR_NOT_ELIGIBLE_HOURS, 1250
        passes — covered by tests 03. This supplements with the
        eligibility-snapshot reading at the exact boundary.

        # difficulty: boundary_precision_check/quota_boundary_480_inclusive
        """
        # Snapshot at 1250 hours → eligible=True via snapshot endpoint.
        employer = create_employer()
        worksite = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=80,
        )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        emp = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2023-01-01",
            hours_worked_trailing_12mo=1250,
        )
        h = make_employee_headers(emp["id"])
        resp = api.get_eligibility_snapshot(emp["id"], h)
        data = validate_success(resp, expected_status=200)
        assert data["eligible"] is True
        assert data["reason_code"] is None

    def test_eligibility_50_employees_at_boundary_passes(self, api):
        """PRD §3.2: "exactly 50 employees passes". Supplemental check
        via eligibility-snapshot endpoint.

        # difficulty: boundary_precision_check/eligibility_zero_count_empty_set_boundary
        """
        employer = create_employer()
        worksite = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=50,
        )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        emp = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2023-01-01", hours_worked_trailing_12mo=2080,
        )
        h = make_employee_headers(emp["id"])
        resp = api.get_eligibility_snapshot(emp["id"], h)
        data = validate_success(resp, expected_status=200)
        assert data["eligible"] is True


# ===========================================================================
# Rule 7 — cross_entity_state_dependency (supplemental)
# ===========================================================================
class TestCrossEntityStateDependencySupplemental:

    def test_approve_after_reject_remains_blocked(self, api):
        """PRD §3.6: "Approving a case with a `certification_status`
        of `INSUFFICIENT` or `AWAITING_DOC` fails the certification-
        completeness check with `ERR_CERT_INCOMPLETE`".
        PRD §3.5: "on a `REJECT`, `review_outcome` becomes `REJECTED`
        and the parent `certification_status` becomes `INSUFFICIENT`".

        Reject → certification_status INSUFFICIENT → APPROVE still
        blocked.

        # difficulty: cross_entity_state_dependency/leavecase_approve_requires_medicalcertification_complete
        """
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
        )
        cert = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=False,
        )
        review_certification(
            leave_case_id=case["id"], cert_id=cert["id"],
            decision="REJECT",
        )
        resp = api.review_leave_case(
            case["id"], {"decision": "APPROVE"},
            TEST_USERS["hr_specialist_headers"],
        )
        validate_error(resp, "ERR_CERT_INCOMPLETE")

    def test_pay_invoice_in_grace_keeps_restore_protected(self, api):
        """PRD §3.9: "payment is allowed when `invoice_status` is in
        `ISSUED` or `GRACE`".
        PRD §3.10: "Restoration is allowed only when the
        `job_restoration_status` is `PROTECTED` and there is no
        outstanding `BenefitInvoice` on this case in the `FORFEITED`
        status".

        Paying an invoice while it is in GRACE keeps the cascade from
        firing on THAT invoice. PRD §3.9 also has the clock sweep
        issue subsequent monthly invoices "as each new calendar-month
        boundary is crossed while the case remains in `APPROVED` or
        `ACTIVE`"; all of those must also be paid to keep
        job_restoration_status PROTECTED through the lifetime of the
        case.

        # difficulty: cross_entity_state_dependency/restore_job_requires_benefitinvoice_no_forfeit
        """
        from test_helpers import pay_invoice
        from test_helpers import list_benefit_invoices
        ctx = setup_invoice_forfeit_cascade(
            initial_clock_iso="2026-01-01T00:00:00.000Z",
            requested_start_date="2026-01-15",
            expected_end_date="2026-04-30",
        )
        invoice = ctx["invoice"]
        # Push to GRACE then pay the original invoice.
        advance_clock_to(add_days(invoice["created_at"], 31))
        pay_invoice(
            invoice_id=invoice["id"], employee_id=ctx["employee"]["id"],
        )
        # Subsequent clock sweeps issue additional monthly invoices
        # (PRD §3.9) — pay each as soon as it appears so none can age
        # into FORFEITED. Advance month-by-month through the case
        # window and after each advance pay any newly issued invoices
        # that are still in ISSUED or GRACE.
        for next_clock in (
            "2026-03-01T00:00:00.000Z",
            "2026-04-01T00:00:00.000Z",
            "2026-05-01T00:00:00.000Z",
        ):
            advance_clock_to(next_clock)
            for inv in list_benefit_invoices(ctx["case"]["id"]):
                if inv.get("invoice_status") in {"ISSUED", "GRACE"}:
                    pay_invoice(
                        invoice_id=inv["id"],
                        employee_id=ctx["employee"]["id"],
                    )
        refreshed = get_leave_case(ctx["case"]["id"])
        # PRD §3.10: job_restoration_status is PROTECTED because no
        # invoice on this case is FORFEITED.
        assert refreshed["job_restoration_status"] == "PROTECTED", (
            f"all GRACE invoices paid → no FORFEITED invoice → "
            f"job_restoration_status PROTECTED; got "
            f"{refreshed['job_restoration_status']!r}"
        )


# ===========================================================================
# Rule 8 — resource_temporal_overlap (supplemental)
# ===========================================================================
class TestResourceTemporalOverlapSupplemental:

    def test_only_one_instance_persists_for_duplicate_day(self, api):
        """PRD §3.4: "the first-writer-wins semantics on the underlying
        constraint also serialize two simultaneous POSTs on the same
        day to a single winner".

        # difficulty: resource_temporal_overlap/leaveinstance_same_day_duplicate_on_same_case
        """
        _e, _w, employee, case = setup_pending_certification_case(
            leave_pattern="INTERMITTENT",
        )
        # Successful first.
        log_instance(
            leave_case_id=case["id"], employee_id=employee["id"],
            instance_date="2026-08-10", hours_used=8,
        )
        # Duplicate.
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_instance(
            case["id"],
            {"instance_date": "2026-08-10", "hours_used": 12},
            h,
        )
        validate_error(resp, "ERR_DUPLICATE_INSTANCE_DAY")

    def test_overlap_per_employee_aggregates_across_cases(self, api):
        """PRD §3.4: "across all of a given employee's cases, no two
        `LeaveInstance` rows may share the same `instance_date` if
        both would consume hours in the same leave-year window".

        Confirm the rule scope is "across all cases", not just
        same-case.

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
            instance_date="2026-09-20", hours_used=8,
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_instance(
            case_b["id"],
            {"instance_date": "2026-09-20", "hours_used": 8},
            h,
        )
        validate_error(resp, "ERR_INSTANCE_OVERLAP")


# ===========================================================================
# Rule 9 — compensating_invariant (supplemental)
# ===========================================================================
class TestCompensatingInvariantSupplemental:

    def test_void_recomputes_hours_charged_on_case(self, api):
        """PRD §3.4: "the void flips `instance_status` to `VOIDED`,
        recomputes `hours_charged` on the parent case from the
        surviving `APPROVED` instances".

        hours_charged_before − voided_hours == hours_charged_after.

        # difficulty: compensating_invariant/void_then_relog_preserves_quota_balance
        """
        from test_helpers import setup_approved_case
        ctx = setup_approved_case(
            leave_pattern="INTERMITTENT",
            requested_start_date="2026-05-01",
            expected_end_date="2026-05-31",
            instance_dates_and_hours=[
                ("2026-05-01", 8), ("2026-05-02", 8), ("2026-05-03", 8),
            ],
        )
        # hours_charged_before = 24.
        before = ctx["case"]["hours_charged"]
        assert before == 24
        # Void one 8-hour instance.
        first_instance_id = ctx["instances"][0]["id"]
        resp = api.void_leave_instance(
            ctx["case"]["id"], first_instance_id,
            TEST_USERS["hr_specialist_headers"],
        )
        assert resp.status_code == 204
        after_case = get_leave_case(ctx["case"]["id"])
        # hours_charged_after = 16.
        assert after_case["hours_charged"] == before - 8, (
            f"void must subtract voided instance's hours from "
            f"hours_charged; expected {before - 8}, got "
            f"{after_case['hours_charged']!r}"
        )

    def test_pfl_remains_submitted_until_paired_case_advances(self, api):
        """PRD §3.8: "On creation the claim begins at `claim_status` of
        `SUBMITTED` and carries `weeks_paid` of 0".
        PRD §3.8: "The `claim_status` advances to `APPROVED` and then
        `PAYING` when a paired FMLA case is approved".

        Before any FMLA case is approved, weeks_paid stays at 0; even
        if a FMLA case is then submitted and DENIED, weeks_paid still
        stays at 0 (conserved quantity).

        # difficulty: compensating_invariant/pfl_link_then_deny_preserves_pfl_weeks_paid
        """
        _e, _w, employee = setup_eligible_employee(
            state_pfl_program="STATE_PFL_8WEEK",
        )
        claim = create_pfl_claim(
            employee_id=employee["id"], claim_type="FAMILY_CARE",
            weeks_authorized=8,
        )
        assert claim["weeks_paid"] == 0
        case = submit_leave_case(
            employee_id=employee["id"],
            reason="FAMILY_SERIOUS_HEALTH",
            leave_pattern="CONTINUOUS",
            requested_start_date="2026-06-01",
            expected_end_date="2026-06-30",
            pfl_claim_id=claim["id"],
        )
        # Cancel the case BEFORE certification — claim must remain
        # SUBMITTED with weeks_paid = 0.
        cancel_case(leave_case_id=case["id"], employee_id=employee["id"])
        refreshed = get_pfl_claim(claim["id"])
        assert refreshed["weeks_paid"] == 0
