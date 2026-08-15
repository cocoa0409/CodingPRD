"""Case intake, basic retrieval, envelope shape, pagination, and filters.

Covers queue-B corner instances under sections `entities` and `endpoints`.
"""
import re

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_offboarding_case,
    create_case,
    create_case_payload,
    HR_INTAKE,
    HR_APPROVER,
)


class TestCaseCreation:
    def test_case_create_success_201_and_fields_echoed(self):
        """PRD §3.1: "A new case starts in `INTAKE`, and its creation dispatches an
        `INTAKE_ALERT` notification to the manager." PRD §2.5: "`version` (integer):
        a system-managed integer that increments by one on every mutation."

        Design: Corner/entities/case_create_success_201_and_fields_echoed
        """
        payload = create_case_payload(
            employee_ref="E-CR1",
            case_type="TERMINATION",
            work_state_code="IL",
            notice_received_date="2026-08-03T00:00:00Z",
            requested_last_day="2026-08-03T00:00:00Z",
            pto_balance_hours=12.5,
            tenure_years=3.5,
            hourly_wage_cents=7200,
            intake_hr_ref="hr-intake-1",
        )
        resp = api_client.create_case(payload, HR_INTAKE)
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"]), "id must be a bare UUID"
        assert data["version"] == 1
        assert data["status"] == "INTAKE"
        assert data["revocation_posture"] == "NOT_STARTED"
        assert data["asset_posture"] == "NOT_STARTED"
        assert data["deduction_total_cents"] == 0
        assert data["rehire_code"] is None
        assert data["determined_last_day"] is None

    def test_case_create_returns_uuid_no_prefix_and_iso_created_at(self):
        """PRD §2.5: "`id` (string): a unique, server-minted UUID with no type
        prefix. `created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits."

        Design: Corner/entities/system_fields_id_created_at_version
        """
        resp = api_client.create_case(
            create_case_payload(employee_ref="E-CR6"), HR_INTAKE
        )
        data = validate_success(resp, expected_status=201)
        # bare UUID, no prefix
        assert re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            data["id"],
        ), f"id must be a bare UUID without type prefix, got {data['id']!r}"
        # exactly 3 fractional digits on the timestamp
        assert re.search(r"\.\d{3}Z$", data["created_at"]), (
            f"created_at must carry 3 fractional second digits, got {data['created_at']!r}"
        )
        assert data["version"] == 1

    def test_case_create_ignores_computed_fields_from_client(self):
        """PRD §3.1: "`determined_last_day` becomes the earlier of the
        `requested_last_day` and the date thirty days after the
        `notice_received_date`" — it is set by approval, not by the client.
        PRD §2.5 lists `status`, `version`, `id`, `created_at`, `updated_at` as
        system-managed.

        Design: Corner/entities/computed_fields_ignore_client_input
        """
        payload = create_case_payload(employee_ref="E-CR5")
        # Attempt to sneak in system/computed fields
        payload["status"] = "CLOSED"
        payload["revocation_posture"] = "COMPLETE"
        payload["deduction_total_cents"] = 99999
        payload["version"] = 99
        resp = api_client.create_case(payload, HR_INTAKE)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "INTAKE"
        assert data["revocation_posture"] == "NOT_STARTED"
        assert data["deduction_total_cents"] == 0
        assert data["version"] == 1


class TestCaseRetrieval:
    def test_case_get_by_id_returns_stored(self):
        """PRD §3.1: "An offboarding begins when an `HRPartner` opens a case."
        PRD §2.5: system fields ride on every primary resource.

        Design: Corner/entities/case_get_by_id_returns_stored
        """
        case = create_case(
            employee_ref="E-CR2",
            case_type="RESIGNATION",
            work_state_code="WA",
            notice_received_date="2026-08-01T00:00:00Z",
            requested_last_day="2026-08-14T00:00:00Z",
            pto_balance_hours=5.0,
            tenure_years=0.5,
            hourly_wage_cents=3000,
        )
        resp = api_client.get_case(case["id"], HR_INTAKE)
        data = validate_success(resp)
        assert data["id"] == case["id"]
        assert data["employee_ref"] == "E-CR2"
        assert data["work_state_code"] == "WA"
        assert data["hourly_wage_cents"] == 3000
        assert data["status"] == "INTAKE"

    def test_case_get_not_found_returns_404(self):
        """PRD §2.6: "Existence — every path-referenced resource resolves, checked
        left to right along the URL hierarchy; otherwise `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/case_get_not_found_returns_404
        """
        resp = api_client.get_case(NON_EXISTENT_UUID, HR_INTAKE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCaseValidation:
    def test_case_create_missing_required_field_400(self):
        """PRD §2.6: "Payload shape — required fields are present, enum values
        belong to their declared sets, and numeric ranges are honored; otherwise
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/case_create_missing_required_field_400
        """
        payload = create_case_payload(employee_ref="E-CR3", work_state_code="TX")
        del payload["hourly_wage_cents"]
        resp = api_client.create_case(payload, HR_INTAKE)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_case_create_invalid_enum_400(self):
        """PRD §3.1: "`case_type` as one of `RESIGNATION`, `TERMINATION`,
        `MUTUAL_SEPARATION`, or `JOB_ABANDONMENT`" — `QUIT` is not a member.
        PRD §2.6: "Payload shape — required fields are present, enum values
        belong to their declared sets, and numeric ranges are honored; otherwise
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/case_create_invalid_enum_400
        """
        resp = api_client.create_case(
            create_case_payload(employee_ref="E-CR4", case_type="QUIT"), HR_INTAKE
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_case_create_invalid_work_state_400(self):
        """PRD §3.1: "`work_state_code`, which must be one of the eight supported
        codes `CA`, `CO`, `IL`, `MA`, `TX`, `NY`, `WA`, or `FL`."
        PRD §2.6: "Payload shape — ... otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/case_create_invalid_enum_400
        """
        resp = api_client.create_case(
            create_case_payload(employee_ref="E-CR4B", work_state_code="ZZ"), HR_INTAKE
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_case_employee_ref_uniqueness_enforced(self):
        """PRD §2.10: "Across the whole system, `employee_ref` is unique: no two
        cases may be opened for the same HRIS employee identifier. Violating any
        of these constraints is rejected with `ERR_REFERENTIAL_INTEGRITY`."

        Design: Corner/entities/case_employee_ref_uniqueness_enforced
        """
        create_case(employee_ref="E-DUP")
        resp = api_client.create_case(
            create_case_payload(employee_ref="E-DUP", case_type="TERMINATION"),
            HR_INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY, expected_status=422)


class TestManagerNotifications:
    def test_manager_notification_immutable_no_update_endpoint(self):
        """PRD §2.5: "A ManagerNotification is an append-only dispatch record:
        it carries `id` and `created_at` only, and both `updated_at` and
        `version` are absent from it."
        PRD §3.1: "its creation dispatches an `INTAKE_ALERT` notification to the
        manager."

        Design: Corner/entities/manager_notification_immutable_no_update_endpoint
        """
        case = create_case(employee_ref="E-MN1")
        resp = api_client.list_case_notifications(case["id"], HR_INTAKE)
        rows = validate_success(resp)
        assert isinstance(rows, list) and len(rows) >= 1
        intake_rows = [r for r in rows if r["notification_kind"] == "INTAKE_ALERT"]
        assert len(intake_rows) == 1
        row = intake_rows[0]
        assert row["suppressed"] is False
        assert is_iso8601_timestamp(row["sent_at"]), "sent_at is server-stamped at dispatch"
        # Append-only: no updated_at / version keys
        assert "updated_at" not in row
        assert "version" not in row


class TestResponseEnvelope:
    def test_response_envelope_success_shape(self):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`. The `response_type` is either
        'object' for a single resource or 'array' for a list of resources."

        Design: Corner/endpoints/response_envelope_success_shape
        """
        case = create_case(employee_ref="E-EP1")
        resp = api_client.get_case(case["id"], HR_INTAKE)
        body = resp.json()
        assert "meta" in body and "response_type" in body and "data" in body
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"

    def test_response_envelope_list_shape_is_array(self):
        """PRD §2.2: "The `response_type` is either 'object' for a single resource
        or 'array' for a list of resources." Pagination fields live in `meta`.

        Design: Corner/endpoints/response_envelope_success_shape
        """
        create_case(employee_ref="E-EP1B")
        resp = api_client.list_cases(HR_INTAKE)
        body = resp.json()
        assert body["response_type"] == "array"
        assert isinstance(body["data"], list)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in body["meta"], f"meta must carry {key}"


class TestPagination:
    def test_list_pagination_defaults_and_bounds(self):
        """PRD §2.3: "The `limit` parameter caps the number of returned items: it
        defaults to 10, accepts a minimum of 1, and is clamped at a maximum of
        100. The `offset` parameter skips a number of items from the start of the
        result set and defaults to 0."

        Design: Corner/endpoints/list_pagination_defaults_and_bounds
        """
        for i in range(12):
            create_case(employee_ref=f"E-EP2-{i:02d}", work_state_code="TX")
        resp = api_client.list_cases(HR_INTAKE)
        body = resp.json()
        assert body["response_type"] == "array"
        assert len(body["data"]) == 10, "default limit is 10"
        assert body["meta"]["total_count"] == 12
        assert body["meta"]["has_more"] is True
        assert body["meta"]["limit"] == 10
        assert body["meta"]["offset"] == 0

    def test_list_pagination_offset_and_limit(self):
        """PRD §2.3: "The `offset` parameter skips a number of items from the
        start of the result set and defaults to 0."

        Design: Corner/endpoints/list_pagination_defaults_and_bounds
        """
        for i in range(12):
            create_case(employee_ref=f"E-EP2B-{i:02d}", work_state_code="TX")
        resp = api_client.list_cases(HR_INTAKE, params={"limit": 5, "offset": 10})
        body = resp.json()
        assert len(body["data"]) == 2
        assert body["meta"]["has_more"] is False
        assert body["meta"]["total_count"] == 12
        assert body["meta"]["limit"] == 5
        assert body["meta"]["offset"] == 10


class TestListFilters:
    def test_list_filter_by_status(self):
        """PRD §3.1: "Cases can be listed and filtered by `status`,
        `work_state_code`, or `case_type`."

        Design: Corner/endpoints/list_filter_by_status
        """
        create_case(employee_ref="E-EP3A", work_state_code="TX")
        create_case(employee_ref="E-EP3B", work_state_code="TX")
        approved_case = create_case(employee_ref="E-EP3C", work_state_code="TX")
        get_success_data(api_client.approve_case(approved_case["id"], HR_APPROVER))

        resp = api_client.list_cases(HR_INTAKE, params={"status": "APPROVED"})
        body = resp.json()
        assert body["meta"]["total_count"] == 1
        assert body["data"][0]["id"] == approved_case["id"]

        resp = api_client.list_cases(HR_INTAKE, params={"status": "INTAKE"})
        body = resp.json()
        assert body["meta"]["total_count"] == 2

    def test_list_filter_by_work_state_code(self):
        """PRD §3.1: "Cases can be listed and filtered by `status`,
        `work_state_code`, or `case_type`."

        Design: Corner/endpoints/list_filter_by_status
        """
        create_case(employee_ref="E-FLT-CA", work_state_code="CA")
        create_case(employee_ref="E-FLT-TX", work_state_code="TX")
        resp = api_client.list_cases(HR_INTAKE, params={"work_state_code": "CA"})
        body = resp.json()
        assert body["meta"]["total_count"] == 1
        assert body["data"][0]["work_state_code"] == "CA"

    def test_list_filter_by_case_type(self):
        """PRD §3.1: "Cases can be listed and filtered by `status`,
        `work_state_code`, or `case_type`."

        Design: Corner/endpoints/list_filter_by_status
        """
        create_case(employee_ref="E-FLT-R", case_type="RESIGNATION")
        create_case(employee_ref="E-FLT-T", case_type="TERMINATION",
                    requested_last_day="2026-08-01T00:00:00Z")
        resp = api_client.list_cases(HR_INTAKE, params={"case_type": "TERMINATION"})
        body = resp.json()
        assert body["meta"]["total_count"] == 1
        assert body["data"][0]["case_type"] == "TERMINATION"


class TestSummaryComputedRead:
    def test_computed_read_summary_fields(self):
        """PRD §3.4: "items merely `COMPUTED` are excluded from the payroll total
        and instead surface as `projected_deduction_cents` on the case summary
        read." PRD §3.7: "For a case it returns the current `revocation_posture`
        and `asset_posture`, the applied `deduction_total_cents`, the
        `projected_deduction_cents` of items computed but not yet applied, a
        `net_pay_preview_cents` reflecting the current statement math, and a
        `ready_to_close` boolean mirroring the readiness gate above."

        Design: Corner/endpoints/computed_read_summary_fields
        """
        from test_helpers import (
            create_and_approve_case,
            create_asset_item,
            CLERK,
            PAYROLL_CALC,
        )
        case = create_and_approve_case(employee_ref="E-EP4")
        item = create_asset_item(
            case["id"], asset_tag="A1", asset_kind="OTHER", replacement_cost_cents=10000,
            issued_date="2026-01-01T00:00:00Z",
        )
        resp = api_client.record_asset_return(
            item["id"],
            {"condition_on_return": "DAMAGED",
             "expected_asset_return_item_version": item["version"]},
            CLERK,
        )
        get_success_data(resp)

        resp = api_client.get_case_summary(case["id"], PAYROLL_CALC)
        summary = validate_success(resp)
        assert summary["projected_deduction_cents"] == 5000
        assert summary["deduction_total_cents"] == 0
        assert summary["asset_posture"] == "COMPLETE"
