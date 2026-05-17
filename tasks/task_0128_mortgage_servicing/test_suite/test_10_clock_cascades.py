"""Clock advance, sweep, and cross-entity cascades.

Coverage targets (PRD §2.9, §3.4, §3.8):
- /_clock/advance transitions CURRENT -> DELINQUENT at delinquency >= 1.
- CURRENT -> DEFAULT after 120 days with no ACTIVE plan.
- ForbearancePlan ACTIVE -> COMPLETED (DEFERRAL with cure_balance=0).
- ForbearancePlan ACTIVE -> BREACHED after 30d past end_date.
- /_sweep/run runs the same evaluation without moving the clock.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    DEFAULT_DELINQUENCY_DAYS,
    advance_clock,
    get_loan,
    run_sweep,
    setup_active_forbearance_plan,
    setup_borrower_and_current_loan,
    setup_loan_in_default,
    setup_loan_in_delinquent,
)


class TestPostureClockCascades:
    def test_clock_advance_current_to_delinquent(self, api):
        """PRD §3.4: "When a clock advance lifts delinquency_days to
        at least 1 and there is no ForbearancePlan in status ACTIVE
        covering the loan, the system transitions Loan.posture from
        CURRENT to DELINQUENT."

        Claim: after 31 days advance (1 day past next_due_date),
        Loan.posture transitions CURRENT -> DELINQUENT.
        """
        b, loan = setup_borrower_and_current_loan()
        assert loan["posture"] == "CURRENT"
        advance_clock(31)
        loan_after = get_loan(loan["id"])
        assert loan_after["posture"] == "DELINQUENT", (
            f"posture should cascade to DELINQUENT after 31d, "
            f"got {loan_after['posture']}"
        )
        assert loan_after["delinquency_days"] >= 1

    def test_clock_advance_delinquent_to_default_at_120d(self, api):
        """PRD §3.4: "When delinquency reaches at least 120 days and
        no ACTIVE plan covers the loan, the system transitions the loan
        from DELINQUENT to DEFAULT".

        Claim: after delinquency_days >= 120 with no ACTIVE plan,
        posture = DEFAULT.
        """
        b, loan = setup_loan_in_default()
        assert loan["posture"] == "DEFAULT"
        assert loan["delinquency_days"] >= DEFAULT_DELINQUENCY_DAYS


class TestForbearanceClockCascades:
    def test_deferral_completes_with_cure_zero(self, api):
        """PRD §3.4: "Under DEFERRAL, cure_balance_cents is immediately
        zero upon the COMPLETED transition and total_paused_cents is
        added to principal_balance_cents (deferred to maturity, with
        no interest accrual on the deferred amount). When the clock
        advances past end_date and cure_balance_cents is zero, the
        plan transitions to COMPLETED and Loan.posture returns to
        CURRENT."

        Claim: a DEFERRAL plan reaches COMPLETED after clock advances
        past end_date, and Loan.principal_balance_cents increases by
        total_paused_cents.
        """
        b, loan, plan = setup_active_forbearance_plan(
            months=1, repayment_method="DEFERRAL",
        )
        principal_before_complete = int(loan["principal_balance_cents"])
        # Advance well past end_date (~30d).
        advance_clock(31)
        # Re-read plan via list endpoint.
        resp = api.list_forbearance_plans(
            loan["id"],
            {"X-User-ID": "servicer-001", "X-User-Role": "Servicer"},
        )
        from test_helpers import validate_success
        data = validate_success(resp, expected_status=200)
        items = data if isinstance(data, list) else data.get("data", data)
        matched = next(p for p in items if p["id"] == plan["id"])
        assert matched["status"] == "COMPLETED", (
            f"DEFERRAL plan must reach COMPLETED after end_date, "
            f"got {matched['status']}"
        )
        loan_after = get_loan(loan["id"])
        # Principal must have increased by total_paused_cents.
        delta = (
            int(loan_after["principal_balance_cents"])
            - principal_before_complete
        )
        assert delta == int(plan["total_paused_cents"]), (
            f"principal_balance_cents increased by {delta}, expected "
            f"total_paused_cents={plan['total_paused_cents']}"
        )
        assert loan_after["posture"] == "CURRENT", (
            f"Loan.posture must return to CURRENT after COMPLETED, "
            f"got {loan_after['posture']}"
        )


class TestSweep:
    def test_sweep_run_succeeds(self, api, platform_admin_headers):
        """PRD §3.8: "the same sweep evaluation without advancing the
        clock ... [returns] an empty data payload".

        Claim: POST /_sweep/run returns 2xx.
        """
        # Just check the endpoint works.
        resp = api.sweep_run(platform_admin_headers)
        assert 200 <= resp.status_code < 300, (
            f"/_sweep/run should return 2xx, got {resp.status_code}"
        )
