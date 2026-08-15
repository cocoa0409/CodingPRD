"""Proration of mid-period effective dates and statement computed fields."""
from test_helpers import (
    add_statement,
    list_order_events,
    make_employer,
    make_employee,
    make_open_run,
    make_state_rule,
    set_clock,
    setup_paid_single_order,
)


class TestProrationRoundingOrder:
    def test_proration_exact_then_round_award(self, api):
        """PRD §3.6: "An order whose `effective_date` falls strictly inside the
        period is prorated: the numerator is the count of days from the later
        of the `effective_date` and the `period_start` through the
        `period_end`, inclusive, and the denominator is the total count of days
        in the period, inclusive; the ratio is applied at full precision before
        any rounding."
        PRD §3.6: "a `FIXED_AMOUNT_PER_PERIOD` order demands its `amount_value`
        cents times the proration factor, rounded half-up once"
        FIXED 10001 effective 2026-08-06 in the 15-day period 08-01..08-15:
        factor 10/15 at full precision, rhu(10001*10/15) = 6667 — not the
        6701 that rounding the factor first would produce.

        Design: Difficulty/combinatorial_formula/proration_rounding_order_exact_then_round
        """
        base = setup_paid_single_order(
            order_overrides={
                "amount_model": "FIXED_AMOUNT_PER_PERIOD",
                "amount_value": 10001,
                "total_balance_cents": 500000,
                "effective_date": "2026-08-06",
            },
            statement_overrides={
                "gross_earnings_cents": 150000,
                "mandatory_deductions_cents": 30000,
            },
        )
        assert base["statement"]["total_withheld_cents"] == 6667
        assert base["order"]["withheld_cents"] == 6667

    def test_prorated_event_basis(self, api):
        """PRD §3.6: "Every posted event's `computation_proof` captures the
        allocation context at posting time — `disposable_earnings_cents`,
        `pool_cents`, `cap_fraction`, `cap_cents`, `floor_cents`, the order's
        `rank`, and the `basis` of the award, one of `FULL`, `PRORATED` when
        the effective date fell inside the period, `CAPPED_BY_STATE`,
        `CAPPED_BY_POOL`, `CAPPED_BY_BALANCE`, `FINAL_PARTIAL` when the award
        closed the balance, or `BLOCKED_BY_SUPPORT` for the creditor
        non-compete."

        Design: Difficulty/combinatorial_formula/proration_rounding_order_exact_then_round
        """
        base = setup_paid_single_order(
            order_overrides={
                "amount_model": "FIXED_AMOUNT_PER_PERIOD",
                "amount_value": 10001,
                "total_balance_cents": 500000,
                "effective_date": "2026-08-06",
            },
            statement_overrides={
                "gross_earnings_cents": 150000,
                "mandatory_deductions_cents": 30000,
            },
        )
        events = list_order_events(base["order"]["id"])
        assert len(events) == 1
        assert events[0]["amount_cents"] == 6667
        assert events[0]["computation_proof"]["basis"] == "PRORATED"


class TestEffectiveDateWindowBoundary:
    def test_effective_on_period_start_uses_full_factor(self, api):
        """PRD §3.6: "An order effective on or before the `period_start` uses
        a factor of one — no proration."
        Effective 2026-08-01 == period_start: the full FIXED 10001 demand is
        awarded (factor 1), boundary between full and prorated.

        Design: Difficulty/resource_temporal_overlap/retroactive_effective_date_window_intersection
        """
        base = setup_paid_single_order(
            order_overrides={
                "amount_model": "FIXED_AMOUNT_PER_PERIOD",
                "amount_value": 10001,
                "total_balance_cents": 500000,
                "effective_date": "2026-08-01",
            },
            statement_overrides={
                "gross_earnings_cents": 150000,
                "mandatory_deductions_cents": 30000,
            },
        )
        assert base["statement"]["total_withheld_cents"] == 10001
        assert base["order"]["withheld_cents"] == 10001

    def test_effective_inside_period_intersects_partial_window(self, api):
        """PRD §3.6: "An order whose `effective_date` falls strictly inside the
        period is prorated: the numerator is the count of days from the later
        of the `effective_date` and the `period_start` through the
        `period_end`, inclusive, and the denominator is the total count of days
        in the period, inclusive; the ratio is applied at full precision before
        any rounding."
        Effective 2026-08-06 intersects only 10 of the 15 period days, so the
        same FIXED 10001 order awards 6667 instead of 10001.

        Design: Difficulty/resource_temporal_overlap/retroactive_effective_date_window_intersection
        """
        base = setup_paid_single_order(
            order_overrides={
                "amount_model": "FIXED_AMOUNT_PER_PERIOD",
                "amount_value": 10001,
                "total_balance_cents": 500000,
                "effective_date": "2026-08-06",
            },
            statement_overrides={
                "gross_earnings_cents": 150000,
                "mandatory_deductions_cents": 30000,
            },
        )
        assert base["statement"]["total_withheld_cents"] == 6667
        assert base["order"]["withheld_cents"] == 6667


class TestStatementComputedFields:
    def test_statement_computes_disposable_earnings_at_creation(self, api):
        """PRD §3.5: "At creation the statement computes its
        `disposable_earnings_cents` as `gross_earnings_cents` minus
        `mandatory_deductions_cents`, records its `payroll_run_id` and
        denormalized `employer_id`, and appends an audit entry (action
        `statement.create`)."
        gross 100000 minus deductions 25000 yields disposable earnings 75000.

        Design: Corner/entities/paystatement_computed_fields_ignore_client_input
        """
        set_clock()
        make_state_rule("CA")
        emp = make_employer()
        ee = make_employee(emp["id"])
        run = make_open_run(emp["id"])
        stmt = add_statement(
            run["id"], ee["id"],
            gross_earnings_cents=100000, mandatory_deductions_cents=25000,
        )
        assert stmt["disposable_earnings_cents"] == 75000
        assert stmt["payroll_run_id"] == run["id"]
        assert stmt["employer_id"] == emp["id"]
