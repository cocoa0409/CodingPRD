"""Envelope shape, authentication, RBAC, pagination, and 404 path probes.

Covers PRD §2.1 (auth & roles), §2.2 (envelope), §2.3 (pagination),
§2.8 (path resolution), §2.9 (validation priority), §5 (error catalogue).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    build_user_headers,
    clock_set,
    create_employee,
    create_employee_payload,
    create_shift_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    TEST_DEFAULTS,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Envelope — PRD §2.2
# ===========================================================================
class TestSuccessEnvelope:

    def test_success_envelope_carries_meta_response_type_and_data(
        self, api, payroll_admin_headers,
    ):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body".

        Claim: a 2xx response carries `meta`, `response_type='object'`,
        and `data`; meta includes `api_request_id` starting with `req_`
        and an ISO 8601 `api_request_timestamp`.
        """
        clock_set(TEST_DEFAULTS["WORKWEEK_ANCHOR"])
        resp = api.create_employee(
            create_employee_payload(), payroll_admin_headers,
        )
        body = resp.json()
        assert resp.status_code == 201
        assert "meta" in body, "missing meta on success response"
        assert "response_type" in body, "missing response_type"
        assert body["response_type"] == "object", (
            f"expected response_type='object', got {body['response_type']!r}"
        )
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id starts with `req_`"
        )
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"])

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string
        that identifies the specific error. The `message` provides a
        human-readable explanation of what went wrong."
        """
        resp = api.create_employee(
            create_employee_payload(), headers={},
        )
        body = resp.json()
        assert body.get("response_type") == "error", (
            f"expected response_type='error', got {body.get('response_type')!r}"
        )
        assert "data" in body and isinstance(body["data"], dict)
        assert body["data"].get("error_id") == "ERR_AUTH_REQUIRED"
        assert isinstance(body["data"].get("message"), str)


# ===========================================================================
# Authentication — PRD §2.1
# ===========================================================================
class TestAuthHeaders:

    def test_missing_both_headers_returns_err_auth_required(self, api):
        """PRD §2.1: "Absence of either header is a hard rejection with
        `ERR_AUTH_REQUIRED` and HTTP status 401."
        """
        resp = api.create_employee(
            create_employee_payload(), headers={},
        )
        validate_error(resp, "ERR_AUTH_REQUIRED")

    def test_missing_x_user_id_returns_err_auth_required(self, api):
        """PRD §2.1: "Absence of either header is a hard rejection with
        `ERR_AUTH_REQUIRED` and HTTP status 401."
        """
        resp = api.create_employee(
            create_employee_payload(),
            headers={"X-User-Role": "PayrollAdmin"},
        )
        validate_error(resp, "ERR_AUTH_REQUIRED")

    def test_missing_x_user_role_returns_err_auth_required(self, api):
        """PRD §2.1: "Absence of either header is a hard rejection with
        `ERR_AUTH_REQUIRED` and HTTP status 401."
        """
        resp = api.create_employee(
            create_employee_payload(),
            headers={"X-User-ID": "test-admin-0001"},
        )
        validate_error(resp, "ERR_AUTH_REQUIRED")

    def test_invalid_role_value_returns_err_invalid_role(self, api):
        """PRD §2.1: "A header value for `X-User-Role` that is not one
        of the three recognized role names is rejected with
        `ERR_INVALID_ROLE`, also 401."
        """
        resp = api.create_employee(
            create_employee_payload(),
            headers=build_user_headers("test-admin-0001", "Superuser"),
        )
        validate_error(resp, "ERR_INVALID_ROLE")


# ===========================================================================
# RBAC — PRD §2.1
# ===========================================================================
class TestRBAC:

    def test_supervisor_cannot_create_employee(self, api,
                                                supervisor_headers):
        """PRD §4: POST /timekeeping/employees is exclusive to
        PayrollAdmin. PRD §2.1: "is the only role permitted to create
        employees".
        """
        clock_set(TEST_DEFAULTS["WORKWEEK_ANCHOR"])
        resp = api.create_employee(
            create_employee_payload(), supervisor_headers,
        )
        validate_error(resp, "ERR_FORBIDDEN")

    def test_employee_cannot_create_employee(self, api, employee_headers):
        """PRD §4: POST /timekeeping/employees is exclusive to
        PayrollAdmin. An Employee call is `ERR_FORBIDDEN`."""
        clock_set(TEST_DEFAULTS["WORKWEEK_ANCHOR"])
        resp = api.create_employee(
            create_employee_payload(), employee_headers,
        )
        validate_error(resp, "ERR_FORBIDDEN")

    def test_supervisor_cannot_finalize_shift(
        self, api, supervisor_headers, payroll_admin_headers,
    ):
        """PRD §4: POST /timekeeping/shifts/{id}/finalize is exclusive to
        PayrollAdmin.
        """
        clock_set(TEST_DEFAULTS["WORKWEEK_ANCHOR"])
        employee = create_employee()
        shift_resp = api.create_shift(
            create_shift_payload(employee["id"]), supervisor_headers,
        )
        shift = validate_success(shift_resp, expected_status=201)
        resp = api.finalize_shift(shift["id"], supervisor_headers)
        validate_error(resp, "ERR_FORBIDDEN")

    def test_employee_cannot_read_audit(self, api, employee_headers):
        """PRD §3.8: "Only the payroll administrator may read the audit
        log."
        """
        resp = api.list_audit(employee_headers)
        validate_error(resp, "ERR_FORBIDDEN")

    def test_supervisor_cannot_read_audit(self, api, supervisor_headers):
        """PRD §3.8: "Only the payroll administrator may read the audit
        log."
        """
        resp = api.list_audit(supervisor_headers)
        validate_error(resp, "ERR_FORBIDDEN")

    def test_supervisor_cannot_revert_time_edit(
        self, api, supervisor_headers,
    ):
        """PRD §4: POST /timekeeping/time-edits/{id}/revert is exclusive
        to PayrollAdmin. PRD §3.5: "Reverting an already-approved time
        edit is a payroll-administrator capability"."""
        resp = api.revert_time_edit(NON_EXISTENT_UUID, supervisor_headers)
        # PRD §2.9 priority: RBAC (ERR_FORBIDDEN) fires before existence
        # (ERR_RESOURCE_NOT_FOUND).
        validate_error(resp, "ERR_FORBIDDEN")

    def test_supervisor_cannot_lock_workweek(self, api, supervisor_headers):
        """PRD §4: POST /timekeeping/workweeks/{id}/lock is exclusive to
        PayrollAdmin.
        """
        resp = api.lock_workweek(NON_EXISTENT_UUID, supervisor_headers)
        validate_error(resp, "ERR_FORBIDDEN")


# ===========================================================================
# 404 path probes — PRD §2.8
# ===========================================================================
class TestNotFoundProbes:

    def test_get_nonexistent_employee(self, api, payroll_admin_headers):
        """PRD §2.8: "absent path resources are reported as
        `ERR_RESOURCE_NOT_FOUND` (404)"."""
        resp = api.get_employee(NON_EXISTENT_UUID, payroll_admin_headers)
        validate_error(resp, "ERR_RESOURCE_NOT_FOUND")

    def test_get_nonexistent_shift(self, api, payroll_admin_headers):
        """PRD §2.8: absent path resource → ERR_RESOURCE_NOT_FOUND (404)."""
        resp = api.get_shift(NON_EXISTENT_UUID, payroll_admin_headers)
        validate_error(resp, "ERR_RESOURCE_NOT_FOUND")

    def test_get_nonexistent_workweek(self, api, payroll_admin_headers):
        """PRD §2.8: absent path resource → ERR_RESOURCE_NOT_FOUND (404)."""
        resp = api.get_workweek(NON_EXISTENT_UUID, payroll_admin_headers)
        validate_error(resp, "ERR_RESOURCE_NOT_FOUND")

    def test_get_nonexistent_time_edit(self, api, payroll_admin_headers):
        """PRD §2.8: absent path resource → ERR_RESOURCE_NOT_FOUND (404)."""
        resp = api.get_time_edit(NON_EXISTENT_UUID, payroll_admin_headers)
        validate_error(resp, "ERR_RESOURCE_NOT_FOUND")

    def test_approve_nonexistent_time_edit(self, api, payroll_admin_headers):
        """PRD §2.8: absent path resource on /approve →
        ERR_RESOURCE_NOT_FOUND (404)."""
        resp = api.approve_time_edit(NON_EXISTENT_UUID,
                                     payroll_admin_headers)
        validate_error(resp, "ERR_RESOURCE_NOT_FOUND")


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_list_employees_returns_paginated_envelope(
        self, api, payroll_admin_headers,
    ):
        """PRD §2.3: "Every list endpoint accepts two query parameters:
        `limit`, defaulting to 10 when omitted ... and `offset`,
        defaulting to 0".
        """
        clock_set(TEST_DEFAULTS["WORKWEEK_ANCHOR"])
        for _ in range(3):
            create_employee()
        data, meta = validate_paginated(
            api.list_employees(payroll_admin_headers),
        )
        assert meta["total_count"] >= 3
        assert meta["limit"] >= 1
        assert meta["offset"] == 0
        assert isinstance(meta["has_more"], bool)

    def test_list_employees_honors_limit(
        self, api, payroll_admin_headers,
    ):
        """PRD §2.3: "`limit`, defaulting to 10 when omitted, with a
        minimum accepted value of 1 and a maximum of 100"."""
        clock_set(TEST_DEFAULTS["WORKWEEK_ANCHOR"])
        for _ in range(3):
            create_employee()
        data, meta = validate_paginated(
            api.list_employees(
                payroll_admin_headers, params={"limit": 1, "offset": 0},
            ),
        )
        assert len(data) == 1
        assert meta["limit"] == 1
        assert meta["has_more"] is True

    def test_list_employees_offset_past_end_returns_empty(
        self, api, payroll_admin_headers,
    ):
        """PRD §2.3: pagination supports arbitrary offsets; past-the-end
        returns empty data with has_more=False."""
        data, meta = validate_paginated(
            api.list_employees(
                payroll_admin_headers, params={"offset": 99999},
            ),
        )
        assert data == []
        assert meta["has_more"] is False
