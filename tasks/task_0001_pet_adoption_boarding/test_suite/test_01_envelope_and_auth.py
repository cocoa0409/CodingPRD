"""Response envelope, auth headers, and RBAC.

Covers PRD §2.1 (auth), §2.2 (envelope), §2.3 (pagination), §2.7 validation ordering
— priorities 1 and 2 are the header + role checks.
"""
import pytest
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    create_shelter_payload, create_animal_payload,
    create_shelter, create_animal, build_user_headers,
)


class TestAuthHeaders:
    def test_missing_x_user_id_rejected(self):
        """PRD §2.1: "Missing, blank, or otherwise unparseable header values yield
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.\""""
        resp = api_client.create_shelter(create_shelter_payload(),
                                         headers={"X-User-Role": "ShelterAdmin"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_missing_x_user_role_rejected(self):
        """PRD §2.1: missing X-User-Role yields ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
        resp = api_client.create_shelter(create_shelter_payload(),
                                         headers={"X-User-ID": "some-user"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_blank_x_user_id_rejected(self):
        """PRD §2.1: blank header values yield ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
        resp = api_client.create_shelter(create_shelter_payload(),
                                         headers={"X-User-ID": "", "X-User-Role": "ShelterAdmin"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_invalid_role_value_rejected(self):
        """PRD §2.1: unparseable header values yield ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
        resp = api_client.create_shelter(create_shelter_payload(),
                                         headers={"X-User-ID": "u1",
                                                  "X-User-Role": "NotARealRole"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


class TestRBAC:
    def test_non_admin_cannot_create_shelter(self):
        """PRD §2.1 + §4: "only ShelterAdmin creates shelters"."""
        resp = api_client.create_shelter(create_shelter_payload(),
                                         TEST_USERS["adopter_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_non_admin_cannot_create_animal(self):
        """PRD §3.1: "Animal intake is similarly an admin privilege"."""
        shelter = create_shelter()
        resp = api_client.create_animal(shelter["id"], create_animal_payload(),
                                        TEST_USERS["adopter_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_non_approver_cannot_approve(self):
        """PRD §3.4: "Approval is reserved for the AdoptionApprover role"."""
        # use a reviewer role to attempt approve on a non-existent app id
        # but existence is priority 3, before permission? Actually per PRD §2.7
        # priority 2 is permission, priority 3 is existence. So role mismatch fires first.
        resp = api_client.approve_application("00000000-0000-0000-0000-000000000000",
                                              TEST_USERS["adoption_reviewer_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_non_finance_cannot_capture(self):
        """PRD §3.8: "POST /fee-settlements/{id}/capture is the finance officer's tool"."""
        resp = api_client.capture_settlement("00000000-0000-0000-0000-000000000000",
                                             TEST_USERS["adopter_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_non_coordinator_cannot_check_in(self):
        """PRD §2.1: "only BoardingCoordinator checks animals in and out of boarding"."""
        resp = api_client.check_in_reservation(
            "00000000-0000-0000-0000-000000000000",
            "00000000-0000-0000-0000-000000000000",
            TEST_USERS["adopter_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


class TestEnvelope:
    def test_success_envelope_shape(self):
        """PRD §2.2: success envelope has meta.api_request_id, api_request_timestamp,
        response_type=object, data."""
        resp = api_client.create_shelter(create_shelter_payload(),
                                         TEST_USERS["shelter_admin_headers"])
        body = resp.json()
        assert "meta" in body
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "object"
        assert "data" in body

    def test_error_envelope_shape(self):
        """PRD §2.2: error envelope has response_type=error and data={error_id, message}."""
        resp = api_client.create_shelter(create_shelter_payload(),
                                         TEST_USERS["adopter_headers"])
        body = resp.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]

    def test_list_envelope_has_pagination_meta(self):
        """PRD §2.2 + §2.3: list endpoints populate limit, offset, total_count, has_more on meta."""
        # create a shelter so the list is non-empty
        create_shelter()
        resp = api_client.list_shelters(TEST_USERS["shelter_admin_headers"])
        data, meta = validate_paginated(resp)
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta
        assert isinstance(data, list)


class TestPagination:
    def test_default_limit_is_50(self):
        """PRD §2.3: "limit defaults to 50"."""
        create_shelter()
        resp = api_client.list_shelters(TEST_USERS["shelter_admin_headers"])
        _, meta = validate_paginated(resp)
        assert meta["limit"] == 50

    def test_limit_zero_rejected(self):
        """PRD §2.3: "minimum of 1 ... values outside this range are rejected as ERR_INVALID_REQUEST"."""
        resp = api_client.list_shelters(TEST_USERS["shelter_admin_headers"],
                                        params={"limit": 0})
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_limit_over_200_rejected(self):
        """PRD §2.3: "maximum of 200 ... values outside this range are rejected as ERR_INVALID_REQUEST"."""
        resp = api_client.list_shelters(TEST_USERS["shelter_admin_headers"],
                                        params={"limit": 201})
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_limit_at_min_accepted(self):
        """PRD §2.3: minimum of 1 — limit=1 is inside the valid range."""
        create_shelter()
        resp = api_client.list_shelters(TEST_USERS["shelter_admin_headers"],
                                        params={"limit": 1})
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 1

    def test_limit_at_max_accepted(self):
        """PRD §2.3: maximum of 200 — limit=200 is inside the valid range."""
        create_shelter()
        resp = api_client.list_shelters(TEST_USERS["shelter_admin_headers"],
                                        params={"limit": 200})
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 200
