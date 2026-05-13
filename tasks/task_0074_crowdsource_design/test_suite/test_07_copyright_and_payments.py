"""Copyright transfer signing pipeline and prize-payment dispatch
(PRD §3.8 + §3.9).

Includes ERR_SIGNATURE_OUT_OF_ORDER, ERR_TRANSFER_SCOPE_INVALID, and
ERR_COPYRIGHT_NOT_REGISTERED, plus PrizePayment SCHEDULED->PAYING->PAID
and FAILED->SCHEDULED retry cycle (difficulty instance).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    PO,
    award_payload,
    create_copyright_transfer_payload,
    dispatch_payment_payload,
    emit_event,
    emit_event_payload,
    make_client_headers,
    make_designer_headers,
    setup_awarded_project,
    setup_paid_prize_payment,
    setup_registered_copyright,
    sign_transfer_payload,
    unique_idempotency_key,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTransferScopeValidation:

    def test_LIMITED_with_empty_usage_rights_rejected(self, api):
        """PRD §3.8: 'when scope is LIMITED, usage_rights must be
        non-empty; when scope is FULL, usage_rights must be empty. A
        violation surfaces ERR_TRANSFER_SCOPE_INVALID.'

        Claim: scope=LIMITED with usage_rights=[] returns
        ERR_TRANSFER_SCOPE_INVALID.
        """
        ctx = setup_awarded_project()
        project = ctx["project"]
        sub = ctx["submissions"][0]
        resp = api.create_copyright_transfer(
            create_copyright_transfer_payload(
                project_id=project["id"],
                submission_id=sub["id"],
                scope="LIMITED",
                usage_rights=[],
            ),
            PO,
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_SCOPE_INVALID.value)

    def test_FULL_with_nonempty_usage_rights_rejected(self, api):
        """PRD §3.8: 'when scope is FULL, usage_rights must be empty. A
        violation surfaces ERR_TRANSFER_SCOPE_INVALID.'

        Claim: scope=FULL with usage_rights non-empty returns
        ERR_TRANSFER_SCOPE_INVALID.
        """
        ctx = setup_awarded_project()
        project = ctx["project"]
        sub = ctx["submissions"][0]
        resp = api.create_copyright_transfer(
            create_copyright_transfer_payload(
                project_id=project["id"],
                submission_id=sub["id"],
                scope="FULL",
                usage_rights=["print", "digital"],
            ),
            PO,
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_SCOPE_INVALID.value)


class TestSignatureOrder:

    def test_designer_signing_before_client_rejected(self, api):
        """PRD §3.8: 'An out-of-order signature is rejected with
        ERR_SIGNATURE_OUT_OF_ORDER.'
        PRD §3.8: 'on issue the server emits a COPYRIGHT_DRAFTED
        AuditEvent and pre-populates signers in the fixed order CLIENT,
        DESIGNER, PLATFORM_NOTARY.'

        Claim: a Designer attempting to sign while the CLIENT slot is
        still unsigned receives ERR_SIGNATURE_OUT_OF_ORDER.
        """
        ctx = setup_awarded_project()
        project = ctx["project"]
        sub = ctx["submissions"][0]
        designer = ctx["designers"][0]
        # Create transfer and issue for signing.
        transfer = validate_success(api.create_copyright_transfer(
            create_copyright_transfer_payload(
                project_id=project["id"],
                submission_id=sub["id"],
                scope="FULL",
                usage_rights=[],
            ),
            PO,
        ), expected_status=201)
        transfer = validate_success(api.issue_for_signing(transfer["id"], PO))
        # Designer tries to sign before Client.
        resp = api.sign_transfer(
            transfer["id"],
            sign_transfer_payload(signer_party_kind="DESIGNER"),
            make_designer_headers(designer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SIGNATURE_OUT_OF_ORDER.value)


class TestDispatchPreconditions:

    def test_dispatch_with_unregistered_copyright_rejected(self, api):
        """PRD §3.9: 'Dispatch is also gated on the linked
        CopyrightTransfer.status being REGISTERED; a dispatch attempt
        against an unregistered transfer is rejected with
        ERR_COPYRIGHT_NOT_REGISTERED.'

        Claim: dispatch on a SCHEDULED PrizePayment whose linked
        CopyrightTransfer is NOT REGISTERED returns
        ERR_COPYRIGHT_NOT_REGISTERED.

        # difficulty: cross_entity_state_dependency/prize_payment_dispatch_requires_copyright_registered
        """
        ctx = setup_awarded_project()
        project = ctx["project"]
        tier = ctx["tiers"][0]
        # Locate the SCHEDULED PrizePayment.
        items, _ = validate_paginated(api.list_prize_payments(
            PO, params={"project_id": project["id"]},
        ))
        pp = next((i for i in items
                   if i.get("prize_tier_id") == tier["id"]), None)
        assert pp is not None
        # The CopyrightTransfer was auto-DRAFTED (not REGISTERED).
        resp = api.dispatch_payment(
            pp["id"],
            dispatch_payment_payload(),
            PO,
        )
        validate_error(resp, ApiErrorId.ERR_COPYRIGHT_NOT_REGISTERED.value)

    def test_dispatch_after_registered_succeeds(self, api):
        """PRD §3.9: 'Dispatch is also gated on the linked
        CopyrightTransfer.status being REGISTERED.'

        Claim: with CopyrightTransfer in REGISTERED, dispatch flips
        PrizePayment from SCHEDULED to PAYING.

        # difficulty: cross_entity_state_dependency/prize_payment_dispatch_requires_copyright_registered
        """
        ctx = setup_registered_copyright()
        project = ctx["project"]
        tier = ctx["tiers"][0]
        items, _ = validate_paginated(api.list_prize_payments(
            PO, params={"project_id": project["id"]},
        ))
        pp = next((i for i in items
                   if i.get("prize_tier_id") == tier["id"]), None)
        assert pp is not None
        resp = api.dispatch_payment(
            pp["id"],
            dispatch_payment_payload(idempotency_key=unique_idempotency_key()),
            PO,
        )
        data = validate_success(resp)
        assert data["status"] == "PAYING"


class TestPaymentCompletion:

    def test_payment_completed_event_moves_to_PAID(self, api):
        """PRD §3.9: 'An event with event_type of PAYMENT_COMPLETED and
        subject_id equal to the payment's identifier moves PAYING to
        PAID.'

        Claim: emitting PAYMENT_COMPLETED moves the payment to PAID.
        """
        ctx = setup_paid_prize_payment()
        pp = ctx["prize_payment"]
        assert pp["status"] == "PAID"

    def test_payment_failed_then_retry_cycle(self, api):
        """PRD §3.9: 'An event with event_type of PAYMENT_FAILED moves
        PAYING to FAILED. From FAILED, PlatformOps may retry, moving
        FAILED back to SCHEDULED for a fresh dispatch attempt.'

        Claim: status traversal SCHEDULED -> PAYING -> FAILED ->
        SCHEDULED is observable through dispatch -> /_events/emit
        PAYMENT_FAILED -> /retry.

        # difficulty: non_linear_state_machine/prize_payment_retry_cycle
        """
        ctx = setup_registered_copyright()
        project = ctx["project"]
        tier = ctx["tiers"][0]
        items, _ = validate_paginated(api.list_prize_payments(
            PO, params={"project_id": project["id"]},
        ))
        pp = next((i for i in items
                   if i.get("prize_tier_id") == tier["id"]), None)
        assert pp is not None
        assert pp["status"] == "SCHEDULED"

        # Dispatch -> PAYING.
        pp1 = validate_success(api.dispatch_payment(
            pp["id"],
            dispatch_payment_payload(idempotency_key=unique_idempotency_key()),
            PO,
        ))
        assert pp1["status"] == "PAYING"

        # /_events PAYMENT_FAILED -> FAILED.
        emit_event("PAYMENT_FAILED", pp["id"])
        pp2 = validate_success(api.get_prize_payment(pp["id"], PO))
        assert pp2["status"] == "FAILED"

        # /retry -> SCHEDULED.
        pp3 = validate_success(api.retry_payment(pp["id"], PO))
        assert pp3["status"] == "SCHEDULED", (
            f"Retry must move FAILED back to SCHEDULED; got {pp3['status']!r}"
        )
