"""Entity-level claims: required fields, defaults, computed fields, envelope shape."""
import pytest

from test_helpers import (
    TEST_USERS,
    NON_EXISTENT_UUID,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    api_client,
    create_org_unit_payload,
    create_employee_payload,
    create_coaching_entry_payload,
    create_pip_template_payload,
    make_hrbp_headers,
    make_manager_headers,
    create_org_unit,
    create_employee,
    setup_cast,
    create_coaching_entries,
    create_and_accept_concern,
    create_and_publish_template,
    create_draft_pip,
    setup_concern_and_template,
)


class TestEmployeeCreation:
    def test_employee_create_without_job_family_rejected(self, api, admin_headers):
        """PRD §3.1: "Employees are provisioned into an org unit by the admin with a
        `full_name`, a work `email` unique within the org unit, a `job_family` of
        `ENGINEERING`, `SALES`, `OPERATIONS`, `SUPPORT`, or `FINANCE`, and a numeric
        `job_level` grade from 1 to 10".
        PRD §5: `ERR_INVALID_REQUEST` maps to 400 Bad Request.

        Design: Corner/entities/employee_create_required_field_omission_returns_invalid_request
        """
        ou = create_org_unit()
        payload = create_employee_payload()
        del payload["job_family"]
        resp = api.create_employee(ou["id"], payload, admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_employee_create_under_missing_org_unit_returns_not_found(
        self, api, admin_headers
    ):
        """PRD §2.6: "Path identifiers are validated strictly left to right: the
        first identifier that does not resolve to an existing resource fails the
        request with `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/employee_parent_org_unit_must_exist
        """
        resp = api.create_employee(
            NON_EXISTENT_UUID, create_employee_payload(), admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_employee_job_level_out_of_range_rejected(self, api, admin_headers):
        """PRD §3.1: "Employees are provisioned into an org unit by the admin with a
        `full_name`, a work `email` unique within the org unit, a `job_family` of
        `ENGINEERING`, `SALES`, `OPERATIONS`, `SUPPORT`, or `FINANCE`, and a numeric
        `job_level` grade from 1 to 10".
        PRD §5: `ERR_INVALID_REQUEST` maps to 400 Bad Request.

        Design: Corner/entities/employee_manager_id_self_reference_and_job_level_range
        """
        ou = create_org_unit()
        ceo = create_employee(
            ou["id"], full_name="CEO", email="ceo@x.com",
            job_family="OPERATIONS", job_level=10,
        )
        resp = api.create_employee(
            ou["id"],
            create_employee_payload(
                full_name="Bad Level", email="bl@x.com", job_level=11,
                manager_id=ceo["id"],
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_new_employee_employment_status_is_active(self, api, admin_headers):
        """PRD §3.1: "New employees start with `employment_status` of `ACTIVE`".

        Design: Corner/entities/employee_employment_status_ignored_input_defaults_to_active
        """
        ou = create_org_unit()
        payload = create_employee_payload(
            full_name="New Hire", email="nh@x.com", job_family="SUPPORT", job_level=3
        )
        payload["employment_status"] = "TERMINATED"  # client-supplied; must not stick
        resp = api.create_employee(ou["id"], payload, admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["employment_status"] == "ACTIVE", (
            f"Fresh employee must be ACTIVE, got {data['employment_status']}"
        )


class TestTemplateDefaults:
    def test_new_template_status_is_draft(self, api, admin_headers):
        """PRD §3.3: "A new template's `template_status` is `DRAFT`."

        Design: Corner/entities/pip_template_default_status_draft_and_ignored_input
        """
        ou = create_org_unit()
        hrbp = create_employee(
            ou["id"], full_name="HRBP", email="h@x.com", job_family="OPERATIONS",
            job_level=7,
        )
        payload = create_pip_template_payload()
        payload["template_status"] = "PUBLISHED"  # client-supplied; must not stick
        resp = api.create_pip_template(ou["id"], payload, make_hrbp_headers(hrbp["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["template_status"] == "DRAFT"


class TestCoachingLogEntryShape:
    def test_coaching_entry_is_append_only_shape(self, api, admin_headers):
        """PRD §2.4: "Three append-only record types — coaching log entries, evidence
        items, and rating-cycle outcome links — are immutable after creation and
        therefore carry only `id` and `created_at`; both `updated_at` and `version`
        are absent from them."

        Design: Corner/entities/coaching_log_entry_immutable_no_version_field
        """
        cast = setup_cast()
        resp = api.create_coaching_log_entry(
            cast["ou_id"], cast["emp_id"],
            create_coaching_entry_payload(severity="INFORMAL"),
            make_manager_headers(cast["mgr_id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert "version" not in data, "append-only entry must not carry version"
        assert "updated_at" not in data, "append-only entry must not carry updated_at"
        assert data["id"]
        assert data["created_at"]
        assert data["employee_id"] == cast["emp_id"]
        assert data["author_manager_id"] == cast["mgr_id"]


class TestPipComputedFields:
    def test_pip_end_date_is_start_plus_duration(self, api, admin_headers):
        """PRD §3.3: "computes `end_date` as `start_date` plus the template's
        duration in days, with `end_date` itself exclusive".

        Design: Corner/entities/pip_computed_end_date_from_start_plus_duration
        """
        cast = setup_cast()
        concern, template = setup_concern_and_template(cast)  # duration_days=30
        pip = create_draft_pip(cast, concern["id"], template["id"],
                               start_date="2026-08-01T00:00:00Z")
        assert pip["end_date"] == "2026-08-31T00:00:00Z", (
            f"end_date must equal start_date + 30 days, got {pip['end_date']}"
        )

    def test_pip_pins_policy_versions_at_creation(self, api, admin_headers):
        """PRD §3.1: "each plan snapshots it so that later policy changes never
        retroactively alter an in-flight plan."
        PRD §3.3: "pins `template_published_version` from the template and
        `policy_version_at_issuance` from the org unit".

        Design: Corner/entities/pip_pins_template_published_version_at_issuance
        """
        cast = setup_cast()
        concern, template = setup_concern_and_template(cast)
        pip = create_draft_pip(cast, concern["id"], template["id"])
        pinned_tpl_version = pip["template_published_version"]
        pinned_policy = pip["policy_version_at_issuance"]
        assert pinned_tpl_version == template["published_version"]
        # First publish bumps policy version from 1 to 2; PIP pins that value.
        assert pinned_policy == 2

        # A second template publication bumps the org-unit policy version again.
        create_and_publish_template(
            cast, name="T2", category="VELOCITY",
            goal_blueprints=[
                {"metric_key": "sp", "target_value": 10, "unit": "points", "weight": 100}
            ],
        )
        resp = api.get_pip(
            cast["ou_id"], cast["emp_id"], pip["id"],
            make_hrbp_headers(cast["hrbp_id"]),
        )
        data = validate_success(resp)
        assert data["template_published_version"] == pinned_tpl_version, (
            "already-created PIP must not move when a later template is published"
        )
        assert data["policy_version_at_issuance"] == pinned_policy


class TestListPaginationAndEnvelope:
    def test_list_employees_applies_default_pagination(self, api, admin_headers):
        """PRD §2.3: "The `limit` parameter caps how many items a response returns;
        it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the response envelope."

        Design: Corner/endpoints/list_employees_pagination_defaults_applied
        """
        ou = create_org_unit()
        for i in range(12):
            create_employee(
                ou["id"], full_name=f"E{i:02d}", email=f"e{i:02d}@x.com",
                job_family="ENGINEERING", job_level=5,
            )
        resp = api.list_employees(ou["id"], admin_headers)
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert len(data) == 10

    def test_error_response_envelope_shape(self, api, admin_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard
        envelope format" with `response_type` of "error" and a `data` object holding
        `error_id` and `message`.

        Design: Corner/endpoints/response_envelope_error_shape
        """
        create_org_unit()
        resp = api.get_org_unit(NON_EXISTENT_UUID, admin_headers)
        body = resp.json()
        assert resp.status_code == 404
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]


class TestPipGoalsRead:
    def test_list_pip_goals_returns_materialized_rows(self, api, admin_headers):
        """PRD §3.3: "One goal per blueprint is materialized at creation — each
        stamped with the plan's `pip_id`, its `metric_key`, `target_value`, `unit`,
        and `weight` copied from the blueprint, `current_value` starting at 0,
        `goal_status` starting `PENDING`, and the weights across a plan always
        summing to 100".

        Design: Corner/endpoints/list_pip_goals_computed_read
        """
        cast = setup_cast()
        concern, template = setup_concern_and_template(
            cast,
            goal_blueprints=[
                {"metric_key": "defects", "target_value": 2, "unit": "count", "weight": 60},
                {"metric_key": "review_turnaround", "target_value": 24, "unit": "hours", "weight": 40},
            ],
        )
        pip = create_draft_pip(cast, concern["id"], template["id"])
        resp = api.list_pip_goals(
            cast["ou_id"], cast["emp_id"], pip["id"],
            make_hrbp_headers(cast["hrbp_id"]),
        )
        goals = get_success_data(resp)
        assert len(goals) == 2
        for g in goals:
            assert g["goal_status"] == "PENDING"
            assert g["current_value"] == 0
        assert sum(g["weight"] for g in goals) == 100
