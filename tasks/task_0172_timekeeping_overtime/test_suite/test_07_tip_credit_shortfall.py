"""Tip declarations and the tip-credit shortfall calculation.

Covers PRD §3.7 (Tip Declarations and the Tip-Credit Shortfall).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_tip_declaration,
    clock_set,
    create_employee,
    create_tip_declaration_payload,
    finalize_shift,
    get_workweek,
    setup_closed_shift,
    setup_tip_credit_fractional_hours_scenario,
    setup_tip_credit_integer_hours_scenario,
    setup_tipped_employee_closed_shift,
    TEST_DEFAULTS,
    TEST_USERS,
    validate_error,
    validate_success,
)


def setup_module(module):
    clock_set(TEST_DEFAULTS["WORKWEEK_ANCHOR"])


# ===========================================================================
# Tip declaration validation — PRD §3.7
# ===========================================================================
class TestTipDeclarationValidation:

    def test_tip_declaration_on_non_tipped_employee_rejected(self, api):
        """PRD §3.7: "declarations submitted for a non-tipped employee,
        or carrying a negative `declared_tips_cents`, are rejected with
        `ERR_TIPS_NOT_APPLICABLE`."
        """
        closed = setup_closed_shift()
        resp = api.create_tip_declaration(
            closed["shift"]["id"],
            create_tip_declaration_payload(1000),
            TEST_USERS["payroll_admin_headers"],
        )
        validate_error(resp, "ERR_TIPS_NOT_APPLICABLE")

    def test_tip_declaration_with_negative_value_rejected(self, api):
        """PRD §3.7: "carrying a negative `declared_tips_cents`, are
        rejected with `ERR_TIPS_NOT_APPLICABLE`."
        """
        # Build a TIPPED employee + closed shift, then declare negative.
        from test_helpers import setup_tipped_employee_closed_shift
        state = setup_tipped_employee_closed_shift(
            worked_hours=4.0,
            declared_tips_cents=0,  # initial value, unused
        )
        # The fixture already created a tip declaration; build a brand-
        # new tipped shift to probe the negative-value rule cleanly.
        from test_helpers import create_employee, create_shift, post_punch
        from test_helpers import make_employee_headers, clock_advance
        emp = create_employee(
            jurisdiction="FED",
            classification="NON_EXEMPT",
            base_hourly_rate_cents=725,
            tipped_role=True,
            tipped_cash_rate_cents=213,
            applicable_minimum_wage_cents=1500,
        )
        shift = create_shift(emp["id"], duration_hours=4.0)
        clock_set(shift["scheduled_start"])
        emp_headers = make_employee_headers(emp["id"])
        post_punch(shift["id"], "IN", emp_headers)
        clock_advance(int(4.0 * 3600))
        post_punch(shift["id"], "OUT", emp_headers)
        resp = api.create_tip_declaration(
            shift["id"],
            create_tip_declaration_payload(-100),
            TEST_USERS["payroll_admin_headers"],
        )
        validate_error(resp, "ERR_TIPS_NOT_APPLICABLE")


# ===========================================================================
# Tip credit shortfall — PRD §3.7
# ===========================================================================
class TestTipCreditShortfall:

    def test_integer_hour_tip_credit_per_line_rounding(self, api):
        """PRD §3.7: "the `cash_wage_cents` for the shift is worked
        hours multiplied by `tipped_cash_rate_cents`, rounded; the
        minimum-wage-required for the shift is worked hours multiplied
        by `applicable_minimum_wage_cents`, rounded. The
        `tip_credit_applied_cents` is the lesser of
        `declared_tips_cents` and the gap between
        minimum-wage-required and cash-wage (floored at zero). The
        `shortfall_topup_cents` is the gap between minimum-wage-required
        and the sum of cash-wage and `tip_credit_applied_cents`,
        floored at zero".

        Claim: worked=4.0, tipped_cash=213, min=1500, declared=2000 →
        cash=852, min=6000, tip_credit_applied=2000,
        shortfall_topup=3148. PRD §3.1 requires base_hourly_rate_cents
        >= 725 for NON_EXEMPT (the federal minimum floor); the fixture
        uses base=725, so base_line = round(4*725) = 2900.
        gross_pay = base_line(2900) + shortfall_topup(3148) = 6048.
        """
        state = setup_tip_credit_integer_hours_scenario()
        tip = state["tip_declaration"]
        # PRD §3.7 fires the shortfall calculation on Shift CLOSED →
        # FINALIZED; refresh by reading the workweek.
        ww = state["workweek"]
        # PRD §3.6 Step 4 sums shortfall_topup_cents into
        # Workweek.gross_pay_cents alongside the base line.
        # base_line(2900) + 0 OT + 0 DT + 0 premiums + 3148 = 6048.
        assert ww["gross_pay_cents"] == 6048, (
            f"PRD §3.7: gross_pay_cents must equal 6048 (2900 base_line + "
            f"3148 shortfall_topup), got {ww['gross_pay_cents']}"
        )

    def test_fractional_hour_per_line_rounding(self, api):
        """PRD §3.7: "The order in which rounding happens is significant
        and is pinned: both `cash_wage_cents` and minimum-wage-required
        are rounded to whole cents **first**, and then the subtraction
        happens."

        Claim: worked=3.5, tipped_cash=213, min=1500, declared=4000 →
        cash_wage=746 (round(745.5)), min=5250, tip_credit_applied=4000,
        shortfall_topup=504. The alternative sum-then-round variant
        gives a different last-cent value. base_line = round(3.5*725)
        = round(2537.5) = 2538; gross_pay = 2538 + 504 = 3042.
        """
        state = setup_tip_credit_fractional_hours_scenario()
        ww = state["workweek"]
        # PRD §3.6 Step 4: base_line(2538) + shortfall(504) = 3042.
        assert ww["gross_pay_cents"] == 3042, (
            f"PRD §3.7: per-line rounding pins gross_pay to 3042 (2538 + "
            f"504); got {ww['gross_pay_cents']}"
        )


# ===========================================================================
# Tip declaration carries computed fields — PRD §3.7
# ===========================================================================
class TestTipDeclarationFields:

    def test_tip_declaration_on_creation_returns_input_value(self, api):
        """PRD §3.7: "the system tracks one `TipDeclaration` per shift
        carrying ... `declared_tips_cents` (the employee's declared
        tips for the shift, at least zero)".

        Claim: a fresh tip declaration carries declared_tips_cents
        equal to the input.
        """
        from test_helpers import (
            clock_advance, create_employee, create_shift,
            make_employee_headers, post_punch,
        )
        emp = create_employee(
            jurisdiction="FED",
            classification="NON_EXEMPT",
            base_hourly_rate_cents=725,
            tipped_role=True,
            tipped_cash_rate_cents=213,
            applicable_minimum_wage_cents=1500,
        )
        shift = create_shift(emp["id"], duration_hours=4.0)
        clock_set(shift["scheduled_start"])
        emp_headers = make_employee_headers(emp["id"])
        post_punch(shift["id"], "IN", emp_headers)
        clock_advance(int(4.0 * 3600))
        post_punch(shift["id"], "OUT", emp_headers)
        resp = api.create_tip_declaration(
            shift["id"],
            create_tip_declaration_payload(2500),
            TEST_USERS["payroll_admin_headers"],
        )
        tip = validate_success(resp, expected_status=201)
        assert_tip_declaration(tip)
        assert tip["declared_tips_cents"] == 2500
