"""The two multi-link cascades: implementation escalating, fine tuning de-escalating."""
from test_helpers import (
    assert_complaint_partition,
    assert_instant_equals,
    assert_priority_budget_invariant,
)
from test_helpers.fixtures import (
    CANONICAL_PLAN,
    CANONICAL_SPLITS,
    corridor_complaints,
    create_corridor,
    create_evaluation,
    create_requester,
    effective_splits,
    enrol_member,
    file_complaint,
    implement_project,
    log_observation,
    read_complaint,
    read_corridor,
    read_evaluation,
    read_intersection,
    read_ped_checks,
    read_plan,
    read_project,
    record_run,
    screen_corridor,
    setup_certified_plan,
    setup_field_tuning_project,
    triage_complaint,
)

CANONICAL = {"plan_overrides": dict(CANONICAL_PLAN), "splits": CANONICAL_SPLITS}
AFTER_RUN = {
    "study_role": "AFTER",
    "direction": "NB",
    "started_at": "2026-07-20T09:00:00Z",
    "duration_sec": 260,
    "stops_count": 2,
    "arrivals_on_green_count": 9,
    "total_arrivals": 10,
}


def _implementation_chain():
    """One intersection in two corridors, three triaged complaints, one certified plan.

    The arterial corridor c1 carries the project; the local corridor c2 shares
    the same intersection and was screened while that intersection was still
    stale, which put it in SCREENED at a score of 38.40.
    """
    ctx = setup_certified_plan(**CANONICAL)
    intersection = ctx["intersections"][0]
    local = create_corridor(jurisdiction_class="LOCAL", annual_volume_change_pct=0.0)
    enrol_member(local["id"], intersection["id"], 1)
    requester = create_requester()
    complaints = [
        file_complaint(requester["id"], local["id"], category="COORDINATION",
                       narrative="Signals on Elm are out of step westbound."),
        file_complaint(requester["id"], local["id"], category="COORDINATION",
                       narrative="Second coordination report on the same block."),
        file_complaint(requester["id"], local["id"], category="PEDESTRIAN",
                       narrative="Walk interval too short at the school crossing."),
    ]
    for complaint in complaints:
        triage_complaint(complaint["id"], "TRIAGE", note="Queued for the program")
    ctx["local"] = screen_corridor(local["id"])
    ctx["complaints"] = complaints
    ctx["requester"] = requester
    return ctx


def test_implementation_deploys_the_plan_and_refreshes_the_intersection():
    """Links one to three: the project, its plan and the plan's intersection all move.

    PRD §3.8: "First, the project moves `PLAN_DEVELOPMENT → IMPLEMENTED` and its
    `version` is incremented. Second, because the project entered `IMPLEMENTED`,
    every timing plan of the project in `CERTIFIED` moves `CERTIFIED →
    DEPLOYED`" and "the plan's intersection is refreshed: `last_retimed_at` takes
    the logical clock's current value, `timing_plan_age_days` consequently
    becomes 0, `deployed_coordinated_cycle_sec` is re-derived as the
    `cycle_length_sec` of the deployed plan holding the lowest `tod_start_min`,
    the three priority-budget fields are recomputed from that new cycle".
    PRD §3.9: "An intersection's `priority_budget_sec` is one fifth — 20 percent
    — of its `deployed_coordinated_cycle_sec`, taken as a floor".

    Design: Difficulty/transitive_cascade/implementation_cascade_five_links_project_plan_intersection_corridor_complaint
    """
    ctx = _implementation_chain()
    assert float(ctx["local"]["priority_score"]) == 38.40
    assert float(ctx["local"]["avg_plan_age_days"]) == 3650.00
    assert ctx["local"]["complaint_count_12mo"] == 3
    assert ctx["local"]["selection_status"] == "SCREENED"

    project = implement_project(ctx["project"]["id"])
    assert project["status"] == "IMPLEMENTED"
    assert read_plan(ctx["plan"]["id"])["status"] == "DEPLOYED"

    intersection = read_intersection(ctx["intersections"][0]["id"])
    assert_instant_equals(intersection["last_retimed_at"], "2026-08-01T00:00:00Z",
                          "last_retimed_at")
    assert intersection["timing_plan_age_days"] == 0
    assert intersection["deployed_coordinated_cycle_sec"] == 105
    assert intersection["priority_budget_sec"] == 21
    assert intersection["granted_priority_extension_total_sec"] == 0
    assert intersection["unallocated_priority_budget_sec"] == 21
    assert_priority_budget_invariant(intersection)


def test_implementation_rescores_both_corridors_and_requeues_their_complaints():
    """Links four and five: the local corridor is auto-deferred and its complaints requeued.

    PRD §3.8: "A corridor whose recomputed score falls below the defer threshold
    of 35.00 **and** whose `selection_status` is `SCREENED` is auto-deferred,
    moving `SCREENED → DEFERRED`" and "A corridor at `UNSCREENED`, `SELECTED` or
    already `DEFERRED` is left alone regardless of its score, and a `SCREENED`
    corridor scoring exactly 35.00 or above is likewise left at `SCREENED`."
    PRD §3.8: "For each auto-deferred corridor, every complaint whose `status` is
    `TRIAGED` and whose `category` is `COORDINATION` moves `TRIAGED → OPEN`,
    processed in `created_at` ascending order, with `reopen_count` incremented by
    1 and `version` incremented by 1. Complaints of any other category are
    untouched".

    Design: Difficulty/transitive_cascade/implementation_cascade_five_links_project_plan_intersection_corridor_complaint
    """
    ctx = _implementation_chain()
    implement_project(ctx["project"]["id"])

    arterial = read_corridor(ctx["corridor"]["id"])
    assert float(arterial["priority_score"]) == 35.00
    assert arterial["priority_score_variant"] == "PROGRAMMING"
    # Exactly 35.00 is not below 35.00, and it is SELECTED rather than SCREENED.
    assert arterial["selection_status"] == "SELECTED"

    local_id = ctx["local"]["id"]
    local = read_corridor(local_id)
    assert float(local["avg_plan_age_days"]) == 0.00
    assert float(local["priority_score"]) == 2.40
    assert local["priority_score_variant"] == "PROGRAMMING"
    assert local["selection_status"] == "DEFERRED"

    first, second, pedestrian = ctx["complaints"]
    for coordination in (first, second):
        row = read_complaint(local_id, coordination["id"])
        assert row["status"] == "OPEN"
        assert row["reopen_count"] == 1
    untouched = read_complaint(local_id, pedestrian["id"])
    assert untouched["status"] == "TRIAGED"
    assert untouched["reopen_count"] == 0

    # TRIAGED and OPEN share the open bucket, so the partition is unchanged.
    assert local["complaint_total_count"] == 3
    assert local["complaint_open_count"] == 3
    assert local["complaint_linked_count"] == 0
    assert local["complaint_terminal_count"] == 0
    assert_complaint_partition(local)
    assert len(corridor_complaints(local_id)) == 3


def _fine_tuning_chain():
    """An implemented project in FIELD_TUNING carrying one provisional evaluation."""
    ctx = setup_field_tuning_project(**CANONICAL)
    project_id = ctx["project"]["id"]
    ctx["after_run"] = record_run(project_id, **AFTER_RUN)
    ctx["evaluation"] = create_evaluation(project_id)
    return ctx


def test_an_adjustment_observation_reopens_the_deployed_plan_to_draft():
    """Links one and two: the observation is stored and its plan is compensated.

    PRD §3.10: "The server stamps `observer_user_id` with the acting `X-User-ID`
    and sets `resolution_status` to `OPEN`." and "That plan moves `DEPLOYED →
    DRAFT` and is compensated exactly as a returned plan is: `cycle_length_sec`
    is restored from `drafted_cycle_length_sec`, `offset_sec` returns to 0,
    `ped_compliance_state` returns to `PENDING`, every phase split's
    `effective_split_sec` is restored to its `split_sec`,
    `effective_split_total_sec` is restored to `drafted_split_total_sec`, every
    pedestrian compliance check of the plan is deleted".

    Design: Difficulty/transitive_cascade/fine_tuning_cascade_four_links_observation_plan_project_evaluation
    """
    ctx = _fine_tuning_chain()
    assert ctx["project"]["status"] == "FIELD_TUNING"
    assert ctx["project"]["tuning_round"] == 0
    assert ctx["evaluation"]["status"] == "PROVISIONAL"
    plan_id = ctx["plan"]["id"]
    assert read_plan(plan_id)["status"] == "DEPLOYED"

    observation = log_observation(
        ctx["project"]["id"], ctx["intersections"][0]["id"],
        finding_code="EARLY_RETURN_TO_GREEN", requires_adjustment=True,
    )
    assert observation["resolution_status"] == "OPEN"
    assert observation["observer_user_id"] == "tech-1"

    plan = read_plan(plan_id)
    assert plan["status"] == "DRAFT"
    assert plan["cycle_length_sec"] == 90
    assert plan["offset_sec"] == 0
    assert plan["ped_compliance_state"] == "PENDING"
    assert plan["effective_split_total_sec"] == 86
    assert effective_splits(plan_id) == {1: 21, 2: 21, 4: 22, 6: 22}
    assert read_ped_checks(plan_id) == []


def test_the_reopened_plan_drags_the_project_back_and_invalidates_the_evaluation():
    """Links three and four: only the plan's departure from DEPLOYED fires them.

    PRD §3.10: "Because that plan left `DEPLOYED`, the project itself moves
    `FIELD_TUNING → PLAN_DEVELOPMENT` with `tuning_round` incremented by 1 and
    its `version` incremented; this second link fires only if a matching deployed
    plan was actually found and reopened. And because the project left
    `FIELD_TUNING`, every performance evaluation of the project still in
    `PROVISIONAL` moves `PROVISIONAL → INVALIDATED`, processed in `created_at`
    ascending order".

    Design: Difficulty/transitive_cascade/fine_tuning_cascade_four_links_observation_plan_project_evaluation
    """
    ctx = _fine_tuning_chain()
    project_id = ctx["project"]["id"]

    log_observation(project_id, ctx["intersections"][0]["id"],
                    finding_code="EARLY_RETURN_TO_GREEN", requires_adjustment=True)

    project = read_project(project_id)
    assert project["status"] == "PLAN_DEVELOPMENT"
    assert project["tuning_round"] == 1

    evaluation = read_evaluation(project_id, ctx["evaluation"]["id"])
    assert evaluation["status"] == "INVALIDATED"


def test_an_observation_without_the_flag_fires_no_cascade_at_all():
    """The flag, not the observation, is what withdraws the timing.

    PRD §3.10: "The optional `requires_adjustment` flag, false by default, is the
    consequential one: it declares that the finding demands a timing change." and
    "An observation flagged `requires_adjustment` fires a three-link cascade on
    top of its own creation."

    Design: Difficulty/transitive_cascade/fine_tuning_cascade_four_links_observation_plan_project_evaluation
    """
    ctx = _fine_tuning_chain()
    project_id = ctx["project"]["id"]
    plan_id = ctx["plan"]["id"]

    observation = log_observation(project_id, ctx["intersections"][0]["id"],
                                 finding_code="QUEUE_SPILLBACK", requires_adjustment=False)
    assert observation["resolution_status"] == "OPEN"

    plan = read_plan(plan_id)
    assert plan["status"] == "DEPLOYED"
    assert plan["cycle_length_sec"] == 105
    assert plan["effective_split_total_sec"] == 105
    assert len(read_ped_checks(plan_id)) == 1

    project = read_project(project_id)
    assert project["status"] == "FIELD_TUNING"
    assert project["tuning_round"] == 0
    assert read_evaluation(project_id, ctx["evaluation"]["id"])["status"] == "PROVISIONAL"


def test_the_implementation_cascade_leaves_no_link_unfired():
    """All five links are observable from one request, each on a different entity.

    PRD §2.11: "When they do, the whole set of effects is applied within the
    triggering request, in the order this document pins, and every touched row
    has its `updated_at` refreshed and its `version` incremented by 1 —
    including rows the caller never named."

    Design: Difficulty/transitive_cascade/implementation_cascade_five_links_project_plan_intersection_corridor_complaint
    """
    ctx = _implementation_chain()
    project_before = read_project(ctx["project"]["id"])
    local_before = read_corridor(ctx["local"]["id"])

    project_after = implement_project(ctx["project"]["id"])

    assert project_after["version"] == project_before["version"] + 1
    assert read_plan(ctx["plan"]["id"])["status"] == "DEPLOYED"
    assert read_intersection(ctx["intersections"][0]["id"])["timing_plan_age_days"] == 0
    local_after = read_corridor(ctx["local"]["id"])
    assert local_after["version"] > local_before["version"]
    assert local_after["selection_status"] == "DEFERRED"
    assert read_complaint(local_after["id"], ctx["complaints"][0]["id"])["reopen_count"] == 1
