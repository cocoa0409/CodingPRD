"""Disbursements and the escrow pool (PRD §3.7)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_disbursement,
    approve_disbursement,
    create_disbursement,
    disbursement_payload,
    re_get_disbursement,
    send_disbursement,
    settle_disbursement,
    setup_confirmed_wire,
    setup_disbursement_settled,
    setup_escrow_in_contingent_wire,
    setup_escrow_ready_to_close,
    validate_error,
    validate_success,
    version_only_payload,
    with_idempotency,
)


# ===========================================================================
# Disbursement creation — PRD §3.7
# ===========================================================================
class TestDisbursementCreation:

    def test_create_disbursement_returns_proposed(self, api):
        """PRD §3.7: "the escrow officer proposes a Disbursement by
        supplying the escrow_file_id, the wire_instruction_id, and the
        dollar amount. The disbursement enters PROPOSED."

        Claim: POST /disbursements returns 201 with status=PROPOSED.
        """
        bundle = setup_escrow_in_contingent_wire()
        ef = bundle["escrow_file"]
        wire = setup_confirmed_wire(
            ef["id"], "SELLER", bundle["seller"]["id"],
        )
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.create_disbursement(
            disbursement_payload(
                escrow_file_id=ef["id"],
                wire_instruction_id=wire["id"],
                amount=1000.00,
            ),
            eo,
        )
        data = validate_success(resp, expected_status=201)
        assert_disbursement(data)
        assert data["status"] == "PROPOSED"
        assert data["amount"] == pytest.approx(1000.00)


# ===========================================================================
# Disbursement approval — PRD §3.7
# ===========================================================================
class TestDisbursementApproval:

    def test_approve_records_approver(self, api):
        """PRD §3.7: "On approval the server writes approved_by_user_id
        to the calling actor."

        Claim: after approve, approved_by_user_id matches the
        DisbursementApprover's X-User-ID.
        """
        bundle = setup_escrow_ready_to_close()
        ef = bundle["escrow_file"]
        wire = bundle["seller_wire"]
        disb = create_disbursement(ef["id"], wire["id"], 500.00)
        disb_approved = approve_disbursement(
            disb["id"], version=disb["version"],
        )
        assert disb_approved["status"] == "APPROVED"
        assert disb_approved.get("approved_by_user_id") == \
            TEST_USERS["disb_approver_headers"]["X-User-ID"]

    def test_approve_then_send_then_settle(self, api):
        """PRD §3.7: "An approved disbursement is sent by the approver,
        moving it to SENT, and is later settled by the escrow officer
        once the bank confirms posting, moving it to SETTLED."

        Claim: approve → send → settle drives status through
        APPROVED, SENT, SETTLED.
        """
        bundle = setup_escrow_ready_to_close()
        ef = bundle["escrow_file"]
        wire = bundle["seller_wire"]
        disb = create_disbursement(ef["id"], wire["id"], 500.00)
        disb = approve_disbursement(disb["id"], version=disb["version"])
        assert disb["status"] == "APPROVED"
        disb = send_disbursement(disb["id"], version=disb["version"])
        assert disb["status"] == "SENT"
        disb = settle_disbursement(disb["id"], version=disb["version"])
        assert disb["status"] == "SETTLED"


# ===========================================================================
# Reverse — PRD §3.7
# ===========================================================================
class TestDisbursementReverse:

    def test_reverse_from_sent_succeeds(self, api):
        """PRD §3.7: "A disbursement can be reversed from PROPOSED,
        APPROVED, or SENT".

        Claim: reverse from SENT moves status to REVERSED.
        """
        bundle = setup_escrow_ready_to_close()
        ef = bundle["escrow_file"]
        wire = bundle["seller_wire"]
        disb = create_disbursement(ef["id"], wire["id"], 500.00)
        disb = approve_disbursement(disb["id"], version=disb["version"])
        disb = send_disbursement(disb["id"], version=disb["version"])
        # Reverse via EscrowOfficer (PRD §3.7 keeps reverse as
        # EscrowOfficer per scaffold mapping).
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.reverse_disbursement(
            disb["id"], version_only_payload(version=disb["version"]), eo,
        )
        data = validate_success(resp)
        assert data["status"] == "REVERSED"
