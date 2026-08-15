"""Employee retention/termination decisions: phase gate, SoD, severance tiers,
notice windows, clock-gated effectiveness, and the payroll-accrual invariant."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_acquisition,
    create_employee_decision_payload,
    create_kicked_off_acquisition,
    get_acquisition,
    get_success_data,
    make_hr_partner_headers,
    make_underwriting_manager_headers,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
UM1 = TEST_USERS["underwriting_manager_headers"]
HR1 = TEST_USERS["hr_partner_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestEmployeeApprovePhaseGate:
    def test_employee_approve_requires_in_diligence(self, api):
        """PRD §3.11: "Approval belongs to an `UnderwritingManager` and
        enforces its checks in a fixed order: the acquisition must be
        `IN_DILIGENCE` (else `ERR_ACQUISITION_NOT_IN_DILIGENCE`); the approver
        must differ from `proposed_by_user_id` (else `ERR_SOD_VIOLATION`); and
        the notice window must satisfy the statutory minimum..."
        PRD §3.11: "A `RETAIN` decision owes nothing: `severance_cents` and
        `pto_payout_cents` are zero, and `assumed_pto_liability_cents` records
        the PTO liability the buyer assumes — `accrued_pto_hours` times the
        hourly rate, rounded half up."

        Design: Difficulty/cross_entity_state_dependency/employee_approve_requires_in_diligence
        """
        acq = create_acquisition(property_name="XDep Three")  # stays DRAFT
        dec = get_success_data(api.create_employee_decision(
            create_employee_decision_payload(
                acq["id"], decision="RETAIN",
                notice_date="2026-08-10T00:00:00Z",
                effective_date="2026-08-25T00:00:00Z"),
            HR1), 201)

        resp = api.approve_employee_decision(dec["id"], UM1)
        validate_error(resp, ApiErrorId.ERR_ACQUISITION_NOT_IN_DILIGENCE, 409)
        assert get_success_data(api.get_employee_decision(dec["id"], UM1))["status"] == "PROPOSED"

        get_success_data(api.kickoff_acquisition(acq["id"], UM1))
        approved = validate_success(api.approve_employee_decision(dec["id"], UM1))
        assert approved["status"] == "APPROVED"
        assert approved["assumed_pto_liability_cents"] == 100_000, (
            "round(5200000/2080) = 2500 hourly x 40 hours"
        )

    def test_retain_accrues_no_severance_and_assumes_pto(self, api):
        """PRD §3.11: "Tenure in years is the calendar days from `hire_date` to
        `effective_date` divided by 365 and rounded down. The weekly rate is
        `annual_salary_cents` divided by 52 rounded half up; the hourly rate is
        `annual_salary_cents` divided by 2080 rounded half up, both rounded
        before any multiplication."
        PRD §3.11: "A `RETAIN` decision owes nothing: `severance_cents` and
        `pto_payout_cents` are zero..."

        Design: Difficulty/cross_entity_state_dependency/employee_approve_requires_in_diligence
        """
        acq = create_kicked_off_acquisition(property_name="Retain Deal")
        dec = get_success_data(api.create_employee_decision(
            create_employee_decision_payload(
                acq["id"], decision="RETAIN",
                notice_date="2026-08-10T00:00:00Z",
                effective_date="2026-08-25T00:00:00Z"),
            HR1), 201)
        approved = get_success_data(api.approve_employee_decision(dec["id"], UM1))
        assert approved["severance_cents"] == 0
        assert approved["pto_payout_cents"] == 0
        assert approved["assumed_pto_liability_cents"] == 100_000


class TestEmployeeApprovePriorityPair:
    def test_employee_approve_sod_beats_temporal(self, api):
        """PRD §2.4: "Because earlier checks run before later ones, a request
        that would fail at two levels surfaces the earlier error — for example,
        an approve issued by the statement's own creator reports
        `ERR_SOD_VIOLATION` even if the statement's generated lines would also
        drift."
        PRD §2.4: "then referential and segregation-of-duties checks
        (`ERR_SOD_VIOLATION`, `ERR_SUPERSEDE_TARGET_NOT_CURRENT`,
        `ERR_RENT_ROLL_ENTRY_MISSING`), then compliance gates ... then temporal
        rules (the notice-window, overlap, and clock-ordering family)"
        PRD §3.11: "The proposal opens `PROPOSED` with `proposed_by_user_id`
        stamped from the caller."

        Design: Difficulty/priority_pair_validation_conflict/employee_approve_sod_beats_temporal
        """
        acq = create_kicked_off_acquisition(property_name="Priority Two")
        # hr-1 proposes; notice 2026-09-01 -> effective 2026-09-10 is 9 days < 14.
        dec = get_success_data(api.create_employee_decision(
            create_employee_decision_payload(
                acq["id"], employee_ref="emp-7", decision="TERMINATE",
                notice_date="2026-09-01T00:00:00Z",
                effective_date="2026-09-10T00:00:00Z",
                required_notice_days=14),
            make_hr_partner_headers("hr-1")), 201)
        assert dec["proposed_by_user_id"] == "hr-1"

        # The proposer approving their own proposal is BOTH an SoD breach and
        # (incidentally) a short notice window; SoD (referential) reports first.
        resp = api.approve_employee_decision(
            dec["id"], make_underwriting_manager_headers("hr-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 409)
        assert get_success_data(api.get_employee_decision(dec["id"], UM1))["status"] == "PROPOSED"

    def test_proposer_stamp_and_sod_rejection_leave_decision_proposed(self, api):
        """PRD §2.8: "An employee decision's approver must differ from its
        `proposed_by_user_id`. ... Each breach is rejected with
        `ERR_SOD_VIOLATION` (HTTP 409)."
        PRD §3.11: "the notice window must satisfy the statutory minimum — the
        calendar days from `notice_date` to `effective_date` must be at least
        `required_notice_days`, else `ERR_NOTICE_PERIOD_INSUFFICIENT`."

        Design: Difficulty/priority_pair_validation_conflict/employee_approve_sod_beats_temporal
        """
        acq = create_kicked_off_acquisition(property_name="Priority Two B")
        dec = get_success_data(api.create_employee_decision(
            create_employee_decision_payload(
                acq["id"], employee_ref="emp-7", decision="TERMINATE",
                notice_date="2026-09-01T00:00:00Z",
                effective_date="2026-09-10T00:00:00Z",
                required_notice_days=14),
            make_hr_partner_headers("hr-1")), 201)

        resp = api.approve_employee_decision(
            dec["id"], make_underwriting_manager_headers("hr-1"))
        err = validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 409)
        assert err["error_id"] != "ERR_NOTICE_PERIOD_INSUFFICIENT"
        after = get_success_data(api.get_employee_decision(dec["id"], UM1))
        assert after["status"] == "PROPOSED"
        assert after["proposed_by_user_id"] == "hr-1"


class TestPayrollAccrualInvariant:
    def test_employee_approve_rescind_conserves_payroll_accrual(self, api):
        """PRD §3.11: "The acquisition's `payroll_accrual_cents` sums
        `severance_cents` plus `pto_payout_cents` over decisions with
        `decision` `TERMINATE` or `TRANSFER` in `APPROVED` or `NOTIFIED`
        status."
        PRD §3.11: "Rescission by the HR partner — or automatically when the
        acquisition terminates — moves an `APPROVED` or `NOTIFIED` decision to
        `RESCINDED` and removes its payroll-accrual contribution as
        compensation, though the computed `severance_cents` and
        `pto_payout_cents` remain on the record for audit."

        Design: Difficulty/compensating_invariant/employee_approve_rescind_conserves_payroll_accrual
        """
        acq = create_kicked_off_acquisition(property_name="Invariant Two")
        dec = get_success_data(api.create_employee_decision(
            create_employee_decision_payload(
                acq["id"], employee_ref="emp-3", position="MAINTENANCE_TECH"),
            HR1), 201)
        assert get_acquisition(acq["id"])["payroll_accrual_cents"] == 0

        approved = get_success_data(api.approve_employee_decision(dec["id"], UM1))
        # Tenure 2020-01-01 -> 2026-09-01 is 6 years: 3 weeks x weekly 100000.
        assert approved["severance_cents"] == 300_000
        assert approved["pto_payout_cents"] == 100_000, "40h x 2500 hourly"
        assert get_acquisition(acq["id"])["payroll_accrual_cents"] == 400_000

        rescinded = get_success_data(api.rescind_employee_decision(
            dec["id"], HR1, reason="seller retains staff"))
        assert rescinded["status"] == "RESCINDED"
        assert get_acquisition(acq["id"])["payroll_accrual_cents"] == 0, (
            "compensation returns the accrual to exactly the baseline"
        )

    def test_rescinded_decision_retains_audit_amounts_but_leaves_accrual(self, api):
        """PRD §3.11: "Rescission by the HR partner — or automatically when the
        acquisition terminates — moves an `APPROVED` or `NOTIFIED` decision to
        `RESCINDED` and removes its payroll-accrual contribution as
        compensation, though the computed `severance_cents` and
        `pto_payout_cents` remain on the record for audit."
        PRD §3.11: "A `TERMINATE` or `TRANSFER` decision earns tenure-tiered
        severance: zero weeks for tenure under one year, one week for tenure of
        one or two years, two weeks for three to five years, and three weeks
        for six or more years, so `severance_cents` is the severance weeks
        times the weekly rate."

        Design: Difficulty/compensating_invariant/employee_approve_rescind_conserves_payroll_accrual
        """
        acq = create_kicked_off_acquisition(property_name="Invariant Two B")
        dec = get_success_data(api.create_employee_decision(
            create_employee_decision_payload(acq["id"], employee_ref="emp-3"),
            HR1), 201)
        get_success_data(api.approve_employee_decision(dec["id"], UM1))
        assert get_acquisition(acq["id"])["payroll_accrual_cents"] == 400_000

        get_success_data(api.rescind_employee_decision(dec["id"], HR1))
        after = get_success_data(api.get_employee_decision(dec["id"], UM1))
        assert after["status"] == "RESCINDED"
        assert after["severance_cents"] == 300_000, (
            "computed amounts stay on the record for audit"
        )
        assert after["pto_payout_cents"] == 100_000
        assert get_acquisition(acq["id"])["payroll_accrual_cents"] == 0


class TestSeveranceTiersAndCap:
    def test_severance_tier_boundaries_and_eight_week_cap(self, api):
        """PRD §3.11: "A `TERMINATE` or `TRANSFER` decision earns tenure-tiered
        severance: zero weeks for tenure under one year, one week for tenure of
        one or two years, two weeks for three to five years, and three weeks
        for six or more years, so `severance_cents` is the severance weeks
        times the weekly rate. Its `pto_payout_cents` is `accrued_pto_hours`
        times the hourly rate, rounded half up, and its
        `assumed_pto_liability_cents` is zero. A cap binds the sum: when
        severance plus PTO payout exceeds eight times the weekly rate, the PTO
        payout is reduced so the two together equal exactly eight weekly
        rates."
        PRD §3.11: "Tenure in years is the calendar days from `hire_date` to
        `effective_date` divided by 365 and rounded down."

        Design: Corner/calculations/severance_tier_boundaries_and_eight_week_cap
        """
        acq = create_kicked_off_acquisition(property_name="Sev Deal")
        # 364 days tenure (2025-10-02 -> 2026-10-01): 0 weeks.
        d1 = get_success_data(api.create_employee_decision(
            create_employee_decision_payload(
                acq["id"], employee_ref="e-364", hire_date="2025-10-02T00:00:00Z",
                notice_date="2026-09-01T00:00:00Z",
                effective_date="2026-10-01T00:00:00Z"),
            HR1), 201)
        # 365 days tenure (2025-10-01 -> 2026-10-01): 1 week; zero PTO.
        d2 = get_success_data(api.create_employee_decision(
            create_employee_decision_payload(
                acq["id"], employee_ref="e-365", hire_date="2025-10-01T00:00:00Z",
                accrued_pto_hours=0,
                notice_date="2026-09-01T00:00:00Z",
                effective_date="2026-10-01T00:00:00Z"),
            HR1), 201)
        # 6y tenure, 208h PTO: 3 weeks severance (300000); raw PTO 520000;
        # the 8-week cap (800000) binds, reducing PTO to 500000.
        d3 = get_success_data(api.create_employee_decision(
            create_employee_decision_payload(
                acq["id"], employee_ref="e-cap", position="MANAGER",
                hire_date="2020-01-01T00:00:00Z", accrued_pto_hours=208,
                notice_date="2026-09-01T00:00:00Z",
                effective_date="2026-10-01T00:00:00Z"),
            HR1), 201)

        a1 = get_success_data(api.approve_employee_decision(d1["id"], UM1))
        assert a1["severance_cents"] == 0
        assert a1["pto_payout_cents"] == 100_000

        a2 = get_success_data(api.approve_employee_decision(d2["id"], UM1))
        assert a2["severance_cents"] == 100_000, "365 days -> 1 week"
        assert a2["pto_payout_cents"] == 0

        a3 = get_success_data(api.approve_employee_decision(d3["id"], UM1))
        assert a3["severance_cents"] == 300_000, "6 years -> 3 weeks"
        assert a3["pto_payout_cents"] == 500_000, (
            "300000 + 520000 exceeds 8 x 100000; the PTO payout is reduced so "
            "the sum equals exactly eight weekly rates"
        )
        assert a3["severance_cents"] + a3["pto_payout_cents"] == 800_000


class TestNoticePeriodBoundary:
    def test_employee_notice_period_boundary(self, api):
        """PRD §3.11: "the notice window must satisfy the statutory minimum —
        the calendar days from `notice_date` to `effective_date` must be at
        least `required_notice_days`, else `ERR_NOTICE_PERIOD_INSUFFICIENT`."

        Design: Corner/validations/employee_notice_period_boundary
        """
        acq = create_kicked_off_acquisition(property_name="Notice Deal")
        dec_a = get_success_data(api.create_employee_decision(
            create_employee_decision_payload(
                acq["id"], employee_ref="e-a",
                notice_date="2026-09-01T00:00:00Z",
                effective_date="2026-09-15T00:00:00Z",
                required_notice_days=14),
            HR1), 201)
        dec_b = get_success_data(api.create_employee_decision(
            create_employee_decision_payload(
                acq["id"], employee_ref="e-b",
                notice_date="2026-09-01T00:00:00Z",
                effective_date="2026-09-14T00:00:00Z",
                required_notice_days=14),
            HR1), 201)

        approved = validate_success(api.approve_employee_decision(dec_a["id"], UM1))
        assert approved["status"] == "APPROVED", "exactly 14 days satisfies >="

        resp = api.approve_employee_decision(dec_b["id"], UM1)
        validate_error(resp, ApiErrorId.ERR_NOTICE_PERIOD_INSUFFICIENT, 409)


class TestMarkEffectiveClockGate:
    def test_mark_effective_gated_by_logical_clock(self, api):
        """PRD §2.7: "At startup, before any operator intervention, the logical
        clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to
        wall-clock time."
        PRD §3.11: "From `APPROVED`, the HR partner notifies the employee,
        moving the decision to `NOTIFIED`, and once the logical clock reaches
        the `effective_date` — marking earlier is rejected with
        `ERR_NOT_YET_EFFECTIVE` — marks it `EFFECTIVE`, at which point the
        decision leaves the accrual set and `payroll_accrual_cents` recomputes
        downward."

        Design: Corner/validations/mark_effective_gated_by_logical_clock
        """
        acq = create_kicked_off_acquisition(property_name="Clock Gate")
        dec = get_success_data(api.create_employee_decision(
            create_employee_decision_payload(
                acq["id"], employee_ref="e-c", position="MANAGER",
                notice_date="2026-08-05T00:00:00Z",
                effective_date="2026-08-25T00:00:00Z"),
            HR1), 201)
        get_success_data(api.approve_employee_decision(dec["id"], UM1))
        get_success_data(api.notify_employee_decision(dec["id"], HR1))
        assert get_acquisition(acq["id"])["payroll_accrual_cents"] == 400_000

        # The startup clock is 2026-08-01, ahead of the 2026-08-25 effective date.
        resp = api.mark_employee_decision_effective(dec["id"], HR1)
        validate_error(resp, ApiErrorId.ERR_NOT_YET_EFFECTIVE, 409)

        get_success_data(api.set_clock("2026-08-25T00:00:00Z", ADMIN))
        effective = validate_success(api.mark_employee_decision_effective(dec["id"], HR1))
        assert effective["status"] == "EFFECTIVE"
        assert get_acquisition(acq["id"])["payroll_accrual_cents"] == 0, (
            "EFFECTIVE decisions leave the APPROVED/NOTIFIED accrual set"
        )


class TestRejectedDecisionTerminal:
    def test_rejected_employee_decision_is_terminal(self, api):
        """PRD §3.11: "A manager may also reject a proposal outright into the
        terminal `REJECTED` state." and "`EFFECTIVE`, `REJECTED`, and
        `RESCINDED` are terminal."
        PRD §5: `ERR_INVALID_STATE_TRANSITION` is HTTP 409.

        Design: Corner/state_machines/rejected_employee_decision_is_terminal
        """
        acq = create_kicked_off_acquisition(property_name="Term ED")
        dec = get_success_data(api.create_employee_decision(
            create_employee_decision_payload(acq["id"], employee_ref="emp-9",
                                             accrued_pto_hours=10),
            HR1), 201)
        get_success_data(api.reject_employee_decision(
            dec["id"], UM1, reason="keep staff"))

        resp = api.approve_employee_decision(
            dec["id"], make_underwriting_manager_headers("um-2"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
