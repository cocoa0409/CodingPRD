"""Calculation rules: last-day determination, final-pay deadlines, PTO payout,
asset deductions, deduction totals, late penalties, posture aggregates.

Covers queue-B corner instances under `calculations` plus queue-A difficulty
instances `dual_variant_calc/*` and `combinatorial_formula/*` and
`boundary_precision_check/*`.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    ApiErrorId,
    assert_instant_equal,
    create_case,
    create_and_approve_case,
    create_case_with_statement,
    create_revocation_task,
    create_asset_item,
    set_clock,
    calculate_statement,
    approve_statement,
    disburse_statement,
    make_task_ready,
    execute_task,
    verify_task,
    HR_INTAKE,
    HR_APPROVER,
    CLERK,
    PAYROLL_CALC,
    PAYROLL_APPROVER,
)


class TestLastDayDetermination:
    def test_last_day_resignation_cap_vs_termination_floor(self):
        """PRD §3.1: "For a `RESIGNATION` or `MUTUAL_SEPARATION`, the employee's
        requested day is honored up to a statutory notice cap: the
        `determined_last_day` becomes the earlier of the `requested_last_day`
        and the date thirty days after the `notice_received_date`. For a
        `TERMINATION` or `JOB_ABANDONMENT`, the company controls the date: the
        `determined_last_day` becomes the later of the `notice_received_date`
        and the `requested_last_day`."

        Design: Corner/calculations/last_day_resignation_cap_vs_termination_floor
        """
        # RESIGNATION case: requested 2026-09-15 > cap 2026-08-31 -> capped at 2026-08-31
        case_a = create_and_approve_case(
            employee_ref="E-C3A", case_type="RESIGNATION", work_state_code="TX",
            notice_received_date="2026-08-01T00:00:00Z",
            requested_last_day="2026-09-15T00:00:00Z",
        )
        assert_instant_equal(case_a["determined_last_day"], "2026-08-31T00:00:00Z")

        # TERMINATION case: same dates -> max(notice, requested) = 2026-09-15
        case_b = create_and_approve_case(
            employee_ref="E-C3B", case_type="TERMINATION", work_state_code="TX",
            notice_received_date="2026-08-01T00:00:00Z",
            requested_last_day="2026-09-15T00:00:00Z",
        )
        assert_instant_equal(case_b["determined_last_day"], "2026-09-15T00:00:00Z")


class TestFinalPayDeadline:
    def test_final_pay_deadline_business_day_rolls_weekend(self):
        """PRD §3.1: "In Illinois, New York, and Washington the rule runs on
        business days: payment is due the next business day after the determined
        last day, skipping Saturdays and Sundays."
        2026-08-14 is a Friday; the next business day is Monday 2026-08-17.

        Design: Corner/calculations/final_pay_deadline_business_day_rolls_weekend
        """
        case = create_and_approve_case(
            employee_ref="E-C1", case_type="TERMINATION", work_state_code="IL",
            notice_received_date="2026-08-14T00:00:00Z",
            requested_last_day="2026-08-14T00:00:00Z",
        )
        assert_instant_equal(case["determined_last_day"], "2026-08-14T00:00:00Z")
        assert_instant_equal(case["final_pay_due_at"], "2026-08-17T00:00:00Z")
        stmts = get_success_data(api_client.list_case_statements(case["id"], PAYROLL_CALC))
        assert stmts[0]["state_law_variant"] == "WITHIN_FIXED_DAYS"

    def test_final_pay_deadline_tx_next_payday_grid(self):
        """PRD §3.1: "In Texas and Florida payment is due on the next regular
        payday after the determined last day, where regular paydays fall on the
        15th and on the last day of each month at 17:00 UTC."
        DL=2026-08-10 -> next payday = 2026-08-15T17:00:00Z.

        Design: Corner/calculations/final_pay_deadline_tx_next_payday_grid
        """
        case = create_and_approve_case(
            employee_ref="E-C2", case_type="RESIGNATION", work_state_code="TX",
            notice_received_date="2026-08-01T00:00:00Z",
            requested_last_day="2026-08-10T00:00:00Z",
        )
        assert_instant_equal(case["final_pay_due_at"], "2026-08-15T17:00:00Z")
        stmts = get_success_data(api_client.list_case_statements(case["id"], PAYROLL_CALC))
        assert stmts[0]["state_law_variant"] == "NEXT_PAYDAY"

    def test_final_pay_deadline_tx_later_payday_grid(self):
        """PRD §3.1: "In Texas and Florida payment is due on the next regular
        payday after the determined last day, where regular paydays fall on the
        15th and on the last day of each month at 17:00 UTC."
        DL=2026-08-16 -> next payday = 2026-08-31T17:00:00Z.

        Design: Corner/calculations/final_pay_deadline_tx_next_payday_grid
        """
        case = create_and_approve_case(
            employee_ref="E-C2B", case_type="RESIGNATION", work_state_code="TX",
            notice_received_date="2026-08-01T00:00:00Z",
            requested_last_day="2026-08-16T00:00:00Z",
        )
        # 2026-08-16 is a Sunday -> weekend roll forward to Monday 2026-08-17.
        # Next payday strictly after 2026-08-17 is 2026-08-31T17:00:00Z.
        assert_instant_equal(case["determined_last_day"], "2026-08-17T00:00:00Z")
        assert_instant_equal(case["final_pay_due_at"], "2026-08-31T17:00:00Z")


class TestPTOPayout:
    def test_pto_zero_balance_pays_zero(self):
        """PRD §3.3: "The state-law variant pays the full `pto_balance_hours`
        multiplied by `hourly_wage_cents` when the `work_state_code` is one of
        `CA`, `CO`, `IL`, or `MA`, and zero in the other four states." A zero
        balance pays zero under either variant, and the greater-of-two rule keeps
        it zero.

        Design: Corner/calculations/pto_zero_balance_pays_zero
        """
        case, stmt = create_case_with_statement(
            employee_ref="E-C4", work_state_code="CA", pto_balance_hours=0.0,
            tenure_years=6.0,
        )
        calculated = calculate_statement(stmt, regular_wages_cents=50000)
        assert calculated["pto_payout_cents"] == 0
        assert calculated["net_pay_cents"] == 50000

    def test_pto_payout_state_vs_company_divergence_tx_branch(self):
        """PRD §3.3: "It first computes the PTO payout, which always evaluates
        two methods and pays the greater. The state-law variant pays the full
        `pto_balance_hours` multiplied by `hourly_wage_cents` when the
        `work_state_code` is one of `CA`, `CO`, `IL`, or `MA`, and zero in the
        other four states. The company-policy variant caps payable hours by
        tenure — 40 hours when `tenure_years` is under two, ... takes the lesser
        of the balance and the cap, rounds the payable hours down to the nearest
        half hour, and multiplies by the wage. The `pto_payout_cents` stored on
        the statement is the greater of the two variants, rounded half-up to a
        whole cent."

        TX, balance=50h, tenure=1.0, wage=5000: state=0, company=min(50,40)*5000=200000.

        Design: Difficulty/dual_variant_calc/pto_payout_state_vs_company_divergence
        """
        case_tx, stmt_tx = create_case_with_statement(
            employee_ref="E-TX-1", case_type="RESIGNATION", work_state_code="TX",
            pto_balance_hours=50.0, tenure_years=1.0, hourly_wage_cents=5000,
        )
        calc_tx = calculate_statement(stmt_tx, regular_wages_cents=100000)
        assert calc_tx["pto_payout_cents"] == 200000
        assert calc_tx["state_law_variant"] == "NEXT_PAYDAY"

    def test_pto_payout_state_vs_company_divergence_ca_branch(self):
        """PRD §3.3: "The state-law variant pays the full `pto_balance_hours`
        multiplied by `hourly_wage_cents` when the `work_state_code` is one of
        `CA`, `CO`, `IL`, or `MA`..." CA, balance=50h, tenure=1.0, wage=5000:
        state=250000, company=200000 -> greater is 250000.

        Design: Difficulty/dual_variant_calc/pto_payout_state_vs_company_divergence
        """
        case_ca, stmt_ca = create_case_with_statement(
            employee_ref="E-CA-1", case_type="RESIGNATION", work_state_code="CA",
            pto_balance_hours=50.0, tenure_years=1.0, hourly_wage_cents=5000,
        )
        calc_ca = calculate_statement(stmt_ca, regular_wages_cents=100000)
        assert calc_ca["pto_payout_cents"] == 250000
        assert calc_ca["state_law_variant"] == "WITHIN_FIXED_DAYS"


class TestPTOTierCap:
    def test_pto_tiered_cap_below_two_year_tenure(self):
        """PRD §3.3: "The company-policy variant caps payable hours by tenure —
        40 hours when `tenure_years` is under two..." TX, tenure=1.9, balance=100,
        wage=5000 -> company = min(100, 40) * 5000 = 200000 (state variant = 0).

        Design: Difficulty/combinatorial_formula/pto_tiered_cap_nested_min_max
        """
        case, stmt = create_case_with_statement(
            employee_ref="E-T1", case_type="RESIGNATION", work_state_code="TX",
            pto_balance_hours=100.0, tenure_years=1.9, hourly_wage_cents=5000,
        )
        calc = calculate_statement(stmt, regular_wages_cents=0)
        assert calc["pto_payout_cents"] == 200000

    def test_pto_tiered_cap_at_two_year_boundary(self):
        """PRD §3.3: "... 80 hours when it is at least two but under five ..."
        TX, tenure=2.0 (inclusive of the 80-hour tier), balance=100, wage=5000
        -> company = min(100, 80) * 5000 = 400000.

        Design: Difficulty/combinatorial_formula/pto_tiered_cap_nested_min_max
        """
        case, stmt = create_case_with_statement(
            employee_ref="E-T2", case_type="RESIGNATION", work_state_code="TX",
            pto_balance_hours=100.0, tenure_years=2.0, hourly_wage_cents=5000,
        )
        calc = calculate_statement(stmt, regular_wages_cents=0)
        assert calc["pto_payout_cents"] == 400000


class TestAssetDeductionRounding:
    def test_asset_deduction_per_item_rounding_then_sum(self):
        """PRD §2.8: "Rounding order is pinned for asset deductions: each item's
        deduction is computed and rounded to a whole cent first, and case-level
        totals then sum those integers. The system never sums unrounded values
        and rounds once at the end." PRD §3.4: "the deduction is half of the
        replacement cost for a damaged item and the full replacement cost for a
        destroyed one, rounded half-up to a whole cent."

        Two OTHER assets at 101 cents each, both DAMAGED: per-item round-half-up
        gives 51 each, projected total 102 (not 101 from sum-then-round).

        Design: Difficulty/combinatorial_formula/asset_deduction_per_item_rounding_then_sum
        """
        case = create_and_approve_case(employee_ref="E-R")
        item1 = create_asset_item(case["id"], asset_tag="A1", asset_kind="OTHER",
                                  replacement_cost_cents=101, issued_date="2026-01-01T00:00:00Z")
        item2 = create_asset_item(case["id"], asset_tag="A2", asset_kind="OTHER",
                                  replacement_cost_cents=101, issued_date="2026-01-01T00:00:00Z")
        r1 = validate_success(api_client.record_asset_return(
            item1["id"],
            {"condition_on_return": "DAMAGED",
             "expected_asset_return_item_version": item1["version"]},
            CLERK,
        ))
        r2 = validate_success(api_client.record_asset_return(
            item2["id"],
            {"condition_on_return": "DAMAGED",
             "expected_asset_return_item_version": item2["version"]},
            CLERK,
        ))
        assert r1["deduction_amount_cents"] == 51
        assert r2["deduction_amount_cents"] == 51

        summary = get_success_data(api_client.get_case_summary(case["id"], PAYROLL_CALC))
        assert summary["projected_deduction_cents"] == 102

    def test_asset_deduction_per_item_rounding_each_is_half_up(self):
        """PRD §3.4: "the deduction is half of the replacement cost for a
        damaged item ... rounded half-up to a whole cent." 101 * 0.5 = 50.5 ->
        51 by round-half-up at the item level.

        Design: Difficulty/combinatorial_formula/asset_deduction_per_item_rounding_then_sum
        """
        case = create_and_approve_case(employee_ref="E-R2")
        item = create_asset_item(case["id"], asset_tag="A1", asset_kind="OTHER",
                                 replacement_cost_cents=101, issued_date="2026-01-01T00:00:00Z")
        r = validate_success(api_client.record_asset_return(
            item["id"],
            {"condition_on_return": "DAMAGED",
             "expected_asset_return_item_version": item["version"]},
            CLERK,
        ))
        assert r["deduction_amount_cents"] == 51


class TestAssetDeductionVariants:
    def test_asset_deduction_default_variant_depreciation(self):
        """PRD §3.4: "Defaulting runs the depreciated-value variant of the
        deduction: the item's age is the whole number of days between
        `issued_date` and `return_due_at`, with any partial day discarded;
        depreciation accrues in basis points per day at a per-kind rate — 20 for
        a `LAPTOP`, 25 for a `PHONE`, and 10 for every other kind — capped at
        7,000 basis points; the depreciated value is the replacement cost scaled
        by the share of ten thousand that remains after depreciation; and the
        deduction is that value rounded half-up to a whole cent."

        LAPTOP, cost=200000, issued=2026-01-01, return_due=2026-08-13 -> age=224d,
        dep=min(224*20, 7000)=4480 bps, value=200000*(10000-4480)/10000=110400.

        Design: Difficulty/dual_variant_calc/asset_deduction_default_vs_damage_divergence
        """
        case = create_and_approve_case(employee_ref="E-A")
        item = create_asset_item(case["id"], asset_tag="L1", asset_kind="LAPTOP",
                                 replacement_cost_cents=200000, issued_date="2026-01-01T00:00:00Z")
        # Push the case to PAYROLL_PENDING so mark-defaulted is legal, then advance
        # the clock past return_due_at + 7 days.
        task = create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
        set_clock("2026-08-10T17:00:00Z")
        execute_task(task["id"], outcome="SUCCESS")
        verify_task(task["id"], outcome="VERIFIED")
        set_clock("2026-08-21T00:00:00Z")

        defaulted = validate_success(api_client.mark_asset_defaulted(item["id"], PAYROLL_CALC))
        assert defaulted["status"] == "DEFAULTED"
        assert defaulted["deduction_status"] == "APPLIED"
        assert defaulted["deduction_amount_cents"] == 110400

    def test_asset_deduction_damage_variant_destroyed_full_cost(self):
        """PRD §3.4: "the deduction is half of the replacement cost for a
        damaged item and the full replacement cost for a destroyed one, rounded
        half-up to a whole cent, and the item's `deduction_status` becomes
        `COMPUTED`." DESTROYED -> full 200000.

        Design: Difficulty/dual_variant_calc/asset_deduction_default_vs_damage_divergence
        """
        case = create_and_approve_case(employee_ref="E-B")
        item = create_asset_item(case["id"], asset_tag="L2", asset_kind="LAPTOP",
                                 replacement_cost_cents=200000, issued_date="2026-01-01T00:00:00Z")
        r = validate_success(api_client.record_asset_return(
            item["id"],
            {"condition_on_return": "DESTROYED",
             "expected_asset_return_item_version": item["version"]},
            CLERK,
        ))
        assert r["deduction_amount_cents"] == 200000
        assert r["deduction_status"] == "COMPUTED"


class TestDeductionCapFloor:
    def test_deduction_cap_floor_net_zero(self):
        """PRD §3.3: "the deduction applied is the lesser of the case's
        `deduction_total_cents` and that gross, so deductions can never drive
        net pay below zero; and `net_pay_cents` is gross minus the applied
        deduction." PRD §2.8: "deductions may never push an employee's net pay
        below zero, so the deduction applied to a statement is capped at gross
        pay."

        VEHICLE, cost=300000, issued=2026-08-01, return_due=2026-08-13 -> age=12d,
        dep=12*10=120bps, value=300000*0.988=296400. Statement gross=1000 ->
        deduction capped at 1000, net=0.

        Design: Corner/calculations/deduction_cap_floor_net_zero
        """
        case, stmt = create_case_with_statement(employee_ref="E-C5")
        item = create_asset_item(case["id"], asset_tag="V1", asset_kind="VEHICLE",
                                 replacement_cost_cents=300000, issued_date="2026-08-01T00:00:00Z")
        calc = calculate_statement(stmt, regular_wages_cents=1000)
        assert calc["net_pay_cents"] == 1000
        # Push case to PAYROLL_PENDING and clock past return_due+7d.
        task = create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
        set_clock("2026-08-10T17:00:00Z")
        execute_task(task["id"], outcome="SUCCESS")
        verify_task(task["id"], outcome="VERIFIED")
        set_clock("2026-08-21T00:00:00Z")
        validate_success(api_client.mark_asset_defaulted(item["id"], PAYROLL_CALC))

        case_after = get_success_data(api_client.get_case(case["id"], HR_INTAKE))
        assert case_after["deduction_total_cents"] == 296400

        stmt_after = get_success_data(api_client.get_statement(stmt["id"], PAYROLL_CALC))
        assert stmt_after["deduction_total_cents"] == 1000
        assert stmt_after["net_pay_cents"] == 0


class TestNotificationDedupe:
    def test_notification_dedupe_window(self):
        """PRD §3.8: "When a notification is created and an unsuppressed
        notification of the same kind already exists for the same case whose
        `sent_at` falls within the preceding sixty minutes — the window includes
        the earlier dispatch instant and excludes the instant exactly sixty
        minutes after it — the new row is still persisted but flagged
        `suppressed`, queryable yet never dispatched."

        First INTAKE_ALERT per case is always unsuppressed.

        Design: Corner/calculations/notification_dedupe_window
        """
        case = create_case(employee_ref="E-C6A", work_state_code="TX")
        rows = get_success_data(api_client.list_case_notifications(case["id"], HR_INTAKE))
        intake_rows = [r for r in rows if r["notification_kind"] == "INTAKE_ALERT"]
        assert len(intake_rows) == 1
        assert intake_rows[0]["suppressed"] is False


class TestLatePenalty:
    def test_late_penalty_one_second_past_due_is_full_first_day(self):
        """PRD §3.3: "The penalty accrues at the employee's daily wage, defined
        as eight hours at the `hourly_wage_cents`, for each late calendar day
        with any fractional day rounded up to a full day, capped at thirty days.
        A disbursement exactly at `due_at` is on-time; one second past it is
        already one full day of penalty." PRD §3.3: "Disbursing after `due_at`
        is not rejected — the law is violated but the employee must still be
        paid — and instead lands the statement in `LATE`, stamping
        `disbursed_at` and computing a waiting-time penalty."

        CA RESIGNATION notice 2026-08-01, requested 2026-08-10: notice >=72h so
        due_at == DL == 2026-08-10T00:00:00Z. The clock is advanced one second
        past due_at while the statement is still CALCULATED (the scheduler marks
        only APPROVED statements late), then the statement is approved and the
        late disbursement lands it in LATE: ceil(1s/1d)=1 day * (5000*8)=40000.

        Design: Difficulty/boundary_precision_check/late_penalty_one_second_past_due
        """
        case, stmt = create_case_with_statement(
            employee_ref="E-B1B", case_type="RESIGNATION", work_state_code="CA",
            notice_received_date="2026-08-01T00:00:00Z",
            requested_last_day="2026-08-10T00:00:00Z",
        )
        calculate_statement(stmt, regular_wages_cents=100000)
        set_clock("2026-08-10T00:00:01Z")
        approve_statement(stmt["id"])
        disbursed = disburse_statement(stmt["id"])
        assert disbursed["status"] == "LATE"
        assert disbursed["late_penalty_cents"] == 40000

    def test_late_penalty_exactly_at_due_is_on_time(self):
        """PRD §3.3: "A disbursement exactly at `due_at` is on-time; one second
        past it is already one full day of penalty."

        Disbursement at exactly due_at lands in DISBURSED with zero penalty.

        Design: Difficulty/boundary_precision_check/late_penalty_one_second_past_due
        """
        case, stmt = create_case_with_statement(
            employee_ref="E-B1A", case_type="RESIGNATION", work_state_code="CA",
            notice_received_date="2026-08-01T00:00:00Z",
            requested_last_day="2026-08-10T00:00:00Z",
        )
        calculate_statement(stmt, regular_wages_cents=100000)
        set_clock("2026-08-10T00:00:00Z")
        approve_statement(stmt["id"])
        disbursed = disburse_statement(stmt["id"])
        assert disbursed["status"] == "DISBURSED"
        assert disbursed["late_penalty_cents"] == 0

    def test_late_penalty_cap_at_30_days(self):
        """PRD §3.3: "The penalty accrues at the employee's daily wage, defined
        as eight hours at the `hourly_wage_cents`, for each late calendar day
        with any fractional day rounded up to a full day, capped at thirty days."
        PRD §3.3: "Disbursing after `due_at` is not rejected — the law is
        violated but the employee must still be paid — and instead lands the
        statement in `LATE`, stamping `disbursed_at` and computing a
        waiting-time penalty."

        The clock is advanced 40 days + 1s past due_at while the statement is
        still CALCULATED (the scheduler marks only APPROVED statements late),
        then the statement is approved and disbursed late:
        cap 30 days * 40000 = 1200000.

        Design: Corner/calculations/late_penalty_cap_at_30_days
        """
        case, stmt = create_case_with_statement(
            employee_ref="E-C7", case_type="RESIGNATION", work_state_code="CA",
        )
        calculate_statement(stmt, regular_wages_cents=100000)
        set_clock("2026-09-19T00:00:01Z")
        approve_statement(stmt["id"])
        disbursed = disburse_statement(stmt["id"])
        assert disbursed["status"] == "LATE"
        assert disbursed["late_penalty_cents"] == 1200000
