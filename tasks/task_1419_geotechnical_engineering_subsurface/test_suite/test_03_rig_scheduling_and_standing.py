"""Rig scheduling: half-open window overlap, subcontractor standing,
committed-hours compensation, frozen-posture gating, and ownership."""
import pytest

from test_helpers import (
    PM,
    ApiErrorId,
    api_client,
    create_subcontractor,
    get_success_data,
    make_drilling_sub_headers,
    mobilize_assignment,
    schedule_rig,
    setup_boring_cleared,
    setup_fieldwork_project,
    setup_scoped_project,
    transition_clearance,
    transition_rig_assignment,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Half-open window overlap (difficulty instance, two tests)
# ---------------------------------------------------------------------------

class TestRigWindowHalfOpenAdjacency:
    """Rig windows are half-open intervals [window_start, window_end): a
    one-hour overlap is double-booking; an exactly adjacent start is legal."""

    def _setup_two_borings(self, api):
        ctx = setup_scoped_project(boring_count=2, schedule_first_rig=False)
        first = schedule_rig(ctx["borings"][0]["id"], ctx["subcontractor"]["id"],
                             "2026-08-03T08:00:00Z", "2026-08-03T16:00:00Z")
        ctx["first_assignment"] = first
        return ctx

    def test_overlapping_window_rejected_adjacent_window_allowed(self, api):
        """PRD section 3.2: "The window must not overlap any existing
        `SCHEDULED` or `MOBILIZED` assignment of the same subcontractor;
        because intervals are half-open, one assignment's `window_end`
        equaling another's `window_start` is permitted — an overlap is
        rejected with `ERR_RIG_DOUBLE_BOOKED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/rig_window_half_open_adjacency
        """
        ctx = self._setup_two_borings(api)
        sub_id = ctx["subcontractor"]["id"]

        overlap = api.create_rig_assignment(
            ctx["borings"][1]["id"],
            {"subcontractor_id": sub_id,
             "window_start": "2026-08-03T15:00:00Z",
             "window_end": "2026-08-03T23:00:00Z"}, PM)
        validate_error(overlap, ApiErrorId.ERR_RIG_DOUBLE_BOOKED)

        adjacent = api.create_rig_assignment(
            ctx["borings"][1]["id"],
            {"subcontractor_id": sub_id,
             "window_start": "2026-08-03T16:00:00Z",
             "window_end": "2026-08-04T08:00:00Z"}, PM)
        created = validate_success(adjacent, 201)
        assert created["status"] == "SCHEDULED", (
            "A window starting exactly at the predecessor's window_end is "
            "legal under half-open semantics"
        )

    def test_committed_hours_total_after_adjacent_booking(self, api):
        """PRD section 3.2: "Each subcontractor exposes
        `committed_rig_hours`, the sum of its outstanding rig-window
        commitments: for every one of its rig assignments in `SCHEDULED` or
        `MOBILIZED`, the window length — `window_end` minus `window_start` —
        in fractional hours, totaled and expressed with one decimal place."

        Design: Difficulty/resource_temporal_overlap/rig_window_half_open_adjacency
        """
        ctx = self._setup_two_borings(api)
        sub_id = ctx["subcontractor"]["id"]
        schedule_rig(ctx["borings"][1]["id"], sub_id,
                     "2026-08-03T16:00:00Z", "2026-08-04T08:00:00Z")

        sub = get_success_data(api.get_subcontractor(sub_id, PM))
        assert sub["committed_rig_hours"] == pytest.approx(24.0, abs=0.05), (
            f"8h window + 16h window must commit 24.0 hours, got "
            f"{sub['committed_rig_hours']}"
        )


# ---------------------------------------------------------------------------
# Committed-hours compensation (difficulty instance, two tests)
# ---------------------------------------------------------------------------

class TestRigCommittedHoursCompensation:
    """committed_rig_hours is conserved: cancel and demobilize restore the
    pre-action value exactly."""

    def test_schedule_then_cancel_restores_committed_hours(self, api):
        """PRD section 3.2: "Scheduling then cancelling, or mobilizing then
        demobilizing, restores the prior value exactly."

        Design: Difficulty/compensating_invariant/rig_schedule_cancel_restores_committed_hours
        """
        ctx = setup_scoped_project(schedule_first_rig=False)
        sub_id = ctx["subcontractor"]["id"]
        before = get_success_data(api.get_subcontractor(sub_id, PM))
        assert before["committed_rig_hours"] == pytest.approx(0.0, abs=0.05)

        assignment = schedule_rig(ctx["boring"]["id"], sub_id)  # 8-hour window
        after_schedule = get_success_data(api.get_subcontractor(sub_id, PM))
        assert after_schedule["committed_rig_hours"] == pytest.approx(8.0, abs=0.05)

        transition_rig_assignment(assignment["id"], "CANCELLED", PM)
        after_cancel = get_success_data(api.get_subcontractor(sub_id, PM))
        assert after_cancel["committed_rig_hours"] == pytest.approx(0.0, abs=0.05), (
            "Cancellation must release the window's hours as compensation"
        )

    def test_mobilize_then_demobilize_restores_committed_hours(self, api):
        """PRD section 3.2: "Scheduling then cancelling, or mobilizing then
        demobilizing, restores the prior value exactly." and "Demobilization
        (`MOBILIZED` → `DEMOBILIZED`) is likewise restricted to the owning
        `DrillingSub` and releases the window's hours from
        `committed_rig_hours`."

        Design: Difficulty/compensating_invariant/rig_schedule_cancel_restores_committed_hours
        """
        ctx = setup_scoped_project()
        sub_id = ctx["subcontractor"]["id"]
        after_schedule = get_success_data(api.get_subcontractor(sub_id, PM))
        assert after_schedule["committed_rig_hours"] == pytest.approx(8.0, abs=0.05)

        mobilize_assignment(ctx["assignment"]["id"], sub_id)
        transition_rig_assignment(ctx["assignment"]["id"], "DEMOBILIZED",
                                  make_drilling_sub_headers(sub_id))
        after_demob = get_success_data(api.get_subcontractor(sub_id, PM))
        assert after_demob["committed_rig_hours"] == pytest.approx(0.0, abs=0.05), (
            "Demobilization must release the window's hours"
        )


# ---------------------------------------------------------------------------
# Drill gating on a MOBILIZED assignment (difficulty instance, two tests)
# ---------------------------------------------------------------------------

class TestDrillRequiresMobilizedRig:
    """The boring's CLEARED -> DRILLED transition is gated on a sibling
    resource: a MOBILIZED rig assignment owned by the caller."""

    def test_drill_with_assignment_only_scheduled_rejected(self, api):
        """PRD section 3.3: "a rig assignment for this boring must stand in
        `MOBILIZED` and the caller's `X-User-ID` must equal that assignment's
        `subcontractor_id` (`ERR_RIG_NOT_MOBILIZED`, HTTP 409, otherwise)".

        Design: Difficulty/cross_entity_state_dependency/drill_requires_mobilized_rig_assignment
        """
        ctx = setup_fieldwork_project()  # assignment SCHEDULED, never mobilized
        from test_helpers import clear_boring
        clear_boring(ctx["boring"]["id"])

        resp = api.transition_boring(
            ctx["boring"]["id"],
            {"to": "DRILLED", "actual_depth_ft": 30, "rock_depth_ft": 0,
             "groundwater_depth_ft": 12, "avg_n60": 12},
            make_drilling_sub_headers(ctx["subcontractor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_RIG_NOT_MOBILIZED)

    def test_drill_succeeds_once_assignment_mobilized(self, api):
        """PRD section 3.3: "Drilling (`CLEARED` → `DRILLED`) belongs to the
        `DrillingSub`. Four gates guard it, all evaluated before any footage
        is recorded: the project must stand in `FIELDWORK`
        (`ERR_PROJECT_STATE_FORBIDS` otherwise); a rig assignment for this
        boring must stand in `MOBILIZED` and the caller's `X-User-ID` must
        equal that assignment's `subcontractor_id` (`ERR_RIG_NOT_MOBILIZED`,
        HTTP 409, otherwise); a `CLEARED` ticket of the boring must still be
        valid (`ERR_CLEARANCE_EXPIRED`); and the project must not be `FROZEN`
        (`ERR_POSTURE_FROZEN`)."

        Design: Difficulty/cross_entity_state_dependency/drill_requires_mobilized_rig_assignment
        """
        ctx = setup_boring_cleared()  # rig MOBILIZED, boring CLEARED
        from test_helpers import drill_boring
        bored = drill_boring(ctx["boring"]["id"], ctx["subcontractor"]["id"])
        assert bored["status"] == "DRILLED"
        assert bored["actual_depth_ft"] == pytest.approx(30)
        assert bored["avg_n60"] == pytest.approx(12)


# ---------------------------------------------------------------------------
# Standing vs window ordering (difficulty instance, two tests)
# ---------------------------------------------------------------------------

class TestSuspendedSubBeatsInvertedWindow:
    """A create with a suspended subcontractor and an inverted window fails
    at the earlier business-constraint category with ERR_STANDING_SUSPENDED;
    once standing is restored, the temporal error surfaces."""

    def _setup_suspended(self, api):
        ctx = setup_scoped_project(schedule_first_rig=False)
        from test_helpers import transition_subcontractor
        transition_subcontractor(ctx["subcontractor"]["id"], "SUSPENDED")
        return ctx

    def test_suspended_standing_reported_over_inverted_window(self, api):
        """PRD section 2.9: "A failure in an earlier category aborts
        evaluation, so a request never surfaces a later category's error when
        an earlier one applies", with "7. **Business constraints** — plan
        exclusivity, rig double-booking, subcontractor standing, laboratory
        capacity, rerun and appeal caps, segregation of duties, and
        uniqueness of ticket and license numbers (409 family)" preceding "8.
        **Temporal rules** — rig-window ordering and visit-date arrival
        (`ERR_INVALID_WINDOW`, `ERR_VISIT_DATE_FUTURE`, both 422)."
        PRD section 3.2: "The subcontractor must stand in `GOOD_STANDING`,
        since a suspended firm can neither receive new assignments nor
        mobilize (`ERR_STANDING_SUSPENDED`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/suspended_sub_beats_inverted_window
        """
        ctx = self._setup_suspended(api)
        resp = api.create_rig_assignment(
            ctx["boring"]["id"],
            {"subcontractor_id": ctx["subcontractor"]["id"],
             "window_start": "2026-08-04T16:00:00Z",  # end before start
             "window_end": "2026-08-04T08:00:00Z"}, PM)
        validate_error(resp, ApiErrorId.ERR_STANDING_SUSPENDED)
        assert resp.status_code == 409

    def test_inverted_window_reported_once_standing_restored(self, api):
        """PRD section 3.2: "And `window_end` must lie strictly after
        `window_start` — a temporal rule whose violation returns
        `ERR_INVALID_WINDOW` (HTTP 422), not a body-validation error."

        Design: Difficulty/priority_pair_validation_conflict/suspended_sub_beats_inverted_window
        """
        ctx = self._setup_suspended(api)
        from test_helpers import transition_subcontractor
        transition_subcontractor(ctx["subcontractor"]["id"], "GOOD_STANDING")

        resp = api.create_rig_assignment(
            ctx["boring"]["id"],
            {"subcontractor_id": ctx["subcontractor"]["id"],
             "window_start": "2026-08-04T16:00:00Z",
             "window_end": "2026-08-04T08:00:00Z"}, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Frozen posture gating (corner) and DrillingSub ownership (corner)
# ---------------------------------------------------------------------------

def test_clearance_conflict_freezes_project_and_blocks_mobilize(api):
    """PRD section 3.2: "A `ProjectManager` may mark a ticket in `FILED` or
    `CLEARED` as `CONFLICT_MARKED`; doing so recomputes the project's
    `posture` to `FROZEN`, a safety freeze that gates rig mobilization, new
    rig scheduling, boring clearance, and drilling." and "From `SCHEDULED`,
    the assigned `DrillingSub` mobilizes the rig (`SCHEDULED` → `MOBILIZED`):
    the caller's `X-User-ID` must equal the assignment's `subcontractor_id`
    (`ERR_FORBIDDEN_ROLE`), the subcontractor must remain in `GOOD_STANDING`
    (`ERR_STANDING_SUSPENDED`), and the project must not be `FROZEN`
    (`ERR_POSTURE_FROZEN`)."

    Design: Corner/state_machines/clearance_conflict_freezes_project_and_blocks_mobilize
    """
    ctx = setup_fieldwork_project(clear_tickets=False)  # ticket FILED
    transition_clearance(ctx["clearance"]["id"], "CONFLICT_MARKED", headers=PM)

    project = get_success_data(api.get_project(ctx["project"]["id"], PM))
    assert project["posture"] == "FROZEN", (
        f"Conflict-marked clearance must freeze the project, got {project['posture']}"
    )

    resp = api.transition_rig_assignment(
        ctx["assignment"]["id"], {"to": "MOBILIZED"},
        make_drilling_sub_headers(ctx["subcontractor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_POSTURE_FROZEN)


def test_drillingsub_cannot_mobilize_others_assignment(api):
    """PRD section 2.1: "When `X-User-Role` is `DrillingSub`, `X-User-ID` is
    the `id` of the acting `Subcontractor`; ownership checks compare a
    RigAssignment's `subcontractor_id` to `X-User-ID`."
    PRD section 3.2: "From `SCHEDULED`, the assigned `DrillingSub` mobilizes
    the rig (`SCHEDULED` → `MOBILIZED`): the caller's `X-User-ID` must equal
    the assignment's `subcontractor_id` (`ERR_FORBIDDEN_ROLE`)".

    Design: Corner/rbac/drillingsub_cannot_mobilize_others_assignment
    """
    ctx = setup_scoped_project()
    rival = create_subcontractor(name="RivalDrill", license_no="LIC-2",
                                 day_rate_cents=80000, max_concurrent_rigs=1)

    resp = api.transition_rig_assignment(
        ctx["assignment"]["id"], {"to": "MOBILIZED"},
        make_drilling_sub_headers(rival["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert resp.status_code == 403
