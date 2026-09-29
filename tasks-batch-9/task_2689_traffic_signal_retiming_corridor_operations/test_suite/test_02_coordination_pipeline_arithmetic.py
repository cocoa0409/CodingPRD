"""The corridor coordination pipeline: cycle propagation, split rescaling, offsets, pedestrians."""
from test_helpers import ApiErrorId, api_client, validate_error
from test_helpers.fixtures import (
    CANONICAL_PLAN,
    CANONICAL_SPLITS_TWO_PHASE,
    ENGINEER,
    add_splits,
    coordinate_project,
    draft_plan,
    read_plan,
    read_ped_checks,
    read_splits,
    setup_canonical_coordinated_plan,
    setup_project_in_plan_development,
    submit_plan,
)

# The canonical four-phase plan with a second pedestrian phase whose provided
# pedestrian change interval sits exactly one tenth of a second below the
# requirement its 62.0 ft crossing generates.
STRADDLE_SPLITS = [
    {"phase_number": 1, "split_sec": 21, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 2, "split_sec": 21, "min_green_sec": 15,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 4, "split_sec": 22, "min_green_sec": 12,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0, "is_pedestrian_phase": True,
     "walk_sec": 4.0, "ped_clear_sec": 17.8, "crosswalk_length_ft": 62.0},
    {"phase_number": 6, "split_sec": 22, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0, "is_pedestrian_phase": True,
     "walk_sec": 4.0, "ped_clear_sec": 17.7, "crosswalk_length_ft": 62.0},
]


def test_split_rescale_rounds_each_phase_and_then_moves_one_second():
    """Drafted splits 21/21/22/22 at cycle 105 land on 26/25/27/27, not on any alternative.

    PRD §3.6: "Each phase's `effective_split_sec` is then the phase's `split_sec`
    multiplied by the plan's operating cycle length, divided by that drafted
    total, rounded half up to a **whole second** — each phase individually,
    before any summation." and "That single residual is added to exactly one
    phase: the phase with the greatest `min_green_sec`, and if several tie on
    that, the one with the lowest `phase_number`." The four unrounded values are
    25.6395/25.6395/26.8605/26.8605, which round to 26/26/27/27 summing to 106,
    so the residual of -1 lands on phase 2 alone.

    Design: Difficulty/combinatorial_formula/split_rescale_round_each_phase_then_apply_single_residual
    """
    ctx = setup_canonical_coordinated_plan()
    plan = ctx["plan"]
    assert plan["cycle_length_sec"] == 105
    assert plan["drafted_split_total_sec"] == 86

    splits = read_splits(plan["id"])
    assert [s["phase_number"] for s in splits] == [1, 2, 4, 6]
    effective = {s["phase_number"]: s["effective_split_sec"] for s in splits}
    assert effective == {1: 26, 2: 25, 4: 27, 6: 27}
    # Phase 2 alone absorbed the residual; its unadjusted rounded value was 26.
    assert effective[2] == 25
    assert sum(effective.values()) == 105


def test_effective_split_total_equals_the_operating_cycle_exactly():
    """A two-phase plan rescales to 53/52 and the totals close on the cycle with no drift.

    PRD §3.6: "After the residual is applied, the plan's
    `effective_split_total_sec` is the sum of the phases' effective splits, which
    now equals the plan's `cycle_length_sec` exactly." PRD §3.6 also pins
    "`drafted_cycle_length_sec` is deliberately left alone". Two 21-second
    phases against a drafted total of 42 both scale to 52.5, both round half up
    to 53 for a sum of 106, so the -1 residual goes to phase 2, which holds the
    greater `min_green_sec` of 15.

    Design: Difficulty/combinatorial_formula/split_rescale_round_each_phase_then_apply_single_residual
    """
    ctx = setup_canonical_coordinated_plan(splits=CANONICAL_SPLITS_TWO_PHASE)
    plan = ctx["plan"]

    assert plan["cycle_length_sec"] == 105
    assert plan["drafted_cycle_length_sec"] == 90
    assert plan["drafted_split_total_sec"] == 42
    assert plan["effective_split_total_sec"] == 105

    effective = {s["phase_number"]: s["effective_split_sec"] for s in read_splits(plan["id"])}
    assert effective == {1: 53, 2: 52}


def test_pedestrian_verdict_is_measured_against_the_rescaled_split():
    """Phase 4 passes only because the check reads its post-rescale 27-second split.

    PRD §3.6: "one request by the project's `TimingEngineer` takes every `DRAFT`
    plan of the project `DRAFT → COORDINATED`, and along the way it computes
    recommended cycles, the corridor's coordinated cycle, the rescaled splits,
    the progression offsets and the pedestrian compliance verdict — **in that
    order, which is pinned**. Evaluating pedestrian minimums before the splits
    have been rescaled would compare them against drafted rather than operating
    splits and can flip a verdict from failing to passing". PRD §3.7:
    "`provided_phase_length_sec` snapshots its `effective_split_sec` — the
    **post-rescale** operating split, never the drafted one."

    Design: Difficulty/combinatorial_formula/coordinate_pipeline_step3_then_step4_then_step6_order_flips_ped_result
    """
    ctx = setup_canonical_coordinated_plan()
    plan = read_plan(ctx["plan"]["id"])
    assert plan["status"] == "COORDINATED"
    assert plan["cycle_length_sec"] == 105

    checks = read_ped_checks(plan["id"])
    # Only phase 4 serves a crossing, so phases 1, 2 and 6 mint no check at all.
    assert len(checks) == 1
    check = checks[0]
    assert check["phase_number"] == 4
    assert float(check["walking_speed_fps"]) == 3.5
    assert float(check["required_ped_clear_sec"]) == 17.8
    assert float(check["provided_ped_clear_sec"]) == 17.8
    assert float(check["required_walk_sec"]) == 4.0
    assert float(check["required_phase_length_sec"]) == 25.8
    # The drafted split was 22 and a drafted-cycle rescale would have given 23.
    assert float(check["provided_phase_length_sec"]) == 27
    assert check["result"] == "PASS"
    assert check["failure_reason"] is None
    assert plan["ped_compliance_state"] == "COMPLIANT"


def test_cycle_overwrite_precedes_rescale_which_precedes_the_pedestrian_step():
    """The three pinned steps are each separately observable on one coordinated plan.

    PRD §3.6: "every `DRAFT` plan whose `coordination_ref` is `MASTER` has its
    `cycle_length_sec` overwritten with that coordinated value.
    `drafted_cycle_length_sec` is deliberately left alone". PRD §3.6 also pins
    the vacuous case: `ped_compliance_state` is "`COMPLIANT` when every
    compliance check the pipeline created for that plan came out passing — which
    includes the case of a plan with no pedestrian phases at all, for which no
    checks are created and the condition holds vacuously".

    Design: Difficulty/combinatorial_formula/coordinate_pipeline_step3_then_step4_then_step6_order_flips_ped_result
    """
    ctx = setup_canonical_coordinated_plan()
    plan = ctx["plan"]
    split_by_phase = {s["phase_number"]: s for s in read_splits(plan["id"])}
    check = read_ped_checks(plan["id"])[0]

    # Step 3 ran: the drafted 90 was overwritten by the coordinated 105.
    assert plan["cycle_length_sec"] == 105
    assert plan["drafted_cycle_length_sec"] == 90
    # Step 4 ran against the overwritten cycle, not the drafted one.
    assert plan["effective_split_total_sec"] == 105
    assert split_by_phase[4]["split_sec"] == 22
    assert split_by_phase[4]["effective_split_sec"] == 27
    # Step 6 snapshotted what step 4 produced.
    assert float(check["provided_phase_length_sec"]) == float(
        split_by_phase[4]["effective_split_sec"]
    )

    # A plan with no pedestrian phase at all is compliant with zero check rows.
    plain = setup_canonical_coordinated_plan(splits=CANONICAL_SPLITS_TWO_PHASE)
    assert read_ped_checks(plain["plan"]["id"]) == []
    assert plain["plan"]["ped_compliance_state"] == "COMPLIANT"


def test_pedestrian_clearance_equality_passes_and_a_tenth_below_fails():
    """62.0 ft at 3.5 fps ceilings to 17.8, which 17.8 satisfies and 17.7 misses.

    PRD §3.7: "`required_ped_clear_sec` is the crossing distance
    `crosswalk_length_ft` divided by that walking speed, raised **up** to the
    next tenth of a second". PRD §3.7: "If the provided pedestrian change
    interval is less than the required one, the `result` is `FAIL` with
    `failure_reason` `PED_CLEAR_SHORT`." and "Every one of the three comparisons
    treats equality as satisfactory: a provided value exactly equal to its
    requirement passes." The quotient is 17.714285..., so a rounding
    implementation would produce 17.7 and let phase 6 through.

    Design: Difficulty/boundary_precision_check/pedestrian_clearance_tenth_of_a_second_equality_passes_one_tenth_below_fails
    """
    ctx = setup_canonical_coordinated_plan(splits=STRADDLE_SPLITS)
    checks = read_ped_checks(ctx["plan"]["id"])

    assert [c["phase_number"] for c in checks] == [4, 6]
    passing, failing = checks[0], checks[1]

    assert float(passing["walking_speed_fps"]) == 3.5
    assert float(passing["required_ped_clear_sec"]) == 17.8
    assert float(passing["required_walk_sec"]) == 4.0
    assert float(passing["required_phase_length_sec"]) == 25.8
    assert float(passing["provided_ped_clear_sec"]) == 17.8
    assert float(passing["provided_phase_length_sec"]) == 27
    assert passing["result"] == "PASS"
    assert passing["failure_reason"] is None

    assert float(failing["required_ped_clear_sec"]) == 17.8
    assert float(failing["provided_ped_clear_sec"]) == 17.7
    assert float(failing["provided_phase_length_sec"]) == 27
    assert failing["result"] == "FAIL"
    # The provided 27 clears the required 25.8, so only the first sub-check bites.
    assert failing["failure_reason"] == "PED_CLEAR_SHORT"


def test_one_failing_pedestrian_check_blocks_submission_but_not_coordination():
    """The plan still reaches COORDINATED, and only the submission is refused.

    PRD §3.6: "`NON_COMPLIANT` when at least one came out failing. Finally each
    plan's `status` becomes `COORDINATED`". PRD §3.8: "Its
    `ped_compliance_state` must be `COMPLIANT` or `WAIVED`; a plan still
    `PENDING` or still `NON_COMPLIANT` is refused with
    `ERR_PED_CLEARANCE_INSUFFICIENT`."

    Design: Difficulty/boundary_precision_check/pedestrian_clearance_tenth_of_a_second_equality_passes_one_tenth_below_fails
    """
    ctx = setup_canonical_coordinated_plan(splits=STRADDLE_SPLITS)
    plan = ctx["plan"]
    assert plan["status"] == "COORDINATED"
    assert plan["ped_compliance_state"] == "NON_COMPLIANT"

    validate_error(
        api_client.submit_timing_plan(plan["id"], ENGINEER),
        ApiErrorId.ERR_PED_CLEARANCE_INSUFFICIENT.value,
    )

    after = read_plan(plan["id"])
    assert after["status"] == "COORDINATED"
    assert after["ped_compliance_state"] == "NON_COMPLIANT"


def _four_plans_over_two_intersections():
    """Two READY members, four DRAFT plans, one coordination run.

    Plans A [360, 540) and B [500, 700) sit on member 1; plans D [360, 540) and
    E [540, 700) sit on member 2.
    """
    ctx = setup_project_in_plan_development(
        intersections=[{}, {}], distances=[0, 2640]
    )
    project_id = ctx["project"]["id"]
    i1, i2 = ctx["intersections"][0]["id"], ctx["intersections"][1]["id"]
    windows = [
        ("a", i1, "AM_PEAK", 360, 540),
        ("b", i1, "MID_DAY", 500, 700),
        ("d", i2, "AM_PEAK", 360, 540),
        ("e", i2, "PM_PEAK", 540, 700),
    ]
    plans = {}
    for key, intersection_id, period, start, end in windows:
        plan = draft_plan(project_id, intersection_id, tod_period=period,
                          tod_start_min=start, tod_end_min=end, **CANONICAL_PLAN)
        add_splits(plan["id"], CANONICAL_SPLITS_TWO_PHASE)
        plans[key] = plan
    coordinate_project(project_id)
    ctx["plans_by_key"] = {k: read_plan(v["id"]) for k, v in plans.items()}
    return ctx


def test_overlapping_windows_on_one_intersection_are_refused():
    """[500, 700) intersects [360, 540) at the same intersection, so the submit fails.

    PRD §3.8: "The plan's window runs from `tod_start_min` inclusive to
    `tod_end_min` exclusive, and it is compared against the window of every
    *other* plan on the same `intersection_id` whose status is `COORDINATED`,
    `SUBMITTED`, `CERTIFIED` or `DEPLOYED`. Any intersection of those two
    half-open ranges is refused with `ERR_TOD_WINDOW_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/timing_plan_tod_windows_half_open_zero_buffer_per_intersection
    """
    ctx = _four_plans_over_two_intersections()
    plans = ctx["plans_by_key"]

    # The pipeline left both plans on member 1 in COORDINATED, which is one of the
    # four statuses the overlap rule compares against, so A's [360, 540) is already
    # a live window that B's [500, 700) intersects.
    coordinated_a = read_plan(plans["a"]["id"])
    assert coordinated_a["status"] == "COORDINATED"
    assert coordinated_a["cycle_length_sec"] == 105
    assert coordinated_a["offset_sec"] == 0

    validate_error(
        api_client.submit_timing_plan(plans["b"]["id"], ENGINEER),
        ApiErrorId.ERR_TOD_WINDOW_OVERLAP.value,
    )
    # The refused submission left the plan exactly where the pipeline put it.
    assert read_plan(plans["b"]["id"])["status"] == "COORDINATED"


def test_adjacent_windows_are_permitted_and_the_resource_key_is_the_intersection():
    """One window ending where the next begins is fine, and other intersections never collide.

    PRD §3.8: "but adjacency is explicitly fine — one plan ending at minute 540
    and another starting at minute 540 do not overlap, and no separation is
    required between them." PRD §3.6 pins the offsets these two plans carry:
    "Divide that cumulative distance in feet by a progression speed of 44.0 feet
    per second (30 miles per hour) to get a cumulative travel time in seconds,
    round that half up to a whole second, and only then take the remainder of
    dividing it by the plan's `cycle_length_sec`."

    Design: Difficulty/resource_temporal_overlap/timing_plan_tod_windows_half_open_zero_buffer_per_intersection
    """
    ctx = _four_plans_over_two_intersections()
    plans = ctx["plans_by_key"]

    first = submit_plan(plans["d"]["id"])
    assert first["status"] == "SUBMITTED"
    assert first["offset_sec"] == 60

    # D ends at minute 540 and E starts at minute 540, and E's [540, 700) also
    # overlaps B's [500, 700) on the other intersection.
    second = submit_plan(plans["e"]["id"])
    assert second["status"] == "SUBMITTED"
    assert second["offset_sec"] == 60

    assert read_plan(plans["b"]["id"])["status"] == "COORDINATED"
