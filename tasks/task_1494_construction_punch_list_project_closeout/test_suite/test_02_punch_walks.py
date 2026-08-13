"""Pre-punch walk scheduling rules, completion gates, and inspector overlap semantics."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_punch_walk,
    begin_punch,
    complete_walk,
    create_punch_walk_payload,
    get_trade,
    new_project,
    new_trade,
    schedule_walk,
    set_clock,
    setup_walked_project,
    validate_error,
    validate_success,
)

PM = TEST_USERS["gc_pm_headers"]
INSP = TEST_USERS["gc_inspector_headers"]


def _punch_active_project_with_trade():
    project = new_project(name="Proj")
    trade = new_trade(project["id"])
    begin_punch(project["id"])
    return project, trade


class TestWalkWindowRules:

    def test_walk_duration_thirty_minutes_boundary(self):
        """PRD §3.2: "Three rules govern the window: it may not begin before the current logical clock (`ERR_SCHEDULED_IN_PAST`); its end must fall at least 30 minutes after its start — a half-hour being the minimum credible walk — with anything shorter rejected as `ERR_INVALID_REQUEST`; and it may not collide with another walk led by the same inspector."

        Design: Corner/validations/walk_duration_thirty_minutes_boundary
        """
        project, trade = _punch_active_project_with_trade()
        short = api_client.create_punch_walk(
            create_punch_walk_payload(
                project["id"], trade["id"], lead_inspector_id="insp-1",
                scheduled_start="2026-08-03T09:00:00Z", scheduled_end="2026-08-03T09:29:00Z",
            ),
            PM,
        )
        validate_error(short, ApiErrorId.ERR_INVALID_REQUEST)

        exact = api_client.create_punch_walk(
            create_punch_walk_payload(
                project["id"], trade["id"], lead_inspector_id="insp-1",
                scheduled_start="2026-08-03T09:00:00Z", scheduled_end="2026-08-03T09:30:00Z",
            ),
            PM,
        )
        walk = validate_success(exact, 201)
        assert_punch_walk(walk)
        assert walk["status"] == "SCHEDULED"

    def test_walk_scheduled_in_past_returns_error(self):
        """PRD §3.2: "Three rules govern the window: it may not begin before the current logical clock (`ERR_SCHEDULED_IN_PAST`); its end must fall at least 30 minutes after its start — a half-hour being the minimum credible walk — with anything shorter rejected as `ERR_INVALID_REQUEST`; and it may not collide with another walk led by the same inspector."
        PRD §2.4: "Before any client call has been handled, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time on its own."

        Design: Corner/validations/walk_scheduled_in_past_returns_error
        """
        project, trade = _punch_active_project_with_trade()
        resp = api_client.create_punch_walk(
            create_punch_walk_payload(
                project["id"], trade["id"], lead_inspector_id="insp-1",
                scheduled_start="2026-07-31T09:00:00Z", scheduled_end="2026-07-31T10:00:00Z",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULED_IN_PAST)


class TestWalkCompletion:

    def test_walk_complete_before_window_returns_error(self):
        """PRD §3.2: "Completing a walk — a `GCInspector` or the `GCProjectManager` — moves it from `SCHEDULED` to `COMPLETED`, but only once the logical clock has reached its `scheduled_start`; an early attempt is rejected with `ERR_WALK_NOT_STARTED`."

        Design: Corner/validations/walk_complete_before_window_returns_error
        """
        project, trade = _punch_active_project_with_trade()
        walk = schedule_walk(project["id"], trade["id"], "insp-1",
                             "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z")
        set_clock("2026-08-03T08:00:00Z")
        early = api_client.complete_punch_walk(walk["id"], INSP)
        validate_error(early, ApiErrorId.ERR_WALK_NOT_STARTED)

        # Completing at exactly scheduled_start passes (the clock has reached it).
        set_clock("2026-08-03T09:00:00Z")
        done = validate_success(api_client.complete_punch_walk(walk["id"], INSP), 200)
        assert done["status"] == "COMPLETED"

    def test_walk_complete_twice_returns_invalid_state(self):
        """PRD §3.2: "Completing a walk — a `GCInspector` or the `GCProjectManager` — moves it from `SCHEDULED` to `COMPLETED`, but only once the logical clock has reached its `scheduled_start`; an early attempt is rejected with `ERR_WALK_NOT_STARTED`."
        PRD §2.10: "8. State-machine and project-phase validity (`ERR_INVALID_STATE`, or `ERR_PROJECT_NOT_CLOSED` for warranty reporting against a project that is not closed)."

        Design: Corner/state_machines/walk_complete_twice_returns_invalid_state
        """
        ctx = setup_walked_project(name="Proj")
        walk = ctx["walk"]
        assert walk["status"] == "COMPLETED"
        again = api_client.complete_punch_walk(walk["id"], INSP)
        validate_error(again, ApiErrorId.ERR_INVALID_STATE)
        still = validate_success(api_client.get_punch_walk(walk["id"], PM), 200)
        assert still["status"] == "COMPLETED"

    def test_walk_complete_flips_trade_has_completed_walk(self):
        """PRD §3.2: "Completion flips the trade package's `has_completed_walk` to true and triggers a recomputation of the project's substantial-completion eligibility."

        Design: Corner/state_machines/walk_complete_flips_trade_has_completed_walk
        """
        project, trade = _punch_active_project_with_trade()
        walk = schedule_walk(project["id"], trade["id"], "insp-1",
                             "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z")
        assert get_trade(trade["id"])["has_completed_walk"] is False
        set_clock("2026-08-03T10:00:00Z")
        complete_walk(walk["id"])
        assert get_trade(trade["id"])["has_completed_walk"] is True


class TestWalkCrossReference:

    def test_foreign_trade_on_walk_create_returns_error(self):
        """PRD §3.2: "With punch active, the `GCProjectManager` schedules a pre-punch walk for a trade by supplying `project_id`, the `trade_package_id` to be walked (it must belong to that project — `ERR_TRADE_NOT_IN_PROJECT`), the `lead_inspector_id` (an opaque identifier for the inspector who will lead the walk), and a window from `scheduled_start` to `scheduled_end`."

        Design: Corner/validations/foreign_trade_on_walk_create_returns_error
        """
        project_a = new_project(name="Proj A")
        trade_a = new_trade(project_a["id"], trade_name="ELECTRICAL", subcontractor_org="SparkyCo")
        project_b = new_project(name="Proj B")
        trade_b = new_trade(project_b["id"], trade_name="PLUMBING", subcontractor_org="PipeCo")
        begin_punch(project_a["id"])
        resp = api_client.create_punch_walk(
            create_punch_walk_payload(
                project_a["id"], trade_b["id"], lead_inspector_id="insp-1",
                scheduled_start="2026-08-03T09:00:00Z", scheduled_end="2026-08-03T10:00:00Z",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_TRADE_NOT_IN_PROJECT)


class TestInspectorOverlapHalfOpen:

    def test_overlapping_walk_rejected_adjacent_accepted(self):
        """PRD §3.2: "Collision uses half-open semantics: a window covers its start instant up to but not including its end instant, so a walk beginning at exactly the moment the same inspector's earlier walk ends is permissible, while any positive shared time is rejected with `ERR_WALK_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/walk_inspector_half_open_adjacency
        """
        project = new_project(name="Proj")
        trade = new_trade(project["id"])
        # PRD §3.1: trade packages may only be registered while MOBILIZED,
        # so the second trade must exist before punch operations begin.
        trade_b = new_trade(project["id"], trade_name="PLUMBING", subcontractor_org="PipeCo")
        begin_punch(project["id"])
        schedule_walk(project["id"], trade["id"], "insp-1",
                      "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z")

        # 09:30 starts inside the existing [09:00, 10:00) window: positive shared time.
        overlap = api_client.create_punch_walk(
            create_punch_walk_payload(
                project["id"], trade_b["id"], lead_inspector_id="insp-1",
                scheduled_start="2026-08-03T09:30:00Z", scheduled_end="2026-08-03T10:30:00Z",
            ),
            PM,
        )
        validate_error(overlap, ApiErrorId.ERR_WALK_OVERLAP)

        # 10:00 is exactly the prior window's end: adjacency is not an overlap.
        adjacent = api_client.create_punch_walk(
            create_punch_walk_payload(
                project["id"], trade_b["id"], lead_inspector_id="insp-1",
                scheduled_start="2026-08-03T10:00:00Z", scheduled_end="2026-08-03T11:00:00Z",
            ),
            PM,
        )
        walk = validate_success(adjacent, 201)
        assert walk["status"] == "SCHEDULED"

    def test_same_window_different_inspector_allowed(self):
        """PRD §3.2: "Three rules govern the window: it may not begin before the current logical clock (`ERR_SCHEDULED_IN_PAST`); its end must fall at least 30 minutes after its start — a half-hour being the minimum credible walk — with anything shorter rejected as `ERR_INVALID_REQUEST`; and it may not collide with another walk led by the same inspector."

        Design: Difficulty/resource_temporal_overlap/walk_inspector_half_open_adjacency
        """
        project = new_project(name="Proj")
        trade = new_trade(project["id"])
        # PRD §3.1: trade packages may only be registered while MOBILIZED,
        # so the second trade must exist before punch operations begin.
        trade_b = new_trade(project["id"], trade_name="PLUMBING", subcontractor_org="PipeCo")
        begin_punch(project["id"])
        schedule_walk(project["id"], trade["id"], "insp-1",
                      "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z")
        other = api_client.create_punch_walk(
            create_punch_walk_payload(
                project["id"], trade_b["id"], lead_inspector_id="insp-2",
                scheduled_start="2026-08-03T09:00:00Z", scheduled_end="2026-08-03T10:00:00Z",
            ),
            PM,
        )
        walk = validate_success(other, 201)
        assert walk["status"] == "SCHEDULED"
