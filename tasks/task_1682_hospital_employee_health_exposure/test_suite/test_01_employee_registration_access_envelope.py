"""Employee registration, access control, response envelope, and pagination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_employee,
    assert_instant,
    build_user_headers,
    create_employee_payload,
    is_valid_uuid,
    register_employee,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEmployeeCreation:
    def test_employee_create_returns_system_defaults(self, api, nurse_headers,
                                                     compliance_headers):
        """PRD §3.1: "A newly registered employee begins with `status`
        `PREPLACEMENT`, a `compliance_posture` of `CLEAR`, and both
        `active_hold_count` and `open_restriction_count` at zero."
        PRD §2.4: "All "now" semantics resolve against a logical clock whose
        startup default is exactly 2026-08-01T00:00:00Z."

        Design: Corner/entities/employee_create_success_defaults
        """
        resp = api.create_employee(
            create_employee_payload(
                employee_ref="E-EN1", full_name="New Hire",
                hire_date="2025-01-05T00:00:00Z",
            ),
            nurse_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_employee(data)
        assert data["status"] == "PREPLACEMENT"
        assert data["compliance_posture"] == "CLEAR"
        assert data["active_hold_count"] == 0
        assert data["open_restriction_count"] == 0
        assert is_valid_uuid(data["id"])
        # Created against the logical clock startup default.
        assert_instant(data["created_at"], "2026-08-01T00:00:00")

        # Immediate read-back returns the same state.
        read = validate_success(api.get_employee(data["id"], compliance_headers))
        assert read["employee_ref"] == "E-EN1"
        assert read["status"] == "PREPLACEMENT"

    def test_employee_create_missing_employee_ref_rejected(self, api, nurse_headers):
        """PRD §2.8: "required fields present, enum values among declared members,
        interval ends no earlier than starts, and justification lengths
        (`ERR_INVALID_REQUEST`, `ERR_INVALID_ENUM`,
        `ERR_INSUFFICIENT_JUSTIFICATION`, `ERR_DECLINATION_REASON_REQUIRED`,
        all HTTP 400)."
        PRD §3.1: the nurse registers each hire "by supplying an
        `employee_ref`".

        Design: Corner/entities/employee_create_missing_required_returns_invalid_request
        """
        payload = create_employee_payload(full_name="No Ref")
        payload.pop("employee_ref")
        resp = api.create_employee(payload, nurse_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        data, meta = validate_paginated(api.list_employees(nurse_headers))
        assert meta["total_count"] == 0 and data == []

    def test_employee_duplicate_ref_rejected(self, api, nurse_headers):
        """PRD §3.1: "An `EmployeeHealthNurse` registers each new hire with the
        health office by supplying an `employee_ref` — the hospital's unique HR
        badge reference, rejected with `ERR_DUPLICATE_EMPLOYEE_REF` when it
        collides with an already-registered reference"

        Design: Corner/entities/employee_duplicate_ref_rejected
        """
        first = api.create_employee(
            create_employee_payload(employee_ref="E-DUP", full_name="First One"),
            nurse_headers,
        )
        validate_success(first, expected_status=201)

        second = api.create_employee(
            create_employee_payload(
                employee_ref="E-DUP", full_name="Second One",
                job_category="TECH", department="LAB",
            ),
            nurse_headers,
        )
        validate_error(second, ApiErrorId.ERR_DUPLICATE_EMPLOYEE_REF)

        _data, meta = validate_paginated(api.list_employees(nurse_headers))
        assert meta["total_count"] == 1


class TestEmployeeListing:
    def test_employee_list_pagination_envelope(self, api, nurse_headers,
                                               compliance_headers):
        """PRD §2.3: "List endpoints accept the query parameters `limit` and
        `offset`." and "The `meta` object of a list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/employee_list_pagination_envelope
        """
        for ref, name in (("E-PG1", "Pg One"), ("E-PG2", "Pg Two"), ("E-PG3", "Pg Three")):
            register_employee(ref, full_name=name)

        page1, meta1 = validate_paginated(
            api.list_employees(compliance_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_employees(compliance_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2


class TestResponseEnvelope:
    def test_success_and_error_envelope_shapes(self, api, nurse_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body" and
        "All error API responses (4xx status codes) follow this standard
        envelope format"; "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/endpoints/response_envelope_shape_object_and_error
        """
        ok = api.create_employee(
            create_employee_payload(employee_ref="E-P1", full_name="Env Elope"),
            nurse_headers,
        )
        assert ok.status_code == 201
        body = ok.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert is_valid_uuid(body["data"]["id"])

        dup = api.create_employee(
            create_employee_payload(employee_ref="E-P1", full_name="Env Elope Again"),
            nurse_headers,
        )
        err = validate_error(dup, ApiErrorId.ERR_DUPLICATE_EMPLOYEE_REF)
        assert dup.json()["response_type"] == "error"
        assert isinstance(err["message"], str) and err["message"].strip()


class TestExistenceAndAuthOrdering:
    def test_screening_get_unknown_id_returns_not_found(self, api, nurse_headers):
        """PRD §2.6: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404)
        at the first path identifier that does not resolve to an existing
        resource, before any later identifier or any business rule is
        considered."

        Design: Corner/entities/screening_get_not_found_returns_404
        """
        resp = api.get_screening(NON_EXISTENT_UUID, nurse_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_undeclared_role_rejected_before_existence_check(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this declared set, is rejected with `ERR_MISSING_AUTH_CONTEXT`."
        PRD §2.8: "Every endpoint applies its checks in a single pinned order,
        and a failure surfaces the error of the earliest failing category
        rather than a later one."

        Design: Corner/validations/invalid_role_beats_not_found
        """
        bogus = build_user_headers("user-x", "SuperUser")
        resp = api.get_employee(NON_EXISTENT_UUID, bogus)
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_CONTEXT)

    def test_forbidden_role_on_employee_create(self, api, compliance_headers,
                                               nurse_headers):
        """PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /employee-health/employees is authorized for
        EmployeeHealthNurse only.

        Design: Corner/validations/forbidden_role_on_employee_create
        """
        resp = api.create_employee(
            create_employee_payload(employee_ref="E-V2", full_name="Wrong Role"),
            compliance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        _data, meta = validate_paginated(api.list_employees(nurse_headers))
        assert meta["total_count"] == 0

    def test_undeclared_enum_member_rejected(self, api, nurse_headers):
        """PRD §3.1: "`job_category` (one of `NURSE`, `PHYSICIAN`, `TECH`,
        `HOUSEKEEPING`, or `OTHER`)".
        PRD §2.8: "required fields present, enum values among declared members,
        interval ends no earlier than starts, and justification lengths
        (`ERR_INVALID_REQUEST`, `ERR_INVALID_ENUM`,
        `ERR_INSUFFICIENT_JUSTIFICATION`, `ERR_DECLINATION_REASON_REQUIRED`,
        all HTTP 400)."

        Design: Corner/validations/invalid_enum_rejected
        """
        resp = api.create_employee(
            create_employee_payload(employee_ref="E-V11", job_category="SUPER_NURSE"),
            nurse_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)

        _data, meta = validate_paginated(api.list_employees(nurse_headers))
        assert meta["total_count"] == 0


class TestExclusiveRoleDenials:
    def test_role_denials_across_exclusive_endpoints(self, api, nurse_headers,
                                                     physician_headers):
        """PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: screening decide is EmployeeHealthPhysician-only; the clock is
        ComplianceOfficer-only; employee creation is EmployeeHealthNurse-only.

        Design: Corner/rbac/role_denials_across_exclusive_endpoints
        """
        emp = register_employee("E-RB2", full_name="Role Test")
        scr = api.create_screening(
            emp["id"], {"expected_employee_version": emp["version"]}, nurse_headers
        )
        scr_id = validate_success(scr, expected_status=201)["id"]

        # Nurse attempting the physician-exclusive clearance decision.
        r1 = api.decide_screening(scr_id, {"outcome": "CLEARED"}, nurse_headers)
        validate_error(r1, ApiErrorId.ERR_FORBIDDEN_ROLE)

        # Physician attempting the ComplianceOfficer-exclusive clock advance.
        r2 = api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, physician_headers)
        validate_error(r2, ApiErrorId.ERR_FORBIDDEN_ROLE)

        # StaffEmployee attempting the nurse-exclusive employee creation.
        staff = build_user_headers(emp["id"], "StaffEmployee")
        r3 = api.create_employee(
            create_employee_payload(employee_ref="E-RB2X", full_name="Staff Try"),
            staff,
        )
        validate_error(r3, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestStaffEmployeeSelfScope:
    def test_staff_employee_reads_only_own_record(self, api, nurse_headers):
        """PRD §2.1: "A `StaffEmployee` therefore sees only their own rows on
        list endpoints, may read only their own employee record, and is
        rejected with `ERR_OWNERSHIP_REQUIRED` when acting on or reading
        another employee's records."

        Design: Corner/rbac/staff_employee_reads_only_own_record
        """
        emp1 = register_employee("E-RB1A", full_name="Self One")
        emp2 = register_employee("E-RB1B", full_name="Other Two", job_category="TECH",
                                 department="LAB")
        staff1 = build_user_headers(emp1["id"], "StaffEmployee")

        other = api.get_employee(emp2["id"], staff1)
        validate_error(other, ApiErrorId.ERR_OWNERSHIP_REQUIRED)

        own = validate_success(api.get_employee(emp1["id"], staff1))
        assert own["employee_ref"] == "E-RB1A"


class TestLogicalClock:
    def test_clock_regression_rejected(self, api, compliance_headers, nurse_headers):
        """PRD §2.4: "the supplied instant must be strictly after the current
        logical time, and a regression or equality is rejected with
        `ERR_CLOCK_REGRESSION`."

        Design: Corner/validations/clock_regression_rejected
        """
        resp = api.set_clock({"to_iso8601": "2026-07-01T00:00:00Z"}, compliance_headers)
        validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)

        # The clock did not move: a subsequent create is stamped at the
        # startup default 2026-08-01T00:00:00Z.
        emp = register_employee("E-CLK1", full_name="Clock Check")
        assert_instant(emp["created_at"], "2026-08-01T00:00:00")
