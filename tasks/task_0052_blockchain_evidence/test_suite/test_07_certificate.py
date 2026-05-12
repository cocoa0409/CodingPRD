"""Certificate issuance, download, and admin revocation.

PRD §3.6, §2.10 priority 7/15.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_certificate,
    bring_evidence_to_confirmed,
    create_certificate,
    create_certificate_payload,
    create_customer_with_balance,
    create_evidence,
    create_notarization,
    make_customer_headers,
    list_audit_logs,
    validate_error,
    validate_success,
)


# ===========================================================================
# Issuance preconditions (priority 7)
# ===========================================================================
class TestCertificateIssuance:
    """PRD §3.6: 'Once an evidence reaches CONFIRMED, a Customer (or,
    for administrative replays, a PlatformAdmin) issues a Certificate
    against it ... Issuance against a non-CONFIRMED evidence is rejected
    with ERR_EVIDENCE_NOT_CONFIRMED.'

    PRD §2.10 priority 7: 'Linked Evidence.status is CONFIRMED on
    POST /certificates and on POST /judicial-packages/{id}/seal'.
    """

    def test_issue_against_pending_evidence_rejected(self, api):
        """PRD §2.10 priority 7: 'Linked Evidence.status is CONFIRMED on
        POST /certificates ... (ERR_EVIDENCE_NOT_CONFIRMED).'"""
        customer = create_customer_with_balance(balance_cents=0)
        evidence = create_evidence(customer)
        res = api.create_certificate(
            create_certificate_payload(evidence_id=evidence["id"]),
            make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_EVIDENCE_NOT_CONFIRMED.value)

    def test_issue_against_confirmed_evidence_succeeds(self, api):
        customer, ev = bring_evidence_to_confirmed()
        res = api.create_certificate(
            create_certificate_payload(
                evidence_id=ev["id"], template_code="STANDARD",
            ),
            make_customer_headers(customer["id"]),
        )
        cert = validate_success(res, 201)
        assert_certificate(cert)
        assert cert["evidence_id"] == ev["id"]
        assert cert["template_code"] == "STANDARD"
        assert cert["status"] == "ISSUED"

    def test_certificate_embeds_hash_snapshot_and_chain(self, api):
        """PRD §3.6: 'hash_snapshot copied from Evidence.file_hash at
        issuance time' / 'chain_id copied from the evidence'."""
        customer, ev = bring_evidence_to_confirmed()
        cert = create_certificate(ev)
        assert cert["hash_snapshot"] == ev["file_hash"]
        assert cert["chain_id"] == ev["chain_id"]

    def test_certificate_appends_audit(self, api):
        """PRD §3.6: 'an audit row of type CERTIFICATE_ISSUED.'"""
        customer, ev = bring_evidence_to_confirmed()
        cert = create_certificate(ev)
        rows = list_audit_logs(
            event_type="CERTIFICATE_ISSUED",
            target_entity="Certificate",
            target_id=cert["id"],
        )
        assert len(rows) >= 1


# ===========================================================================
# Verification code format (PRD §3.6)
# ===========================================================================
class TestVerificationCodeFormat:
    """PRD §3.6: 'verification_code (a 12-character uppercase
    alphanumeric handle, globally unique, suitable for a public
    verification UI)'."""

    def test_verification_code_is_12_uppercase_alnum(self, api):
        customer, ev = bring_evidence_to_confirmed()
        cert = create_certificate(ev)
        vc = cert["verification_code"]
        assert len(vc) == 12, f"verification_code must be 12 chars"
        assert vc.isalnum() and vc.upper() == vc


# ===========================================================================
# Download endpoint (PRD §3.6)
# ===========================================================================
class TestCertificateDownload:
    """PRD §3.6: 'The certificate may be downloaded as a format of pdf,
    png, or json. The download capability is read-only for Customer,
    JudicialOfficer, and PlatformAdmin'."""

    @pytest.mark.parametrize("fmt", ["pdf", "png", "json"])
    def test_download_each_format(self, api, fmt):
        customer, ev = bring_evidence_to_confirmed()
        cert = create_certificate(ev)
        res = api.download_certificate(
            cert["id"],
            make_customer_headers(customer["id"]),
            params={"format": fmt},
        )
        validate_success(res, 200)


# ===========================================================================
# Admin revocation (PRD §3.6)
# ===========================================================================
class TestCertificateRevocation:
    """PRD §3.6: 'an admin-only revocation capability flips the status
    from ISSUED to REVOKED directly'."""

    def test_admin_revoke_flips_status(self, api, admin_headers):
        customer, ev = bring_evidence_to_confirmed()
        cert = create_certificate(ev)
        res = api.revoke_certificate(cert["id"], admin_headers)
        revoked = validate_success(res, 200)
        assert revoked["status"] == "REVOKED"

    def test_get_after_revocation_shows_revoked(self, api,
                                                 admin_headers):
        customer, ev = bring_evidence_to_confirmed()
        cert = create_certificate(ev)
        validate_success(
            api.revoke_certificate(cert["id"], admin_headers), 200,
        )
        got = validate_success(api.get_certificate(
            cert["id"], make_customer_headers(customer["id"]),
        ), 200)
        assert got["status"] == "REVOKED"
