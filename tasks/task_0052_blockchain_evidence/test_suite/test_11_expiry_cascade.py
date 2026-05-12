"""Expiry sweep, certificate revocation cascade, judicial draft rejection.

PRD §3.4, §2.10 priority 15.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    bring_evidence_to_confirmed,
    create_certificate,
    create_judicial_package,
    get_evidence,
    iso_z,
    make_customer_headers,
    run_sweep,
    setup_sealed_judicial_package,
    validate_error,
    validate_success,
)


# ===========================================================================
# Sweep flips CONFIRMED → EXPIRED (PRD §3.4)
# ===========================================================================
class TestExpirySweep:
    """PRD §3.4: 'A PlatformAdmin runs the expiry sweep capability,
    which advances every CONFIRMED evidence whose expires_at is at or
    before the server's current time into the terminal EXPIRED state.'"""

    def test_sweep_after_expiry_moves_to_expired(self, api):
        """PRD §3.4: 'every CONFIRMED evidence whose expires_at is at
        or before the server's current time into the terminal EXPIRED
        state.' DOCUMENT/30 → expires 30 days after confirmed_at."""
        customer, ev = bring_evidence_to_confirmed(
            balance_cents=1_000,
            evidence_overrides={
                "evidence_type": "DOCUMENT", "storage_period_days": 30,
            },
        )
        # ev["confirmed_at"] is set by the server. Advance clock past it.
        confirmed_at = datetime.fromisoformat(
            ev["confirmed_at"].replace("Z", "+00:00"),
        )
        past_expiry = confirmed_at + timedelta(days=31)
        advance_clock(iso_z(past_expiry))
        run_sweep()
        ev_after = get_evidence(ev["id"])
        assert ev_after["status"] == "EXPIRED"


# ===========================================================================
# Cascade: Evidence EXPIRED → Certificate REVOKED (PRD §3.4)
# ===========================================================================
class TestCertificateRevocationCascade:
    """PRD §3.4: 'Two cascades fire from this transition. The evidence's
    linked Certificate, if any, flips to REVOKED'.

    Also exercises difficulty-design
    'clock_advance_triggers_evidence_expiry_then_certificate_revocation'.
    """

    def test_certificate_revoked_when_evidence_expires(self, api,
                                                       admin_headers):
        """PRD §3.4: 'The evidence's linked Certificate, if any, flips
        to REVOKED'."""
        customer, ev = bring_evidence_to_confirmed(
            balance_cents=5_000,
            evidence_overrides={
                "evidence_type": "DOCUMENT", "storage_period_days": 30,
            },
        )
        cert = create_certificate(ev)
        confirmed_at = datetime.fromisoformat(
            ev["confirmed_at"].replace("Z", "+00:00"),
        )
        advance_clock(iso_z(confirmed_at + timedelta(days=31)))
        run_sweep()
        # Read back evidence and certificate.
        ev_after = get_evidence(ev["id"])
        assert ev_after["status"] == "EXPIRED"
        cert_after = validate_success(api.get_certificate(
            cert["id"], make_customer_headers(customer["id"]),
        ), 200)
        assert cert_after["status"] == "REVOKED"


# ===========================================================================
# Cascade: DRAFT JudicialPackage → REJECTED (PRD §3.4)
# ===========================================================================
class TestJudicialDraftRejection:
    """PRD §3.4: 'Any JudicialPackage whose evidence_id matches and
    whose status is still DRAFT flips to REJECTED — no fee refund is
    issued because no fee has been debited for a DRAFT package yet.'

    Difficulty-design instance
    'judicial_draft_rejection_preserves_judicial_surcharge_total_invariant'.
    """

    def test_draft_package_rejected_on_expiry(self, api):
        """PRD §3.4: 'Any JudicialPackage whose evidence_id matches and
        whose status is still DRAFT flips to REJECTED'."""
        customer, ev = bring_evidence_to_confirmed(
            balance_cents=100_000,
            evidence_overrides={
                "evidence_type": "DOCUMENT", "storage_period_days": 30,
            },
        )
        create_certificate(ev)
        pkg = create_judicial_package(ev)  # DRAFT, not sealed
        confirmed_at = datetime.fromisoformat(
            ev["confirmed_at"].replace("Z", "+00:00"),
        )
        advance_clock(iso_z(confirmed_at + timedelta(days=31)))
        run_sweep()
        from test_helpers.fixtures import JUDICIAL
        pkg_after = validate_success(api.get_judicial_package(
            pkg["id"], JUDICIAL,
        ), 200)
        assert pkg_after["status"] == "REJECTED"


# ===========================================================================
# Expired evidence rejects certificate download & judicial preparation
# ===========================================================================
class TestExpiredEvidenceBlocking:
    """PRD §2.10 priority 15: 'Certificate download and judicial-package
    creation are rejected once Evidence.expires_at has passed
    (ERR_EVIDENCE_EXPIRED). Verification itself is still permitted
    after expiry and returns a VerificationReport whose outcome is
    EXPIRED.'"""

    def test_certificate_download_after_expiry_rejected(self, api):
        """PRD §2.10 priority 15: 'Certificate download ... rejected
        once Evidence.expires_at has passed (ERR_EVIDENCE_EXPIRED).'"""
        customer, ev = bring_evidence_to_confirmed(balance_cents=5_000)
        cert = create_certificate(ev)
        confirmed_at = datetime.fromisoformat(
            ev["confirmed_at"].replace("Z", "+00:00"),
        )
        advance_clock(iso_z(confirmed_at + timedelta(days=31)))
        run_sweep()
        res = api.download_certificate(
            cert["id"],
            make_customer_headers(customer["id"]),
            params={"format": "pdf"},
        )
        validate_error(res, ApiErrorId.ERR_EVIDENCE_EXPIRED.value)

    def test_judicial_prep_after_expiry_rejected(self, api):
        """PRD §3.7: 'Preparing a package against an evidence whose
        expires_at has passed is rejected with ERR_EVIDENCE_EXPIRED.'"""
        from test_helpers import create_judicial_package_payload
        from test_helpers.fixtures import JUDICIAL
        customer, ev = bring_evidence_to_confirmed(balance_cents=5_000)
        confirmed_at = datetime.fromisoformat(
            ev["confirmed_at"].replace("Z", "+00:00"),
        )
        advance_clock(iso_z(confirmed_at + timedelta(days=31)))
        run_sweep()
        res = api.create_judicial_package(
            create_judicial_package_payload(
                evidence_id=ev["id"], authority_code="COURT_BJ",
            ),
            JUDICIAL,
        )
        validate_error(res, ApiErrorId.ERR_EVIDENCE_EXPIRED.value)

    def test_verification_after_expiry_returns_expired_outcome(self, api):
        """PRD §3.8: 'EXPIRED when the evidence's expires_at has passed
        (verification is still permitted after expiry — only certificate
        downloads and judicial preparation are blocked — so verification
        of an expired evidence runs to completion and returns this
        outcome)'."""
        from test_helpers import create_verification_payload
        customer, ev = bring_evidence_to_confirmed(balance_cents=5_000)
        confirmed_at = datetime.fromisoformat(
            ev["confirmed_at"].replace("Z", "+00:00"),
        )
        advance_clock(iso_z(confirmed_at + timedelta(days=31)))
        run_sweep()
        res = api.create_verification(
            create_verification_payload(
                evidence_id=ev["id"], file_hash=ev["file_hash"],
            ),
            make_customer_headers(customer["id"]),
        )
        report = validate_success(res, 201)
        assert report["outcome"] == "EXPIRED"
