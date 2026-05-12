"""On-behalf-of pickup authorizations.

PRD §3.4 (On-Behalf-of Pickup Authorizations).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_days,
    add_hours,
    add_seconds,
    assert_pickup_authorization,
    create_authorization,
    create_authorization_payload,
    is_iso8601_timestamp,
    register_shelved_parcel,
    setup_station_with_staff,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestAuthorizationCreation:
    def test_authorization_stamps_granted_at_and_starts_active(self, api):
        """PRD §3.4: "The server stamps granted_at itself, sets the
        authorization's status to ACTIVE."

        Claim: POST /parcels/{id}/authorizations returns a record with
        status=ACTIVE and an ISO 8601 granted_at.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        auth = create_authorization(parcel)
        assert_pickup_authorization(auth)
        assert auth["status"] == "ACTIVE"
        assert is_iso8601_timestamp(auth["granted_at"])

    def test_expires_at_at_or_before_granted_at_is_invalid(self, api):
        """PRD §3.4: "the expires_at must be strictly later than the
        just-stamped granted_at and no later than the parcel's
        free_storage_deadline plus seven days. A violation surfaces as
        ERR_AUTHORIZATION_EXPIRY_INVALID (HTTP 422)."

        Claim: an expires_at instant equal to or before granted_at
        yields ERR_AUTHORIZATION_EXPIRY_INVALID.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        # Use a clearly past time (well before granted_at would be).
        past_iso = "2000-01-01T00:00:00.000Z"
        resp = api.create_authorization(
            parcel["id"],
            create_authorization_payload(expires_at=past_iso),
            TEST_USERS["recipient_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_EXPIRY_INVALID)

    def test_expires_at_beyond_deadline_plus_seven_days_is_invalid(self, api):
        """PRD §3.4: "the expires_at must be strictly later than the
        just-stamped granted_at and no later than the parcel's
        free_storage_deadline plus seven days. A violation surfaces as
        ERR_AUTHORIZATION_EXPIRY_INVALID."

        Claim: an expires_at instant strictly after
        free_storage_deadline + 7 days yields
        ERR_AUTHORIZATION_EXPIRY_INVALID.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        # 8 days past the deadline -> outside window.
        too_far = add_days(parcel["free_storage_deadline"], 8)
        resp = api.create_authorization(
            parcel["id"],
            create_authorization_payload(expires_at=too_far),
            TEST_USERS["recipient_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_EXPIRY_INVALID)

    def test_expires_at_within_deadline_plus_seven_days_succeeds(self, api):
        """PRD §3.4: "the expires_at must be strictly later than the
        just-stamped granted_at and no later than the parcel's
        free_storage_deadline plus seven days."

        Claim: expires_at at deadline + 1 day succeeds.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        within = add_days(parcel["free_storage_deadline"], 1)
        resp = api.create_authorization(
            parcel["id"],
            create_authorization_payload(expires_at=within),
            TEST_USERS["recipient_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"


class TestAuthorizationRevocation:
    def test_revoke_sets_status_revoked(self, api):
        """PRD §3.4: "revocation flows through the
        authorization-update capability and simply sets its status to
        REVOKED."

        Claim: PATCH /authorizations/{id} with status=REVOKED returns
        a record whose status is REVOKED.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        auth = create_authorization(parcel)
        resp = api.patch_authorization(
            auth["id"], {"status": "REVOKED"},
            TEST_USERS["recipient_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "REVOKED"
