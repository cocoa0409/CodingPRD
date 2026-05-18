"""Clock-driven cascades: delinquency, default, charge-off, and
installment state machine.

PRD §3.6, §2.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    INSTALLMENT_GRACE_DAYS,
    INSTALLMENT_PERIOD_DAYS,
    advance_clock,
    find_disclosure,
    get_investment,
    get_investor,
    get_loan,
    list_installments,
    setup_loan_charged_off,
    setup_loan_charged_off_three_investors,
    setup_loan_in_default,
    setup_loan_in_delinquent,
    setup_originated_loan,
)


def _installments(platform_id, loan_id) -> list:
    body = list_installments(platform_id, loan_id)
    rows = body if isinstance(body, list) else body.get("data", body)
    if isinstance(rows, dict) and "data" in rows:
        rows = rows["data"]
    return rows


# ===========================================================================
# Delinquency — PRD §3.6
# ===========================================================================
class TestDelinquencyTransition:

    def test_first_late_installment_drives_loan_to_delinquent(self, api):
        """PRD §3.6: "The first time consecutive_missed_installments
        moves from zero to a positive integer, the loan transitions
        ACTIVE -> DELINQUENT and emits a draft Disclosure with kind
        DELINQUENCY_NOTICE."

        Claim: after the first installment becomes LATE,
        loan.status == 'DELINQUENT' and
        loan.consecutive_missed_installments >= 1.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_loan_in_delinquent(principal_cents=100_000)
        assert loan["status"] == "DELINQUENT"
        assert loan["consecutive_missed_installments"] >= 1

    def test_first_delinquency_emits_delinquency_notice_disclosure(
        self, api,
    ):
        """PRD §3.6: "emits a draft Disclosure with kind
        DELINQUENCY_NOTICE."

        Claim: a DRAFT DELINQUENCY_NOTICE exists for the loan.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_loan_in_delinquent(principal_cents=100_000)
        d = find_disclosure(
            platform["id"], subject_type="LOAN",
            subject_id=loan["id"], kind="DELINQUENCY_NOTICE",
            published=False,
        )
        assert d is not None


# ===========================================================================
# Default — PRD §3.6
# ===========================================================================
class TestDefaultTransition:

    def test_three_consecutive_misses_drive_loan_to_default(self, api):
        """PRD §3.6: "When consecutive_missed_installments reaches
        three or more, the loan transitions DELINQUENT -> DEFAULT
        during the same sweep and emits a draft Disclosure with kind
        DEFAULT_NOTICE."

        Claim: after 3+ consecutive misses, loan.status == 'DEFAULT'.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_loan_in_default(principal_cents=100_000)
        assert loan["status"] == "DEFAULT"
        assert loan["consecutive_missed_installments"] >= 3

    def test_default_emits_default_notice_disclosure(self, api):
        """PRD §3.6: "emits a draft Disclosure with kind DEFAULT_NOTICE."

        Claim: a DRAFT DEFAULT_NOTICE exists.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_loan_in_default(principal_cents=100_000)
        d = find_disclosure(
            platform["id"], subject_type="LOAN",
            subject_id=loan["id"], kind="DEFAULT_NOTICE",
            published=False,
        )
        assert d is not None


# ===========================================================================
# Charge-off — PRD §3.6
# ===========================================================================
class TestChargeOffTransition:

    def test_five_consecutive_misses_drive_loan_to_charged_off(self, api):
        """PRD §3.6: "When the counter reaches five or more, the loan
        transitions DEFAULT -> CHARGED_OFF".

        Claim: after 5+ consecutive misses, loan.status == 'CHARGED_OFF'.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_loan_charged_off(principal_cents=100_000)
        assert loan["status"] == "CHARGED_OFF"
        assert loan["consecutive_missed_installments"] >= 5

    def test_charge_off_sets_principal_outstanding_to_zero(self, api):
        """PRD §3.6: "principal_outstanding_cents is set to zero."

        Claim: after charge-off, principal_outstanding_cents == 0.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_loan_charged_off(principal_cents=100_000)
        assert loan["principal_outstanding_cents"] == 0

    def test_charge_off_books_loss_amount(self, api):
        """PRD §3.6: "the loan's charged_off_loss_cents is set to the
        sum of principal_outstanding_cents and accrued_late_fees_cents
        at the moment of charge-off".

        Claim: after charge-off (no prior payments), charged_off_loss
        is strictly positive and at least the principal_cents (no
        cures reduced it).
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_loan_charged_off(principal_cents=100_000)
        assert loan["charged_off_loss_cents"] >= 100_000

    def test_charge_off_emits_charge_off_notice_disclosure(self, api):
        """PRD §3.6: "A draft Disclosure with kind CHARGE_OFF_NOTICE is
        emitted."

        Claim: a DRAFT CHARGE_OFF_NOTICE exists.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_loan_charged_off(principal_cents=100_000)
        d = find_disclosure(
            platform["id"], subject_type="LOAN",
            subject_id=loan["id"], kind="CHARGE_OFF_NOTICE",
            published=False,
        )
        assert d is not None

    def test_charge_off_waives_remaining_installments(self, api):
        """PRD §3.6: "Every remaining installment, regardless of its
        current state (SCHEDULED, DUE, or LATE), transitions to
        WAIVED".

        Claim: after charge-off, every non-PAID installment has status
        == 'WAIVED'.
        """
        (platform, officer, b, investor, listing, investment,
         loan) = setup_loan_charged_off(principal_cents=100_000)
        rows = _installments(platform["id"], loan["id"])
        for it in rows:
            assert it["status"] in {"WAIVED", "PAID"}, (
                f"installment {it['sequence_number']} should be "
                f"WAIVED or PAID after charge-off; got {it['status']}"
            )

    def test_charge_off_marks_converted_investments_as_lost(self, api):
        """PRD §3.6: "Every CONVERTED Investment on the loan
        transitions to LOST."

        Claim: each CONVERTED investment becomes LOST after charge-off.
        """
        (platform, officer, b, investors, investments, listing,
         loan) = setup_loan_charged_off_three_investors(
            principal_cents=100_000,
            shares=(30_000, 30_000, 40_000),
        )
        for inv in investments:
            refreshed = get_investment(platform["id"], inv["id"])
            assert refreshed["status"] == "LOST", (
                f"investment {inv['id']} should be LOST after "
                f"charge-off; got {refreshed['status']}"
            )

    def test_charge_off_loss_sums_to_total_loss(self, api):
        """PRD §3.6: "the total distributed equals total_loss exactly."

        Claim: the per-investor deltas in outstanding_principal_cents
        sum to loan.charged_off_loss_cents.

        Setup: 3 investors with shares 30/30/40 cents-thousand.
        Pre-origination outstanding_principal each was the pledged
        amount. After charge-off, each investor's outstanding
        decremented by their pro-rata share of the loss.
        """
        (platform, officer, b, investors, investments, listing,
         loan) = setup_loan_charged_off_three_investors(
            principal_cents=100_000,
            shares=(30_000, 30_000, 40_000),
        )
        total_loss = loan["charged_off_loss_cents"]
        # After charge-off, each investor's outstanding_principal_cents
        # equals (original pledge - actual_share_of_loss).
        # Delta = original_pledge - current_outstanding.
        original_pledges = {
            inv["id"]: pledge
            for inv, pledge in zip(investors, (30_000, 30_000, 40_000))
        }
        deltas = []
        for inv in investors:
            refreshed = get_investor(platform["id"], inv["id"])
            delta = (
                original_pledges[inv["id"]]
                - refreshed["outstanding_principal_cents"]
            )
            deltas.append(delta)
        assert sum(deltas) == total_loss, (
            f"sum of per-investor loss deltas ({sum(deltas)}) must "
            f"equal loan.charged_off_loss_cents ({total_loss})"
        )
