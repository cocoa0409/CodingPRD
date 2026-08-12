"""Run interval overlap (half-open semantics), optimistic concurrency on the
line version, temporal start gating, and list/pagination behavior."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_line, create_product, create_run, schedule_run,
    create_production_run_payload, get_line_version, set_clock,
    MANAGER, SUPERVISOR, OPERATOR,
)


def _schedule_raw(run_id, line_id):
    return api_client.schedule_run(
        run_id, {"expected_line_version": get_line_version(line_id)}, SUPERVISOR)


def _plain_line_and_product(line_code):
    line = create_line(line_code, "ALLERGEN_DEDICATED")
    product = create_product(f"{line_code}-PROD", [])
    return line, product


class TestRunOverlapAdjacency:
    def test_adjacent_run_touching_at_endpoint_schedules(self, api):
        """PRD §3.4: "the run's half-open interval — including
        `planned_start_utc` and excluding `planned_end_utc`, so back-to-back
        runs touching at an endpoint do not collide — must not intersect the
        corresponding interval of any other `SCHEDULED` or `IN_PROGRESS` run on
        the same line, failing with `ERR_RUN_OVERLAP` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/run_overlap_half_open_adjacency_allowed
        """
        line, product = _plain_line_and_product("LINE-11")
        run1 = create_run(line["id"], product["id"],
                          "2026-06-10T08:00:00Z", "2026-06-10T12:00:00Z")
        run_adjacent = create_run(line["id"], product["id"],
                                  "2026-06-10T12:00:00Z", "2026-06-10T16:00:00Z")
        validate_success(_schedule_raw(run1["id"], line["id"]), 200)
        scheduled = validate_success(_schedule_raw(run_adjacent["id"], line["id"]), 200)
        assert scheduled["status"] == "SCHEDULED", (
            "A run starting exactly at the predecessor's planned_end_utc must be allowed")

    def test_overlapping_run_rejected_at_schedule(self, api):
        """PRD §3.4: "the run's half-open interval — including
        `planned_start_utc` and excluding `planned_end_utc`, so back-to-back
        runs touching at an endpoint do not collide — must not intersect the
        corresponding interval of any other `SCHEDULED` or `IN_PROGRESS` run on
        the same line, failing with `ERR_RUN_OVERLAP` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/run_overlap_half_open_adjacency_allowed
        """
        line, product = _plain_line_and_product("LINE-11B")
        run1 = create_run(line["id"], product["id"],
                          "2026-06-10T08:00:00Z", "2026-06-10T12:00:00Z")
        run_overlap = create_run(line["id"], product["id"],
                                 "2026-06-10T11:30:00Z", "2026-06-10T12:30:00Z")
        validate_success(_schedule_raw(run1["id"], line["id"]), 200)
        res = _schedule_raw(run_overlap["id"], line["id"])
        validate_error(res, "ERR_RUN_OVERLAP")


class TestRunOverlapHalfOpen:
    def test_one_minute_interior_overlap_rejected_at_schedule(self, api):
        """PRD §3.4: "Overlap is policed at creation and again at scheduling:
        the run's half-open interval — including `planned_start_utc` and
        excluding `planned_end_utc`, so back-to-back runs touching at an
        endpoint do not collide — must not intersect the corresponding interval
        of any other `SCHEDULED` or `IN_PROGRESS` run on the same line, failing
        with `ERR_RUN_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/run_interval_half_open_overlap_on_line
        """
        line, product = _plain_line_and_product("LINE-13")
        run1 = create_run(line["id"], product["id"],
                          "2026-06-12T08:00:00Z", "2026-06-12T12:00:00Z")
        run_overlap = create_run(line["id"], product["id"],
                                 "2026-06-12T11:59:00Z", "2026-06-12T13:00:00Z")
        validate_success(_schedule_raw(run1["id"], line["id"]), 200)
        res = _schedule_raw(run_overlap["id"], line["id"])
        validate_error(res, "ERR_RUN_OVERLAP")

    def test_overlapping_run_rejected_at_creation(self, api):
        """PRD §3.4: "Overlap is policed at creation and again at scheduling:
        the run's half-open interval — including `planned_start_utc` and
        excluding `planned_end_utc`, so back-to-back runs touching at an
        endpoint do not collide — must not intersect the corresponding interval
        of any other `SCHEDULED` or `IN_PROGRESS` run on the same line, failing
        with `ERR_RUN_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/run_interval_half_open_overlap_on_line
        """
        line, product = _plain_line_and_product("LINE-13B")
        run1 = create_run(line["id"], product["id"],
                          "2026-06-12T08:00:00Z", "2026-06-12T12:00:00Z")
        validate_success(_schedule_raw(run1["id"], line["id"]), 200)
        res = api.create_production_run(
            create_production_run_payload(line["id"], product["id"],
                                          planned_start_utc="2026-06-12T11:00:00Z",
                                          planned_end_utc="2026-06-12T13:00:00Z"),
            SUPERVISOR)
        validate_error(res, "ERR_RUN_OVERLAP")


class TestOccStaleLineVersion:
    def test_schedule_with_stale_line_version_rejected(self, api):
        """PRD §2.7: "Scheduling a production run requires the request to carry
        `expected_line_version`, holding the line `version` the client last
        observed. If the line's current `version` has advanced since that
        observation — for example because another supervisor has just scheduled
        a different run on the same line, legitimately changing the overlap
        universe — the schedule request is rejected with
        `ERR_STALE_LINE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_stale_line_version_on_schedule
        """
        line, product = _plain_line_and_product("LINE-OCC1")
        stale_version = line["version"]
        run_a = create_run(line["id"], product["id"],
                           "2026-06-01T08:00:00Z", "2026-06-01T09:00:00Z")
        run_b = create_run(line["id"], product["id"],
                           "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")
        # First schedule succeeds and advances the line's version.
        res_a = api.schedule_run(run_a["id"], {"expected_line_version": stale_version},
                                 SUPERVISOR)
        validate_success(res_a, 200)
        # Second schedule replays the pre-bump observation: stale.
        res_b = api.schedule_run(run_b["id"], {"expected_line_version": stale_version},
                                 SUPERVISOR)
        validate_error(res_b, "ERR_STALE_LINE_VERSION")


class TestRunStartTemporalAndState:
    def test_start_from_draft_rejected(self, api):
        """PRD §3.4: "A `LineOperator` starts the run, moving it `SCHEDULED` →
        `IN_PROGRESS`. The run must be `SCHEDULED` (`ERR_RUN_NOT_SCHEDULED`)".

        Design: Corner/state_machines/run_start_from_draft_returns_invalid_state
        """
        line, product = _plain_line_and_product("LINE-S1")
        run = create_run(line["id"], product["id"],
                         "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z")
        res = api.start_run(run["id"], OPERATOR)
        validate_error(res, "ERR_RUN_NOT_SCHEDULED")

    def test_start_before_planned_start_rejected_not_due(self, api):
        """PRD §3.4: "the logical clock must have reached `planned_start_utc` —
        starting early is rejected with `ERR_RUN_NOT_DUE` (HTTP 409)."
        PRD §2.4: "At startup the logical clock reads exactly
        2026-05-01T00:00:00Z, and it never falls back to wall-clock time
        thereafter."

        Design: Corner/validations/run_not_due_start_rejected
        """
        line, product = _plain_line_and_product("LINE-V6")
        run = create_run(line["id"], product["id"],
                         "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z")
        run = schedule_run(run)
        assert run["status"] == "SCHEDULED"
        # Clock still at the 2026-05-01 startup default: before planned start.
        res = api.start_run(run["id"], OPERATOR)
        validate_error(res, "ERR_RUN_NOT_DUE")


class TestRunListing:
    def test_list_pagination_envelope_and_status_filter(self, api):
        """PRD §2.3: "Paginated list responses carry the following fields in
        the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`." and "when omitted it defaults to 10".
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/list_pagination_defaults_and_filter
        """
        line, product = _plain_line_and_product("LINE-E1")
        for start, end in (("2026-06-01T08:00:00Z", "2026-06-01T09:00:00Z"),
                           ("2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z"),
                           ("2026-06-01T12:00:00Z", "2026-06-01T13:00:00Z")):
            create_run(line["id"], product["id"], start, end)

        data, meta = validate_paginated(
            api.list_production_runs(SUPERVISOR,
                                     params={"line_id": line["id"], "status": "DRAFT"}))
        assert meta["limit"] == 10, "default limit must be 10"
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3
        for run in data:
            assert run["status"] == "DRAFT"
            assert run["line_id"] == line["id"]


class TestChangeoverReverseLookup:
    def test_list_changeovers_filtered_by_to_run(self, api):
        """PRD §3.5: "A `QaSupervisor` plans one by naming the `line_id`, the
        `from_run_id` of the run ending (null when this is the first run ever
        scheduled on the line), the `to_run_id` of the run that will start
        afterwards, the `procedure_id` of the procedure version being executed,
        and a `scheduled_minutes` budget." — the stored to_run_id link is then
        readable back through the changeover list.

        Design: Corner/endpoints/fk_reverse_reachability_changeovers_by_run
        """
        from test_helpers import (create_allergen, create_matrix_entry,
                                  create_and_approve_procedure, create_changeover)
        allergen = create_allergen("SOY")
        line = create_line("LINE-E2", "WET_WASH")
        create_matrix_entry(line["id"], allergen["id"],
                            handling="REQUIRES_CHANGEOVER", changeover_minutes=10)
        product = create_product("P-E2", ["SOY"])
        procedure = create_and_approve_procedure(allergen["id"], "COP-E2",
                                                 min_swab_zones=1)
        run = create_run(line["id"], product["id"],
                         "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z")
        changeover = create_changeover(line["id"], run["id"], procedure["id"], 10)

        data, meta = validate_paginated(
            api.list_changeovers(SUPERVISOR, params={"to_run_id": run["id"]}))
        ids = [c["id"] for c in data]
        assert changeover["id"] in ids
        assert meta["total_count"] == 1
