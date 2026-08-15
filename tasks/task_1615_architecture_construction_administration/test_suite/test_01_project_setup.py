"""Project creation: defaults, computed-field initialization, envelope, 404s."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_project,
    create_project_payload,
    create_active_project,
    make_firm_admin_headers,
    make_architect_headers,
)


class TestProjectDefaults:
    def test_create_project_applies_default_windows(self, api):
        """PRD 3.1: "Four optional knobs carry defaults: `grace_days` (at least zero, default 0)
        defers the start of extension billing past the adjusted completion date;
        `review_window_days_submittal` (at least one, default 10) sets the calendar days
        the CA team has to review a submittal; `review_window_days_rfi` (at least one,
        default 7) sets the calendar days the CA team has to answer an RFI; and
        `field_report_window_days` (at least one, default 3) sets the calendar days after
        a performed visit within which its field report must be issued."

        Design: Corner/entities/create_project_applies_default_windows
        """
        payload = create_project_payload()
        for key in ("grace_days", "review_window_days_submittal",
                    "review_window_days_rfi", "field_report_window_days"):
            payload.pop(key, None)
        resp = api.create_project(payload, make_firm_admin_headers())
        project = validate_success(resp, 201)
        assert_project(project)
        assert project["grace_days"] == 0
        assert project["review_window_days_submittal"] == 10
        assert project["review_window_days_rfi"] == 7
        assert project["field_report_window_days"] == 3

    def test_create_project_initializes_derived_position(self, api):
        """PRD 3.1: "A freshly created project initializes its derived position:
        `adjusted_contract_sum_cents` starts equal to `original_contract_sum_cents`,
        `adjusted_substantial_completion_date` starts equal to
        `base_substantial_completion_date`, `excusable_delay_days`,
        `certified_to_date_cents`, and `retainage_held_cents` all start at zero,
        `ca_posture` starts at `NORMAL`, `substantial_completion_actual_date` is null,
        and `status` is `SETUP`."

        Design: Corner/entities/create_project_applies_default_windows
        """
        payload = create_project_payload()
        payload.pop("grace_days", None)
        resp = api.create_project(payload, make_firm_admin_headers())
        project = validate_success(resp, 201)
        assert project["status"] == "SETUP"
        assert project["ca_posture"] == "NORMAL"
        assert project["excusable_delay_days"] == 0
        assert project["certified_to_date_cents"] == 0
        assert project["retainage_held_cents"] == 0
        assert project["adjusted_contract_sum_cents"] == 10000000
        assert project["adjusted_substantial_completion_date"] == "2026-09-30"
        assert project["substantial_completion_actual_date"] is None
        assert project["version"] == 1


class TestComputedFieldInputIgnored:
    def test_create_project_computed_field_input_ignored(self, api):
        """PRD 3.1: "A freshly created project initializes its derived position:
        `adjusted_contract_sum_cents` starts equal to `original_contract_sum_cents`,
        `adjusted_substantial_completion_date` starts equal to
        `base_substantial_completion_date`, `excusable_delay_days`,
        `certified_to_date_cents`, and `retainage_held_cents` all start at zero,
        `ca_posture` starts at `NORMAL`, `substantial_completion_actual_date` is null,
        and `status` is `SETUP`."

        Design: Corner/entities/create_project_computed_field_input_ignored
        """
        payload = create_project_payload(
            sov_lines=[{"line_code": "A", "description": "Concrete",
                        "scheduled_value_cents": 10000000}],
        )
        payload["adjusted_contract_sum_cents"] = 1
        payload["excusable_delay_days"] = 99
        payload["status"] = "CLOSED"
        resp = api.create_project(payload, make_firm_admin_headers())
        project = validate_success(resp, 201)
        assert project["adjusted_contract_sum_cents"] == 10000000
        assert project["excusable_delay_days"] == 0
        assert project["status"] == "SETUP"


class TestProjectNotFound:
    def test_get_nonexistent_project_returns_404(self, api):
        """PRD 2.8: "Each resource type has its own not-found error, all HTTP 404:
        `ERR_PROJECT_NOT_FOUND`, `ERR_SUBMITTAL_NOT_FOUND`, ..."

        Design: Corner/entities/get_nonexistent_project_returns_404
        """
        resp = api.get_project(NON_EXISTENT_UUID, make_firm_admin_headers())
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND, 404)


class TestRfiDefaults:
    def test_rfi_create_defaults_cost_impact_flag_false(self, api):
        """PRD 3.4: "A `Contractor` files a request for information with the
        `project_id`, the `question` text, and an optional `cost_impact_flag`
        (default false) recording whether the contractor anticipates the answer
        will carry cost impact. The RFI lands `OPEN`, `received_at` is stamped
        from the clock, and `due_at` is computed as `received_at` plus the
        project's `review_window_days_rfi` calendar days."

        Design: Corner/entities/rfi_create_defaults_cost_impact_flag_false
        """
        project = create_active_project(
            sov_lines=[{"line_code": "A", "description": "Concrete",
                        "scheduled_value_cents": 10000000}],
        )
        resp = api.create_rfi(
            {"project_id": project["id"], "question": "Confirm anchor bolt embedment"},
            {"X-User-ID": project["contractor_user_id"], "X-User-Role": "Contractor"},
        )
        rfi = validate_success(resp, 201)
        assert rfi["cost_impact_flag"] is False
        assert rfi["status"] == "OPEN"
        assert rfi["received_at"].startswith("2026-08-01T00:00:00")
        assert rfi["due_at"].startswith("2026-08-08T00:00:00")


class TestSovSumMismatch:
    def test_create_project_sov_sum_mismatch_returns_422(self, api):
        """PRD 3.1: "Line codes must be unique within the project, and the
        scheduled values must sum to the original contract sum exactly; a
        schedule that does not foot to the contract sum is rejected with
        `ERR_SOV_SUM_MISMATCH` (HTTP 422)."

        Design: Corner/validations/create_project_sov_sum_mismatch_returns_422
        """
        payload = create_project_payload(
            sov_lines=[{"line_code": "A", "description": "Concrete",
                        "scheduled_value_cents": 9999999}],
        )
        resp = api.create_project(payload, make_firm_admin_headers())
        validate_error(resp, ApiErrorId.ERR_SOV_SUM_MISMATCH, 422)
        listing = get_success_data(api.list_projects(make_firm_admin_headers()))
        assert listing == []


class TestPunchItemInitialState:
    def test_punch_item_created_open_with_zero_reopen_count(self, api):
        """PRD 3.7: "A new item opens in `OPEN` with `reopen_count` zero."

        Design: Corner/entities/punch_item_created_open_with_zero_reopen_count
        """
        from test_helpers import (
            create_report_issued_visit,
            set_clock,
        )
        project = create_active_project(
            sov_lines=[{"line_code": "A", "description": "Concrete",
                        "scheduled_value_cents": 10000000}],
        )
        set_clock("2026-08-20T09:00:00Z")
        visit, _report = create_report_issued_visit(
            project["id"], visit_date="2026-08-20", purpose="PUNCH_INSPECTION",
            conformance_summary="MINOR_DEVIATIONS",
        )
        resp = api.create_punch_list_item(
            {"project_id": project["id"], "raised_visit_id": visit["id"],
             "description": "Door hardware misaligned", "location": "Lobby L1"},
            make_architect_headers(),
        )
        item = validate_success(resp, 201)
        assert item["status"] == "OPEN"
        assert item["reopen_count"] == 0
        assert item["version"] == 1
