"""Permits for high-hazard work: JHA approval gate, the three temporal conflict
rules, validation-priority pairs, posture gates, the issued-permit counter
invariant, and manual-only cascade reversal (PRD §3.4, §2.6, §2.9)."""
from test_helpers import (
    ApiErrorId, api_client,
    validate_error, validate_success,
    assert_permit,
    create_project, create_project_with_active_plan,
    create_cleared_worker, create_worker, create_verified_certificate,
    complete_orientation, clear_worker,
    create_conducted_huddle, create_huddle, conduct_huddle,
    create_jha, approve_jha, create_approved_jha, get_jha,
    create_permit, create_issued_permit, issue_permit, close_permit,
    reinstate_permit, get_permit, get_project,
    create_incident, investigate_incident, record_determination, close_incident,
    setup_jobsite_with_issued_permit, set_clock,
    make_safety_manager_headers, make_site_superintendent_headers,
)

SM = make_safety_manager_headers()
SS = make_site_superintendent_headers()


class TestPermitCloseStateGate:

    def test_permit_close_from_requested_rejected(self, api):
        """PRD §3.4: "A `SiteSuperintendent` closes it — optionally recording
        `completion_notes` — moving it from `ISSUED` to the terminal `CLOSED`
        state"
        PRD §2.9: "Fifth (priority 5): the target resource must be in the state
        the operation requires."

        Design: Corner/errors/permit_close_from_requested_rejected
        """
        setup = setup_jobsite_with_issued_permit(project_name="Fauntleroy",
                                                 annual_hours=19000)
        # Re-create the request without issuing: build a fresh REQUESTED permit.
        project = setup["project"]
        jha = setup["jha"]
        worker = setup["worker"]
        permit = create_permit(
            project["id"], jha["id"], permit_type="EXCAVATION",
            work_start="2026-08-05T08:00:00Z", work_end="2026-08-05T12:00:00Z",
            authorized_worker_ids=[worker["id"]],
        )
        assert permit["status"] == "REQUESTED"
        resp = api.close_permit(permit["id"], {}, SS)
        validate_error(resp, ApiErrorId.ERR_PERMIT_INVALID_STATE)


class TestPermitCreateRequiresApprovedJha:

    def test_permit_create_blocked_until_jha_approved(self, api):
        """PRD §3.4: "The request is validated at creation time against the same
        rules that govern issuance: the linked JHA must be `APPROVED` (else
        `ERR_JHA_NOT_APPROVED`)"

        Design: Difficulty/cross_entity_state_dependency/permit_create_requires_jha_approved
        """
        set_clock("2026-08-01T08:00:00Z")
        project, _plan = create_project_with_active_plan(
            name="Ballard Locks Annex", annual_hours_worked=40000
        )
        worker = create_cleared_worker(project["id"], full_name="I Petrov")
        huddle = create_conducted_huddle(project["id"],
                                         attendee_worker_ids=[worker["id"]])
        jha = create_jha(project["id"], huddle["id"],
                         task_description="torch-cut handrail", hazards="fire",
                         controls="watch + extinguisher")

        # JHA still DRAFT: creation is rejected.
        resp_blocked = api.create_permit(
            {"project_id": project["id"], "jha_id": jha["id"],
             "permit_type": "HOT_WORK",
             "work_start": "2026-08-02T08:00:00Z", "work_end": "2026-08-02T10:00:00Z",
             "authorized_worker_ids": [worker["id"]]}, SS,
        )
        validate_error(resp_blocked, ApiErrorId.ERR_JHA_NOT_APPROVED)

        # After approval the identical request succeeds.
        approve_jha(jha["id"])
        resp_ok = api.create_permit(
            {"project_id": project["id"], "jha_id": jha["id"],
             "permit_type": "HOT_WORK",
             "work_start": "2026-08-02T08:00:00Z", "work_end": "2026-08-02T10:00:00Z",
             "authorized_worker_ids": [worker["id"]]}, SS,
        )
        permit = validate_success(resp_ok, 201)
        assert_permit(permit)
        assert permit["status"] == "REQUESTED"

    def test_permit_create_blocked_when_jha_demoted_to_re_review(self, api):
        """PRD §3.3: "any time a permit referencing the JHA moves from `ISSUED` to
        `SUSPENDED` — whatever the cause — an `APPROVED` JHA is automatically
        demoted to `RE_REVIEW_REQUIRED` per §2.7, and it must be approved again
        before permits depending on it can be issued or reinstated."
        PRD §3.4: "the linked JHA must be `APPROVED` (else `ERR_JHA_NOT_APPROVED`)"

        Design: Difficulty/cross_entity_state_dependency/permit_create_requires_jha_approved
        """
        set_clock("2026-08-01T08:00:00Z")
        project, _plan = create_project_with_active_plan(
            name="Ballard Locks West", annual_hours_worked=41000
        )
        w1 = create_cleared_worker(project["id"], full_name="I Petrov")
        w2 = create_cleared_worker(project["id"], full_name="K Anders")
        huddle = create_conducted_huddle(project["id"],
                                         attendee_worker_ids=[w1["id"], w2["id"]])
        jha = create_approved_jha(project["id"], huddle["id"],
                                  task_description="edge work", hazards="fall",
                                  controls="rails")
        permit_a = create_issued_permit(
            project["id"], jha["id"], permit_type="FALL_PROTECTION",
            work_start="2026-08-02T08:00:00Z", work_end="2026-08-02T16:00:00Z",
            authorized_worker_ids=[w1["id"]],
        )

        # Suspending the crew member cascades: permit A SUSPENDED, JHA demoted.
        validate_success(
            api.suspend_worker(w1["id"], {"reason": "observed without harness"}, SM),
            200,
        )
        assert get_permit(permit_a["id"])["status"] == "SUSPENDED"
        assert get_jha(jha["id"])["status"] == "RE_REVIEW_REQUIRED"

        # A once-approved JHA is not enough: creation against the demoted JHA
        # is rejected even with a fully cleared crew.
        resp = api.create_permit(
            {"project_id": project["id"], "jha_id": jha["id"],
             "permit_type": "FALL_PROTECTION",
             "work_start": "2026-08-04T08:00:00Z", "work_end": "2026-08-04T12:00:00Z",
             "authorized_worker_ids": [w2["id"]]}, SS,
        )
        validate_error(resp, ApiErrorId.ERR_JHA_NOT_APPROVED)


class TestExcavationHalfOpenIntervals:

    def _jobsite(self, name, hours):
        set_clock("2026-08-01T08:00:00Z")
        project, _plan = create_project_with_active_plan(name=name,
                                                         annual_hours_worked=hours)
        workers = [
            create_cleared_worker(project["id"], full_name=n)
            for n in ("K Lowe", "L Mora", "M Nair")
        ]
        huddle = create_conducted_huddle(
            project["id"], attendee_worker_ids=[w["id"] for w in workers]
        )
        jha = create_approved_jha(project["id"], huddle["id"])
        return project, workers, jha

    def test_excavation_adjacency_allowed_overlap_rejected(self, api):
        """PRD §3.4: "the excavation rule uses half-open interval semantics: a new
        excavation permit conflicts with any other permit of the same project and
        type `EXCAVATION` in status `REQUESTED`, `ISSUED`, or `SUSPENDED` when the
        new permit's `work_start` is strictly before the other's `work_end` and
        the other's `work_start` is strictly before the new permit's `work_end`;
        back-to-back adjacency, where the new window starts exactly when the other
        ends, is allowed."

        Design: Difficulty/resource_temporal_overlap/excavation_adjacency_allowed_overlap_rejected
        """
        project, workers, jha = self._jobsite("Denny Regrade", 140000)
        w1, w2, w3 = workers
        permit_a = create_permit(
            project["id"], jha["id"], permit_type="EXCAVATION",
            work_start="2026-08-02T08:00:00Z", work_end="2026-08-02T16:00:00Z",
            authorized_worker_ids=[w1["id"]],
        )

        # Back-to-back adjacency (new.start == existing.end) is allowed.
        resp_b = api.create_permit(
            {"project_id": project["id"], "jha_id": jha["id"],
             "permit_type": "EXCAVATION",
             "work_start": "2026-08-02T16:00:00Z", "work_end": "2026-08-02T20:00:00Z",
             "authorized_worker_ids": [w2["id"]]}, SS,
        )
        permit_b = validate_success(resp_b, 201)
        assert permit_b["status"] == "REQUESTED"

        # True overlap (15:00 < 16:00) is rejected.
        resp_c = api.create_permit(
            {"project_id": project["id"], "jha_id": jha["id"],
             "permit_type": "EXCAVATION",
             "work_start": "2026-08-02T15:00:00Z", "work_end": "2026-08-02T18:00:00Z",
             "authorized_worker_ids": [w3["id"]]}, SS,
        )
        validate_error(resp_c, ApiErrorId.ERR_PERMIT_TIME_CONFLICT)

    def test_excavation_left_adjacency_allowed_partial_overlap_rejected(self, api):
        """PRD §3.4: "back-to-back adjacency, where the new window starts exactly
        when the other ends, is allowed."
        PRD §3.4: "a new excavation permit conflicts with any other permit of the
        same project and type `EXCAVATION` in status `REQUESTED`, `ISSUED`, or
        `SUSPENDED` when the new permit's `work_start` is strictly before the
        other's `work_end` and the other's `work_start` is strictly before the new
        permit's `work_end`"

        Design: Difficulty/resource_temporal_overlap/excavation_adjacency_allowed_overlap_rejected
        """
        project, workers, jha = self._jobsite("Denny Regrade West", 141000)
        w1, w2, w3 = workers
        create_permit(
            project["id"], jha["id"], permit_type="EXCAVATION",
            work_start="2026-08-02T08:00:00Z", work_end="2026-08-02T16:00:00Z",
            authorized_worker_ids=[w1["id"]],
        )

        # Adjacency on the left edge (new.end == existing.start) is also allowed.
        resp_left = api.create_permit(
            {"project_id": project["id"], "jha_id": jha["id"],
             "permit_type": "EXCAVATION",
             "work_start": "2026-08-02T04:00:00Z", "work_end": "2026-08-02T08:00:00Z",
             "authorized_worker_ids": [w2["id"]]}, SS,
        )
        assert validate_success(resp_left, 201)["status"] == "REQUESTED"

        # Partial overlap from the left (07:00 < 08:00 < 09:00) conflicts.
        resp_overlap = api.create_permit(
            {"project_id": project["id"], "jha_id": jha["id"],
             "permit_type": "EXCAVATION",
             "work_start": "2026-08-02T07:00:00Z", "work_end": "2026-08-02T09:00:00Z",
             "authorized_worker_ids": [w3["id"]]}, SS,
        )
        validate_error(resp_overlap, ApiErrorId.ERR_PERMIT_TIME_CONFLICT)


class TestCrewClosedIntervals:

    def _jobsite_one_worker(self, name, hours):
        set_clock("2026-08-01T08:00:00Z")
        project, _plan = create_project_with_active_plan(name=name,
                                                         annual_hours_worked=hours)
        worker = create_cleared_worker(project["id"], full_name="N Ortiz")
        huddle = create_conducted_huddle(project["id"],
                                         attendee_worker_ids=[worker["id"]])
        jha = create_approved_jha(project["id"], huddle["id"])
        return project, worker, jha

    def test_crew_touching_endpoint_conflicts(self, api):
        """PRD §3.4: "for every worker named in the new permit's
        `authorized_worker_ids`, if that worker also appears on another permit in
        status `ISSUED` or `SUSPENDED` whose window touches or overlaps the new
        window at either endpoint — the new start at or before the other's end,
        and the other's start at or before the new end — that is a conflict;
        unlike excavation, touching endpoints conflict for crew"

        Design: Difficulty/resource_temporal_overlap/crew_closed_interval_touching_conflicts
        """
        project, worker, jha = self._jobsite_one_worker("Interbay Shop", 30000)
        permit_a = create_issued_permit(
            project["id"], jha["id"], permit_type="FALL_PROTECTION",
            work_start="2026-08-03T08:00:00Z", work_end="2026-08-03T16:00:00Z",
            authorized_worker_ids=[worker["id"]],
        )

        # The new window merely TOUCHES the issued window at 16:00 — for crew
        # double-booking both endpoints are inclusive, so this conflicts.
        resp = api.create_permit(
            {"project_id": project["id"], "jha_id": jha["id"],
             "permit_type": "HOT_WORK",
             "work_start": "2026-08-03T16:00:00Z", "work_end": "2026-08-03T20:00:00Z",
             "authorized_worker_ids": [worker["id"]]}, SS,
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_TIME_CONFLICT)
        assert get_permit(permit_a["id"])["status"] == "ISSUED"

    def test_crew_gap_allowed_and_requested_permits_do_not_block(self, api):
        """PRD §3.4: "unlike excavation, touching endpoints conflict for crew, and
        `REQUESTED` permits do not block crews at all."

        Design: Difficulty/resource_temporal_overlap/crew_closed_interval_touching_conflicts
        """
        project, worker, jha = self._jobsite_one_worker("Interbay Shop Annex", 31000)
        permit_a = create_issued_permit(
            project["id"], jha["id"], permit_type="FALL_PROTECTION",
            work_start="2026-08-03T08:00:00Z", work_end="2026-08-03T16:00:00Z",
            authorized_worker_ids=[worker["id"]],
        )

        # A genuine gap (new start strictly after the issued end) does not touch.
        resp_gap = api.create_permit(
            {"project_id": project["id"], "jha_id": jha["id"],
             "permit_type": "FALL_PROTECTION",
             "work_start": "2026-08-03T17:00:00Z", "work_end": "2026-08-03T20:00:00Z",
             "authorized_worker_ids": [worker["id"]]}, SS,
        )
        assert validate_success(resp_gap, 201)["status"] == "REQUESTED"

        # A merely REQUESTED permit does not block the crew: an overlapping
        # request against the still-REQUESTED permit D is allowed.
        permit_d = create_permit(
            project["id"], jha["id"], permit_type="FALL_PROTECTION",
            work_start="2026-08-05T08:00:00Z", work_end="2026-08-05T12:00:00Z",
            authorized_worker_ids=[worker["id"]],
        )
        assert permit_d["status"] == "REQUESTED"
        resp_e = api.create_permit(
            {"project_id": project["id"], "jha_id": jha["id"],
             "permit_type": "FALL_PROTECTION",
             "work_start": "2026-08-05T10:00:00Z", "work_end": "2026-08-05T14:00:00Z",
             "authorized_worker_ids": [worker["id"]]}, SS,
        )
        assert validate_success(resp_e, 201)["status"] == "REQUESTED"


class TestPermitValidationPriority:

    def _frozen_jobsite_with_suspended_permit(self, name="Tower 12", hours=200000):
        """Permit ISSUED, then a CRITICAL incident freezes posture and the permit
        is cascade-suspended (PRD §2.6)."""
        setup = setup_jobsite_with_issued_permit(
            project_name=name, annual_hours=hours, permit_type="EXCAVATION",
        )
        create_incident(
            setup["project"]["id"], worker_id=setup["worker"]["id"],
            incident_type="INJURY", severity="CRITICAL",
            occurred_at="2026-08-02T10:00:00Z", work_related=True,
            description="trench wall collapse injury",
        )
        return setup

    def test_state_error_precedes_posture_gate_on_issue(self, api):
        """PRD §2.9: "Every write request is validated against the following
        checks in strict priority order; the first failure determines the error
        returned."
        PRD §2.9: "Fifth (priority 5): the target resource must be in the state
        the operation requires. Sixth (priority 6): business safety gates — the
        training clearance check, the posture gates, segregation of duties, the
        post-incident drug test requirement at incident close, and the
        expired-certificate rule."

        Design: Difficulty/priority_pair_validation_conflict/permit_issue_state_vs_posture_priority
        """
        setup = self._frozen_jobsite_with_suspended_permit()
        permit = setup["permit"]
        assert get_permit(permit["id"])["status"] == "SUSPENDED"
        assert get_project(setup["project"]["id"])["safety_posture"] == "FROZEN"

        # Both violations hold (SUSPENDED permit under FROZEN posture); the
        # state violation at priority 5 determines the error.
        resp = api.issue_permit(permit["id"], {}, SM)
        validate_error(resp, ApiErrorId.ERR_PERMIT_INVALID_STATE)
        assert get_permit(permit["id"])["status"] == "SUSPENDED"

    def test_state_error_still_precedes_posture_after_jha_reapproved(self, api):
        """PRD §2.9: "Every write request is validated against the following
        checks in strict priority order; the first failure determines the error
        returned."
        PRD §3.4: "the permit must be `REQUESTED` (else `ERR_PERMIT_INVALID_STATE`),
        the project's posture must be `NORMAL` (else `ERR_PROJECT_POSTURE_BLOCKED`)"

        Design: Difficulty/priority_pair_validation_conflict/permit_issue_state_vs_posture_priority
        """
        setup = self._frozen_jobsite_with_suspended_permit("Tower 12 Annex")
        permit = setup["permit"]
        jha = setup["jha"]
        # Clearing the referential gate (JHA re-approved) leaves exactly the
        # state violation (priority 5) and the posture violation (priority 6).
        approve_jha(jha["id"])
        assert get_jha(jha["id"])["status"] == "APPROVED"
        assert get_project(setup["project"]["id"])["safety_posture"] == "FROZEN"

        resp = api.issue_permit(permit["id"], {}, SM)
        validate_error(resp, ApiErrorId.ERR_PERMIT_INVALID_STATE)
        assert get_permit(permit["id"])["status"] == "SUSPENDED"

    def test_jha_violation_precedes_time_conflict_on_create(self, api):
        """PRD §2.9: "Seventh (priority 7): cross-entity reference states — an
        approved JHA behind permit operations, a conducted huddle behind JHA
        approval, a completed inspection behind deficiency creation,
        subcontractor standing behind worker clearance and reinstatement, cleared
        crew behind permit operations, oriented-or-cleared attendees behind huddle
        conduct, and an active safety plan behind orientation. Eighth (priority 8):
        temporal interval rules — permit time conflicts, certificate window
        overlap, and the post-incident drug test window."

        Design: Difficulty/priority_pair_validation_conflict/permit_create_jha_vs_overlap_priority
        """
        set_clock("2026-08-01T08:00:00Z")
        project, _plan = create_project_with_active_plan(name="Mercer Yard",
                                                         annual_hours_worked=110000)
        worker = create_cleared_worker(project["id"], full_name="G Hale")
        huddle = create_conducted_huddle(project["id"],
                                         attendee_worker_ids=[worker["id"]])
        jha1 = create_approved_jha(project["id"], huddle["id"],
                                   task_description="north trench",
                                   hazards="cave-in", controls="shoring")
        create_permit(
            project["id"], jha1["id"], permit_type="EXCAVATION",
            work_start="2026-08-02T08:00:00Z", work_end="2026-08-02T16:00:00Z",
            authorized_worker_ids=[worker["id"]],
        )
        jha2 = create_jha(project["id"], huddle["id"],
                          task_description="south trench", hazards="cave-in",
                          controls="sloping")

        # JHA DRAFT (priority 7) AND excavation overlap (priority 8) both fail;
        # the referential error is reported.
        resp = api.create_permit(
            {"project_id": project["id"], "jha_id": jha2["id"],
             "permit_type": "EXCAVATION",
             "work_start": "2026-08-02T12:00:00Z", "work_end": "2026-08-02T20:00:00Z",
             "authorized_worker_ids": [worker["id"]]}, SS,
        )
        validate_error(resp, ApiErrorId.ERR_JHA_NOT_APPROVED)

    def test_time_conflict_surfaces_after_jha_gate_cleared(self, api):
        """PRD §2.9: "Every write request is validated against the following
        checks in strict priority order; the first failure determines the error
        returned."
        PRD §3.4: "the excavation rule uses half-open interval semantics: a new
        excavation permit conflicts with any other permit of the same project and
        type `EXCAVATION` in status `REQUESTED`, `ISSUED`, or `SUSPENDED` when the
        new permit's `work_start` is strictly before the other's `work_end` and
        the other's `work_start` is strictly before the new permit's `work_end`"

        Design: Difficulty/priority_pair_validation_conflict/permit_create_jha_vs_overlap_priority
        """
        set_clock("2026-08-01T08:00:00Z")
        project, _plan = create_project_with_active_plan(name="Mercer Yard East",
                                                         annual_hours_worked=111000)
        worker = create_cleared_worker(project["id"], full_name="G Hale")
        huddle = create_conducted_huddle(project["id"],
                                         attendee_worker_ids=[worker["id"]])
        jha1 = create_approved_jha(project["id"], huddle["id"])
        create_permit(
            project["id"], jha1["id"], permit_type="EXCAVATION",
            work_start="2026-08-02T08:00:00Z", work_end="2026-08-02T16:00:00Z",
            authorized_worker_ids=[worker["id"]],
        )
        jha2 = create_jha(project["id"], huddle["id"],
                          task_description="south trench", hazards="cave-in",
                          controls="sloping")
        approve_jha(jha2["id"])

        # With the JHA now APPROVED, the underlying excavation overlap surfaces.
        resp = api.create_permit(
            {"project_id": project["id"], "jha_id": jha2["id"],
             "permit_type": "EXCAVATION",
             "work_start": "2026-08-02T12:00:00Z", "work_end": "2026-08-02T20:00:00Z",
             "authorized_worker_ids": [worker["id"]]}, SS,
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_TIME_CONFLICT)


class TestPermitPostureGate:

    def test_frozen_posture_blocks_permit_issue(self, api):
        """PRD §3.4: "the permit must be `REQUESTED` (else
        `ERR_PERMIT_INVALID_STATE`), the project's posture must be `NORMAL` (else
        `ERR_PROJECT_POSTURE_BLOCKED`)"
        PRD §2.6: "the posture is `FROZEN` if the project has any deficiency of
        severity `IMMINENT_DANGER` in status `OPEN` or `OVERDUE`, or any incident
        of severity `CRITICAL` or `FATALITY` in status `REPORTED`,
        `UNDER_INVESTIGATION`, or `DETERMINATION_MADE`."

        Design: Corner/validations/posture_frozen_blocks_permit_issue
        """
        set_clock("2026-08-01T08:00:00Z")
        project, _plan = create_project_with_active_plan(name="Magnolia",
                                                         annual_hours_worked=48000)
        worker = create_cleared_worker(project["id"], full_name="Y Zhao")
        huddle = create_conducted_huddle(project["id"],
                                         attendee_worker_ids=[worker["id"]])
        jha = create_approved_jha(project["id"], huddle["id"],
                                  task_description="deck welding", hazards="fire",
                                  controls="watch")
        permit = create_permit(
            project["id"], jha["id"], permit_type="HOT_WORK",
            work_start="2026-08-04T08:00:00Z", work_end="2026-08-04T10:00:00Z",
            authorized_worker_ids=[worker["id"]],
        )
        # The freeze suspends only ISSUED permits; this one stays REQUESTED.
        create_incident(project["id"], incident_type="NEAR_MISS",
                        severity="CRITICAL", occurred_at="2026-08-02T08:00:00Z",
                        work_related=True,
                        description="crane load drift over crew")
        assert get_project(project["id"])["safety_posture"] == "FROZEN"
        assert get_permit(permit["id"])["status"] == "REQUESTED"

        resp = api.issue_permit(permit["id"], {}, SM)
        validate_error(resp, ApiErrorId.ERR_PROJECT_POSTURE_BLOCKED)
        assert get_permit(permit["id"])["status"] == "REQUESTED"


class TestIssuedPermitCountInvariant:

    def test_issue_then_close_returns_count_to_baseline(self, api):
        """PRD §3.4: "On issuance the project's `issued_permit_count` increments
        by 1 and the project's `version` increments by 1."
        PRD §3.4: "moving it from `ISSUED` to the terminal `CLOSED` state, which
        decrements `issued_permit_count` and increments the project's `version`."

        Design: Difficulty/compensating_invariant/permit_issue_close_count_invariant
        """
        setup = setup_jobsite_with_issued_permit(project_name="Yesler Terrace",
                                                 annual_hours=85000)
        project_id = setup["project"]["id"]
        permit = setup["permit"]

        after_issue = get_project(project_id)
        assert after_issue["issued_permit_count"] == 1, (
            f"issuance increments the count: {after_issue['issued_permit_count']}"
        )

        closed = close_permit(permit["id"], completion_notes="work complete")
        assert closed["status"] == "CLOSED"
        after_close = get_project(project_id)
        assert after_close["issued_permit_count"] == 0, (
            f"close returns the count to the pre-issue baseline, got "
            f"{after_close['issued_permit_count']}"
        )

    def test_suspend_then_reinstate_returns_count(self, api):
        """PRD §3.4: "suspension also decrements `issued_permit_count`, increments
        the project's `version`, and demotes the linked JHA."
        PRD §3.4: "on success clears `suspension_reason` to an empty string,
        re-increments `issued_permit_count`, and increments the project's
        `version`."

        Design: Difficulty/compensating_invariant/permit_issue_close_count_invariant
        """
        setup = setup_jobsite_with_issued_permit(project_name="Yesler Terrace N",
                                                 annual_hours=86000)
        project_id = setup["project"]["id"]
        permit = setup["permit"]
        worker = setup["worker"]
        jha = setup["jha"]
        assert get_project(project_id)["issued_permit_count"] == 1

        # Manual worker suspension cascades: permit SUSPENDED, count decrements.
        validate_success(
            api.suspend_worker(worker["id"], {"reason": "at-risk behavior"}, SM), 200
        )
        assert get_permit(permit["id"])["status"] == "SUSPENDED"
        assert get_project(project_id)["issued_permit_count"] == 0

        # Restore the chain: worker reinstated to ORIENTED, re-cleared, JHA
        # re-approved, then the permit reinstated — count returns to 1.
        validate_success(api.reinstate_worker(worker["id"], {}, SM), 200)
        clear_worker(worker["id"])
        approve_jha(jha["id"])
        reinstated = reinstate_permit(permit["id"])
        assert reinstated["status"] == "ISSUED"
        assert reinstated["suspension_reason"] == ""
        assert get_project(project_id)["issued_permit_count"] == 1


class TestFreezeReversalIsManual:

    def test_posture_lifts_but_permit_stays_suspended_until_reinstate(self, api):
        """PRD §2.6: "When a project transitions out of `FROZEN`, no permit is
        automatically reinstated — reinstatement is a manual act."
        PRD §3.6: "Closing recomputes posture, which may lift a `FROZEN`
        contribution once the incident leaves the determination window; permits
        suspended by the freeze stay suspended, because reinstatement is manual
        only."

        Design: Corner/cross_cutting_layers/posture_auto_lifts_but_permits_need_manual_reinstate
        """
        setup = setup_jobsite_with_issued_permit(project_name="Queen Anne",
                                                 annual_hours=66000)
        project_id = setup["project"]["id"]
        permit = setup["permit"]
        jha = setup["jha"]

        # CRITICAL property-damage incident (no worker) freezes the project and
        # cascade-suspends the issued permit.
        incident = create_incident(
            project_id, incident_type="PROPERTY_DAMAGE", severity="CRITICAL",
            occurred_at="2026-08-02T10:00:00Z", work_related=True,
            description="crane struck facade; no worker involved",
        )
        assert get_project(project_id)["safety_posture"] == "FROZEN"
        assert get_permit(permit["id"])["status"] == "SUSPENDED"

        # Investigate, determine non-recordable (no worker -> no drug-test gate),
        # and close: posture reconciles to NORMAL, the permit does not.
        investigate_incident(incident["id"], "operator error", "insp-1")
        record_determination(incident["id"], manager_id="sm-1")
        closed = close_incident(incident["id"])
        assert closed["status"] == "CLOSED"
        assert get_project(project_id)["safety_posture"] == "NORMAL"
        assert get_permit(permit["id"])["status"] == "SUSPENDED", (
            "cascade suspension has no automatic reversal"
        )

        # Manual reinstatement (after re-approving the demoted JHA) restores it.
        approve_jha(jha["id"])
        reinstated = reinstate_permit(permit["id"])
        assert reinstated["status"] == "ISSUED"
