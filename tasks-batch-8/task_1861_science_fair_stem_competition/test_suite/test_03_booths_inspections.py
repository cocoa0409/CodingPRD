"""Booth scheduling, display-safety inspection windows, and the judging gate.

Covers: (hall, booth_number) slot occupancy, inclusive inspection-window
boundaries on the logical clock, temporal-before-uniqueness validation
priority, the begin-judging inspection gate, the FAIL cascade withdrawing the
project (and unblocking the gate), and the independence of the project's
parallel state dimensions.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_project,
    assign_judge,
    booth_payload,
    fd_headers,
    get_assignment,
    get_edition,
    get_project,
    ops_headers,
    record_inspection,
    schedule_booth,
    set_clock,
    setup_judging,
    setup_registration_closed,
    si_headers,
    validate_error,
    validate_success,
)

# Window used by the boundary tests: two hours on 2026-08-05 (PRD §3.6).
WIN_START = "2026-08-05T10:00:00Z"
WIN_END = "2026-08-05T12:00:00Z"


class TestBoothSlotOccupancy:
    def test_same_slot_disjoint_window_rejected(self, api):
        """PRD §3.6: "the (`hall`, `booth_number`) pair must be free within
        this edition, or the request fails with `ERR_BOOTH_TAKEN`."

        Design: Difficulty/resource_temporal_overlap/booth_slot_point_occupancy_conflict
        """
        ctx = setup_registration_closed(num_projects=2, name="Occ Edition")
        pa, pb = ctx["projects"]
        schedule_booth(
            pa["id"], hall="A", booth_number=1,
            window_start="2026-08-01T00:00:00Z", window_end="2026-08-02T00:00:00Z",
        )

        resp = api_client.create_booth_assignment(
            pb["id"],
            booth_payload(
                hall="A", booth_number=1,
                inspection_window_start="2026-08-03T00:00:00Z",
                inspection_window_end="2026-08-04T00:00:00Z",
            ),
            ops_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_BOOTH_TAKEN, 422)

    def test_same_number_different_hall_accepted(self, api):
        """PRD §3.6: "the (`hall`, `booth_number`) pair must be free within
        this edition, or the request fails with `ERR_BOOTH_TAKEN`."

        Design: Difficulty/resource_temporal_overlap/booth_slot_point_occupancy_conflict
        """
        ctx = setup_registration_closed(num_projects=2, name="Occ Edition")
        pa, pb = ctx["projects"]
        schedule_booth(pa["id"], hall="A", booth_number=1)

        booth = validate_success(
            api_client.create_booth_assignment(
                pb["id"], booth_payload(hall="B", booth_number=1), ops_headers()
            ),
            201,
        )
        assert booth["hall"] == "B" and booth["booth_number"] == 1
        assert get_project(pb["id"])["inspection_status"] == "SCHEDULED"


class TestInspectionWindowBoundary:
    def test_one_tick_after_window_end_rejected(self, api):
        """PRD §3.6: "The logical clock must read within the scheduled window,
        both endpoints inclusive — `inspection_window_start` and
        `inspection_window_end` — or the result is rejected with
        `ERR_OUTSIDE_WINDOW`."

        Design: Difficulty/resource_temporal_overlap/inspection_window_inclusive_boundary_conflict
        """
        ctx = setup_registration_closed(num_projects=1, name="Win Edition", code="CHEM")
        project = ctx["projects"][0]
        schedule_booth(project["id"], hall="C", booth_number=3, window_start=WIN_START, window_end=WIN_END)
        set_clock("2026-08-05T12:00:01Z")

        resp = api_client.record_inspection_result(
            project["id"], {"result": "PASS"}, si_headers()
        )
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_WINDOW, 422)

    def test_exactly_at_window_end_accepted(self, api):
        """PRD §3.6: "The logical clock must read within the scheduled window,
        both endpoints inclusive — `inspection_window_start` and
        `inspection_window_end` — or the result is rejected with
        `ERR_OUTSIDE_WINDOW`."

        Design: Difficulty/resource_temporal_overlap/inspection_window_inclusive_boundary_conflict
        """
        ctx = setup_registration_closed(num_projects=1, name="Win Edition", code="CHEM")
        project = ctx["projects"][0]
        schedule_booth(project["id"], hall="C", booth_number=3, window_start=WIN_START, window_end=WIN_END)
        set_clock("2026-08-05T12:00:00Z")

        updated = validate_success(
            api_client.record_inspection_result(project["id"], {"result": "PASS"}, si_headers())
        )
        assert updated["inspection_status"] == "PASSED", (
            "the window end is inclusive: a result at exactly inspection_window_end must succeed"
        )


class TestTemporalBeforeUniqueness:
    def test_inverted_window_on_taken_booth_reports_window_error(self, api):
        """PRD §2.8: "Both window errors sit at this priority, ahead of the
        priority-7 uniqueness constraint — so on booth scheduling an inverted
        window surfaces as `ERR_INVALID_WINDOW` even when the requested booth
        happens to be taken as well."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_booth
        """
        ctx = setup_registration_closed(num_projects=2, name="PV2 Edition")
        pa, pb = ctx["projects"]
        schedule_booth(pa["id"], hall="A", booth_number=1)

        resp = api_client.create_booth_assignment(
            pb["id"],
            booth_payload(
                hall="A", booth_number=1,
                inspection_window_start="2026-08-10T00:00:00Z",
                inspection_window_end="2026-08-01T00:00:00Z",
            ),
            ops_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW, 422)

    def test_inverted_window_on_free_booth_reports_window_error(self, api):
        """PRD §3.6: "the window must not be inverted — a start that is not
        strictly before the end is rejected with `ERR_INVALID_WINDOW`, a
        priority-6 temporal check that surfaces ahead of any uniqueness
        failure".

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_booth
        """
        ctx = setup_registration_closed(num_projects=2, name="PV2 Edition")
        pa, pb = ctx["projects"]
        schedule_booth(pa["id"], hall="A", booth_number=1)

        resp = api_client.create_booth_assignment(
            pb["id"],
            booth_payload(
                hall="A", booth_number=9,
                inspection_window_start="2026-08-10T00:00:00Z",
                inspection_window_end="2026-08-01T00:00:00Z",
            ),
            ops_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW, 422)


class TestBeginJudgingGate:
    def test_uninspected_project_blocks_begin_judging(self, api):
        """PRD §3.6: "When the `FairDirector` begins judging —
        `REGISTRATION_CLOSED` → `JUDGING` — every `CONFIRMED` project must
        already have `inspection_status` `SCHEDULED` or `PASSED`; a single
        uninspected confirmed project blocks the transition with
        `ERR_PROJECTS_UNINSPECTED`."

        Design: Difficulty/cross_entity_state_dependency/edition_begin_judging_gated_by_project_inspection
        """
        ctx = setup_registration_closed(num_projects=1, name="Gate2 Edition", code="CHEM")
        edition_id = ctx["edition"]["id"]

        resp = api_client.begin_judging(edition_id, fd_headers())
        validate_error(resp, ApiErrorId.ERR_PROJECTS_UNINSPECTED, 409)
        assert get_edition(edition_id)["status"] == "REGISTRATION_CLOSED", (
            "a rejected begin-judging must leave the edition REGISTRATION_CLOSED"
        )

    def test_scheduling_booth_unblocks_begin_judging(self, api):
        """PRD §3.6: "every `CONFIRMED` project must already have
        `inspection_status` `SCHEDULED` or `PASSED`; a single uninspected
        confirmed project blocks the transition with
        `ERR_PROJECTS_UNINSPECTED`."

        Design: Difficulty/cross_entity_state_dependency/edition_begin_judging_gated_by_project_inspection
        """
        ctx = setup_registration_closed(num_projects=1, name="Gate2 Edition", code="CHEM")
        edition_id = ctx["edition"]["id"]
        schedule_booth(ctx["projects"][0]["id"], hall="A", booth_number=1)

        edition = validate_success(api_client.begin_judging(edition_id, fd_headers()))
        assert edition["status"] == "JUDGING"


class TestFailedInspectionCascade:
    def _setup_two_projects_one_failed(self):
        """PA CONFIRMED+PASSED; PB CONFIRMED, booth scheduled, then FAIL."""
        ctx = setup_registration_closed(num_projects=2, name="Gate Edition", code="CHEM")
        pa, pb = ctx["projects"]
        schedule_booth(pa["id"], hall="A", booth_number=1)
        schedule_booth(pb["id"], hall="A", booth_number=2)
        record_inspection(pa["id"], "PASS")
        return ctx, pa, pb

    def test_fail_marks_failed_and_withdraws(self, api):
        """PRD §3.6: "A `FAIL` moves it to `FAILED` and cascades: the project's
        `registration_status` is withdrawn, ending its season on the spot."

        Design: Difficulty/transitive_cascade/failed_inspection_cascades_project_to_editing_gating
        """
        _ctx, _pa, pb = self._setup_two_projects_one_failed()
        updated = validate_success(
            api_client.record_inspection_result(pb["id"], {"result": "FAIL"}, si_headers())
        )
        assert updated["inspection_status"] == "FAILED"
        assert updated["registration_status"] == "WITHDRAWN", (
            "the failed inspection must cascade registration_status to WITHDRAWN"
        )

    def test_withdrawn_failure_no_longer_blocks_judging(self, api):
        """PRD §3.6: "every `CONFIRMED` project must already have
        `inspection_status` `SCHEDULED` or `PASSED`; a single uninspected
        confirmed project blocks the transition with
        `ERR_PROJECTS_UNINSPECTED`."
        PRD §3.6: "A `FAIL` moves it to `FAILED` and cascades: the project's
        `registration_status` is withdrawn, ending its season on the spot."

        Design: Difficulty/transitive_cascade/failed_inspection_cascades_project_to_editing_gating
        """
        ctx, _pa, pb = self._setup_two_projects_one_failed()
        validate_success(api_client.record_inspection_result(pb["id"], {"result": "FAIL"}, si_headers()))

        edition = validate_success(api_client.begin_judging(ctx["edition"]["id"], fd_headers()))
        assert edition["status"] == "JUDGING", (
            "the FAILED project is withdrawn and no longer counts as an uninspected CONFIRMED project"
        )


class TestParallelProjectDimensions:
    def test_fail_cascade_leaves_judging_dimension(self, api):
        """PRD §3.6: "A `FAIL` moves it to `FAILED` and cascades: the project's
        `registration_status` is withdrawn, ending its season on the spot."
        PRD §2.10: "Each entity touched by a cascade is independently mutated —
        its own `updated_at` refreshed and its own `version` (where it carries
        one) incremented".

        Design: Difficulty/non_linear_state_machine/project_parallel_dimensions_independent
        """
        # Project CONFIRMED, inspection SCHEDULED (which admits begin-judging),
        # and a live judging assignment — then the inspection FAILs.
        ctx = setup_judging(num_projects=1, inspection="schedule", name="Parallel Edition")
        project = ctx["projects"][0]
        judge = ctx["judges"][0]
        assignment = assign_judge(project["id"], judge["id"])

        updated = validate_success(
            api_client.record_inspection_result(project["id"], {"result": "FAIL"}, si_headers())
        )
        assert updated["inspection_status"] == "FAILED"
        assert updated["registration_status"] == "WITHDRAWN"

        after = get_project(project["id"])
        assert_project(after)
        assert after["judging_status"] == "ASSIGNED", (
            "the inspection cascade touches registration_status only; the judging "
            "dimension must be left untouched"
        )
        assert get_assignment(assignment["id"])["status"] == "ASSIGNED", (
            "the assignment row itself is not cascaded by the failed inspection"
        )

    def test_dimensions_compose_before_failure(self, api):
        """PRD §3.6: "A `PASS` moves the project to `PASSED`." PRD §3.4: "a
        successful creation sets the project's `judging_status` to `ASSIGNED`,
        increments the judge's `active_assignment_count` by 1, and stamps the
        assignment's `assigned_at` from the logical clock."

        Design: Difficulty/non_linear_state_machine/project_parallel_dimensions_independent
        """
        ctx = setup_judging(num_projects=1, inspection="pass", name="Parallel Edition")
        project = ctx["projects"][0]
        judge = ctx["judges"][0]
        assign_judge(project["id"], judge["id"])

        mid = get_project(project["id"])
        assert mid["registration_status"] == "CONFIRMED"
        assert mid["inspection_status"] == "PASSED"
        assert mid["judging_status"] == "ASSIGNED", (
            "registration, inspection, and judging are parallel dimensions on one project"
        )
