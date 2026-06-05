"""SLA deadline variants and dual budget accountings (depth: dual_variant_calc,
combinatorial_formula).

Every test translates exactly one §1.8 difficulty instance.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    set_clock,
    create_service,
    create_responder,
    create_schedule,
    create_shift,
    create_policy,
    create_tier,
    setup_pageable_service,
    trigger_incident,
    acknowledge,
    resolve,
    TEST_USERS,
    WIDE_SHIFT_START,
    WIDE_SHIFT_END,
)

COMMANDER = TEST_USERS["incident_commander_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Difficulty/dual_variant_calc/sla_deadline_business_hours_vs_calendar
# ===========================================================================
def test_calendar_variant_ack_deadline_tier2_24x7():
    """PRD §3.5: "For a `TIER_2` or `TIER_3` service the *calendar* variant
    applies: the deadline is simply `triggered_at` plus the relevant minutes
    measured as 24/7 wall-clock minutes — the acknowledgement deadline is
    `triggered_at` plus the effective ack minutes, and the resolve deadline is
    `triggered_at` plus the base resolve minutes for the severity."

    A SEV2 (base ack 30 min) incident on a HEALTHY TIER_2 service triggered at
    00:00:00Z gets ack_deadline_at exactly 30 wall-clock minutes later.

    Design: Difficulty/dual_variant_calc/sla_deadline_business_hours_vs_calendar
    """
    set_clock("2026-06-01T00:00:00Z")
    # A pageable TIER_2 topology so the trigger's reachable-target check (PRD §3.2:
    # "If the policy has no tiers ... the trigger fails with ERR_NO_ESCALATION_TARGET")
    # is satisfied; the WIDE shift covers the 2026-06-01T00:00:00Z trigger clock.
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    assert inc["ack_deadline_at"] == "2026-06-01T00:30:00.000Z", (
        f"calendar SEV2 ack deadline should be +30 wall-clock minutes, "
        f"got {inc['ack_deadline_at']}"
    )


def test_business_hours_variant_ack_deadline_tier1_skips_offhours():
    """PRD §3.5: "For a `TIER_1` service the *business-hours* variant applies:
    only minutes that fall on Monday through Friday within the window from 09:00
    (inclusive) up to 17:00 (exclusive) UTC count toward the deadline. The server
    walks forward from `triggered_at`, consuming only business minutes, until the
    required number of minutes (the effective ack minutes for the ack deadline,
    the base resolve minutes for the resolve deadline) has been consumed; the
    wall-clock instant reached at that point is the deadline."

    A SEV2 incident on a TIER_1 service triggered Monday 00:00:00Z (before the
    09:00 business window) must consume its 30 business minutes starting at 09:00,
    landing ack_deadline_at at 09:30:00Z — strictly later than the calendar value.

    Design: Difficulty/dual_variant_calc/sla_deadline_business_hours_vs_calendar
    """
    set_clock("2026-06-01T00:00:00Z")  # Monday, before 09:00 UTC
    # A pageable TIER_1 topology so the trigger's reachable-target check (PRD §3.2)
    # passes; the WIDE shift covers the 2026-06-01T00:00:00Z trigger clock. The
    # business-hours SLA deadline computation (PRD §3.5) is independent of paging.
    env = setup_pageable_service(tier="TIER_1", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    assert inc["ack_deadline_at"] == "2026-06-01T09:30:00.000Z", (
        f"business-hours SEV2 ack deadline should be 09:30:00Z (30 business "
        f"minutes from 09:00), got {inc['ack_deadline_at']}"
    )


# ===========================================================================
# Difficulty/dual_variant_calc/budget_time_based_vs_event_based
# ===========================================================================
def test_budget_summary_time_based_consumed_minutes():
    """PRD §3.5: "For each incident on the service that is `RESOLVED` and whose
    `counts_against_budget` is true, the incident's `downtime_minutes` is the span
    from its `triggered_at` to its `resolved_at`, expressed in seconds, divided by
    60, rounded up to a whole minute."
    PRD §3.5: "The budget-summary read returns both side by side: `consumed_minutes`
    (the time-based total), `event_cost_minutes` (the event-based total),
    `remaining_minutes`, and `budget_status`."

    A single SEV2 incident open for 150 seconds (00:00:00 -> 00:02:30) yields a
    time-based consumed of ceil(150/60) = 3 minutes.

    Design: Difficulty/dual_variant_calc/budget_time_based_vs_event_based
    """
    set_clock("2026-06-01T00:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    acknowledge(inc["id"], env["responder"]["id"])
    set_clock("2026-06-01T00:02:30Z")
    resolve(inc["id"], env["responder"]["id"])

    summary = validate_success(
        api_client.get_budget_summary(env["service"]["id"], COMMANDER), 200
    )
    assert summary["consumed_minutes"] == 3, (
        f"time-based consumed should be ceil(150/60)=3, got {summary['consumed_minutes']}"
    )


def test_budget_summary_event_based_diverges_from_time_based():
    """PRD §3.5: "The event-based cost charges each `RESOLVED`, budget-counting
    incident a *fixed* number of minutes by severity regardless of its actual
    downtime: 60 minutes for `SEV1`, 30 for `SEV2`, 10 for `SEV3`, and 5 for
    `SEV4`."
    PRD §3.5: "Because it ignores actual downtime, this figure generally diverges
    from the time-based consumed number for the same incident set."

    The same single SEV2 incident open 150 seconds costs a fixed 30 event minutes,
    which differs from the time-based 3 minutes.

    Design: Difficulty/dual_variant_calc/budget_time_based_vs_event_based
    """
    set_clock("2026-06-01T00:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    acknowledge(inc["id"], env["responder"]["id"])
    set_clock("2026-06-01T00:02:30Z")
    resolve(inc["id"], env["responder"]["id"])

    summary = validate_success(
        api_client.get_budget_summary(env["service"]["id"], COMMANDER), 200
    )
    assert summary["event_cost_minutes"] == 30, (
        f"event-based cost for SEV2 should be a fixed 30, got {summary['event_cost_minutes']}"
    )
    assert summary["consumed_minutes"] != summary["event_cost_minutes"], (
        "event-based cost must diverge from the time-based consumed for this incident"
    )


# ===========================================================================
# Difficulty/combinatorial_formula/effective_sla_nonlinear_min_max_branch_on_posture
# ===========================================================================
def test_effective_ack_tightened_on_exhausted_service():
    """PRD §3.5: "If the service's `budget_status` is `EXHAUSTED`, multiply the
    base by a pressure factor of 0.5 and round the product up to a whole minute;
    if instead the `budget_status` is `WARNING`, multiply the base by 0.75 and
    round up to a whole minute; otherwise (a `HEALTHY` service) the tightened
    figure equals the base. The effective ack minutes are then the larger of an
    absolute floor of 5 minutes and the smaller of the base and the tightened
    figure."
    PRD §3.5: "This effective ack-minutes value — not the raw base — feeds the
    acknowledgement-deadline computation."

    On an EXHAUSTED service a SEV2 base of 30 tightens to ceil(30*0.5)=15, so a
    new SEV2 incident triggered at 00:01:30 gets ack_deadline_at at 00:16:30
    (15 minutes), not 00:31:30.

    Design: Difficulty/combinatorial_formula/effective_sla_nonlinear_min_max_branch_on_posture
    """
    set_clock("2026-06-01T00:00:00Z")
    # Budget of 2 minutes; first SEV2 incident open 90s -> consumed 2 -> EXHAUSTED.
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=2)
    first = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    acknowledge(first["id"], env["responder"]["id"])
    set_clock("2026-06-01T00:01:30Z")
    resolve(first["id"], env["responder"]["id"])
    svc = validate_success(api_client.get_service(env["service"]["id"], COMMANDER), 200)
    assert svc["budget_status"] == "EXHAUSTED", (
        f"service should be EXHAUSTED (consumed 2 >= budget 2), got {svc['budget_status']}"
    )

    # New SEV2 incident triggered at 00:01:30 on the now-EXHAUSTED service.
    second = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    assert second["ack_deadline_at"] == "2026-06-01T00:16:30.000Z", (
        f"effective ack should be 15 min (tightened from 30) from trigger 00:01:30, "
        f"got {second['ack_deadline_at']}"
    )


def test_effective_ack_unchanged_on_healthy_service():
    """PRD §3.5: "otherwise (a `HEALTHY` service) the tightened figure equals the
    base. The effective ack minutes are then the larger of an absolute floor of 5
    minutes and the smaller of the base and the tightened figure."

    On a HEALTHY service the tightened figure equals the base, so a SEV2 incident
    triggered at 00:00:00 gets the full 30-minute ack window (00:30:00) — the
    complement branch of the budget-posture min/max formula.

    Design: Difficulty/combinatorial_formula/effective_sla_nonlinear_min_max_branch_on_posture
    """
    set_clock("2026-06-01T00:00:00Z")
    # A pageable HEALTHY TIER_2 topology so the trigger's reachable-target check
    # (PRD §3.2) passes; the WIDE shift covers the 2026-06-01T00:00:00Z clock.
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    assert inc["ack_deadline_at"] == "2026-06-01T00:30:00.000Z", (
        f"HEALTHY service SEV2 ack should equal the full base 30 min, "
        f"got {inc['ack_deadline_at']}"
    )


# ===========================================================================
# Difficulty/combinatorial_formula/budget_consumed_round_per_incident_then_sum
# ===========================================================================
def test_per_incident_downtime_ceiling_each_is_two_minutes():
    """PRD §3.5: "the incident's `downtime_minutes` is the span from its
    `triggered_at` to its `resolved_at`, expressed in seconds, divided by 60,
    rounded up to a whole minute."

    Each of two incidents open exactly 90 seconds rounds up to ceil(90/60) = 2
    downtime minutes individually.

    Design: Difficulty/combinatorial_formula/budget_consumed_round_per_incident_then_sum
    """
    set_clock("2026-06-01T00:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    sid, pid, rid = env["service"]["id"], env["policy"]["id"], env["responder"]["id"]

    inc_a = trigger_incident(sid, pid, severity="SEV4")
    acknowledge(inc_a["id"], rid)
    set_clock("2026-06-01T00:01:30Z")
    inc_a = resolve(inc_a["id"], rid)
    assert inc_a["downtime_minutes"] == 2, (
        f"90s downtime should ceil to 2 minutes, got {inc_a['downtime_minutes']}"
    )


def test_round_per_incident_then_sum_yields_four_not_three():
    """PRD §3.5: "The service's `error_budget_consumed_minutes` is the sum of
    those per-incident `downtime_minutes` over that set, with the per-incident
    ceiling applied to each incident *before* summing."
    PRD §2.9: "Per-incident downtime is rounded up to a whole minute (ceiling)
    *before* any summation; the platform never sums seconds first and rounds
    afterward."

    Two SEV4 incidents each open 90 seconds give ceil(90/60)+ceil(90/60)=2+2=4,
    not ceil(180/60)=3.

    Design: Difficulty/combinatorial_formula/budget_consumed_round_per_incident_then_sum
    """
    set_clock("2026-06-01T00:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    sid, pid, rid = env["service"]["id"], env["policy"]["id"], env["responder"]["id"]

    inc_a = trigger_incident(sid, pid, severity="SEV4")
    acknowledge(inc_a["id"], rid)
    set_clock("2026-06-01T00:01:30Z")
    resolve(inc_a["id"], rid)

    inc_b = trigger_incident(sid, pid, severity="SEV4")
    acknowledge(inc_b["id"], rid)
    set_clock("2026-06-01T00:03:00Z")
    resolve(inc_b["id"], rid)

    svc = validate_success(api_client.get_service(sid, COMMANDER), 200)
    assert svc["error_budget_consumed_minutes"] == 4, (
        f"round-per-incident-then-sum should give 4 (2+2), got "
        f"{svc['error_budget_consumed_minutes']}"
    )
