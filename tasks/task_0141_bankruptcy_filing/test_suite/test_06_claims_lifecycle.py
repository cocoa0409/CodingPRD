"""Claim creation, allowance via conduct_341, disallowance.

PRD §3.6.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    assert_claim,
    conduct_341,
    create_claim_payload,
    create_creditor,
    disallow_claim,
    file_claim,
    make_creditor_headers,
    re_get_claim,
    setup_meeting_held_case,
    setup_meeting_scheduled_case,
    validate_error,
)


# ===========================================================================
# Claim creation — PRD §3.6
# ===========================================================================
class TestClaimCreation:
    """PRD §3.6: 'Creditors file Claim rows against an open case by
    submitting creditor_id, claim_class, amount_cents, and
    is_dischargeable. The creditor_id must match the acting X-User-ID,
    the claim_class must equal the registered creditor_type of that
    creditor (otherwise ERR_CLAIM_CLASS_MISMATCH), and the amount_cents
    must be strictly greater than zero (a zero-or-negative value yields
    ERR_CLAIM_AMOUNT_INVALID).'"""

    def test_claim_created_in_filed_status(self, api):
        """PRD §3.6: "A newly filed claim enters in FILED status and
        waits for the 341 meeting to be conducted before transitioning
        to ALLOWED via the cascade described in §3.5."

        Claim: a fresh claim has status=FILED.
        """
        debtor, case, _mtr, _md = setup_meeting_scheduled_case()
        creditor = create_creditor(creditor_type="GENERAL_UNSECURED")
        cl = file_claim(case=case, creditor=creditor, amount_cents=100_000)
        assert_claim(cl)
        assert cl["status"] == "FILED"

    def test_claim_class_must_equal_creditor_type(self, api):
        """PRD §3.6: "the claim_class must equal the registered
        creditor_type of that creditor (otherwise
        ERR_CLAIM_CLASS_MISMATCH)".

        Claim: claim_class mismatch with creditor_type ->
        ERR_CLAIM_CLASS_MISMATCH.
        """
        debtor, case, _mtr, _md = setup_meeting_scheduled_case()
        creditor = create_creditor(creditor_type="SECURED")
        resp = api.create_claim(
            case["id"],
            create_claim_payload(
                creditor_id=creditor["id"],
                claim_class="GENERAL_UNSECURED",  # mismatch
                amount_cents=10_000,
                is_dischargeable=True,
            ),
            make_creditor_headers(creditor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_CLASS_MISMATCH.value)

    def test_zero_amount_claim_rejected(self, api):
        """PRD §3.6: "the amount_cents must be strictly greater than
        zero (a zero-or-negative value yields ERR_CLAIM_AMOUNT_INVALID)".

        Claim: amount_cents=0 -> ERR_CLAIM_AMOUNT_INVALID.
        """
        debtor, case, _mtr, _md = setup_meeting_scheduled_case()
        creditor = create_creditor(creditor_type="GENERAL_UNSECURED")
        resp = api.create_claim(
            case["id"],
            create_claim_payload(
                creditor_id=creditor["id"],
                claim_class="GENERAL_UNSECURED",
                amount_cents=0,
                is_dischargeable=True,
            ),
            make_creditor_headers(creditor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_AMOUNT_INVALID.value)

    def test_negative_amount_claim_rejected(self, api):
        """PRD §3.6: "amount_cents must be strictly greater than zero
        (a zero-or-negative value yields ERR_CLAIM_AMOUNT_INVALID)".

        Claim: amount_cents<0 -> ERR_CLAIM_AMOUNT_INVALID.
        """
        debtor, case, _mtr, _md = setup_meeting_scheduled_case()
        creditor = create_creditor(creditor_type="GENERAL_UNSECURED")
        resp = api.create_claim(
            case["id"],
            create_claim_payload(
                creditor_id=creditor["id"],
                claim_class="GENERAL_UNSECURED",
                amount_cents=-100,
                is_dischargeable=True,
            ),
            make_creditor_headers(creditor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_AMOUNT_INVALID.value)


# ===========================================================================
# Claim disallowance — PRD §3.6
# ===========================================================================
class TestClaimDisallowance:
    """PRD §3.6: 'A trustee may disallow a FILED claim, identified by
    its claim_id path segment, while the case is still in FILED or
    MEETING_SCHEDULED — disallowance transitions the claim to
    DISALLOWED directly without passing through ALLOWED.'"""

    def test_disallow_filed_claim_in_meeting_scheduled(self, api):
        """PRD §3.6: "A trustee may disallow a FILED claim, identified
        by its claim_id path segment, while the case is still in FILED
        or MEETING_SCHEDULED — disallowance transitions the claim to
        DISALLOWED directly without passing through ALLOWED."

        Claim: disallow a FILED claim while case in MEETING_SCHEDULED
        -> Claim.status=DISALLOWED.
        """
        debtor, case, _mtr, _md = setup_meeting_scheduled_case()
        creditor = create_creditor(creditor_type="GENERAL_UNSECURED")
        cl = file_claim(case=case, creditor=creditor, amount_cents=50_000)
        result = disallow_claim(case=case, claim=cl)
        assert result["status"] == "DISALLOWED"

    def test_disallow_from_meeting_held_rejected(self, api):
        """PRD §3.6: "Once the case has advanced past
        MEETING_SCHEDULED, claims are no longer in FILED state and
        disallowance via this route is not available; attempting it
        from any other case state is rejected with ERR_INVALID_STATE."

        Claim: disallow attempt when case is in MEETING_HELD (claim has
        already cascaded to ALLOWED) -> ERR_INVALID_STATE.
        """
        # Build with one claim that will cascade to ALLOWED.
        debtor, case, _mtr, _cr, claims_after = setup_meeting_held_case(
            chapter_requested="CHAPTER_7",
            claims=[{"amount_cents": 50_000,
                     "is_dischargeable": True,
                     "claim_class": "GENERAL_UNSECURED"}],
        )
        cl = claims_after[0]
        assert cl["status"] == "ALLOWED"
        resp = api.disallow_claim(
            case["id"], cl["id"], None, TEST_USERS["trustee_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# is_dischargeable field — PRD §3.6
# ===========================================================================
class TestIsDischargeableField:
    """PRD §3.6: 'The is_dischargeable boolean is supplied at claim
    filing and records whether this debt will be erased on discharge:
    it is set to false for the exempt set (support obligations, certain
    taxes, criminal restitution, fraud-based debts) and true for
    ordinary dischargeable debts.'"""

    @pytest.mark.parametrize("dischargeable", [True, False])
    def test_is_dischargeable_round_trips(self, api, dischargeable):
        """PRD §3.6: "The is_dischargeable boolean is supplied at
        claim filing and records whether this debt will be erased on
        discharge".

        Claim: is_dischargeable supplied at creation is persisted.
        """
        debtor, case, _mtr, _md = setup_meeting_scheduled_case()
        creditor = create_creditor(creditor_type="GENERAL_UNSECURED")
        cl = file_claim(
            case=case, creditor=creditor, amount_cents=100_000,
            is_dischargeable=dischargeable,
        )
        assert cl["is_dischargeable"] is dischargeable
