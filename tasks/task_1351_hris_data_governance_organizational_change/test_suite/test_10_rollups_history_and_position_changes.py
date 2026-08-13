"""Subtree rollups, field-history reconstruction, and clock-applied position changes."""
import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock,
    approve_change_request_record,
    create_data_field_record,
    create_position_record,
    create_worker_record,
    get_success_data,
    list_assignment_rows,
    provision_grant,
    setup_worker_with_field,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
STEWARD = TEST_USERS["steward_headers"]


class TestSubtreeRollups:
    def test_subtree_headcount_filled_vs_budgeted(self, api, analyst_headers):
        """PRD §3.2: "In `FILLED_ONLY` mode the rollup counts distinct workers
        holding an assignment row with `row_status` `ACTIVE` whose position sits
        in the subtree. In `BUDGETED_CAPACITY` mode it instead sums
        `headcount_budget` over the subtree's `ACTIVE` positions, ignoring actual
        assignments entirely; `CLOSED` positions contribute zero."

        Design: Difficulty/dual_variant_calc/subtree_headcount_filled_vs_budgeted
        """
        root = create_position_record(title="Root", department="HQ", headcount_budget=10)
        child = create_position_record(
            title="Child", department="ENG", headcount_budget=4,
            parent_position_id=root["id"],
        )
        create_worker_record(child["id"], worker_number="W930", legal_name="W Two")

        filled = validate_success(
            api.get_subtree_metrics(root["id"], analyst_headers, params={"mode": "FILLED_ONLY"})
        )
        budgeted = validate_success(
            api.get_subtree_metrics(root["id"], analyst_headers, params={"mode": "BUDGETED_CAPACITY"})
        )
        assert filled["headcount"] == 1
        assert budgeted["headcount"] == 14
        assert filled["headcount"] != budgeted["headcount"]

    def test_subtree_headcount_modes_answer_over_same_subtree(self, api, analyst_headers):
        """PRD §3.2: "Two rollup modes serve both the close precondition and
        organizational planning, computed over the subtree — the position plus
        all transitive descendants along `parent_position_id` edges, which is
        cycle-free by construction."
        PRD §3.2: "In `FILLED_ONLY` mode the rollup counts distinct workers
        holding an assignment row with `row_status` `ACTIVE` whose position sits
        in the subtree. In `BUDGETED_CAPACITY` mode it instead sums
        `headcount_budget` over the subtree's `ACTIVE` positions, ignoring actual
        assignments entirely; `CLOSED` positions contribute zero."

        Second reading of the dual-mode rollup: the mode is echoed back and the
        two modes draw from disjoint input sets on an identical tree.

        Design: Difficulty/dual_variant_calc/subtree_headcount_filled_vs_budgeted
        """
        root = create_position_record(title="Root", department="HQ", headcount_budget=10)
        child = create_position_record(
            title="Child", department="ENG", headcount_budget=4,
            parent_position_id=root["id"],
        )
        create_worker_record(child["id"], worker_number="W931", legal_name="W Two B")

        filled = validate_success(
            api.get_subtree_metrics(root["id"], analyst_headers, params={"mode": "FILLED_ONLY"})
        )
        assert filled["mode"] == "FILLED_ONLY"
        assert filled["headcount"] == 1

        budgeted = validate_success(
            api.get_subtree_metrics(root["id"], analyst_headers, params={"mode": "BUDGETED_CAPACITY"})
        )
        assert budgeted["mode"] == "BUDGETED_CAPACITY"
        assert budgeted["headcount"] == 14

    def test_subtree_budgeted_capacity_excludes_closed_positions(self, api, analyst_headers):
        """PRD §3.2: "In `FILLED_ONLY` mode the rollup counts distinct workers
        holding an assignment row with `row_status` `ACTIVE` whose position sits
        in the subtree. In `BUDGETED_CAPACITY` mode it instead sums
        `headcount_budget` over the subtree's `ACTIVE` positions, ignoring actual
        assignments entirely; `CLOSED` positions contribute zero."

        Design: Corner/calculations/subtree_budgeted_capacity_excludes_closed_positions
        """
        root = create_position_record(title="Root", department="HQ", headcount_budget=10)
        child = create_position_record(
            title="Child", department="ENG", headcount_budget=4,
            parent_position_id=root["id"],
        )
        validate_success(api.close_position(child["id"], analyst_headers))

        budgeted = validate_success(
            api.get_subtree_metrics(root["id"], analyst_headers, params={"mode": "BUDGETED_CAPACITY"})
        )
        assert budgeted["headcount"] == 10

    def test_subtree_filled_only_excludes_future_rows(self, api, analyst_headers):
        """PRD §3.2: "In `FILLED_ONLY` mode the rollup counts distinct workers
        holding an assignment row with `row_status` `ACTIVE` whose position sits
        in the subtree. In `BUDGETED_CAPACITY` mode it instead sums
        `headcount_budget` over the subtree's `ACTIVE` positions, ignoring actual
        assignments entirely; `CLOSED` positions contribute zero."

        Design: Corner/calculations/subtree_filled_only_excludes_future_rows
        """
        root = create_position_record(title="Root", department="HQ", headcount_budget=10)
        child = create_position_record(
            title="Child", department="ENG", headcount_budget=4,
            parent_position_id=root["id"],
        )
        create_worker_record(child["id"], worker_number="W932", hire_date="2026-09-01",
                             legal_name="Fut")

        filled = validate_success(
            api.get_subtree_metrics(root["id"], analyst_headers, params={"mode": "FILLED_ONLY"})
        )
        assert filled["headcount"] == 0


class TestFieldHistory:
    def test_field_history_returns_null_when_no_row_covers(self, api, steward_headers):
        """PRD §3.9: "The base row is the worker's non-`VOIDED` assignment row
        whose half-open interval covers `as_of_date`, an open-ended row counting
        as extending without limit; if no row covers the date, the value is
        null."

        Design: Corner/calculations/field_history_returns_null_when_no_row_covers
        """
        pos = create_position_record()
        worker = create_worker_record(pos["id"], worker_number="W933", legal_name="Nul")
        field = create_data_field_record()

        before = validate_success(
            api.get_field_history(
                worker["id"], steward_headers,
                params={"field_id": field["id"], "as_of_date": "2025-06-01", "mode": "AS_IS"},
            )
        )
        assert before["value"] is None

        covered = validate_success(
            api.get_field_history(
                worker["id"], steward_headers,
                params={"field_id": field["id"], "as_of_date": "2026-06-01", "mode": "AS_IS"},
            )
        )
        assert covered["value"] == "10000"


class TestPositionChangeSweep:
    def test_clock_sweep_auto_applies_position_change(self, api):
        """PRD §3.4: "Application is the moment of mutation, performed by an
        `HrisAnalyst` on an `APPROVED` request — or, for position-targeted
        requests, by the clock sweep itself once the clock date reaches the
        `effective_date`."
        PRD §2.5: "Each clock advance re-evaluates every time-driven rule in the
        system: assignment rows derive their `row_status` from the clock relative
        to their interval (`FUTURE` rows whose start has been reached become
        `ACTIVE`; rows whose end has been reached or passed become `HISTORY`; a
        future row whose entire interval has elapsed moves directly from `FUTURE`
        to `HISTORY`); approved grants whose window has opened become
        `PROVISIONED` and grants whose window has closed become `EXPIRED`; waived
        exceptions whose waiver has lapsed reopen; scheduled batches whose
        effective date has been reached execute automatically; approved
        position-targeted change requests apply once the clock reaches their
        `effective_date`; and every exception record's `priority_score` is
        recomputed because age grows with the clock."

        Design: Corner/state_machines/clock_sweep_auto_applies_position_change
        """
        pos = create_position_record(title="Engineer")
        field = create_data_field_record(
            field_key="position.title", sensitivity="INTERNAL", channels=[],
            owner_team="people", display_name="Position Title",
        )
        provision_grant("appr-1", "CHANGE_APPROVER")

        resp = api.create_position_change_request(
            pos["id"],
            {
                "target_type": "POSITION_FIELD",
                "target_field_id": field["id"],
                "new_value": "Staff Engineer",
                "effective_date": "2026-09-01",
                "expected_position_version": pos["version"],
            },
            ANALYST,
        )
        cr = validate_success(resp, expected_status=201)
        approve_change_request_record(cr["id"], "appr-1")

        advance_clock("2026-09-01T00:00:00Z")

        cr_now = validate_success(api.get_change_request(cr["id"], ANALYST))
        assert cr_now["status"] == "APPLIED"

        pos_now = validate_success(api.get_position(pos["id"], ANALYST))
        assert pos_now["title"] == "Staff Engineer"
