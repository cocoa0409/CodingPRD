"""Auth, response envelope, and RBAC tests (PRD §2.1, §2.2, §2.9)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_course_category_payload,
    create_course_payload,
    create_trainee_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Auth header presence (PRD §2.1)
# ===========================================================================
class TestAuthHeaderPresence:

    def test_missing_user_id_header_returns_auth_required(self, api):
        """PRD §2.1: "If either header is missing or empty on any other
        endpoint, the request is rejected with ERR_AUTH_REQUIRED."

        Claim: omitting X-User-ID -> ERR_AUTH_REQUIRED.
        """
        resp = api._request(
            "GET", "/training/courses",
            headers={"X-User-Role": "TrainingAdmin"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_role_header_returns_auth_required(self, api):
        """PRD §2.1: "If either header is missing or empty on any other
        endpoint, the request is rejected with ERR_AUTH_REQUIRED."

        Claim: omitting X-User-Role -> ERR_AUTH_REQUIRED.
        """
        resp = api._request(
            "GET", "/training/courses",
            headers={"X-User-ID": "admin-1"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_user_id_returns_auth_required(self, api):
        """PRD §2.1: "If either header is missing or empty on any other
        endpoint, the request is rejected with ERR_AUTH_REQUIRED."

        Claim: empty X-User-ID -> ERR_AUTH_REQUIRED.
        """
        resp = api._request(
            "GET", "/training/courses",
            headers={"X-User-ID": "", "X-User-Role": "TrainingAdmin"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_user_role_returns_auth_required(self, api):
        """PRD §2.1: "If either header is missing or empty on any other
        endpoint, the request is rejected with ERR_AUTH_REQUIRED."

        Claim: empty X-User-Role -> ERR_AUTH_REQUIRED.
        """
        resp = api._request(
            "GET", "/training/courses",
            headers={"X-User-ID": "admin-1", "X-User-Role": ""},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)


# ===========================================================================
# Role membership and permission (PRD §2.1)
# ===========================================================================
class TestForbiddenRole:

    def test_unknown_role_returns_forbidden_role(self, api):
        """PRD §2.1: "If the supplied X-User-Role is not one of the
        recognized role names, the request is rejected with
        ERR_FORBIDDEN_ROLE."

        Claim: unknown role string -> ERR_FORBIDDEN_ROLE.
        """
        resp = api._request(
            "GET", "/training/courses",
            headers={"X-User-ID": "x", "X-User-Role": "GalacticOverlord"},
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_trainee_cannot_create_course(self, api, trainee_fallback_headers):
        """PRD §2.1: "the same error is returned when a role attempts
        an operation outside its permitted set."
        PRD §4: POST /training/courses is restricted to CourseDesigner,
        TrainingAdmin.

        Claim: Trainee creating a course -> ERR_FORBIDDEN_ROLE.
        """
        # category_id is irrelevant — auth check fires before body
        # validation per PRD §2.9.
        payload = create_course_payload(category_id="cat-x")
        resp = api.create_course(payload, trainee_fallback_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_course_designer_cannot_publish_course(self, api,
                                                    course_designer_headers):
        """PRD §4: POST /training/courses/{id}/publish is restricted to
        TrainingAdmin only.

        Claim: CourseDesigner publishing -> ERR_FORBIDDEN_ROLE.
        """
        # Even with a fake course id, RBAC fires before existence check
        # per PRD §2.9.
        resp = api.publish_course("00000000-0000-0000-0000-000000000000",
                                  course_designer_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_trainee_cannot_create_trainee_record(self, api,
                                                   trainee_fallback_headers):
        """PRD §4: POST /training/trainees is restricted to TrainingAdmin.

        Claim: Trainee onboarding another trainee -> ERR_FORBIDDEN_ROLE.
        """
        resp = api.create_trainee(create_trainee_payload(),
                                  trainee_fallback_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_department_manager_cannot_create_course_category(
        self, api, department_manager_headers,
    ):
        """PRD §4: POST /training/course-categories is restricted to
        TrainingAdmin.

        Claim: DepartmentManager creating a category -> ERR_FORBIDDEN_ROLE.
        """
        resp = api.create_course_category(
            create_course_category_payload(), department_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# Validation ordering (PRD §2.9)
# ===========================================================================
class TestValidationOrdering:

    def test_missing_auth_beats_unknown_role(self, api):
        """PRD §2.9: "the absence of X-User-ID/X-User-Role first
        (returning ERR_AUTH_REQUIRED), then the role membership check
        (ERR_FORBIDDEN_ROLE)."

        Claim: header absence is evaluated BEFORE role recognition.
        """
        resp = api._request(
            "POST", "/training/courses",
            payload=create_course_payload(category_id="cat-x"),
            headers={"X-User-Role": "TrainingAdmin"},  # no X-User-ID
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)


# ===========================================================================
# Public verification endpoint (PRD §2.1, §3.7)
# ===========================================================================
class TestPublicVerification:

    def test_verification_endpoint_does_not_require_auth(self, api):
        """PRD §2.1: "The only exception is the public
        certificate-verification endpoint described in §3 and listed
        in §4, which serves anonymous traffic."

        Claim: POST /training/certificates/verify/{code} does NOT
        require X-User-ID/X-User-Role. The endpoint may legitimately
        return 404 for an unknown code, but it must NOT return
        ERR_AUTH_REQUIRED for missing headers.
        """
        resp = api.verify_certificate("nonexistent-code", headers={})
        # PRD §2.1 explicitly excludes this endpoint from the auth
        # requirement — so ERR_AUTH_REQUIRED must NOT appear.
        if resp.status_code == 401:
            pytest.fail(
                "Public verification endpoint must not require auth "
                "per PRD §2.1; got 401."
            )


# ===========================================================================
# Success-response envelope (PRD §2.2)
# ===========================================================================
class TestSuccessEnvelope:

    def test_success_envelope_carries_meta_and_data(
        self, api, training_admin_headers,
    ):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body."

        Claim: a successful response has meta.api_request_id,
        meta.api_request_timestamp, response_type, and data.
        """
        # A simple list call exercises both 2xx and the meta block.
        resp = api.list_courses(training_admin_headers)
        body = resp.json()
        assert resp.status_code == 200
        assert "meta" in body
        assert "api_request_id" in body["meta"]
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"PRD §2.2: api_request_id must start with 'req_', got "
            f"{body['meta']['api_request_id']!r}"
        )
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] in ("object", "array")
        assert "data" in body


# ===========================================================================
# Error-response envelope (PRD §2.2)
# ===========================================================================
class TestErrorEnvelope:

    def test_error_envelope_has_response_type_error_and_error_id(self, api):
        """PRD §2.2: "All error API responses (4xx status codes)
        follow this standard envelope format ... response_type is
        'error' ... data.error_id is a unique, machine-readable
        string."

        Claim: a missing-auth error returns response_type='error'
        and data.error_id is present.
        """
        resp = api._request("GET", "/training/courses", headers={})
        body = resp.json()
        assert resp.status_code == 401
        assert body.get("response_type") == "error"
        assert body["data"]["error_id"] == "ERR_AUTH_REQUIRED"
        assert "message" in body["data"]


# ===========================================================================
# Pagination bounds (PRD §2.3)
# ===========================================================================
class TestPaginationBounds:

    def test_limit_above_100_rejected(self, api, training_admin_headers):
        """PRD §2.3: "If not provided, it defaults to 10, with a minimum
        of 1 and a maximum of 100. ... Any list request with limit or
        offset outside these bounds is rejected with
        ERR_INVALID_PAGINATION."

        Claim: limit=101 -> ERR_INVALID_PAGINATION.
        """
        resp = api.list_courses(training_admin_headers,
                                params={"limit": 101})
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_limit_below_one_rejected(self, api, training_admin_headers):
        """PRD §2.3: "If not provided, it defaults to 10, with a
        minimum of 1 and a maximum of 100. ... Any list request with
        limit or offset outside these bounds is rejected with
        ERR_INVALID_PAGINATION."

        Claim: limit=0 -> ERR_INVALID_PAGINATION.
        """
        resp = api.list_courses(training_admin_headers, params={"limit": 0})
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_offset_negative_rejected(self, api, training_admin_headers):
        """PRD §2.3: "The offset parameter specifies the number of
        items to skip and defaults to 0, with a minimum of 0. ... Any
        list request with limit or offset outside these bounds is
        rejected with ERR_INVALID_PAGINATION."

        Claim: offset=-1 -> ERR_INVALID_PAGINATION.
        """
        resp = api.list_courses(training_admin_headers, params={"offset": -1})
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_limit_100_is_accepted(self, api, training_admin_headers):
        """PRD §2.3: "with a minimum of 1 and a maximum of 100".

        Claim: limit=100 is at the inclusive upper bound and succeeds.
        """
        resp = api.list_courses(training_admin_headers,
                                params={"limit": 100, "offset": 0})
        assert resp.status_code == 200, (
            f"Expected 200 for limit=100 (PRD §2.3 inclusive max), "
            f"got {resp.status_code}"
        )

    def test_limit_one_is_accepted(self, api, training_admin_headers):
        """PRD §2.3: "with a minimum of 1 and a maximum of 100".

        Claim: limit=1 is at the inclusive lower bound and succeeds.
        """
        resp = api.list_courses(training_admin_headers,
                                params={"limit": 1, "offset": 0})
        assert resp.status_code == 200
