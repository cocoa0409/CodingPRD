"""ReducedFareCertificate and LowIncomeVerification — PRD §3.2, §3.3.

Covers PENDING → ACTIVE approval rules, REVOKED transitions, window
overlap enforcement, declared-vs-verified income comparison, threshold
boundary, and the cascade onto FareCard.discount_class.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to_iso,
    approve_low_income_verification_payload,
    create_active_low_income_verification,
    create_active_reduced_fare_certificate,
    create_low_income_verification_payload,
    create_pending_reduced_fare_certificate,
    create_reduced_fare_certificate_payload,
    create_rider,
    get_card,
    get_rider,
    issue_card,
    make_rider_headers,
    setup_rider_with_low_income_card,
    setup_rider_with_reduced_fare_card,
    validate_error,
    validate_success,
)


# ===========================================================================
# Reduced-fare certificate lifecycle
# ===========================================================================
class TestReducedFareCertificateLifecycle:

    def test_create_certificate_is_pending(
            self, api, agency_officer_headers):
        """PRD §3.2: "A newly created certificate starts in `status`
        `PENDING`."

        Claim: a fresh certificate is in PENDING."""
        rider = create_rider()
        payload = create_reduced_fare_certificate_payload(
            rider_id=rider["id"], program_type="SENIOR",
        )
        resp = api.create_reduced_fare_certificate(
            payload, agency_officer_headers,
        )
        cert = validate_success(resp, expected_status=201)
        assert cert["status"] == "PENDING"

    def test_approve_pending_certificate_to_active(
            self, api, agency_officer_headers):
        """PRD §3.2: "Approval by an `AgencyOfficer` is permitted only
        while the certificate is in `PENDING` and only while its
        `valid_until` lies strictly after the current server time;
        success transitions it to `ACTIVE`."

        Claim: approving a PENDING certificate whose valid_until is in
        the future transitions it to ACTIVE."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider = create_rider()
        cert = create_pending_reduced_fare_certificate(
            rider_id=rider["id"],
            valid_from="2026-01-01T00:00:00.000Z",
            valid_until="2027-01-01T00:00:00.000Z",
        )
        resp = api.approve_reduced_fare_certificate(
            cert["id"], agency_officer_headers,
        )
        approved = validate_success(resp, expected_status=200)
        assert approved["status"] == "ACTIVE"

    def test_approve_non_pending_certificate_rejected(
            self, api, agency_officer_headers):
        """PRD §3.2: "Approval by an `AgencyOfficer` is permitted only
        while the certificate is in `PENDING`"; PRD §2.11: "state-
        eligibility of the target resource for the requested operation
        ... (rejection: `ERR_INVALID_STATE`)".

        Claim: approving an already-ACTIVE certificate → ERR_INVALID_STATE."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider = create_rider()
        cert = create_active_reduced_fare_certificate(
            rider_id=rider["id"], program_type="SENIOR",
        )
        # Second approve attempt against an ACTIVE certificate.
        resp = api.approve_reduced_fare_certificate(
            cert["id"], agency_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_certificate_window_overlap_rejected_on_create(
            self, api, agency_officer_headers):
        """PRD §3.2: "two certificates of the same `program_type` for
        the same rider may not have overlapping `[valid_from,
        valid_until]` windows."

        Claim: a second certificate that overlaps an existing ACTIVE
        certificate of the same (rider, program_type) is rejected with
        ERR_CERTIFICATE_WINDOW_OVERLAP."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider = create_rider()
        _cert1 = create_active_reduced_fare_certificate(
            rider_id=rider["id"], program_type="SENIOR",
            valid_from="2026-01-01T00:00:00.000Z",
            valid_until="2026-12-31T23:59:59.000Z",
        )
        # Overlap on [2026-06-01, 2026-12-31].
        overlap_payload = create_reduced_fare_certificate_payload(
            rider_id=rider["id"], program_type="SENIOR",
            valid_from="2026-06-01T00:00:00.000Z",
            valid_until="2027-06-01T00:00:00.000Z",
        )
        # Per scaffold: the check happens on either create or approve.
        # PRD permits either; we accept the create path being rejected,
        # OR a create that succeeds then approve being rejected. To be
        # PRD-faithful (two-reader test), only assert the named error
        # in the overlap scenario; accept which call surfaces it.
        from prd_bench_local_runner.testing import (
            get_success_data, validate_error,
        )
        resp = api.create_reduced_fare_certificate(
            overlap_payload, agency_officer_headers,
        )
        if 200 <= resp.status_code < 300:
            cert2 = resp.json()["data"]
            approve_resp = api.approve_reduced_fare_certificate(
                cert2["id"], agency_officer_headers,
            )
            validate_error(
                approve_resp,
                ApiErrorId.ERR_CERTIFICATE_WINDOW_OVERLAP.value,
            )
        else:
            validate_error(
                resp,
                ApiErrorId.ERR_CERTIFICATE_WINDOW_OVERLAP.value,
            )

    def test_revoke_active_certificate_to_revoked(
            self, api, agency_officer_headers):
        """PRD §3.2: "Revocation by an `AgencyOfficer` is permitted
        only while the certificate is in `ACTIVE`; success transitions
        it to terminal `REVOKED`."

        Claim: revoke on an ACTIVE certificate moves it to REVOKED."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider = create_rider()
        cert = create_active_reduced_fare_certificate(
            rider_id=rider["id"], program_type="SENIOR",
        )
        resp = api.revoke_reduced_fare_certificate(
            cert["id"], agency_officer_headers,
        )
        revoked = validate_success(resp, expected_status=200)
        assert revoked["status"] == "REVOKED"

    def test_revoke_cascades_card_downgrade(
            self, api, agency_officer_headers):
        """PRD §3.2: "for each `FareCard` owned by the rider whose
        `discount_class` is `REDUCED_FARE` and that has no other
        `ACTIVE` certificate of any `program_type` covering the
        current moment, the card's `discount_class` is downgraded to
        `STANDARD`."

        Claim: revoking the only ACTIVE certificate on a rider
        downgrades their REDUCED_FARE card to STANDARD."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, cert, card = setup_rider_with_reduced_fare_card(
            topup_cents=0,
        )
        assert card["discount_class"] == "REDUCED_FARE"
        resp = api.revoke_reduced_fare_certificate(
            cert["id"], agency_officer_headers,
        )
        validate_success(resp, expected_status=200)
        # Re-read the card.
        refreshed = get_card(card["id"])
        assert refreshed["discount_class"] == "STANDARD", (
            "Card discount_class must downgrade to STANDARD after the "
            "only ACTIVE certificate is revoked; got "
            f"{refreshed['discount_class']!r}"
        )


# ===========================================================================
# Low-income verification — declared vs verified
# ===========================================================================
class TestLowIncomeVerification:

    def test_create_returns_pending_with_null_verified(
            self, api, agency_officer_headers):
        """PRD §3.3: "the record starts in `status` `PENDING` with
        `verified_annual_income_cents` null and `approved_at` null."

        Claim: a fresh verification has status=PENDING,
        verified_annual_income_cents=null, approved_at=null."""
        rider = create_rider()
        h = make_rider_headers(rider["id"])
        resp = api.create_low_income_verification(
            create_low_income_verification_payload(
                rider_id=rider["id"],
                declared_annual_income_cents=2_500_000,
            ),
            h,
        )
        v = validate_success(resp, expected_status=201)
        assert v["status"] == "PENDING"
        assert v.get("verified_annual_income_cents") is None
        assert v.get("approved_at") is None

    def test_approve_with_verified_at_threshold_active(
            self, api, agency_officer_headers):
        """PRD §3.3: "The threshold for eligibility is three million
        cents (that is, thirty thousand US dollars), and the comparison
        is inclusive: a verified income that is at most three million
        cents qualifies. If the verified income satisfies the threshold
        and the verification is still in `PENDING`, the record
        transitions to `ACTIVE`, `approved_at` is written to the
        server clock, the rider's `low_income_verified` is set to
        true."

        Claim: at the boundary verified=3_000_000 the verification
        transitions to ACTIVE, and the rider's low_income_verified
        flips to true."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider = create_rider()
        rh = make_rider_headers(rider["id"])
        v = validate_success(
            api.create_low_income_verification(
                create_low_income_verification_payload(
                    rider_id=rider["id"],
                    declared_annual_income_cents=2_500_000,
                ), rh,
            ),
            expected_status=201,
        )
        approved = validate_success(
            api.approve_low_income_verification(
                v["id"],
                approve_low_income_verification_payload(
                    verified_annual_income_cents=3_000_000,
                ),
                agency_officer_headers,
            ),
            expected_status=200,
        )
        assert approved["status"] == "ACTIVE"
        assert approved["verified_annual_income_cents"] == 3_000_000
        # Rider's low_income_verified must be true.
        refreshed = get_rider(rider["id"], headers=rh)
        assert refreshed["low_income_verified"] is True

    def test_approve_with_verified_above_threshold_rejected(
            self, api, agency_officer_headers):
        """PRD §3.3: "If the verified income exceeds the threshold and
        the verification is still in `PENDING`, the record transitions
        to terminal `REJECTED` and the rider's `low_income_verified`
        remains false."

        Claim: verified=3_000_001 transitions to REJECTED with
        rider.low_income_verified unchanged at false."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider = create_rider()
        rh = make_rider_headers(rider["id"])
        v = validate_success(
            api.create_low_income_verification(
                create_low_income_verification_payload(
                    rider_id=rider["id"],
                    declared_annual_income_cents=2_500_000,
                ), rh,
            ),
            expected_status=201,
        )
        result = validate_success(
            api.approve_low_income_verification(
                v["id"],
                approve_low_income_verification_payload(
                    verified_annual_income_cents=3_000_001,
                ),
                agency_officer_headers,
            ),
            expected_status=200,
        )
        assert result["status"] == "REJECTED"
        refreshed = get_rider(rider["id"], headers=rh)
        assert refreshed["low_income_verified"] is False, (
            "low_income_verified must remain false after rejection"
        )
