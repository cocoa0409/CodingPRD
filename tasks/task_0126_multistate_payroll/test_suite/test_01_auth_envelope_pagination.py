"""Authentication, role validation, response envelope, and pagination.

PRD §2.1, §2.2, §2.3.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_employee_payload,
    setup_world,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthMissingHeaders:
    """PRD §2.1: 'When either header is missing or carries a value the
    system does not recognize, the request is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'"""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "When either header is missing or carries a value
        the system does not recognize, the request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

        Claim: both headers absent -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        resp = api._request("GET", "/employees", headers={})
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "When either header is missing or carries a value
        the system does not recognize, the request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

        Claim: only X-User-ID supplied -> error.
        """
        resp = api._request(
            "GET", "/employees", headers={"X-User-ID": "anyone"},
        )
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "When either header is missing or carries a value
        the system does not recognize, the request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

        Claim: only X-User-Role supplied -> error.
        """
        resp = api._request(
            "GET", "/employees", headers={"X-User-Role": "PayrollManager"},
        )
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )


class TestAuthInvalidRole:
    """PRD §2.1: 'When either header ... carries a value the system
    does not recognize, the request is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'"""

    @pytest.mark.parametrize(
        "bad_role",
        ["Admin", "User", "Payroll", "payrollspecialist",
         "PayrollAdministrator", ""],
    )
    def test_unknown_role_rejected(self, api, bad_role):
        """PRD §2.1: "When either header is missing or carries a value
        the system does not recognize, the request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

        Claim: unrecognized X-User-Role -> error.
        """
        resp = api._request(
            "GET", "/employees",
            headers={"X-User-Role": bad_role, "X-User-ID": "user-1"},
        )
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )


class TestRBACInsufficientPermission:
    """PRD §2.1: 'When the role does not authorize the requested
    operation, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS.'"""

    def test_treasurer_cannot_create_employee(self, api, seeded_world):
        """PRD §2.1: "When the role does not authorize the requested
        operation, the request is rejected with
        ERR_INSUFFICIENT_PERMISSIONS." PRD §4 endpoint table says
        POST /employees is restricted to PayrollSpecialist and
        PayrollManager.

        Claim: Treasurer attempting create-employee -> error.
        """
        resp = api_client.create_employee(
            create_employee_payload(),
            TEST_USERS["treasurer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_specialist_cannot_terminate_employee(self, api, seeded_world):
        """PRD §2.1: "When the role does not authorize the requested
        operation, the request is rejected with
        ERR_INSUFFICIENT_PERMISSIONS." PRD §4: terminate restricted to
        PayrollManager.

        Claim: PayrollSpecialist attempting terminate -> error.
        """
        # Create employee first as a specialist (allowed).
        cresp = api_client.create_employee(
            create_employee_payload(),
            TEST_USERS["specialist_headers"],
        )
        emp = validate_success(cresp, expected_status=201)
        resp = api_client.terminate_employee(
            emp["id"], TEST_USERS["specialist_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_specialist_cannot_approve_paycheck(self, api, seeded_world):
        """PRD §2.1: "When the role does not authorize the requested
        operation, the request is rejected with
        ERR_INSUFFICIENT_PERMISSIONS." PRD §4 approve restricted to
        PayrollManager.

        Claim: PayrollSpecialist approving a paycheck -> error.
        """
        # We need a paycheck id to call approve. Use a clearly
        # non-existent id, but the role check (priority 2) runs
        # BEFORE the existence check (priority 3), so this still
        # surfaces ERR_INSUFFICIENT_PERMISSIONS per PRD §2.7.
        resp = api_client.approve_paycheck(
            "00000000-0000-0000-0000-000000000000",
            TEST_USERS["specialist_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_manager_cannot_mark_paid(self, api, seeded_world):
        """PRD §2.1: "When the role does not authorize the requested
        operation, the request is rejected with
        ERR_INSUFFICIENT_PERMISSIONS." PRD §4: mark-paid restricted to
        Treasurer.

        Claim: PayrollManager marking a paycheck paid -> error.
        """
        resp = api_client.mark_paid_paycheck(
            "00000000-0000-0000-0000-000000000000",
            TEST_USERS["manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


class TestSuccessEnvelope:
    """PRD §2.2: 'All successful API responses (those with 2xx status
    codes) follow this standard envelope format'."""

    def test_create_employee_envelope_shape(self, api, seeded_world):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body" with meta.api_request_id (req_ prefix),
        api_request_timestamp, response_type 'object', and data.

        Claim: successful POST returns the documented envelope.
        """
        resp = api_client.create_employee(
            create_employee_payload(),
            TEST_USERS["specialist_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert isinstance(data, dict)
        body = resp.json()
        meta = body["meta"]
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{meta['api_request_id']!r}"
        )
        assert isinstance(meta["api_request_timestamp"], str)
        assert body["response_type"] == "object"


class TestPagination:
    """PRD §2.3: 'The limit parameter ... defaulting to 10, with a
    minimum of 1 and a maximum of 100. The offset parameter ...
    defaults to 0.'"""

    def test_list_employees_envelope_paginated(self, api, seeded_world):
        """PRD §2.3: "The meta object of any list response includes
        limit, offset, total_count, and has_more."

        Claim: GET /employees response carries pagination meta.
        """
        # Create a couple of employees to ensure data presence.
        for _ in range(2):
            api_client.create_employee(
                create_employee_payload(),
                TEST_USERS["specialist_headers"],
            )
        resp = api_client.list_employees(
            TEST_USERS["manager_headers"],
        )
        data, meta = validate_paginated(resp)
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta
        assert isinstance(data, list)

    def test_list_employees_default_limit_is_ten(self, api, seeded_world):
        """PRD §2.3: "The limit parameter specifies the maximum number
        of items to return, defaulting to 10".

        Claim: no limit param -> meta.limit == 10.
        """
        resp = api_client.list_employees(TEST_USERS["manager_headers"])
        _, meta = validate_paginated(resp)
        assert meta["limit"] == 10, (
            f"default limit must be 10, got {meta['limit']}"
        )

    def test_list_employees_default_offset_is_zero(self, api, seeded_world):
        """PRD §2.3: "The offset parameter specifies the number of
        items to skip and defaults to 0."

        Claim: no offset param -> meta.offset == 0.
        """
        resp = api_client.list_employees(TEST_USERS["manager_headers"])
        _, meta = validate_paginated(resp)
        assert meta["offset"] == 0, (
            f"default offset must be 0, got {meta['offset']}"
        )

    def test_list_employees_explicit_limit_offset_respected(
            self, api, seeded_world):
        """PRD §2.3: "The limit parameter specifies the maximum number
        of items to return". Tests that explicit limit/offset are
        honored.

        Claim: explicit limit/offset values are reflected in meta.
        """
        for _ in range(5):
            api_client.create_employee(
                create_employee_payload(),
                TEST_USERS["specialist_headers"],
            )
        resp = api_client.list_employees(
            TEST_USERS["manager_headers"],
            params={"limit": 2, "offset": 1},
        )
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 2
        assert meta["offset"] == 1
        assert len(data) <= 2
