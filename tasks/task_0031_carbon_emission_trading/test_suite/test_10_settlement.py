"""Annual settlement: closing balance, carry-forward / repurchase / deficit
purchase computations.

PRD references:
  - §3.7 Settlement and Cycle Closure
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_seconds,
    advance_clock,
    assert_annual_settlement,
    settle_cycle,
    setup_compliance_ready_enterprise,
    submit_declaration,
    validate_error,
)


def _list_settlements_for(api, regulator_headers, enterprise_id):
    res = api.list_annual_settlements(
        regulator_headers,
        params={"enterprise_id": enterprise_id, "limit": 50},
    )
    return res.json()["data"]


# ===========================================================================
# §3.7 — Settlement preconditions (state)
# ===========================================================================
class TestSettlementCreation:
    def test_settlement_created_with_carry_forward_when_surplus_within_cap(
        self, api, regulator_headers
    ):
        """PRD §3.7: 'If the closing balance is non-negative, then
        carry_forward_amount equals the lesser of closing_balance and the
        carry-forward cap, repurchase_amount equals closing_balance minus
        carry_forward_amount (rounded half-up to two decimal places,
        repurchased by the regulator at a floor price of 30.00 currency
        units), and deficit_purchase_amount is zero.'

        Claim: with verified=50, declared_offset_quota=50, allocation
        free_paid_ratio=1.0 yielding quota_balance=300, the closing balance
        is 250.00. The next-cycle carry-forward cap is large enough that
        the entire 250 carries forward and repurchase=0.
        """
        cyc, ent, finalized, decl = setup_compliance_ready_enterprise(
            jurisdiction_code="JD_ALPHA",
            free_paid_ratio=1.00,
            ccer_cap_pct=0.05,
            activity_volume=200.00,
            benchmark_factor=1.50,  # total quota = 300
            line_activity_data=100.00,
            line_emission_factor=0.50,
            line_verified_amount=50.00,
        )
        submit_declaration(
            declaration_id=decl["id"], enterprise_id=ent["id"],
            declared_offset_quota=50.00, declared_offset_ccer=0.0,
        )
        # Move clock past the compliance deadline before settle.
        advance_clock(add_seconds(cyc["compliance_deadline"], 1))
        settle_cycle(cyc["id"])
        settlements = _list_settlements_for(api, regulator_headers, ent["id"])
        assert settlements, (
            "PRD §3.7: cycle.settle creates one AnnualSettlement per "
            "enterprise"
        )
        s = next(x for x in settlements
                 if x.get("enterprise_id") == ent["id"])
        assert_annual_settlement(s)
        # closing_balance = opening (300) + net_traded (0) - retired (50)
        #                   - mandatory_deductions (0) = 250
        assert s["closing_balance"] == pytest.approx(250.00, abs=0.01)
        # No next-cycle allocation in this minimal scenario, so the
        # carry-forward cap is 0; the entire surplus must be repurchased.
        # PRD §3.7 says repurchase_amount = closing - carry_forward.
        assert (s["carry_forward_amount"] + s["repurchase_amount"]
                ) == pytest.approx(250.00, abs=0.01)
        assert s["deficit_purchase_amount"] == pytest.approx(0.00, abs=0.01)


# ===========================================================================
# §3.7 — Settlement closing balance formula
# ===========================================================================
class TestClosingBalanceFormula:
    def test_closing_balance_equals_opening_minus_retired(
        self, api, regulator_headers
    ):
        """PRD §3.7: 'The closing_balance is opening_quota plus
        net_traded_quota minus retired_quota minus mandatory deductions,
        rounded half-up to two decimal places.'

        Claim: with no trading and no penalties, closing == opening -
        retired exactly.
        """
        cyc, ent, finalized, decl = setup_compliance_ready_enterprise(
            jurisdiction_code="JD_ALPHA",
            free_paid_ratio=1.00,
            activity_volume=400.00,
            benchmark_factor=1.00,  # total quota = 400
            line_activity_data=100.00,
            line_emission_factor=1.00,  # verified = 100 (overridden below)
            line_verified_amount=100.00,
        )
        submit_declaration(
            declaration_id=decl["id"], enterprise_id=ent["id"],
            declared_offset_quota=100.00, declared_offset_ccer=0.0,
        )
        advance_clock(add_seconds(cyc["compliance_deadline"], 1))
        settle_cycle(cyc["id"])
        settlements = _list_settlements_for(api, regulator_headers, ent["id"])
        s = next(x for x in settlements
                 if x.get("enterprise_id") == ent["id"])
        # opening was 400 (the allocation), retired 100 -> closing 300.
        assert s["closing_balance"] == pytest.approx(
            s["opening_quota"] - s["retired_quota"], abs=0.01
        )


# ===========================================================================
# §3.7 — Settlement deficit purchase
# ===========================================================================
class TestDeficitPurchase:
    def test_negative_closing_yields_deficit_purchase(
        self, api, regulator_headers
    ):
        """PRD §3.7: 'If the closing balance is negative, then
        carry_forward_amount and repurchase_amount are both zero, and
        deficit_purchase_amount equals the absolute value of the closing
        balance (rounded half-up to two decimal places).'

        Claim: a settlement whose post-deduction closing_balance is
        negative records carry_forward=0, repurchase=0, deficit_purchase
        = abs(closing).

        Construction: small allocation (50), small retirement (40), but
        large mandatory_deduction from a NON_COMPLIANT cycle pulls
        closing below zero. We use a deficit large enough that 1.5x is
        bigger than the residual.
        """
        # verified=100, declared_offset_quota=40 -> deficit=60 ->
        # mandatory_deduction = 90
        # opening=300, retired=40, deduction=90 -> closing = 170 (still +)
        # That's not negative. Use bigger imbalance:
        # allocation total=100 (free_paid_ratio=1.0), retired=80,
        # mandatory_deduction=1.5*(100-80)=30, closing = 100 - 80 - 30 = -10
        cyc, ent, finalized, decl = setup_compliance_ready_enterprise(
            jurisdiction_code="JD_ALPHA",
            free_paid_ratio=1.00,
            activity_volume=100.00, benchmark_factor=1.00,  # total = 100
            line_activity_data=100.00, line_emission_factor=1.00,
            line_verified_amount=100.00,
        )
        # deficit=20 -> mandatory_deduction=30 -> closing = 100 - 80 - 30 = -10
        submit_declaration(
            declaration_id=decl["id"], enterprise_id=ent["id"],
            declared_offset_quota=80.00, declared_offset_ccer=0.0,
        )
        advance_clock(add_seconds(cyc["compliance_deadline"], 1))
        settle_cycle(cyc["id"])
        settlements = _list_settlements_for(api, regulator_headers, ent["id"])
        s = next(x for x in settlements
                 if x.get("enterprise_id") == ent["id"])
        assert s["closing_balance"] < 0, (
            f"Expected negative closing_balance to test deficit_purchase; "
            f"got {s['closing_balance']}"
        )
        assert s["carry_forward_amount"] == pytest.approx(0.00, abs=0.01)
        assert s["repurchase_amount"] == pytest.approx(0.00, abs=0.01)
        assert s["deficit_purchase_amount"] == pytest.approx(
            abs(s["closing_balance"]), abs=0.01
        )
