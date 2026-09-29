"""Optimistic concurrency on the two parent aggregates, and the three writes it guards."""
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
    REVIEWER,
    advance_project,
    complete_before_study,
    create_evaluation,
    create_intersection,
    draft_plan,
    field_tuning,
    intersection_version,
    patch_intersection,
    project_version,
    read_intersection,
    read_plan,
    record_run,
    setup_implemented_project,
    setup_project_in_data_collection,
)
from test_helpers.factories import (
    performance_evaluation_payload,
    priority_config_payload,
    timing_plan_payload,
)

# A syntactically valid UUID that names no row in any table.
UNKNOWN_ID = "11111111-1111-4111-8111-111111111111"

# Four non-pedestrian phases drafted at 21 / 30 / 22 / 22 — a drafted total of 95
# at a drafted cycle of 90, which the pipeline rescales onto a coordinated 105.
EVAL_SPLITS = [
    {"phase_number": 1, "split_sec": 21, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 2, "split_sec": 30, "min_green_sec": 15,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 4, "split_sec": 22, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 6, "split_sec": 22, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
]


def test_drafting_a_plan_invalidates_the_token_of_every_other_plan_the_client_holds():
    """The guarded version is the project's, so one accepted draft stales all the others.

    PRD §2.9: "Drafting a timing plan requires `expected_project_version`, carrying
    the client's last observed `version` of the retiming project the plan belongs
    to. If that value does not equal the project's current `version` — because some
    other writer has advanced the project since the client read it, for example by
    drafting the plan that legitimately supersedes the one this client still
    believes is current — the create is rejected with `ERR_STALE_PROJECT_VERSION`
    (HTTP 412) and nothing is written."

    PRD §3.5: "Creation also increments the parent project's `version` by 1, which
    is precisely why a second client holding a stale `expected_project_version` is
    turned away." ... "When a plan is created for a `project_id`,
    `intersection_id` and `tod_period` combination that already carries a plan
    still in `DRAFT`, that earlier draft transitions `DRAFT → SUPERSEDED` and has
    its own `version` incremented"

    PRD §2.4: "an integer that starts at 1 when the row is created and increases by
    exactly 1 on every mutation".  PRD §2.9 names only "Two create operations
    mutate a parent aggregate as a side effect", so the before-study rows leave the
    project's version alone, while PRD §3.4 moves it: "A successful advance
    recomputes `eligible_member_count` and increments the project's `version`."

    The last call shows the ordering: PRD §2.7 places "7. Body foreign keys resolve
    — the 404 codes for corridor, intersection, project and requester." above "11.
    Optimistic concurrency: the supplied parent version matches —
    `ERR_STALE_PROJECT_VERSION` or `ERR_STALE_INTERSECTION_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/occ_project_version_gates_plan_creation_and_the_supersede_that_moves_it
    """
    ctx = setup_project_in_data_collection()
    project_id = ctx["project"]["id"]
    intersection_id = ctx["intersections"][0]["id"]
    assert ctx["project"]["version"] == 1, "a freshly opened project is at version 1"

    complete_before_study(ctx)
    assert project_version(project_id) == 1, "counts and runs do not mutate the parent project"

    advanced = advance_project(project_id)
    assert advanced["status"] == "PLAN_DEVELOPMENT"
    assert advanced["version"] == 2, "the advance is the first mutation of the project row"

    # Plan A takes the AM_PEAK window and moves the parent to version 3.
    plan_a = draft_plan(
        project_id, intersection_id, expected_project_version=2, cycle_length_sec=90
    )
    assert plan_a["status"] == "DRAFT"
    assert plan_a["version"] == 1
    assert project_version(project_id) == 3, "the create incremented the parent aggregate"

    # A different time-of-day window, but the very same parent token: refused.
    validate_error(
        api_client.create_timing_plan(
            timing_plan_payload(
                project_id, intersection_id, 2,
                tod_period="MID_DAY", tod_start_min=540, tod_end_min=720,
                cycle_length_sec=90,
            ),
            AUTHOR,
        ),
        ApiErrorId.ERR_STALE_PROJECT_VERSION,
        412,
    )

    refreshed = project_version(project_id)
    assert refreshed == 3, "the refused create wrote nothing at all"
    plan_b = draft_plan(
        project_id, intersection_id, expected_project_version=refreshed,
        tod_period="MID_DAY", tod_start_min=540, tod_end_min=720, cycle_length_sec=90,
    )
    assert plan_b["status"] == "DRAFT", "the identical body succeeds on a refreshed token"

    # Plan C re-drafts the AM_PEAK window, which is the very race the rule names.
    latest = project_version(project_id)
    assert latest == 4
    plan_c = draft_plan(
        project_id, intersection_id, expected_project_version=latest, cycle_length_sec=100
    )
    assert plan_c["status"] == "DRAFT"

    superseded = read_plan(plan_a["id"])
    assert superseded["status"] == "SUPERSEDED", "the newest thinking replaces the old draft"
    assert superseded["version"] == 2, "the superseded row's own version moved by exactly 1"

    rows, meta = validate_paginated(api_client.list_project_timing_plans(project_id, ENGINEER))
    assert meta["total_count"] == 3, "only the three accepted creates exist"
    assert {row["id"] for row in rows} == {plan_a["id"], plan_b["id"], plan_c["id"]}

    # An unresolvable body foreign key answers before the concurrency guard does,
    # even though the token supplied here is stale as well.
    validate_error(
        api_client.create_timing_plan(
            timing_plan_payload(
                UNKNOWN_ID, intersection_id, 2,
                tod_period="PM_PEAK", tod_start_min=960, tod_end_min=1140,
                cycle_length_sec=90,
            ),
            AUTHOR,
        ),
        ApiErrorId.ERR_PROJECT_NOT_FOUND,
        404,
    )


def test_the_intersection_token_is_staled_by_the_engineer_and_by_the_administrator_alike():
    """A different parent, a different code, and two independent writers moving the version.

    PRD §2.9: "Proposing a priority configuration requires
    `expected_intersection_version`, carrying the client's last observed `version`
    of the target intersection. A mismatch against the intersection's current
    `version` is rejected with `ERR_STALE_INTERSECTION_VERSION` (HTTP 412). This
    guard exists because an intersection's `version` moves whenever its deployed
    coordinated cycle, and therefore its per-cycle priority second budget, is
    recomputed"

    PRD §3.9: "A new configuration starts with `approval_status` `PROPOSED`,
    `deployment_status` `NOT_DEPLOYED` and `granted_extension_sec` 0;
    `proposed_by_user_id` records the acting `X-User-ID`, and the parent
    intersection's `version` is incremented by 1." ... "the same rank number may
    legitimately be held once for `TSP` and once for `EVP` at the same
    intersection"

    PRD §3.1: "Every accepted update re-derives `operational_posture` from the new
    health values and increments the intersection's `version`." — an administrator's
    inventory edit therefore invalidates the engineer's token, which is exactly the
    race PRD §2.9 declares.

    PRD §3.9 leaves the budget at zero throughout, since it "is 0 whenever no plan
    of the intersection is deployed and therefore no coordinated cycle exists".

    PRD §2.7 places "7. Body foreign keys resolve — the 404 codes for corridor,
    intersection, project and requester." above "11. Optimistic concurrency: the
    supplied parent version matches — `ERR_STALE_PROJECT_VERSION` or
    `ERR_STALE_INTERSECTION_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/occ_intersection_version_gates_priority_config_creation_across_two_roles
    """
    intersection = create_intersection(max_cycle_length_sec=150)
    intersection_id = intersection["id"]
    assert intersection["version"] == 1

    first = validate_success(
        api_client.create_priority_config(
            priority_config_payload(
                intersection_id, 1, priority_type="EVP",
                requested_max_extension_sec=10, conflict_resolution_rank=1,
            ),
            ENGINEER,
        ),
        201,
    )
    assert first["approval_status"] == "PROPOSED"
    assert first["deployment_status"] == "NOT_DEPLOYED"
    assert first["granted_extension_sec"] == 0, "proposing reserves nothing"
    assert intersection_version(intersection_id) == 2, "the create moved the parent aggregate"

    # The engineer's own previous create is what staled their token.
    validate_error(
        api_client.create_priority_config(
            priority_config_payload(
                intersection_id, 1, priority_type="TSP",
                requested_max_extension_sec=8, conflict_resolution_rank=1,
            ),
            ENGINEER,
        ),
        ApiErrorId.ERR_STALE_INTERSECTION_VERSION,
        412,
    )

    second_token = intersection_version(intersection_id)
    assert second_token == 2, "the 412 wrote nothing"
    second = validate_success(
        api_client.create_priority_config(
            priority_config_payload(
                intersection_id, second_token, priority_type="TSP",
                requested_max_extension_sec=8, conflict_resolution_rank=1,
            ),
            ENGINEER,
        ),
        201,
    )
    assert second["approval_status"] == "PROPOSED", "rank 1 is free again for the other type"
    assert second["conflict_resolution_rank"] == 1

    # A completely unrelated inventory edit by another role stales the token too.
    engineer_token = intersection_version(intersection_id)
    assert engineer_token == 3
    patched = patch_intersection(intersection_id, detection_status="PARTIAL")
    assert patched["detection_status"] == "PARTIAL"
    assert patched["version"] == 4, "the administrator's update moved the parent aggregate"

    validate_error(
        api_client.create_priority_config(
            priority_config_payload(
                intersection_id, engineer_token, priority_type="EVP",
                requested_max_extension_sec=6, conflict_resolution_rank=2,
            ),
            ENGINEER,
        ),
        ApiErrorId.ERR_STALE_INTERSECTION_VERSION,
        412,
    )
    third = validate_success(
        api_client.create_priority_config(
            priority_config_payload(
                intersection_id, 4, priority_type="EVP",
                requested_max_extension_sec=6, conflict_resolution_rank=2,
            ),
            ENGINEER,
        ),
        201,
    )
    assert third["conflict_resolution_rank"] == 2, "the same body succeeds on the fresh token"

    # The unresolvable body foreign key answers before the concurrency guard.
    validate_error(
        api_client.create_priority_config(
            priority_config_payload(
                UNKNOWN_ID, engineer_token, priority_type="TSP",
                requested_max_extension_sec=6, conflict_resolution_rank=9,
            ),
            ENGINEER,
        ),
        ApiErrorId.ERR_INTERSECTION_NOT_FOUND,
        404,
    )

    config_rows, config_meta = validate_paginated(
        api_client.list_intersection_priority_configs(intersection_id, ADMIN)
    )
    assert config_meta["total_count"] == 3, "exactly three creates landed"
    assert {row["id"] for row in config_rows} == {first["id"], second["id"], third["id"]}

    final = read_intersection(intersection_id)
    assert final["version"] == 5, "three creates plus one update, and nothing from the refusals"
    assert final["priority_budget_sec"] == 0, "no plan has ever been deployed here"
    assert final["granted_priority_extension_total_sec"] == 0
    assert final["unallocated_priority_budget_sec"] == 0


def test_a_phase_transition_stales_the_token_that_guards_evaluation_creation():
    """The third guarded write, invalidated by a status change rather than a sibling create.

    PRD §2.9: "The same field and the same rejection code guard the creation of a
    provisional performance evaluation for a project."

    PRD §3.10: "A `SignalOpsAdmin` starts the observation phase by supplying an
    `action` of `START`, which moves the project `IMPLEMENTED → FIELD_TUNING`" ...
    "Creation requires `expected_project_version` and is refused with
    `ERR_STALE_PROJECT_VERSION` on a mismatch. A new evaluation is `PROVISIONAL`
    with `metric_variant` `PROVISIONAL_UNWEIGHTED`".

    PRD §2.4: "an integer that starts at 1 when the row is created and increases by
    exactly 1 on every mutation", so the transition moves the project past the
    version that the implement call handed back.

    PRD §3.10 fixes the numbers the accepted retry must produce: "every run with
    `study_role` `AFTER` is included regardless of when it was recorded, and a mean
    is the plain arithmetic mean" ... "`delay_reduction_pct` is 100.0 multiplied by
    the difference between the before mean and the after mean, divided by the before
    mean, rounded half up to 2 decimal places".

    Design: Corner/cross_cutting_complexity_layers/occ_project_version_also_gates_performance_evaluation_creation
    """
    ctx = setup_implemented_project(plan_overrides={"cycle_length_sec": 90}, splits=EVAL_SPLITS)
    project_id = ctx["project"]["id"]
    assert ctx["project"]["status"] == "IMPLEMENTED"
    implement_token = ctx["project"]["version"]

    tuning = field_tuning(project_id, "START")
    assert tuning["status"] == "FIELD_TUNING"
    assert tuning["version"] > implement_token, "the phase transition is the invalidating write"

    record_run(
        project_id,
        study_role="AFTER",
        started_at=CLOCK_START,
        duration_sec=300,
        stops_count=3,
        arrivals_on_green_count=8,
        total_arrivals=12,
    )

    validate_error(
        api_client.create_performance_evaluation(
            project_id, performance_evaluation_payload(implement_token), REVIEWER
        ),
        ApiErrorId.ERR_STALE_PROJECT_VERSION,
        412,
    )

    _, empty_meta = validate_paginated(
        api_client.list_project_performance_evaluations(project_id, REVIEWER)
    )
    assert empty_meta["total_count"] == 0, "the refusal precedes every metric computation"

    current = project_version(project_id)
    assert current == tuning["version"]
    evaluation = create_evaluation(project_id, expected_project_version=current)
    assert evaluation["status"] == "PROVISIONAL"
    assert evaluation["metric_variant"] == "PROVISIONAL_UNWEIGHTED"
    assert evaluation["included_after_run_count"] == 1
    assert evaluation["mean_travel_time_before_sec"] == 320.00
    assert evaluation["mean_travel_time_after_sec"] == 300.00
    assert evaluation["delay_reduction_pct"] == 6.25
    assert evaluation["stops_reduction_pct"] == 40.00
    assert evaluation["aog_pct_after"] == 66.67

    _, filled_meta = validate_paginated(
        api_client.list_project_performance_evaluations(project_id, REVIEWER)
    )
    assert filled_meta["total_count"] == 1, "one refused create and one accepted create"
