"""Applicant screening gate and the late-fee sweep — depth tests.

Covers the conjunctive screening gate, its credit-score boundary, and the
late-fee round-then-add-flat ordering with its strict grace-cutoff boundary.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success,
    create_applicant_payload, create_lease_payload,
)
from test_helpers.fixtures import (
    PM, create_unit, create_screened_applicant, create_submitted_applicant,
    setup_active_lease, post_rent_charge, assess_late_fees, list_late_fee_charges,
)


class TestScreeningGate:
    def test_high_rti_fails_despite_passing_credit(self, api):
        """PRD §3.2: "The application passes screening only when all three of the
        following hold together: the credit score is at least 620, the
        rent-to-income ratio is at most 0.40, and the debt-to-income ratio is at
        most 0.45." PRD §3.2: "The rent-to-income ratio is the requested monthly
        rent multiplied by twelve, divided by annual income, rounded half-up to
        four decimal places."

        income 6_000_000, rent 250_000 -> rti 0.5000 (> 0.40) so the conjunctive
        gate fails even though credit_score 700 passes on its own.

        Design: Difficulty/combinatorial_formula/screening_three_input_nonlinear_gate
        """
        unit = create_unit()
        app = create_submitted_applicant(
            unit["id"],
            annual_income_cents=6000000,
            credit_score=700,
            requested_rent_cents=250000,
            monthly_debt_cents=50000,
        )
        screened = get_success_data(api.screen_applicant(app["id"], PM))
        assert screened["rent_to_income_ratio"] == pytest.approx(0.5, abs=1e-9)
        assert screened["dti_ratio"] == pytest.approx(0.6, abs=1e-9)
        assert screened["screening_decision"] == "FAIL"
        assert screened["status"] == "SCREENED"

    def test_credit_score_620_passes_619_fails(self, api):
        """PRD §3.2: "an application landing exactly on a boundary — a score of
        exactly 620, a rent-to-income of exactly 0.40, a debt-to-income of exactly
        0.45 — passes that particular check." PRD §3.2: "the credit score is at
        least 620".

        With rti/dti held at 0.20 (income 12_000_000, rent 200_000), credit score
        is the sole discriminator: 620 PASSES, 619 FAILS.

        Design: Difficulty/boundary_precision_check/credit_score_min_inclusive_620_vs_619
        """
        unit = create_unit()
        app_at = create_submitted_applicant(
            unit["id"], credit_score=620, annual_income_cents=12000000,
            requested_rent_cents=200000, monthly_debt_cents=0,
        )
        app_below = create_submitted_applicant(
            unit["id"], credit_score=619, annual_income_cents=12000000,
            requested_rent_cents=200000, monthly_debt_cents=0,
        )
        at = get_success_data(api.screen_applicant(app_at["id"], PM))
        below = get_success_data(api.screen_applicant(app_below["id"], PM))
        assert at["screening_decision"] == "PASS"
        assert below["screening_decision"] == "FAIL"

    def test_credit_score_620_boundary_only_credit_varies(self, api):
        """PRD §3.2: "a score of exactly 620 ... passes that particular check."

        Second test of the boundary instance: a single applicant at exactly the
        minimum credit score, with both ratios comfortably within limits, passes.

        Design: Difficulty/boundary_precision_check/credit_score_min_inclusive_620_vs_619
        """
        unit = create_unit()
        app = create_submitted_applicant(
            unit["id"], credit_score=620, annual_income_cents=12000000,
            requested_rent_cents=200000, monthly_debt_cents=0,
        )
        screened = get_success_data(api.screen_applicant(app["id"], PM))
        assert screened["screening_decision"] == "PASS"

    def test_zero_income_sentinel_autofail(self, api):
        """PRD §3.2: "if annual income is zero, the division is undefined, so both
        ratios are set to the sentinel value 999.9999 and the decision is FAIL
        regardless of the credit score."

        Second test of the gate instance: the zero-income special case forces FAIL
        even with a high credit score.

        Design: Difficulty/combinatorial_formula/screening_three_input_nonlinear_gate
        """
        unit = create_unit()
        app = create_submitted_applicant(
            unit["id"], annual_income_cents=0, credit_score=800,
            requested_rent_cents=200000, monthly_debt_cents=0,
        )
        screened = get_success_data(api.screen_applicant(app["id"], PM))
        assert screened["rent_to_income_ratio"] == pytest.approx(999.9999, abs=1e-4)
        assert screened["dti_ratio"] == pytest.approx(999.9999, abs=1e-4)
        assert screened["screening_decision"] == "FAIL"


class TestLateFeeSweep:
    def test_late_fee_rounds_pct_then_adds_flat(self, api):
        """PRD §3.5: "its amount is the lease's monthly_rent_cents multiplied by
        the lease's late_fee_pct, rounded half-up to whole cents, and then the
        lease's late_fee_flat_cents is added on top of that rounded figure."

        rent 200_000, pct 0.05 -> round(10000.0)=10000, + flat 2500 = 12500. Sweep
        at 2026-06-09 (after the 2026-06-06 cutoff) creates exactly one LATE_FEE
        charge of 12500 and balance becomes 212500.

        Design: Difficulty/combinatorial_formula/late_fee_round_then_add_flat_order
        """
        world = setup_active_lease(
            state_code="TX", market_rent_cents=200000, deposit_cents=200000,
            lease_overrides={
                "monthly_rent_cents": 200000, "late_fee_pct": 0.05,
                "late_fee_flat_cents": 2500, "grace_period_days": 5,
            },
        )
        lease_id = world["lease"]["id"]
        post_rent_charge(lease_id, amount_cents=200000, period_label="2026-06",
                         due_date="2026-06-01")
        updated = assess_late_fees(lease_id, "2026-06-09")
        assert updated["balance_due_cents"] == 212500
        fees = list_late_fee_charges(lease_id)
        assert len(fees) == 1
        assert fees[0]["amount_cents"] == 12500

    def test_late_fee_amount_is_exact_12500(self, api):
        """PRD §3.5: "its amount is the lease's monthly_rent_cents multiplied by
        the lease's late_fee_pct, rounded half-up to whole cents, and then the
        lease's late_fee_flat_cents is added on top of that rounded figure."

        Second test of the rounding-order instance: assert the LATE_FEE charge's
        own amount_cents directly equals 12500.

        Design: Difficulty/combinatorial_formula/late_fee_round_then_add_flat_order
        """
        world = setup_active_lease(
            state_code="TX", market_rent_cents=200000, deposit_cents=200000,
            lease_overrides={
                "monthly_rent_cents": 200000, "late_fee_pct": 0.05,
                "late_fee_flat_cents": 2500, "grace_period_days": 5,
            },
        )
        lease_id = world["lease"]["id"]
        post_rent_charge(lease_id, amount_cents=200000, due_date="2026-06-01")
        assess_late_fees(lease_id, "2026-06-09")
        fees = list_late_fee_charges(lease_id)
        assert len(fees) == 1
        assert fees[0]["amount_cents"] == 12500
        assert fees[0]["charge_type"] == "LATE_FEE"

    def test_no_fee_on_exact_grace_cutoff_day(self, api):
        """PRD §3.5: "the grace period is inclusive, so the cutoff day itself is
        still on time. Only when the sweep date is strictly after that cutoff is a
        fee owed — a sweep landing exactly on the last grace day, where as_of_date
        equals due_date plus grace_period_days, produces nothing."

        due 2026-06-01, grace 5 -> cutoff 2026-06-06; sweeping as_of 2026-06-06
        produces no fee, balance stays 200000.

        Design: Difficulty/boundary_precision_check/late_fee_grace_cutoff_strict_greater
        """
        world = setup_active_lease(
            state_code="TX", market_rent_cents=200000, deposit_cents=200000,
            lease_overrides={
                "monthly_rent_cents": 200000, "late_fee_pct": 0.05,
                "late_fee_flat_cents": 2500, "grace_period_days": 5,
            },
        )
        lease_id = world["lease"]["id"]
        post_rent_charge(lease_id, amount_cents=200000, due_date="2026-06-01")
        updated = assess_late_fees(lease_id, "2026-06-06")
        assert updated["balance_due_cents"] == 200000
        assert list_late_fee_charges(lease_id) == []

    def test_fee_owed_day_after_cutoff(self, api):
        """PRD §3.5: "Only when the sweep date is strictly after that cutoff is a
        fee owed".

        Second test of the strict-cutoff boundary: one day past the cutoff
        (2026-06-07) does owe a fee, so a LATE_FEE charge appears.

        Design: Difficulty/boundary_precision_check/late_fee_grace_cutoff_strict_greater
        """
        world = setup_active_lease(
            state_code="TX", market_rent_cents=200000, deposit_cents=200000,
            lease_overrides={
                "monthly_rent_cents": 200000, "late_fee_pct": 0.05,
                "late_fee_flat_cents": 2500, "grace_period_days": 5,
            },
        )
        lease_id = world["lease"]["id"]
        post_rent_charge(lease_id, amount_cents=200000, due_date="2026-06-01")
        updated = assess_late_fees(lease_id, "2026-06-07")
        assert updated["balance_due_cents"] == 212500
        fees = list_late_fee_charges(lease_id)
        assert len(fees) == 1
        assert fees[0]["amount_cents"] == 12500
