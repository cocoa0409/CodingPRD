"""Dynamic load balancing: PROPORTIONAL vs PRIORITY allocation, demand-charge
avoidance cap, power conservation on suspend, and manual rebalance.

Queue A (Difficulty): dual_variant_calc (allocation) and compensating_invariant
(power conservation) on site_load_allocation.
Queue B (Corner): demand-avoidance cap and the manual rebalance snapshot.
"""
from test_helpers import (
    validate_success,
    setup_charging_pool,
    make_driver_headers,
    assert_load_allocation,
    TEST_USERS,
)

CPO = TEST_USERS["cpo_headers"]
STATION = TEST_USERS["station_headers"]


def _get_session(api, env, sess):
    did = env["driver"]["id"]
    return validate_success(api.get_session(sess["id"], make_driver_headers(did)),
                            expected_status=200)


def test_proportional_allocation_splits_pool_pro_rata(api):
    """PRD §3.4: "Otherwise the cap is split pro rata: each candidate's raw share is
    the cap multiplied by that candidate's request divided by the total demand, and
    each raw share is then truncated downward to a whole multiple of 0.1 kW."

    Design: Difficulty/dual_variant_calc/load_allocation_proportional_vs_priority_same_pool
    """
    env = setup_charging_pool(
        circuit_limit_kw=100, allocation_policy="PROPORTIONAL",
        stalls=[{"max_power_kw": 60}, {"max_power_kw": 60}, {"max_power_kw": 30}],
    )
    a, b, c = env["sessions"]
    # requests 60/60/30, sum 150 > cap 100 -> 100*60/150=40.0, 40.0, 100*30/150=20.0
    assert _get_session(api, env, a)["allocated_power_kw"] == 40.0, "A gets 40.0 kW pro rata"
    assert _get_session(api, env, b)["allocated_power_kw"] == 40.0, "B gets 40.0 kW pro rata"
    assert _get_session(api, env, c)["allocated_power_kw"] == 20.0, "C gets 20.0 kW pro rata"
    site = validate_success(api.get_site(env["site"]["id"], CPO), expected_status=200)
    assert site["allocated_total_kw"] == 100.0, "site allocated_total_kw == 100.0 (full cap)"


def test_priority_allocation_waterfall_starves_lowest(api):
    """PRD §3.4: "Under the `PRIORITY` policy the cap is filled by a strict
    waterfall: candidates are sorted by ascending stall `reservation_priority` and
    then ascending `created_at`, and each in turn is granted the smaller of its
    request and the power still remaining, with the remaining budget reduced by each
    grant. A lower-priority candidate may therefore receive zero kilowatts".

    Design: Difficulty/dual_variant_calc/load_allocation_proportional_vs_priority_same_pool
    """
    env = setup_charging_pool(
        circuit_limit_kw=100, allocation_policy="PRIORITY",
        stalls=[{"max_power_kw": 60, "reservation_priority": 1},
                {"max_power_kw": 60, "reservation_priority": 2},
                {"max_power_kw": 30, "reservation_priority": 3}],
    )
    a, b, c = env["sessions"]
    # cap 100: A(prio1)=min(60,100)=60, remaining 40; B(prio2)=min(60,40)=40, remaining 0;
    # C(prio3)=min(30,0)=0 -> 60/40/0, distinct from PROPORTIONAL's 40/40/20
    assert _get_session(api, env, a)["allocated_power_kw"] == 60.0, "A (prio1) fully satisfied"
    assert _get_session(api, env, b)["allocated_power_kw"] == 40.0, "B (prio2) gets remaining 40"
    assert _get_session(api, env, c)["allocated_power_kw"] == 0.0, "C (prio3) starved to 0"


def test_priority_allocation_with_demand_avoidance_cap(api):
    """PRD §3.4: "The run begins by choosing the cap: it is the site's
    `demand_charge_threshold_kw` when `demand_avoidance_armed` is true, and the
    site's `circuit_limit_kw` otherwise."

    Design: Corner/calculations/priority_allocation_with_demand_avoidance_cap
    """
    env = setup_charging_pool(
        circuit_limit_kw=100, demand_charge_threshold_kw=60, demand_avoidance_armed=True,
        allocation_policy="PRIORITY",
        stalls=[{"max_power_kw": 60, "reservation_priority": 1},
                {"max_power_kw": 60, "reservation_priority": 2}],
    )
    a, b = env["sessions"]
    # cap = demand threshold 60 (not circuit 100): A(prio1)=60, B(prio2)=0
    assert _get_session(api, env, a)["allocated_power_kw"] == 60.0, "A fully satisfied at 60 kW cap"
    assert _get_session(api, env, b)["allocated_power_kw"] == 0.0, "B starved by the demand cap"
    site = validate_success(api.get_site(env["site"]["id"], CPO), expected_status=200)
    assert site["allocated_total_kw"] == 60.0, "allocated_total_kw == demand cap 60, below circuit 100"


def test_site_power_conserved_on_suspend_release(api):
    """PRD §3.6: "suspension sets `allocated_power_kw` to 0, re-runs load balancing
    with trigger reason `SESSION_SUSPEND` so the freed power is redistributed to the
    remaining charging sessions, recomputes the site's `allocated_total_kw`".
    PRD §3.4: "Under either policy the sum of the allocations never exceeds the cap".

    Design: Difficulty/compensating_invariant/site_power_conservation_on_suspend_release
    """
    env = setup_charging_pool(
        circuit_limit_kw=60, allocation_policy="PRIORITY",
        stalls=[{"max_power_kw": 60, "reservation_priority": 1},
                {"max_power_kw": 60, "reservation_priority": 2}],
    )
    a, b = env["sessions"]
    did = env["driver"]["id"]
    # Before suspend: A=60, B=0. Suspend A -> A releases 60, B gains the freed 60.
    suspended = validate_success(api.suspend_session(a["id"], STATION), expected_status=200)
    assert suspended["allocated_power_kw"] == 0.0, "suspended session releases its kW"
    assert _get_session(api, env, b)["allocated_power_kw"] == 60.0, "B receives the freed 60 kW"
    site = validate_success(api.get_site(env["site"]["id"], CPO), expected_status=200)
    assert site["allocated_total_kw"] == 60.0, (
        "allocated_total_kw == sum of CHARGING allocations, still <= cap 60; no kW leaked"
    )


def test_site_power_conserved_across_suspend_in_proportional_pool(api):
    """PRD §3.1: "`allocated_total_kw`, the sum of `allocated_power_kw` across the
    site's sessions whose `charging_status` is `CHARGING`, recomputed on every
    load-balance run". PRD §3.4: "Under either policy the sum of the allocations
    never exceeds the cap".

    Design: Difficulty/compensating_invariant/site_power_conservation_on_suspend_release
    """
    env = setup_charging_pool(
        circuit_limit_kw=100, allocation_policy="PROPORTIONAL",
        stalls=[{"max_power_kw": 60}, {"max_power_kw": 60}, {"max_power_kw": 30}],
    )
    a, b, c = env["sessions"]
    did = env["driver"]["id"]
    # Initial 40/40/20 = 100 at cap. Suspend C (was 20); remaining demand 60+60=120 > 100,
    # so the two survivors re-split the full 100 (50/50). Conservation: total stays 100.
    suspended = validate_success(api.suspend_session(c["id"], STATION), expected_status=200)
    assert suspended["allocated_power_kw"] == 0.0, "suspended C releases its kW"
    alloc_a = _get_session(api, env, a)["allocated_power_kw"]
    alloc_b = _get_session(api, env, b)["allocated_power_kw"]
    site = validate_success(api.get_site(env["site"]["id"], CPO), expected_status=200)
    assert site["allocated_total_kw"] == round(alloc_a + alloc_b, 1), (
        "allocated_total_kw equals the sum of remaining CHARGING allocations"
    )
    assert site["allocated_total_kw"] == 100.0, (
        "freed power redistributed; total stays at the 100 kW cap, none leaked"
    )


def test_rebalance_endpoint_recomputes_allocations(api):
    """PRD §3.4: "Each run produces a **LoadAllocation** snapshot recording the
    `site_id` it covers, the `trigger_reason` (one of `SESSION_START`, `SESSION_STOP`,
    `SESSION_SUSPEND`, or `MANUAL_REBALANCE`), the `policy_used` (`PROPORTIONAL` or
    `PRIORITY`), the ceiling `cap_kw` enforced for the run, the `allocated_total_kw`
    actually distributed, and the `session_count` of charging sessions that received
    an allocation."

    Design: Corner/endpoints/rebalance_endpoint_recomputes_allocations
    """
    env = setup_charging_pool(
        circuit_limit_kw=200, allocation_policy="PRIORITY",
        stalls=[{"max_power_kw": 60}],
    )
    resp = api.rebalance_site(env["site"]["id"], CPO)
    data = validate_success(resp, expected_status=200)
    assert_load_allocation(data)
    assert data["trigger_reason"] == "MANUAL_REBALANCE", "manual rebalance trigger_reason"
    assert data["allocated_total_kw"] == 60.0, "single CHARGING session gets 60 kW"
    assert data["session_count"] == 1, "one CHARGING session received an allocation"
