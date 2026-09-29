"""The priority budget waterfall's two axes and the two performance-metric variants."""
from test_helpers import assert_priority_budget_invariant
from test_helpers.fixtures import (
    CANONICAL_PLAN,
    CANONICAL_SPLITS,
    approve_config,
    certify_evaluation,
    create_evaluation,
    deploy_config,
    field_tuning,
    propose_config,
    read_config,
    read_evaluation,
    read_intersection,
    record_run,
    set_clock,
    setup_canonical_implemented_project,
    setup_implemented_project,
    suspend_config,
)

CANONICAL = {"plan_overrides": dict(CANONICAL_PLAN), "splits": CANONICAL_SPLITS}

# One emergency-vehicle treatment asking for 15 of the intersection's 21
# budgeted seconds, so the grant is its own request rather than the remainder.
EVP_CONFIG = {
    "priority_type": "EVP",
    "requested_max_extension_sec": 15,
    "max_early_green_sec": 5,
    "conflict_resolution_rank": 1,
}


def _approved_evp_config():
    """An intersection running a deployed 105-second plan plus one APPROVED EVP row."""
    ctx = setup_canonical_implemented_project()
    intersection_id = ctx["intersections"][0]["id"]
    proposed = propose_config(intersection_id, **EVP_CONFIG)
    ctx["proposed"] = proposed
    ctx["config"] = approve_config(proposed["id"])
    ctx["intersection_id"] = intersection_id
    return ctx


def test_the_budget_is_a_floored_fifth_of_the_deployed_coordinated_cycle():
    """105 seconds of cycle buys 21 seconds of priority, and a proposal grants none of it.

    PRD §3.9: "An intersection's `priority_budget_sec` is one fifth — 20 percent
    — of its `deployed_coordinated_cycle_sec`, taken as a floor so the budget can
    never exceed the fraction, and it is 0 whenever no plan of the intersection
    is deployed and therefore no coordinated cycle exists." and "A new
    configuration starts with `approval_status` `PROPOSED`, `deployment_status`
    `NOT_DEPLOYED` and `granted_extension_sec` 0".

    Design: Difficulty/non_linear_state_machine/priority_config_deployment_axis_cycles_without_moving_approval_axis
    """
    ctx = _approved_evp_config()
    intersection = read_intersection(ctx["intersection_id"])
    assert intersection["deployed_coordinated_cycle_sec"] == 105
    assert intersection["priority_budget_sec"] == 21
    assert intersection["granted_priority_extension_total_sec"] == 0
    assert intersection["unallocated_priority_budget_sec"] == 21
    assert_priority_budget_invariant(intersection)

    assert ctx["proposed"]["approval_status"] == "PROPOSED"
    assert ctx["proposed"]["deployment_status"] == "NOT_DEPLOYED"
    assert ctx["proposed"]["granted_extension_sec"] == 0
    assert ctx["proposed"]["proposed_by_user_id"] == "timing-eng-1"


def test_approval_moves_the_approval_axis_and_leaves_the_deployment_axis_alone():
    """APPROVE writes an approver but the row is still NOT_DEPLOYED with a zero grant.

    PRD §3.9: "The approval axis moves `PROPOSED → APPROVED` or `PROPOSED →
    REJECTED` and never moves again — `REJECTED` is terminal — while the
    deployment axis moves `NOT_DEPLOYED → DEPLOYED`, `DEPLOYED → SUSPENDED` and
    `SUSPENDED → DEPLOYED` as operations require." and "An `APPROVE` writes the
    acting `X-User-ID` into `approved_by_user_id`".

    Design: Difficulty/non_linear_state_machine/priority_config_deployment_axis_cycles_without_moving_approval_axis
    """
    ctx = _approved_evp_config()
    approved = ctx["config"]

    assert approved["approval_status"] == "APPROVED"
    assert approved["deployment_status"] == "NOT_DEPLOYED"
    assert approved["granted_extension_sec"] == 0
    assert approved["approved_by_user_id"] == "cert-eng-1"
    assert approved["version"] == ctx["proposed"]["version"] + 1

    # Approval on its own hands out nothing: the waterfall only walks DEPLOYED rows.
    intersection = read_intersection(ctx["intersection_id"])
    assert intersection["granted_priority_extension_total_sec"] == 0
    assert intersection["unallocated_priority_budget_sec"] == 21


def test_deployment_grants_the_requested_seconds_without_touching_the_approval_axis():
    """The deploy moves only the second axis and the waterfall hands over 15 of 21 seconds.

    PRD §3.9: "The deployment axis may only leave `NOT_DEPLOYED` once the
    approval axis has reached `APPROVED`, but no deployment move ever changes
    `approval_status`." and "each configuration's `granted_extension_sec` is the
    smaller of its own `requested_max_extension_sec` and whatever remains of the
    budget" and "The intersection's `granted_priority_extension_total_sec` is the
    sum of the granted extensions, and its `unallocated_priority_budget_sec` is
    the budget minus that sum."

    Design: Difficulty/non_linear_state_machine/priority_config_deployment_axis_cycles_without_moving_approval_axis
    """
    ctx = _approved_evp_config()
    config_id = ctx["config"]["id"]

    deployed = deploy_config(config_id)
    assert deployed["deployment_status"] == "DEPLOYED"
    assert deployed["granted_extension_sec"] == 15
    # The approval axis is exactly where the approval left it.
    assert deployed["approval_status"] == "APPROVED"
    assert deployed["approved_by_user_id"] == "cert-eng-1"

    intersection = read_intersection(ctx["intersection_id"])
    assert intersection["priority_budget_sec"] == 21
    assert intersection["granted_priority_extension_total_sec"] == 15
    assert intersection["unallocated_priority_budget_sec"] == 6
    assert_priority_budget_invariant(intersection)


def test_the_deployment_axis_cycles_through_suspension_and_back():
    """NOT_DEPLOYED to DEPLOYED to SUSPENDED to DEPLOYED, with the grant swinging 15/0/15.

    PRD §3.9: "**Suspension** is deployment's compensation. It requires the
    deployment axis to be at `DEPLOYED` ... The configuration moves to
    `SUSPENDED` and its `granted_extension_sec` is zeroed; the waterfall is then
    re-run over the intersection's remaining deployed configurations, which is
    what returns the released seconds to whoever was starved before; the three
    intersection budget fields are recomputed". PRD §3.9 also pins the return
    leg: the deployment axis moves "`SUSPENDED → DEPLOYED` as operations
    require."

    Design: Difficulty/non_linear_state_machine/priority_config_deployment_axis_cycles_without_moving_approval_axis
    """
    ctx = _approved_evp_config()
    config_id = ctx["config"]["id"]
    intersection_id = ctx["intersection_id"]

    first = deploy_config(config_id)
    assert (first["deployment_status"], first["granted_extension_sec"]) == ("DEPLOYED", 15)

    suspended = suspend_config(config_id, reason="Fire station relocated for six weeks")
    assert suspended["deployment_status"] == "SUSPENDED"
    assert suspended["granted_extension_sec"] == 0
    assert suspended["approval_status"] == "APPROVED"

    released = read_intersection(intersection_id)
    assert released["granted_priority_extension_total_sec"] == 0
    assert released["unallocated_priority_budget_sec"] == 21
    assert_priority_budget_invariant(released)

    again = deploy_config(config_id)
    assert again["deployment_status"] == "DEPLOYED"
    assert again["granted_extension_sec"] == 15

    # Three deployment moves later the approval axis has still never moved.
    final = read_config(intersection_id, config_id)
    assert final["approval_status"] == "APPROVED"
    assert final["approved_by_user_id"] == "cert-eng-1"
    assert final["proposed_by_user_id"] == "timing-eng-1"
    restored = read_intersection(intersection_id)
    assert restored["granted_priority_extension_total_sec"] == 15
    assert restored["unallocated_priority_budget_sec"] == 6


# The before pair is 320 s over 12 arrivals northbound and 340 s over 18
# arrivals southbound; the two after runs straddle the tuning cutoff.
BEFORE_SB_RUN = {
    "study_role": "BEFORE", "direction": "SB",
    "started_at": "2026-07-15T09:00:00Z", "duration_sec": 340,
    "stops_count": 7, "arrivals_on_green_count": 3, "total_arrivals": 18,
}
AFTER_RUN_MID_TUNING = {
    "study_role": "AFTER", "direction": "NB",
    "started_at": "2026-08-05T09:00:00Z", "duration_sec": 260,
    "stops_count": 3, "arrivals_on_green_count": 8, "total_arrivals": 10,
}
AFTER_RUN_POST_TUNING = {
    "study_role": "AFTER", "direction": "NB",
    "started_at": "2026-08-06T09:00:00Z", "duration_sec": 250,
    "stops_count": 2, "arrivals_on_green_count": 9, "total_arrivals": 10,
}


def _project_with_one_evaluation():
    """Two BEFORE runs, one AFTER run each side of the tuning cutoff, one evaluation.

    The mid-tuning after run is stamped `recorded_at` 2026-08-05T10:00:00Z and
    the post-tuning one 2026-08-06T10:00:00Z, which is also the instant the
    tuning phase completed.
    """
    ctx = setup_implemented_project(**CANONICAL)
    project_id = ctx["project"]["id"]
    record_run(project_id, **BEFORE_SB_RUN)

    set_clock("2026-08-05T10:00:00Z")
    field_tuning(project_id, "START")
    ctx["mid_run"] = record_run(project_id, **AFTER_RUN_MID_TUNING)

    set_clock("2026-08-06T10:00:00Z")
    ctx["project"] = field_tuning(project_id, "COMPLETE")
    ctx["post_run"] = record_run(project_id, **AFTER_RUN_POST_TUNING)

    ctx["evaluation"] = create_evaluation(project_id)
    return ctx


def test_the_provisional_variant_takes_every_after_run_and_means_them_plainly():
    """Both after runs enter, unweighted, so the means are 330.00 and 255.00.

    PRD §3.10: "Under the **provisional variant**, every run with `study_role`
    `AFTER` is included regardless of when it was recorded, and a mean is the
    plain arithmetic mean: the sum of the runs' `duration_sec` divided by the
    number of runs, rounded half up to 2 decimal places." and "A new evaluation
    is `PROVISIONAL` with `metric_variant` `PROVISIONAL_UNWEIGHTED`". PRD §3.10:
    "`included_after_run_count` reports how many `AFTER` runs actually entered
    the computation under the active variant."

    Design: Difficulty/dual_variant_calc/performance_evaluation_provisional_unweighted_vs_certified_weighted_variants
    """
    ctx = _project_with_one_evaluation()
    evaluation = ctx["evaluation"]

    assert evaluation["status"] == "PROVISIONAL"
    assert evaluation["metric_variant"] == "PROVISIONAL_UNWEIGHTED"
    assert float(evaluation["mean_travel_time_before_sec"]) == 330.00
    assert float(evaluation["mean_travel_time_after_sec"]) == 255.00
    assert float(evaluation["delay_reduction_pct"]) == 22.73
    assert evaluation["total_stops_before"] == 12
    assert evaluation["total_stops_after"] == 5
    assert float(evaluation["stops_reduction_pct"]) == 58.33
    assert float(evaluation["aog_pct_before"]) == 23.33
    assert float(evaluation["aog_pct_after"]) == 85.00
    assert evaluation["included_after_run_count"] == 2


def test_certification_reweights_the_means_and_drops_the_pre_cutoff_run():
    """One request flips both axes at once: the inclusion set shrinks and the mean weights.

    PRD §3.10: "Under the **certified variant**, an `AFTER` run is included only
    when its `recorded_at` is at or after the project's
    `last_tuning_completed_at`, so runs invalidated by the last round of fine
    tuning are dropped from the after mean, from `total_stops_after` and from
    `aog_pct_after` alike; and a mean becomes an **arrivals-weighted** mean — the
    sum over the included runs of `duration_sec` multiplied by `total_arrivals`,
    divided by the sum of `total_arrivals`, rounded half up to 2 decimal places.
    The weighting applies to the `BEFORE` mean as well as the `AFTER` mean".
    PRD §3.10: "Certification sets `metric_variant` to `CERTIFIED_WEIGHTED`,
    **recomputes every metric field** under the certified variant rather than
    reusing the provisional numbers, sets `certified_by_user_id` to the acting
    `X-User-ID`, moves the evaluation `PROVISIONAL → CERTIFIED`".

    Design: Difficulty/dual_variant_calc/performance_evaluation_provisional_unweighted_vs_certified_weighted_variants
    """
    ctx = _project_with_one_evaluation()

    certified = certify_evaluation(ctx["evaluation"]["id"])
    assert certified["status"] == "CERTIFIED"
    assert certified["metric_variant"] == "CERTIFIED_WEIGHTED"
    assert certified["certified_by_user_id"] == "cert-eng-1"

    # (320*12 + 340*18) / 30 = 332.00, against the unweighted 330.00.
    assert float(certified["mean_travel_time_before_sec"]) == 332.00
    # Only the post-cutoff run survives, so its weighted mean is its own duration.
    assert float(certified["mean_travel_time_after_sec"]) == 250.00
    assert float(certified["delay_reduction_pct"]) == 24.70
    assert certified["included_after_run_count"] == 1


def test_the_two_variants_disagree_on_every_after_derived_number():
    """The same four stored runs give two different read-outs of the same retiming.

    PRD §3.10: "Identical run data therefore yields different certified numbers
    than provisional ones even when the two inclusion sets happen to coincide."
    PRD §3.10: "`total_stops_before` and `total_stops_after` are the sums of
    `stops_count` over the included before and after runs, and
    `stops_reduction_pct` is 100.0 multiplied by their difference divided by
    `total_stops_before`" and "`aog_pct_after` is the same quantity over the
    included after runs."

    Design: Difficulty/dual_variant_calc/performance_evaluation_provisional_unweighted_vs_certified_weighted_variants
    """
    ctx = _project_with_one_evaluation()
    project_id = ctx["project"]["id"]
    provisional = ctx["evaluation"]

    certified = certify_evaluation(provisional["id"])

    # The before side is never filtered, only reweighted.
    assert certified["total_stops_before"] == provisional["total_stops_before"] == 12
    assert float(certified["aog_pct_before"]) == float(provisional["aog_pct_before"]) == 23.33
    # The after side loses the mid-tuning run outright.
    assert certified["total_stops_after"] == 2
    assert float(certified["stops_reduction_pct"]) == 83.33
    assert float(certified["aog_pct_after"]) == 90.00
    assert certified["included_after_run_count"] == 1
    assert provisional["included_after_run_count"] == 2

    stored = read_evaluation(project_id, provisional["id"])
    assert stored["metric_variant"] == "CERTIFIED_WEIGHTED"
    assert float(stored["mean_travel_time_after_sec"]) == 250.00
    assert stored["version"] == provisional["version"] + 1
