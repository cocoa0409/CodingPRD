"""Initiator / Backer registration and KYC.

PRD references:
  - §3.1 Onboarding Initiators and Backers
  - §2.4 Common Resource Properties
  - §4 endpoint table
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_backer,
    assert_initiator,
    create_backer_payload,
    create_initiator,
    create_initiator_payload,
    validate_error,
    validate_success,
    verify_kyc,
)


class TestRegisterInitiator:
    def test_create_initiator_persists_in_pending(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: 'Newly created initiators are persisted with kyc_status
        set to PENDING.'

        Claim: POST /initiators returns kyc_status=PENDING.
        """
        res = api.create_initiator(
            create_initiator_payload(
                legal_name="Acme Studios",
                tax_id="TAX-1234",
                bank_account_id="BA-9999",
            ),
            platform_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_initiator(data)
        assert data["kyc_status"] == "PENDING"
        assert data["legal_name"] == "Acme Studios"

    def test_create_initiator_minimum_legal_name_only(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: 'A creator joins the platform by registering as an
        initiator with at least their legal_name.'

        Claim: legal_name alone is sufficient; optional fields may be omitted.
        """
        res = api.create_initiator(
            create_initiator_payload(legal_name="Minimal Inc"),
            platform_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["legal_name"] == "Minimal Inc"
        assert data["kyc_status"] == "PENDING"


class TestVerifyKyc:
    def test_verify_kyc_sets_status_verified(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: 'KYC verification is a PlatformAdmin operation that
        supplies a decision and flips kyc_status to either VERIFIED or
        REJECTED'.

        Claim: verify-kyc with decision=VERIFIED → kyc_status=VERIFIED.
        """
        initiator = create_initiator()
        res = api.verify_kyc(
            initiator["id"], {"decision": "VERIFIED"},
            platform_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["kyc_status"] == "VERIFIED"
        assert data["id"] == initiator["id"]

    def test_verify_kyc_sets_status_rejected(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: 'KYC verification is a PlatformAdmin operation that
        supplies a decision and flips kyc_status to either VERIFIED or
        REJECTED'.

        Claim: verify-kyc with decision=REJECTED → kyc_status=REJECTED.
        """
        initiator = create_initiator()
        res = api.verify_kyc(
            initiator["id"], {"decision": "REJECTED"},
            platform_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["kyc_status"] == "REJECTED"

    def test_verify_kyc_unknown_initiator_404(
        self, api, platform_admin_headers,
    ):
        """PRD §2.6: 'if it does not name an existing project, the request
        is rejected with ERR_NOT_FOUND (HTTP 404)'. PRD §2.8 lists
        path-parameter existence as the third precedence step.

        Claim: verify-kyc on a non-existent id → ERR_NOT_FOUND.
        """
        res = api.verify_kyc(
            NON_EXISTENT_UUID, {"decision": "VERIFIED"},
            platform_admin_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")


class TestRegisterBacker:
    def test_create_backer_basic(self, api, platform_admin_headers):
        """PRD §3.1: 'Backers register with their display_name, email
        (which is unique across all backers), and an optional
        default_shipping_address.'

        Claim: POST /backers with display_name + email returns the Backer.
        """
        res = api.create_backer(
            create_backer_payload(
                display_name="Patreon Pat",
                email="pat@example.test",
            ),
            platform_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_backer(data)
        assert data["display_name"] == "Patreon Pat"
        assert data["email"] == "pat@example.test"
