"""Forensic verification reports.

PRD §3.8, §2.10 priority 15.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_verification_report,
    bring_evidence_to_confirmed,
    create_certificate,
    create_verification_payload,
    make_customer_headers,
    random_sha256_hex,
    validate_error,
    validate_success,
)


# ===========================================================================
# Forensic verification (PRD §3.8)
# ===========================================================================
class TestVerificationOutcomes:
    """PRD §3.8: 'The outcome is exactly one of five enumerated values:
    VERIFIED when the hashes match, the certificate is ISSUED, and the
    chain proof verifies; TAMPERED when the recomputed and on-chain
    hashes diverge or the chain proof fails ... REVOKED when the linked
    certificate is REVOKED but the underlying hashes still match;
    UNAVAILABLE when on-chain data cannot be read back.'

    PRD §3.8: 'tamper_detected is true when recomputed_hash is not
    equal to on_chain_hash or when the chain proof fails to verify'.
    """

    def test_verified_outcome_matching_hash_issued_cert(self, api):
        """PRD §3.8: 'VERIFIED when the hashes match, the certificate
        is ISSUED, and the chain proof verifies.'"""
        customer, ev = bring_evidence_to_confirmed()
        create_certificate(ev)
        res = api.create_verification(
            create_verification_payload(
                evidence_id=ev["id"],
                file_hash=ev["file_hash"],
            ),
            make_customer_headers(customer["id"]),
        )
        report = validate_success(res, 201)
        assert_verification_report(report)
        assert report["outcome"] == "VERIFIED"
        assert report["tamper_detected"] is False
        assert report["certificate_valid"] is True

    def test_tampered_outcome_when_hash_diverges(self, api):
        """PRD §3.8: 'TAMPERED when the recomputed and on-chain hashes
        diverge'."""
        customer, ev = bring_evidence_to_confirmed()
        create_certificate(ev)
        # Submit a different hash to trigger tamper detection.
        wrong_hash = random_sha256_hex()
        assert wrong_hash != ev["file_hash"]
        res = api.create_verification(
            create_verification_payload(
                evidence_id=ev["id"],
                file_hash=wrong_hash,
            ),
            make_customer_headers(customer["id"]),
        )
        report = validate_success(res, 201)
        assert report["outcome"] == "TAMPERED"
        assert report["tamper_detected"] is True

    def test_revoked_outcome_when_cert_revoked_but_hash_matches(self, api,
                                                                admin_headers):
        """PRD §3.8: 'REVOKED when the linked certificate is REVOKED
        but the underlying hashes still match'."""
        customer, ev = bring_evidence_to_confirmed()
        cert = create_certificate(ev)
        validate_success(
            api.revoke_certificate(cert["id"], admin_headers), 200,
        )
        res = api.create_verification(
            create_verification_payload(
                evidence_id=ev["id"], file_hash=ev["file_hash"],
            ),
            make_customer_headers(customer["id"]),
        )
        report = validate_success(res, 201)
        assert report["outcome"] == "REVOKED"
