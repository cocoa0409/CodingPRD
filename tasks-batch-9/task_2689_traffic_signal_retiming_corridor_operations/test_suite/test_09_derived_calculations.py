"""Derived numbers: posture ladder, ages, windows, Webster cycles, offsets, budgets."""
from test_helpers import ApiErrorId, api_client, assert_instant_equals, validate_error
from test_helpers.constants import CLOCK_START, NEVER_RETIMED_AGE_DAYS
from test_helpers.fixtures import (
    ADMIN,
    CANONICAL_PLAN,
    CANONICAL_SPLITS,
    TECHNICIAN,
    add_splits,
    advance_project,
    approve_config,
    coordinate_project,
    create_corridor,
    create_intersection,
    create_requester,
    decide_corridor,
    draft_plan,
    effective_splits,
    enrol_member,
    file_complaint,
    intersection_counts,
    patch_intersection,
    project_counts,
    propose_config,
    read_config,
    read_intersection,
    read_plan,
    record_count,
    record_run,
    screen_corridor,
    set_clock,
    setup_canonical_implemented_project,
    setup_certified_plan,
    setup_project_in_data_collection,
    triage_complaint,
)

# Four phases totalling 95 drafted seconds; phase 2 carries the greatest
# minimum green, so it is the phase the rescale residual lands on.
MASTER_SPLITS = [
    {"phase_number": 1, "split_sec": 21, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 2, "split_sec": 30, "min_green_sec": 15,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 4, "split_sec": 22, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 6, "split_sec": 22, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
]

# Two phases of 20 seconds each, drafted total 40, phase 2 holding the greatest
# minimum green.
TWO_PHASE_SPLITS = [
    {"phase_number": 1, "split_sec": 20, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 2, "split_sec": 20, "min_green_sec": 12,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
]

# 1280 vehicles over four phases: a critical flow ratio of 0.7111 and a
# recommended cycle of 105 seconds.
MODERATE_VOLUMES = {"1": 350, "2": 500, "4": 250, "6": 180}
# 1500 vehicles over four phases: 0.8333 and 175 seconds.
HEAVY_VOLUMES = {"1": 400, "2": 600, "4": 300, "6": 200}


def test_the_posture_ladder_is_walked_top_down_and_never_latches():
    """OFFLINE beats PARTIAL on the same row, and repairing both fields restores READY.

    PRD §2.10: "It is computed from exactly two of the intersection's own fields
    — `comm_status` and `detection_status` — and never from any child row, and it
    is re-derived on every read and on every write that materialises the
    intersection. If communication is `OFFLINE`, or detection has `FAILED`, the
    posture is `BLOCKED`. Otherwise, if communication is `INTERMITTENT`, or
    detection is `PARTIAL` or `NONE`, the posture is `RESTRICTED`. In every
    remaining case the posture is `READY`." PRD §3.1: "Every accepted update
    re-derives `operational_posture` from the new health values and increments
    the intersection's `version`."

    Design: Corner/calculations/operational_posture_threshold_ladder_including_its_precedence
    """
    intersection = create_intersection(controller_type="TS2_CABINET",
                                       detection_status="FULL", comm_status="ONLINE")
    intersection_id = intersection["id"]
    assert intersection["operational_posture"] == "READY"
    assert intersection["version"] == 1

    degraded_comm = patch_intersection(intersection_id, comm_status="INTERMITTENT")
    assert degraded_comm["operational_posture"] == "RESTRICTED"

    partial = patch_intersection(intersection_id, comm_status="ONLINE",
                                 detection_status="PARTIAL")
    assert partial["operational_posture"] == "RESTRICTED"

    none_detection = patch_intersection(intersection_id, detection_status="NONE")
    assert none_detection["operational_posture"] == "RESTRICTED"

    failed = patch_intersection(intersection_id, detection_status="FAILED")
    assert failed["operational_posture"] == "BLOCKED"

    # Simultaneously OFFLINE and PARTIAL: the first branch decides.
    both = patch_intersection(intersection_id, detection_status="PARTIAL",
                              comm_status="OFFLINE")
    assert both["operational_posture"] == "BLOCKED"

    healthy_again = patch_intersection(intersection_id, detection_status="FULL",
                                       comm_status="ONLINE")
    assert healthy_again["operational_posture"] == "READY"
    assert healthy_again["version"] == 7


def test_plan_age_truncates_downward_at_every_whole_day_boundary():
    """One second short of a day is still zero days; a never-retimed signal stays at 3650.

    PRD §3.1: "`timing_plan_age_days` reports how stale the intersection's
    deployed timing is, in whole days: while `last_retimed_at` is still null —
    meaning no timing plan for this intersection has ever reached `DEPLOYED` —
    the age reads exactly 3650 days" ... "Once `last_retimed_at` holds an
    instant, the age is the whole number of seconds between it and the logical
    clock's current value, divided by 86400 and truncated downward to a whole
    day; a gap of one second short of two full days reports 1, not 2." PRD §2.8:
    "plan age in days truncates downward to a whole day, and the priority second
    budget takes the floor of its fraction, so neither can ever overstate."

    Design: Corner/calculations/timing_plan_age_days_floors_at_the_whole_day_boundary
    """
    untouched = create_intersection()
    assert untouched["timing_plan_age_days"] == NEVER_RETIMED_AGE_DAYS
    assert untouched["last_retimed_at"] is None

    ctx = setup_canonical_implemented_project()
    intersection_id = ctx["intersections"][0]["id"]

    retimed = read_intersection(intersection_id)
    assert_instant_equals(retimed["last_retimed_at"], CLOCK_START, "last_retimed_at")
    assert retimed["timing_plan_age_days"] == 0

    set_clock("2026-08-01T23:59:59Z")
    assert read_intersection(intersection_id)["timing_plan_age_days"] == 0

    set_clock("2026-08-02T00:00:00Z")
    assert read_intersection(intersection_id)["timing_plan_age_days"] == 1

    set_clock("2026-08-03T12:00:00Z")
    # Two and a half elapsed days truncate to 2, never round to 3.
    assert read_intersection(intersection_id)["timing_plan_age_days"] == 2
    # The age reads off last_retimed_at alone, so the spare signal never moves.
    assert read_intersection(untouched["id"])["timing_plan_age_days"] == \
        NEVER_RETIMED_AGE_DAYS


def test_the_twelve_month_window_is_closed_below_and_drops_no_action_complaints():
    """Three filters at once: the status set, the inclusive lower bound, one second past it.

    PRD §3.2: "`complaint_count_12mo` is recomputed as the trailing-twelve-month
    complaint pressure — the number of the corridor's complaints whose
    `received_at` falls inside the **closed** interval that begins 365 days
    before the logical clock's current value and ends at that current value,
    counting only complaints in `OPEN`, `TRIAGED`, `LINKED` or `RESOLVED`.
    Complaints in `CLOSED_NO_ACTION` are excluded from this window count" ...
    "and a complaint whose `received_at` falls exactly on the lower bound, to the
    second, **is** counted, while one second earlier is not." PRD §3.2:
    "`complaint_total_count` counts every complaint filed against the corridor
    regardless of status or age".

    Design: Corner/calculations/complaint_window_lower_bound_is_inclusive_and_closed_no_action_is_excluded
    """
    intersection = create_intersection()
    corridor = create_corridor(jurisdiction_class="ARTERIAL",
                               annual_volume_change_pct=20.0)
    corridor_id = corridor["id"]
    enrol_member(corridor_id, intersection["id"], 1, distance_from_prev_ft=0)

    requester = create_requester()
    kept = file_complaint(requester["id"], corridor_id, category="COORDINATION",
                          narrative="Progression is broken northbound in the AM.")
    dropped = file_complaint(requester["id"], corridor_id, category="DETECTION",
                             narrative="Detector loop looks broken.")
    assert_instant_equals(kept["received_at"], CLOCK_START, "received_at")
    assert triage_complaint(dropped["id"], "NO_ACTION",
                            note="Maintenance ticket, not a timing complaint."
                            )["status"] == "CLOSED_NO_ACTION"

    day_zero = screen_corridor(corridor_id)
    assert day_zero["complaint_count_12mo"] == 1
    assert day_zero["complaint_total_count"] == 2
    assert float(day_zero["avg_plan_age_days"]) == 3650.00
    # 0.45 + 0.35 * 0.8 + 0.20 * 0.05 == 0.74, times the ARTERIAL 1.25.
    assert float(day_zero["priority_score"]) == 92.50

    decide_corridor(corridor_id, "DEFER", rationale="Wait for the next cycle")
    set_clock("2027-08-01T00:00:00Z")
    on_the_bound = screen_corridor(corridor_id)
    assert on_the_bound["complaint_count_12mo"] == 1
    assert float(on_the_bound["priority_score"]) == 92.50

    decide_corridor(corridor_id, "DEFER", rationale="Still waiting")
    set_clock("2027-08-01T00:00:01Z")
    past_the_bound = screen_corridor(corridor_id)
    assert past_the_bound["complaint_count_12mo"] == 0
    assert past_the_bound["complaint_total_count"] == 2
    # The complaint component drops to 0 and the score falls by exactly 1.25.
    assert float(past_the_bound["priority_score"]) == 91.25


def test_every_webster_constant_and_both_clamps_show_up_in_four_counts():
    """The ceiling runs before the local maximum, and the 60-second floor runs last.

    PRD §3.4: "Its `critical_flow_ratio_sum` is the sum of all its phase volumes
    divided by a saturation flow of 1800 vehicles per hour per lane" ... "A count
    whose critical flow ratio reaches the oversaturation ratio of 0.95 describes
    an approach that cannot be fixed by retiming — a sum of exactly 0.95 is
    already too much, and is rejected together with anything above it — and the
    recording is refused with `ERR_OVERSATURATED_APPROACH`." ... "the total lost
    time is the number of phase entries multiplied by 4.0 seconds of lost time
    per phase; the raw cycle is one and a half times that total lost time, plus
    5.0, all divided by one minus the critical flow ratio sum; that raw cycle is
    then raised to the next whole multiple of 5 seconds" ... "The clamping order
    matters: the local ceiling is applied to the rounded-up value, and the
    60-second floor is applied last and therefore wins over a ceiling below 60."

    Design: Corner/calculations/webster_constants_with_ceiling_to_five_and_both_clamps
    """
    ctx = setup_project_in_data_collection(intersections=[{"max_cycle_length_sec": 150}])
    project_id = ctx["project"]["id"]
    intersection_id = ctx["intersections"][0]["id"]

    moderate = record_count(intersection_id, project_id,
                            count_date="2026-07-10T00:00:00Z", period="AM_PEAK",
                            phase_volumes=MODERATE_VOLUMES)
    assert float(moderate["critical_flow_ratio_sum"]) == 0.7111
    # 29.0 / (1 - 0.711111) == 100.3846, raised to the next multiple of five.
    assert moderate["recommended_cycle_sec"] == 105

    light = record_count(intersection_id, project_id,
                         count_date="2026-07-11T00:00:00Z", period="MID_DAY",
                         phase_volumes={"1": 100, "2": 100})
    assert float(light["critical_flow_ratio_sum"]) == 0.1111
    # 19.125 ceils to 20 and is then lifted to the floor.
    assert light["recommended_cycle_sec"] == 60

    heavy = record_count(intersection_id, project_id,
                         count_date="2026-07-12T00:00:00Z", period="PM_PEAK",
                         phase_volumes={"1": 854, "2": 854})
    assert float(heavy["critical_flow_ratio_sum"]) == 0.9489
    # 332.6087 ceils to 335 and is only then clamped down to the local maximum.
    assert heavy["recommended_cycle_sec"] == 150

    validate_error(
        api_client.create_turning_movement_count(
            intersection_id,
            {
                "project_id": project_id,
                "study_role": "BEFORE",
                "count_date": "2026-07-13T00:00:00Z",
                "period": "PM_PEAK",
                "phase_volumes": {"1": 855, "2": 855},
            },
            TECHNICIAN,
        ),
        ApiErrorId.ERR_OVERSATURATED_APPROACH.value,
        422,
    )

    stored = intersection_counts(intersection_id, study_role="BEFORE")
    assert len(stored) == 3
    assert sorted(row["recommended_cycle_sec"] for row in stored) == [60, 105, 150]


def test_a_local_free_plan_neither_raises_the_corridor_cycle_nor_takes_an_offset():
    """The downstream 175-second ask never enters the max, and its 2640 ft buys no offset.

    PRD §3.6: "Participants are the corridor's membership rows, enumerated in
    `sequence_index` ascending order, restricted to members whose intersection
    posture is `READY` or `RESTRICTED` **and** which have at least one `DRAFT`
    plan for this project whose `coordination_ref` is `MASTER`." ... "Otherwise
    the coordinated cycle is the largest of the participants' recommended cycles,
    raised to the next whole multiple of 5 seconds." PRD §3.6: "A plan whose
    `coordination_ref` is `LOCAL_FREE` keeps its own drafted cycle untouched."
    PRD §3.6: "A plan whose `coordination_ref` is `LOCAL_FREE` gets an
    `offset_sec` of 0 and nothing more happens."

    Design: Corner/calculations/coordination_participants_exclude_local_free_plans
    """
    ctx = setup_project_in_data_collection(
        intersections=[{"max_cycle_length_sec": 240}, {"max_cycle_length_sec": 240}],
        distances=[0, 2640],
    )
    project_id = ctx["project"]["id"]
    upstream_id = ctx["intersections"][0]["id"]
    downstream_id = ctx["intersections"][1]["id"]

    upstream_count = record_count(upstream_id, project_id,
                                  phase_volumes=MODERATE_VOLUMES)
    downstream_count = record_count(downstream_id, project_id,
                                    phase_volumes=HEAVY_VOLUMES)
    assert upstream_count["recommended_cycle_sec"] == 105
    assert float(downstream_count["critical_flow_ratio_sum"]) == 0.8333
    # The downstream signal alone would demand the longer cycle.
    assert downstream_count["recommended_cycle_sec"] == 175
    record_run(project_id)
    advance_project(project_id)

    master = draft_plan(project_id, upstream_id, cycle_length_sec=90,
                        coordination_ref="MASTER")
    local = draft_plan(project_id, downstream_id, cycle_length_sec=90,
                       coordination_ref="LOCAL_FREE")
    add_splits(master["id"], MASTER_SPLITS)
    add_splits(local["id"], TWO_PHASE_SPLITS)

    coordinate_project(project_id)

    coordinated = read_plan(master["id"])
    assert coordinated["cycle_length_sec"] == 105
    assert coordinated["drafted_cycle_length_sec"] == 90
    assert coordinated["drafted_split_total_sec"] == 95
    assert coordinated["effective_split_total_sec"] == 105
    assert coordinated["offset_sec"] == 0
    assert effective_splits(master["id"]) == {1: 23, 2: 34, 4: 24, 6: 24}

    free_running = read_plan(local["id"])
    assert free_running["cycle_length_sec"] == 90
    assert free_running["drafted_cycle_length_sec"] == 90
    # 2640 ft would have produced 60 seconds under the master.
    assert free_running["offset_sec"] == 0
    # The rescale still runs, against the plan's own 90-second cycle.
    assert free_running["effective_split_total_sec"] == 90
    assert effective_splits(local["id"]) == {1: 45, 2: 45}


def test_the_cumulative_travel_time_is_rounded_before_the_modulo_folds_it():
    """4618 ft rounds to 105 and folds to 0; rounding after the modulo would yield 105.

    PRD §3.6: "Divide that cumulative distance in feet by a progression speed of
    44.0 feet per second (30 miles per hour) to get a cumulative travel time in
    seconds, round that half up to a whole second, and only then take the
    remainder of dividing it by the plan's `cycle_length_sec`. The rounding
    happens before the modulo, never after." PRD §3.6: "a residual is computed as
    the operating cycle length minus the sum of the rounded effective splits; the
    residual may be positive or negative. That single residual is added to
    exactly one phase: the phase with the greatest `min_green_sec`, and if
    several tie on that, the one with the lowest `phase_number`."

    Design: Corner/calculations/offset_is_rounded_before_the_modulo_not_after
    """
    ctx = setup_project_in_data_collection(
        intersections=[{"max_cycle_length_sec": 150} for _ in range(3)],
        distances=[0, 2640, 1978],
    )
    project_id = ctx["project"]["id"]
    intersection_ids = [inter["id"] for inter in ctx["intersections"]]

    for intersection_id in intersection_ids:
        record_count(intersection_id, project_id, phase_volumes=MODERATE_VOLUMES)
    record_run(project_id)
    advance_project(project_id)

    plans = []
    for intersection_id in intersection_ids:
        plan = draft_plan(project_id, intersection_id, cycle_length_sec=90,
                          coordination_ref="MASTER")
        add_splits(plan["id"], TWO_PHASE_SPLITS)
        plans.append(plan)

    coordinate_project(project_id)
    first, second, third = [read_plan(plan["id"]) for plan in plans]

    assert first["cycle_length_sec"] == 105
    # The first member has no distance ahead of it.
    assert first["offset_sec"] == 0
    # 2640 / 44.0 == 60.0 exactly, and 60 mod 105 == 60.
    assert second["offset_sec"] == 60
    # 4618 / 44.0 == 104.9545 rounds to 105, and 105 mod 105 == 0.
    assert third["offset_sec"] == 0

    # Each phase's 52.5 rounds half up to 53, so the residual is negative.
    assert effective_splits(plans[2]["id"]) == {1: 53, 2: 52}
    assert third["effective_split_total_sec"] == 105
    assert third["drafted_split_total_sec"] == 40


def test_certification_alone_never_feeds_the_priority_budget():
    """A CERTIFIED plan is not a deployed cycle, so the budget stays 0 and the deploy fails.

    PRD §3.1: "`deployed_coordinated_cycle_sec` is the `cycle_length_sec` of this
    intersection's `DEPLOYED` timing plan holding the lowest `tod_start_min`, and
    is null while no plan of this intersection is `DEPLOYED`." PRD §3.9: "An
    intersection's `priority_budget_sec` is one fifth — 20 percent — of its
    `deployed_coordinated_cycle_sec`, taken as a floor so the budget can never
    exceed the fraction, and it is 0 whenever no plan of the intersection is
    deployed and therefore no coordinated cycle exists." ... "That budget is then
    handed out by a **waterfall** over the intersection's configurations whose
    `deployment_status` is `DEPLOYED`". PRD §3.9: "And the intersection must
    already carry at least one `DEPLOYED` timing plan, since there is no cycle to
    extend otherwise; the absence of one is refused with
    `ERR_PLAN_COVERAGE_INCOMPLETE`."

    Design: Corner/calculations/priority_budget_is_zero_until_a_plan_is_actually_deployed
    """
    ctx = setup_certified_plan(plan_overrides=dict(CANONICAL_PLAN),
                               splits=CANONICAL_SPLITS)
    intersection_id = ctx["intersections"][0]["id"]
    assert ctx["plan"]["status"] == "CERTIFIED"
    assert ctx["plan"]["cycle_length_sec"] == 105
    # A freshly registered intersection has no cycle and no budget.
    assert ctx["intersections"][0]["deployed_coordinated_cycle_sec"] is None
    assert ctx["intersections"][0]["priority_budget_sec"] == 0

    blessed_but_unrolled = read_intersection(intersection_id)
    assert blessed_but_unrolled["deployed_coordinated_cycle_sec"] is None
    assert blessed_but_unrolled["priority_budget_sec"] == 0
    assert blessed_but_unrolled["granted_priority_extension_total_sec"] == 0
    assert blessed_but_unrolled["unallocated_priority_budget_sec"] == 0

    proposed = propose_config(intersection_id, priority_type="TSP",
                              requested_max_extension_sec=10,
                              conflict_resolution_rank=1)
    approved = approve_config(proposed["id"])
    assert approved["approval_status"] == "APPROVED"
    # The allocation pool is filtered on deployment, not on approval.
    assert approved["granted_extension_sec"] == 0

    validate_error(
        api_client.deploy_priority_config(approved["id"], ADMIN),
        ApiErrorId.ERR_PLAN_COVERAGE_INCOMPLETE.value,
        409,
    )

    refused = read_config(intersection_id, approved["id"])
    assert refused["deployment_status"] == "NOT_DEPLOYED"
    assert refused["granted_extension_sec"] == 0
    assert read_intersection(intersection_id)["priority_budget_sec"] == 0


def test_both_component_caps_and_the_final_cap_hold_across_three_shared_corridors():
    """One shared signal, three classes: 100.00, 80.00 and 64.00 from identical inputs.

    PRD §3.2: "The **age component** is the corridor's `avg_plan_age_days`
    divided by an age saturation of 1825 days — five years, the point past which
    additional staleness earns no more credit — capped at 1. The **volume
    component** is the absolute value of `annual_volume_change_pct` divided by a
    volume saturation of 25.0 percent, capped at 1. The **complaint component**
    is `complaint_count_12mo` divided by a complaint saturation of 20 complaints,
    capped at 1." ... "the product is capped at 1, multiplied by 100.0, and
    rounded half up to 2 decimal places. No component and no intermediate product
    is ever rounded on its own; the single rounding step is the last one."

    Design: Corner/calculations/component_saturation_caps_and_class_multiplier_with_the_final_min_cap
    """
    shared = create_intersection(location_name="Shared Junction @ Main")
    assert shared["timing_plan_age_days"] == NEVER_RETIMED_AGE_DAYS

    corridors = {}
    for key, jurisdiction_class in (("a", "ARTERIAL"), ("b", "COLLECTOR"),
                                    ("c", "LOCAL")):
        corridor = create_corridor(jurisdiction_class=jurisdiction_class,
                                   annual_volume_change_pct=400.0)
        enrol_member(corridor["id"], shared["id"], 1, distance_from_prev_ft=0)
        corridors[key] = corridor

    requester = create_requester()
    for category in ("COORDINATION", "COORDINATION", "PEDESTRIAN", "DETECTION",
                     "TIMING_OTHER"):
        file_complaint(requester["id"], corridors["a"]["id"], category=category,
                       narrative=f"A {category} complaint about this corridor.")

    arterial = screen_corridor(corridors["a"]["id"])
    assert float(arterial["avg_plan_age_days"]) == 3650.00
    assert arterial["complaint_count_12mo"] == 5
    # Raw is (0.45 + 0.35 + 0.20 * 0.25) * 1.25 == 1.0625, capped at 1.
    assert float(arterial["priority_score"]) == 100.00

    collector = screen_corridor(corridors["b"]["id"])
    # Complaints are scoped per corridor even though the member is shared.
    assert collector["complaint_count_12mo"] == 0
    # An age ratio of 2.0 and a volume ratio of 16.0 both clamp to 1.0.
    assert float(collector["priority_score"]) == 80.00

    local = screen_corridor(corridors["c"]["id"])
    assert float(local["priority_score"]) == 64.00


def test_the_pipeline_consumes_the_before_count_with_the_greatest_count_date():
    """A later, lighter count coordinates the corridor at 60 rather than the earlier 105.

    PRD §3.6: "Exactly one turning movement count per intersection feeds the
    pipeline, and which one is chosen is fully determined: among the counts for
    this project at this intersection with `study_role` `BEFORE`, take the one
    with the greatest `count_date`; if two share that `count_date`, take the one
    with the greatest `created_at`; if they still tie, prefer `PM_PEAK` over
    `AM_PEAK`, and `AM_PEAK` over `MID_DAY`. That count's
    `recommended_cycle_sec` — computed exactly as described in §3.4 for the count
    itself — is the intersection's ask." PRD §3.6: "Each phase's
    `effective_split_sec` is then the phase's `split_sec` multiplied by the
    plan's operating cycle length, divided by that drafted total, rounded half up
    to a **whole second** — each phase individually, before any summation."

    Design: Corner/calculations/recommended_cycle_uses_the_latest_before_count_not_the_first
    """
    ctx = setup_project_in_data_collection(intersections=[{"max_cycle_length_sec": 150}])
    project_id = ctx["project"]["id"]
    intersection_id = ctx["intersections"][0]["id"]

    early = record_count(intersection_id, project_id,
                         count_date="2026-07-10T00:00:00Z", period="AM_PEAK",
                         phase_volumes=MODERATE_VOLUMES)
    assert early["recommended_cycle_sec"] == 105

    late = record_count(intersection_id, project_id,
                        count_date="2026-07-20T00:00:00Z", period="AM_PEAK",
                        phase_volumes={"1": 200, "2": 200, "4": 200, "6": 200})
    assert float(late["critical_flow_ratio_sum"]) == 0.4444
    # 52.2 ceils to 55 and is then lifted to the 60-second floor.
    assert late["recommended_cycle_sec"] == 60

    record_run(project_id)
    advance_project(project_id)
    plan = draft_plan(project_id, intersection_id, cycle_length_sec=90,
                      coordination_ref="MASTER")
    add_splits(plan["id"], TWO_PHASE_SPLITS)

    coordinate_project(project_id)

    coordinated = read_plan(plan["id"])
    assert coordinated["cycle_length_sec"] == 60
    assert coordinated["drafted_cycle_length_sec"] == 90
    assert coordinated["effective_split_total_sec"] == 60
    assert effective_splits(plan["id"]) == {1: 30, 2: 30}
    # The unused count is not deleted, merely not selected.
    assert len(project_counts(project_id, study_role="BEFORE")) == 2
