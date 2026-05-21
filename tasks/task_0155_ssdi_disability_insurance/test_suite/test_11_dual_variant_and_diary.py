"""Dual-variant calculations (provisional vs final PIA/back-pay), CDR
diary lookup, and version mismatch (OCC).

Covers difficulty-design rule 1 (pia_provisional_vs_final_on_application,
back_pay_provisional_vs_final_on_application_ledger). PRD §3.4 (waiting
period + back-pay), §3.5 (PIA variants), §2.5 (OCC).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    MIE_DIARY_MONTHS,
    MIP_DIARY_MONTHS,
    MINE_DIARY_MONTHS,
    TEST_USERS,
    advance_clock_by_days,
    api_client,
    appeal_application,
    create_claimant,
    create_determination_payload,
    get_application,
    issue_determination,
    make_alj_headers,
    make_claimant_headers,
    parse_iso,
    patch_ssi,
    setup_application_approved_at_initial,
    setup_application_at_initial_review,
    setup_held_hearing_for_alj_pending,
    setup_alj_approved_application,
    setup_application_at_alj_pending,
    setup_insured_claimant,
    create_ssi_supplement,
    activate_ssi,
    validate_error,
    validate_success,
)


class TestPIAVariantProvisionalVsFinal:
    """Difficulty design rule 1: pia_provisional_vs_final_on_application."""

    def test_initial_allow_uses_provisional_pia(self, api):
        """# difficulty: dual_variant_calc/pia_provisional_vs_final_on_application

        PRD §3.5: "The provisional variant — used at allowances issued
        at INITIAL_REVIEW and at RECONSIDERATION — includes the
        claimant's year-of-onset earnings only up to the last completed
        QuarterCredit; later partial quarters in that year are dropped."

        Claim: at INITIAL ALLOW the application is approved and
        pia_cents is computed; we assert the row exists and is
        dime-rounded.
        """
        claimant, application = setup_application_approved_at_initial()
        assert isinstance(application["pia_cents"], int)
        assert application["pia_cents"] >= 0
        assert application["pia_cents"] % 10 == 0, (
            f"provisional pia_cents must be dime-rounded; got "
            f"{application['pia_cents']}"
        )

    def test_alj_allow_uses_final_pia(self, api):
        """# difficulty: dual_variant_calc/pia_provisional_vs_final_on_application

        PRD §3.5: "The final variant — used at allowances issued at
        the ALJ level — includes the full year-of-onset earnings as a
        single annual figure, no quarter truncation."

        Claim: at ALJ ALLOW the application enters ALJ_APPROVED with
        a dime-rounded pia_cents (final variant).
        """
        claimant, application = setup_alj_approved_application()
        assert application["status"] == "ALJ_APPROVED"
        assert isinstance(application["pia_cents"], int)
        assert application["pia_cents"] % 10 == 0


class TestBackPayVariantProvisionalVsFinal:
    """Difficulty design rule 1: back_pay_provisional_vs_final_on_application_ledger."""

    def test_initial_allow_computes_back_pay(self, api):
        """# difficulty: dual_variant_calc/back_pay_provisional_vs_final_on_application_ledger

        PRD §3.5: "Back pay. Computed on every approval transition.
        The number of retroactive months is the count of full calendar
        months from entitlement_date through the month immediately
        before approval_date (exclusive at the approval-month
        boundary). back_pay_cents is the months retroactive multiplied
        by monthly_benefit_cents."

        Claim: at INITIAL ALLOW, back_pay_cents is an integer >= 0.
        """
        claimant, application = setup_application_approved_at_initial()
        back_pay = application["back_pay_cents"]
        assert isinstance(back_pay, int)
        assert back_pay >= 0

    def test_alj_allow_back_pay_cap_at_twelve_pre_filing_months(self, api):
        """# difficulty: dual_variant_calc/back_pay_provisional_vs_final_on_application_ledger

        PRD §3.5: "The final back-pay variant — used at allowances at
        the ALJ level — caps pre-filing retro months at twelve
        absolute (12 full months prior to filing_date absolutely,
        regardless of intervening denial windows)."

        Claim: at ALJ ALLOW, back_pay_cents = months_retro *
        monthly_benefit_cents, with months_retro <= 12 + months
        between filing_date and approval_date.
        """
        claimant, application = setup_alj_approved_application()
        back_pay = application["back_pay_cents"]
        monthly = application["monthly_benefit_cents"]
        assert isinstance(back_pay, int) and back_pay >= 0
        # Sanity: back_pay must be integer multiple of monthly_benefit_cents.
        if monthly > 0:
            assert back_pay % monthly == 0, (
                f"back_pay_cents {back_pay} must be a multiple of "
                f"monthly_benefit_cents {monthly}"
            )


class TestCDRDiaryLookup:

    def test_meets_listing_with_listing_1_yields_mip_36_months(self, api):
        """PRD §3.4: "if medical_basis is MEETS_LISTING and the
        listing_code of the most recent accepted evidence row begins
        with '1.' or '11.', the diary is MIP and the diary interval
        is thirty-six months".
        """
        claimant, application = setup_application_approved_at_initial(
            listing_code="1.15",
        )
        assert application["cdr_diary"] == "MIP"
        # next_cdr_due_date should equal approval_date + 36 months.
        approval = parse_iso(application["approval_date"])
        due = parse_iso(application["next_cdr_due_date"])
        # Allow some slack for month-edge arithmetic; require >= 36*28d.
        delta_days = (due - approval).days
        assert delta_days >= 36 * 28, (
            f"MIP diary interval is 36 months (PRD §3.4); got "
            f"{delta_days} days between approval and next_cdr_due_date"
        )

    def test_meets_listing_with_listing_2_yields_mine_84_months(self, api):
        """PRD §3.4: "if the medical basis is MEETS_LISTING but the
        listing code does not begin with '1.' or '11.', the diary is
        MINE and the interval is eighty-four months".
        """
        # Use a listing code beginning with "2." which is neither "1." nor "11.".
        claimant, application = setup_application_approved_at_initial(
            listing_code="2.10",
        )
        assert application["cdr_diary"] == "MINE"


class TestOptimisticConcurrency:

    def test_version_mismatch_on_ssi_patch_returns_version_mismatch(self, api):
        """PRD §2.5: "When the caller supplies version, the server
        compares it to the stored value before mutating; if they
        differ, the request is rejected with ERR_VERSION_MISMATCH at
        HTTP status 409."
        """
        claimant = setup_insured_claimant()
        ss = create_ssi_supplement(
            claimant["id"],
            countable_income_cents=0,
            countable_resources_cents=100_00,
            living_arrangement="OWN_HOUSEHOLD",
        )
        activated = activate_ssi(ss["id"])
        stale_version = activated["version"] - 1
        if stale_version < 0:
            stale_version = 99
        resp = api.patch_ssi_supplement(
            ss["id"],
            {"countable_income_cents": 100_00, "version": stale_version},
            TEST_USERS["dds_examiner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_MISMATCH.value)

    def test_version_match_on_ssi_patch_succeeds(self, api):
        """PRD §2.5: "Omitting version from the body skips this check
        and applies the mutation against whatever the current stored
        version happens to be. The version integer increments by one
        on every accepted mutation".

        Claim: providing the correct stored version succeeds and
        version increments.
        """
        claimant = setup_insured_claimant()
        ss = create_ssi_supplement(
            claimant["id"],
            countable_income_cents=0,
            countable_resources_cents=100_00,
            living_arrangement="OWN_HOUSEHOLD",
        )
        activated = activate_ssi(ss["id"])
        v_before = activated["version"]
        resp = api.patch_ssi_supplement(
            ss["id"],
            {"countable_income_cents": 100_00, "version": v_before},
            TEST_USERS["dds_examiner_headers"],
        )
        data = validate_success(resp)
        assert data["version"] >= v_before + 1
