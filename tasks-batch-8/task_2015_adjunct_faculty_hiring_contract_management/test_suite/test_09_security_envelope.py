"""Authentication/authorization gates, request-schema errors, pagination envelope,
and the entity versioning layer (PRD Sections 2.1-2.3, 2.5, 2.8)."""
from test_helpers import (
    ABSENT_UUID,
    ApiErrorId,
    add_credential,
    assert_version_incremented,
    create_application,
    create_department,
    create_fall_term,
    create_open_posting,
    create_payroll_period,
    create_section,
    get_success_data,
    hire_faculty,
    is_iso8601_timestamp,
    lock_period,
    set_clock,
    start_review,
    validate_error,
    validate_paginated,
    validate_success,
    evaluation_payload,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["hr_admin_headers"]
REV1 = TEST_USERS["hr_reviewer_1_headers"]
REV2 = TEST_USERS["hr_reviewer_2_headers"]
CHAIR = TEST_USERS["chair_headers"]
DEAN = TEST_USERS["dean_headers"]
PAYROLL = TEST_USERS["payroll_headers"]


class TestAuthentication:
    def test_unauthenticated_missing_role_header(self, api):
        """PRD Section 2.1: "A request that is missing either header, presents a
        malformed header, or names a role the system does not declare is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_role_header
        """
        resp = api.list_departments(headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_existence_check_precedes_state_check(self, api, chair_headers):
        """PRD Section 2.5: "an unresolvable identifier anywhere in the path fails
        the request with `ERR_NOT_FOUND` before any query parameter or body field
        is examined."
        PRD Section 2.8: "A request that violates several rules at once receives
        exactly one error: the checks below run in a fixed order and the first
        failing check wins."

        Design: Corner/validations/existence_check_precedes_state_check
        """
        resp = api.cancel_section(
            ABSENT_UUID, {"cancellation_reason": "PROGRAM_CUT"}, chair_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRoleDenial:
    def test_chair_cannot_verify_credentials(self, api, chair_headers):
        """PRD Section 2.1: "A request that authenticates cleanly but whose role is
        not listed for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD Section 4: POST /adjunct-hr/credentials/{id}/verify is authorized for
        HRReviewer only.

        Design: Corner/rbac/chair_cannot_verify_credentials
        """
        set_clock("2026-06-01T00:00:00Z")
        dept = create_department(code="RBC2", contact_hour_value=1.00)
        create_fall_term()
        posting = create_open_posting(dept["id"], term_code="2026FA",
                                      min_education_tier="BACHELORS")
        application = create_application(
            posting["id"], applicant_name="Jax Adjunct",
            applicant_email="jax@x.edu", claimed_education_tier="BACHELORS")
        start_review(application["id"])
        cred = add_credential(application["id"], "TRANSCRIPT", tier="BACHELORS")

        denied = api.verify_credential(cred["id"], chair_headers)
        validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = get_success_data(api.get_credential(cred["id"], REV1))
        assert after["verification_status"] == "PENDING", "denied call mutates nothing"

    def test_dean_cannot_run_payroll_close_and_payroll_cannot_post_evaluations(self, api):
        """PRD Section 2.1: "A request that authenticates cleanly but whose role is
        not listed for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD Section 4: POST /adjunct-hr/payroll-periods/{id}/close is authorized for
        PayrollOfficer only; POST /adjunct-hr/evaluations is authorized for Dean
        only.

        Design: Corner/rbac/dean_cannot_run_payroll_close_and_payroll_cannot_post_evaluations
        """
        set_clock("2026-06-01T00:00:00Z")
        dept = create_department(code="XDNY", contact_hour_value=1.00)
        create_fall_term()
        faculty = hire_faculty(dept["id"], tier="BACHELORS",
                               min_education_tier="BACHELORS",
                               applicant_name="Kay Adjunct",
                               applicant_email="kay@x.edu")["faculty"]
        period = create_payroll_period("2026FA-P1", "2026-08-24", "2026-09-20")
        lock_period(period["id"])

        close_as_dean = api.close_payroll_period(period["id"], DEAN)
        validate_error(close_as_dean, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        eval_as_payroll = api.create_evaluation(
            evaluation_payload(faculty["id"], term_code="2026FA"), PAYROLL)
        validate_error(eval_as_payroll, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestSharedReads:
    def test_get_endpoints_shared_across_all_roles(
        self, api, payroll_headers, dean_headers, hr_reviewer_1_headers
    ):
        """PRD Section 2.1: "Read access is shared: every GET endpoint accepts all
        five roles."

        Design: Corner/rbac/get_endpoints_shared_across_all_roles
        """
        dept = create_department(code="SHRD", name="SharedDept", contact_hour_value=1.00)
        for headers in (payroll_headers, dean_headers, hr_reviewer_1_headers):
            data = validate_success(api.get_department(dept["id"], headers), 200)
            assert data["code"] == "SHRD"


class TestRequestSchema:
    def test_invalid_enum_and_missing_required_field(self, api, hr_admin_headers):
        """PRD Section 2.8: "`ERR_INVALID_REQUEST` (400) — request body schema:
        required fields present, enum members valid, numeric ranges respected,
        dates well-formed. Applies to every endpoint."
        PRD Section 3.2: credential levels are `BACHELORS`, then `MASTERS`, then
        `DOCTORATE` — "PHD" is not a member.

        Design: Corner/validations/invalid_enum_and_missing_required_field
        """
        dept = create_department(code="ENUM", name="EnumDept", contact_hour_value=1.00)
        bad_enum = api.create_rate_schedule(
            {
                "department_id": dept["id"],
                "education_tier": "PHD",
                "rate_basis": "PER_COURSE",
                "base_rate_cents": 450000,
                "longevity_step_cents": 0,
                "longevity_step_cap": 0,
                "effective_start_date": "2026-08-01",
                "effective_end_date": "2027-01-31",
            },
            hr_admin_headers,
        )
        validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST)

        missing_field = api.create_department(
            {"code": "NOMV", "name": "NoChvDept"}, hr_admin_headers)
        validate_error(missing_field, ApiErrorId.ERR_INVALID_REQUEST)


class TestPaginationEnvelope:
    def test_list_pagination_defaults_and_envelope(self, api, hr_admin_headers):
        """PRD Section 2.3: "List endpoints paginate with two query parameters:
        `limit` defaults to 10, accepts a minimum of 1 and a maximum of 100;
        `offset` defaults to 0. List results sort by `created_at` ascending. The
        `meta` block of every list response carries `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD Section 2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Design: Corner/endpoints/list_pagination_defaults_and_envelope
        """
        for i in range(1, 13):
            create_department(code=f"PG{i:02d}", name=f"Dept{i:02d}",
                              contact_hour_value=1.00)

        first_page = api.list_departments(hr_admin_headers)
        body = first_page.json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"]["api_request_id"], str)
        data, meta = validate_paginated(first_page)
        assert len(data) == 10, "default limit is 10"
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_departments(hr_admin_headers, params={"limit": 2, "offset": 2}))
        assert len(page2) == 2, "limit=2 pages deterministically"
        assert meta2["has_more"] is True, "rows remain past offset 2 + 2"

        last_page, meta3 = validate_paginated(
            api.list_departments(hr_admin_headers, params={"limit": 2, "offset": 11}))
        assert len(last_page) == 1, "offset 11 of 12 returns exactly one row"
        assert meta3["has_more"] is False


class TestVersioningLayer:
    def test_version_increments_on_every_mutation(self, api, chair_headers):
        """PRD Section 2.5: "All entities except payroll entries and evaluation
        records additionally carry `updated_at`, refreshed on every mutation, and
        `version`, an integer that increments by one on every mutation of the
        record, including state transitions and partial updates."
        PRD Section 3.5: "While it is `SCHEDULED` or `RUNNING`, the chair may patch
        its `enrollment` — and only its `enrollment` — with each patch bumping the
        section's `version`."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        set_clock("2026-06-01T00:00:00Z")
        dept = create_department(code="VERX", contact_hour_value=1.00)
        create_fall_term()
        section = create_section(dept["id"], term_code="2026FA", course_code="VER-101",
                                 weekly_contact_hours=3.0, enrollment=20)
        v_created = section["version"]

        patched = validate_success(api.patch_section(
            section["id"], {"enrollment": 17}, chair_headers), 200)
        assert_version_incremented(patched["version"], v_created)
        assert patched["version"] == v_created + 1, "exactly +1 on the enrollment patch"
        assert is_iso8601_timestamp(patched["updated_at"])

        cancelled = validate_success(api.cancel_section(
            section["id"], {"cancellation_reason": "PROGRAM_CUT"}, chair_headers), 200)
        assert cancelled["version"] == patched["version"] + 1, (
            "exactly +1 on the cancel state transition"
        )
