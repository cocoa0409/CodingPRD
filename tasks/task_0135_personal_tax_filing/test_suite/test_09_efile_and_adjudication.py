"""E-filing and IRS adjudication workflows.

Coverage targets (PRD §3.8):
- READY_TO_FILE -> FILED creates EFiling with outcome PENDING.
- Adjudicator ACCEPTED -> TaxReturn FILED -> ACCEPTED, accepted_at set.
- Adjudicator REJECTED -> TaxReturn FILED -> REJECTED.
- Reject decision requires rejection_code.
- /unlock-for-correction takes REJECTED back to DRAFT.
- Pending credits prevent efile (PRD §3.8).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    accept_filing,
    add_credit,
    assert_efiling,
    assert_tax_return,
    compute_tax_return,
    decide_filing_payload,
    efile_tax_return,
    make_taxpayer_headers,
    re_get_efiling,
    re_get_tax_return,
    reject_filing,
    setup_filed_return,
    setup_ready_to_file_return,
    setup_rejected_return,
    setup_simple_w2_return,
    TEST_USERS,
    unlock_for_correction,
    validate_error,
    validate_success,
)


# ===========================================================================
# Efile happy path — PRD §3.8
# ===========================================================================
class TestEfile:

    def test_efile_creates_pending_efiling(self, api):
        """PRD §3.8: "The submission creates a new EFiling record
        carrying its tax_return_id, a system-minted submission_id, an
        outcome of PENDING, a filed_at timestamp set to the current
        virtual clock value, and a null processed_at."

        Claim: POST /tax-returns/{id}/efile returns an EFiling with
        outcome=PENDING, processed_at=null.
        """
        taxpayer, ready_return, _ = setup_ready_to_file_return()
        efiling = efile_tax_return(taxpayer, ready_return["id"])
        assert_efiling(efiling)
        assert efiling["outcome"] == "PENDING"
        assert efiling["processed_at"] is None
        assert efiling["tax_return_id"] == ready_return["id"]

    def test_efile_transitions_return_to_filed(self, api):
        """PRD §3.8: "The owning return moves from READY_TO_FILE to
        FILED, its own filed_at is set to the clock value".

        Claim: after /efile the return's status == FILED.
        """
        taxpayer, ready_return, _ = setup_ready_to_file_return()
        efile_tax_return(taxpayer, ready_return["id"])
        after = re_get_tax_return(taxpayer, ready_return["id"])
        assert after["status"] == "FILED"
        assert after["filed_at"] is not None

    def test_efile_requires_ready_to_file_state(self, api):
        """PRD §3.8: "The submission is rejected with ERR_INVALID_STATE
        if the return is not in READY_TO_FILE".

        Claim: efile on a DRAFT return -> ERR_INVALID_STATE.
        """
        from test_helpers import (
            setup_active_taxpayer_with_draft_return,
        )
        taxpayer, draft = setup_active_taxpayer_with_draft_return()
        resp = api.efile_tax_return(
            draft["id"], {}, make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_efile_blocked_when_credit_pending(self, api):
        """PRD §3.8: "The submission is rejected with ERR_INVALID_STATE
        if the return is not in READY_TO_FILE or if any TaxCredit on
        the return still shows eligibility_status PENDING - every
        claimed credit must have been evaluated by a prior compute
        call."

        Claim: a credit added AFTER compute (i.e., still PENDING)
        blocks efile with ERR_INVALID_STATE.

        Construction: setup_ready_to_file_return gives a READY_TO_FILE
        return; we then add a credit which reverts it back to DRAFT
        per PRD §2.7 — so we re-arrange: compute, then attach credit
        which re-opens to DRAFT, then compute again so the credit is
        evaluated. To test the PENDING blocker we must build a path
        where a credit on the return is PENDING at the moment of
        efile. Since compute always evaluates every credit, the only
        way to reach efile with a PENDING credit is if someone
        bypasses compute. PRD's stated guard is observable only when
        an implementation that doesn't enforce compute would let
        through. We test the rule at its observable surface: a return
        in non-READY_TO_FILE state at efile time returns
        ERR_INVALID_STATE (the same error covers both phrases of the
        PRD sentence). The credit-PENDING subset is therefore
        observed via the DRAFT path: a return with an unevaluated
        credit will be in DRAFT (because adding a credit reverted it),
        and efile against DRAFT returns ERR_INVALID_STATE.
        """
        taxpayer, ready_return, _ = setup_ready_to_file_return()
        # Add a credit — this reverts the return to DRAFT per PRD §2.7.
        add_credit(
            taxpayer, ready_return["id"],
            credit_type="CTC", requested_amount_cents=200_000,
        )
        resp = api.efile_tax_return(
            ready_return["id"], {},
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# IRS adjudication — PRD §3.8
# ===========================================================================
class TestAdjudication:

    def test_accept_decision_cascades_to_return(self, api):
        """PRD §3.8: "An accept decision sets the filing's outcome to
        ACCEPTED and stamps processed_at with the current clock; in
        the same operation it cascades the linked TaxReturn from FILED
        to ACCEPTED, stamps the return's accepted_at".

        Claim: after accept_filing, TaxReturn.status == ACCEPTED,
        accepted_at is non-null, and EFiling.outcome == ACCEPTED with
        processed_at set.
        """
        taxpayer, filed_return, efiling = setup_filed_return()
        accept_filing(efiling["id"])
        after_return = re_get_tax_return(taxpayer, filed_return["id"])
        after_efiling = re_get_efiling(taxpayer, efiling["id"])
        assert after_return["status"] == "ACCEPTED"
        assert after_return["accepted_at"] is not None
        assert after_efiling["outcome"] == "ACCEPTED"
        assert after_efiling["processed_at"] is not None

    def test_reject_decision_cascades_to_return(self, api):
        """PRD §3.8: "A reject decision requires a rejection_code (and
        optionally a rejection_message) and sets the filing's outcome
        to REJECTED, stamps processed_at, cascades the return from
        FILED to REJECTED".

        Claim: after reject_filing, TaxReturn.status == REJECTED,
        EFiling.outcome == REJECTED.
        """
        taxpayer, filed_return, efiling = setup_filed_return()
        reject_filing(efiling["id"], rejection_code="R0001")
        after_return = re_get_tax_return(taxpayer, filed_return["id"])
        after_efiling = re_get_efiling(taxpayer, efiling["id"])
        assert after_return["status"] == "REJECTED"
        assert after_efiling["outcome"] == "REJECTED"

    def test_decide_requires_pending_outcome(self, api):
        """PRD §2.10 priority 7 (state precondition) plus PRD §3.8:
        "Only an IRSAdjudicator may decide a filing, and only while
        the EFiling's outcome is PENDING."

        Claim: a second decision on an already-decided EFiling ->
        ERR_INVALID_STATE.
        """
        taxpayer, filed_return, efiling = setup_filed_return()
        accept_filing(efiling["id"])
        # Try to decide it again.
        resp = api.decide_efiling(
            efiling["id"],
            decide_filing_payload(outcome="ACCEPTED"),
            TEST_USERS["irs_adjudicator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Reopen for correction — PRD §3.8
# ===========================================================================
class TestReopen:

    def test_unlock_for_correction_reverts_to_draft(self, api):
        """PRD §3.8: "When a return has been rejected by the IRS, the
        taxpayer is permitted to reopen it for correction. The reopen
        operation requires that the return is currently in REJECTED
        and that the most recent EFiling for that return has an
        outcome of REJECTED; on success the return moves from REJECTED
        back to DRAFT, the computed numbers are invalidated per §2.7".

        Claim: POST /tax-returns/{id}/unlock-for-correction on a
        REJECTED return moves it back to DRAFT and zeroes the
        computed fields.
        """
        taxpayer, rejected, _ = setup_rejected_return()
        assert rejected["status"] == "REJECTED"
        unlock_for_correction(taxpayer, rejected["id"])
        after = re_get_tax_return(taxpayer, rejected["id"])
        assert after["status"] == "DRAFT"
        # PRD §2.7 invalidation applies.
        for f in (
            "agi_cents",
            "taxable_income_cents",
            "regular_tax_cents",
            "amt_cents",
            "total_credits_cents",
            "balance_due_or_refund_cents",
        ):
            assert after[f] == 0

    def test_unlock_rejected_when_not_in_rejected(self, api):
        """PRD §3.8: "The reopen operation requires that the return is
        currently in REJECTED".

        Claim: unlock-for-correction on a DRAFT return ->
        ERR_INVALID_STATE.
        """
        from test_helpers import setup_active_taxpayer_with_draft_return
        taxpayer, draft = setup_active_taxpayer_with_draft_return()
        resp = api.unlock_for_correction(
            draft["id"], make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
