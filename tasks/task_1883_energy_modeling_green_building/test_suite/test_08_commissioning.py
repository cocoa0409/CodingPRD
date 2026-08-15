"""Commissioning: agent specialty and independence gates, half-open schedule
overlap, task execution states, and the construction-phase prerequisite gate
(PRD §3.6, §3.4, §2.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    award_attempt,
    begin_review,
    complete_cx_task,
    create_attempt,
    create_credit_entry,
    create_cx_task,
    create_members,
    create_project,
    drive_attempt_ready,
    get_attempt,
    get_project,
    get_success_data,
    lock_strategy,
    make_commissioning_agent_headers,
    make_project_administrator_headers,
    start_cx_task,
    submit_phase,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANY = TEST_USERS["any_headers"]


def _project_with_cx_members(api, project_name="Tower O"):
    """Project plus a second, non-independent COMMISSIONING member."""
    members = create_members()
    cx_bad = get_success_data(
        api.create_team_member(
            {"full_name": "Chuck Cx", "email": "chuck@x.com",
             "specialty": "COMMISSIONING", "is_independent": False},
            ADMIN)
    )
    project = create_project(members["admin"]["id"], project_name=project_name)
    return members, cx_bad, project


class TestAgentEligibility:
    def test_commissioning_agent_invalid_specialty_rejected(self, api):
        """PRD §3.6: "The agent must be a team member whose `specialty` is `COMMISSIONING` — otherwise `ERR_INVALID_TEAM_MEMBER_SPECIALTY` (HTTP 422) — and must be independent: `is_independent` set to true, and not the person recorded as `created_by` on the project's `LOCKED` proposed model; either failure is rejected with `ERR_CX_AGENT_NOT_INDEPENDENT` (HTTP 403)."

        Design: Corner/validations/commissioning_agent_invalid_specialty_rejected
        """
        members = create_members()
        project = create_project(members["admin"]["id"], project_name="Agent Tower")
        # The candidate is a MANAGEMENT member carrying is_independent=true (and
        # no locked proposed model exists), so only the specialty check can fail.
        independent_manager = get_success_data(
            api.create_team_member(
                {"full_name": "Manny Manager", "email": "manny@x.com",
                 "specialty": "MANAGEMENT", "is_independent": True},
                ADMIN)
        )
        resp = api.create_commissioning_task(
            {"project_id": project["id"], "task_type": "CX_PLAN",
             "agent_id": independent_manager["id"],
             "scheduled_start": "2026-09-01T09:00:00Z",
             "scheduled_end": "2026-09-01T12:00:00Z",
             "is_prerequisite_linked": False},
            make_project_administrator_headers(members["admin"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TEAM_MEMBER_SPECIALTY)

    def test_non_independent_agent_error_precedes_overlap_error(self, api):
        """PRD §2.7: "When a request violates several rules at once, the returned error is the one belonging to the earliest stage of a fixed evaluation ladder:"
        PRD §2.7: "8. Compliance gates — segregation of duties, commissioning-agent independence, prerequisites awarded before certification, and the minimum modeled improvement (HTTP 403, 409, or 422 per gate)."
        PRD §2.7: "10. Uniqueness and structural constraints — duplicate attempts or applications, the one-analysis-per-project rule, schedule and period conflicts, empty packages, withdrawals after review has started, unresolved comments, report counts, and model lock order (HTTP 409; the empty-package, performance-tolerance, and points-floor cases answer HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_before_constraint_on_cx_schedule
        """
        members, cx_bad, project = _project_with_cx_members(api, "Tower J")
        create_cx_task(
            project["id"], members["cx"]["id"], members["admin"]["id"],
            task_type="CX_PLAN")

        resp = api.create_commissioning_task(
            {"project_id": project["id"], "task_type": "FUNCTIONAL_TESTING",
             "agent_id": cx_bad["id"],
             "scheduled_start": "2026-09-01T11:00:00Z",
             "scheduled_end": "2026-09-01T13:00:00Z",
             "is_prerequisite_linked": False},
            make_project_administrator_headers(members["admin"]["id"]),
        )
        # Both independence (safety stage) and the [11:00,13:00) overlap with
        # [09:00,12:00) (structural stage) fail; the safety stage is earlier.
        validate_error(resp, ApiErrorId.ERR_CX_AGENT_NOT_INDEPENDENT)
        assert resp.json()["data"]["error_id"] != "ERR_CX_SCHEDULE_OVERLAP"

    def test_non_independent_agent_rejected_without_overlap(self, api):
        """PRD §3.6: "The agent must be a team member whose `specialty` is `COMMISSIONING` — otherwise `ERR_INVALID_TEAM_MEMBER_SPECIALTY` (HTTP 422) — and must be independent: `is_independent` set to true, and not the person recorded as `created_by` on the project's `LOCKED` proposed model; either failure is rejected with `ERR_CX_AGENT_NOT_INDEPENDENT` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/safety_before_constraint_on_cx_schedule
        """
        members, cx_bad, project = _project_with_cx_members(api, "Tower J2")
        create_cx_task(
            project["id"], members["cx"]["id"], members["admin"]["id"],
            task_type="CX_PLAN")

        # Adjacent window [12:00,14:00): no overlap, so only independence fails.
        resp = api.create_commissioning_task(
            {"project_id": project["id"], "task_type": "FUNCTIONAL_TESTING",
             "agent_id": cx_bad["id"],
             "scheduled_start": "2026-09-01T12:00:00Z",
             "scheduled_end": "2026-09-01T14:00:00Z",
             "is_prerequisite_linked": False},
            make_project_administrator_headers(members["admin"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CX_AGENT_NOT_INDEPENDENT)


class TestHalfOpenSchedule:
    def test_adjacent_task_schedules_cleanly(self, api):
        """PRD §3.6: "Mere adjacency is not a conflict: a new task starting at exactly the moment an existing one ends schedules cleanly."

        Design: Difficulty/resource_temporal_overlap/commissioning_half_open_adjacency
        """
        members, cx_bad, project = _project_with_cx_members(api)
        t1 = create_cx_task(
            project["id"], members["cx"]["id"], members["admin"]["id"],
            task_type="CX_PLAN")

        t2 = validate_success(
            api.create_commissioning_task(
                {"project_id": project["id"], "task_type": "FUNCTIONAL_TESTING",
                 "agent_id": members["cx"]["id"],
                 "scheduled_start": "2026-09-01T12:00:00Z",
                 "scheduled_end": "2026-09-01T14:00:00Z",
                 "is_prerequisite_linked": False},
                make_project_administrator_headers(members["admin"]["id"])),
            201,
        )
        assert t2["status"] == "SCHEDULED", (
            "start == existing end is adjacency, allowed under half-open intervals")

    def test_overlapping_task_rejected(self, api):
        """PRD §3.6: "A new task conflicts with any existing task on the same project in `SCHEDULED` or `IN_PROGRESS` whose window intersects it — the new start falling before the existing end while the existing start falls before the new end — and such a conflict is rejected with `ERR_CX_SCHEDULE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/commissioning_half_open_adjacency
        """
        members, cx_bad, project = _project_with_cx_members(api)
        t1 = create_cx_task(
            project["id"], members["cx"]["id"], members["admin"]["id"],
            task_type="CX_PLAN")

        resp = api.create_commissioning_task(
            {"project_id": project["id"], "task_type": "SYSTEMS_MANUAL",
             "agent_id": members["cx"]["id"],
             "scheduled_start": "2026-09-01T11:00:00Z",
             "scheduled_end": "2026-09-01T13:00:00Z",
             "is_prerequisite_linked": False},
            make_project_administrator_headers(members["admin"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CX_SCHEDULE_OVERLAP)
        after = get_success_data(api.get_commissioning_task(t1["id"], ANY))
        assert after["status"] == "SCHEDULED"

    def test_failed_task_frees_schedule(self, api):
        """PRD §3.6: "Tasks in `PASSED` or `FAILED` never block anything."
        PRD §3.6: "Starting moves a task `SCHEDULED → IN_PROGRESS`; completing it records an `outcome` of `PASSED` or `FAILED` — optionally accompanied by `result_notes` — and moves the task from `IN_PROGRESS` to the matching terminal state, with both `outcome` and `result_notes` null until that moment."

        Design: Corner/state_machines/commissioning_failed_task_frees_schedule
        """
        members, cx_bad, project = _project_with_cx_members(api, "Retest Tower")
        t1 = create_cx_task(project["id"], members["cx"]["id"], members["admin"]["id"])
        start_cx_task(t1["id"], members["cx"]["id"])
        t1 = complete_cx_task(
            t1["id"], members["cx"]["id"], outcome="FAILED", result_notes="AHU-3 failed")
        assert t1["status"] == "FAILED"
        assert t1["outcome"] == "FAILED"
        assert t1["result_notes"] == "AHU-3 failed"

        t2 = validate_success(
            api.create_commissioning_task(
                {"project_id": project["id"], "task_type": "FUNCTIONAL_TESTING",
                 "agent_id": members["cx"]["id"],
                 "scheduled_start": "2026-09-01T10:00:00Z",
                 "scheduled_end": "2026-09-01T13:00:00Z",
                 "is_prerequisite_linked": True},
                make_project_administrator_headers(members["admin"]["id"])),
            201,
        )
        assert t2["status"] == "SCHEDULED", "a FAILED task never blocks the schedule"

    def test_complete_scheduled_task_rejected(self, api):
        """PRD §3.6: "A caller whose `X-User-ID` is not the task's `agent_id` fails with `ERR_NOT_ASSIGNED_COMMISSIONING_AGENT` (HTTP 403), and starting or completing from the wrong state fails with `ERR_INVALID_TASK_STATE` (HTTP 409)."

        Design: Corner/state_machines/complete_scheduled_task_rejected
        """
        members, cx_bad, project = _project_with_cx_members(api, "Task Tower")
        t1 = create_cx_task(
            project["id"], members["cx"]["id"], members["admin"]["id"],
            task_type="CX_PLAN", is_prerequisite_linked=False)

        resp = api.complete_commissioning_task(
            t1["id"], "PASSED", make_commissioning_agent_headers(members["cx"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_TASK_STATE)
        after = get_success_data(api.get_commissioning_task(t1["id"], ANY))
        assert after["status"] == "SCHEDULED"
        assert after["outcome"] is None


class TestConstructionCommissioningGate:
    def _design_reviewed_with_ready_construction_attempt(self, api):
        """DESIGN_REVIEWED project: prerequisite attempt awarded 20 in DESIGN;
        the construction attempt READY_FOR_SUBMITTAL; a prerequisite-linked
        commissioning task freshly SCHEDULED (not yet PASSED)."""
        members = create_members()
        admin_id = members["admin"]["id"]
        spec_id = members["spec"]["id"]
        e_p = create_credit_entry(
            credit_code="EAp1", title="Fundamental Commissioning",
            category="ENERGY_ATMOSPHERE", points_possible=20,
            is_prerequisite=True, phase_eligibility="BOTH")
        e_c = create_credit_entry(
            credit_code="MRc1", title="Materials Reuse", category="MATERIALS",
            points_possible=10, phase_eligibility="CONSTRUCTION")
        project = create_project(admin_id, project_name="Tower N")
        a_p = create_attempt(project["id"], e_p["id"], spec_id, admin_id, phase="DESIGN")
        a_c = create_attempt(project["id"], e_c["id"], spec_id, admin_id,
                             phase="CONSTRUCTION")
        lock_strategy(project["id"], admin_id)
        drive_attempt_ready(a_p["id"], spec_id, admin_id)
        submit_phase(project["id"], "DESIGN", admin_id)
        begin_review(a_p["id"])
        award_attempt(a_p["id"], raw=20)
        drive_attempt_ready(a_c["id"], spec_id, admin_id)
        task = create_cx_task(
            project["id"], members["cx"]["id"], admin_id, is_prerequisite_linked=True)
        return members, project, a_c, task

    def test_construction_submit_blocked_until_commissioning_passes(self, api):
        """PRD §3.4: "Construction submission moves the project `DESIGN_REVIEWED → CONSTRUCTION_SUBMITTED` under the same package, funds, and segregation rules, plus the commissioning gate: every commissioning task flagged `is_prerequisite_linked` on the project must already be `PASSED`, otherwise the submission fails with `ERR_COMMISSIONING_INCOMPLETE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/construction_submit_requires_commissioning_passed
        """
        members, project, a_c, task = (
            self._design_reviewed_with_ready_construction_attempt(api))
        admin_id = members["admin"]["id"]

        resp = api.submit_phase(project["id"], "CONSTRUCTION",
                                make_project_administrator_headers(admin_id))
        validate_error(resp, ApiErrorId.ERR_COMMISSIONING_INCOMPLETE)
        assert get_project(project["id"])["status"] == "DESIGN_REVIEWED"

        start_cx_task(task["id"], members["cx"]["id"])
        complete_cx_task(task["id"], members["cx"]["id"], outcome="PASSED")

        submitted = validate_success(
            api.submit_phase(project["id"], "CONSTRUCTION",
                             make_project_administrator_headers(admin_id))
        )
        assert submitted["status"] == "CONSTRUCTION_SUBMITTED"

    def test_construction_submit_debits_construction_fee(self, api):
        """PRD §3.4: "The certification fee for a phase is its base — 250,000 cents for `DESIGN`, 350,000 cents for `CONSTRUCTION` — plus 5,000 cents for every whole-or-partial thousand square feet of `gross_floor_area_sqft`, the area being divided by one thousand and rounded up to a whole number before multiplying; the total is capped at 2,000,000 cents, so the charged fee is the smaller of the computed amount and the cap."
        PRD §3.4: "On success, every included attempt transitions `READY_FOR_SUBMITTAL → SUBMITTED` with its `submission_round` incremented by one, the fee is debited, the projected and conservative levels are recomputed against the new input set, and the project's `version` increments by one."

        Design: Difficulty/cross_entity_state_dependency/construction_submit_requires_commissioning_passed
        """
        members, project, a_c, task = (
            self._design_reviewed_with_ready_construction_attempt(api))
        admin_id = members["admin"]["id"]

        resp = api.submit_phase(project["id"], "CONSTRUCTION",
                                make_project_administrator_headers(admin_id))
        validate_error(resp, ApiErrorId.ERR_COMMISSIONING_INCOMPLETE)

        start_cx_task(task["id"], members["cx"]["id"])
        complete_cx_task(task["id"], members["cx"]["id"], outcome="PASSED")
        submitted = validate_success(
            api.submit_phase(project["id"], "CONSTRUCTION",
                             make_project_administrator_headers(admin_id))
        )
        assert submitted["fee_balance_cents"] == 3200000, (
            "5000000 - 850000 design fee - 950000 construction fee; the rejected "
            "first attempt debited nothing")
        attempt = get_attempt(a_c["id"])
        assert attempt["status"] == "SUBMITTED"
        assert attempt["submission_round"] == 1
