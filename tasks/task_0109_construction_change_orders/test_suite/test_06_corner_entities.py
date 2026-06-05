"""Entity-surface corner tests (Corner queue: entities section)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    OWNER, CONTRACTOR,
    JAN,
    create_project, create_sov_line, setup_project_with_one_sov_line,
    create_pay_application,
)


class TestProjectCreation:
    def test_create_project_defaults_and_derived_zero(self, api):
        """PRD §3.1: "At creation its revised_contract_sum_cents equals the
        original_contract_sum_cents, and its three other derived ledger figures —
        total_completed_and_stored_cents, retainage_held_cents, and the line roll-ups behind
        them — all start at zero." PRD §3.1: "when not supplied, is taken to be 0.10."

        Design: Corner/entities/create_project_returns_201_with_defaults_and_derived_zero
        """
        resp = api.create_project(
            {"name": "Tower", "owner_user_id": "owner-1",
             "original_contract_sum_cents": 500_000},
            OWNER,
        )
        data = validate_success(resp, 201)
        proj = validate_success(api.get_project(data["id"], OWNER), 200)
        assert proj["status"] == "ACTIVE"
        assert proj["revised_contract_sum_cents"] == 500000
        assert proj["retainage_held_cents"] == 0
        assert proj["default_retainage_pct"] == 0.10
        assert proj["version"] == 1


class TestProjectNotFound:
    def test_get_unknown_project_returns_not_found(self, api):
        """PRD §2.8: "the first one that does not resolve yields ERR_NOT_FOUND (HTTP 404)
        before any later reference or business rule is evaluated."

        Design: Corner/entities/get_project_nonexistent_returns_not_found
        """
        resp = api.get_project(NON_EXISTENT_UUID, OWNER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


class TestSovLineFieldValidation:
    def test_missing_scheduled_value_returns_invalid_request(self, api):
        """PRD §2.10: "Generic field-shape validation — required fields present, enums in
        range, integer and sign constraints ... surfaces as ERR_INVALID_REQUEST (HTTP 422)".

        Design: Corner/entities/create_sov_line_missing_scheduled_value_returns_invalid_request
        """
        project = create_project(500_000, name="ReqP")
        resp = api.create_sov_line(
            {"project_id": project["id"], "item_no": "001", "description": "Foundation"},
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    def test_nonpositive_scheduled_value_returns_invalid_request(self, api):
        """PRD §2.10: "Field-shape failures of this kind include a non-positive
        scheduled_value_cents". PRD §3.1: "a scheduled_value_cents (G703 column C) that must
        be strictly greater than zero."

        Design: Corner/entities/create_sov_line_nonpositive_scheduled_value_returns_invalid_request
        """
        project = create_project(500_000, name="ZeroP")
        resp = api.create_sov_line(
            {"project_id": project["id"], "item_no": "001", "description": "X",
             "scheduled_value_cents": 0},
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


class TestSovLineDuplicateItemNo:
    def test_duplicate_item_no_returns_duplicate_error(self, api):
        """PRD §3.1: "The item_no must be unique among the active lines of the project; a
        collision is rejected with ERR_DUPLICATE_ITEM_NO (HTTP 409)."

        Design: Corner/entities/duplicate_item_no_on_sov_create_returns_duplicate
        """
        project = create_project(500_000, name="DupP")
        create_sov_line(project["id"], "001", 300_000, "First")
        resp = api.create_sov_line(
            {"project_id": project["id"], "item_no": "001", "description": "Second",
             "scheduled_value_cents": 200_000},
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ITEM_NO.value, 409)


class TestPayAppLineComputedFields:
    def test_computed_fields_reflect_server_computation(self, api):
        """PRD §3.3: "it applies the linked schedule-of-values line's retainage_pct to the
        sum of work_completed_previous_cents, work_completed_this_period_cents, and
        materials_stored_cents". PRD §3.3: "At creation the line snapshots
        work_completed_previous_cents from the linked SovLine.work_completed_to_date_cents as
        of the most recently certified prior application (zero if none)".

        Design: Corner/entities/pay_app_line_computed_fields_ignored_on_input
        """
        project, sov1 = setup_project_with_one_sov_line(sov1_value=600_000)
        app = create_pay_application(project["id"], 1, JAN, project["version"])
        resp = api.create_pay_app_line(
            {"pay_app_id": app["id"], "sov_line_id": sov1["id"],
             "work_completed_this_period_cents": 100_000, "materials_stored_cents": 0},
            CONTRACTOR,
        )
        data = validate_success(resp, 201)
        assert data["line_retainage_cents"] == 10000  # 0.10 * 100000.
        assert data["work_completed_previous_cents"] == 0  # no prior certified app.


class TestProjectListPagination:
    def test_project_list_returns_array_with_pagination_meta(self, api):
        """PRD §2.3: "Each list response carries the pagination bookkeeping in the meta
        object, namely limit, offset, total_count, and has_more."

        Design: Corner/entities/project_list_pagination_envelope
        """
        create_project(100_000, name="L1")
        create_project(200_000, name="L2")
        resp = api.list_projects(OWNER)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert meta["total_count"] >= 2
        assert isinstance(meta["has_more"], bool)
