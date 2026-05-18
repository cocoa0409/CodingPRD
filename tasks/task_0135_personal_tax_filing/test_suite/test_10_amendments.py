"""1040X amendment workflow.

Coverage targets (PRD §3.9):
- Creating amendment requires original in ACCEPTED.
- form_code is fixed at '1040X' (system-controlled).
- Only one active AmendedReturn per original (DRAFT/SUBMITTED).
- Submit moves DRAFT -> SUBMITTED, original ACCEPTED -> AMENDED.
- Submit requires at least one restated field differs.
- Accept decision: AmendedReturn -> ACCEPTED, original AMENDED ->
  SUPERSEDED.
- Reject decision: AmendedReturn -> REJECTED, original AMENDED ->
  ACCEPTED.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    accept_amendment,
    accept_filing,
    assert_amended_return,
    create_amendment,
    create_amendment_payload,
    decide_amendment_payload,
    make_taxpayer_headers,
    re_get_amendment,
    re_get_tax_return,
    reject_amendment,
    setup_accepted_return,
    setup_amendment_draft,
    setup_amendment_submitted,
    setup_active_taxpayer_with_draft_return,
    submit_amendment,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Creating amendment — PRD §3.9
# ===========================================================================
class TestCreateAmendment:

    def test_amendment_form_code_is_1040x(self, api):
        """PRD §3.9: "The amendment's form_code is fixed at the literal
        string '1040X' by the system and is not taxpayer-controllable."

        Claim: every created AmendedReturn carries form_code='1040X'.
        """
        taxpayer, _tax_return, amendment = setup_amendment_draft()
        assert_amended_return(amendment)
        assert amendment["form_code"] == "1040X"

    def test_amendment_starts_in_draft(self, api):
        """PRD §3.9: "The amendment is born in DRAFT with a null
        submitted_at, null restated_return_snapshot, and zeroes for
        delta_agi_cents, delta_tax_cents, and
        delta_balance_due_or_refund_cents."

        Claim: a freshly created amendment has status DRAFT, null
        submitted_at, and zero delta fields.
        """
        taxpayer, _tax_return, amendment = setup_amendment_draft()
        assert amendment["status"] == "DRAFT"
        assert amendment.get("submitted_at") is None
        assert amendment["delta_agi_cents"] == 0
        assert amendment["delta_tax_cents"] == 0
        assert amendment["delta_balance_due_or_refund_cents"] == 0

    def test_create_against_non_accepted_rejected(self, api):
        """PRD §3.9: "The taxpayer creates an AmendedReturn by supplying
        the original_return_id (which must reference a TaxReturn
        currently in ACCEPTED - otherwise ERR_AMENDMENT_NOT_ALLOWED)".

        Claim: POST /amendments where original is DRAFT ->
        ERR_AMENDMENT_NOT_ALLOWED.
        """
        taxpayer, draft = setup_active_taxpayer_with_draft_return()
        resp = api.create_amendment(
            create_amendment_payload(
                original_return_id=draft["id"],
                reason_summary="early",
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_NOT_ALLOWED.value)

    def test_amendment_already_open_blocks_second(self, api):
        """PRD §3.9: "Only one active amendment is permitted per
        original return: a second creation or submission attempt while
        another AmendedReturn with status DRAFT or SUBMITTED already
        references the same original is rejected with
        ERR_AMENDMENT_ALREADY_OPEN."

        Claim: a second POST /amendments while an active amendment
        exists -> ERR_AMENDMENT_ALREADY_OPEN.
        """
        taxpayer, accepted_return, _amendment = setup_amendment_draft()
        resp = api.create_amendment(
            create_amendment_payload(
                original_return_id=accepted_return["id"],
                reason_summary="another",
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_ALREADY_OPEN.value)


# ===========================================================================
# Submit amendment — PRD §3.9
# ===========================================================================
class TestSubmitAmendment:

    def test_submit_moves_amendment_to_submitted(self, api):
        """PRD §3.9: "Submitting an amendment from DRAFT to SUBMITTED
        re-runs the entire compute pipeline (AGI, taxable income,
        regular tax, AMT, credits, balance) against the amendment's
        restated inputs."

        Claim: a successful submit reports status SUBMITTED.
        """
        taxpayer, _amended_return, amendment = setup_amendment_submitted()
        assert amendment["status"] == "SUBMITTED"

    def test_submit_cascades_original_to_amended(self, api):
        """PRD §3.9: "Submission additionally cascades the original
        TaxReturn from ACCEPTED to AMENDED in the same operation and
        appends a RETURN_AMENDED audit row."

        Claim: original TaxReturn's status moves ACCEPTED -> AMENDED
        in the same operation.
        """
        taxpayer, original_after_amend, _amendment = (
            setup_amendment_submitted()
        )
        assert original_after_amend["status"] == "AMENDED"

    def test_submit_sets_submitted_at(self, api):
        """PRD §3.9: "The system stamps the amendment's submitted_at
        with the current clock".

        Claim: submitted amendment has non-null submitted_at.
        """
        taxpayer, _amended_return, amendment = setup_amendment_submitted()
        assert amendment.get("submitted_at") is not None

    def test_submit_requires_at_least_one_restated_field(self, api):
        """PRD §3.9: "The submission step requires that at least one
        restated field actually differs from the original snapshot;
        otherwise it is rejected with ERR_INVALID_STATE."

        Claim: POST /amendments/{id}/submit on an amendment whose
        restated fields are all identical to the original ->
        ERR_INVALID_STATE.

        Build: original = SINGLE STD dep=0 qc=0; amendment supplies no
        restated fields (so every restated value matches original).
        Submit must fail.
        """
        # setup_amendment_draft returns (taxpayer, accepted_original,
        # amendment_in_DRAFT). We pass no restated_* overrides so the
        # amendment's restated values default to match the original
        # snapshot.
        taxpayer, _accepted_return, amendment = setup_amendment_draft(
            reason_summary="no diff",
        )
        assert amendment["status"] == "DRAFT"
        resp = api.submit_amendment(
            amendment["id"], {},
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Decide amendment — PRD §3.9
# ===========================================================================
class TestDecideAmendment:

    def test_accept_amendment_supersedes_original(self, api):
        """PRD §3.9: "An accept decision requires the amendment is
        currently SUBMITTED; it transitions the amendment to its
        terminal ACCEPTED state, cascades the original return from
        AMENDED to the terminal state SUPERSEDED".

        Claim: accept_amendment -> amendment.status==ACCEPTED, original
        TaxReturn.status==SUPERSEDED.
        """
        taxpayer, original_after_amend, amendment = (
            setup_amendment_submitted()
        )
        accept_amendment(amendment["id"])
        after_amendment = re_get_amendment(taxpayer, amendment["id"])
        after_original = re_get_tax_return(
            taxpayer, original_after_amend["id"],
        )
        assert after_amendment["status"] == "ACCEPTED"
        assert after_original["status"] == "SUPERSEDED"

    def test_reject_amendment_reverts_original_to_accepted(self, api):
        """PRD §3.9: "A reject decision likewise requires SUBMITTED
        status and a rejection_message; it transitions the amendment
        to its terminal REJECTED state, reverts the original return
        from AMENDED back to ACCEPTED (so the taxpayer's previously
        accepted filing is restored)".

        Claim: reject_amendment -> amendment.status==REJECTED, original
        TaxReturn.status reverts AMENDED -> ACCEPTED.
        """
        taxpayer, original_after_amend, amendment = (
            setup_amendment_submitted()
        )
        reject_amendment(amendment["id"])
        after_amendment = re_get_amendment(taxpayer, amendment["id"])
        after_original = re_get_tax_return(
            taxpayer, original_after_amend["id"],
        )
        assert after_amendment["status"] == "REJECTED"
        assert after_original["status"] == "ACCEPTED"
