"""Project lifecycle transitions, cross-entity guards, holds/resume, permit
revocation cascade, and validation-priority conflicts. Covers §3.3-§3.9.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_estimating_project, create_approved_project, create_rejected_project,
    create_scheduled_project, create_completed_project,
    create_project, add_segment, create_estimate, project_version,
    issue_permit, place_material_order, create_crew, book_crew,
    create_permit_payload, create_material_order_payload,
    create_crew_assignment_payload, approve_estimate_payload, set_clock,
    SINGLE_400_REBAR,
    TEST_USERS,
)

PM = TEST_USERS["project_manager_headers"]
EST = TEST_USERS["estimator_headers"]
INS = TEST_USERS["inspector_headers"]


class TestPermitRevokeCascade:
    def test_revoke_issued_permit_forces_scheduled_project_on_hold(self, api):
        """PRD §3.4: "Revocation carries a consequence: if the owning project is in
        SCHEDULED at the moment of revocation, the project is forced into ON_HOLD
        and its status_before_hold is snapshotted as SCHEDULED, with the project's
        version incremented alongside the permit's."

        Design: Difficulty/transitive_cascade/permit_revoke_depth2_forces_hold
        """
        set_clock("2026-06-01T00:00:00Z")
        bundle = create_scheduled_project(
            segments=SINGLE_400_REBAR, site_name="Rev A", mix_type="STANDARD",
            pour_scheduled_start="2026-06-02T12:00:00Z", pour_duration_hours=4,
            window_start="2026-06-02T12:00:00Z", window_end="2026-06-02T18:00:00Z")
        permit = bundle["permit"]
        revoked = get_success_data(api.revoke_permit(permit["id"], INS))
        assert revoked["status"] == "REVOKED"
        project = get_success_data(api.get_project(bundle["project"]["id"], PM))
        assert project["status"] == "ON_HOLD"
        assert project["status_before_hold"] == "SCHEDULED"

    def test_revoke_permit_on_non_scheduled_project_leaves_status(self, api):
        """PRD §3.4: "If the project is not SCHEDULED, only the permit's version
        increments."

        Design: Difficulty/transitive_cascade/permit_revoke_depth2_forces_hold
        """
        # An APPROVED (not SCHEDULED) project: revoking its ISSUED permit must NOT
        # force a hold; the project keeps its APPROVED status.
        proj, est = create_approved_project(segments=SINGLE_400_REBAR, site_name="Rev B")
        permit = issue_permit(proj["id"])
        revoked = get_success_data(api.revoke_permit(permit["id"], INS))
        assert revoked["status"] == "REVOKED"
        project = get_success_data(api.get_project(proj["id"], PM))
        assert project["status"] == "APPROVED"
        assert project["status_before_hold"] is None


class TestSchedulePreconditionConflicts:
    def test_schedule_state_beats_referential_precondition(self, api):
        """PRD §2.6: "(6) that the target resource is in a state from which the
        requested transition is defined, yielding ERR_INVALID_STATE (HTTP 409);
        (7) cross-entity transition guards, yielding ERR_PRECONDITION_NOT_MET (HTTP
        409)"

        Design: Difficulty/priority_pair_validation_conflict/schedule_state_beats_referential_precondition
        """
        # DRAFT project (wrong state for schedule) AND missing permit/material/crew.
        # P6 state check (409 ERR_INVALID_STATE) must pre-empt P7 referential.
        proj = create_project(site_name="Sch A")
        add_segment(proj["id"], label="slab", area_sqft=400, thickness_in=4)
        res = api.schedule_project(proj["id"], PM)
        validate_error(res, "ERR_INVALID_STATE")

    def test_schedule_from_estimating_state_invalid(self, api):
        """PRD §3.5: "A ProjectManager schedules an APPROVED project, advancing it
        to SCHEDULED"
        PRD §2.6: "(6) that the target resource is in a state from which the
        requested transition is defined, yielding ERR_INVALID_STATE (HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/schedule_state_beats_referential_precondition
        """
        # ESTIMATING project (wrong state) and no permit/material/crew either:
        # the P6 state check fires ERR_INVALID_STATE before the P7 referential guard.
        proj, est = create_estimating_project(segments=SINGLE_400_REBAR, site_name="Sch B")
        assert proj["status"] == "ESTIMATING"
        res = api.schedule_project(proj["id"], PM)
        validate_error(res, "ERR_INVALID_STATE")

    def test_schedule_requires_issued_permit(self, api):
        """PRD §3.5: "A ProjectManager schedules an APPROVED project, advancing it
        to SCHEDULED, but only when three cross-entity conditions all hold: the
        project has a permit in ISSUED status, at least one material order in
        ORDERED status, and at least one crew assignment in BOOKED status."
        PRD §3.5: "If any of the three is missing, scheduling is refused with
        ERR_PRECONDITION_NOT_MET."

        Design: Difficulty/cross_entity_state_dependency/schedule_requires_permit_issued
        """
        proj, est = create_approved_project(segments=SINGLE_400_REBAR, site_name="Perm A")
        # Permit applied but NOT issued; material order and crew present.
        get_success_data(api.create_permit(proj["id"], create_permit_payload(), PM))
        place_material_order(proj["id"])
        crew = create_crew(crew_name="C5")
        book_crew(proj["id"], crew["id"], "2026-07-01T12:00:00Z", "2026-07-01T18:00:00Z")
        res = api.schedule_project(proj["id"], PM)
        validate_error(res, "ERR_PRECONDITION_NOT_MET")

    def test_schedule_succeeds_when_permit_issued(self, api):
        """PRD §3.5: "A ProjectManager schedules an APPROVED project, advancing it
        to SCHEDULED, but only when three cross-entity conditions all hold: the
        project has a permit in ISSUED status, at least one material order in
        ORDERED status, and at least one crew assignment in BOOKED status."

        Design: Difficulty/cross_entity_state_dependency/schedule_requires_permit_issued
        """
        proj, est = create_approved_project(segments=SINGLE_400_REBAR, site_name="Perm OK")
        issue_permit(proj["id"])  # ISSUED satisfies the permit condition
        place_material_order(proj["id"])
        crew = create_crew(crew_name="C5b")
        book_crew(proj["id"], crew["id"], "2026-07-01T12:00:00Z", "2026-07-01T18:00:00Z")
        project = validate_success(api.schedule_project(proj["id"], PM), 200)
        assert project["status"] == "SCHEDULED"


class TestHoldResumeInvariant:
    def test_hold_then_resume_conserves_scheduled_status(self, api):
        """PRD §3.9: "a ProjectManager may place an APPROVED or SCHEDULED project
        on hold, capturing the current status into status_before_hold and moving
        the project to ON_HOLD."
        PRD §3.9: "Resuming the project restores it to whatever status_before_hold
        recorded - back to APPROVED if it was held from APPROVED, or back to
        SCHEDULED if it was held from SCHEDULED - and clears status_before_hold to
        null."

        Design: Difficulty/compensating_invariant/project_status_conserved_hold_then_resume
        """
        set_clock("2026-06-01T00:00:00Z")
        bundle = create_scheduled_project(
            segments=SINGLE_400_REBAR, site_name="Hold A", mix_type="STANDARD")
        pid = bundle["project"]["id"]
        held = get_success_data(api.hold_project(pid, PM))
        assert held["status"] == "ON_HOLD"
        assert held["status_before_hold"] == "SCHEDULED"
        resumed = get_success_data(api.resume_project(pid, PM))
        assert resumed["status"] == "SCHEDULED"
        assert resumed["status_before_hold"] is None

    def test_hold_then_resume_conserves_approved_status(self, api):
        """PRD §3.9: "Resuming the project restores it to whatever
        status_before_hold recorded - back to APPROVED if it was held from
        APPROVED, or back to SCHEDULED if it was held from SCHEDULED - and clears
        status_before_hold to null."

        Design: Difficulty/compensating_invariant/project_status_conserved_hold_then_resume
        """
        proj, est = create_approved_project(segments=SINGLE_400_REBAR, site_name="Hold B")
        held = get_success_data(api.hold_project(proj["id"], PM))
        assert held["status"] == "ON_HOLD"
        assert held["status_before_hold"] == "APPROVED"
        resumed = get_success_data(api.resume_project(proj["id"], PM))
        assert resumed["status"] == "APPROVED"
        assert resumed["status_before_hold"] is None


class TestStateMachineGuards:
    def test_approve_estimate_from_draft_invalid_state(self, api):
        """PRD §3.3: "Approving an estimate carries the project from ESTIMATING to
        APPROVED."
        PRD §3.3: "the project must currently be ESTIMATING."

        Design: Corner/state_machines/approve_estimate_from_draft_project_returns_invalid_state
        """
        proj = create_project(site_name="IS")
        add_segment(proj["id"], label="s", area_sqft=100, thickness_in=4)
        pv = project_version(proj["id"])
        res = api.approve_estimate(
            proj["id"],
            approve_estimate_payload("00000000-0000-4000-8000-000000000001", pv),
            PM)
        validate_error(res, "ERR_INVALID_STATE")

    def test_estimate_requires_at_least_one_segment(self, api):
        """PRD §3.2: "When the Estimator creates an Estimate, the project moves
        from DRAFT to ESTIMATING, provided it is currently DRAFT and has at least
        one flatwork segment."

        Design: Corner/state_machines/estimate_requires_at_least_one_segment
        """
        proj = create_project(site_name="NoSeg")
        res = api.create_estimate(proj["id"], {}, EST)
        validate_error(res, "ERR_INVALID_STATE")

    def test_reject_then_schedule_terminal_lockdown(self, api):
        """PRD §3.3: "a ProjectManager may reject the project while it is
        ESTIMATING, which moves it to the terminal REJECTED state"
        PRD §3.5: "A ProjectManager schedules an APPROVED project, advancing it to
        SCHEDULED"

        Design: Corner/state_machines/reject_terminal_lockdown_no_further_transition
        """
        proj, est = create_rejected_project(
            segments=[dict(label="s", area_sqft=100, thickness_in=4)], site_name="Rej")
        res = api.schedule_project(proj["id"], PM)
        validate_error(res, "ERR_INVALID_STATE")

    def test_cancelled_material_order_cannot_start_pour(self, api):
        """PRD §3.6: "A material order may also be cancelled from ORDERED, moving
        it to the terminal CANCELLED state and incrementing its version."
        PRD §3.5: "Starting the pour advances a material order from ORDERED to
        POURING, and is permitted only while the order is ORDERED and its project
        is SCHEDULED."

        Design: Corner/state_machines/material_order_cancel_then_start_pour_invalid_state
        """
        proj, est = create_approved_project(segments=SINGLE_400_REBAR, site_name="Cxl")
        mo = place_material_order(proj["id"])
        get_success_data(api.cancel_material_order(mo["id"], PM))
        res = api.start_pour(mo["id"], {}, PM)
        validate_error(res, "ERR_INVALID_STATE")


class TestPermitClose:
    def test_close_before_project_completed_precondition(self, api):
        """PRD §3.4: "closing it moves ISSUED to CLOSED, but only when the owning
        project has reached COMPLETED - a close attempted on a project that is not
        yet COMPLETED is refused as a precondition failure with
        ERR_PRECONDITION_NOT_MET."

        Design: Corner/errors/permit_close_before_completed_returns_precondition
        """
        proj, est = create_approved_project(segments=SINGLE_400_REBAR, site_name="PClose")
        permit = issue_permit(proj["id"])
        res = api.close_permit(permit["id"], INS)
        validate_error(res, "ERR_PRECONDITION_NOT_MET")

    def test_approve_estimate_stale_version_after_second_estimate(self, api):
        """PRD §2.7: "When a ProjectManager approves an estimate, the request must
        carry expected_project_version equal to the project's current version; a
        mismatch is rejected with ERR_STALE_PROJECT_VERSION (HTTP 412)."
        PRD §3.2: "If an Estimator creates another estimate while the project is
        already ESTIMATING, the prior DRAFT estimate is moved to SUPERSEDED and the
        new one becomes the live DRAFT"

        Design: Corner/errors/approve_estimate_stale_version_returns_412
        """
        proj = create_project(site_name="Stale")
        add_segment(proj["id"], label="s1", area_sqft=200, thickness_in=4)
        create_estimate(proj["id"])
        pv_stale = project_version(proj["id"])
        est2 = create_estimate(proj["id"])  # supersedes prior, bumps version
        res = api.approve_estimate(
            proj["id"], approve_estimate_payload(est2["id"], pv_stale), PM)
        validate_error(res, "ERR_STALE_PROJECT_VERSION")
