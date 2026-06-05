"""Corner — entities section: creation, required fields, defaults, NOT_FOUND,
listing/pagination, FK resolution.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_employee,
    create_employee_payload,
    create_employer,
    create_employer_payload,
    set_clock,
    submit_case,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEmployerCreateMinimalRequiredFieldsSucceeds:
    def test_employer_create_returns_201_with_pfl_enabled_for_ca(self, api):
        """PRD §3.1: "At creation, the server computes `pfl_enabled` from the worksite state: it is true when `state_code` is one of `CA`, `NY`, `NJ`, `MA`, `WA`, `CT`, `RI`, `CO`, `OR` and false when `state_code` is `FED`"
        PRD §2.4: "`version` (an integer that begins at 1 on creation and increments by exactly one on every server-side mutation that modifies a non-system field of the resource)"
        PRD §3.1: "The `fmla_method` is an optional input that defaults to `ROLLING_BACKWARD`"

        Design: Corner/entities/employer_create_minimal_required_fields_succeeds
        """
        res = api.create_employer(
            create_employer_payload(
                legal_name="Acme",
                state_code="CA",
                employer_premium_share_pct=0.75,
                monthly_premium_total_cents=90000,
            ),
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["legal_name"] == "Acme"
        assert data["state_code"] == "CA"
        assert data["pfl_enabled"] is True
        assert data["version"] == 1
        assert data["fmla_method"] == "ROLLING_BACKWARD"


class TestEmployerCreateFedStatePflDisabled:
    def test_employer_with_state_fed_has_pfl_enabled_false(self, api):
        """PRD §3.1: "At creation, the server computes `pfl_enabled` from the worksite state: it is true when `state_code` is one of `CA`, `NY`, `NJ`, `MA`, `WA`, `CT`, `RI`, `CO`, `OR` and false when `state_code` is `FED`"

        Design: Corner/entities/employer_create_fed_state_pfl_disabled
        """
        res = api.create_employer(
            create_employer_payload(
                legal_name="FedOnly",
                state_code="FED",
                employer_premium_share_pct=0.50,
                monthly_premium_total_cents=80000,
            ),
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["pfl_enabled"] is False, (
            f"FED is not in PFL set; pfl_enabled must be false. Got {data['pfl_enabled']!r}"
        )


class TestEmployerGetNotFound:
    def test_get_employer_with_unknown_id_returns_not_found(self, api):
        """PRD §2.5: "When a path contains multiple `{id}` segments, each segment is resolved in order; the first unresolved id yields `ERR_NOT_FOUND` (HTTP 404)"

        Design: Corner/entities/employer_get_not_found
        """
        res = api.get_employer(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestEmployeeMissingRequiredEmailReturnsInvalidRequest:
    def test_employee_create_missing_email_returns_invalid_request(self, api):
        """PRD §2.6: "(16) request-body well-formedness — required fields present, correct types, valid enum values — returning `ERR_INVALID_REQUEST`."

        Design: Corner/entities/employee_missing_required_email_returns_invalid_request
        """
        emp = create_employer()
        payload = create_employee_payload(emp["id"], email="x@x.com")
        payload.pop("email")
        res = api.create_employee(payload, TEST_USERS["hr_admin_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestEmployeeInvalidEmployerFkReturnsReferencedNotFound:
    def test_employee_create_with_unknown_employer_id_returns_referenced_not_found(self, api):
        """PRD §2.5: "Foreign-key references embedded in request bodies — any field whose name ends in `_id` — are resolved before any business validation runs; an unresolved body-side reference yields `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/employee_invalid_employer_fk_returns_referenced_not_found
        """
        res = api.create_employee(
            create_employee_payload(NON_EXISTENT_UUID, email="x@x.com"),
            TEST_USERS["hr_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND)


class TestEmployeeDefaultHealthPlanEnrolledTrue:
    def test_employee_create_omitting_health_plan_enrolled_defaults_to_true(self, api):
        """PRD §3.3: "the optional `health_plan_enrolled` flag (defaulting to true)"

        Design: Corner/entities/employee_default_health_plan_enrolled_true
        """
        emp_corp = create_employer(state_code="FED")
        payload = create_employee_payload(emp_corp["id"], email="d@x.com")
        # Default factory does not set health_plan_enrolled — PRD default = true.
        assert "health_plan_enrolled" not in payload
        res = api.create_employee(payload, TEST_USERS["hr_admin_headers"])
        data = validate_success(res, expected_status=201)
        assert data["health_plan_enrolled"] is True, (
            f"health_plan_enrolled defaults to true when omitted; got {data['health_plan_enrolled']!r}"
        )
        assert data["employment_status"] == "ACTIVE"


class TestLeaveCaseListPaginationFilterByEmployee:
    def test_list_leave_cases_filter_by_employee_id_returns_only_matching(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0, minimum 0)."
        PRD §2.3: "The pagination envelope in `meta` carries `limit`, `offset`, `total_count` (the unfiltered-by-window total of rows matching the query), and `has_more` (true when more rows exist after the current page)."

        Design: Corner/entities/leave_case_list_pagination_filter_by_employee
        """
        employer = create_employer(state_code="FED")
        w1 = create_employee(employer["id"], email="p1@x.com")
        w2 = create_employee(employer["id"], email="p2@x.com")
        set_clock("2026-05-01T00:00:00.000Z")
        submit_case(
            w1["id"],
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        submit_case(
            w2["id"],
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        res = api.list_cases(
            TEST_USERS["hr_admin_headers"],
            params={"employee_id": w1["id"], "limit": 10, "offset": 0},
        )
        data, meta = validate_paginated(res)
        assert len(data) == 1
        assert data[0]["employee_id"] == w1["id"]
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
