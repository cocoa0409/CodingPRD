"""Auth, RBAC, response envelope, pagination, and NotFound.

These tests exercise cross-cutting checks defined in PRD §2.1
(auth/role), §2.2 (envelope), §2.3 (pagination), §2.4 (NotFound).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    PAGINATION_DEFAULT_LIMIT,
    TEST_USERS,
    build_user_headers,
    create_patient,
    create_patient_payload,
    is_iso8601_timestamp,
    setup_patient_with_policy,
    setup_registered_encounter,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 Auth — missing headers
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "A request that omits either header is rejected
        with ERR_AUTH_MISSING."

        Claim: a POST with neither header set returns ERR_AUTH_MISSING.
        """
        res = api.create_patient(create_patient_payload(), headers={})
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "A request that omits either header is rejected
        with ERR_AUTH_MISSING."

        Claim: omitting X-User-ID returns ERR_AUTH_MISSING.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={"X-User-Role": "RegistrationClerk"},
        )
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "A request that omits either header is rejected
        with ERR_AUTH_MISSING."

        Claim: omitting X-User-Role returns ERR_AUTH_MISSING.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={"X-User-ID": "clerk-001"},
        )
        validate_error(res, "ERR_AUTH_MISSING")


# ===========================================================================
# §2.1 RBAC — role not authorized for endpoint
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: "A request whose `X-User-Role` is not authorized for the endpoint in question is rejected with `ERR_FORBIDDEN`.\""""

    def test_biller_cannot_create_patient(self, api):
        """PRD §4 endpoint table: POST /patients is restricted to
        RegistrationClerk.

        PRD §2.1: "A request whose `X-User-Role` is not authorized for the endpoint in question is rejected with `ERR_FORBIDDEN`."

        Claim: a Biller calling POST /patients returns ERR_FORBIDDEN.
        """
        res = api.create_patient(
            create_patient_payload(), TEST_USERS["biller_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_coder_cannot_create_charge(self, api):
        """PRD §4 endpoint table: POST /encounters/{encounter_id}/
        charges is restricted to ChargeCaptureClerk.

        PRD §2.1: "A request whose `X-User-Role` is not authorized for the endpoint in question is rejected with `ERR_FORBIDDEN`."

        Claim: a Coder attempting to create a charge returns
        ERR_FORBIDDEN.
        """
        from test_helpers import create_charge_payload
        patient, policy, encounter = setup_registered_encounter()
        res = api.create_charge(
            encounter["id"], create_charge_payload(),
            TEST_USERS["coder_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_registration_clerk_cannot_submit_clearance(self, api):
        """PRD §4 endpoint table: POST /encounters/{encounter_id}/
        clearance is restricted to Biller.

        PRD §2.1: "A request whose `X-User-Role` is not authorized for the endpoint in question is rejected with `ERR_FORBIDDEN`."

        Claim: a RegistrationClerk attempting clearance returns
        ERR_FORBIDDEN.
        """
        from test_helpers import submit_clearance_payload
        patient, policy, encounter = setup_registered_encounter()
        res = api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=0,
            ),
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_charge_capture_clerk_cannot_write_off(self, api):
        """PRD §4 endpoint table: POST /encounters/{encounter_id}/
        write-off is restricted to Biller.

        PRD §2.1: "A request whose `X-User-Role` is not authorized for the endpoint in question is rejected with `ERR_FORBIDDEN`."

        Claim: a ChargeCaptureClerk attempting write-off returns
        ERR_FORBIDDEN.
        """
        patient, policy, encounter = setup_registered_encounter()
        res = api.write_off_encounter(
            encounter["id"], TEST_USERS["charge_capture_clerk_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.2 Response envelope
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: every successful response follows the standard envelope."""

    def test_success_envelope_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."

        Claim: a successful POST returns meta.api_request_id starting
        with "req_", meta.api_request_timestamp as ISO 8601, and a
        data object.
        """
        res = api.create_patient(
            create_patient_payload(),
            TEST_USERS["registration_clerk_headers"],
        )
        body = res.json()
        assert "meta" in body
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{body['meta']['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body.get("response_type") in {"object", "array"}
        assert "data" in body

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Claim: an error response carries response_type=="error" and
        data.error_id + data.message.
        """
        res = api.create_patient(create_patient_payload(), headers={})
        body = res.json()
        assert body.get("response_type") == "error"
        assert isinstance(body["data"]["error_id"], str)
        assert isinstance(body["data"]["message"], str)


# ===========================================================================
# §2.3 Pagination
# ===========================================================================
class TestPagination:
    """PRD §2.3: list endpoints expose limit / offset."""

    def test_default_limit_applied(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned and, when omitted, defaults to 10; the accepted range is a minimum of 1 and a maximum of 100."

        Claim: listing patients without query params returns at most
        PAGINATION_DEFAULT_LIMIT rows.
        """
        # Seed slightly more than default.
        for _ in range(PAGINATION_DEFAULT_LIMIT + 2):
            create_patient()
        data, meta = validate_paginated(
            api.list_patients(TEST_USERS["registration_clerk_headers"]),
        )
        assert len(data) <= PAGINATION_DEFAULT_LIMIT
        assert "total_count" in meta
        assert "has_more" in meta

    def test_explicit_limit_and_has_more(self, api):
        """PRD §2.3: "The response envelope's `meta` block on a list response carries `limit`, `offset`, `total_count`, and `has_more` so the caller can paginate forward without re-counting."

        Claim: requesting limit=1 with multiple seeded rows returns one
        item and has_more=true.
        """
        for _ in range(3):
            create_patient()
        data, meta = validate_paginated(
            api.list_patients(
                TEST_USERS["registration_clerk_headers"],
                params={"limit": 1},
            ),
        )
        assert len(data) == 1
        assert meta["has_more"] is True

    def test_offset_past_end_returns_empty(self, api):
        """PRD §2.3: "every list endpoint sorts its results by `created_at` in ascending order."

        Claim: requesting an offset past the total returns an empty page
        with has_more=false.
        """
        create_patient()
        data, meta = validate_paginated(
            api.list_patients(
                TEST_USERS["registration_clerk_headers"],
                params={"offset": 9999},
            ),
        )
        assert data == []
        assert meta["has_more"] is False


# ===========================================================================
# §2.4 NotFound — left-to-right path resolution
# ===========================================================================
class TestResourceNotFound:
    """PRD §2.4: the first identifier that does not resolve causes the
    request to fail immediately with ERR_NOT_FOUND."""

    def test_get_patient_not_found(self, api):
        """PRD §2.4: "The first identifier that does not resolve causes the request to fail immediately with `ERR_NOT_FOUND`".

        Claim: GET /patients/{non-existent} returns ERR_NOT_FOUND.
        """
        res = api.get_patient(
            NON_EXISTENT_UUID, TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_encounter_not_found(self, api):
        """PRD §2.4: "The first identifier that does not resolve causes the request to fail immediately with `ERR_NOT_FOUND`".

        Claim: GET /encounters/{non-existent} returns ERR_NOT_FOUND.
        """
        res = api.get_encounter(
            NON_EXISTENT_UUID, TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_fk_policy_id_not_found_on_encounter_create(self, api):
        """PRD §2.4: "The same rule applies to foreign-key references
        inside request bodies: when admitting a patient the supplied
        policy_id must point at an existing InsurancePolicy and the
        supplied patient_id must point at an existing Patient,
        otherwise the request is rejected with ERR_NOT_FOUND before
        any business validation runs."

        Claim: POST /encounters with a non-existent policy_id returns
        ERR_NOT_FOUND.
        """
        from test_helpers import create_encounter_payload
        patient, _ = setup_patient_with_policy()
        res = api.create_encounter(
            create_encounter_payload(
                patient_id=patient["id"], policy_id=NON_EXISTENT_UUID,
            ),
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_fk_patient_id_not_found_on_policy_create(self, api):
        """PRD §2.4: "This existence sweep covers admission, policy
        attachment, charge creation, and the coding-record submission."

        Claim: POST /patients/{nonexistent}/policies returns
        ERR_NOT_FOUND.
        """
        from test_helpers import create_policy_payload
        res = api.create_policy(
            NON_EXISTENT_UUID, create_policy_payload(),
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")
