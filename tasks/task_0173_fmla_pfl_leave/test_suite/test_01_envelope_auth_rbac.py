"""Envelope, authentication, role enforcement, pagination, and path
404 probes.

Covers PRD §2.1 (auth & roles), §2.2 (envelope), §2.3 (pagination),
§2.5 (path resolution), §5 (error catalogue).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    advance_clock_to,
    build_user_headers,
    create_employer_payload,
    create_leave_case_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_employee_headers,
    setup_eligible_employee,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Envelope shape — PRD §2.2
# ===========================================================================
class TestSuccessEnvelope:

    def test_health_envelope_carries_meta_and_data(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body"."""
        resp = api.health()
        body = resp.json()
        assert resp.status_code == 200, (
            f"GET /_health should return 200, got {resp.status_code}"
        )
        assert "meta" in body, "missing meta on success response"
        assert "response_type" in body, "missing response_type"
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id is server-generated unique "
            "identifier that starts with `req_`"
        )
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))

    def test_create_employer_envelope_returns_object(self, api,
                                                      compliance_officer_headers):
        """PRD §2.2: "Operations that create or modify a resource will
        return the created or updated resource object in the data field"
        with `response_type: "object"`."""
        resp = api.create_employer(
            create_employer_payload(), compliance_officer_headers,
        )
        data = validate_success(resp, expected_status=201)
        body = resp.json()
        assert body["response_type"] == "object", (
            f"expected response_type='object', got {body['response_type']!r}"
        )
        assert is_valid_uuid(data["id"]), (
            "PRD §2.4: id is a server-minted UUID with no type prefix"
        )

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format" with `error_id` and `message`."""
        resp = api.create_employer(create_employer_payload(), headers={})
        body = resp.json()
        assert body.get("response_type") == "error"
        assert isinstance(body.get("data"), dict)
        assert body["data"].get("error_id") == "ERR_MISSING_AUTH_HEADERS"
        assert isinstance(body["data"].get("message"), str), (
            "PRD §2.2: error envelope must include a human-readable "
            "message"
        )


# ===========================================================================
# Authentication — PRD §2.1
# ===========================================================================
class TestAuthHeaders:

    def test_missing_both_headers(self, api):
        """PRD §2.1: "If either header is missing or empty the request
        is rejected with `ERR_MISSING_AUTH_HEADERS`"."""
        resp = api.create_employer(create_employer_payload(), headers={})
        validate_error(resp, "ERR_MISSING_AUTH_HEADERS")

    def test_missing_user_id_only(self, api):
        """PRD §2.1: "If either header is missing or empty the request
        is rejected with `ERR_MISSING_AUTH_HEADERS`"."""
        resp = api.create_employer(
            create_employer_payload(),
            {"X-User-Role": "ComplianceOfficer",
             "Content-Type": "application/json"},
        )
        validate_error(resp, "ERR_MISSING_AUTH_HEADERS")

    def test_missing_user_role_only(self, api):
        """PRD §2.1: "If either header is missing or empty the request
        is rejected with `ERR_MISSING_AUTH_HEADERS`"."""
        resp = api.create_employer(
            create_employer_payload(),
            {"X-User-ID": "any-id",
             "Content-Type": "application/json"},
        )
        validate_error(resp, "ERR_MISSING_AUTH_HEADERS")

    def test_empty_user_id_string(self, api):
        """PRD §2.1: "If either header is missing or empty the request
        is rejected with `ERR_MISSING_AUTH_HEADERS`"."""
        resp = api.create_employer(
            create_employer_payload(),
            {"X-User-ID": "",
             "X-User-Role": "ComplianceOfficer",
             "Content-Type": "application/json"},
        )
        validate_error(resp, "ERR_MISSING_AUTH_HEADERS")

    def test_unknown_role(self, api):
        """PRD §2.1: "If the `X-User-Role` value is not one of the
        three recognized roles below, the request is rejected with
        `ERR_UNKNOWN_ROLE`"."""
        h = build_user_headers("any-id", "Admin")
        resp = api.create_employer(create_employer_payload(), h)
        validate_error(resp, "ERR_UNKNOWN_ROLE")

    def test_three_roles_spelled_exactly(self, api,
                                          compliance_officer_headers):
        """PRD §2.1: "The three roles are spelled exactly as `Employee`,
        `HRSpecialist`, and `ComplianceOfficer`"."""
        # Lowercased role should be unknown.
        h = build_user_headers("any-id", "employee")
        resp = api.create_employer(create_employer_payload(), h)
        validate_error(resp, "ERR_UNKNOWN_ROLE")


# ===========================================================================
# RBAC — PRD §2.1, §4
# ===========================================================================
class TestRBAC:

    def test_hr_specialist_cannot_create_employer(self, api,
                                                    hr_specialist_headers):
        """PRD §4: POST /employers is ComplianceOfficer-only.
        PRD §2.1: "If the caller's role is recognized and identifiable
        but is not authorized to invoke the endpoint per the role matrix
        expressed in §4, the request is rejected with `ERR_FORBIDDEN`"."""
        resp = api.create_employer(
            create_employer_payload(), hr_specialist_headers,
        )
        validate_error(resp, "ERR_FORBIDDEN")

    def test_employee_cannot_create_employer(self, api):
        """PRD §4: POST /employers is ComplianceOfficer-only.

        PRD §2.6 validation ordering: identity resolution
        (ERR_UNKNOWN_IDENTITY) is higher priority than endpoint
        authorization (ERR_FORBIDDEN). To faithfully assert the
        FORBIDDEN check we must use a real (persisted) Employee.id."""
        _e, _w, employee = setup_eligible_employee()
        h = make_employee_headers(employee["id"])
        resp = api.create_employer(create_employer_payload(), h)
        validate_error(resp, "ERR_FORBIDDEN")

    def test_employee_cannot_review_leave_case(self, api):
        """PRD §4: POST /leave-cases/{id}/review is HRSpecialist-only."""
        from test_helpers import setup_pending_certification_case
        _e, _w, employee, case = setup_pending_certification_case()
        h = make_employee_headers(employee["id"])
        resp = api.review_leave_case(
            case["id"], {"decision": "APPROVE"}, h,
        )
        validate_error(resp, "ERR_FORBIDDEN")

    def test_employee_cannot_advance_clock(self, api):
        """PRD §4: POST /_clock/advance is ComplianceOfficer-only.
        PRD §2.10: "This capability is restricted to `ComplianceOfficer`".

        PRD §2.6 validation ordering: identity resolution
        (ERR_UNKNOWN_IDENTITY) is higher priority than endpoint
        authorization (ERR_FORBIDDEN). To faithfully assert the
        FORBIDDEN check we must use a real (persisted) Employee.id."""
        _e, _w, employee = setup_eligible_employee()
        h = make_employee_headers(employee["id"])
        resp = api.clock_advance(
            {"to_timestamp": "2026-06-01T00:00:00.000Z"}, h,
        )
        validate_error(resp, "ERR_FORBIDDEN")

    def test_hr_specialist_cannot_advance_clock(self, api,
                                                 hr_specialist_headers):
        """PRD §2.10: "This capability is restricted to
        `ComplianceOfficer`"."""
        resp = api.clock_advance(
            {"to_timestamp": "2026-06-01T00:00:00.000Z"},
            hr_specialist_headers,
        )
        validate_error(resp, "ERR_FORBIDDEN")


# ===========================================================================
# Path resolution / 404 — PRD §2.5
# ===========================================================================
class TestPathResolution:

    def test_get_nonexistent_employee_returns_404(self, api,
                                                    hr_specialist_headers):
        """PRD §2.5: "any unresolved identifier likewise returns
        `ERR_NOT_FOUND`"."""
        resp = api.get_employee(NON_EXISTENT_UUID, hr_specialist_headers)
        validate_error(resp, "ERR_NOT_FOUND")

    def test_get_nonexistent_leave_case_returns_404(self, api,
                                                      hr_specialist_headers):
        """PRD §2.5: unresolved identifier returns `ERR_NOT_FOUND`."""
        resp = api.get_leave_case(NON_EXISTENT_UUID, hr_specialist_headers)
        validate_error(resp, "ERR_NOT_FOUND")

    def test_get_nonexistent_pfl_claim_returns_404(self, api,
                                                     hr_specialist_headers):
        """PRD §2.5: unresolved identifier returns `ERR_NOT_FOUND`."""
        resp = api.get_pfl_claim(NON_EXISTENT_UUID, hr_specialist_headers)
        validate_error(resp, "ERR_NOT_FOUND")


# ===========================================================================
# Ownership — PRD §2.1
# ===========================================================================
class TestOwnership:

    def test_employee_cannot_view_other_employees_case(self, api):
        """PRD §2.1: "When `X-User-Role` is `Employee` ... ownership
        checks on any resource that references an `Employee` ...
        compare the resource's owning `employee_id` to `X-User-ID`. A
        mismatch surfaces as `ERR_NOT_OWNER`"."""
        # Create two employees on the same employer, then have employee
        # B try to view employee A's leave case.
        emp1, _ws1, employee1 = setup_eligible_employee()
        # Reuse the same employer/worksite for employee2.
        from test_helpers import create_employee, submit_leave_case
        employee2 = create_employee(
            employer_id=emp1["id"], worksite_id=_ws1["id"],
        )
        case_of_employee1 = submit_leave_case(
            employee_id=employee1["id"],
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
            requested_start_date="2026-05-01",
            expected_end_date="2026-05-31",
        )
        # employee2 tries to GET employee1's case.
        h = make_employee_headers(employee2["id"])
        resp = api.get_leave_case(case_of_employee1["id"], h)
        validate_error(resp, "ERR_NOT_OWNER")
