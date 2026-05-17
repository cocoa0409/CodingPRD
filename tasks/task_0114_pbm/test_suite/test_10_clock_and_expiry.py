"""Simulated clock side effects: PA EXPIRED, benefit-year rollover.

PRD §2.11.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    PA_EFFECTIVE_WINDOW_SECONDS,
    SECONDS_PER_DAY,
    advance_clock,
    create_member,
    create_plan,
    re_get_member,
    re_get_prior_authorization,
    setup_approved_pa,
    setup_paid_claim,
    setup_reference_data,
    validate_error,
    validate_success,
)


class TestClockExpiry:
    """PRD §2.11: auto-transitions on each clock advance."""

    def test_pa_auto_expires_at_effective_end(self, api):
        """PRD §2.11: "any APPROVED prior authorization whose
        effective_end is at or earlier than the new clock time auto-
        transitions to EXPIRED".

        Claim: clock at exactly effective_end -> PA -> EXPIRED.
        """
        _, drug, _, member = setup_reference_data()
        pa = setup_approved_pa(
            member_id=member["id"], drug_id=drug["id"],
        )
        advance_clock(PA_EFFECTIVE_WINDOW_SECONDS)
        refreshed = re_get_prior_authorization(pa["id"])
        assert refreshed["status"] == "EXPIRED"

    def test_pa_before_effective_end_still_approved(self, api):
        """PRD §2.11: the auto-expiry trigger is "at or earlier than
        the new clock time". One second BEFORE effective_end the PA
        is still APPROVED.

        Claim: clock at effective_end-1 -> PA still APPROVED.
        """
        _, drug, _, member = setup_reference_data()
        pa = setup_approved_pa(
            member_id=member["id"], drug_id=drug["id"],
        )
        advance_clock(PA_EFFECTIVE_WINDOW_SECONDS - 1)
        refreshed = re_get_prior_authorization(pa["id"])
        assert refreshed["status"] == "APPROVED"


class TestBenefitYearRollover:
    """PRD §2.11: "any Member whose benefit_year_start plus one year
    is at or earlier than the new clock time has both
    ytd_deductible_paid_cents and ytd_oop_paid_cents reset to zero
    and benefit_year_start advanced by one year.\""""

    def test_benefit_year_rollover_resets_ytd(self, api):
        """PRD §2.11: "any Member whose benefit_year_start plus one
        year is at or earlier than the new clock time has both
        ytd_deductible_paid_cents and ytd_oop_paid_cents reset to
        zero".

        Setup: member with ytd_*>0 from a PAID claim. Advance one
        year (365 days). Expect ytd_deductible and ytd_oop both
        reset to 0.
        """
        _, drug, _, member = setup_reference_data()
        setup_paid_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=1, quantity=10,
        )
        m_before = re_get_member(member["id"])
        # Sanity: some YTD movement.
        assert (m_before["ytd_deductible_paid_cents"]
                + m_before["ytd_oop_paid_cents"]) > 0
        # Advance exactly 365 days.
        advance_clock(365 * SECONDS_PER_DAY)
        m_after = re_get_member(member["id"])
        assert m_after["ytd_deductible_paid_cents"] == 0
        assert m_after["ytd_oop_paid_cents"] == 0
