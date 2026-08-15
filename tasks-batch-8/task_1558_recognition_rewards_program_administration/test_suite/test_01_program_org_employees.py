"""Program creation defaults, employee registration, and generic envelope claims."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_employee,
    assert_program,
    create_department,
    create_employee,
    create_employee_payload,
    create_program,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProgramCreationDefaults:
    def test_program_creation_applies_documented_defaults(self, api, hr_admin_headers):
        """PRD §3.1: "A recognition program begins life in `DRAFT` status."
        PRD §3.1: "`nomination_review_sla_days`, defaulting to 14, sets how many
        days a nomination may sit in review before it auto-expires.
        `duplicate_window_days`, defaulting to 30, sets the look-back window for
        duplicate-nomination detection. `velocity_limit_per_7_days`, defaulting
        to 5, caps how many nominations one nominator may file in any trailing
        seven-day window."
        PRD §3.1: "`state_rate_map` and `grossup_enabled` — the latter defaulting
        to false — drive tax treatment in §3.6" and "`accrual_method`, defaulting
        to `STRAIGHT_LINE`, together with `fiscal_year_start_month` drives monthly
        accruals in §3.7."

        Design: Corner/entities/program_creation_applies_defaults
        """
        created = create_program()
        program = validate_success(api.get_program(created["id"], hr_admin_headers), 200)
        assert_program(program)
        assert program["status"] == "DRAFT"
        assert program["accrual_method"] == "STRAIGHT_LINE"
        assert program["velocity_limit_per_7_days"] == 5
        assert program["duplicate_window_days"] == 30
        assert program["nomination_review_sla_days"] == 14
        assert program["grossup_enabled"] is False
        assert program["version"] == 1


class TestEmployeeRegistration:
    def test_new_employee_starts_with_zeroed_computed_balances(
        self, api, hr_admin_headers
    ):
        """PRD §3.1: "A newly registered employee starts with `program_status`
        `ELIGIBLE`, `recognition_tier` `BRONZE`, zero `available_points`,
        `held_points`, `lifetime_granted_points`, `lifetime_redeemed_points`,
        and `lifetime_expired_points`, and zero year-to-date tax accumulators."

        Design: Corner/entities/employee_creation_computed_input_ignored
        """
        dept = create_department()
        res = api.create_employee(
            create_employee_payload(
                dept["id"], available_points=9999, recognition_tier="PLATINUM",
            ),
            hr_admin_headers,
        )
        employee = validate_success(res, 201)
        assert_employee(employee)
        assert employee["available_points"] == 0
        assert employee["held_points"] == 0
        assert employee["lifetime_granted_points"] == 0
        assert employee["lifetime_redeemed_points"] == 0
        assert employee["lifetime_expired_points"] == 0
        assert employee["ytd_supplemental_wages_cents"] == 0
        assert employee["ytd_de_minimis_cents"] == 0
        assert employee["recognition_tier"] == "BRONZE"
        assert employee["program_status"] == "ELIGIBLE"

    def test_employee_missing_state_code_rejected(self, api, hr_admin_headers):
        """PRD §2.8 stage 4: "Required fields are present, types are valid,
        enum members are valid, and integers are in range — including
        `points_requested` being at least 1 and at most the program's
        `max_points_per_nomination`, redemption `quantity` between 1 and 5
        inclusive (`ERR_INVALID_QUANTITY`), `period_month` between 1 and 12
        inclusive, and `tax_year` between 2000 and 2100 inclusive
        (`ERR_INVALID_TAX_YEAR`) — on all mutating endpoints
        (`ERR_INVALID_REQUEST` unless a more specific error applies)."
        PRD §3.1: "Employees are registered by an `HRAdmin` with a unique
        external `employee_ref` (a conflict is `ERR_INVALID_REQUEST`), a
        `full_name`, a home `department_id` used for budget and chargeback
        attribution, a nullable `manager_id` pointing at another employee, a
        `hire_date` in year-month-day form that drives anniversary milestones,
        and a two-letter `state_code` used for supplemental state tax lookup."

        Design: Corner/entities/employee_missing_required_field_returns_invalid_request
        """
        dept = create_department()
        payload = create_employee_payload(dept["id"])
        del payload["state_code"]
        res = api.create_employee(payload, hr_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        _, meta = validate_paginated(api.list_employees(hr_admin_headers))
        assert meta["total_count"] == 0

    def test_employee_body_fk_department_not_found(self, api, hr_admin_headers):
        """PRD §2.8 stage 3: "every body-supplied foreign key (such as
        `nominee_id`, `catalog_item_id`, `department_id`, `vendor_id`,
        `program_id`, or `budget_id`) resolves to an existing entity
        (`ERR_NOT_FOUND`)."

        Design: Corner/entities/employee_body_fk_department_not_found
        """
        res = api.create_employee(
            create_employee_payload(NON_EXISTENT_UUID), hr_admin_headers
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_employee_duplicate_ref_rejected(self, api, hr_admin_headers):
        """PRD §3.1: "Employees are registered by an `HRAdmin` with a unique
        external `employee_ref` (a conflict is `ERR_INVALID_REQUEST`)".

        Design: Corner/entities/employee_duplicate_ref_rejected
        """
        dept = create_department()
        first = create_employee(dept["id"], employee_ref="DUP")
        assert first["employee_ref"] == "DUP"
        res = api.create_employee(
            create_employee_payload(dept["id"], employee_ref="DUP", state_code="TX"),
            hr_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        _, meta = validate_paginated(api.list_employees(hr_admin_headers))
        assert meta["total_count"] == 1


class TestGenericEnvelope:
    def test_get_unknown_program_returns_not_found(self, api, hr_admin_headers):
        """PRD §2.8 stage 3: "Every path identifier resolves to an existing
        entity, resolved left to right along the path — the path parameters
        are `programId`, `departmentId`, `employeeId`, `id` on the short-form
        employee routes, `budgetId`, `nominationId`, `awardId`, `vendorId`,
        `catalogItemId`, `redemptionOrderId`, `taxRecordId`, `accrualRunId`,
        `abuseFlagId`, and `anniversaryEventId` — and every body-supplied
        foreign key (such as `nominee_id`, `catalog_item_id`, `department_id`,
        `vendor_id`, `program_id`, or `budget_id`) resolves to an existing
        entity (`ERR_NOT_FOUND`)."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/not_found_on_unknown_resource_id
        """
        res = api.get_program(NON_EXISTENT_UUID, hr_admin_headers)
        error = validate_error(res, ApiErrorId.ERR_NOT_FOUND)
        assert len(error["message"].strip()) > 0

    def test_employee_list_pagination_defaults(self, api, hr_admin_headers):
        """PRD §2.3: "The `limit` parameter defaults to 10, with a minimum of 1
        and a maximum of 100; `offset` defaults to 0. List responses carry the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`
        inside the `meta` object."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/entities/list_pagination_defaults_and_envelope
        """
        dept = create_department()
        for i in range(12):
            create_employee(dept["id"], employee_ref=f"E{i + 1:02d}")

        res = api.list_employees(hr_admin_headers)
        data, meta = validate_paginated(res)
        body = res.json()
        assert body["response_type"] == "array"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert len(data) == 10
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
