"""Entity-specific 404 codes, phase gates, state gates and uniqueness refusals."""
from test_helpers import (
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_START
from test_helpers.fixtures import (
    ADMIN,
    AUTHOR,
    ENGINEER,
    LIAISON,
    REVIEWER,
    TECHNICIAN,
    add_split,
    advance_project,
    approve_config,
    certify_evaluation,
    complete_before_study,
    coordinate_project,
    create_corridor,
    create_evaluation,
    create_intersection,
    create_requester,
    deploy_config,
    field_tuning,
    log_observation,
    patch_intersection,
    project_version,
    propose_config,
    read_evaluation,
    read_intersection,
    read_plan,
    read_project,
    read_requester,
    record_run,
    resolve_observation,
    set_clock,
    setup_canonical_implemented_project,
    setup_draft_plan,
    setup_field_tuning_project,
    setup_project_in_data_collection,
    suspend_config,
)
from test_helpers.factories import (
    complaint_payload,
    corridor_member_payload,
    field_observation_payload,
    phase_split_payload,
    priority_config_payload,
)

# A syntactically valid UUID that names no row in any table.
UNKNOWN_ID = "11111111-1111-4111-8111-111111111111"

# One logical hour past the startup instant of the clock.
CLOCK_PLUS_ONE_HOUR = "2026-08-01T01:00:00Z"

# A single non-pedestrian phase drafted at 20 s, so the plan can be coordinated
# with a second 20 s phase and land on effective splits of 53 and 52.
SPLIT_PHASE_1 = {
    "phase_number": 1,
    "split_sec": 20,
    "min_green_sec": 10,
    "yellow_sec": 3.0,
    "red_clearance_sec": 1.0,
}


def test_the_same_unknown_uuid_answers_with_a_different_code_at_every_endpoint():
    """One fabricated identifier, offered to ten path segments and four request bodies.

    PRD §2.6: "Identifiers embedded in a path are resolved strictly **left to
    right**, and the first identifier that resolves to nothing decides the
    response ... All eleven are HTTP 404."

    PRD §2.6: "Foreign keys arriving in a **request body** are resolved after
    every path identifier has been resolved, and they raise the same 404 codes".

    PRD §2.7: "7. Body foreign keys resolve — the 404 codes for corridor,
    intersection, project and requester."

    The body-borne cases each carry exactly one unresolvable foreign key, so the
    code that comes back names that field and not the path parent that resolved
    perfectly well.

    Design: Corner/errors/every_not_found_code_is_reachable_for_its_own_entity_type
    """
    intersection = create_intersection()
    corridor = create_corridor()
    requester = create_requester()

    # Ten path segments, one unknown identifier, ten different entity codes.
    detail = validate_error(
        api_client.get_intersection(UNKNOWN_ID, ADMIN),
        ApiErrorId.ERR_INTERSECTION_NOT_FOUND,
        404,
    )
    assert len(detail["message"].strip()) > 0, "the 404 envelope carries a human-readable message"

    validate_error(
        api_client.get_retiming_project(UNKNOWN_ID, ENGINEER),
        ApiErrorId.ERR_PROJECT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_timing_plan(UNKNOWN_ID, ENGINEER),
        ApiErrorId.ERR_TIMING_PLAN_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_requester(UNKNOWN_ID, LIAISON),
        ApiErrorId.ERR_REQUESTER_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.triage_complaint(
            UNKNOWN_ID, {"disposition": "TRIAGE", "note": "No such complaint."}, LIAISON
        ),
        ApiErrorId.ERR_COMPLAINT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.update_phase_split(UNKNOWN_ID, {"split_sec": 25}, ENGINEER),
        ApiErrorId.ERR_PHASE_SPLIT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.waive_pedestrian_check(
            UNKNOWN_ID, {"waiver_justification": "No such check."}, REVIEWER
        ),
        ApiErrorId.ERR_PED_CHECK_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.approve_priority_config(UNKNOWN_ID, {"decision": "APPROVE"}, REVIEWER),
        ApiErrorId.ERR_PRIORITY_CONFIG_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.update_field_observation(
            UNKNOWN_ID, {"resolution_status": "ADDRESSED"}, TECHNICIAN
        ),
        ApiErrorId.ERR_OBSERVATION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.certify_performance_evaluation(UNKNOWN_ID, REVIEWER),
        ApiErrorId.ERR_EVALUATION_NOT_FOUND,
        404,
    )

    # Four request bodies; in each, the path resolved and exactly one FK did not.
    validate_error(
        api_client.create_corridor_member(
            corridor["id"], corridor_member_payload(UNKNOWN_ID, 1), ADMIN
        ),
        ApiErrorId.ERR_INTERSECTION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_complaint(
            complaint_payload(UNKNOWN_ID, corridor["id"], narrative="Unknown requester."),
            LIAISON,
        ),
        ApiErrorId.ERR_REQUESTER_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_complaint(
            complaint_payload(requester["id"], UNKNOWN_ID, narrative="Unknown corridor."),
            LIAISON,
        ),
        ApiErrorId.ERR_CORRIDOR_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_field_observation(
            field_observation_payload(UNKNOWN_ID, intersection["id"]), TECHNICIAN
        ),
        ApiErrorId.ERR_PROJECT_NOT_FOUND,
        404,
    )

    # Not one of the fourteen refusals wrote a row.
    members, meta = validate_paginated(api_client.list_corridor_members(corridor["id"], ADMIN))
    assert members == []
    assert meta["total_count"] == 0
    assert read_requester(requester["id"])["version"] == 1


def test_every_out_of_phase_action_names_the_phase_it_needs_not_the_one_it_found():
    """Six refusals against one DATA_COLLECTION project, then the advance itself goes stale.

    PRD §3.6: "The project must be in `PLAN_DEVELOPMENT`, and is otherwise
    refused with `ERR_PROJECT_NOT_IN_PLAN_DEVELOPMENT`."

    PRD §3.8: "The project's `TimingEngineer` may implement only from
    `PLAN_DEVELOPMENT` — otherwise `ERR_PROJECT_NOT_IN_PLAN_DEVELOPMENT`".

    PRD §3.10: "which moves the project `IMPLEMENTED → FIELD_TUNING`; from any
    other status the request is refused with `ERR_PROJECT_NOT_IMPLEMENTED`".

    PRD §3.10: "Creation is deliberately permitted while the project is in either
    `FIELD_TUNING` or `EVALUATION` ... any other project status is refused with
    `ERR_PROJECT_NOT_IN_EVALUATION`."

    PRD §3.10: "Observations may only be logged while the project is in
    `FIELD_TUNING`, and are otherwise refused with
    `ERR_PROJECT_NOT_IN_FIELD_TUNING`."

    PRD §3.10: "A `disposition` of `CLOSED` requires the project to be in
    `EVALUATION`, otherwise `ERR_PROJECT_NOT_IN_EVALUATION`".

    PRD §3.4: "**Advancing** the project out of data collection moves it
    `DATA_COLLECTION → PLAN_DEVELOPMENT` and is refused with
    `ERR_PROJECT_NOT_IN_DATA_COLLECTION` from any other status."

    PRD §2.7: "Because the state check (rung 10) precedes the concurrency check
    (rung 11), a request that is both aimed at a wrongly-stated resource and
    carrying a stale parent version reports the state error, not the
    stale-version error." The evaluation create below therefore reports the phase
    gate even though its `expected_project_version` is perfectly current.

    Design: Corner/errors/project_phase_gates_reject_every_out_of_phase_action
    """
    ctx = setup_project_in_data_collection()
    complete_before_study(ctx)
    project_id = ctx["project"]["id"]
    intersection_id = ctx["intersections"][0]["id"]

    opened = read_project(project_id)
    assert opened["status"] == "DATA_COLLECTION"
    assert opened["version"] == 1, "counts and runs are append-only and never touch the project"

    validate_error(
        api_client.coordinate_project(project_id, ENGINEER),
        ApiErrorId.ERR_PROJECT_NOT_IN_PLAN_DEVELOPMENT,
        409,
    )
    # The phase gate answers before the plan-coverage gate is ever consulted.
    validate_error(
        api_client.implement_project(project_id, ENGINEER),
        ApiErrorId.ERR_PROJECT_NOT_IN_PLAN_DEVELOPMENT,
        409,
    )
    validate_error(
        api_client.project_field_tuning(project_id, {"action": "START"}, ADMIN),
        ApiErrorId.ERR_PROJECT_NOT_IMPLEMENTED,
        409,
    )
    validate_error(
        api_client.create_performance_evaluation(
            project_id, {"expected_project_version": opened["version"]}, REVIEWER
        ),
        ApiErrorId.ERR_PROJECT_NOT_IN_EVALUATION,
        409,
    )
    validate_error(
        api_client.create_field_observation(
            field_observation_payload(project_id, intersection_id), TECHNICIAN
        ),
        ApiErrorId.ERR_PROJECT_NOT_IN_FIELD_TUNING,
        409,
    )
    validate_error(
        api_client.close_project(project_id, {"disposition": "CLOSED"}, ADMIN),
        ApiErrorId.ERR_PROJECT_NOT_IN_EVALUATION,
        409,
    )

    advanced = advance_project(project_id)
    assert advanced["status"] == "PLAN_DEVELOPMENT"
    assert advanced["version"] == 2, "exactly one of the seven calls mutated the project"

    validate_error(
        api_client.advance_project(project_id, ENGINEER),
        ApiErrorId.ERR_PROJECT_NOT_IN_DATA_COLLECTION,
        409,
    )
    final = read_project(project_id)
    assert final["status"] == "PLAN_DEVELOPMENT"
    assert final["version"] == 2


def test_the_same_split_patch_is_accepted_while_draft_and_refused_once_coordinated():
    """Three write paths onto one plan, each guarding a different status.

    PRD §3.5: "A phase split belongs to exactly one plan, carries that plan's
    `timing_plan_id`, and may only be added while the plan is still in `DRAFT`;
    adding one to a plan that has moved on is refused with `ERR_PLAN_NOT_DRAFT`."

    PRD §3.5: "a NEMA phase number between 1 and 8 that must be unique within
    the plan — a repeat is refused with `ERR_DUPLICATE_PHASE_NUMBER`".

    PRD §3.5: "The adjustment is likewise only available while the parent plan is
    in `DRAFT`, and is refused with `ERR_PLAN_NOT_DRAFT` otherwise. Every
    accepted adjustment re-mirrors `effective_split_sec` onto the new
    `split_sec`".

    PRD §3.8: "The plan must be in `COORDINATED`, and from any other status the
    submission is refused with `ERR_PLAN_NOT_COORDINATED`."

    PRD §3.6: "a residual is computed as the operating cycle length minus the sum
    of the rounded effective splits ... That single residual is added to exactly
    one phase: the phase with the greatest `min_green_sec`".

    Design: Corner/errors/plan_state_gates_and_the_duplicate_phase_number_guard
    """
    ctx = setup_draft_plan(plan_overrides={"cycle_length_sec": 90}, splits=[dict(SPLIT_PHASE_1)])
    plan_id = ctx["plan"]["id"]
    project_id = ctx["project"]["id"]
    split_id = ctx["splits"][0]["id"]
    assert ctx["plan"]["status"] == "DRAFT"

    validate_error(
        api_client.create_phase_split(
            plan_id,
            phase_split_payload(
                plan_id, 1, split_sec=24, min_green_sec=10, yellow_sec=3.0, red_clearance_sec=1.0
            ),
            AUTHOR,
        ),
        ApiErrorId.ERR_DUPLICATE_PHASE_NUMBER,
        409,
    )

    # The very same PATCH, twice: legal here, refused after the pipeline runs.
    patched = validate_success(
        api_client.update_phase_split(split_id, {"split_sec": 20, "min_green_sec": 10}, AUTHOR)
    )
    assert patched["split_sec"] == 20
    assert patched["effective_split_sec"] == 20

    second = add_split(
        plan_id, 2, split_sec=20, min_green_sec=12, yellow_sec=3.0, red_clearance_sec=1.0
    )
    assert second["phase_number"] == 2

    validate_error(
        api_client.submit_timing_plan(plan_id, ENGINEER),
        ApiErrorId.ERR_PLAN_NOT_COORDINATED,
        409,
    )

    coordinate_project(project_id)
    coordinated = read_plan(plan_id)
    assert coordinated["status"] == "COORDINATED"
    assert coordinated["cycle_length_sec"] == 105

    validate_error(
        api_client.update_phase_split(split_id, {"split_sec": 25}, AUTHOR),
        ApiErrorId.ERR_PLAN_NOT_DRAFT,
        409,
    )

    rows, meta = validate_paginated(api_client.list_phase_splits(plan_id, ADMIN))
    assert meta["total_count"] == 2
    assert [row["phase_number"] for row in rows] == [1, 2]
    assert rows[0]["split_sec"] == 20, "the refused PATCH wrote nothing"
    # 20 of a drafted 40 at a 105 s cycle rounds to 53 each; the residual of -1
    # lands on phase 2, which holds the greater min_green_sec.
    assert rows[0]["effective_split_sec"] == 53
    assert rows[1]["effective_split_sec"] == 52
    assert coordinated["effective_split_total_sec"] == 105


def test_a_requester_email_differing_only_in_capitalisation_is_a_duplicate():
    """Uniqueness on the email folds case, and a refused registration writes nothing.

    PRD §3.3: "an `email` that must contain an `@` character and must be unique
    across all requesters; a second registration using an email another requester
    already holds, compared without regard to letter case, is refused with
    `ERR_DUPLICATE_REQUESTER_EMAIL`."

    PRD §3.3: "A new requester's `open_complaint_count` starts at 0".

    PRD §2.4: "an integer that starts at 1 when the row is created and increases
    by exactly 1 on every mutation".

    Design: Corner/errors/duplicate_requester_email_is_matched_case_insensitively
    """
    first = create_requester(
        display_name="Ada Citizen", email="ada@example.org", contact_pref="EMAIL"
    )
    assert first["email"] == "ada@example.org"
    assert first["open_complaint_count"] == 0
    assert first["version"] == 1

    validate_error(
        api_client.create_requester(
            {"display_name": "Ada C.", "email": "ADA@Example.ORG", "contact_pref": "PHONE"},
            LIAISON,
        ),
        ApiErrorId.ERR_DUPLICATE_REQUESTER_EMAIL,
        409,
    )
    validate_error(
        api_client.create_requester(
            {"display_name": "Ada C.", "email": "ada@example.org", "contact_pref": "PHONE"},
            LIAISON,
        ),
        ApiErrorId.ERR_DUPLICATE_REQUESTER_EMAIL,
        409,
    )

    # A genuinely different local part is not a duplicate.
    second = create_requester(display_name="Bob Citizen", email="ada.citizen@example.org")
    assert second["id"] != first["id"]
    assert second["open_complaint_count"] == 0

    unchanged = read_requester(first["id"])
    assert unchanged["email"] == "ada@example.org"
    assert unchanged["display_name"] == "Ada Citizen"
    assert unchanged["version"] == 1


def test_the_two_priority_axes_the_rank_scope_and_the_budget_refuse_independently():
    """Approval and deployment are separate axes, and the budget is read at deploy time.

    PRD §3.9: "The configuration must be in `PROPOSED` on the approval axis;
    anything else is refused with `ERR_CONFIG_NOT_PROPOSED`."

    PRD §3.9: "The configuration must be `APPROVED` on the approval axis,
    otherwise `ERR_CONFIG_NOT_APPROVED`. Its deployment axis must be at
    `NOT_DEPLOYED` or `SUSPENDED`, otherwise `ERR_CONFIG_NOT_DEPLOYED` ... The
    intersection's posture must be exactly `READY`; both `RESTRICTED` and
    `BLOCKED` are refused with `ERR_POSTURE_BLOCKS_DEPLOYMENT`".

    PRD §3.9: "a rank already held at the same `intersection_id` for the same
    `priority_type` by a configuration whose `deployment_status` is anything other
    than `SUSPENDED` is refused with `ERR_DUPLICATE_PRIORITY_RANK`".

    PRD §3.9: "An intersection's `priority_budget_sec` is one fifth — 20 percent —
    of its `deployed_coordinated_cycle_sec`, taken as a floor".

    PRD §3.9: "When the intersection's `unallocated_priority_budget_sec` is
    already 0 at the moment of the deploy, the waterfall can give the newly
    deployed configuration nothing at all, so the request is refused with
    `ERR_PRIORITY_BUDGET_EXHAUSTED`".

    PRD §3.9: "It requires the deployment axis to be at `DEPLOYED`, otherwise
    `ERR_CONFIG_NOT_DEPLOYED` ... The configuration moves to `SUSPENDED` and its
    `granted_extension_sec` is zeroed".

    Design: Corner/errors/priority_config_gates_rank_reuse_budget_exhaustion_and_posture
    """
    ctx = setup_canonical_implemented_project()
    intersection_id = ctx["intersections"][0]["id"]
    implemented = read_intersection(intersection_id)
    assert implemented["deployed_coordinated_cycle_sec"] == 105
    assert implemented["priority_budget_sec"] == 21
    assert implemented["unallocated_priority_budget_sec"] == 21

    evp = propose_config(
        intersection_id,
        priority_type="EVP",
        requested_max_extension_sec=25,
        conflict_resolution_rank=1,
    )
    assert evp["approval_status"] == "PROPOSED"
    assert evp["deployment_status"] == "NOT_DEPLOYED"
    assert evp["granted_extension_sec"] == 0

    # The two axes refuse independently, each naming its own axis.
    validate_error(
        api_client.deploy_priority_config(evp["id"], ADMIN),
        ApiErrorId.ERR_CONFIG_NOT_APPROVED,
        409,
    )
    validate_error(
        api_client.suspend_priority_config(
            evp["id"], ADMIN, {"reason": "Nothing to suspend yet."}
        ),
        ApiErrorId.ERR_CONFIG_NOT_DEPLOYED,
        409,
    )

    assert approve_config(evp["id"])["approval_status"] == "APPROVED"
    validate_error(
        api_client.approve_priority_config(evp["id"], {"decision": "APPROVE"}, REVIEWER),
        ApiErrorId.ERR_CONFIG_NOT_PROPOSED,
        409,
    )

    # Rank uniqueness is scoped per intersection and per priority type.
    current_version = read_intersection(intersection_id)["version"]
    validate_error(
        api_client.create_priority_config(
            priority_config_payload(
                intersection_id,
                current_version,
                priority_type="EVP",
                requested_max_extension_sec=5,
                conflict_resolution_rank=1,
            ),
            ENGINEER,
        ),
        ApiErrorId.ERR_DUPLICATE_PRIORITY_RANK,
        409,
    )
    tsp = propose_config(
        intersection_id,
        priority_type="TSP",
        requested_max_extension_sec=10,
        conflict_resolution_rank=1,
    )
    assert tsp["conflict_resolution_rank"] == 1
    assert approve_config(tsp["id"])["approval_status"] == "APPROVED"

    deployed = deploy_config(evp["id"])
    assert deployed["deployment_status"] == "DEPLOYED"
    assert deployed["granted_extension_sec"] == 21, "the smaller of the 25 asked for and the 21 left"

    # Approval reserved nothing; the waterfall has already spent the whole budget.
    validate_error(
        api_client.deploy_priority_config(tsp["id"], ADMIN),
        ApiErrorId.ERR_PRIORITY_BUDGET_EXHAUSTED,
        409,
    )

    blocked = patch_intersection(intersection_id, comm_status="OFFLINE")
    assert blocked["operational_posture"] == "BLOCKED"

    # Backing priority out is never posture-gated; putting it back is.
    suspended = suspend_config(evp["id"], reason="Comms down; back out the priority.")
    assert suspended["deployment_status"] == "SUSPENDED"
    assert suspended["granted_extension_sec"] == 0
    validate_error(
        api_client.deploy_priority_config(evp["id"], ADMIN),
        ApiErrorId.ERR_POSTURE_BLOCKS_DEPLOYMENT,
        409,
    )

    configs, meta = validate_paginated(
        api_client.list_intersection_priority_configs(intersection_id, ADMIN)
    )
    assert meta["total_count"] == 2, "the refused create wrote nothing"
    assert {row["priority_type"] for row in configs} == {"EVP", "TSP"}

    final = read_intersection(intersection_id)
    assert final["priority_budget_sec"] == 21
    assert final["granted_priority_extension_total_sec"] == 0
    assert final["unallocated_priority_budget_sec"] == 21


def test_the_after_study_gate_fires_once_for_emptiness_and_once_for_the_tuning_cutoff():
    """The tuning window is closed on both sides, and one run satisfies only the provisional read.

    PRD §3.10: "The `observed_at` instant must fall inside the tuning window: at
    or after the project's most recent entry into `FIELD_TUNING`, and at or before
    the logical clock's current value. An observation dated before tuning began,
    or dated in the future, is refused with `ERR_OBSERVATION_OUT_OF_WINDOW`."

    PRD §3.10: "the observation must still be `OPEN`, a second resolution being
    refused with `ERR_OBSERVATION_NOT_OPEN`".

    PRD §3.10: "if it has no included `AFTER` run the computation fails with
    `ERR_NO_AFTER_STUDY`."

    PRD §3.10: "Completion moves the project `FIELD_TUNING → EVALUATION`, stamps
    `last_tuning_completed_at` with the logical clock's current value".

    PRD §3.10: "And at least one `AFTER` run must have a `recorded_at` at or after
    `last_tuning_completed_at`; without one the certification is refused with
    `ERR_NO_AFTER_STUDY`."

    PRD §3.10: "Under the **provisional variant**, every run with `study_role`
    `AFTER` is included regardless of when it was recorded, and a mean is the
    plain arithmetic mean ... Under the **certified variant**, an `AFTER` run is
    included only when its `recorded_at` is at or after the project's
    `last_tuning_completed_at`".

    PRD §3.10: "The evaluation must be `PROVISIONAL`, otherwise
    `ERR_EVALUATION_NOT_PROVISIONAL`."

    PRD §3.4: "The server stamps `recorded_at` with the logical clock's current
    value; that stamp, not `started_at`, is what the certified performance variant
    later filters on."

    Design: Corner/errors/observation_and_evaluation_gates_across_the_tuning_boundary
    """
    ctx = setup_field_tuning_project()
    project_id = ctx["project"]["id"]
    intersection_id = ctx["intersections"][0]["id"]
    assert ctx["project"]["status"] == "FIELD_TUNING"
    assert ctx["project"]["tuning_round"] == 0

    # One second before the implementation moment, then one second after now.
    validate_error(
        api_client.create_field_observation(
            field_observation_payload(
                project_id, intersection_id, observed_at="2026-07-31T23:59:59Z"
            ),
            TECHNICIAN,
        ),
        ApiErrorId.ERR_OBSERVATION_OUT_OF_WINDOW,
        422,
    )
    validate_error(
        api_client.create_field_observation(
            field_observation_payload(
                project_id, intersection_id, observed_at="2026-08-01T00:00:01Z"
            ),
            TECHNICIAN,
        ),
        ApiErrorId.ERR_OBSERVATION_OUT_OF_WINDOW,
        422,
    )

    observation = log_observation(project_id, intersection_id, observed_at=CLOCK_START)
    assert observation["resolution_status"] == "OPEN"
    assert resolve_observation(observation["id"], "ADDRESSED")["resolution_status"] == "ADDRESSED"
    validate_error(
        api_client.update_field_observation(
            observation["id"], {"resolution_status": "DISMISSED"}, TECHNICIAN
        ),
        ApiErrorId.ERR_OBSERVATION_NOT_OPEN,
        409,
    )

    # First trigger of the after-study gate: the AFTER run set is empty.
    version_for_eval = project_version(project_id)
    validate_error(
        api_client.create_performance_evaluation(
            project_id, {"expected_project_version": version_for_eval}, REVIEWER
        ),
        ApiErrorId.ERR_NO_AFTER_STUDY,
        409,
    )

    first_run = record_run(
        project_id,
        study_role="AFTER",
        started_at=CLOCK_START,
        duration_sec=300,
        stops_count=3,
        arrivals_on_green_count=8,
        total_arrivals=12,
    )
    assert first_run["recorded_at"].startswith(CLOCK_START[:-1])

    provisional = create_evaluation(project_id, expected_project_version=version_for_eval)
    assert provisional["status"] == "PROVISIONAL"
    assert provisional["metric_variant"] == "PROVISIONAL_UNWEIGHTED"
    assert provisional["mean_travel_time_before_sec"] == 320.00
    assert provisional["mean_travel_time_after_sec"] == 300.00
    assert provisional["delay_reduction_pct"] == 6.25
    assert provisional["aog_pct_after"] == 66.67
    assert provisional["included_after_run_count"] == 1

    set_clock(CLOCK_PLUS_ONE_HOUR)
    completed = field_tuning(project_id, "COMPLETE")
    assert completed["status"] == "EVALUATION"
    assert completed["last_tuning_completed_at"].startswith(CLOCK_PLUS_ONE_HOUR[:-1])

    # Second trigger: the only AFTER run predates the cutoff the completion stamped,
    # even though the provisional variant was perfectly happy to use it.
    validate_error(
        api_client.certify_performance_evaluation(provisional["id"], REVIEWER),
        ApiErrorId.ERR_NO_AFTER_STUDY,
        409,
    )

    second_run = record_run(
        project_id,
        study_role="AFTER",
        started_at=CLOCK_PLUS_ONE_HOUR,
        duration_sec=280,
        stops_count=2,
        arrivals_on_green_count=9,
        total_arrivals=12,
    )
    assert second_run["recorded_at"].startswith(CLOCK_PLUS_ONE_HOUR[:-1])

    certified = certify_evaluation(provisional["id"])
    assert certified["status"] == "CERTIFIED"
    assert certified["metric_variant"] == "CERTIFIED_WEIGHTED"
    assert certified["included_after_run_count"] == 1
    assert certified["mean_travel_time_before_sec"] == 320.00
    assert certified["mean_travel_time_after_sec"] == 280.00
    assert certified["delay_reduction_pct"] == 12.50
    assert certified["stops_reduction_pct"] == 60.00
    assert certified["aog_pct_after"] == 75.00
    assert certified["certified_by_user_id"] == REVIEWER["X-User-ID"]

    validate_error(
        api_client.certify_performance_evaluation(provisional["id"], REVIEWER),
        ApiErrorId.ERR_EVALUATION_NOT_PROVISIONAL,
        409,
    )
    unchanged = read_evaluation(project_id, provisional["id"])
    assert unchanged["status"] == "CERTIFIED"
    assert unchanged["mean_travel_time_after_sec"] == 280.00
    assert unchanged["delay_reduction_pct"] == 12.50
