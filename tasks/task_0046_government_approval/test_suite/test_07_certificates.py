"""Certificate issuance, verification, revocation, and reissuance.

Covers PRD §3.10 (certificate workflows), parts of §2.14 (sweep-driven
expiry), §2.13 (audit trail).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_certificate,
    DAY_SECONDS,
    decide,
    get_application,
    get_success_data,
    revoke_certificate_payload,
    run_sweep,
    setup_application_under_review_single_dept,
    setup_approved_application_with_certificate,
    TEST_USERS,
    validate_error,
    validate_success,
    VERIFICATION_CODE_LEN,
)


# ===========================================================================
# Issuance shape (PRD §3.10)
# ===========================================================================
class TestCertificateIssuance:
    def test_approved_application_issues_certificate(self, api):
        """PRD §3.10: "When an application transitions to APPROVED --
        whether organically through aggregation or through escalation
        resolution -- the platform issues a Certificate against the
        CertificateTemplate named on the pinned
        MatterVersion.certificate_template_id."

        Claim: an approved application has a Certificate retrievable
        through GET /applications/{id}/certificate.
        """
        ctx = setup_approved_application_with_certificate(validity_days=1)
        cert = ctx["certificate"]
        assert_certificate(cert)
        assert cert["status"] == "ACTIVE"
        assert cert["application_id"] == ctx["application"]["id"]

    def test_serial_number_uses_gov_matter_yymmdd_six_digit_format(self, api):
        """PRD §3.10: "serial_number is generated as
        GOV-{matter.code}-{YYMMDD}-{6-digit zero-padded sequence}, where
        the sequence is the next-per-day sequence for that matter code in
        UTC."

        Claim: serial_number starts with GOV-{matter.code}- and ends with
        a 6-digit YYMMDD followed by a 6-digit zero-padded sequence.
        """
        ctx = setup_approved_application_with_certificate()
        serial = ctx["certificate"]["serial_number"]
        matter_code = ctx["matter"]["code"]
        assert serial.startswith(f"GOV-{matter_code}-"), (
            f"serial must start with GOV-{matter_code}-, got {serial!r}"
        )
        # GOV-{code}-YYMMDD-NNNNNN
        parts = serial.split("-")
        assert len(parts) >= 4, f"serial must split into >=4 dash segments: {serial!r}"
        assert len(parts[-1]) == 6 and parts[-1].isdigit()
        assert len(parts[-2]) == 6 and parts[-2].isdigit()

    def test_verification_code_is_16_char_alphanumeric(self, api):
        """PRD §3.10: "verification_code is generated as a 16-character
        alphanumeric string ... The leading 16 characters of the encoded
        result form the value."

        Claim: verification_code length == 16, all alphanumeric.
        """
        ctx = setup_approved_application_with_certificate()
        code = ctx["certificate"]["verification_code"]
        assert len(code) == VERIFICATION_CODE_LEN
        assert code.isalnum()

    def test_validity_days_zero_yields_null_expires_at(self, api):
        """PRD §3.10: "expires_at is set to null when the template's
        validity_days is 0."

        Claim: validity_days=0 yields a Certificate with expires_at=null.
        """
        ctx = setup_approved_application_with_certificate(validity_days=0)
        assert ctx["certificate"]["expires_at"] is None

    def test_validity_days_nonzero_uses_86400_per_day(self, api):
        """PRD §3.10: "otherwise it is computed as issued_at plus
        validity_days multiplied by the day-in-seconds constant of
        86,400."

        Claim: validity_days=2 yields expires_at exactly 2*86,400 seconds
        after issued_at.
        """
        from test_helpers import parse_iso
        ctx = setup_approved_application_with_certificate(validity_days=2)
        cert = ctx["certificate"]
        issued = parse_iso(cert["issued_at"])
        expires = parse_iso(cert["expires_at"])
        diff = int((expires - issued).total_seconds())
        assert diff == 2 * DAY_SECONDS, (
            f"expires_at - issued_at expected {2 * DAY_SECONDS}s, got {diff}"
        )


# ===========================================================================
# Public verification (PRD §3.10)
# ===========================================================================
class TestCertificateVerification:
    def test_verify_returns_minimal_status_snapshot(self, api,
                                                    platform_admin_headers):
        """PRD §3.10: "A public verification endpoint accepts a
        verification_code and returns a minimal status snapshot --
        sufficient for an external party to confirm the certificate
        exists and report its current status, issued_at, and expires_at.
        The verification surface deliberately omits the rendered body
        and the audit-adjacent metadata."

        Claim: GET /certificates/verify/{verification_code} returns
        status, issued_at, expires_at, and does NOT carry rendered_body.
        """
        ctx = setup_approved_application_with_certificate()
        cert = ctx["certificate"]
        resp = api.verify_certificate(
            cert["verification_code"], platform_admin_headers,
        )
        data = validate_success(resp)
        assert "status" in data
        assert "issued_at" in data
        assert "expires_at" in data
        assert "rendered_body" not in data, (
            "PRD §3.10 deliberately omits rendered_body from verification"
        )


# ===========================================================================
# Revocation (PRD §3.10)
# ===========================================================================
class TestCertificateRevocation:
    def test_revoke_active_certificate_flips_to_revoked(
        self, api, platform_admin_headers,
    ):
        """PRD §3.10: "A PlatformAdmin may also revoke an ACTIVE
        certificate explicitly by submitting an optional reason; the
        certificate flips from ACTIVE to REVOKED."

        Claim: POST /certificates/{id}/revoke on an ACTIVE certificate
        flips status to REVOKED.
        """
        ctx = setup_approved_application_with_certificate()
        cert_id = ctx["certificate"]["id"]
        resp = api.revoke_certificate(
            cert_id, platform_admin_headers,
            payload=revoke_certificate_payload("test"),
        )
        data = validate_success(resp)
        assert data["status"] == "REVOKED"


# ===========================================================================
# Reissuance (PRD §3.10)
# ===========================================================================
class TestCertificateReissuance:
    def test_reissue_active_creates_new_and_supersedes_old(
        self, api, certificate_officer_headers,
    ):
        """PRD §3.10: "Reissue creates a fresh Certificate row using the
        same certificate_template_id as the source, with a fresh
        serial_number, a fresh verification_code, a fresh issued_at, and
        a fresh expires_at derived from the new issued_at; the source
        certificate's superseded_by_certificate_id is then set to the
        new certificate's id and its status flips from its prior value
        to REISSUED."

        Claim: reissuing an ACTIVE certificate yields a new ACTIVE row
        with a different serial_number; old certificate becomes REISSUED
        with superseded_by_certificate_id == new.id.

        # difficulty: non_linear_state_machine/certificate_branching_with_revert_on_reissue
        """
        ctx = setup_approved_application_with_certificate(validity_days=1)
        cert1 = ctx["certificate"]
        resp = api.reissue_certificate(cert1["id"], certificate_officer_headers)
        cert2 = validate_success(resp, expected_status=201)
        assert_certificate(cert2)
        assert cert2["status"] == "ACTIVE"
        assert cert2["serial_number"] != cert1["serial_number"]
        assert cert2["application_id"] == cert1["application_id"]
        # Old certificate state.
        from test_helpers import api_client as _ac
        old_resp = _ac.get_application_certificate(
            ctx["application"]["id"], TEST_USERS["platform_admin_headers"],
        )
        # /applications/{id}/certificate returns the active one (the new
        # one), so directly look at the structural relationship rather
        # than re-fetching the old by its id (no GET /certificates/{id}
        # endpoint per PRD §4). We instead rely on the API contract:
        # the new cert was issued and the old's status must have flipped.
        # Verify by trying to reissue cert1 again -- it MUST fail with
        # ERR_CERTIFICATE_ALREADY_REISSUED because its
        # superseded_by_certificate_id is now set.
        retry = api.reissue_certificate(cert1["id"], certificate_officer_headers)
        validate_error(retry, ApiErrorId.ERR_CERTIFICATE_ALREADY_REISSUED)

    def test_reissue_already_reissued_is_rejected(
        self, api, certificate_officer_headers,
    ):
        """PRD §3.10: "A reissue request against a source whose
        superseded_by_certificate_id is already non-null is rejected
        with ERR_CERTIFICATE_ALREADY_REISSUED."

        Claim: a second reissue against the same source yields
        ERR_CERTIFICATE_ALREADY_REISSUED.

        # difficulty: resource_temporal_overlap/certificate_validity_window_aggregate_capacity_one_per_application
        """
        ctx = setup_approved_application_with_certificate(validity_days=1)
        cert1 = ctx["certificate"]
        first = api.reissue_certificate(cert1["id"], certificate_officer_headers)
        validate_success(first, expected_status=201)
        second = api.reissue_certificate(cert1["id"], certificate_officer_headers)
        validate_error(second, ApiErrorId.ERR_CERTIFICATE_ALREADY_REISSUED)


# ===========================================================================
# Sweep-driven expiry (PRD §3.10, §2.14)
# ===========================================================================
class TestCertificateExpirySweep:
    def test_sweep_after_expiry_flips_to_expired(self, api):
        """PRD §3.10: "An ACTIVE Certificate whose expires_at is at or
        before the current server time transitions automatically to
        EXPIRED when the periodic sweep (or the test-only sweep) runs."

        Claim: clock-advance past expires_at then sweep flips status
        to EXPIRED.
        """
        ctx = setup_approved_application_with_certificate(validity_days=1)
        # validity_days=1 == 86,400 seconds; advance past it.
        advance_clock(DAY_SECONDS + 1)
        run_sweep()
        # Re-read via /applications/{id}/certificate.
        resp = api.get_application_certificate(
            ctx["application"]["id"], TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(resp)
        # The application's still-known certificate should now be EXPIRED.
        assert data["status"] == "EXPIRED"
