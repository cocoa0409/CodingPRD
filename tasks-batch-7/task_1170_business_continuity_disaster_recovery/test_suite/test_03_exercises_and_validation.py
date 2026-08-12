"""Exercises, validation runs, and the failover cascade (PRD §3.6, §3.7, §2.8)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    complete_exercise,
    create_active_process,
    create_approved_plan,
    create_capability,
    create_completed_exercise,
    create_contact,
    create_exercise,
    create_plan_with_sections,
    create_site,
    make_exercise_officer_headers,
    make_plan_approver_headers,
    make_plan_author_headers,
    record_validation_run,
    set_clock,
    setup_approved_program,
    start_exercise,
    submit_plan,
    validate_error,
    validate_success,
)


class TestFailoverCompletionCascade:
    def _setup(self):
        set_clock()
        author = create_contact("Author Ann", "Plan Author")
        officer = create_contact("Officer Ola", "Exercise Officer")
        process_program = setup_approved_program(
            process_name="WireTransfer", rto=4, rpo=1, criticality_tier="TIER_1")
        process = process_program["process"]
        plan = process_program["plan"]
        site = create_site(officer["id"], name="SiteBeta", region="us-west",
                           capacity_seats=50)
        capability = create_capability(process["id"], author["id"],
                                       capability_type="SITE",
                                       capability_ref_id=site["id"])
        exercise = create_exercise(
            process["id"], plan["id"], officer["id"], exercise_type="FAILOVER",
            scheduled_start="2026-06-10T09:00:00Z",
            scheduled_end="2026-06-10T17:00:00Z")
        assert exercise["requires_capability_check"] is True, (
            "requires_capability_check must be true for FAILOVER"
        )
        start_exercise(exercise["id"], officer["id"])
        return author, officer, process, plan, capability, exercise

    def test_failover_completion_missed_result_creates_gap_run(self, api):
        """PRD §3.6: "If `achieved_rto_hours` exceeds the plan's `rto_committed_hours`, or `achieved_rpo_hours` exceeds the plan's `rpo_committed_hours`, the result is `MISSED` regardless of the declared outcome — measured reality outranks declaration."
        PRD §3.6: "When the completed exercise is a `FAILOVER` (that is, `requires_capability_check` is true), completion additionally fires the **validation cascade**."
        PRD §3.7: "the result is `GAP_IDENTIFIED` when `measured_rto_hours` exceeds the target recovery time or `measured_rpo_hours` exceeds the target recovery point, and `VALIDATED` otherwise — equality to the target passes on both legs."

        Declared PARTIAL with achieved 9 against committed 4 yields MISSED, and the
        cascade-created run evaluates GAP_IDENTIFIED against the 4-hour target.

        Design: Difficulty/transitive_cascade/failover_completion_run_capability_gap_cascade
        """
        _, officer, _, _, _, exercise = self._setup()
        completed = complete_exercise(exercise["id"], officer["id"],
                                      completion_outcome="PARTIAL",
                                      achieved_rto_hours=9, achieved_rpo_hours=1)
        assert completed["status"] == "COMPLETED"
        assert completed["result"] == "MISSED", (
            "achieved 9 > committed 4 overrides the declared PARTIAL"
        )
        run_id = completed["validation_run_id"]
        assert run_id, "the failover cascade must pin validation_run_id"
        run = validate_success(
            api_client.get_validation_run(run_id, make_exercise_officer_headers(officer["id"])))
        assert run["result"] == "GAP_IDENTIFIED"
        assert run["exercise_id"] == exercise["id"]
        assert run["method"] == "FAILOVER"

    def test_failover_completion_flips_capability_and_opens_gap(self, api):
        """PRD §3.7: "On a `GAP_IDENTIFIED` result, the capability moves to `GAP_IDENTIFIED` and the server opens a capability gap — `gap_type` `CAPABILITY`, the capability in `capability_id`, `finding_id` empty — and records that gap's identifier in the run's `gap_created_id` (empty when the result is `VALIDATED`)."
        PRD §3.7: "The capability's `last_validation_run_id` is set to the new run."

        The run flips the UNPROVEN capability to GAP_IDENTIFIED and opens one OPEN gap.

        Design: Difficulty/transitive_cascade/failover_completion_run_capability_gap_cascade
        """
        _, officer, _, _, capability, exercise = self._setup()
        completed = complete_exercise(exercise["id"], officer["id"],
                                      completion_outcome="PARTIAL",
                                      achieved_rto_hours=9, achieved_rpo_hours=1)
        run_id = completed["validation_run_id"]
        cap_after = validate_success(
            api_client.get_recovery_capability(
                capability["id"], make_exercise_officer_headers(officer["id"])))
        assert cap_after["status"] == "GAP_IDENTIFIED"
        assert cap_after["last_validation_run_id"] == run_id
        gaps = validate_success(
            api_client.list_capability_gaps(capability["id"],
                                            make_exercise_officer_headers(officer["id"])))
        assert len(gaps) == 1, f"expected exactly one capability gap, got {len(gaps)}"
        assert gaps[0]["gap_type"] == "CAPABILITY"
        assert gaps[0]["status"] == "OPEN"
        assert gaps[0]["capability_id"] == capability["id"]


class TestExerciseCompletionPlanRecheck:
    def _setup_stranded_exercise(self):
        committee = create_contact("Cm One", "Risk Committee")
        approver = create_contact("Approver Al", "Plan Approver")
        program = setup_approved_program(process_name="FX", rto=8, rpo=2)
        process, plan1 = program["process"], program["plan"]
        author = program["author"]
        exercise = create_exercise(
            process["id"], plan1["id"], approver["id"], exercise_type="TABLETOP",
            scheduled_start="2026-08-01T09:00:00Z",
            scheduled_end="2026-08-01T11:00:00Z")
        start_exercise(exercise["id"], approver["id"])
        # A second plan is approved; the supersede cascade retires plan1 mid-exercise.
        plan2 = create_approved_plan(process["id"], author["id"], approver["id"],
                                     title="FX DR v2", version_no=2,
                                     strategy_type="ACTIVE_ACTIVE",
                                     rto_committed_hours=8, rpo_committed_hours=2)
        return committee, approver, process, plan1, plan2, exercise

    def test_exercise_completion_fails_after_plan_superseded(self, api):
        """PRD §3.6: "Completion re-verifies the plan: the referenced plan must still be `APPROVED` at completion time, and because a plan-approval supersede cascade may have retired it mid-exercise, a retired plan fails completion with `ERR_PLAN_NOT_APPROVED_FOR_EXERCISE`."
        PRD §3.3: "Notably, the supersede cascade retires the prior plan even while exercises still reference it; those exercises are stranded and will later fail completion, as §3.6 describes."

        The supersede cascade strands the in-progress exercise; completion is refused.

        Design: Difficulty/cross_entity_state_dependency/exercise_blocked_by_retired_plan_at_completion
        """
        _, approver, _, plan1, plan2, exercise = self._setup_stranded_exercise()
        assert plan2["status"] == "APPROVED"
        plan1_after = validate_success(
            api_client.get_plan(plan1["id"], make_plan_approver_headers(approver["id"])))
        assert plan1_after["status"] == "RETIRED", (
            "the supersede cascade must retire the previously APPROVED plan"
        )
        response = api_client.complete_exercise(
            exercise["id"],
            {"completion_outcome": "MET", "achieved_rto_hours": 8,
             "achieved_rpo_hours": 2},
            make_exercise_officer_headers(approver["id"]))
        validate_error(response, ApiErrorId.ERR_PLAN_NOT_APPROVED_FOR_EXERCISE)

    def test_exercise_stays_in_progress_after_failed_completion(self, api):
        """PRD §3.6: "Completion re-verifies the plan: the referenced plan must still be `APPROVED` at completion time, and because a plan-approval supersede cascade may have retired it mid-exercise, a retired plan fails completion with `ERR_PLAN_NOT_APPROVED_FOR_EXERCISE`."

        The rejected completion leaves the exercise IN_PROGRESS with no result.

        Design: Difficulty/cross_entity_state_dependency/exercise_blocked_by_retired_plan_at_completion
        """
        _, approver, _, _, _, exercise = self._setup_stranded_exercise()
        response = api_client.complete_exercise(
            exercise["id"],
            {"completion_outcome": "MET", "achieved_rto_hours": 8,
             "achieved_rpo_hours": 2},
            make_exercise_officer_headers(approver["id"]))
        validate_error(response, ApiErrorId.ERR_PLAN_NOT_APPROVED_FOR_EXERCISE)
        reread = validate_success(
            api_client.get_exercise(exercise["id"],
                                    make_exercise_officer_headers(approver["id"])))
        assert reread["status"] == "IN_PROGRESS"
        assert reread.get("result") in (None, ""), "no result may be frozen on failure"


class TestFailoverWindowDisjointness:
    def _setup_with_failover(self):
        program = setup_approved_program(process_name="Swift", rto=8, rpo=2,
                                         criticality_tier="TIER_1")
        process, plan = program["process"], program["plan"]
        officer = program["approver"]
        ex1 = create_exercise(
            process["id"], plan["id"], officer["id"], exercise_type="FAILOVER",
            scheduled_start="2026-09-01T09:00:00Z",
            scheduled_end="2026-09-01T17:00:00Z")
        return officer, process, plan, ex1

    def test_failover_touching_windows_rejected(self, api):
        """PRD §3.6: "For `FAILOVER` exercises only, an exclusivity rule applies: the failover windows of one process must be strictly disjoint under closed-interval semantics, meaning touching endpoints already count as overlap; a colliding schedule is rejected with `ERR_EXERCISE_WINDOW_OVERLAP`."

        A failover starting exactly at the previous failover's end collides.

        Design: Difficulty/resource_temporal_overlap/failover_exercise_closed_interval_touching_ends
        """
        officer, process, plan, _ = self._setup_with_failover()
        response = api_client.create_exercise(
            {"process_id": process["id"], "plan_id": plan["id"],
             "exercise_type": "FAILOVER",
             "scheduled_start": "2026-09-01T17:00:00Z",
             "scheduled_end": "2026-09-01T20:00:00Z"},
            make_exercise_officer_headers(officer["id"]))
        validate_error(response, ApiErrorId.ERR_EXERCISE_WINDOW_OVERLAP)

    def test_tabletop_window_exempt_from_failover_disjointness(self, api):
        """PRD §3.6: "`TABLETOP` exercises face no window-exclusivity rule."

        A tabletop fully inside a failover window schedules fine.

        Design: Difficulty/resource_temporal_overlap/failover_exercise_closed_interval_touching_ends
        """
        officer, process, plan, _ = self._setup_with_failover()
        tabletop = create_exercise(
            process["id"], plan["id"], officer["id"], exercise_type="TABLETOP",
            scheduled_start="2026-09-01T10:00:00Z",
            scheduled_end="2026-09-01T12:00:00Z")
        assert tabletop["status"] == "SCHEDULED"
        assert tabletop["requires_capability_check"] is False


class TestSchedulePrecedence:
    def _setup(self):
        committee = create_contact("Cm One", "Risk Committee")
        approver = create_contact("Approver Al", "Plan Approver")
        program = setup_approved_program(process_name="Cards", rto=8, rpo=2)
        process, plan1 = program["process"], program["plan"]
        author = program["author"]
        ex1 = create_exercise(
            process["id"], plan1["id"], approver["id"], exercise_type="FAILOVER",
            scheduled_start="2026-07-01T09:00:00Z",
            scheduled_end="2026-07-01T17:00:00Z")
        plan2 = create_plan_with_sections(
            process["id"], author["id"], title="Cards DR v2", version_no=2,
            strategy_type="WARM_SITE", rto_committed_hours=8, rpo_committed_hours=2)
        submit_plan(plan2["id"], author["id"])
        return committee, approver, author, process, plan1, plan2, ex1

    def test_schedule_with_unapproved_plan_reports_plan_error(self, api):
        """PRD §2.10: "The layers are evaluated in this fixed sequence, and the first failing layer wins"
        PRD §2.10: "an exercise's plan must be `APPROVED` at scheduling, rescheduling, and completion (`ERR_PLAN_NOT_APPROVED_FOR_EXERCISE`, HTTP 409)"
        PRD §2.10: "failover-exercise window disjointness (`ERR_EXERCISE_WINDOW_OVERLAP`, HTTP 409)"

        Scheduling against an IN_REVIEW plan fails the layer-8 safety check even
        though the window also overlaps an existing failover (layer 12).

        Design: Difficulty/priority_pair_validation_conflict/schedule_unapproved_plan_beats_window_overlap
        """
        _, approver, _, process, _, plan2, _ = self._setup()
        response = api_client.create_exercise(
            {"process_id": process["id"], "plan_id": plan2["id"],
             "exercise_type": "FAILOVER",
             "scheduled_start": "2026-07-01T12:00:00Z",
             "scheduled_end": "2026-07-01T20:00:00Z"},
            make_exercise_officer_headers(approver["id"]))
        validate_error(response, ApiErrorId.ERR_PLAN_NOT_APPROVED_FOR_EXERCISE)

    def test_schedule_rejection_creates_no_exercise(self, api):
        """PRD §3.6: "the plan must be `APPROVED` at scheduling time, else `ERR_PLAN_NOT_APPROVED_FOR_EXERCISE`."
        PRD §3.6: "The exercise calendar can be filtered by `process_id`, `plan_id`, `status`, `exercise_type`, and `validation_run_id`."

        The rejected scheduling leaves the process calendar holding only the first exercise.

        Design: Difficulty/priority_pair_validation_conflict/schedule_unapproved_plan_beats_window_overlap
        """
        _, approver, _, process, _, plan2, ex1 = self._setup()
        response = api_client.create_exercise(
            {"process_id": process["id"], "plan_id": plan2["id"],
             "exercise_type": "FAILOVER",
             "scheduled_start": "2026-07-01T12:00:00Z",
             "scheduled_end": "2026-07-01T20:00:00Z"},
            make_exercise_officer_headers(approver["id"]))
        validate_error(response, ApiErrorId.ERR_PLAN_NOT_APPROVED_FOR_EXERCISE)
        exercises = validate_success(
            api_client.list_exercises(make_exercise_officer_headers(approver["id"]),
                                      params={"process_id": process["id"]}))
        assert len(exercises) == 1
        assert exercises[0]["id"] == ex1["id"]


class TestExerciseCancelTerminal:
    def test_exercise_cancel_from_completed_rejected(self, api):
        """PRD §3.6: "Cancellation moves an exercise from either `SCHEDULED` or `IN_PROGRESS` to `CANCELLED` — terminal, no further transitions — and any other source state fails `ERR_INVALID_STATE`."

        Cancelling a COMPLETED exercise fails; the frozen result stays put.

        Design: Corner/state_machines/exercise_cancel_from_completed_rejected
        """
        program = setup_approved_program(process_name="CancelProc", rto=8, rpo=2)
        process, plan = program["process"], program["plan"]
        officer = program["approver"]
        exercise = create_completed_exercise(
            process["id"], plan["id"], officer["id"], completion_outcome="MET",
            achieved_rto_hours=8, achieved_rpo_hours=2,
            scheduled_start="2026-05-01T09:00:00Z",
            scheduled_end="2026-05-01T11:00:00Z")
        assert exercise["status"] == "COMPLETED"
        assert exercise["result"] == "MET"
        response = api_client.cancel_exercise(
            exercise["id"], make_exercise_officer_headers(officer["id"]))
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        reread = validate_success(
            api_client.get_exercise(exercise["id"],
                                    make_exercise_officer_headers(officer["id"])))
        assert reread["status"] == "COMPLETED"
        assert reread["result"] == "MET"


class TestValidationRunSupersede:
    def test_validation_run_supersedes_prior_run(self, api):
        """PRD §3.7: "At most one run per capability is `RECORDED` at any time: the prior `RECORDED` run, if any, moves to `SUPERSEDED` — it remains queryable but no longer drives anything, and per §2.5 this system transition refreshes its `updated_at` without incrementing its `version`."
        PRD §3.7: "On a `VALIDATED` result, the capability moves to `VALIDATED` from whichever of `UNPROVEN`, `GAP_IDENTIFIED`, or `REMEDIATED` it occupied, and `proven_rto_hours` and `proven_rpo_hours` are refreshed from the measured values of the capability's current `RECORDED` run"

        The second run supersedes the first; proven values track the newer RECORDED run.

        Design: Corner/state_machines/validation_run_supersedes_prior_run
        """
        program = setup_approved_program(process_name="SupProc", rto=8, rpo=2)
        process = program["process"]
        officer = program["approver"]
        author = program["author"]
        capability = create_capability(process["id"], author["id"],
                                       capability_type="DATA_RESTORE",
                                       capability_ref_id="backup-x")
        run1 = record_validation_run(capability["id"], officer["id"], 6, 1,
                                     method="COMPONENT_TEST", evidence_ref="ev1")
        assert run1["result"] == "VALIDATED"
        run2 = record_validation_run(capability["id"], officer["id"], 8, 2,
                                     method="SIMULATION", evidence_ref="ev2")
        run1_after = validate_success(
            api_client.get_validation_run(run1["id"],
                                          make_exercise_officer_headers(officer["id"])))
        assert run1_after["status"] == "SUPERSEDED"
        cap_after = validate_success(
            api_client.get_recovery_capability(
                capability["id"], make_exercise_officer_headers(officer["id"])))
        assert cap_after["status"] == "VALIDATED"
        assert cap_after["proven_rto_hours"] == 8, (
            "proven values must track the RECORDED run, not the SUPERSEDED one"
        )
        assert cap_after["last_validation_run_id"] == run2["id"]


class TestExerciseResultComputation:
    def test_exercise_result_inclusive_boundary_and_declared_outcome(self, api):
        """PRD §3.6: "If both measured values are within their committed targets (equality passes, the boundary is inclusive), then a declared `MET` yields `MET`, and any other declared outcome is honored as declared — `PARTIAL` or `MISSED`."

        Achieved 8/2 against committed 8/2: declared MET yields MET; declared MISSED
        with targets met still yields MISSED.

        Design: Corner/calculations/exercise_result_inclusive_boundary_and_declared_outcome
        """
        program = setup_approved_program(process_name="ExProc", rto=8, rpo=2)
        process, plan = program["process"], program["plan"]
        officer = program["approver"]
        ex1 = create_exercise(process["id"], plan["id"], officer["id"],
                              scheduled_start="2026-05-02T09:00:00Z",
                              scheduled_end="2026-05-02T11:00:00Z")
        ex2 = create_exercise(process["id"], plan["id"], officer["id"],
                              scheduled_start="2026-05-03T09:00:00Z",
                              scheduled_end="2026-05-03T11:00:00Z")
        start_exercise(ex1["id"], officer["id"])
        start_exercise(ex2["id"], officer["id"])
        r1 = complete_exercise(ex1["id"], officer["id"], completion_outcome="MET",
                               achieved_rto_hours=8, achieved_rpo_hours=2)
        r2 = complete_exercise(ex2["id"], officer["id"], completion_outcome="MISSED",
                               achieved_rto_hours=8, achieved_rpo_hours=2)
        assert r1["result"] == "MET", "equality to committed targets passes (inclusive)"
        assert r2["result"] == "MISSED", (
            "targets met but the officer declared MISSED — the declaration is honored"
        )


class TestCascadeRunDiscovery:
    def test_cascade_created_run_discoverable_via_reverse_get(self, api):
        """PRD §3.6: "The exercise's `validation_run_id` is pinned to the created run (it stays empty when the pool was empty and no run was created)."
        PRD §3.7: "Runs can be listed with filters on `capability_id`, `exercise_id`, `result`, `status`, and `gap_created_id`, and both per-capability and per-exercise run histories are exposed as sub-collections."

        The cascade-created run is reachable through the exercise's run sub-collection
        and the capability ends VALIDATED with proven values from the run.

        Design: Corner/endpoints/cascade_created_run_discoverable_via_reverse_get
        """
        program = setup_approved_program(process_name="RRProc", rto=8, rpo=2)
        process, plan = program["process"], program["plan"]
        officer, author = program["approver"], program["author"]
        site = create_site(officer["id"], name="RR Site", capacity_seats=40)
        capability = create_capability(process["id"], author["id"],
                                       capability_type="SITE",
                                       capability_ref_id=site["id"])
        exercise = create_exercise(
            process["id"], plan["id"], officer["id"], exercise_type="FAILOVER",
            scheduled_start="2026-11-01T09:00:00Z",
            scheduled_end="2026-11-01T17:00:00Z")
        start_exercise(exercise["id"], officer["id"])
        completed = complete_exercise(exercise["id"], officer["id"],
                                      completion_outcome="MET",
                                      achieved_rto_hours=8, achieved_rpo_hours=2)
        run_id = completed["validation_run_id"]
        assert run_id, "the failover cascade must pin validation_run_id"
        runs = validate_success(
            api_client.list_exercise_validation_runs(
                exercise["id"], make_exercise_officer_headers(officer["id"])))
        assert len(runs) == 1
        assert runs[0]["id"] == run_id
        assert runs[0]["result"] == "VALIDATED"
        cap_after = validate_success(
            api_client.get_recovery_capability(
                capability["id"], make_exercise_officer_headers(officer["id"])))
        assert cap_after["status"] == "VALIDATED"
        assert cap_after["proven_rto_hours"] == 8


class TestExerciseOptimisticConcurrency:
    def test_stale_exercise_version_on_reschedule(self, api):
        """PRD §2.8: "Rescheduling an exercise likewise requires `expected_exercise_version`, and a mismatch with the exercise's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412); the canonical case is another officer having already rescheduled the same exercise."

        After one successful reschedule advances the version, replaying the captured
        version is rejected 412.

        Design: Corner/validations/stale_exercise_version_on_reschedule
        """
        program = setup_approved_program(process_name="OccExProc", rto=8, rpo=2)
        process, plan = program["process"], program["plan"]
        officer = program["approver"]
        officer_headers = make_exercise_officer_headers(officer["id"])
        exercise = create_exercise(
            process["id"], plan["id"], officer["id"], exercise_type="TABLETOP",
            scheduled_start="2026-10-01T09:00:00Z",
            scheduled_end="2026-10-01T11:00:00Z")
        captured = exercise["version"]
        first = validate_success(
            api_client.update_exercise(
                exercise["id"],
                {"scheduled_end": "2026-10-01T12:00:00Z",
                 "expected_exercise_version": captured},
                officer_headers))
        assert first["version"] == captured + 1
        stale = api_client.update_exercise(
            exercise["id"],
            {"scheduled_end": "2026-10-01T13:00:00Z",
             "expected_exercise_version": captured},
            officer_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


class TestFindingCrossReference:
    def test_finding_process_mismatch_rejected(self, api):
        """PRD §3.6: "An officer records one against a `COMPLETED` exercise — creation against an exercise in any other state fails with `ERR_INVALID_STATE` — supplying the `exercise_id`, the affected `process_id` (which must equal the exercise's process, else `ERR_VALIDATION` with HTTP 422), a `severity` of `CRITICAL`, `HIGH`, `MEDIUM`, or `LOW`, a narrative `description`, a remediation `due_date`, and optionally a `root_cause` (which may also be filled in later at verification time)."

        A finding whose process_id differs from its exercise's process is refused
        even though both processes exist.

        Design: Corner/validations/finding_process_mismatch_rejected
        """
        program = setup_approved_program(process_name="FmP1", rto=8, rpo=2)
        process, plan = program["process"], program["plan"]
        officer = program["approver"]
        other = create_contact("Other Owner", "Owner")
        process2 = create_active_process(other["id"], name="FmP2")
        exercise = create_completed_exercise(
            process["id"], plan["id"], officer["id"], completion_outcome="MET",
            achieved_rto_hours=8, achieved_rpo_hours=2,
            scheduled_start="2026-05-04T09:00:00Z",
            scheduled_end="2026-05-04T11:00:00Z")
        response = api_client.create_finding(
            {"exercise_id": exercise["id"], "process_id": process2["id"],
             "severity": "LOW", "description": "wrong process",
             "due_date": "2026-12-01T00:00:00Z"},
            make_exercise_officer_headers(officer["id"]))
        validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)
