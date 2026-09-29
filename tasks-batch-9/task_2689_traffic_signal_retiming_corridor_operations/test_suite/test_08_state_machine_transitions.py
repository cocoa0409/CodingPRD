"""Declared transitions, refused triggers, initial states, terminal dead ends and loops."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_priority_budget_invariant,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_START
from test_helpers.fixtures import (
    ADMIN,
    CANONICAL_PLAN,
    CANONICAL_SPLITS,
    ENGINEER,
    INDEPENDENT_REVIEWER,
    LIAISON,
    TECHNICIAN,
    add_splits,
    advance_project,
    approve_config,
    certify_plan,
    close_project,
    complete_before_study,
    coordinate_project,
    corridor_complaints,
    create_corridor,
    create_intersection,
    create_requester,
    decide_corridor,
    deploy_config,
    draft_plan,
    enrol_member,
    field_tuning,
    file_complaint,
    implement_project,
    log_observation,
    open_project,
    project_observations,
    project_plans,
    project_version,
    propose_config,
    read_complaint,
    read_corridor,
    read_intersection,
    read_plan,
    read_project,
    read_requester,
    resolve_observation,
    screen_corridor,
    set_clock,
    setup_canonical_implemented_project,
    setup_draft_plan,
    setup_field_tuning_project,
    setup_project_in_plan_development,
    setup_selected_corridor,
    submit_plan,
    suspend_config,
    triage_complaint,
)

CANONICAL = {"plan_overrides": dict(CANONICAL_PLAN), "splits": CANONICAL_SPLITS}
EVP_CONFIG = {"priority_type": "EVP", "requested_max_extension_sec": 15,
              "conflict_resolution_rank": 1}
TSP_CONFIG = {"priority_type": "TSP", "requested_max_extension_sec": 10,
              "conflict_resolution_rank": 2}


def _deployed_configs(intersection_id):
    return validate_success(
        api_client.list_intersection_priority_configs(
            intersection_id, ADMIN, {"deployment_status": "DEPLOYED"}
        )
    )


def test_triage_moves_the_complaint_and_refreshes_both_derived_counters():
    """OPEN to TRIAGED bumps the version while leaving every open bucket numerically still.

    PRD §3.3: "Supplying a `disposition` of `TRIAGE`, optionally with a `note`,
    moves the complaint `OPEN → TRIAGED` ... Both dispositions refresh the
    corridor's four bucket counters and the requester's `open_complaint_count`, and
    increment the complaint's `version`. The arithmetic differs between them in a
    way worth internalising: `TRIAGED` and `OPEN` both live in the open bucket, so
    a triage leaves `complaint_open_count` and the requester's
    `open_complaint_count` numerically unchanged".

    Design: Corner/state_machines/complaint_open_to_triaged_valid_transition_refreshes_counters
    """
    corridor = create_corridor(jurisdiction_class="ARTERIAL", annual_volume_change_pct=20.0)
    requester = create_requester(display_name="Ada Citizen", email="ada@example.org")
    filed = file_complaint(requester["id"], corridor["id"], category="COORDINATION",
                          narrative="Waiting three cycles at 2nd Ave every morning.")
    assert filed["status"] == "OPEN"

    triaged = triage_complaint(filed["id"], "TRIAGE",
                              note="Corridor is on the retiming shortlist.")
    assert triaged["status"] == "TRIAGED"
    assert triaged["version"] == filed["version"] + 1
    assert triaged["linked_project_id"] is None
    assert triaged["reopen_count"] == 0

    corridor_after = read_corridor(corridor["id"])
    assert corridor_after["complaint_total_count"] == 1
    assert corridor_after["complaint_open_count"] == 1
    assert corridor_after["complaint_linked_count"] == 0
    assert corridor_after["complaint_terminal_count"] == 0
    assert read_requester(requester["id"])["open_complaint_count"] == 1


def test_completing_the_tuning_phase_waits_for_the_last_open_observation():
    """The status gate is satisfied and the resolution gate alone refuses the COMPLETE.

    PRD §3.10: "Completing the tuning phase — the `COMPLETE` action — requires the
    project to be in `FIELD_TUNING`, otherwise `ERR_PROJECT_NOT_IN_FIELD_TUNING`,
    and requires every field observation of the project to have been resolved one
    way or the other; a project still holding an `OPEN` observation is refused with
    `ERR_OBSERVATIONS_UNRESOLVED`. Completion moves the project `FIELD_TUNING →
    EVALUATION`, stamps `last_tuning_completed_at` with the logical clock's current
    value, and increments the project's `version`." PRD §3.10: "Each observation is
    closed out by marking its `resolution_status` as `ADDRESSED` or `DISMISSED`".

    Design: Corner/state_machines/field_tuning_complete_rejected_while_an_observation_is_open
    """
    ctx = setup_field_tuning_project(**CANONICAL)
    project_id = ctx["project"]["id"]
    assert ctx["project"]["status"] == "FIELD_TUNING"

    observation = log_observation(project_id, ctx["intersections"][0]["id"],
                                 finding_code="EARLY_RETURN_TO_GREEN",
                                 requires_adjustment=False)
    assert observation["resolution_status"] == "OPEN"

    validate_error(
        api_client.project_field_tuning(project_id, {"action": "COMPLETE"}, ADMIN),
        ApiErrorId.ERR_OBSERVATIONS_UNRESOLVED.value,
        409,
    )
    refused = read_project(project_id)
    assert refused["status"] == "FIELD_TUNING"
    assert refused["last_tuning_completed_at"] is None

    assert resolve_observation(observation["id"], "ADDRESSED")["resolution_status"] == "ADDRESSED"

    completed = field_tuning(project_id, "COMPLETE")
    assert completed["status"] == "EVALUATION"
    assert_instant_equals(completed["last_tuning_completed_at"], CLOCK_START,
                          "last_tuning_completed_at")
    assert completed["version"] == refused["version"] + 1


def _two_approved_configs():
    """An intersection on a deployed 105-second plan with EVP rank 1 and TSP rank 2 approved."""
    ctx = setup_canonical_implemented_project()
    intersection_id = ctx["intersections"][0]["id"]
    evp = propose_config(intersection_id, **EVP_CONFIG)
    tsp = propose_config(intersection_id, **TSP_CONFIG)
    ctx["evp"] = approve_config(evp["id"], note="EVP first")
    ctx["tsp"] = approve_config(tsp["id"], note="TSP second")
    ctx["intersection_id"] = intersection_id
    return ctx


def test_deploying_two_configs_walks_the_waterfall_and_rewrites_the_ledger_each_time():
    """EVP takes 15 of 21 and TSP is left the remaining 6 of its requested 10.

    PRD §3.9: "That budget is then handed out by a **waterfall** over the
    intersection's configurations whose `deployment_status` is `DEPLOYED`, in a
    strictly pinned order: all `EVP` configurations first, then all `TSP`
    configurations; within one priority type by `conflict_resolution_rank`
    ascending ... each configuration's `granted_extension_sec` is the smaller of its
    own `requested_max_extension_sec` and whatever remains of the budget, and the
    remainder shrinks by the amount granted, so an early emergency treatment can
    legitimately starve a later transit one." PRD §2.11: "every touched row has its
    `updated_at` refreshed and its `version` incremented by 1 — including rows the
    caller never named."

    Design: Corner/state_machines/priority_config_deploy_applies_every_declared_side_effect
    """
    ctx = _two_approved_configs()
    intersection_id = ctx["intersection_id"]
    before = read_intersection(intersection_id)
    assert before["deployed_coordinated_cycle_sec"] == 105
    assert before["priority_budget_sec"] == 21
    assert before["operational_posture"] == "READY"

    evp_deployed = deploy_config(ctx["evp"]["id"])
    assert evp_deployed["deployment_status"] == "DEPLOYED"
    assert evp_deployed["granted_extension_sec"] == 15

    mid = read_intersection(intersection_id)
    assert mid["granted_priority_extension_total_sec"] == 15
    assert mid["unallocated_priority_budget_sec"] == 6
    assert mid["version"] == before["version"] + 1

    tsp_deployed = deploy_config(ctx["tsp"]["id"])
    assert tsp_deployed["deployment_status"] == "DEPLOYED"
    # The waterfall serves EVP before TSP, so TSP gets 6 rather than its full 10.
    assert tsp_deployed["granted_extension_sec"] == 6

    after = read_intersection(intersection_id)
    assert after["priority_budget_sec"] == 21
    assert after["granted_priority_extension_total_sec"] == 21
    assert after["unallocated_priority_budget_sec"] == 0
    assert after["version"] == mid["version"] + 1
    assert_priority_budget_invariant(after)

    assert len(_deployed_configs(intersection_id)) == 2


def test_suspending_the_emergency_config_tops_the_starved_transit_config_back_up():
    """The survivor is re-allocated from scratch to its full 10, not left at its squeezed 6.

    PRD §3.9: "**Suspension** is deployment's compensation. It requires the
    deployment axis to be at `DEPLOYED` ... The configuration moves to `SUSPENDED`
    and its `granted_extension_sec` is zeroed; the waterfall is then re-run over the
    intersection's remaining deployed configurations, which is what returns the
    released seconds to whoever was starved before; the three intersection budget
    fields are recomputed". PRD §3.9: "The intersection's
    `granted_priority_extension_total_sec` is the sum of the granted extensions, and
    its `unallocated_priority_budget_sec` is the budget minus that sum."

    Design: Corner/state_machines/priority_config_suspend_compensates_the_whole_allocation
    """
    ctx = _two_approved_configs()
    intersection_id = ctx["intersection_id"]
    deploy_config(ctx["evp"]["id"])
    deploy_config(ctx["tsp"]["id"])

    pre = _deployed_configs(intersection_id)
    assert [(row["priority_type"], row["granted_extension_sec"]) for row in pre] == [
        ("EVP", 15), ("TSP", 6)
    ]

    suspended = suspend_config(ctx["evp"]["id"],
                              reason="Fire station relocated; EVP treatment paused.")
    assert suspended["deployment_status"] == "SUSPENDED"
    assert suspended["granted_extension_sec"] == 0
    # The compensation touches the deployment axis only.
    assert suspended["approval_status"] == "APPROVED"

    post = _deployed_configs(intersection_id)
    assert len(post) == 1
    assert post[0]["priority_type"] == "TSP"
    assert post[0]["granted_extension_sec"] == 10

    intersection = read_intersection(intersection_id)
    assert intersection["priority_budget_sec"] == 21
    assert intersection["granted_priority_extension_total_sec"] == 10
    assert intersection["unallocated_priority_budget_sec"] == 11
    assert_priority_budget_invariant(intersection)


def test_submit_from_draft_and_certify_or_return_from_coordinated_are_all_refused():
    """Each illegal trigger reports its own source-state code and executes nothing.

    PRD §3.8: "The plan must be in `COORDINATED`, and from any other status the
    submission is refused with `ERR_PLAN_NOT_COORDINATED`." PRD §3.8: "The reviewing
    `CertifyingEngineer` must not be the plan's author, must find the plan in
    `SUBMITTED` — otherwise `ERR_PLAN_NOT_SUBMITTED`". PRD §3.8: "The reviewer must
    supply a `reason`, and the plan must be in `SUBMITTED` — otherwise
    `ERR_PLAN_NOT_SUBMITTED`." PRD §3.8 also pins what a certification would have
    written: "writes the acting `X-User-ID` into `certified_by_user_id`", and a
    return "`return_count` is incremented by 1".

    Design: Corner/state_machines/plan_submit_from_draft_and_certify_from_coordinated_are_rejected
    """
    ctx = setup_draft_plan(**CANONICAL)
    plan_id = ctx["plan"]["id"]
    assert ctx["plan"]["status"] == "DRAFT"

    validate_error(
        api_client.submit_timing_plan(plan_id, ENGINEER),
        ApiErrorId.ERR_PLAN_NOT_COORDINATED.value,
        409,
    )

    coordinate_project(ctx["project"]["id"])
    coordinated = read_plan(plan_id)
    assert coordinated["status"] == "COORDINATED"

    # Certify and return share SUBMITTED as their only source state.
    validate_error(
        api_client.certify_timing_plan(plan_id, INDEPENDENT_REVIEWER),
        ApiErrorId.ERR_PLAN_NOT_SUBMITTED.value,
        409,
    )
    validate_error(
        api_client.return_timing_plan(plan_id, {"reason": "Not ready"}, INDEPENDENT_REVIEWER),
        ApiErrorId.ERR_PLAN_NOT_SUBMITTED.value,
        409,
    )

    final = read_plan(plan_id)
    assert final["status"] == "COORDINATED"
    assert final["version"] == coordinated["version"]
    assert final["return_count"] == 0
    assert final["certified_by_user_id"] is None


def test_every_machine_reports_its_declared_initial_state_on_creation():
    """Four machines and one two-axis machine all start where the contract says.

    PRD §3.2: "A new corridor starts at `selection_status` `UNSCREENED` with
    `member_count` 0, every complaint counter 0, `priority_score` 0,
    `priority_score_variant` null and `screened_at` null." PRD §3.4: "A new project
    starts in `DATA_COLLECTION` with `tuning_round` 0 and
    `last_tuning_completed_at` null". PRD §3.5: "A new plan starts in `DRAFT` on the
    workflow axis and `PENDING` on the pedestrian-compliance axis, with `offset_sec`
    0, `return_count` 0, `certified_by_user_id` null, and both split totals at 0."
    PRD §3.3: "sets `status` to `OPEN`, leaves `linked_project_id` null and
    `reopen_count` at 0". PRD §3.9: "A new configuration starts with
    `approval_status` `PROPOSED`, `deployment_status` `NOT_DEPLOYED` and
    `granted_extension_sec` 0".

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    fresh_corridor = create_corridor(name="Second St 4th-9th", jurisdiction_class="COLLECTOR")
    assert fresh_corridor["selection_status"] == "UNSCREENED"
    assert fresh_corridor["priority_score_variant"] is None
    assert fresh_corridor["screened_at"] is None

    ctx = setup_selected_corridor()
    project = open_project(ctx["corridor"]["id"])
    assert project["status"] == "DATA_COLLECTION"
    assert project["tuning_round"] == 0
    assert project["last_tuning_completed_at"] is None

    ctx["project"] = project
    complete_before_study(ctx)
    ctx["project"] = advance_project(project["id"])

    plan = draft_plan(project["id"], ctx["intersections"][0]["id"],
                     tod_period="PM_PEAK", tod_start_min=900, tod_end_min=1140)
    assert plan["status"] == "DRAFT"
    assert plan["ped_compliance_state"] == "PENDING"
    assert plan["offset_sec"] == 0
    assert plan["return_count"] == 0

    requester = create_requester(display_name="Ada Citizen", email="ada@example.org")
    complaint = file_complaint(requester["id"], ctx["corridor"]["id"], category="PEDESTRIAN",
                              narrative="Walk signal is too short at 1st Ave.")
    assert complaint["status"] == "OPEN"
    assert complaint["reopen_count"] == 0
    assert complaint["linked_project_id"] is None

    config = propose_config(ctx["intersections"][0]["id"], priority_type="TSP",
                           requested_max_extension_sec=8, conflict_resolution_rank=3)
    # The two axes start independently of one another.
    assert config["approval_status"] == "PROPOSED"
    assert config["deployment_status"] == "NOT_DEPLOYED"
    assert config["granted_extension_sec"] == 0
    assert config["approved_by_user_id"] is None


def test_an_abandoned_project_and_a_no_action_complaint_refuse_every_further_write():
    """Both terminal states are dead ends, each answering on its own code.

    PRD §3.10: "Any other status — including `IMPLEMENTED`, `FIELD_TUNING`,
    `EVALUATION` and the two terminal statuses themselves — is refused with
    `ERR_PROJECT_TERMINAL`, which is also the code returned for any attempted write
    against a project already `CLOSED` or `ABANDONED`." PRD §3.3: "Either
    disposition requires the complaint to be in `OPEN`; from anywhere else the
    request is refused with `ERR_COMPLAINT_INVALID_STATE`, and that same code covers
    every mis-stated complaint action — linking from outside `TRIAGED`, resolving
    from outside `LINKED`, reopening from outside `RESOLVED`." PRD §3.3:
    "supplying `NO_ACTION` moves it `OPEN → CLOSED_NO_ACTION`, which is the
    complaint machine's only terminal state."

    Design: Corner/state_machines/closed_project_and_no_action_complaint_reject_all_further_writes
    """
    ctx = setup_selected_corridor()
    corridor_id = ctx["corridor"]["id"]
    abandoned = close_project(
        open_project(corridor_id)["id"], "ABANDONED",
        note="Corridor deferred to next fiscal year.",
    )
    assert abandoned["status"] == "ABANDONED"
    project_id = abandoned["id"]

    requester = create_requester(display_name="Ada Citizen", email="ada@example.org")
    filed = file_complaint(requester["id"], corridor_id, category="DETECTION",
                          narrative="Loop detector seems dead on the side street.")
    closed = triage_complaint(filed["id"], "NO_ACTION",
                             note="Referred to maintenance, not a timing issue.")
    assert closed["status"] == "CLOSED_NO_ACTION"

    validate_error(api_client.advance_project(project_id, ENGINEER),
                   ApiErrorId.ERR_PROJECT_TERMINAL.value, 409)
    # Even a replay of the transition that produced the terminal state is refused.
    validate_error(api_client.close_project(project_id, {"disposition": "ABANDONED"}, ADMIN),
                   ApiErrorId.ERR_PROJECT_TERMINAL.value, 409)
    validate_error(
        api_client.project_field_tuning(project_id, {"action": "START"}, ADMIN),
        ApiErrorId.ERR_PROJECT_TERMINAL.value, 409)

    # A second, live project so the complaint's own state is the only thing wrong.
    live = open_project(corridor_id)
    assert live["status"] == "DATA_COLLECTION"

    validate_error(
        api_client.triage_complaint(filed["id"], {"disposition": "TRIAGE"}, LIAISON),
        ApiErrorId.ERR_COMPLAINT_INVALID_STATE.value, 409)
    validate_error(
        api_client.link_complaint(filed["id"], {"project_id": live["id"]}, LIAISON),
        ApiErrorId.ERR_COMPLAINT_INVALID_STATE.value, 409)
    validate_error(
        api_client.reopen_complaint(filed["id"], LIAISON, {"reason": "Citizen called again"}),
        ApiErrorId.ERR_COMPLAINT_INVALID_STATE.value, 409)

    assert read_project(project_id)["status"] == "ABANDONED"
    still_closed = read_complaint(corridor_id, filed["id"])
    assert still_closed["status"] == "CLOSED_NO_ACTION"
    assert still_closed["version"] == closed["version"]


def test_replaying_the_same_triage_is_a_conflict_rather_than_a_no_op():
    """The identical body a second time is refused and double-counts nothing.

    PRD §3.3: "Either disposition requires the complaint to be in `OPEN`; from
    anywhere else the request is refused with `ERR_COMPLAINT_INVALID_STATE`", and
    "Both dispositions refresh the corridor's four bucket counters and the
    requester's `open_complaint_count`, and increment the complaint's `version`."
    PRD §3.2 pins the reverse listing used to re-read it: "the complaints filed
    against it filterable by `status` and `category`."

    Design: Corner/state_machines/second_triage_of_the_same_complaint_is_rejected
    """
    corridor = create_corridor(jurisdiction_class="ARTERIAL", annual_volume_change_pct=20.0)
    requester = create_requester(display_name="Ada Citizen", email="ada@example.org")
    filed = file_complaint(requester["id"], corridor["id"], category="TIMING_OTHER",
                          narrative="Green is far too short northbound.")
    body = {"disposition": "TRIAGE", "note": "Queued for the corridor study."}
    triaged = triage_complaint(filed["id"], "TRIAGE", note=body["note"])
    assert triaged["status"] == "TRIAGED"
    assert triaged["version"] == 2

    validate_error(
        api_client.triage_complaint(filed["id"], body, LIAISON),
        ApiErrorId.ERR_COMPLAINT_INVALID_STATE.value,
        409,
    )

    rows = corridor_complaints(corridor["id"], status="TRIAGED")
    assert len(rows) == 1
    assert rows[0]["status"] == "TRIAGED"
    assert rows[0]["version"] == triaged["version"]
    assert read_requester(requester["id"])["open_complaint_count"] == 1


def test_the_screen_select_screen_loop_is_re_entrant_and_writes_on_every_lap():
    """Four laps flip the variant label each time and only the screens restamp the corridor.

    PRD §3.2: "a corridor arrives at `SCREENED` from `UNSCREENED` the first time,
    from `DEFERRED` in a later program cycle, and from `SELECTED` when a previous
    project has finished and the corridor is thrown back into the pool, so
    `UNSCREENED → SCREENED`, `DEFERRED → SCREENED` and `SELECTED → SCREENED` are all
    legal." PRD §3.2: "Then `avg_plan_age_days` and `priority_score` are recomputed
    under the screening variant, `priority_score_variant` is set to `SCREENING`,
    `screened_at` is stamped with the logical clock's current value, and the
    corridor's `version` is incremented." PRD §3.2: "Both decisions recompute
    `complaint_count_12mo`, `avg_plan_age_days` and `priority_score` under the
    **programming variant** before anything else is decided, set
    `priority_score_variant` to `PROGRAMMING`, and increment the corridor's
    `version`." PRD §3.2: "There is no terminal selection status — a corridor is
    perpetually re-screenable."

    Design: Corner/state_machines/corridor_screen_select_screen_loop_reruns_the_whole_recomputation
    """
    intersection = create_intersection(location_name="Main St @ 1st Ave")
    corridor = create_corridor(jurisdiction_class="ARTERIAL", annual_volume_change_pct=20.0)
    enrol_member(corridor["id"], intersection["id"], 1, distance_from_prev_ft=0)
    baseline_version = corridor["version"] + 1  # the enrolment itself is a write

    lap1 = screen_corridor(corridor["id"])
    assert (lap1["selection_status"], lap1["priority_score_variant"]) == ("SCREENED", "SCREENING")
    assert float(lap1["priority_score"]) == 91.25
    assert_instant_equals(lap1["screened_at"], CLOCK_START, "screened_at")
    assert lap1["version"] == baseline_version + 1

    lap2 = decide_corridor(corridor["id"], "SELECT", rationale="First programming pass")
    assert (lap2["selection_status"], lap2["priority_score_variant"]) == ("SELECTED", "PROGRAMMING")
    assert float(lap2["priority_score"]) == 91.25
    assert lap2["version"] == lap1["version"] + 1
    assert_instant_equals(lap2["screened_at"], CLOCK_START, "screened_at")

    set_clock("2026-08-02T00:00:00Z")

    lap3 = screen_corridor(corridor["id"])
    assert (lap3["selection_status"], lap3["priority_score_variant"]) == ("SCREENED", "SCREENING")
    assert float(lap3["priority_score"]) == 91.25
    # A transition INTO SCREENED restamps the corridor.
    assert_instant_equals(lap3["screened_at"], "2026-08-02T00:00:00Z", "screened_at")
    assert lap3["version"] == lap2["version"] + 1

    lap4 = decide_corridor(corridor["id"], "DEFER", rationale="Push to next cycle after all")
    assert (lap4["selection_status"], lap4["priority_score_variant"]) == ("DEFERRED", "PROGRAMMING")
    assert lap4["version"] == lap3["version"] + 1
    # A selection decision does not restamp it.
    assert_instant_equals(lap4["screened_at"], "2026-08-02T00:00:00Z", "screened_at")


def _relaunch(project_id, plan_id):
    """Take a reopened DRAFT plan back through coordination, review and implementation."""
    coordinate_project(project_id)
    submit_plan(plan_id)
    certify_plan(plan_id)
    implement_project(project_id)
    return field_tuning(project_id, "START")


def test_the_tuning_loop_stops_dead_at_the_third_completed_round():
    """The fourth adjustment is refused outright and no observation row is written.

    PRD §3.10: "The tuning loop is bounded. `tuning_round` counts completed loops
    back into plan development, and the loop may run at most three times: if
    incrementing `tuning_round` would carry it past 3, the entire observation
    request is refused with `ERR_TUNING_ROUND_LIMIT` and **no field observation row
    is created at all** — the reopen, the project transition and the invalidation
    are all abandoned along with it. A project that has exhausted its rounds must be
    finished on the timing it has." PRD §3.10: "Because that plan left `DEPLOYED`,
    the project itself moves `FIELD_TUNING → PLAN_DEVELOPMENT` with `tuning_round`
    incremented by 1".

    Design: Corner/state_machines/tuning_loop_terminates_at_the_third_round
    """
    ctx = setup_field_tuning_project(**CANONICAL)
    project_id = ctx["project"]["id"]
    intersection_id = ctx["intersections"][0]["id"]
    plan_id = ctx["plan"]["id"]

    for lap, finding in enumerate(
        ("PROGRESSION_BREAK", "QUEUE_SPILLBACK", "EARLY_RETURN_TO_GREEN"), start=1
    ):
        log_observation(project_id, intersection_id, finding_code=finding,
                        requires_adjustment=True)
        reopened = read_project(project_id)
        assert reopened["status"] == "PLAN_DEVELOPMENT"
        assert reopened["tuning_round"] == lap
        assert _relaunch(project_id, plan_id)["status"] == "FIELD_TUNING"

    # The project legitimately re-entered tuning for a fourth attempt.
    assert read_project(project_id)["tuning_round"] == 3
    assert read_plan(plan_id)["status"] == "DEPLOYED"

    validate_error(
        api_client.create_field_observation(
            {
                "project_id": project_id,
                "intersection_id": intersection_id,
                "tod_period": "AM_PEAK",
                "observed_at": CLOCK_START,
                "finding_code": "PED_CALL_MISSED",
                "requires_adjustment": True,
            },
            TECHNICIAN,
        ),
        ApiErrorId.ERR_TUNING_ROUND_LIMIT.value,
        409,
    )

    observations = project_observations(project_id)
    assert len(observations) == 3
    assert observations[0]["finding_code"] == "PROGRESSION_BREAK"
    final = read_project(project_id)
    assert final["status"] == "FIELD_TUNING"
    assert final["tuning_round"] == 3
    # The refused observation did not reopen the plan.
    assert read_plan(plan_id)["status"] == "DEPLOYED"


def test_a_redraft_supersedes_a_draft_predecessor_but_a_coordinated_one_blocks_it():
    """The same triple twice is a silent supersede; the third time it is a conflict.

    PRD §3.5: "When a plan is created for a `project_id`, `intersection_id` and
    `tod_period` combination that already carries a plan still in `DRAFT`, that
    earlier draft transitions `DRAFT → SUPERSEDED` and has its own `version`
    incremented — the engineer's newest thinking replaces the old, and `SUPERSEDED`
    is the plan machine's terminal state. If, however, the same combination already
    carries a plan that has moved past drafting — one in `COORDINATED`, `SUBMITTED`,
    `CERTIFIED` or `DEPLOYED` — the create is refused with `ERR_DUPLICATE_TOD_PLAN`,
    because superseding work that has already been coordinated or blessed would
    silently discard a review." PRD §3.5: "`drafted_cycle_length_sec` snapshots the
    supplied `cycle_length_sec`".

    Design: Corner/state_machines/draft_plan_is_superseded_by_recreate_while_a_coordinated_plan_blocks_it
    """
    ctx = setup_project_in_plan_development()
    project_id = ctx["project"]["id"]
    intersection_id = ctx["intersections"][0]["id"]

    first = draft_plan(project_id, intersection_id, cycle_length_sec=90)
    assert first["status"] == "DRAFT"

    second = draft_plan(project_id, intersection_id, cycle_length_sec=100)
    assert second["status"] == "DRAFT"
    assert second["drafted_cycle_length_sec"] == 100

    superseded = project_plans(project_id, status="SUPERSEDED")
    assert len(superseded) == 1
    assert superseded[0]["id"] == first["id"]
    assert superseded[0]["status"] == "SUPERSEDED"
    # Moved, not deleted, and bumped exactly once.
    assert superseded[0]["version"] == 2

    add_splits(second["id"], CANONICAL_SPLITS)
    coordinate_project(project_id)
    assert read_plan(second["id"])["status"] == "COORDINATED"
    version_after_coordination = project_version(project_id)

    validate_error(
        api_client.create_timing_plan(
            {
                "project_id": project_id,
                "intersection_id": intersection_id,
                "tod_period": "AM_PEAK",
                "tod_start_min": 360,
                "tod_end_min": 540,
                "cycle_length_sec": 95,
                "coordination_ref": "MASTER",
                "expected_project_version": version_after_coordination,
            },
            ENGINEER,
        ),
        ApiErrorId.ERR_DUPLICATE_TOD_PLAN.value,
        409,
    )

    assert len(project_plans(project_id)) == 2
    # The refused create consumed no version, so the same guard still matches.
    assert project_version(project_id) == version_after_coordination
