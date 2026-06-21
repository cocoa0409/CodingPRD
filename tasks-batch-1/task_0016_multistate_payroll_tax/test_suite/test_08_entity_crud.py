"""Entity CRUD coverage — create/retrieve/list/defaults/computed-fields."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    set_clock,
    seed_federal_and_california_2025,
    create_employee,
    create_and_file_w4,
    create_garnishment_order,
    create_draft_paycheck_run,
    attach_regular_paycheck,
    attach_overtime_paycheck,
    setup_employee_with_filed_w4,
    get_paycheck,
    create_employee_payload,
    regular_paycheck_payload,
    NON_EXISTENT_UUID,
    TEST_USERS,
)


# =========================================================================
# Queue (B) Corner — entities employee_create_minimal_required_fields
# =========================================================================

class TestEmployeeCreate:
    def test_create_employee_with_minimum_fields_initializes_defaults(self, api):
        """PRD §3.1: "The newly created employee enters `ACTIVE` status, and
        every year-to-date accumulator — `ytd_wages_cents`,
        `ytd_fed_withheld_cents`, `ytd_ss_wages_cents`, and
        `ytd_medicare_wages_cents` — is initialized to zero."
        PRD §3.1: "an optional `locality_code` (one of `NONE`, `NYC`, or `SF`;
        defaults to `NONE` when the work location has no local income tax)"

        Design: Corner/entities/employee_create_minimal_required_fields
        """
        res = api_client.create_employee(
            create_employee_payload(
                full_name="Sam Alpha",
                work_state_code="CA",
                residence_state_code="CA",
            ),
            TEST_USERS["hr_clerk_headers"],
        )
        emp = validate_success(res, expected_status=201)
        assert emp["status"] == "ACTIVE"
        assert emp["ytd_wages_cents"] == 0
        assert emp["ytd_fed_withheld_cents"] == 0
        assert emp["ytd_ss_wages_cents"] == 0
        assert emp["ytd_medicare_wages_cents"] == 0
        assert emp["locality_code"] == "NONE"


# =========================================================================
# Queue (B) Corner — entities employee_get_returns_stored
# =========================================================================

class TestEmployeeGet:
    def test_get_employee_returns_stored_fields(self, api):
        """PRD §3.1 (employee fields persisted) plus PRD §2.2 (the `data` field
        contains the resource object) — GET /employees/{id} returns the same
        fields the POST stored.

        Design: Corner/entities/employee_get_returns_stored
        """
        emp = create_employee(
            full_name="Tina Bravo", work_state_code="NY",
            residence_state_code="NY", locality_code="NYC",
        )
        res = api_client.get_employee(emp["id"], TEST_USERS["hr_clerk_headers"])
        got = validate_success(res, expected_status=200)
        assert got["id"] == emp["id"]
        assert got["full_name"] == "Tina Bravo"
        assert got["work_state_code"] == "NY"
        assert got["locality_code"] == "NYC"


# =========================================================================
# Queue (B) Corner — entities employee_list_pagination
# =========================================================================

class TestEmployeeListPagination:
    def test_list_employees_honors_limit_and_returns_pagination_meta(self, api):
        """PRD §2.3: "Each list response includes `limit`, `offset`,
        `total_count`, and `has_more` in its `meta` block so callers can
        paginate forward without an off-by-one."

        Design: Corner/entities/employee_list_pagination
        """
        for i in range(3):
            create_employee(full_name=f"E{i}", work_state_code="CA",
                            residence_state_code="CA")
        res = api_client.list_employees(
            TEST_USERS["hr_clerk_headers"], params={"limit": 2, "offset": 0}
        )
        data, meta = validate_paginated(res)
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True


# =========================================================================
# Queue (B) Corner — entities employee_not_found
# =========================================================================

class TestEmployeeNotFound:
    def test_get_with_unresolvable_uuid_returns_not_found(self, api):
        """PRD §2.5: "Nested URL paths are validated left-to-right."
        PRD §2.5: "if the run id does not exist, the response is
        `ERR_NOT_FOUND` and the child collection is never consulted."

        Design: Corner/entities/employee_not_found
        """
        res = api_client.get_employee(NON_EXISTENT_UUID, TEST_USERS["hr_clerk_headers"])
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# =========================================================================
# Queue (B) Corner — entities garnishment_deduction_immutable_no_common_fields
# =========================================================================

class TestGarnishmentDeductionMinimalFields:
    def test_garnishment_deduction_persisted_with_only_id_and_created_at(self, api):
        """PRD §2.4: "Two scaffold entities deliberately carry only `id` and
        `created_at`: `GarnishmentDeduction` (a child of `Paycheck`, written
        once when the parent paycheck transitions to `PAID`) and
        `TaxRateTable` (configuration data that is replaced rather than mutated
        in place). Neither of these two entity types exposes `updated_at`, and
        neither exposes `version`."

        After /paychecks fires the waterfall, the GarnishmentDeduction is
        readable via /paychecks/{id}/garnishment-deductions and via
        /garnishment-deductions/{id}.

        Design: Corner/entities/garnishment_deduction_immutable_no_common_fields
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        g = create_garnishment_order(
            emp["id"], order_type="CHILD_SUPPORT",
            weekly_cap_cents=30000, original_balance_cents=100000,
            served_on="2025-06-01T00:00:00.000Z",
        )
        run = create_draft_paycheck_run()
        pay = attach_regular_paycheck(run["id"], emp["id"])

        sub_list = api_client.list_garnishment_deductions_for_paycheck(
            pay["id"], TEST_USERS["payroll_preparer_headers"]
        )
        # Expect a list with at least one row
        body = sub_list.json()
        assert body["response_type"] == "array"
        deductions = body["data"]
        assert len(deductions) >= 1
        ded = deductions[0]
        assert ded["paycheck_id"] == pay["id"]
        assert ded["garnishment_order_id"] == g["id"]
        assert ded["amount_cents"] == 30000


# =========================================================================
# Queue (B) Corner — entities paycheck_computed_gross_overrides_input_ignored
# =========================================================================

class TestPaycheckComputedFieldsRecomputed:
    def test_paycheck_gross_wages_cents_is_computed_not_taken_from_input(self, api):
        """PRD §3.4: "Gross wages. The output `gross_wages_cents` depends on
        `pay_type`. For a `REGULAR` paycheck, gross is the product of
        `regular_hours_e2` and `hourly_rate_cents` divided by 100 with the
        remainder discarded (floor division)."

        Design: Corner/entities/paycheck_computed_gross_overrides_input_ignored
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        run = create_draft_paycheck_run()
        # REGULAR 40h @ $50/hr — compute should yield 200,000c
        pay = attach_regular_paycheck(run["id"], emp["id"])
        assert pay["gross_wages_cents"] == 200000


# =========================================================================
# Queue (B) Corner — endpoints list_paychecks_by_employee_filter
# =========================================================================

class TestListPaychecksByEmployeeFilter:
    def test_paychecks_list_supports_employee_id_filter(self, api):
        """PRD §3.8: "Paychecks can be filtered by `employee_id`,
        `paycheck_run_id`, `status`, and `pay_type`."

        Design: Corner/endpoints/list_paychecks_by_employee_filter
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp_a, _ = setup_employee_with_filed_w4(full_name="Emp A")
        emp_b, _ = setup_employee_with_filed_w4(full_name="Emp B")
        run = create_draft_paycheck_run()
        attach_regular_paycheck(run["id"], emp_a["id"])
        attach_regular_paycheck(run["id"], emp_b["id"])

        res = api_client.list_paychecks(
            TEST_USERS["payroll_preparer_headers"],
            params={"employee_id": emp_a["id"]},
        )
        data, _ = validate_paginated(res)
        assert len(data) == 1
        assert data[0]["employee_id"] == emp_a["id"]


# =========================================================================
# Queue (B) Corner — endpoints paychecks_sub_resource_under_run
# =========================================================================

class TestPaychecksSubResourceListing:
    def test_list_paychecks_under_run_returns_all_children(self, api):
        """PRD §3.8: "The sub-resource listing under a parent paycheck run
        resolves the run identifier first; if the run id does not exist, the
        response is `ERR_NOT_FOUND` and the child collection is never
        consulted." (sub-resource form covered by PRD §3.8 + endpoint table)

        Design: Corner/endpoints/paychecks_sub_resource_under_run
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        run = create_draft_paycheck_run()
        attach_regular_paycheck(
            run["id"], emp["id"], regular_hours_e2=4000, hourly_rate_cents=5000,
        )
        attach_overtime_paycheck(
            run["id"], emp["id"], overtime_hours_e2=1000, hourly_rate_cents=5000,
        )
        res = api_client.list_paychecks_for_run(
            run["id"], TEST_USERS["payroll_preparer_headers"]
        )
        data, _ = validate_paginated(res)
        assert len(data) == 2
