"""Auth headers, role authorization, response envelopes, pagination, and
seeding endpoints (Departments, Handlers, CategoryRules).

PRD §2.1, §2.2, §2.3, §2.4, §2.5, §3.1.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PA, HO, DISP, SUP, SA,
    TEST_USERS,
    assert_category_rule,
    assert_department,
    assert_handler,
    create_category_rule,
    create_category_rule_payload,
    create_department,
    create_department_payload,
    create_handler,
    create_handler_payload,
    unique_category_code,
    unique_department_code,
    unique_jurisdiction_code,
    unique_sub_category_code,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth header presence (PRD §2.1)
# ===========================================================================
class TestAuthHeadersRequired:
    """PRD §2.1: 'Every request to the API must carry two headers:
    X-User-Role, naming the role making the call, and X-User-ID, naming
    the specific actor. Either header missing — or X-User-Role carrying
    a string that is not one of the recognised roles — is rejected with
    ERR_AUTH_MISSING (401).'
    """

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: 'Either header missing... is rejected with
        ERR_AUTH_MISSING (401).'"""
        res = api.create_department(
            create_department_payload(),
            {"X-User-ID": "some-id"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'Either header missing... is rejected with
        ERR_AUTH_MISSING (401).'"""
        res = api.create_department(
            create_department_payload(),
            {"X-User-Role": "PlatformAdmin"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_unrecognised_role_rejected(self, api):
        """PRD §2.1: 'X-User-Role carrying a string that is not one of
        the recognised roles — is rejected with ERR_AUTH_MISSING (401).'
        """
        res = api.create_department(
            create_department_payload(),
            {"X-User-Role": "Sysadmin", "X-User-ID": "x"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)


# ===========================================================================
# Role authorisation (PRD §2.1, §4)
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: 'A recognised role acting on an endpoint outside its
    permitted set is rejected with ERR_FORBIDDEN (403).'
    """

    def test_hotline_operator_cannot_create_department(self, api):
        """PRD §4: 'POST /departments — Register a department —
        PlatformAdmin'."""
        res = api.create_department(create_department_payload(), HO)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_dispatcher_cannot_create_handler(self, api):
        """PRD §4: 'POST /handlers — Register a handler within a
        department — PlatformAdmin'."""
        dept = create_department()
        res = api.create_handler(
            create_handler_payload(department_id=dept["id"]), DISP,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_supervisor_cannot_classify_work_order(self, api):
        """PRD §4: 'POST /work-orders/{id}/classify — ... — Dispatcher'."""
        res = api.classify_work_order(NON_EXISTENT_UUID,
                                      {"mode": "RULE_BASED"}, SUP)
        # ERR_FORBIDDEN must precede the not-found.
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_survey_agent_cannot_register_work_order(self, api):
        """PRD §4: 'POST /work-orders — Register a call... —
        HotlineOperator'."""
        res = api.create_work_order(
            {"jurisdiction_code": "J0001",
             "category_code": "X", "sub_category_code": "Y",
             "content_text": "x"},
            SA,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Response envelope shape (PRD §2.2)
# ===========================================================================
class TestEnvelopeShape:
    """PRD §2.2: 'All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body.'
    """

    def test_success_envelope_has_meta_response_type_data(self, api):
        """PRD §2.2: 'response_type is either "object" for a single
        resource or "array" for a list of resources.'"""
        res = api.create_department(create_department_payload(), PA)
        body = res.json()
        assert "meta" in body and "response_type" in body and "data" in body
        assert body["response_type"] == "object"
        meta = body["meta"]
        assert meta.get("api_request_id", "").startswith("req_"), (
            "api_request_id must start with 'req_'"
        )
        assert "api_request_timestamp" in meta

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: 'The error_id is a unique, machine-readable string
        that identifies the specific error. The message provides a
        human-readable explanation of what went wrong.'"""
        res = api.create_department(create_department_payload(), HO)
        assert res.status_code == 403
        body = res.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_FORBIDDEN"
        assert isinstance(body["data"].get("message"), str)


# ===========================================================================
# Pagination (PRD §2.3)
# ===========================================================================
class TestPagination:
    """PRD §2.3: 'limit defaults to 10, has a minimum of 1, and a maximum
    of 100; values outside this range fail field validation. offset
    defaults to 0 and has no upper bound apart from the integer domain.'
    """

    def test_default_limit_is_ten(self, api):
        """PRD §2.3: 'limit defaults to 10'."""
        # Ensure at least 1 department.
        create_department()
        resp = api.list_departments(PA)
        _data, meta = validate_paginated(resp)
        assert meta["limit"] == 10

    def test_limit_above_max_rejected(self, api):
        """PRD §2.3: 'limit... has a... maximum of 100; values outside
        this range fail field validation.'"""
        resp = api.list_departments(PA, params={"limit": 101})
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_limit_below_min_rejected(self, api):
        """PRD §2.3: 'limit... has a minimum of 1... values outside
        this range fail field validation.'"""
        resp = api.list_departments(PA, params={"limit": 0})
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_has_more_true_when_offset_plus_limit_less_than_total(self, api):
        """PRD §2.3: 'has_more is true precisely when offset + limit <
        total_count.'"""
        for _ in range(3):
            create_department()
        resp = api.list_departments(PA, params={"limit": 1, "offset": 0})
        _data, meta = validate_paginated(resp)
        if meta["total_count"] >= 2:
            assert meta["has_more"] is True


# ===========================================================================
# Department CRUD (PRD §3.1)
# ===========================================================================
class TestDepartmentCRUD:
    """PRD §3.1: 'A Department is created with a name, a stable
    kebab-case code... a list of jurisdiction_codes... and a list of
    category_codes it is responsible for.'"""

    def test_create_department_returns_versioned_resource(self, api):
        """PRD §2.4: 'version is a non-negative integer that starts at 1
        on creation.' PRD §3.1: Department fields."""
        payload = create_department_payload()
        resp = api.create_department(payload, PA)
        data = validate_success(resp, expected_status=201)
        assert_department(data)
        assert data["version"] == 1
        assert data["status"] == "ACTIVE", (
            "PRD §3.1: 'The department's status defaults to ACTIVE.'"
        )
        assert data["pending_work_count"] == 0, (
            "PRD §3.1: 'A computed pending_work_count... starts at zero.'"
        )

    def test_create_department_invalid_code_rejected(self, api):
        """PRD §3.1: 'code (matching the pattern of a leading lowercase
        letter followed by lowercase letters, digits, and hyphens, total
        length 2 to 40 characters, unique across the table)'."""
        payload = create_department_payload(code="A_BAD_CODE")
        res = api.create_department(payload, PA)
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_get_department_includes_pending_work_count(self, api):
        """PRD §4: 'GET /departments/{id} — Retrieve a department
        including its pending_work_count.'"""
        d = create_department()
        resp = api.get_department(d["id"], PA)
        data = validate_success(resp)
        assert "pending_work_count" in data
        assert data["pending_work_count"] == 0

    def test_get_unknown_department_404_with_resource_not_found(self, api):
        """PRD §2.5: 'A missing Department... referenced directly
        through a top-level path segment yields the generic
        ERR_RESOURCE_NOT_FOUND (404).'"""
        resp = api.get_department(NON_EXISTENT_UUID, PA)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


# ===========================================================================
# Handler CRUD (PRD §3.1)
# ===========================================================================
class TestHandlerCRUD:
    """PRD §3.1: 'A Handler is bound to a department at creation time
    through the department_id field; the target department must exist
    and have status equal to ACTIVE.'"""

    def test_create_handler_with_active_department(self, api):
        """PRD §3.1: 'the target department must exist and have status
        equal to ACTIVE.'"""
        dept = create_department()
        resp = api.create_handler(
            create_handler_payload(department_id=dept["id"]), PA,
        )
        data = validate_success(resp, expected_status=201)
        assert_handler(data)
        assert data["department_id"] == dept["id"]
        assert data["status"] == "ACTIVE"
        assert data["open_assignment_count"] == 0

    def test_create_handler_unknown_department_id_rejected(self, api):
        """PRD §2.5: 'Body-referenced foreign keys (such as
        department_id...) that fail to resolve yield
        ERR_REFERENCE_NOT_FOUND (422).'"""
        resp = api.create_handler(
            create_handler_payload(department_id=NON_EXISTENT_UUID), PA,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ===========================================================================
# CategoryRule CRUD (PRD §3.1)
# ===========================================================================
class TestCategoryRuleCRUD:
    """PRD §3.1: 'A CategoryRule ties a (category_code,
    sub_category_code) pair... to a lead_department_code and a list of
    supporting_department_codes. The pair is unique.'"""

    def test_create_category_rule_returns_resource(self, api):
        """PRD §3.1: CategoryRule fields including time-limit constraints."""
        dept = create_department()
        payload = create_category_rule_payload(
            lead_department_code=dept["code"],
        )
        resp = api.create_category_rule(payload, PA)
        data = validate_success(resp, expected_status=201)
        assert_category_rule(data)
        assert data["category_code"] == payload["category_code"]

    def test_committed_time_limit_above_statutory_rejected(self, api):
        """PRD §2.7: 'the committed value must be less than or equal to
        the statutory value (so the committed deadline always lands at
        or before the statutory deadline for the same case).'"""
        dept = create_department()
        payload = create_category_rule_payload(
            lead_department_code=dept["code"],
            statutory_time_limit_hours=24,
            committed_time_limit_hours=48,
        )
        resp = api.create_category_rule(payload, PA)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_lead_must_be_existing_department_code(self, api):
        """PRD §3.1: 'The lead code must reference a department whose
        status is ACTIVE at creation time.'"""
        payload = create_category_rule_payload(
            lead_department_code="nonexistent-lead-zzz",
        )
        resp = api.create_category_rule(payload, PA)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)

    def test_supporting_must_not_include_lead(self, api):
        """PRD §3.1: 'Supporting codes... must not include the lead
        code, and are deduplicated.'"""
        dept = create_department()
        payload = create_category_rule_payload(
            lead_department_code=dept["code"],
            supporting_department_codes=[dept["code"]],
        )
        resp = api.create_category_rule(payload, PA)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
