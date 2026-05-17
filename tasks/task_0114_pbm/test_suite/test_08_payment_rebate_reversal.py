"""Pay, rebate accrual, reverse, clawback ledger, clawback window.

PRD §3.6 / §3.7 / §3.9 / §2.8 rung 14.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    DEFAULT_CLAWBACK_WINDOW_DAYS,
    SECONDS_PER_DAY,
    advance_clock,
    assert_ledger_entry,
    assert_ledger_zero_sum_for_claim,
    create_copay_card,
    create_drug,
    create_formulary_entry,
    create_member,
    create_plan,
    create_rebate_agreement,
    list_ledger_for_claim,
    occ_payload,
    pay_claim,
    re_get_claim,
    re_get_copay_card,
    re_get_member,
    setup_adjudicated_claim,
    setup_paid_claim,
    setup_reference_data,
    setup_reversed_claim,
    submit_claim,
    validate_error,
    validate_success,
)


# ===========================================================================
# Pay
# ===========================================================================
class TestPayClaim:

    def test_pay_transitions_status_and_payment_status(self, api):
        """PRD §3.6: "After adjudication, a ClaimsAdjudicator moves
        the claim from ADJUDICATED to PAID. The pay transition
        requires the claim to actually be in ADJUDICATED; on success,
        the claim's payment_status parallel-axis field flips from
        UNPAID to PAID."

        Claim: pay transitions status PAID and payment_status PAID.
        """
        _, drug, _, member = setup_reference_data()
        paid = setup_paid_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        assert paid["status"] == "PAID"
        assert paid["payment_status"] == "PAID"


# ===========================================================================
# Rebate accrual on PAY.
# ===========================================================================
class TestRebateAccrual:

    def test_pay_posts_rebate_accrued_ledger_entry(self, api):
        """PRD §3.6: "If an active agreement does exist, the system
        posts a REBATE_ACCRUED LedgerEntry for the claim. The accrued
        amount is the claim's adjudicated_plan_paid_cents multiplied
        by the agreement's rebate_rate, rounded half-up to the
        nearest whole cent, and stored as a positive integer on
        LedgerEntry.amount_cents."

        Setup: plan(ded=0, oop_max=200000, coins=0.20, tier 1
        copay=1000). Drug unit=5000. MAIL_ORDER_90, q=10.
          raw=50000, allowed=round_half_up(50000*0.90)=45000.
          ded=0, post_ded=45000, member_share=min(1000,45000)=1000
            (tier 1).
          member_pre_card=1000. plan_paid=45000-1000=44000.
        Rebate rate=0.15 -> accrued=round_half_up(44000*0.15)=6600.
        """
        plan = create_plan(deductible_cents=0, oop_max_cents=200_000,
                           coinsurance_rate=0.20,
                           mail_order_discount_rate=0.90)
        drug = create_drug(unit_allowed_cents=5_000)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=1, copay_cents=1000)
        member = create_member(plan_id=plan["id"])
        create_rebate_agreement(drug_id=drug["id"], rebate_rate=0.15)
        paid = setup_paid_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="MAIL_ORDER_90", days_supply=90, quantity=10,
        )
        # plan_paid sanity
        assert paid["adjudicated_plan_paid_cents"] == 44_000
        entries = list_ledger_for_claim(paid["id"])
        accruals = [e for e in entries
                    if e["entry_type"] == "REBATE_ACCRUED"]
        assert len(accruals) == 1, (
            f"expected exactly 1 REBATE_ACCRUED entry, got "
            f"{len(accruals)}"
        )
        accrual = accruals[0]
        assert_ledger_entry(accrual)
        assert accrual["amount_cents"] == 6_600
        assert accrual["claim_id"] == paid["id"]

    def test_pay_without_active_agreement_posts_no_entry(self, api):
        """PRD §3.6: "If no active agreement exists for the drug,
        payment produces no ledger entry."

        Claim: no agreement -> ledger entries list is empty for the
        claim.
        """
        _, drug, _, member = setup_reference_data()
        # No rebate agreement created.
        paid = setup_paid_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        entries = list_ledger_for_claim(paid["id"])
        assert entries == [], (
            f"expected zero ledger entries with no agreement, got "
            f"{entries}"
        )


# ===========================================================================
# Reverse cascade.
# ===========================================================================
class TestReverseCascade:

    def test_reverse_flips_status_and_payment_status(self, api):
        """PRD §3.7: "The claim's status transitions to REVERSED and
        its payment_status flips from PAID to REFUNDED."

        Claim: after reverse, status=REVERSED and payment_status=
        REFUNDED.
        """
        _, drug, _, member = setup_reference_data()
        rev = setup_reversed_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        assert rev["status"] == "REVERSED"
        assert rev["payment_status"] == "REFUNDED"

    def test_reverse_refunds_member_ytd(self, api):
        """PRD §3.7: "The member's ytd_deductible_paid_cents is
        decremented by the deductible portion that was originally
        applied to this claim, and the member's ytd_oop_paid_cents is
        decremented by the adjudicated_member_cost_cents that was
        originally written at adjudicate."

        Note (PRD-only readers): the verbatim PRD sentence says
        ytd_oop is decremented by ``adjudicated_member_cost_cents``.
        We pick a scenario WITHOUT a copay card so that
        adjudicated_member_cost_cents == member_pre_card; both the
        adjudicate-time §3.5 rule (ytd_oop += member_pre_card) and
        the reverse-time §3.7 rule (ytd_oop -= adjudicated_member_cost)
        yield ytd_oop returning to its pre-claim value. This avoids
        depending on a §3.5-vs-§3.7 asymmetry the PRD does not
        explicitly resolve.

        Setup: plan(ded=50000, oop_max=200000, coins=0.20, tier 3).
        Drug unit=10000, q=30 -> allowed=300000. ded_portion=50000.
        post_ded=250000, member_share=50000, member_pre_card=100000.
        adjudicated_member_cost_cents=100000 (no card).
        Before adjudicate: ytd_ded=0, ytd_oop=0.
        After adjudicate: ytd_ded=50000, ytd_oop=100000.
        After reverse: ytd_ded=0, ytd_oop=0.
        """
        plan = create_plan(deductible_cents=50_000,
                           oop_max_cents=200_000,
                           coinsurance_rate=0.20)
        drug = create_drug(unit_allowed_cents=10_000)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        paid = setup_paid_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=30,
        )
        # Member state post-adjudicate
        m_after_adj = re_get_member(member["id"])
        assert m_after_adj["ytd_deductible_paid_cents"] == 50_000
        assert m_after_adj["ytd_oop_paid_cents"] == 100_000
        # Reverse — use the helper for clean OCC threading.
        from test_helpers import reverse_claim
        reverse_claim(paid)
        m_after_rev = re_get_member(member["id"])
        assert m_after_rev["ytd_deductible_paid_cents"] == 0
        assert m_after_rev["ytd_oop_paid_cents"] == 0

    def test_reverse_posts_compensating_clawback_ledger_entry(self, api):
        """PRD §3.7: "When a REBATE_ACCRUED ledger entry exists for
        the claim, a compensating REBATE_CLAWBACK LedgerEntry is
        appended whose amount_cents is the negation of the original
        accrual; the invariant after this second posting is that the
        sum of every ledger entry's amount_cents for the same claim_id
        is exactly zero."

        Setup mirrors the accrual test: rebate rate=0.15, plan_paid=
        44000 -> accrual=+6600. Reverse within 90-day window
        -> clawback=-6600. Sum == 0.
        """
        plan = create_plan(deductible_cents=0, oop_max_cents=200_000,
                           coinsurance_rate=0.20,
                           mail_order_discount_rate=0.90)
        drug = create_drug(unit_allowed_cents=5_000)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=1, copay_cents=1000)
        member = create_member(plan_id=plan["id"])
        create_rebate_agreement(drug_id=drug["id"], rebate_rate=0.15,
                                clawback_window_days=90)
        rev = setup_reversed_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="MAIL_ORDER_90", days_supply=90, quantity=10,
        )
        entries = list_ledger_for_claim(rev["id"])
        accruals = [e for e in entries
                    if e["entry_type"] == "REBATE_ACCRUED"]
        clawbacks = [e for e in entries
                     if e["entry_type"] == "REBATE_CLAWBACK"]
        assert len(accruals) == 1
        assert len(clawbacks) == 1
        assert accruals[0]["amount_cents"] == 6_600
        assert clawbacks[0]["amount_cents"] == -6_600
        assert_ledger_zero_sum_for_claim(entries)


# ===========================================================================
# Clawback window — rung 14.
# ===========================================================================
class TestClawbackWindow:

    def test_reverse_after_window_rejected(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §3.7: "When an accrual ledger entry exists for the
        claim, the reverse is additionally gated on the clawback
        window: the current clock time must be strictly less than the
        accrued entry's posted_at plus the agreement's
        clawback_window_days expressed as days. A reverse attempted
        at or after that deadline is rejected with
        ERR_CLAWBACK_WINDOW_EXPIRED."
        PRD §2.8 rung 14: "Clawback window — for claim reverse, when
        an accrual ledger entry exists for the claim, the current
        clock time must lie strictly before the accrual's posted_at
        plus the agreement's clawback_window_days; otherwise
        ERR_CLAWBACK_WINDOW_EXPIRED (422)."

        Setup: agreement clawback_window_days=90; pay claim; advance
        90 days. Reverse -> ERR_CLAWBACK_WINDOW_EXPIRED.
        """
        plan = create_plan(deductible_cents=0, oop_max_cents=200_000,
                           coinsurance_rate=0.20)
        drug = create_drug(unit_allowed_cents=1_000)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=1, copay_cents=100)
        member = create_member(plan_id=plan["id"])
        create_rebate_agreement(drug_id=drug["id"], rebate_rate=0.10,
                                clawback_window_days=90)
        paid = setup_paid_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=1, quantity=1,
        )
        # Advance exactly 90 days; the strict-less-than check now
        # fails ("at or after").
        advance_clock(90 * SECONDS_PER_DAY)
        res = api.reverse_claim(
            paid["id"], occ_payload(version=paid["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_CLAWBACK_WINDOW_EXPIRED")

    def test_reverse_without_accrual_not_gated_by_window(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §3.7: "When no accrual exists, the time gate does not
        apply."

        Setup: no rebate agreement; pay claim; advance 1000 days;
        reverse -> succeeds.
        """
        _, drug, _, member = setup_reference_data()
        paid = setup_paid_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=1, quantity=1,
        )
        advance_clock(1000 * SECONDS_PER_DAY)
        res = api.reverse_claim(
            paid["id"], occ_payload(version=paid["version"]),
            claims_adjudicator_headers,
        )
        rev = validate_success(res, 200)
        assert rev["status"] == "REVERSED"
        assert rev["payment_status"] == "REFUNDED"
