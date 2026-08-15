"""Case opening: enrollment defaults, policy resolution, auth/shape/existence guards."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    is_valid_uuid,
    assert_employee,
    assert_case,
    assert_timestamp_equals_instant,
    create_policy,
    create_employee,
    create_case,
    create_case_payload,
)

MC = TEST_USERS["coordinator_headers"]


class TestEmployeeEnrollment:
    def test_create_employee_applies_defaults(self):
        """PRD §3.1: "New employees begin with `employment_status` set to `ACTIVE`."
        PRD §2.4: "Fields that record an event or a later-supplied value are null
        until the corresponding action populates them: `authorized_at`,
        `termination_date`, `survey_at`, `estimated_cents`, `final_invoice_cents`,
        `rating`, `rated_at`, `reject_reason`, `paid_at`, `sale_price_cents`,
        `loss_basis_used`, `gross_loss_cents`, `capped_benefit_cents`, `signed_at`,
        `next_due_date`, and `decision_note`."
        PRD §2.5: "At startup, before any call, the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time."

        Design: Corner/entities/create_employee_applies_defaults
        """
        resp = api_client.create_employee(
            {"full_name": "Default Dee", "job_level": "MANAGER",
             "home_ownership": "RENTER"}, MC)
        data = validate_success(resp, 201)
        assert_employee(data)
        assert data["employment_status"] == "ACTIVE"
        assert data["termination_date"] is None
        assert is_valid_uuid(data["id"])
        assert_timestamp_equals_instant(data["created_at"], 2026, 8, 1)

        fetched = validate_success(api_client.get_employee(data["id"], MC))
        assert fetched["employment_status"] == "ACTIVE"
        assert fetched["termination_date"] is None

    def test_create_employee_with_invalid_job_level_rejected(self):
        """PRD §2.10: "Request shape**: required fields are present, enum values
        are in range, a rating is an integer from 1 to 5, monetary amounts are
        positive integers, and claim line items are non-empty (`ERR_INVALID_REQUEST`,
        HTTP 400)."
        PRD §3.1: "a `job_level` of `ASSOCIATE`, `MANAGER`, `DIRECTOR`, or
        `EXECUTIVE`"

        Design: Corner/entities/create_employee_with_invalid_job_level_rejected
        """
        resp = api_client.create_employee(
            {"full_name": "Bad Enum", "job_level": "SUPREME",
             "home_ownership": "RENTER"}, MC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_employee_system_fields_input_ignored(self):
        """PRD §2.4: "`id` (string): a unique, server-minted identifier formatted
        as a UUID, with no type prefix."
        PRD §2.4: "`version` (integer): a system-managed integer that increments
        by exactly one on every mutation of the resource, including mutations
        driven automatically by cascades or by the system itself."

        Design: Corner/entities/create_employee_system_fields_input_ignored
        """
        supplied_id = "11111111-1111-1111-1111-111111111111"
        resp = api_client.create_employee(
            {"full_name": "Sys Sid", "job_level": "MANAGER",
             "home_ownership": "RENTER", "id": supplied_id, "version": 99}, MC)
        data = validate_success(resp, 201)
        assert data["id"] != supplied_id, "client-supplied id must not be honored"
        assert is_valid_uuid(data["id"])
        assert isinstance(data["version"], int), "version must be system-managed"
        assert data["employment_status"] == "ACTIVE"


class TestCaseOpeningAndPolicyResolution:
    def test_create_case_resolves_policy_and_zeroes_ledger(self):
        """PRD §3.2: "The resolved tier's `id` is stored on the case as
        `policy_id`, the case enters `DRAFT`, and its three ledger totals
        initialize to zero."
        PRD §3.2: "the system searches all policy tiers for the one whose
        `job_level` matches the employee's level, whose `move_scope` matches the
        requested scope, and whose `home_ownership` matches the employee's
        ownership status."

        Design: Corner/entities/create_case_resolves_policy_and_zeroes_ledger
        """
        policy = create_policy()
        employee = create_employee(full_name="Comp Cate")
        resp = api_client.create_case(create_case_payload(employee["id"]), MC)
        case = validate_success(resp, 201)
        assert_case(case)
        assert case["policy_id"] == policy["id"]
        assert case["status"] == "DRAFT"
        assert case["total_committed_cents"] == 0
        assert case["total_paid_cents"] == 0
        assert case["total_released_cents"] == 0
        assert case["cumulative_taxable_paid_cents"] == 0

    def test_create_case_without_matching_policy_returns_422(self):
        """PRD §3.2: "When no tier matches, creation is rejected with
        `ERR_POLICY_NOT_FOUND` (HTTP 422)."

        Design: Corner/entities/create_case_without_matching_policy_returns_422
        """
        create_policy()  # only MANAGER/DOMESTIC/RENTER exists
        employee = create_employee(full_name="NoPol Ned", job_level="EXECUTIVE")
        resp = api_client.create_case(create_case_payload(employee["id"]), MC)
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_FOUND)

    def test_case_initial_state_is_draft(self):
        """PRD §3.2: "The resolved tier's `id` is stored on the case as
        `policy_id`, the case enters `DRAFT`, and its three ledger totals
        initialize to zero."

        Design: Corner/state_machines/case_initial_state_is_draft
        """
        create_policy()
        employee = create_employee(full_name="Init Ina")
        case = create_case(employee["id"])
        fetched = validate_success(api_client.get_case(case["id"], MC))
        assert fetched["status"] == "DRAFT"

    def test_create_case_for_terminated_employee_rejected(self):
        """PRD §3.2: "Only an `ACTIVE` employee may be put into motion: case
        creation, and later the authorization step, are both rejected with
        `ERR_EMPLOYEE_NOT_ACTIVE` when the employee has already been terminated."
        PRD §3.1: "When employment ends, the coordinator terminates the record:
        `employment_status` flips to `TERMINATED`, `termination_date` is stamped
        from the logical clock, and the employee's `version` increments."

        Design: Corner/validations/create_case_for_terminated_employee_rejected
        """
        create_policy()
        employee = create_employee(full_name="Gone Gina")
        terminated = validate_success(api_client.terminate_employee(employee["id"], MC))
        assert terminated["employment_status"] == "TERMINATED"
        assert_timestamp_equals_instant(terminated["termination_date"], 2026, 8, 1)

        resp = api_client.create_case(create_case_payload(employee["id"]), MC)
        validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_ACTIVE)

    def test_create_case_missing_auth_headers_returns_401(self):
        """PRD §2.1: "A request that arrives without both headers, or whose role
        value is not one of the declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/create_case_missing_auth_headers_returns_401
        """
        payload = {"employee_id": NON_EXISTENT_UUID, "move_scope": "DOMESTIC",
                   "origin_city": "Chicago", "destination_city": "Denver",
                   "expected_move_date": "2026-09-01T00:00:00Z"}
        resp = api_client.create_case(payload, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_get_nonexistent_case_returns_404(self):
        """PRD §2.10: "Existence**: path identifiers and body foreign keys such
        as `employee_id`, `case_id`, and `vendor_id` resolve to existing
        resources, validated left to right (`ERR_NOT_FOUND`, HTTP 404)."

        Design: Corner/entities/get_nonexistent_case_returns_404
        """
        resp = api_client.get_case(NON_EXISTENT_UUID, MC)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_create_booking_missing_case_id_rejected(self):
        """PRD §2.10: "Request shape**: required fields are present, enum values
        are in range, a rating is an integer from 1 to 5, monetary amounts are
        positive integers, and claim line items are non-empty (`ERR_INVALID_REQUEST`,
        HTTP 400)."
        PRD §3.4: "The booking carries `case_id`, a `kind` of `TEMP_HOUSING` or
        `TRAVEL`, a `start_date`, an `amount_cents`, and — for housing — an
        `end_date`."

        Design: Corner/entities/create_booking_missing_case_id_rejected
        """
        payload = {"kind": "TRAVEL", "start_date": "2026-08-15T00:00:00Z",
                   "amount_cents": 61000}
        resp = api_client.create_service_booking(payload, MC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCaseListing:
    def test_list_cases_filtered_by_employee_paginates(self):
        """PRD §3.2: "The case collection is listed with optional `employee_id`,
        `policy_id`, and `status` filters alongside the standard pagination
        parameters."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/list_cases_filtered_by_employee_paginates
        """
        create_policy()
        emp1 = create_employee(full_name="List Liv")
        emp2 = create_employee(full_name="List Lou")
        create_case(emp1["id"])
        create_case(emp1["id"], destination_city="Boulder",
                    expected_move_date="2026-10-01T00:00:00Z")
        create_case(emp2["id"])

        resp = api_client.list_cases(
            MC, params={"employee_id": emp1["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert len(data) == 1, "limit must cap the page size"
        assert all(c["employee_id"] == emp1["id"] for c in data)
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is True

        # Second page carries the other case of emp1.
        resp2 = api_client.list_cases(
            MC, params={"employee_id": emp1["id"], "limit": 1, "offset": 1})
        data2, meta2 = validate_paginated(resp2)
        assert len(data2) == 1 and data2[0]["employee_id"] == emp1["id"]
        assert meta2["has_more"] is False
