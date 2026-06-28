"""Project parallel state axes, completion, cancellation, and cascades."""
from test_helpers import (
    api_client as _ac,
    get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    bootstrap_actors, create_measured_project, create_draft_project,
    create_baselined_project, THREE_LINE_ESTIMATE,
    setup_completed_window, setup_scheduled_window,
    request_and_approve_draw, release_draw,
    current_project_version,
)


class TestParallelAxes:
    def test_filing_permit_advances_compliance_without_touching_workflow(self, api):
        """PRD §3.4: "Filing a building permit moves the project's
        `compliance_status` from `PENDING_CLEARANCE` to `PERMIT_FILED`"
        PRD §2.8: "These two axes advance on separate triggers; a project may, for
        example, reach `ESTIMATED` on the workflow axis while still
        `PENDING_CLEARANCE` on the compliance axis."

        Design: Difficulty/non_linear_state_machine/nonlinear_project_parallel_workflow_and_compliance
        """
        proj, _meas, actors = create_measured_project()
        # create_measured_project returns the project snapshot taken at creation
        # time (DRAFT); refetch to observe the post-measurement workflow_status.
        pre = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert pre["workflow_status"] == "MEASURED"
        get_success_data(_ac.create_permit({"project_id": proj["id"], "jurisdiction": "Dallas"}, actors["pm_h"]))
        refetched = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert refetched["workflow_status"] == "MEASURED", \
            f"workflow must remain MEASURED, got {refetched['workflow_status']}"
        assert refetched["compliance_status"] == "PERMIT_FILED", \
            f"compliance must advance to PERMIT_FILED, got {refetched['compliance_status']}"

    def test_measured_workflow_stays_while_permit_filed_on_compliance(self, api):
        """PRD §3.2: "Recording the first measurement requires the project to be in
        `DRAFT`; the side effect of a successful recording is to set the project's
        `workflow_status` to `MEASURED`."
        PRD §3.4: "Filing a building permit moves the project's `compliance_status`
        from `PENDING_CLEARANCE` to `PERMIT_FILED`"

        Design: Difficulty/non_linear_state_machine/nonlinear_project_parallel_workflow_and_compliance
        """
        proj, _meas, actors = create_measured_project()
        permit = get_success_data(_ac.create_permit(
            {"project_id": proj["id"], "jurisdiction": "Dallas"}, actors["pm_h"]))
        assert permit["status"] == "FILED"
        refetched = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert refetched["workflow_status"] == "MEASURED"
        assert refetched["compliance_status"] == "PERMIT_FILED"


class TestWorkScheduleCancelCascade:
    def test_window_cancel_rejects_progress_draw_on_it(self, api):
        """PRD §3.6: "A window in `PROPOSED`, `CONFIRMED`, or `WEATHER_HOLD` may be
        cancelled, setting its `status` to `CANCELLED`; this cascades to set any
        `ProgressDraw` on that window in `REQUESTED` or `APPROVED` status to
        `REJECTED`"

        Design: Difficulty/transitive_cascade/cascade_project_cancel_depth3_to_progressdraw
        """
        # Per PRD §3.6 only a PROPOSED/CONFIRMED/WEATHER_HOLD window may be
        # cancelled (COMPLETED is terminal and not cancellable). Use a CONFIRMED
        # window and request a draw against it, then cancel — the cascade rejects
        # the REQUESTED draw on the now-CANCELLED window.
        base = setup_scheduled_window()
        proj, actors, ws = base["project"], base["actors"], base["work_schedule"]
        draw = get_success_data(_ac.create_progress_draw(
            proj["id"], {"work_schedule_id": ws["id"], "milestone_pct": 0.30}, actors["pm_h"]))
        # Cancel the (confirmed) window — cascade rejects the draw.
        cancelled_ws = validate_success(_ac.cancel_work_schedule(ws["id"], actors["pm_h"]))
        assert cancelled_ws["status"] == "CANCELLED"
        refetched_draw = validate_success(_ac.get_progress_draw(draw["id"], actors["pm_h"]))
        assert refetched_draw["status"] == "REJECTED", \
            f"draw on a cancelled window must be REJECTED, got {refetched_draw['status']}"

    def test_window_cancel_sets_status_cancelled(self, api):
        """PRD §3.6: "A window in `PROPOSED`, `CONFIRMED`, or `WEATHER_HOLD` may be
        cancelled, setting its `status` to `CANCELLED`; this cascades to set any
        `ProgressDraw` on that window in `REQUESTED` or `APPROVED` status to
        `REJECTED`"

        Design: Difficulty/transitive_cascade/cascade_project_cancel_depth3_to_progressdraw
        """
        # CONFIRMED window (cancellable per PRD §3.6) with a REQUESTED draw on it.
        base = setup_scheduled_window()
        actors, ws = base["actors"], base["work_schedule"]
        proj = base["project"]
        draw = get_success_data(_ac.create_progress_draw(
            proj["id"], {"work_schedule_id": ws["id"], "milestone_pct": 0.30}, actors["pm_h"]))
        _ac.cancel_work_schedule(ws["id"], actors["pm_h"])
        refetched_ws = validate_success(_ac.get_work_schedule(ws["id"], actors["pm_h"]))
        assert refetched_ws["status"] == "CANCELLED"
        refetched_draw = validate_success(_ac.get_progress_draw(draw["id"], actors["pm_h"]))
        assert refetched_draw["status"] == "REJECTED"


class TestCompletion:
    def test_complete_with_open_window_returns_open_milestones(self, api):
        """PRD §3.8: "A completion attempt with any open window or open draw is
        rejected with `ERR_OPEN_MILESTONES` (HTTP 409)."

        Design: Corner/state_machines/complete_project_with_open_milestones_returns_open_milestones
        """
        from test_helpers import setup_scheduled_window
        # Project SCHEDULED with one CONFIRMED window; start it so the project is
        # IN_PROGRESS while the window stays CONFIRMED (still open, not COMPLETED).
        sched = setup_scheduled_window()
        proj, actors, ws1 = sched["project"], sched["actors"], sched["work_schedule"]
        get_success_data(_ac.start_work_schedule(ws1["id"], actors["pm_h"]))
        resp = _ac.complete_project(proj["id"], actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_OPEN_MILESTONES.value)

    def test_complete_releases_residual_retainage_and_activates_warranties(self, api):
        """PRD §3.8: "On success the project's `workflow_status` becomes `COMPLETED`,
        every `PENDING` warranty row is activated to `ACTIVE`, and the project's
        residual retainage is released: the still-held retainage amount is added to
        `amount_released_cents` and `retainage_held_cents` is then set back to zero."

        Design: Corner/state_machines/complete_project_activates_warranties_and_releases_retainage
        """
        # Project IN_PROGRESS, contract 1324980, one COMPLETED window, draw 30% RELEASED.
        base = setup_completed_window(line_items=THREE_LINE_ESTIMATE(),
                                      measurement_overrides={"gross_wall_sqft": 2000, "opening_sqft": 200},
                                      actors=bootstrap_actors(with_finance=True))
        proj, actors, ws = base["project"], base["actors"], base["work_schedule"]
        draw = request_and_approve_draw(proj["id"], ws["id"], actors, milestone_pct=0.30)
        # gross 397494, retainage 39749, net 357745
        release_draw(proj["id"], draw["id"], actors)
        completed = validate_success(_ac.complete_project(proj["id"], actors["pm_h"]))
        assert completed["workflow_status"] == "COMPLETED"
        assert completed["retainage_held_cents"] == 0, \
            f"residual retainage must be released to 0, got {completed['retainage_held_cents']}"
        assert completed["amount_released_cents"] == 397494, \
            f"357745 net + 39749 residual retainage = 397494, got {completed['amount_released_cents']}"
        # All warranties now ACTIVE.
        data, _meta = validate_paginated(_ac.list_warranties(actors["pm_h"], params={"project_id": proj["id"]}))
        assert len(data) == 2
        assert all(w["status"] == "ACTIVE" for w in data), \
            f"all warranties must be ACTIVE, got {[w['status'] for w in data]}"


class TestCancellation:
    def test_cancel_already_cancelled_returns_cancel_not_allowed(self, api):
        """PRD §3.8: "a cancellation attempt on an ineligible status, or one omitting
        the `cancelled_reason`, is rejected with `ERR_CANCEL_NOT_ALLOWED` (HTTP 409)."

        Design: Corner/state_machines/cancel_already_cancelled_project_returns_cancel_not_allowed
        """
        proj, actors = create_draft_project()
        v0 = current_project_version(proj["id"], actors)
        get_success_data(_ac.cancel_project(
            proj["id"], {"cancelled_reason": "client backed out", "expected_project_version": v0}, actors["pm_h"]))
        v1 = current_project_version(proj["id"], actors)
        resp = _ac.cancel_project(
            proj["id"], {"cancelled_reason": "again", "expected_project_version": v1}, actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_CANCEL_NOT_ALLOWED.value)
