"""State-tax-benefit credit at contribution settlement (PRD §3.3).

This file targets the IN_STATE_ONLY vs PARITY behavior and the
cap-room arithmetic. It also satisfies the difficulty-design
instance `state_tax_credit_in_state_vs_cross_state`.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    create_beneficiary,
    create_donor,
    create_pending_contribution,
    create_state_rule,
    ensure_state_rule,
    get_success_data,
    make_donor_headers,
    open_account,
    settle_contribution,
    settle_lump_sum,
    setup_donor_beneficiary_account,
    validate_success,
)


class TestStateTaxBenefitCredit:
    """PRD §3.3 narrative on `state-tax-benefit credit`. Two readers
    arrive at the same outcome because PRD §3.3 spells out the exact
    formula step-by-step.
    """

    def test_in_state_match_full_credit(self, api):
        """PRD §3.3: "when parity is PARITY, or when parity is
        IN_STATE_ONLY and the account's state_plan_code matches the
        donor's state_of_residence — the system computes the remaining
        deduction room for the year by subtracting the donor's existing
        ytd_state_deduction_used_cents from the rule's
        deduction_cap_cents, taking the greater of that difference and
        zero. The credit awarded equals the smaller of the
        contribution's amount_cents and that remaining room. The
        donor's ytd_state_deduction_used_cents is incremented by the
        credit awarded."

        Claim: IN_STATE_ONLY rule + donor.state_of_residence ==
        account.state_plan_code → credit = min(amount, cap_room). With
        amount=200_000 and cap_room=500_000, the credit is 200_000.

        # difficulty: dual_variant_calc/state_tax_credit_in_state_vs_cross_state
        """
        ensure_state_rule(
            "NY", parity="IN_STATE_ONLY",
            deduction_cap_cents=500_000,
            lifetime_aggregate_cap_cents=10_000_000,
        )
        donor, _ben, account_ny = setup_donor_beneficiary_account(
            donor_state="NY", plan_state="NY",
            parity="IN_STATE_ONLY",
            deduction_cap_cents=500_000,
            lifetime_aggregate_cap_cents=10_000_000,
        )
        settle_lump_sum(
            account=account_ny, donor=donor, amount_cents=200_000,
        )
        refreshed = get_success_data(
            api.get_donor(donor["id"], make_donor_headers(donor["id"])),
        )
        assert refreshed["ytd_state_deduction_used_cents"] == 200_000

    def test_cross_state_in_state_only_no_credit(self, api):
        """PRD §3.3: "The system first resolves the donor's
        residence-state rule. If that rule's parity is IN_STATE_ONLY
        and the account's state_plan_code is different from the
        donor's state_of_residence, the credit awarded for this
        contribution is zero and the contribution still settles —
        there is no rejection, just no deduction."

        Claim: IN_STATE_ONLY donor in NY contributes to a UT plan →
        credit_cents=0; the contribution still settles, donor YTD
        deduction stays 0.

        # difficulty: dual_variant_calc/state_tax_credit_in_state_vs_cross_state
        """
        ensure_state_rule(
            "NY", parity="IN_STATE_ONLY",
            deduction_cap_cents=500_000,
            lifetime_aggregate_cap_cents=10_000_000,
        )
        ensure_state_rule(
            "UT", parity="IN_STATE_ONLY",
            deduction_cap_cents=300_000,
            lifetime_aggregate_cap_cents=10_000_000,
        )
        donor = create_donor(state_of_residence="NY")
        beneficiary = create_beneficiary(relationship_family_code="CHILD")
        account_ut = open_account(
            donor=donor, beneficiary=beneficiary,
            state_plan_code="UT", ensure_plan_rule=False,
        )
        # Settle a contribution on the UT plan.
        contribution = create_pending_contribution(
            account=account_ut, donor=donor, amount_cents=200_000,
        )
        settle_contribution(contribution["id"])
        # PRD §3.3: contribution still settles, but credit is 0.
        refreshed = get_success_data(
            api.get_donor(donor["id"], make_donor_headers(donor["id"])),
        )
        # ytd_contribution_total_cents reflects the deposit.
        assert refreshed["ytd_contribution_total_cents"] == 200_000
        # ytd_state_deduction_used_cents stays at zero (cross-state under
        # IN_STATE_ONLY yields zero credit).
        assert refreshed["ytd_state_deduction_used_cents"] == 0

    def test_parity_credit_applied_for_any_state(self, api):
        """PRD §3.3: "when parity is PARITY ... the system computes the
        remaining deduction room ... The credit awarded equals the
        smaller of the contribution's amount_cents and that remaining
        room."

        Claim: PARITY rule on donor's home state allows credit even
        when contributing to a different state's plan.
        """
        ensure_state_rule(
            "PA", parity="PARITY",
            deduction_cap_cents=500_000,
            lifetime_aggregate_cap_cents=10_000_000,
        )
        ensure_state_rule(
            "VT", parity="PARITY",
            deduction_cap_cents=500_000,
            lifetime_aggregate_cap_cents=10_000_000,
        )
        donor = create_donor(state_of_residence="PA")
        beneficiary = create_beneficiary(relationship_family_code="CHILD")
        account_vt = open_account(
            donor=donor, beneficiary=beneficiary,
            state_plan_code="VT", ensure_plan_rule=False,
        )
        contribution = create_pending_contribution(
            account=account_vt, donor=donor, amount_cents=150_000,
        )
        settle_contribution(contribution["id"])
        refreshed = get_success_data(
            api.get_donor(donor["id"], make_donor_headers(donor["id"])),
        )
        # PARITY: credit = min(150_000, 500_000) = 150_000.
        assert refreshed["ytd_state_deduction_used_cents"] == 150_000

    def test_credit_capped_at_remaining_room(self, api):
        """PRD §3.3: "The credit awarded equals the smaller of the
        contribution's amount_cents and that remaining room."

        Claim: when amount_cents exceeds the remaining cap room, the
        credit equals the remaining room only (not amount_cents); donor
        YTD deduction lands EXACTLY at deduction_cap_cents.
        """
        ensure_state_rule(
            "MA", parity="PARITY",
            deduction_cap_cents=100_000,
            lifetime_aggregate_cap_cents=10_000_000,
        )
        donor, _ben, account = setup_donor_beneficiary_account(
            donor_state="MA", plan_state="MA",
            parity="PARITY",
            deduction_cap_cents=100_000,
            lifetime_aggregate_cap_cents=10_000_000,
        )
        # Settle a 70k contribution → credit = 70k (room=100k).
        settle_lump_sum(account=account, donor=donor, amount_cents=70_000)
        refreshed_after_first = get_success_data(
            api.get_donor(donor["id"], make_donor_headers(donor["id"])),
        )
        assert refreshed_after_first[
            "ytd_state_deduction_used_cents"
        ] == 70_000
        # Now room = 30k. Settle an 80k contribution → credit = 30k.
        settle_lump_sum(account=account, donor=donor, amount_cents=80_000)
        refreshed_after_second = get_success_data(
            api.get_donor(donor["id"], make_donor_headers(donor["id"])),
        )
        # PRD §3.3: capped at deduction_cap_cents.
        assert refreshed_after_second[
            "ytd_state_deduction_used_cents"
        ] == 100_000

    def test_credit_uses_donor_residence_not_plan_state(self, api):
        """PRD §3.3: "The state-tax-benefit credit at settlement is
        computed against the state rule of the donor's
        state_of_residence (not the account's state_plan_code)."

        Claim: when donor lives in PARITY-state-A and the account is in
        IN_STATE_ONLY-state-B, the residency-state rule (PARITY)
        governs and credit is awarded — proving the residency rule (not
        plan rule) is the one consulted.
        """
        ensure_state_rule(
            "TX", parity="PARITY",
            deduction_cap_cents=500_000,
            lifetime_aggregate_cap_cents=10_000_000,
        )
        ensure_state_rule(
            "FL", parity="IN_STATE_ONLY",
            deduction_cap_cents=10_000,
            lifetime_aggregate_cap_cents=10_000_000,
        )
        donor = create_donor(state_of_residence="TX")
        beneficiary = create_beneficiary(relationship_family_code="CHILD")
        # Open account in FL even though donor lives in TX.
        account = open_account(
            donor=donor, beneficiary=beneficiary,
            state_plan_code="FL", ensure_plan_rule=False,
        )
        settle_lump_sum(account=account, donor=donor, amount_cents=200_000)
        refreshed = get_success_data(
            api.get_donor(donor["id"], make_donor_headers(donor["id"])),
        )
        # The TX rule (PARITY, 500k cap) governs → credit = 200k. If
        # the FL rule (IN_STATE_ONLY, 10k cap) had been used the credit
        # would be 0 (cross-state under IN_STATE_ONLY) or capped at 10k.
        assert refreshed["ytd_state_deduction_used_cents"] == 200_000
