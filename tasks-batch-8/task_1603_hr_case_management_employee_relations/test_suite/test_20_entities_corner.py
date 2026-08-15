"""Corner tests — entities section (creation defaults, not-found, pagination, uniqueness, computed fields, immutability)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    setup_employee,
    setup_investigator,
    setup_intake_channel,
    setup_case,
    setup_holiday,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
)


class TestEmployeeCreationDefaults:
    def test_employee_creation_applies_defaults_and_system_fields(self):
        """PRD §3.1: "An employee's `employment_status` is one of `ACTIVE`,
        `ON_LEAVE`, or `TERMINATED`, defaulting to `ACTIVE` when the
        registration payload omits it."
        PRD §2.4: "All primary resources in the system carry a standard set of
        system-managed fields: `id` ... `created_at` ... `updated_at` ...
        `version` — a system-managed integer that increments by one on every
        mutation."

        Design: Corner/entities/employee_creation_applies_defaults_and_system_fields
        """
        resp = api_client.create_employee(
            {
                "employee_number": "E-9001",
                "full_name": "Default Test",
                "email": "e9001@example.com",
                "location_code": "SF",
                "department": "Ops",
                "hire_date": "2021-05-01T00:00:00Z",
            },
            TEST_USERS["er_manager_headers"],
        )
        emp = validate_success(resp, 201)
        assert emp["employment_status"] == "ACTIVE"
        assert emp["version"] == 1
        assert emp["manager_id"] is None
        assert "created_at" in emp


class TestEmployeeNotFound:
    def test_employee_not_found_returns_404(self):
        """PRD §2.6: "Existence comes next: path identifiers are resolved left
        to right (§2.11), and a miss fails with `ERR_NOT_FOUND`."

        Design: Corner/entities/employee_not_found_returns_404
        """
        resp = api_client.get_employee(NON_EXISTENT_UUID, TEST_USERS["er_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestEmployeePagination:
    def test_employee_list_pagination_envelope(self):
        """PRD §2.3: "The `limit` parameter caps how many items a response
        returns; when omitted it defaults to 10, and it accepts a minimum of 1
        and a maximum of 100. The `offset` parameter says how many items to
        skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/employee_list_pagination_envelope
        """
        for i in range(1, 13):
            setup_employee(
                employee_number=f"E-P{i:02d}",
                full_name=f"Page {i}",
                email=f"ep{i:02d}@example.com",
            )
        page1_resp = api_client.list_employees(TEST_USERS["er_manager_headers"])
        page1, meta1 = validate_paginated(page1_resp)
        assert len(page1) == 10
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        page2_resp = api_client.list_employees(
            TEST_USERS["er_manager_headers"], params={"offset": 10}
        )
        page2, meta2 = validate_paginated(page2_resp)
        assert len(page2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False
        assert meta2["offset"] == 10


class TestEmployeeDuplicate:
    def test_employee_duplicate_employee_number_rejected(self):
        """PRD §3.1: "a manager assignment that would create a cycle is
        rejected with `ERR_DUPLICATE`, as is any reuse of an existing
        `employee_number` or `email`."

        Design: Corner/entities/employee_duplicate_employee_number_rejected
        """
        setup_employee(
            employee_number="E-D01", full_name="Dup Base",
            email="ed01a@example.com",
        )
        resp = api_client.create_employee(
            {
                "employee_number": "E-D01",
                "full_name": "Dup Other",
                "email": "ed01b@example.com",
                "location_code": "LA",
                "department": "Sales",
                "hire_date": "2021-01-01T00:00:00Z",
            },
            TEST_USERS["er_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE, 409)


class TestEmployeeManagerCycle:
    def test_employee_manager_cycle_rejected(self):
        """PRD §3.1: "the reporting chain must never close into a loop — a
        manager assignment that would create a cycle is rejected with
        `ERR_DUPLICATE`."

        Design: Corner/entities/employee_manager_cycle_rejected
        """
        a = setup_employee(employee_number="E-C01", full_name="Cyc A",
                            email="ec01@example.com")
        b = setup_employee(employee_number="E-C02", full_name="Cyc B",
                            email="ec02@example.com")
        # A.manager_id = B
        api_client.patch_employee(
            a["id"], {"manager_id": b["id"]}, TEST_USERS["er_manager_headers"]
        )
        # Now setting B.manager_id = A would create a cycle
        resp = api_client.patch_employee(
            b["id"], {"manager_id": a["id"]}, TEST_USERS["er_manager_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE, 409)
        # B's manager_id must remain null
        b_after = get_success_data(api_client.get_employee(b["id"], TEST_USERS["er_manager_headers"]))
        assert b_after["manager_id"] is None


class TestInvestigatorComputedField:
    def test_investigator_computed_active_case_count_ignores_input(self):
        """PRD §3.1: "the derived `active_case_count` tracks the live figure
        — the number of cases currently assigned to the investigator whose
        status is one of `TRIAGE`, `ASSIGNED`, `INVESTIGATING`,
        `FINDINGS_DRAFT`, `CALIBRATION`, or `PENDING_CLOSURE`. ... The count
        starts at zero and is recomputed on every assignment, unassignment,
        closure, and reopen."

        Design: Corner/entities/investigator_computed_active_case_count_ignores_input
        """
        emp, inv = setup_investigator(certification_level="LEVEL_2", max_active_cases=4)
        assert inv["active_case_count"] == 0
        # PATCH max_active_cases — computed active_case_count must remain 0
        resp = api_client.patch_investigator(
            inv["id"], {"max_active_cases": 6}, TEST_USERS["er_manager_headers"]
        )
        after = validate_success(resp, 200)
        assert after["active_case_count"] == 0, (
            f"active_case_count must remain 0 (computed); got {after['active_case_count']}"
        )
        assert after["max_active_cases"] == 6


class TestCaseIntakeChannelDefaults:
    def test_case_intake_applies_channel_defaults(self):
        """PRD §3.2: "When the payload omits `category`, the channel's
        `default_category` applies; when it omits `severity`, the channel's
        `default_severity` applies."
        PRD §3.2: "the case enters `TRIAGE`."

        Design: Corner/entities/case_intake_applies_channel_defaults
        """
        ch = setup_intake_channel(
            channel_code="ANONYMOUS_LETTER", display_name="Anon",
            default_category="SAFETY", default_severity="CRITICAL",
            sla_business_days=3,
        )
        subject = setup_employee()
        resp = api_client.create_case(
            {"intake_channel_id": ch["id"], "subject_employee_id": subject["id"]},
            TEST_USERS["er_manager_headers"],
        )
        case = validate_success(resp, 201)
        assert case["category"] == "SAFETY"
        assert case["severity"] == "CRITICAL"
        assert case["status"] == "TRIAGE"
        assert case["reporter_employee_id"] is None


class TestHolidayEntryImmutable:
    def test_holiday_calendar_entry_immutable_no_version(self):
        """PRD §2.4: "One resource is exempt from part of this convention: a
        holiday calendar entry carries only `id` and `created_at`. Because
        holiday entries are never modified after registration, `updated_at`
        and `version` are both absent from that resource."

        Design: Corner/entities/holiday_calendar_entry_immutable_no_version
        """
        h = setup_holiday("2026-12-25T00:00:00Z", "Christmas")
        # Verify the created response itself omits version/updated_at
        assert "id" in h
        assert "created_at" in h
        assert "version" not in h, "holiday entries must not carry version"
        assert "updated_at" not in h, "holiday entries must not carry updated_at"
        # And the list view also omits them
        list_resp = api_client.list_holidays(TEST_USERS["er_manager_headers"])
        items = get_success_data(list_resp)
        entries = items if isinstance(items, list) else items.get("data", [])
        match = next((e for e in entries if e["id"] == h["id"]), None)
        assert match is not None
        assert "version" not in match
        assert "updated_at" not in match
