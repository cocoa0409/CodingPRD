"""Withholding waterfall: protected-floor variants, the min-of-four award, fees."""
from test_helpers import (
    add_statement,
    drive_order_to_active,
    get_statement,
    list_order_events,
    make_authority,
    make_employer,
    make_employee,
    make_open_run,
    make_state_rule,
    pay_run_fresh,
    receive_order,
    set_clock,
    setup_paid_single_order,
)


class TestFloorVariants:
    def test_weekly_normalized_floor_variant_ca(self, api):
        """PRD §3.6: "For an employee whose `work_state_code` is anything other
        than `TX`, the weekly floor is the state's `min_wage_multiplier` times
        725 cents — the federal minimum hourly wage — times forty hours, and the
        period floor is that weekly floor scaled by the employee's
        `pay_frequency`: a factor of 1 for `WEEKLY`, 2 for `BIWEEKLY`, 2.1667
        for `SEMIMONTHLY`, and 4.3333 for `MONTHLY`, with the resulting period
        floor rounded half-up to whole cents."
        PRD §3.6: "The withholding pool is disposable earnings minus the period
        floor, or zero when the floor meets or exceeds disposable earnings."
        CA SEMIMONTHLY, mult 0.75: floor = rhu(0.75*725*40*2.1667) = 47126,
        pool = 200000 - 47126 = 152874; 25% of DE awards 50000.

        Design: Difficulty/dual_variant_calc/floor_variant_weekly_normalized_vs_hourly_test
        """
        base = setup_paid_single_order(
            order_overrides={
                "amount_model": "PERCENT_OF_DISPOSABLE",
                "amount_value": 2500,
                "total_balance_cents": 900000,
                "effective_date": "2026-08-01",
            },
            statement_overrides={
                "gross_earnings_cents": 250000,
                "mandatory_deductions_cents": 50000,
            },
        )
        stmt = base["statement"]
        assert stmt["disposable_earnings_cents"] == 200000
        assert stmt["total_withheld_cents"] == 50000
        events = list_order_events(base["order"]["id"])
        assert len(events) == 1, "exactly one WITHHOLD event expected"
        proof = events[0]["computation_proof"]
        assert proof["disposable_earnings_cents"] == 200000
        assert proof["floor_cents"] == 47126
        assert proof["pool_cents"] == 152874

    def test_hourly_test_floor_variant_tx(self, api):
        """PRD §3.6: "For a Texas employee the period floor is instead the
        statement's `hours_worked` times the state's `hourly_floor_cents`,
        rounded half-up to cents, and neither the federal multiplier nor the
        pay frequency plays any role."
        Identical statement inputs to the CA case (DE 200000) but the TX
        hourly floor is 40 x 1000 = 40000, so the pool is 160000 — the two
        floor variants diverge on the same gross/deductions.

        Design: Difficulty/dual_variant_calc/floor_variant_weekly_normalized_vs_hourly_test
        """
        base = setup_paid_single_order(
            state_code="TX",
            state_rule_overrides={
                "hourly_floor_cents": 1000,
                "fee_deductible_from_wages": False,
            },
            employee_overrides={"work_state_code": "TX", "hourly_rate_cents": 2000},
            order_overrides={
                "amount_model": "PERCENT_OF_DISPOSABLE",
                "amount_value": 2500,
                "total_balance_cents": 900000,
                "effective_date": "2026-08-01",
            },
            statement_overrides={
                "gross_earnings_cents": 250000,
                "mandatory_deductions_cents": 50000,
            },
            hours_worked=40,
        )
        stmt = base["statement"]
        assert stmt["disposable_earnings_cents"] == 200000
        assert stmt["total_withheld_cents"] == 50000
        events = list_order_events(base["order"]["id"])
        assert len(events) == 1
        proof = events[0]["computation_proof"]
        assert proof["floor_cents"] == 40000
        assert proof["pool_cents"] == 160000


class TestMinOfFourAward:
    def test_balance_term_wins_min_chain(self, api):
        """PRD §3.6: "The award is the smallest of four quantities: the raw
        demand, the state cap, the pool still remaining, and the order's
        `remaining_balance_cents`."
        FIXED 100000 demand, cap 125000, pool 187166, balance 90000 — the
        balance term wins, so 90000 is withheld and net pay is 160000.

        Design: Difficulty/combinatorial_formula/waterfall_min4_chain_cap_balance_pool
        """
        base = setup_paid_single_order(
            state_rule_overrides={"min_wage_multiplier": 1.0},
            order_overrides={
                "amount_model": "FIXED_AMOUNT_PER_PERIOD",
                "amount_value": 100000,
                "total_balance_cents": 90000,
                "effective_date": "2026-08-01",
            },
            statement_overrides={
                "gross_earnings_cents": 300000,
                "mandatory_deductions_cents": 50000,
            },
        )
        stmt = base["statement"]
        assert stmt["total_withheld_cents"] == 90000
        assert stmt["net_pay_cents"] == 160000

    def test_final_partial_award_satisfies_order(self, api):
        """PRD §3.6: "When an award equals the order's remaining balance before
        the award, the order is satisfied on the spot: its `processing_status`
        becomes `SATISFIED`, its `remit_posture` closes, its final event carries
        the basis `FINAL_PARTIAL`, sibling orders on the same employee absorb
        the freed pool within the same waterfall pass without any re-run, and
        an audit entry (action `order.satisfy`) is appended."

        Design: Difficulty/combinatorial_formula/waterfall_min4_chain_cap_balance_pool
        """
        base = setup_paid_single_order(
            state_rule_overrides={"min_wage_multiplier": 1.0},
            order_overrides={
                "amount_model": "FIXED_AMOUNT_PER_PERIOD",
                "amount_value": 100000,
                "total_balance_cents": 90000,
                "effective_date": "2026-08-01",
            },
            statement_overrides={
                "gross_earnings_cents": 300000,
                "mandatory_deductions_cents": 50000,
            },
        )
        order = base["order"]
        assert order["processing_status"] == "SATISFIED"
        assert order["remit_posture"] == "CLOSED"
        assert order["remaining_balance_cents"] == 0
        assert order["withheld_cents"] == 90000
        events = list_order_events(order["id"])
        assert len(events) == 1
        assert events[0]["computation_proof"]["basis"] == "FINAL_PARTIAL"


class TestFloorBoundary:
    def test_floor_equality_yields_zero_pool(self, api):
        """PRD §3.6: "The withholding pool is disposable earnings minus the
        period floor, or zero when the floor meets or exceeds disposable
        earnings."
        PRD §3.6: "a zero award contributes a line to the statement's
        `computation_breakdown` but posts no event."
        TX hourly floor 40 x 1000 = 40000 exactly equals DE 40000: pool is 0,
        nothing may be withheld, net pay stays 40000.

        Design: Difficulty/boundary_precision_check/floor_equality_zero_pool
        """
        base = setup_paid_single_order(
            state_code="TX",
            state_rule_overrides={
                "hourly_floor_cents": 1000,
                "fee_deductible_from_wages": False,
            },
            employee_overrides={"work_state_code": "TX", "hourly_rate_cents": 2000},
            order_overrides={
                "amount_model": "FIXED_AMOUNT_PER_PERIOD",
                "amount_value": 5000,
                "effective_date": "2026-08-01",
            },
            statement_overrides={
                "gross_earnings_cents": 60000,
                "mandatory_deductions_cents": 20000,
            },
            hours_worked=40,
        )
        stmt = base["statement"]
        assert stmt["total_withheld_cents"] == 0
        assert stmt["net_pay_cents"] == 40000
        assert base["order"]["withheld_cents"] == 0
        assert list_order_events(base["order"]["id"]) == []
        breakdown = stmt["computation_breakdown"]
        line = [b for b in breakdown if b["order_id"] == base["order"]["id"]]
        assert len(line) == 1 and line[0]["awarded_cents"] == 0

    def test_one_cent_above_floor_awards_one_cent(self, api):
        """PRD §3.6: "The withholding pool is disposable earnings minus the
        period floor, or zero when the floor meets or exceeds disposable
        earnings."
        One cent above the boundary: DE 40001 against the same 40000 floor
        leaves a pool of exactly 1, so the award is a single cent and net pay
        lands exactly on the floor.

        Design: Difficulty/boundary_precision_check/floor_equality_zero_pool
        """
        base = setup_paid_single_order(
            state_code="TX",
            state_rule_overrides={
                "hourly_floor_cents": 1000,
                "fee_deductible_from_wages": False,
            },
            employee_overrides={"work_state_code": "TX", "hourly_rate_cents": 2000},
            order_overrides={
                "amount_model": "FIXED_AMOUNT_PER_PERIOD",
                "amount_value": 5000,
                "effective_date": "2026-08-01",
            },
            statement_overrides={
                "gross_earnings_cents": 60001,
                "mandatory_deductions_cents": 20000,
            },
            hours_worked=40,
        )
        stmt = base["statement"]
        assert stmt["total_withheld_cents"] == 1
        assert stmt["net_pay_cents"] == 40000
        assert base["order"]["withheld_cents"] == 1
        events = list_order_events(base["order"]["id"])
        assert len(events) == 1 and events[0]["amount_cents"] == 1


class TestAdminFee:
    def test_admin_fee_deductible_vs_borne_by_employer(self, api):
        """PRD §3.6: "Under `PER_ORDER`, the statement's `total_admin_fee_cents`
        is the employer's `admin_fee_cents` multiplied by the count of orders
        that received positive awards on that statement. When the state's
        `fee_deductible_from_wages` is true, the fee comes out of the employee:
        net pay is disposable earnings minus total withheld minus the fee, and
        if the full fee would push net pay below zero the fee is clipped to
        disposable earnings minus total withheld, leaving net pay at exactly
        zero. When `fee_deductible_from_wages` is false, the fee is recorded on
        the statement but borne by the employer, and net pay is simply
        disposable earnings minus total withheld."
        CA (deductible): net = 80000 - 10000 - 500 = 69500.
        TX (employer-borne): fee recorded 500, net = 80000 - 10000 = 70000.

        Design: Corner/calculations/admin_fee_deductible_vs_borne_by_employer
        """
        set_clock()
        make_state_rule("CA", min_wage_multiplier=0.75, fee_deductible_from_wages=True)
        make_state_rule(
            "TX",
            min_wage_multiplier=0.75,
            hourly_floor_cents=1000,
            fee_deductible_from_wages=False,
        )
        auth = make_authority()

        # CA employer (fee deductible from wages)
        emp_a = make_employer(administrative_fee_policy="PER_ORDER", admin_fee_cents=500)
        ee_a = make_employee(emp_a["id"], work_state_code="CA")
        ord_a = receive_order(ee_a["id"], auth["id"], case_number="CS-FA",
                              amount_value=10000)
        drive_order_to_active(ord_a["id"])
        run_a = make_open_run(emp_a["id"])
        stmt_a = add_statement(run_a["id"], ee_a["id"],
                               gross_earnings_cents=100000,
                               mandatory_deductions_cents=20000)
        pay_run_fresh(emp_a["id"], run_a["id"])

        # TX employer (fee borne by employer)
        emp_b = make_employer(administrative_fee_policy="PER_ORDER", admin_fee_cents=500)
        ee_b = make_employee(emp_b["id"], work_state_code="TX", hourly_rate_cents=2000)
        ord_b = receive_order(ee_b["id"], auth["id"], case_number="CS-FB",
                              amount_value=10000)
        drive_order_to_active(ord_b["id"])
        run_b = make_open_run(emp_b["id"])
        stmt_b = add_statement(run_b["id"], ee_b["id"],
                               gross_earnings_cents=100000,
                               mandatory_deductions_cents=20000,
                               hours_worked=40)
        pay_run_fresh(emp_b["id"], run_b["id"])

        a = get_statement(stmt_a["id"])
        b = get_statement(stmt_b["id"])
        assert a["total_admin_fee_cents"] == 500
        assert a["net_pay_cents"] == 69500
        assert b["total_admin_fee_cents"] == 500
        assert b["net_pay_cents"] == 70000
