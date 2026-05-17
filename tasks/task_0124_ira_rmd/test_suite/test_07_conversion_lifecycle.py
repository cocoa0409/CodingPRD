"""Conversion request lifecycle: branching states, approval,
rejection, cancellation, completion, segregation, Backdoor preconditions.

Coverage targets (PRD §3.7):
- Create -> PENDING.
- Pair validation: source must be TRADITIONAL, dest must be ROTH;
  cross-participant rejected.
- PENDING -> APPROVED (Custodian, segregation enforced).
- PENDING -> REJECTED (Custodian).
- PENDING -> CANCELED (Participant, owner only).
- APPROVED -> COMPLETED (Custodian, balance check, cascade creates
  DistributionEvent + Form1099R).
- Backdoor precondition: source must hold only POSTED
  BACKDOOR_NONDEDUCTIBLE for the current tax_year.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_conversion_request,
    create_conversion_request,
    create_conversion_request_payload,
    create_participant_born,
    get_account,
    make_custodian_headers,
    make_participant_headers,
    open_account,
    post_contribution,
    setup_approved_conversion,
    setup_backdoor_pair,
    setup_pending_conversion,
    setup_traditional_to_roth_pair,
    validate_error,
    validate_success,
)


# ===========================================================================
# Create — PRD §3.7
# ===========================================================================
class TestCreateConversionRequest:

    def test_create_conversion_request_pending(self, api):
        """PRD §3.7: "A Participant initiates a conversion by submitting
        the source_account_id, the destination_account_id, the
        amount_cents to convert (a positive integer of at least 1 cent),
        and an optional backdoor_flag that defaults to false. The
        system creates a ConversionRequest in PENDING status".

        Claim: POST /conversion-requests creates a PENDING request.
        """
        p, trad, roth = setup_traditional_to_roth_pair(
            seed_source_balance_cents=100_000,
        )
        resp = api.create_conversion_request(
            create_conversion_request_payload(
                source_account_id=trad["id"],
                destination_account_id=roth["id"],
                amount_cents=100_000,
            ),
            make_participant_headers(p["id"]),
        )
        cr = validate_success(resp, expected_status=201)
        assert_conversion_request(cr)
        assert cr["status"] == "PENDING"
        assert cr["participant_id"] == p["id"]
        assert cr.get("approver_role_id") is None
        assert cr.get("completed_distribution_id") is None

    def test_invalid_pair_traditional_to_traditional_rejected(self, api):
        """PRD §3.7: "The source account must be of type TRADITIONAL
        and the destination must be of type ROTH; any other pairing is
        rejected with ERR_INVALID_CONVERSION_PAIR."

        Claim: TRADITIONAL -> TRADITIONAL pair ->
        ERR_INVALID_CONVERSION_PAIR.
        """
        p = create_participant_born(1985)
        t1 = open_account(p["id"], account_type="TRADITIONAL")
        t2 = open_account(p["id"], account_type="TRADITIONAL")
        resp = api.create_conversion_request(
            create_conversion_request_payload(
                source_account_id=t1["id"],
                destination_account_id=t2["id"],
                amount_cents=1_000,
            ),
            make_participant_headers(p["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_CONVERSION_PAIR.value,
        )

    def test_invalid_pair_roth_to_roth_rejected(self, api):
        """PRD §3.7: "The source account must be of type TRADITIONAL
        and the destination must be of type ROTH; any other pairing is
        rejected with ERR_INVALID_CONVERSION_PAIR."

        Claim: ROTH -> ROTH pair -> ERR_INVALID_CONVERSION_PAIR.
        """
        p = create_participant_born(1985)
        r1 = open_account(p["id"], account_type="ROTH")
        r2 = open_account(p["id"], account_type="ROTH")
        resp = api.create_conversion_request(
            create_conversion_request_payload(
                source_account_id=r1["id"],
                destination_account_id=r2["id"],
                amount_cents=1_000,
            ),
            make_participant_headers(p["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_CONVERSION_PAIR.value,
        )

    def test_cross_participant_conversion_rejected(self, api):
        """PRD §3.7: "Both accounts must belong to the same participant
        as the path participant; cross-participant attempts are
        rejected with ERR_CROSS_PARTICIPANT_CONVERSION."

        Claim: source belongs to P1, destination to P2 ->
        ERR_CROSS_PARTICIPANT_CONVERSION.
        """
        p1 = create_participant_born(1985)
        p2 = create_participant_born(1985)
        trad_p1 = open_account(p1["id"], account_type="TRADITIONAL")
        roth_p2 = open_account(p2["id"], account_type="ROTH")
        resp = api.create_conversion_request(
            create_conversion_request_payload(
                source_account_id=trad_p1["id"],
                destination_account_id=roth_p2["id"],
                amount_cents=1_000,
            ),
            make_participant_headers(p1["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_CROSS_PARTICIPANT_CONVERSION.value,
        )


# ===========================================================================
# Approve — PRD §3.7
# ===========================================================================
class TestApproveConversion:

    def test_approve_pending_transitions_to_approved(self, api,
                                                    custodian_headers):
        """PRD §3.7: "Approval records the approving custodian's
        X-User-ID in approver_role_id and transitions the request to
        APPROVED."

        Claim: approve PENDING -> status=APPROVED and approver_role_id
        is set.
        """
        p, trad, roth, cr = setup_pending_conversion()
        resp = api.approve_conversion_request(cr["id"], custodian_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "APPROVED"
        assert data.get("approver_role_id"), (
            "approver_role_id must be set on approval"
        )

    def test_segregation_violation_when_custodian_id_equals_participant(
        self, api,
    ):
        """PRD §3.7: "The segregation rule (§2.1) blocks approvals
        where the custodian's X-User-ID matches the requesting
        participant's id with ERR_SEGREGATION_VIOLATION."

        Claim: Custodian with X-User-ID equal to participant id ->
        ERR_SEGREGATION_VIOLATION.
        """
        p, trad, roth, cr = setup_pending_conversion()
        bad_headers = make_custodian_headers(p["id"])
        resp = api.approve_conversion_request(cr["id"], bad_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION.value)


# ===========================================================================
# Reject / Cancel — PRD §3.7
# ===========================================================================
class TestRejectAndCancel:

    def test_reject_pending_transitions_to_rejected(self, api,
                                                   custodian_headers):
        """PRD §3.7: "A Custodian may instead reject a pending
        conversion. Rejection requires only that the request is
        currently PENDING; it transitions the request to REJECTED and
        performs no ledger movement."

        Claim: reject PENDING -> status=REJECTED.
        """
        p, trad, roth, cr = setup_pending_conversion()
        resp = api.reject_conversion_request(cr["id"], custodian_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "REJECTED"

    def test_participant_cancel_own_pending_transitions_to_canceled(
        self, api,
    ):
        """PRD §3.7: "The originating Participant may cancel their own
        pending conversion (the cancel endpoint requires the
        canceller's X-User-ID to equal the request's participant_id);
        this transitions a PENDING request to CANCELED."

        Claim: cancel PENDING by owner -> status=CANCELED.
        """
        p, trad, roth, cr = setup_pending_conversion()
        resp = api.cancel_conversion_request(
            cr["id"], make_participant_headers(p["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CANCELED"


# ===========================================================================
# Complete — PRD §3.7 cascade
# ===========================================================================
class TestCompleteConversion:

    def test_complete_approved_transitions_to_completed_and_moves_funds(
        self, api, custodian_headers,
    ):
        """PRD §3.7: "Completion triggers the three-link cascade
        described in §2.11: the source distribution is created and
        settled, balances move atomically from source to destination,
        a Form1099R is auto-issued, and completed_distribution_id is
        populated on the request. The terminal status after completion
        is COMPLETED."

        Claim: complete APPROVED -> status=COMPLETED, source debited,
        destination credited, completed_distribution_id set.
        """
        p, trad, roth, cr = setup_approved_conversion(
            amount_cents=700_000,
        )
        resp = api.complete_conversion_request(cr["id"],
                                               custodian_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "COMPLETED"
        assert data.get("completed_distribution_id"), (
            "completed_distribution_id must be set on completion"
        )
        trad_after = get_account(p["id"], trad["id"])
        roth_after = get_account(p["id"], roth["id"])
        assert trad_after["balance_cents"] == 0
        assert roth_after["balance_cents"] == 700_000


# ===========================================================================
# Backdoor precondition — PRD §3.7
# ===========================================================================
class TestBackdoorPrecondition:

    def test_backdoor_approval_with_pure_backdoor_source_succeeds(
        self, api, custodian_headers,
    ):
        """PRD §3.7: "when backdoor_flag is true — the source account's
        balance_cents must equal the sum of amount_cents across every
        POSTED ContributionEvent of type BACKDOOR_NONDEDUCTIBLE in the
        current tax_year on that source account, with no other postings
        and no accumulated earnings."

        Claim: backdoor approval with source containing ONLY POSTED
        BACKDOOR_NONDEDUCTIBLE succeeds.
        """
        p, trad, roth = setup_backdoor_pair(backdoor_amount_cents=700_000)
        cr = create_conversion_request(
            participant=p, source_account=trad, destination_account=roth,
            amount_cents=700_000, backdoor_flag=True,
        )
        resp = api.approve_conversion_request(cr["id"], custodian_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "APPROVED"

    def test_backdoor_approval_with_regular_contribution_rejected(
        self, api, custodian_headers,
    ):
        """PRD §3.7: "if any other contribution type or any earnings
        have entered the source for the current tax_year, approval is
        rejected with ERR_BACKDOOR_PRECONDITION_VIOLATED."

        Claim: source holds REGULAR contributions (not pure backdoor) +
        backdoor_flag=true -> ERR_BACKDOOR_PRECONDITION_VIOLATED.
        """
        p, trad, roth = setup_traditional_to_roth_pair(
            seed_source_balance_cents=200_000,
        )
        # Add a BACKDOOR contribution too so total = 300_000 mixed.
        post_contribution(trad["id"], amount_cents=100_000,
                          contribution_type="BACKDOOR_NONDEDUCTIBLE")
        cr = create_conversion_request(
            participant=p, source_account=trad, destination_account=roth,
            amount_cents=300_000, backdoor_flag=True,
        )
        resp = api.approve_conversion_request(cr["id"], custodian_headers)
        validate_error(
            resp, ApiErrorId.ERR_BACKDOOR_PRECONDITION_VIOLATED.value,
        )
