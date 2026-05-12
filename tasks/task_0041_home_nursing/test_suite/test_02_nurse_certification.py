"""Nurse certification lifecycle tests.

Covers PRD §3.1 (PENDING -> CERTIFIED -> EXPIRING -> CERTIFIED|PENDING|
DISQUALIFIED), §3.6 (clock-driven transitions).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_NOW_ISO,
    NurseCertificationStatus,
    TEST_USERS,
    add_days,
    advance_clock,
    api_client,
    assert_nurse,
    certify_nurse,
    create_certification_record_payload,
    create_certified_nurse,
    create_nurse_payload,
    create_nurse_raw,
    get_success_data,
    validate_error,
    validate_success,
    verify_nurse_identity,
)


class TestNurseRegistration:

    def test_new_nurse_starts_pending(self, api, platform_admin_headers):
        """PRD §3.1: 'A new nurse profile begins life with
        certification_status of PENDING, no certified_until date, and the
        boolean flags license_verified and hospital_affiliation_verified
        both false.'

        Claim: just-created Nurse has certification_status=PENDING,
        certified_until is null/None, license_verified=False,
        hospital_affiliation_verified=False.
        """
        res = api.create_nurse(
            create_nurse_payload(), platform_admin_headers
        )
        data = validate_success(res, expected_status=201)
        assert data["certification_status"] == "PENDING"
        assert data.get("certified_until") in (None, "", )
        assert data["license_verified"] is False
        assert data["hospital_affiliation_verified"] is False

    def test_new_nurse_initial_rating_is_5(self, api, platform_admin_headers):
        """PRD §3.1: 'The newly created profile is assigned an initial
        rating of 5.00.'"""
        res = api.create_nurse(
            create_nurse_payload(), platform_admin_headers
        )
        data = validate_success(res, expected_status=201)
        assert float(data["rating"]) == 5.00

    def test_new_nurse_default_max_daily_orders_6(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: 'optionally a per-day workload ceiling
        max_daily_orders (default 6, must be at least 1)'."""
        payload = create_nurse_payload()
        payload.pop("max_daily_orders", None)
        res = api.create_nurse(payload, platform_admin_headers)
        data = validate_success(res, expected_status=201)
        assert data["max_daily_orders"] == 6

    def test_new_nurse_default_revenue_share_7000(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: 'a revenue_share_bps for the nurse's cut of net
        service revenue (default 7000, meaning 70%)'."""
        payload = create_nurse_payload()
        payload.pop("revenue_share_bps", None)
        res = api.create_nurse(payload, platform_admin_headers)
        data = validate_success(res, expected_status=201)
        assert data["revenue_share_bps"] == 7000


class TestCertificationGates:

    def test_certify_blocked_without_license_verified(
        self, api, compliance_officer_headers, platform_admin_headers,
    ):
        """PRD §3.1: 'For this initial certification to advance the nurse
        from PENDING to CERTIFIED, three conditions must hold:
        license_verified must be true, hospital_affiliation_verified must
        be true, and the cumulative sum of training_hours over the
        nurse's INITIAL and TRAINING records must reach the minimum
        training threshold of 24 hours.'

        Claim: license_verified is False -> nurse remains PENDING after
        an INITIAL/PASS attempt.
        """
        nurse = create_nurse_raw()
        # Verify hospital only, NOT license.
        verify_nurse_identity(nurse["id"], license=False, hospital=True)
        # Attempt initial certification with sufficient training hours.
        certify_nurse(nurse["id"], training_hours=24)
        # Re-read; nurse should NOT have advanced to CERTIFIED.
        res = api.get_nurse(nurse["id"], compliance_officer_headers)
        data = get_success_data(res)
        assert data["certification_status"] == "PENDING"

    def test_certify_blocked_below_training_threshold(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.1: 'the cumulative sum of training_hours over the
        nurse's INITIAL and TRAINING records must reach the minimum
        training threshold of 24 hours.'

        Claim: training_hours=23 (boundary - 1) leaves nurse PENDING.
        """
        nurse = create_nurse_raw()
        verify_nurse_identity(nurse["id"])
        certify_nurse(nurse["id"], training_hours=23)
        res = api.get_nurse(nurse["id"], compliance_officer_headers)
        data = get_success_data(res)
        assert data["certification_status"] == "PENDING"

    def test_certify_succeeds_at_threshold(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.1: '...must reach the minimum training threshold of 24
        hours. When all three hold, the nurse advances to CERTIFIED,
        certified_until is set to the supplied effective_at plus a
        recertification validity period of 365 days'.

        Claim: training_hours=24 exactly + both verifications true ->
        nurse becomes CERTIFIED and certified_until is set.
        """
        nurse = create_nurse_raw()
        verify_nurse_identity(nurse["id"])
        certify_nurse(
            nurse["id"], training_hours=24,
            effective_at=DEFAULT_NOW_ISO,
        )
        res = api.get_nurse(nurse["id"], compliance_officer_headers)
        data = get_success_data(res)
        assert data["certification_status"] == "CERTIFIED"
        assert data["certified_until"] is not None


class TestDisqualification:

    def test_disqualify_pending_nurse(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.1: 'Disqualification is the terminal outcome: a
        CertificationRecord with kind DISQUALIFICATION (regardless of
        outcome) sends a non-disqualified nurse straight to DISQUALIFIED'.
        """
        nurse = create_nurse_raw()
        payload = create_certification_record_payload(
            kind="DISQUALIFICATION", outcome="FAIL",
            effective_at=DEFAULT_NOW_ISO,
            notes="License revoked",
        )
        res = api.create_certification_record(
            nurse["id"], payload, compliance_officer_headers
        )
        validate_success(res, expected_status=201)
        # Re-read.
        nurse_after = get_success_data(
            api.get_nurse(nurse["id"], compliance_officer_headers)
        )
        assert nurse_after["certification_status"] == "DISQUALIFIED"

    def test_disqualify_disqualified_rejected(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.1: 'A nurse who is already DISQUALIFIED cannot be
        transitioned again -- the request is rejected with
        ERR_INVALID_STATE.'
        """
        nurse = create_nurse_raw()
        # First disqualification.
        payload = create_certification_record_payload(
            kind="DISQUALIFICATION", outcome="FAIL",
            effective_at=DEFAULT_NOW_ISO,
        )
        res = api.create_certification_record(
            nurse["id"], payload, compliance_officer_headers
        )
        validate_success(res, expected_status=201)
        # Second attempt -> should fail.
        res2 = api.create_certification_record(
            nurse["id"], payload, compliance_officer_headers
        )
        validate_error(res2, ApiErrorId.ERR_INVALID_STATE.value)


class TestCertificationNotFound:

    def test_cert_record_for_unknown_nurse_404(
        self, api, compliance_officer_headers,
    ):
        """PRD §2.5: 'path-resource existence ... ERR_NURSE_NOT_FOUND'.
        Claim: POST /nurses/{unknown}/certification-records -> 404
        ERR_NURSE_NOT_FOUND.
        """
        from test_helpers import NON_EXISTENT_UUID
        payload = create_certification_record_payload(
            kind="INITIAL", outcome="PASS",
            effective_at=DEFAULT_NOW_ISO, training_hours=24,
        )
        res = api.create_certification_record(
            NON_EXISTENT_UUID, payload, compliance_officer_headers
        )
        validate_error(res, ApiErrorId.ERR_NURSE_NOT_FOUND.value)
