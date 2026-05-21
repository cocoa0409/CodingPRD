"""Envelope, authentication, role enforcement, pagination, and 404 path
probes.

Covers PRD §2.1 (auth & roles), §2.2 (envelope), §2.3 (pagination),
§2.7 (path resolution), §5 (error catalogue).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    advance_clock_to,
    api_client,
    build_user_headers,
    create_employee,
    create_employee_payload,
    create_i9_form_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_employee_with_section2_done,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Envelope shape — PRD §2.2
# ===========================================================================
class TestSuccessEnvelope:

    def test_success_envelope_has_meta_response_type_and_data(self, api,
                                                              hr_staff_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body".

        Claim: success response carries `meta`, `response_type='object'`,
        and `data`.
        """
        advance_clock_to("2026-05-20T08:00:00.000Z")
        resp = api.create_employee(
            create_employee_payload(start_date="2026-06-01"),
            hr_staff_headers,
        )
        # The runner's validate_success raises on any envelope mismatch.
        data = validate_success(resp, expected_status=201)
        body = resp.json()
        assert "meta" in body, "missing meta on success response"
        assert "response_type" in body, "missing response_type"
        assert body["response_type"] == "object", (
            f"expected response_type='object', got {body['response_type']!r}"
        )
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str), (
            "api_request_id must be a string"
        )
        assert meta["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id is server-generated unique "
            "identifier that starts with `req_`"
        )
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
            "api_request_timestamp must be ISO 8601 UTC"
        )
        assert "data" in body
        assert is_valid_uuid(data["id"]), (
            "PRD §2.4: id is a server-minted UUID with no type prefix"
        )

    def test_error_envelope_has_error_id_and_message(self, api):
        """PRD §2.2: error envelope carries data.error_id and
        data.message; response_type='error'."""
        resp = api.create_employee(
            create_employee_payload(), headers={},
        )
        body = resp.json()
        assert body.get("response_type") == "error", (
            f"expected response_type='error', got {body.get('response_type')!r}"
        )
        assert "data" in body and isinstance(body["data"], dict)
        assert body["data"].get("error_id") == "ERR_AUTH_MISSING"
        assert isinstance(body["data"].get("message"), str), (
            "error envelope must include a human-readable message"
        )


# ===========================================================================
# Authentication — PRD §2.1
# ===========================================================================
class TestAuthHeaders:

    def test_missing_headers_returns_err_auth_missing(self, api):
        """PRD §2.1: "A request that omits or malforms either header is
        rejected with `ERR_AUTH_MISSING`"."""
        resp = api.create_employee(
            create_employee_payload(), headers={},
        )
        validate_error(resp, "ERR_AUTH_MISSING")

    def test_missing_user_role_only_returns_err_auth_missing(self, api):
        """PRD §2.1: both X-User-ID and X-User-Role are required."""
        resp = api.create_employee(
            create_employee_payload(),
            headers={"X-User-ID": "some-id"},
        )
        validate_error(resp, "ERR_AUTH_MISSING")

    def test_missing_user_id_only_returns_err_auth_missing(self, api):
        """PRD §2.1: both X-User-ID and X-User-Role are required."""
        resp = api.create_employee(
            create_employee_payload(),
            headers={"X-User-Role": "HRStaff"},
        )
        validate_error(resp, "ERR_AUTH_MISSING")


# ===========================================================================
# RBAC — PRD §2.1
# ===========================================================================
class TestRBAC:

    def test_employee_role_cannot_create_employee(self, api):
        """PRD §4 endpoint table: POST /employees is HRStaff-exclusive.
        PRD §2.1: "A request whose role is not authorized for the
        endpoint it targets is rejected with `ERR_FORBIDDEN`"."""
        h = build_user_headers("some-employee-id", "Employee")
        resp = api.create_employee(create_employee_payload(), h)
        validate_error(resp, "ERR_FORBIDDEN")

    def test_employer_rep_cannot_create_employee(self, api):
        """PRD §4: POST /employees is HRStaff-only."""
        h = build_user_headers("erep-1", "EmployerRep")
        resp = api.create_employee(create_employee_payload(), h)
        validate_error(resp, "ERR_FORBIDDEN")

    def test_hr_staff_cannot_sign_section2(self, api, hr_staff_headers):
        """PRD §4: POST .../section2 is EmployerRep-exclusive.
        PRD §2.1: "`HRStaff` cannot ... perform EmployerRep document
        examinations".
        """
        employee, form, _doc = setup_employee_with_section2_done()
        # Re-attempt sign with HRStaff role on the same (now SECTION_2_DONE)
        # form. Validation order (PRD §2.9): role check (FORBIDDEN) comes
        # before the state check.
        resp = api.sign_section2(
            employee["id"], form["id"], {"version": form["version"]},
            hr_staff_headers,
        )
        validate_error(resp, "ERR_FORBIDDEN")

    def test_hr_staff_cannot_submit_everify_case(self, api,
                                                 hr_staff_headers):
        """PRD §4: POST /employees/{id}/everify-cases is
        EmployerRep-exclusive."""
        employee, form, _doc = setup_employee_with_section2_done()
        resp = api.submit_everify_case(
            employee["id"],
            {"i9_form_id": form["id"], "idempotency_key": "k-test"},
            hr_staff_headers,
        )
        validate_error(resp, "ERR_FORBIDDEN")

    def test_employer_rep_cannot_create_i9_form(self, api,
                                                employer_rep_headers):
        """PRD §4: POST /employees/{id}/i9-forms is HRStaff-exclusive."""
        employee = create_employee()
        resp = api.create_i9_form(
            employee["id"],
            create_i9_form_payload(form_kind="INITIAL"),
            employer_rep_headers,
        )
        validate_error(resp, "ERR_FORBIDDEN")

    def test_non_system_cannot_advance_clock(self, api, hr_staff_headers):
        """PRD §4: POST /_clock/advance is System-only."""
        resp = api.clock_advance(
            {"to": "2026-06-01T00:00:00.000Z"}, hr_staff_headers,
        )
        validate_error(resp, "ERR_FORBIDDEN")

    def test_non_system_cannot_run_sweep(self, api, employer_rep_headers):
        """PRD §4: POST /_sweep/run is System-only."""
        resp = api.run_sweep(employer_rep_headers)
        validate_error(resp, "ERR_FORBIDDEN")


# ===========================================================================
# Path resolution — PRD §2.7
# ===========================================================================
class TestPathResolution:

    def test_get_nonexistent_employee_returns_err_not_found(self, api,
                                                            hr_staff_headers):
        """PRD §2.7: "If any segment fails to resolve, the response is
        `ERR_NOT_FOUND`"."""
        resp = api.get_employee(NON_EXISTENT_UUID, hr_staff_headers)
        validate_error(resp, "ERR_NOT_FOUND")

    def test_get_nonexistent_case_returns_err_not_found(self, api,
                                                        employer_rep_headers):
        """PRD §2.7: path id resolution failure → ERR_NOT_FOUND."""
        resp = api.get_everify_case(NON_EXISTENT_UUID, employer_rep_headers)
        validate_error(resp, "ERR_NOT_FOUND")

    def test_create_form_with_unresolved_employee_returns_err_not_found(
            self, api, hr_staff_headers):
        """PRD §2.7: the Employee path segment is resolved first."""
        resp = api.create_i9_form(
            NON_EXISTENT_UUID,
            create_i9_form_payload(form_kind="INITIAL"),
            hr_staff_headers,
        )
        validate_error(resp, "ERR_NOT_FOUND")

    def test_create_form_with_unresolved_supersedes_form_id_returns_reference_not_found(
            self, api, hr_staff_headers):
        """PRD §2.7: "if a body field carrying a foreign-key reference
        such as `employee_id`, `i9_form_id`, `list_a_document_id`,
        `list_b_document_id`, `list_c_document_id`, or
        `supersedes_form_id` does not point at an existing row, the
        response is `ERR_REFERENCE_NOT_FOUND`"."""
        employee = create_employee()
        resp = api.create_i9_form(
            employee["id"],
            create_i9_form_payload(
                form_kind="REVERIFICATION",
                supersedes_form_id=NON_EXISTENT_UUID,
            ),
            hr_staff_headers,
        )
        validate_error(resp, "ERR_REFERENCE_NOT_FOUND")


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_list_employees_default_pagination(self, api, hr_staff_headers):
        """PRD §2.3: "The `limit` parameter ... defaults to 10".
        PRD §2.3: "List responses include the four pagination fields
        `limit`, `offset`, `total_count`, and `has_more` in the
        envelope's `meta` block."
        """
        for _ in range(2):
            create_employee()
        resp = api.list_employees(hr_staff_headers)
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10, (
            f"PRD §2.3 default limit=10, got {meta['limit']}"
        )
        assert meta["offset"] == 0, (
            f"PRD §2.3 default offset=0, got {meta['offset']}"
        )
        assert isinstance(meta.get("total_count"), int)
        assert isinstance(meta.get("has_more"), bool)

    def test_limit_below_one_returns_err_pagination(self, api,
                                                    hr_staff_headers):
        """PRD §2.3: "A `limit` outside the inclusive range from 1 to
        100, or a negative `offset`, yields `ERR_PAGINATION`"."""
        resp = api.list_employees(hr_staff_headers, params={"limit": 0})
        validate_error(resp, "ERR_PAGINATION")

    def test_limit_above_max_returns_err_pagination(self, api,
                                                    hr_staff_headers):
        """PRD §2.3: limit > 100 → ERR_PAGINATION."""
        resp = api.list_employees(hr_staff_headers, params={"limit": 101})
        validate_error(resp, "ERR_PAGINATION")

    def test_negative_offset_returns_err_pagination(self, api,
                                                    hr_staff_headers):
        """PRD §2.3: negative offset → ERR_PAGINATION."""
        resp = api.list_employees(hr_staff_headers, params={"offset": -1})
        validate_error(resp, "ERR_PAGINATION")

    def test_limit_one_returns_one_item_with_has_more(self, api,
                                                     hr_staff_headers):
        """PRD §2.3: meta.has_more reflects remaining items."""
        for _ in range(3):
            create_employee()
        resp = api.list_employees(
            hr_staff_headers, params={"limit": 1, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1, (
            f"Expected 1 item with limit=1, got {len(data)}"
        )
        assert meta["has_more"] is True or meta["total_count"] <= 1
