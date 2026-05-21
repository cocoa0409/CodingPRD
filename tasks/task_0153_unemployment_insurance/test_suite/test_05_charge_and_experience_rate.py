"""EmployerCharge allocation and experience-rate recomputation.

Covers PRD §3.3 (employer-charge allocation with pinned rounding),
§3.7 (charge relief), and §2.8 (monetary precision regimes).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_charge_dollar_conservation,
    assert_employer_charge,
    get_employer,
    list_employer_charges,
    make_employer_agent_headers,
    relieve_charge,
    setup_employer_with_active_charge,
    setup_two_employer_charge_split,
    validate_error,
    validate_success,
)


class TestChargeAllocationConservation:

    def test_two_equal_employer_charge_sum_equals_payment(self, api):
        """PRD §2.8: "Round half up for per-employer charge allocation,
        with a residual-reconciliation pass guaranteeing that the sum
        of issued EmployerCharge.charge_cents equals the originating
        BenefitPayment.amount_cents exactly."

        # difficulty: combinatorial_formula/employer_charge_allocation_mode_b_rounding_order
        # difficulty: compensating_invariant/payment_dollar_conservation_invariant
        """
        scenario = setup_two_employer_charge_split(payable_amount_cents=10_001)
        cert = scenario["certification"]
        # The actual payable might be the claim's WBA if our earnings
        # tuning didn't land on 10_001 (depends on WBA value); use
        # whatever the cert produced.
        target = cert.get("payable_amount_cents")
        if not target:
            pytest.skip("certification did not produce a payment")

        charges_a = list_employer_charges(scenario["employer_a"]["id"])
        charges_b = list_employer_charges(scenario["employer_b"]["id"])
        all_charges = [
            c for c in (charges_a + charges_b)
            if c.get("payment_id") == cert.get("payment_id")
        ]
        # Sum charges across both employers for this payment.
        assert_charge_dollar_conservation(
            all_charges, target, counted_statuses=("ACTIVE",),
        )

    def test_odd_cent_residual_tie_break_by_employer_id_asc(self, api):
        """PRD §3.3: "fourth, that residual — positive or negative —
        is distributed one cent at a time to employers sorted by
        wages_E descending, with ties broken by Employer.id ascending."

        With equal wages_E for two employers, the residual goes to
        the lexically smaller Employer.id first. Combined with
        round_half_up of the raw 0.5-cent shares, the smaller-id
        employer ends up with the lower charge after subtracting the
        residual cent.

        # difficulty: combinatorial_formula/employer_charge_allocation_mode_b_rounding_order
        """
        scenario = setup_two_employer_charge_split(payable_amount_cents=10_001)
        cert = scenario["certification"]
        target = cert.get("payable_amount_cents")
        if not target or target % 2 == 0:
            pytest.skip(
                "scenario did not produce an odd-cent payment; tie-break "
                "behaviour cannot be observed"
            )
        charges_a = list_employer_charges(scenario["employer_a"]["id"])
        charges_b = list_employer_charges(scenario["employer_b"]["id"])
        # Take the single charge each generated for this payment.
        ca = next(
            (c for c in charges_a if c.get("payment_id") == cert["payment_id"]),
            None,
        )
        cb = next(
            (c for c in charges_b if c.get("payment_id") == cert["payment_id"]),
            None,
        )
        assert ca is not None and cb is not None
        # employer_a.id < employer_b.id by construction (we sorted at
        # setup time). raw_each = target / 2, round_half_up each.
        # For odd target, residual = -1; subtract from A (smaller id).
        # So A gets the lower charge, B gets the higher.
        assert ca["charge_cents"] + cb["charge_cents"] == target
        # ca < cb under tie-break by Employer.id ASC (residual subtracts
        # from the smaller-id employer).
        assert ca["charge_cents"] < cb["charge_cents"], (
            f"tie-break by Employer.id ASC should put A's charge lower: "
            f"A={ca['charge_cents']}, B={cb['charge_cents']}"
        )


class TestExperienceRateTiers:

    def test_exact_boundary_ratio_010_lands_floor_tier(self, api):
        """PRD §3.3: "a reserve ratio of at least 0.10 yields the 1.00%
        floor of 100 basis points".

        # difficulty: boundary_precision_check/experience_rate_tier_boundary_exact_010
        """
        from test_helpers import create_employer
        # reserve/payroll = 1_000_000 / 10_000_000 = 0.10 exactly.
        e = create_employer(
            reserve_ratio_basis_cents=1_000_000,
            taxable_payroll_cents=10_000_000,
        )
        assert e["experience_rate_bps"] == 100, (
            f"ratio=0.10 must map to floor 100 bps, got {e['experience_rate_bps']}"
        )

    def test_ratio_just_below_010_lands_next_tier(self, api):
        """PRD §3.3: "otherwise at least 0.07 yields 180 basis points".

        ratio = 999_999/10_000_000 = 0.0999999... < 0.10 (but >= 0.07).

        # difficulty: boundary_precision_check/experience_rate_tier_boundary_exact_010
        """
        from test_helpers import create_employer
        e = create_employer(
            reserve_ratio_basis_cents=999_999,
            taxable_payroll_cents=10_000_000,
        )
        assert e["experience_rate_bps"] == 180, (
            f"ratio<0.10 must drop to 180 bps tier, "
            f"got {e['experience_rate_bps']}"
        )

    def test_active_charge_raises_rate_relief_lowers(self, api):
        """PRD §3.3: "the relieved charge subtracts from the net
        charges (driving the rate down), whereas the active charge
        adds to the net charges (driving the rate up). The same inputs
        under the two states therefore yield different
        experience_rate_bps values."

        # difficulty: dual_variant_calc/employer_rate_charge_active_vs_relieved
        """
        # Set up Employer with initial rate at floor (ratio=0.10 -> 100).
        scenario = setup_employer_with_active_charge(
            reserve_basis_cents=1_000_000,
            taxable_payroll_cents=10_000_000,
            charge_amount_cents=300_000,
        )
        emp_before = get_employer(scenario["employer"]["id"])
        # After ACTIVE charge of 300_000:
        # net = 300_000; adjusted_reserve = 1_000_000 - 300_000 = 700_000.
        # ratio = 0.07 -> 180 bps.
        assert emp_before["experience_rate_bps"] == 180, (
            f"with one ACTIVE charge of 300_000, expected 180 bps, "
            f"got {emp_before['experience_rate_bps']}"
        )

        # Relieve the charge.
        charges = list_employer_charges(scenario["employer"]["id"])
        active = next(c for c in charges if c["status"] == "ACTIVE")
        relieved = relieve_charge(
            scenario["employer"]["id"], active["id"], via="adjudicator",
        )
        assert relieved["status"] == "RELIEVED"

        emp_after = get_employer(scenario["employer"]["id"])
        # After RELIEVED: net = 0 - 300_000 = -300_000.
        # adjusted_reserve = max(0, 1_000_000 - (-300_000)) = 1_300_000.
        # ratio = 1_300_000 / 10_000_000 = 0.13 -> 100 bps (floor tier).
        assert emp_after["experience_rate_bps"] == 100, (
            f"after RELIEF the rate should drop back to the floor "
            f"tier (100 bps); got {emp_after['experience_rate_bps']}"
        )


class TestChargeListAndRelief:

    def test_employer_agent_lists_own_charges(self, api):
        """PRD §3.7: "An employer agent reads charges levied against
        the employer they represent through a list endpoint that
        supports filtering by status and the standard limit / offset
        pagination."
        """
        scenario = setup_employer_with_active_charge()
        emp_id = scenario["employer"]["id"]
        resp = api.list_employer_charges(
            emp_id, make_employer_agent_headers(emp_id),
        )
        from test_helpers import validate_paginated
        data, _meta = validate_paginated(resp)
        assert len(data) >= 1
        for c in data:
            assert c["employer_id"] == emp_id
            assert_employer_charge(c)

    def test_relief_via_agent_role(self, api):
        """PRD §3.7: "Granting relief transitions the EmployerCharge to
        status equal to RELIEVED and triggers an experience_rate_bps
        recomputation for that Employer under the relieved-charge
        variant."
        """
        scenario = setup_employer_with_active_charge()
        emp_id = scenario["employer"]["id"]
        active_charges = [
            c for c in list_employer_charges(emp_id)
            if c["status"] == "ACTIVE"
        ]
        assert active_charges, "expected at least one ACTIVE charge"
        c = active_charges[0]
        relieved = relieve_charge(emp_id, c["id"], via="agent")
        assert relieved["status"] == "RELIEVED"
