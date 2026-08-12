"""Employee roster basics, defaults, and the response envelope."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    create_employee_payload, setup_employee, setup_manager, setup_report,
    assert_employee, assert_instant_equals, DEFAULT_CLOCK_ISO,
)

ADMIN = TEST_USERS["admin_headers"]


class TestEmployeeCreationDefaults:
    def test_employee_creation_applies_defaults_and_system_fields(self, api):
        """PRD §3.1: "The optional `demographic_group` records one of `GROUP_A`,
        `GROUP_B`, `GROUP_C`, `GROUP_D`, or `UNDISCLOSED`, defaulting to
        `UNDISCLOSED` when omitted"
        PRD §3.1: "A new employee starts with `employment_status` `ACTIVE`, an
        empty `rating_history` (an append-only list of rating records, latest
        entry last, written exclusively by calibration finalization), and derived
        flags computed from the rest of the system: `is_high_potential` is true
        exactly when the employee holds a nomination in `ACTIVE` or `UNDER_REVIEW`
        status, and `active_hold_count` counts the employee's applications
        currently sitting in `MANAGER_HOLD`"
        PRD §2.4: "At startup the logical clock reads exactly
        `2026-05-01T00:00:00Z`; before any explicit adjustment it continues to
        read this default."

        Design: Corner/entities/employee_creation_applies_defaults_and_system_fields
        """
        resp = api.create_employee({
            "employee_code": "E100",
            "full_name": "Amy New",
            "department": "ENG",
            "job_level": 4,
            "hire_date": "2023-06-01",
            "performance_rating": "SOLID",
        }, ADMIN)
        data = validate_success(resp, 201)
        assert_employee(data)
        assert data["demographic_group"] == "UNDISCLOSED", (
            "omitted demographic_group must default to UNDISCLOSED"
        )
        assert data["employment_status"] == "ACTIVE"
        assert data["is_high_potential"] is False
        assert data["active_hold_count"] == 0
        assert data["rating_history"] == []
        assert is_valid_uuid(data["id"])
        assert_instant_equals(data["created_at"], DEFAULT_CLOCK_ISO)


class TestEmployeeValidation:
    def test_employee_create_missing_required_returns_invalid_request(self, api):
        """PRD §2.8: "Request-body well-formedness — required fields present,
        enum members valid, no undeclared fields (a field absent from the
        endpoint's input schema, such as `assessment_method` on a role update,
        is rejected), and scalar constraints such as `job_level` lying within 1
        through 10, `completion_pct` within 0 through 100, `planned_close_date`
        not earlier than `planned_open_date`, and `scheduled_end` later than
        `scheduled_start` — failure yields `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/employee_create_missing_required_returns_invalid_request
        """
        resp = api.create_employee({
            "full_name": "No Code",
            "department": "ENG",
            "job_level": 4,
            "hire_date": "2023-06-01",
            "performance_rating": "SOLID",
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_employee_create_invalid_enum_returns_invalid_request(self, api):
        """PRD §2.8: "Request-body well-formedness — required fields present,
        enum members valid, no undeclared fields (a field absent from the
        endpoint's input schema, such as `assessment_method` on a role update,
        is rejected), and scalar constraints such as `job_level` lying within 1
        through 10, `completion_pct` within 0 through 100, `planned_close_date`
        not earlier than `planned_open_date`, and `scheduled_end` later than
        `scheduled_start` — failure yields `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "the current `performance_rating` — one of `LOW`, `SOLID`,
        `STRONG`, or `EXCEPTIONAL`."

        Design: Corner/entities/employee_create_invalid_enum_returns_invalid_request
        """
        bad_enum = api.create_employee({
            "employee_code": "E101",
            "full_name": "Bad Enum",
            "department": "ENG",
            "job_level": 4,
            "hire_date": "2023-06-01",
            "performance_rating": "GREAT",
        }, ADMIN)
        validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST, 400)

        undeclared = api.create_employee({
            "employee_code": "E102",
            "full_name": "Computed Inject",
            "department": "ENG",
            "job_level": 4,
            "hire_date": "2023-06-01",
            "performance_rating": "SOLID",
            "is_high_potential": True,
        }, ADMIN)
        validate_error(undeclared, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestEmployeeLookup:
    def test_employee_get_unknown_id_returns_not_found(self, api):
        """PRD §2.8: "4. Path identifier resolution — failure yields
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/employee_get_unknown_id_returns_not_found
        """
        resp = api.get_employee(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestEmployeeListing:
    def test_employee_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of
        1 and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "Paginated list-based responses include the following fields
        in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD §2.3: "Unless otherwise specified, all list endpoints return
        resources sorted by their creation timestamp in ascending order."

        Design: Corner/entities/employee_list_pagination_envelope
        """
        e1 = setup_employee(employee_code="P1", full_name="Pa One")
        e2 = setup_employee(employee_code="P2", full_name="Pa Two")
        e3 = setup_employee(employee_code="P3", full_name="Pa Three")

        page1, meta1 = validate_paginated(api.list_employees(ADMIN, params={"limit": 2}))
        assert len(page1) == 2, f"page 1 must hold exactly 2 items, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert [e["id"] for e in page1] == [e1["id"], e2["id"]], (
            "page 1 must hold the two earliest-created employees in creation order"
        )

        page2, meta2 = validate_paginated(
            api.list_employees(ADMIN, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1, f"page 2 must hold exactly 1 item, got {len(page2)}"
        assert meta2["has_more"] is False
        assert page2[0]["id"] == e3["id"]

    def test_employee_manager_self_reference_reverse_reachable(self, api):
        """PRD §3.1: "The optional `current_manager_id` establishes the
        self-referential reporting line and must reference an existing employee
        whose `employment_status` is `ACTIVE`, or be null for top-of-chain
        employees."
        PRD §3.1: "The roster can be listed with filters on `department`,
        `employment_status`, or `current_manager_id`."

        Design: Corner/entities/employee_manager_self_reference_reverse_reachable
        """
        manager, _ = setup_manager(employee_code="M100", full_name="Mara Boss")
        r1 = setup_report(manager["id"], employee_code="R100", full_name="Rep One")
        r2 = setup_report(manager["id"], employee_code="R101", full_name="Rep Two")
        setup_employee(employee_code="U100", full_name="Una Related")

        data, meta = validate_paginated(
            api.list_employees(ADMIN, params={"current_manager_id": manager["id"]})
        )
        returned = {e["id"] for e in data}
        assert returned == {r1["id"], r2["id"]}, (
            f"Expected exactly the two reports, got {returned}"
        )
        assert meta["total_count"] == 2


class TestErrorEnvelope:
    def test_error_response_envelope_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/error_response_envelope_shape
        """
        resp = api.get_employee(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN,
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
            "error meta must contain only api_request_id and api_request_timestamp"
        )
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
