"""Cross-workflow locking and cascade-across-entities behaviors.

PRD §3.4 (IA + OIC overlap), §3.8 (OIC accept cascades to IA).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    create_and_activate_agreement,
    create_draft_oic,
    create_taxpayer,
    create_tax_liability,
    decide_offer_in_compromise_payload,
    get_installment_agreement,
    get_tax_liability,
    make_oic_officer_headers,
    make_taxpayer_headers,
    pay_oic_deposit,
    setup_oic_under_review,
    submit_oic,
    take_up_oic,
    validate_error,
    validate_success,
)


class TestLiabilityLockedDuringUnderReview:

    def test_take_up_locks_liability_against_concurrent_workflows(self, api):
        """PRD §3.4: "fails with ERR_LIABILITY_LOCKED if any covered
        liability is simultaneously held by an UNDER_REVIEW Offer in
        Compromise."

        Claim: an OIC in UNDER_REVIEW prevents activation of a new IA
        covering the same liability.

        # difficulty: resource_temporal_overlap/ia_oic_simultaneous_lock_overlap
        """
        from test_helpers import (
            TEST_USERS,
            create_installment_agreement_payload,
        )
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=1_000_000,
        )
        # Push the OIC to UNDER_REVIEW.
        setup_oic_under_review(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_000_000,
            schedule_months=5,
            deposit_cents=200_000,
            take_up_officer_id="oic-locker-A",
        )
        # Try to create + activate an IA covering the locked liability.
        ia_payload = create_installment_agreement_payload(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=200_000,
            payment_method="CHECK",
        )
        draft_resp = api.create_installment_agreement(
            ia_payload, make_taxpayer_headers(taxpayer["id"]),
        )
        # Draft may succeed; activation must surface the lock.
        if draft_resp.status_code >= 400:
            validate_error(draft_resp, ApiErrorId.ERR_LIABILITY_LOCKED.value)
            return
        draft = draft_resp.json()["data"]
        activate_resp = api.activate_installment_agreement(
            draft["id"], TEST_USERS["irs_officer_headers"],
        )
        validate_error(
            activate_resp, ApiErrorId.ERR_LIABILITY_LOCKED.value,
        )


class TestOICAcceptCascade:

    def test_oic_accept_terminates_covering_ia_and_reverts_other_liabilities(
        self, api,
    ):
        """PRD §3.8: "any ACTIVE InstallmentAgreement covering any of
        the offer's liabilities cascades into TERMINATED, with the
        agreement's covered liabilities that appear in the OIC
        transitioning to IN_COMPROMISE and the covered liabilities
        that do not appear in the OIC reverting to OPEN."

        Claim: OIC ACCEPT triggers IA.status=TERMINATED, in-OIC
        liability=IN_COMPROMISE, out-of-OIC liability=OPEN.

        # difficulty: transitive_cascade/oic_accept_to_ia_terminate_to_liability_revert_depth3
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=30_000)
        # MDI=30k => rcp = 30_000 * 12 = 360_000 (schedule_months=5)
        liab_a = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=500_000,
        )
        liab_b = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=500_000,
        )
        agreement = create_and_activate_agreement(
            taxpayer["id"], [liab_a["id"], liab_b["id"]],
            proposed_monthly_payment_cents=100_000,
            payment_method="DDIA",
        )
        # OIC covers only liab_a.
        oic = setup_oic_under_review(
            taxpayer["id"], [liab_a["id"]],
            offer_amount_cents=400_000,
            schedule_months=5,
            deposit_cents=80_000,
            take_up_officer_id="oic-cascade-A",
        )
        # Accept by a different officer.
        accept_resp = api.decide_offer_in_compromise(
            oic["id"],
            decide_offer_in_compromise_payload("ACCEPT"),
            make_oic_officer_headers("oic-cascade-B"),
        )
        validate_success(accept_resp)
        # liab_a → IN_COMPROMISE
        assert get_tax_liability(liab_a["id"])["status"] == "IN_COMPROMISE"
        # liab_b → OPEN (reverted, not in OIC)
        assert get_tax_liability(liab_b["id"])["status"] == "OPEN"
        # agreement → TERMINATED
        assert get_installment_agreement(agreement["id"])["status"] == "TERMINATED"


class TestOverlappingTolling:

    def test_two_simultaneously_open_oic_pending_tollings_forbidden(self, api):
        """PRD §3.3: "Two simultaneously-open events of the same
        event_kind on the same liability are forbidden — a second open
        of the same kind is rejected with ERR_OVERLAPPING_TOLLING."

        Claim: submit a second OIC while a first OIC's OIC_PENDING
        tolling is still open on the same liability →
        ERR_OVERLAPPING_TOLLING.

        # difficulty: resource_temporal_overlap/csed_tolling_half_open_overlap
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=2_000_000,
        )
        # First OIC: draft + deposit + submit (opens OIC_PENDING).
        oic_a = create_draft_oic(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_500_000, schedule_months=5,
        )
        pay_oic_deposit(taxpayer["id"], oic_a["id"], 300_000)
        submit_oic(taxpayer["id"], oic_a["id"])
        # Second OIC drafted; its submit must collide on the open
        # OIC_PENDING.
        oic_b = create_draft_oic(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_500_000, schedule_months=5,
        )
        pay_oic_deposit(taxpayer["id"], oic_b["id"], 300_000)
        resp = api.submit_offer_in_compromise(
            oic_b["id"], make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OVERLAPPING_TOLLING.value)
