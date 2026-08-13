"""Rigging review gates: plot-submission prerequisite, segregation of duties,
the version pin, bay aggregate limits, plot load conservation, and the
supersede cascade."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_planning_production, create_plot, get_plot, add_rigging_point,
    get_rigging_point, submit_plot, approve_plot, transition_point,
    submit_point_for_review, approve_point, get_production,
    make_structural_engineer_headers,
)

PM = TEST_USERS["production_manager_headers"]
RIG = TEST_USERS["rigging_supervisor_headers"]
ENG = TEST_USERS["structural_engineer_headers"]
# The submitter's own identity reused at the approval step (self-approval attempt).
ENG_SELF = make_structural_engineer_headers("rig-1")
ENG2 = make_structural_engineer_headers("eng-2")


class TestPointReviewRequiresPlotSubmitted:
    def test_review_blocked_while_plot_draft_then_succeeds(self, api):
        """PRD §3.3: "A `RiggingSupervisor` submits a `RESERVED` point for review (`RESERVED` → `UNDER_REVIEW`), which is gated on two preconditions: the logical clock must not have passed the engineering deadline — submission must occur at or before `load_in_at` minus the venue's `engineering_submission_lead_hours`, else `ERR_ENGINEERING_DEADLINE_PASSED` (HTTP 422) — and the point's plot must be `SUBMITTED` or `APPROVED`, else `ERR_PLOT_NOT_SUBMITTED` (HTTP 409)."
        PRD §3.3: "Entering review captures `plot_version_at_submission`, the plot's current `version`, pinning the point's review to that revision of the plot."

        Design: Difficulty/cross_entity_state_dependency/point_review_requires_plot_submitted
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        point = add_rigging_point(plot["id"])
        resp = api.transition_rigging_point(point["id"], {"to": "UNDER_REVIEW"}, RIG)
        validate_error(resp, ApiErrorId.ERR_PLOT_NOT_SUBMITTED)
        plot = submit_plot(plot["id"])
        data = submit_point_for_review(point["id"])
        assert data["status"] == "UNDER_REVIEW"
        assert data["plot_version_at_submission"] == plot["version"]

    def test_review_succeeds_when_plot_approved(self, api):
        """PRD §3.3: "the point's plot must be `SUBMITTED` or `APPROVED`, else `ERR_PLOT_NOT_SUBMITTED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/point_review_requires_plot_submitted
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        point = add_rigging_point(plot["id"])
        submit_plot(plot["id"])
        plot = approve_plot(plot["id"])
        data = submit_point_for_review(point["id"])
        assert data["status"] == "UNDER_REVIEW"
        assert data["plot_version_at_submission"] == plot["version"]


class TestBayOverloadAtPlotApproval:
    def test_bay_overload_at_plot_approval_with_boundary(self, api):
        """PRD §3.3: "the bay's sum may equal the venue's `bay_aggregate_limit_kg` exactly, and a sum strictly greater rejects the approval with `ERR_BAY_OVERLOAD` (HTTP 422)."

        Design: Corner/errors/bay_overload_at_plot_approval_with_boundary
        """
        ctx = setup_planning_production()  # point cap 500, bay limit 2000
        plot = create_plot(ctx["production"])
        points = [add_rigging_point(plot["id"], point_label=f"P-{c}", deadweight_kg=500)
                  for c in "ABCDE"]
        submit_plot(plot["id"])
        resp = api.transition_plot(plot["id"], {"to": "APPROVED"}, ENG)
        validate_error(resp, ApiErrorId.ERR_BAY_OVERLOAD)  # 5 x 500 = 2500 > 2000
        transition_point(points[-1]["id"], {"to": "RELEASED"})
        data = approve_plot(plot["id"])
        assert data["status"] == "APPROVED", "bay sum exactly 2000 == limit passes"


class TestPlotApprovedInvalidTransitions:
    def test_plot_approved_cannot_return_to_submitted(self, api):
        """PRD §2.6: "the requested `to` must be a declared transition from the entity's current state for this actor, and child-creation endpoints require their parent to be in the correct state (`ERR_INVALID_STATE`, HTTP 409)."
        PRD §3.3: "Plot-level approval (`SUBMITTED` → `APPROVED`) rests with the `StructuralEngineer` and enforces the same bay aggregate rule across the plot's non-`RELEASED` points, with `ERR_BAY_OVERLOAD` on violation."

        Design: Corner/state_machines/plot_approved_cannot_return_to_submitted
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        add_rigging_point(plot["id"])
        submit_plot(plot["id"])
        approve_plot(plot["id"])
        resp = api.transition_plot(plot["id"], {"to": "SUBMITTED"}, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_plot(plot["id"])["status"] == "APPROVED"


class TestStalePlotRevision:
    def test_stale_plot_revision_blocks_point_approval(self, api):
        """PRD §3.3: "Finally, the version pin requires the plot's current `version` to still equal `plot_version_at_submission`; any intervening mutation of the plot — another reservation, a submit, a release — rejects the approval with `ERR_STALE_PLOT_REVISION` (HTTP 409)."

        Design: Corner/state_machines/stale_plot_revision_blocks_point_approval
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        point = add_rigging_point(plot["id"])
        submit_plot(plot["id"])
        point = submit_point_for_review(point["id"])
        pin = point["plot_version_at_submission"]
        plot = approve_plot(plot["id"])  # intervening plot mutation bumps its version
        assert plot["version"] == pin + 1
        resp = api.transition_rigging_point(point["id"], {"to": "APPROVED"}, ENG2)
        validate_error(resp, ApiErrorId.ERR_STALE_PLOT_REVISION)
        assert get_rigging_point(point["id"])["status"] == "UNDER_REVIEW"


class TestSodOnPointApproval:
    def test_sod_rigging_approver_is_submitter_rejected(self, api):
        """PRD §3.3: "Approving a point (`UNDER_REVIEW` → `APPROVED`) enforces three checks, evaluated in order — segregation of duties first, so a self-approval surfaces `ERR_SOD_VIOLATION` (HTTP 403) rather than being masked by later checks; then the bay aggregate load; then the version pin. Segregation of duties requires the approver's `X-User-ID` to differ from the point's `submitted_by_user_id`."

        Design: Corner/state_machines/sod_rigging_approver_is_submitter_rejected
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        point = add_rigging_point(plot["id"], supervisor_id="rig-1")
        submit_plot(plot["id"])
        submit_point_for_review(point["id"], supervisor_id="rig-1")
        # rig-1 both submitted the point and now attempts the engineering approval.
        resp = api.transition_rigging_point(point["id"], {"to": "APPROVED"}, ENG_SELF)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        data = approve_point(point["id"], engineer_id="eng-1")
        assert data["status"] == "APPROVED"


class TestPlotLoadConservation:
    def test_plot_load_conservation_add_then_release(self, api):
        """PRD §3.3: "Each reservation also recomputes the plot's `total_factored_load_kg` — the sum of `factored_load_kg` over the plot's points in `RESERVED`, `UNDER_REVIEW`, `APPROVED`, or `REJECTED` status, with `RELEASED` points excluded — and because that derived field changes, the plot's `version` increments with every reservation, which is what invalidates other holders of `expected_plot_version`."
        PRD §3.3: "A supervisor may also release a point outright from `RESERVED`, `UNDER_REVIEW`, `REJECTED`, or `APPROVED`; every release recomputes the plot's `total_factored_load_kg` and frees the `point_label`."

        Design: Difficulty/compensating_invariant/plot_load_conservation
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        add_rigging_point(plot["id"], point_label="A1", deadweight_kg=400)
        assert get_plot(plot["id"])["total_factored_load_kg"] == pytest.approx(400.00, abs=0.001)
        point_b = add_rigging_point(plot["id"], point_label="B1", deadweight_kg=100)
        assert get_plot(plot["id"])["total_factored_load_kg"] == pytest.approx(500.00, abs=0.001)
        transition_point(point_b["id"], {"to": "RELEASED"})
        assert get_plot(plot["id"])["total_factored_load_kg"] == pytest.approx(400.00, abs=0.001), \
            "the add/release pair must leave committed load unchanged"

    def test_plot_load_recomputed_on_revise_and_release(self, api):
        """PRD §3.3: "the revision recomputes `factored_load_kg` and `utilization`, re-applies the per-point capacity check with the same equality-passes rule (`ERR_POINT_OVERLOAD` on failure), and refreshes the plot's `total_factored_load_kg`."

        Design: Difficulty/compensating_invariant/plot_load_conservation
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        point = add_rigging_point(plot["id"], deadweight_kg=400)
        assert get_plot(plot["id"])["total_factored_load_kg"] == pytest.approx(400.00, abs=0.001)
        submit_plot(plot["id"])
        submit_point_for_review(point["id"])
        validate_success(api.transition_rigging_point(point["id"], {"to": "REJECTED"}, ENG))
        transition_point(point["id"], {"to": "RESERVED", "deadweight_kg": 300, "motor_count": 0})
        assert get_plot(plot["id"])["total_factored_load_kg"] == pytest.approx(300.00, abs=0.001)
        transition_point(point["id"], {"to": "RELEASED"})
        assert get_plot(plot["id"])["total_factored_load_kg"] == pytest.approx(0.00, abs=0.001)


class TestPlotApprovalSupersedeCascade:
    def _two_plots(self, api):
        """PL1 APPROVED with point APPROVED; PL2 SUBMITTED with one RESERVED point."""
        ctx = setup_planning_production()
        plot1 = create_plot(ctx["production"], title="Main Rig v1")
        point1 = add_rigging_point(plot1["id"], point_label="A1")
        submit_plot(plot1["id"])
        plot1 = approve_plot(plot1["id"])
        point1 = submit_point_for_review(point1["id"])
        point1 = approve_point(point1["id"])
        production = get_production(ctx["production"]["id"])
        plot2 = create_plot(production, title="Main Rig v2")
        point2 = add_rigging_point(plot2["id"], point_label="B1")
        submit_plot(plot2["id"])
        return ctx, plot1, point1, plot2, point2

    def test_approving_second_plot_supersedes_first(self, api):
        """PRD §3.3: "Approval stamps `approved_by_user_id` with the engineer's `X-User-ID` and `approved_at` with the logical clock, then fires the supersede cascade: any other `APPROVED` plot of the same production moves to `SUPERSEDED`, and every rigging point on that superseded plot with status `RESERVED`, `UNDER_REVIEW`, `APPROVED`, or `REJECTED` moves to `RELEASED`, which recomputes the superseded plot's `total_factored_load_kg` to 0."

        Design: Difficulty/transitive_cascade/plot_approval_supersede_cascade
        """
        _, plot1, point1, plot2, _ = self._two_plots(api)
        data = approve_plot(plot2["id"])
        assert data["status"] == "APPROVED"
        plot1_after = get_plot(plot1["id"])
        assert plot1_after["status"] == "SUPERSEDED"
        assert plot1_after["total_factored_load_kg"] == pytest.approx(0.00, abs=0.001)
        assert get_rigging_point(point1["id"])["status"] == "RELEASED"

    def test_approving_second_plot_stamps_approval_and_keeps_its_points(self, api):
        """PRD §3.3: "Approval stamps `approved_by_user_id` with the engineer's `X-User-ID` and `approved_at` with the logical clock, then fires the supersede cascade: any other `APPROVED` plot of the same production moves to `SUPERSEDED`, and every rigging point on that superseded plot with status `RESERVED`, `UNDER_REVIEW`, `APPROVED`, or `REJECTED` moves to `RELEASED`, which recomputes the superseded plot's `total_factored_load_kg` to 0."

        Design: Difficulty/transitive_cascade/plot_approval_supersede_cascade
        """
        _, plot1, _, plot2, point2 = self._two_plots(api)
        data = approve_plot(plot2["id"], engineer_id="eng-1")
        assert data["approved_by_user_id"] == "eng-1"
        assert data["approved_at"], "approved_at must be stamped at approval"
        # The newly approved plot's own points are untouched by the cascade.
        assert get_rigging_point(point2["id"])["status"] == "RESERVED"
        assert get_plot(plot1["id"])["status"] == "SUPERSEDED"
