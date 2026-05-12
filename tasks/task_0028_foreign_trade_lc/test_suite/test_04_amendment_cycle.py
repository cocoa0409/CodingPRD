"""Amendment cycle: applicant / beneficiary / confirming-bank consent
plus withdrawal (PRD §3.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    applicant_consent_amendment,
    assert_lc_amendment,
    beneficiary_consent_amendment,
    cancel_lc_payload,
    consent_payload,
    create_amendment_payload,
    find_swift_message_of_type,
    get_lc,
    initiate_amendment,
    setup_active_lc,
    setup_pending_amendment,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_amendment,
)


# ===========================================================================
# §3.4 — Initiation
# ===========================================================================
class TestAmendmentInitiation:

    def test_amendment_creation_pushes_lc_to_pending_applicant(self, api):
        """PRD §3.4: 'Initiating an amendment creates an LcAmendment row
        carrying a per-LC amendment_seq starting at 1, sets its
        applicant_consent to PENDING, sets the LC's
        amendment_consent_status from NONE to PENDING_APPLICANT, and
        emits an MT707 SWIFT message keyed on the new amendment's id.'"""
        lc, bundle = setup_active_lc(amount_minor_units=100_000)
        res = api.create_amendment(
            lc["id"],
            create_amendment_payload(changes={"amount_minor_units": 150_000}),
            bundle["issuing_bank_headers"],
        )
        amendment = validate_success(res, expected_status=201)
        assert_lc_amendment(amendment)
        assert amendment["status"] == "PENDING"
        assert amendment["applicant_consent"] == "PENDING"
        assert amendment["amendment_seq"] == 1, (
            "PRD §3.4: 'a per-LC amendment_seq starting at 1'"
        )
        # Verify LC.amendment_consent_status flipped.
        snapshot = get_lc(lc["id"], bundle["applicant_headers"])
        assert snapshot["amendment_consent_status"] == "PENDING_APPLICANT", (
            "PRD §3.4: 'sets the LC's amendment_consent_status from NONE "
            "to PENDING_APPLICANT'"
        )

    def test_amendment_creation_emits_mt707(self, api):
        """PRD §3.4: 'and emits an MT707 SWIFT message keyed on the new
        amendment's id.'"""
        lc, bundle = setup_active_lc(amount_minor_units=100_000)
        initiate_amendment(
            lc["id"], bundle["issuing_bank_headers"],
            changes={"amount_minor_units": 150_000},
        )
        res = api.list_swift_messages(lc["id"], bundle["issuing_bank_headers"])
        msgs, _ = validate_paginated(res)
        mt707 = find_swift_message_of_type(msgs, "MT707")
        assert mt707 is not None, "PRD §3.4: MT707 must be emitted on amendment"

    def test_concurrent_pending_amendments_rejected(self, api):
        """PRD §3.4: 'At most one LcAmendment may be PENDING per LC at a
        time — a second concurrent initiation is rejected with
        ERR_AMENDMENT_PENDING'."""
        lc, bundle, _amendment = setup_pending_amendment(
            amount_minor_units=100_000,
        )
        res = api.create_amendment(
            lc["id"],
            create_amendment_payload(changes={"expiry_date": "2027-01-01T00:00:00.000Z"}),
            bundle["issuing_bank_headers"],
        )
        validate_error(res, "ERR_AMENDMENT_PENDING")

    def test_amend_lc_in_draft_rejected(self, api):
        """PRD §3.4: 'An LC in ISSUED, ADVISED, or ACTIVE can be amended;
        any other lifecycle status produces ERR_LC_NOT_AMENDABLE.'"""
        from test_helpers import (  # noqa: WPS433
            create_lc_draft,
            setup_party_bundle,
        )
        bundle = setup_party_bundle()
        lc, _ = create_lc_draft(bundle=bundle)
        # LC sits in DRAFT — amendment must be rejected.
        res = api.create_amendment(
            lc["id"],
            create_amendment_payload(changes={"amount_minor_units": 9_999}),
            bundle["issuing_bank_headers"],
        )
        validate_error(res, "ERR_LC_NOT_AMENDABLE")


# ===========================================================================
# §3.4 — Consent ordering and decisions
# ===========================================================================
class TestConsentDecisions:

    def test_applicant_consent_advances_to_pending_beneficiary(self, api):
        """PRD §3.4: 'a CONSENTED decision flips applicant_consent to
        CONSENTED and advances amendment_consent_status to
        PENDING_BENEFICIARY'."""
        lc, bundle, amendment = setup_pending_amendment(
            amount_minor_units=100_000,
        )
        res = api.applicant_consent(
            lc["id"], amendment["id"],
            consent_payload(decision="CONSENTED"),
            bundle["applicant_headers"],
        )
        after = validate_success(res)
        assert after["applicant_consent"] == "CONSENTED"
        snapshot = get_lc(lc["id"], bundle["applicant_headers"])
        assert snapshot["amendment_consent_status"] == "PENDING_BENEFICIARY"

    def test_applicant_rejection_resets_lc_to_none(self, api):
        """PRD §3.4: 'a REJECTED decision sets applicant_consent to
        REJECTED, the row's status to REJECTED, rejected_by_role to
        APPLICANT, and resets the LC's amendment_consent_status to NONE
        so a fresh amendment may begin.'"""
        lc, bundle, amendment = setup_pending_amendment(
            amount_minor_units=100_000,
        )
        res = api.applicant_consent(
            lc["id"], amendment["id"],
            consent_payload(decision="REJECTED"),
            bundle["applicant_headers"],
        )
        after = validate_success(res)
        assert after["applicant_consent"] == "REJECTED"
        assert after["status"] == "REJECTED"
        assert after["rejected_by_role"] == "APPLICANT", (
            "PRD §3.4: 'rejected_by_role to APPLICANT'"
        )
        snapshot = get_lc(lc["id"], bundle["applicant_headers"])
        assert snapshot["amendment_consent_status"] == "NONE", (
            "PRD §3.4: 'resets the LC's amendment_consent_status to NONE'"
        )

    def test_beneficiary_consent_before_applicant_rejected(self, api):
        """PRD §3.4: 'Beneficiary or confirming-bank consent attempts
        before the applicant has consented are rejected with
        ERR_AMENDMENT_CONSENT_OUT_OF_ORDER'."""
        lc, bundle, amendment = setup_pending_amendment(
            amount_minor_units=100_000,
        )
        res = api.beneficiary_consent(
            lc["id"], amendment["id"],
            consent_payload(decision="CONSENTED"),
            bundle["beneficiary_headers"],
        )
        validate_error(res, "ERR_AMENDMENT_CONSENT_OUT_OF_ORDER")

    def test_consent_on_already_decided_amendment_rejected(self, api):
        """PRD §3.4: 'any consent attempt on a row whose status is no
        longer PENDING is rejected with ERR_AMENDMENT_ALREADY_DECIDED.'"""
        lc, bundle, amendment = setup_pending_amendment(
            amount_minor_units=100_000,
        )
        # Reject — terminal status.
        applicant_consent_amendment(
            lc["id"], amendment["id"], bundle["applicant_headers"],
            decision="REJECTED",
        )
        # Second attempt.
        res = api.applicant_consent(
            lc["id"], amendment["id"],
            consent_payload(decision="CONSENTED"),
            bundle["applicant_headers"],
        )
        validate_error(res, "ERR_AMENDMENT_ALREADY_DECIDED")

    def test_full_consent_chain_no_confirming_bank_merges_changes(self, api):
        """PRD §3.4: 'PENDING_BENEFICIARY → CONSENTED ... if there is no
        confirming bank ... When all required consents are collected, the
        system automatically moves the LcAmendment from PENDING to
        CONSENTED, sets applied_at to the current server clock, and
        resets the LC's amendment_consent_status to NONE. As part of
        the same transaction it merges every field of changes into the
        parent LC row.'"""
        lc, bundle, amendment = setup_pending_amendment(
            amount_minor_units=100_000,
            confirmation_required=False,
            changes={"amount_minor_units": 250_000},
        )
        # Applicant consents.
        applicant_consent_amendment(
            lc["id"], amendment["id"], bundle["applicant_headers"],
            decision="CONSENTED",
        )
        # Beneficiary consents — no confirming bank, so cycle finishes.
        res = api.beneficiary_consent(
            lc["id"], amendment["id"],
            consent_payload(decision="CONSENTED"),
            bundle["beneficiary_headers"],
        )
        validate_success(res)
        # LC now reflects the merged amount.
        snapshot = get_lc(lc["id"], bundle["applicant_headers"])
        assert snapshot["amount_minor_units"] == 250_000, (
            "PRD §3.4: 'it merges every field of changes into the parent "
            "LC row'"
        )
        assert snapshot["amendment_consent_status"] == "NONE", (
            "PRD §3.4: 'resets the LC's amendment_consent_status to NONE'"
        )

    def test_confirming_bank_required_when_lc_has_confirming(self, api):
        """PRD §3.4: 'a CONSENTED decision flips beneficiary_consent and
        the LC's amendment_consent_status advances to
        PENDING_CONFIRMING_BANK if the LC has a confirming_bank_id'."""
        lc, bundle, amendment = setup_pending_amendment(
            amount_minor_units=100_000,
            confirmation_required=True,
        )
        applicant_consent_amendment(
            lc["id"], amendment["id"], bundle["applicant_headers"],
            decision="CONSENTED",
        )
        res = api.beneficiary_consent(
            lc["id"], amendment["id"],
            consent_payload(decision="CONSENTED"),
            bundle["beneficiary_headers"],
        )
        after = validate_success(res)
        snapshot = get_lc(lc["id"], bundle["applicant_headers"])
        assert snapshot["amendment_consent_status"] == "PENDING_CONFIRMING_BANK"


# ===========================================================================
# §3.4 — Withdrawal
# ===========================================================================
class TestWithdrawal:

    def test_withdraw_before_applicant_consent_succeeds(self, api):
        """PRD §3.4: 'Withdrawal is also possible: the IssuingBank may
        withdraw a PENDING amendment, but only before the applicant has
        consented ... Withdrawal moves the row to WITHDRAWN and resets
        amendment_consent_status to NONE.'"""
        lc, bundle, amendment = setup_pending_amendment(
            amount_minor_units=100_000,
        )
        res = api.withdraw_amendment(
            lc["id"], amendment["id"], bundle["issuing_bank_headers"],
        )
        after = validate_success(res)
        assert after["status"] == "WITHDRAWN"
        snapshot = get_lc(lc["id"], bundle["applicant_headers"])
        assert snapshot["amendment_consent_status"] == "NONE"

    def test_withdraw_after_applicant_consent_rejected(self, api):
        """PRD §3.4: 'once applicant_consent is CONSENTED, withdrawal is
        no longer permitted.'"""
        lc, bundle, amendment = setup_pending_amendment(
            amount_minor_units=100_000,
        )
        applicant_consent_amendment(
            lc["id"], amendment["id"], bundle["applicant_headers"],
            decision="CONSENTED",
        )
        res = api.withdraw_amendment(
            lc["id"], amendment["id"], bundle["issuing_bank_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE_TRANSITION")
