"""Difficulty-design coverage (mandatory priority queue).

This file dedicates at least two tests to every difficulty-design
instance. Each test cites the PRD prose that states the underlying rule,
not the difficulty-design entry itself (PRD-first principle).

Coverage map:
  - dual_variant_calc:
      cleaning_task_priority_original_vs_rework
      housekeeper_workload_provisional_vs_realized
  - combinatorial_formula:
      priority_score_synergy_multiplier_mode_a
      minibar_charge_sum_then_round_mode_b
  - non_linear_state_machine:
      cleaning_task_submitted_branching
      minibar_consumption_investigated_branching
  - transitive_cascade:
      dispatch_isolate_room_triple_hop
      inspect_fail_rework_chain_depth_two
  - priority_pair_validation_conflict:
      state_vs_business_safety_dispatch_already_dispatched_on_isolated_room
      state_vs_business_referential_accept_completed_task_by_nonassignee
  - boundary_precision_check:
      linen_scheduled_replacement_at_exact_interval
      priority_tier_threshold_at_exact_urgent_boundary
  - cross_entity_state_dependency:
      cleaning_task_dispatch_requires_housekeeper_on_shift
      maintenance_dispatch_requires_room_not_already_isolated
  - resource_temporal_overlap:
      room_isolation_exclusive_capacity_one
      minibar_dispute_window_half_open_temporal
  - compensating_invariant:
      minibar_waiver_net_zero_folio_invariant
      linen_unit_conservation_invariant
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    MINIBAR_DISPUTE_WINDOW_HOURS,
    MINUTES_PER_DAY,
    MINUTES_PER_HOUR,
    TEST_DEFAULTS,
    TEST_USERS,
    create_linen_movement_payload,
    dispatch_maintenance_ticket_payload,
    dispute_minibar_payload,
    inspect_cleaning_task_payload,
    laundry_return_payload,
    make_housekeeper_headers,
    resolve_minibar_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    advance_clock,
    create_cleaning_task,
    create_housekeeper,
    create_housekeeper_on_shift,
    create_linen_movement,
    create_linen_type,
    create_maintenance_ticket,
    create_minibar_item,
    create_room,
    dispatch_ticket,
    drive_consumption_to_state,
    drive_task_to_state,
    drive_ticket_through_repair,
    early_check_in_within_window_iso,
    handover_linen,
    list_audit_entries_for_subject,
    post_consumption,
    setup_consumption_two_25c_items,
    setup_high_priority_task_inputs,
    setup_linen_movement_at_handover,
    setup_room_and_housekeeper,
    setup_room_hk_task,
    setup_room_isolated_by_ticket,
    setup_task_in_state,
    unique_code,
    unique_zone,
)


# ===========================================================================
# dual_variant_calc / cleaning_task_priority_original_vs_rework
# ===========================================================================
def test_dual_variant_priority_original_vs_rework(api):
    """# difficulty: dual_variant_calc/cleaning_task_priority_original_vs_rework

    PRD §3.5: "Original (non-rework) tasks pass task_source straight
    into the formula; rework tasks always carry expedite_flag true
    because that field is forced at auto-creation, which can lift a
    task from HIGH to URGENT purely on the rework path even if the
    underlying inputs would not otherwise have done so."

    PRD §3.3: "auto-creates a rework task whose parent_task_id is the
    failed task's id, whose task_source is the failed task's original
    task_source, and whose expedite_flag is forced to true."

    Claim: an original SCHEDULED task with vip=true + early-check-in
    (no expedite) scores base 20 + vip 30 + early 25 = 75 (HIGH); its
    rework, with forced expedite=true, gets all three bonuses and
    synergy: 20 + round_half_up((30+20+25)*1.20) = 110 (URGENT).
    """
    room, hk = setup_room_and_housekeeper(vip_flag=True)
    eci = early_check_in_within_window_iso(1.0)
    # Original: SCHEDULED, expedite=false, vip=true, early-in-window.
    # Base 20 + vip 30 + expedite 0 + early 25 = 75 (HIGH) — no synergy
    # because expedite_bonus is 0.
    t_orig = create_cleaning_task(
        room_id=room["id"], task_source="SCHEDULED",
        expedite_flag=False, early_check_in_at=eci,
    )
    assert t_orig["priority_score"] == 75
    assert t_orig["priority_tier"] == "HIGH"
    # Drive original to SUBMITTED then FAIL inspection.
    t_orig = drive_task_to_state(
        t_orig, hk["id"], target="SUBMITTED",
        clock_advance_minutes_between_start_submit=10,
    )
    api.inspect_cleaning_task(
        t_orig["id"],
        inspect_cleaning_task_payload(outcome="FAIL"),
        TEST_USERS["supervisor_headers"],
    )
    # Locate rework task by parent_task_id on this room.
    tlist = api.list_cleaning_tasks(
        TEST_USERS["supervisor_headers"],
        params={"room_id": room["id"]},
    )
    tasks, _ = validate_paginated(tlist)
    rework = [t for t in tasks if t.get("parent_task_id") == t_orig["id"]]
    assert len(rework) == 1
    r = rework[0]
    assert r["expedite_flag"] is True
    assert r["task_source"] == "SCHEDULED"
    # Rework keeps the early_check_in_at copied through (PRD §3.3
    # rework auto-creation), so all three bonuses fire with synergy:
    # 20 + round_half_up((30+20+25)*1.20) = 110 → URGENT.
    assert r["priority_score"] == 110, (
        "PRD §3.5 + §3.3 rework path: expedite forced to true brings "
        "the third bonus, activating synergy. Score 20+90=110."
    )
    assert r["priority_tier"] == "URGENT"
    assert r["priority_score"] != t_orig["priority_score"]


def test_dual_variant_rework_can_lift_high_to_urgent_via_expedite(api):
    """# difficulty: dual_variant_calc/cleaning_task_priority_original_vs_rework

    PRD §3.5: "Original (non-rework) tasks pass task_source straight
    into the formula; rework tasks always carry expedite_flag true
    because that field is forced at auto-creation, which can lift a
    task from HIGH to URGENT purely on the rework path even if the
    underlying inputs would not otherwise have done so."

    Distinct angle: even WITHOUT early-check-in, the rework's forced
    expedite=true causes a tier change. Original CHECK_OUT vip task
    (50+30=80 HIGH) → rework adds expedite=20 → 100 → URGENT.
    """
    room, hk = setup_room_and_housekeeper(vip_flag=True)
    t_orig = create_cleaning_task(
        room_id=room["id"], task_source="CHECK_OUT",
        expedite_flag=False,
    )
    assert t_orig["priority_score"] == 80
    assert t_orig["priority_tier"] == "HIGH"
    t_orig = drive_task_to_state(
        t_orig, hk["id"], target="SUBMITTED",
        clock_advance_minutes_between_start_submit=10,
    )
    api.inspect_cleaning_task(
        t_orig["id"],
        inspect_cleaning_task_payload(outcome="FAIL"),
        TEST_USERS["supervisor_headers"],
    )
    tlist = api.list_cleaning_tasks(
        TEST_USERS["supervisor_headers"],
        params={"room_id": room["id"]},
    )
    tasks, _ = validate_paginated(tlist)
    rework = [t for t in tasks if t.get("parent_task_id") == t_orig["id"]]
    assert len(rework) == 1
    r = rework[0]
    # CHECK_OUT base 50 + vip 30 + expedite 20 + early 0 = 100 → URGENT
    assert r["priority_score"] == 100
    assert r["priority_tier"] == "URGENT"


# ===========================================================================
# dual_variant_calc / housekeeper_workload_provisional_vs_realized
# ===========================================================================
def test_dual_variant_provisional_vs_realized_differ_with_in_flight_task(api):
    """# difficulty: dual_variant_calc/housekeeper_workload_provisional_vs_realized

    PRD §3.6: "at the same instant, for the same housekeeper, the
    realized number is strictly less than the provisional number
    whenever at least one non-completed task is on the roster, and the
    two numbers must differ whenever such an in-flight task exists."

    Setup matches the difficulty-design recipe:
    - Complete a STAYOVER task (25+0=25 estimated) with actual=30 min
      → realized contributes 30.
    - Start a CHECK_OUT task (25+15=40 estimated), don't submit →
      provisional contributes 40.
    Result: realized=30, provisional=40, must differ.
    """
    zone = unique_zone()
    room1 = create_room(zone_code=zone, pms_occupancy="OCCUPIED")
    # OCCUPIED_DIRTY for STAYOVER.
    room2 = create_room(zone_code=zone)
    hk = create_housekeeper_on_shift(assigned_zone=zone)
    # Task T1: STAYOVER on room1 (estimated 25), drive to COMPLETED
    # with 30-minute actual.
    t1 = create_cleaning_task(
        room_id=room1["id"], task_source="STAYOVER",
    )
    drive_task_to_state(
        t1, hk["id"], target="COMPLETED",
        clock_advance_minutes_between_start_submit=30,
    )
    # Task T2: CHECK_OUT on room2 (estimated 40), drive to IN_PROGRESS
    # (started but not submitted).
    t2 = create_cleaning_task(
        room_id=room2["id"], task_source="CHECK_OUT",
    )
    drive_task_to_state(t2, hk["id"], target="IN_PROGRESS")
    res = api.get_housekeeper(hk["id"], TEST_USERS["supervisor_headers"])
    final = validate_success(res)
    assert final["realized_workload_minutes"] == 30
    assert final["provisional_workload_minutes"] == 40
    assert (
        final["provisional_workload_minutes"]
        != final["realized_workload_minutes"]
    ), "PRD §3.6: 'the two numbers must differ' when an in-flight task exists."


def test_dual_variant_provisional_equals_realized_when_idle(api):
    """# difficulty: dual_variant_calc/housekeeper_workload_provisional_vs_realized

    PRD §3.6: "the realized number is strictly less than the
    provisional number whenever at least one non-completed task is on
    the roster, and the two numbers must differ whenever such an
    in-flight task exists."

    Contrapositive: a housekeeper with no in-flight tasks (only
    completed today) has provisional == realized.
    """
    room, hk, task = setup_task_in_state(
        target="COMPLETED",
        room_type="STANDARD",
        task_source="CHECK_OUT",
        clock_advance_minutes_between_start_submit=40,
    )
    res = api.get_housekeeper(hk["id"], TEST_USERS["supervisor_headers"])
    final = validate_success(res)
    # Provisional excludes COMPLETED (PRD §3.6); realized counts the
    # completed actual_minutes today.
    assert final["provisional_workload_minutes"] == 0
    assert final["realized_workload_minutes"] == 40


# ===========================================================================
# combinatorial_formula / priority_score_synergy_multiplier_mode_a
# ===========================================================================
def test_combinatorial_synergy_active_with_all_three_bonuses(api):
    """# difficulty: combinatorial_formula/priority_score_synergy_multiplier_mode_a

    PRD §3.5: "if all three are strictly greater than zero, the sum is
    multiplied by a synergy multiplier of 1.20 and the product rounded
    half-up to a whole number before being added to the base."

    vip=true, expedite=true, early=true, base SCHEDULED 20:
    20 + round_half_up((30+20+25)*1.20) = 20 + 90 = 110 (URGENT).
    """
    room, hk, t_a = setup_high_priority_task_inputs(
        vip_flag=True, expedite_flag=True, early_check_in=True,
        task_source="SCHEDULED",
    )
    assert t_a["priority_score"] == 110
    assert t_a["priority_tier"] == "URGENT"


def test_combinatorial_synergy_inactive_when_vip_absent(api):
    """# difficulty: combinatorial_formula/priority_score_synergy_multiplier_mode_a

    PRD §3.5: "if all three are strictly greater than zero, the sum is
    multiplied by a synergy multiplier of 1.20 ... The three bonuses
    are summed."

    Distinguishing pair: remove the vip bonus → multiplier does NOT
    apply, scoring is plain additive: SCHEDULED 20 + 0 + 20 + 25 = 65
    → NORMAL (65 < 70).
    """
    room, hk, t_b = setup_high_priority_task_inputs(
        vip_flag=False, expedite_flag=True, early_check_in=True,
        task_source="SCHEDULED",
    )
    assert t_b["priority_score"] == 65, (
        "Without VIP, synergy multiplier must not apply: 20 + 0 + 20 + 25 = 65."
    )
    assert t_b["priority_tier"] == "NORMAL"


# ===========================================================================
# combinatorial_formula / minibar_charge_sum_then_round_mode_b
# ===========================================================================
def test_combinatorial_sum_then_round_two_25c_items_yields_5c_tax(api):
    """# difficulty: combinatorial_formula/minibar_charge_sum_then_round_mode_b

    PRD §3.11: "computes tax_cents as the gross amount multiplied by
    the minibar tax rate of 0.10 and rounded half-up to a whole cent
    on that single product (per-line tax-then-sum is incorrect because
    each line's tax would be rounded independently)."

    Pinned: two 25¢ items → gross 50, tax = round_half_up(50*0.10) = 5,
    posted = 55. Per-line tax-then-sum (forbidden) would give
    round(2.5)+round(2.5)=6 and posted=56.
    """
    room, items, pending = setup_consumption_two_25c_items()
    posted = post_consumption(pending["id"])
    assert posted["gross_amount_cents"] == 50
    assert posted["tax_cents"] == 5, (
        "tax computed on the SUM (round_half_up(50*0.10)=5); per-line "
        "tax-then-sum (=6) is forbidden."
    )
    assert posted["posted_amount_cents"] == 55


def test_combinatorial_sum_then_round_three_lines(api):
    """# difficulty: combinatorial_formula/minibar_charge_sum_then_round_mode_b

    PRD §3.11: "computes tax_cents as the gross amount multiplied by
    the minibar tax rate of 0.10 and rounded half-up to a whole cent
    on that single product (per-line tax-then-sum is incorrect because
    each line's tax would be rounded independently)."

    Distinct scenario: three 33¢ items × 1 each → gross 99, tax =
    round_half_up(99*0.10) = round_half_up(9.9) = 10, posted = 109.
    Per-line: round(3.3)+round(3.3)+round(3.3) = 3+3+3 = 9, posted=108
    — forbidden.
    """
    room = create_room()
    items = [
        create_minibar_item(unit_price_cents=33, par_level=10,
                            replenishment_threshold=2)
        for _ in range(3)
    ]
    line_items = [
        {"minibar_item_id": it["id"], "quantity": 1} for it in items
    ]
    from test_helpers.fixtures import create_minibar_consumption
    consumption = create_minibar_consumption(
        room_id=room["id"], line_items=line_items,
        source_type="GUEST_SELF_REPORT",
    )
    posted = post_consumption(consumption["id"])
    assert posted["gross_amount_cents"] == 99
    assert posted["tax_cents"] == 10, (
        "sum-then-round: round_half_up(99*0.10)=10. Per-line "
        "rounding gives 9 and is forbidden."
    )
    assert posted["posted_amount_cents"] == 109


# ===========================================================================
# non_linear_state_machine / cleaning_task_submitted_branching
# ===========================================================================
def test_branching_fail_creates_rework_pass_does_not(api):
    """# difficulty: non_linear_state_machine/cleaning_task_submitted_branching

    PRD §3.3: "a failing inspection advances it to CANCELLED and
    auto-creates a rework task whose parent_task_id is the failed
    task's id."

    Compare a sibling PASS: PASS leads to COMPLETED with no rework
    task. The two branches produce disjoint side-effect sets.
    """
    # FAIL branch
    room_f, hk_f, t_fail = setup_task_in_state(
        target="SUBMITTED",
        task_source="CHECK_OUT",
        clock_advance_minutes_between_start_submit=15,
    )
    api.inspect_cleaning_task(
        t_fail["id"],
        inspect_cleaning_task_payload(outcome="FAIL"),
        TEST_USERS["supervisor_headers"],
    )
    res = api.get_cleaning_task(
        t_fail["id"], TEST_USERS["supervisor_headers"],
    )
    final_fail = validate_success(res)
    assert final_fail["status"] == "CANCELLED"
    tasks_f, _ = validate_paginated(api.list_cleaning_tasks(
        TEST_USERS["supervisor_headers"],
        params={"room_id": room_f["id"]},
    ))
    rework_f = [t for t in tasks_f if t.get("parent_task_id") == t_fail["id"]]
    assert len(rework_f) == 1
    # PASS branch
    room_p, hk_p, t_pass = setup_task_in_state(
        target="SUBMITTED",
        task_source="CHECK_OUT",
        clock_advance_minutes_between_start_submit=15,
    )
    api.inspect_cleaning_task(
        t_pass["id"],
        inspect_cleaning_task_payload(outcome="PASS"),
        TEST_USERS["supervisor_headers"],
    )
    res = api.get_cleaning_task(
        t_pass["id"], TEST_USERS["supervisor_headers"],
    )
    final_pass = validate_success(res)
    assert final_pass["status"] == "COMPLETED"
    tasks_p, _ = validate_paginated(api.list_cleaning_tasks(
        TEST_USERS["supervisor_headers"],
        params={"room_id": room_p["id"]},
    ))
    rework_p = [t for t in tasks_p if t.get("parent_task_id") == t_pass["id"]]
    assert len(rework_p) == 0, (
        "PRD §3.3: no rework task on PASS branch — fork branches are "
        "mutually exclusive."
    )


def test_branching_rework_task_immediately_dispatched(api):
    """# difficulty: non_linear_state_machine/cleaning_task_submitted_branching

    PRD §3.3: "auto-creates a rework task whose parent_task_id is the
    failed task's id, whose task_source is the failed task's original
    task_source, and whose expedite_flag is forced to true; that
    rework task is auto-dispatched immediately."
    """
    room, hk, task = setup_task_in_state(
        target="SUBMITTED",
        task_source="CHECK_OUT",
        clock_advance_minutes_between_start_submit=15,
    )
    api.inspect_cleaning_task(
        task["id"],
        inspect_cleaning_task_payload(outcome="FAIL"),
        TEST_USERS["supervisor_headers"],
    )
    tasks, _ = validate_paginated(api.list_cleaning_tasks(
        TEST_USERS["supervisor_headers"],
        params={"room_id": room["id"]},
    ))
    rework = [t for t in tasks if t.get("parent_task_id") == task["id"]]
    assert len(rework) == 1
    # PRD §3.3: 'that rework task is auto-dispatched immediately.'
    # → status must be ASSIGNED with a real housekeeper.
    assert rework[0]["status"] == "ASSIGNED"
    assert rework[0]["assigned_housekeeper_id"] == hk["id"]


# ===========================================================================
# non_linear_state_machine / minibar_consumption_investigated_branching
# ===========================================================================
def test_branching_resolve_keep_charge_true_keeps_folio(api):
    """# difficulty: non_linear_state_machine/minibar_consumption_investigated_branching

    PRD §3.11: "when keep_charge is true the record advances to
    RESOLVED (the folio charge stands) and an audit entry is
    appended."

    Distinguishing branch: keep_charge=true → no WAIVE audit entry,
    no payment-reverse.
    """
    from test_helpers.fixtures import setup_consumption_in_state
    room, items, inv = setup_consumption_in_state(target="INVESTIGATED")
    res = api.resolve_minibar_consumption(
        inv["id"], resolve_minibar_payload(keep_charge=True),
        TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "RESOLVED"
    waive = list_audit_entries_for_subject(
        inv["id"], action_type="MINIBAR_CONSUMPTION_WAIVE",
    )
    assert len(waive) == 0, (
        "PRD §3.11 RESOLVED branch: no MINIBAR_CONSUMPTION_WAIVE audit "
        "entry should fire."
    )


def test_branching_resolve_keep_charge_false_waives_and_audits(api):
    """# difficulty: non_linear_state_machine/minibar_consumption_investigated_branching

    PRD §3.11: "when keep_charge is false the record advances to
    WAIVED, the server emits an outbound payment-reverse event
    reversing folio_reference (only valid when the original
    posted_amount_cents is greater than zero), and a
    MINIBAR_CONSUMPTION_WAIVE audit entry is appended."

    Distinct branch from RESOLVED: a WAIVE audit entry MUST be present.
    """
    from test_helpers.fixtures import setup_consumption_in_state
    room, items, inv = setup_consumption_in_state(target="INVESTIGATED")
    res = api.resolve_minibar_consumption(
        inv["id"], resolve_minibar_payload(keep_charge=False),
        TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "WAIVED"
    waive = list_audit_entries_for_subject(
        inv["id"], action_type="MINIBAR_CONSUMPTION_WAIVE",
    )
    assert len(waive) >= 1


# ===========================================================================
# transitive_cascade / dispatch_isolate_room_triple_hop
# ===========================================================================
def test_transitive_cascade_dispatch_isolate_open_task_provisional(api):
    """# difficulty: transitive_cascade/dispatch_isolate_room_triple_hop

    PRD §3.7: "The cascade depth — dispatch isolates the room, the
    room flips, the open cleaning tasks cancel, and every affected
    housekeeper's provisional_workload_minutes is recomputed — is
    intentional."

    Verify all hops:
      hop 1: ticket → DISPATCHED
      hop 2: Room.status → OUT_OF_ORDER, out_of_order_ticket_id set
      hop 3: open CleaningTask → CANCELLED
      hop 4: Housekeeper.provisional_workload_minutes recomputed
    """
    room, hk, task = setup_room_hk_task(task_source="CHECK_OUT")
    assert task["status"] == "ASSIGNED"
    assert task["estimated_minutes"] == 40
    res = api.get_housekeeper(
        hk["id"], TEST_USERS["supervisor_headers"],
    )
    before = validate_success(res)
    assert before["provisional_workload_minutes"] == 40
    ticket = create_maintenance_ticket(
        room_id=room["id"], reporter_housekeeper_id=hk["id"],
        severity="CRITICAL", description="pipe burst",
    )
    dispatched = dispatch_ticket(ticket["id"], "eng-1")
    # hop 1
    assert dispatched["status"] == "DISPATCHED"
    # hop 2
    res = api.get_room(room["id"], TEST_USERS["supervisor_headers"])
    r_final = validate_success(res)
    assert r_final["status"] == "OUT_OF_ORDER"
    assert r_final["out_of_order_ticket_id"] == ticket["id"]
    # hop 3
    res = api.get_cleaning_task(
        task["id"], TEST_USERS["supervisor_headers"],
    )
    t_final = validate_success(res)
    assert t_final["status"] == "CANCELLED"
    # hop 4
    res = api.get_housekeeper(
        hk["id"], TEST_USERS["supervisor_headers"],
    )
    after = validate_success(res)
    assert after["provisional_workload_minutes"] == 0


def test_transitive_cascade_inspect_fail_rework_chain(api):
    """# difficulty: transitive_cascade/inspect_fail_rework_chain_depth_two

    PRD §3.3: "a failing inspection advances it to CANCELLED and
    auto-creates a rework task whose parent_task_id is the failed
    task's id, whose task_source is the failed task's original
    task_source, and whose expedite_flag is forced to true; that
    rework task is auto-dispatched immediately."

    Hops:
      hop 1: SUBMITTED → CANCELLED
      hop 2: rework CleaningTask exists with parent_task_id == failed
      hop 3: rework status in {ASSIGNED, PENDING} with expedite=true
    """
    room, hk, task = setup_task_in_state(
        target="SUBMITTED",
        task_source="CHECK_OUT",
        clock_advance_minutes_between_start_submit=20,
    )
    api.inspect_cleaning_task(
        task["id"],
        inspect_cleaning_task_payload(outcome="FAIL"),
        TEST_USERS["supervisor_headers"],
    )
    # hop 1
    res = api.get_cleaning_task(
        task["id"], TEST_USERS["supervisor_headers"],
    )
    assert validate_success(res)["status"] == "CANCELLED"
    # hop 2 + 3
    tasks, _ = validate_paginated(api.list_cleaning_tasks(
        TEST_USERS["supervisor_headers"],
        params={"room_id": room["id"]},
    ))
    rework = [t for t in tasks if t.get("parent_task_id") == task["id"]]
    assert len(rework) == 1
    assert rework[0]["status"] in {"ASSIGNED", "PENDING"}
    assert rework[0]["expedite_flag"] is True


# ===========================================================================
# priority_pair_validation_conflict /
#   state_vs_business_safety_dispatch_already_dispatched_on_isolated_room
# ===========================================================================
def test_validation_priority_state_precedes_business_safety_on_dispatch(api):
    """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_dispatch_already_dispatched_on_isolated_room

    PRD §2.6: "first the two authentication checks ... then
    path-parameter existence; then foreign-key existence in the
    request body; then state-machine eligibility for the requested
    transition (raising the family of state errors enumerated in §5,
    such as ... ERR_TICKET_NOT_REPORTED ...); then the business-safety
    checks (manual-correction target validity and isolating-ticket
    conflicts)."

    Setup: a ticket m1 is already DISPATCHED (so m1 is not REPORTED),
    AND the room is held by m1's isolation. Re-dispatching m1 must
    surface the state error ERR_TICKET_NOT_REPORTED — not the
    business-safety ERR_ROOM_ALREADY_ISOLATED — because state precedes
    business_safety.
    """
    room, hk, m1 = setup_room_isolated_by_ticket(severity="CRITICAL")
    # m1 is DISPATCHED, room is held. Attempt re-dispatch.
    res = api.dispatch_maintenance_ticket(
        m1["id"],
        dispatch_maintenance_ticket_payload("eng-1b"),
        TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_TICKET_NOT_REPORTED.value)
    body = res.json()
    assert body["data"]["error_id"] != \
        ApiErrorId.ERR_ROOM_ALREADY_ISOLATED.value, (
            "PRD §2.6: state check precedes business_safety, so the "
            "state error must surface, not ERR_ROOM_ALREADY_ISOLATED."
        )


def test_validation_priority_state_precedes_business_referential_on_accept(api):
    """# difficulty: priority_pair_validation_conflict/state_vs_business_referential_accept_completed_task_by_nonassignee

    PRD §2.6: "then state-machine eligibility for the requested
    transition ... then the business-safety checks ... then
    actor-identity referential checks (such as a non-assignee touching
    a task)."

    Setup: task accepted by Alice (status=ACCEPTED → not ASSIGNED).
    Bob (also on shift) tries to /accept. State check (priority 5)
    fires before actor-identity check (priority 8): the response is
    ERR_TASK_NOT_ASSIGNED, NOT ERR_NOT_TASK_ASSIGNEE.
    """
    import uuid as _uuid
    zone = unique_zone()
    sfx = _uuid.uuid4().hex[:6]
    room = create_room(zone_code=zone)
    alice = create_housekeeper_on_shift(
        assigned_zone=zone, employee_code=f"HK-AAA-001-{sfx}",
    )
    bob = create_housekeeper_on_shift(
        assigned_zone=zone, employee_code=f"HK-BBB-002-{sfx}",
    )
    task = create_cleaning_task(
        room_id=room["id"], task_source="CHECK_OUT",
    )
    # Auto-dispatched to alice (lowest employee_code among ties).
    assert task["assigned_housekeeper_id"] == alice["id"]
    # Alice accepts → task.status = ACCEPTED.
    api.accept_cleaning_task(
        task["id"], make_housekeeper_headers(alice["id"]),
    )
    # Bob tries to accept the now-ACCEPTED task.
    res = api.accept_cleaning_task(
        task["id"], make_housekeeper_headers(bob["id"]),
    )
    validate_error(res, ApiErrorId.ERR_TASK_NOT_ASSIGNED.value)
    body = res.json()
    assert body["data"]["error_id"] != \
        ApiErrorId.ERR_NOT_TASK_ASSIGNEE.value, (
            "PRD §2.6: state precedes business_referential."
        )


# ===========================================================================
# boundary_precision_check / linen_scheduled_replacement_at_exact_interval
# ===========================================================================
def test_boundary_linen_scheduled_replacement_just_below_interval(api):
    """# difficulty: boundary_precision_check/linen_scheduled_replacement_at_exact_interval

    PRD §3.12: "the elapsed time since the most recent movement ...
    is converted to whole days by flooring the seconds-difference
    divided by 86400; replacement is required when that elapsed-days
    count is at least scheduled_interval_days. Zero elapsed days never
    triggers a scheduled replacement; the boundary is inclusive on the
    upper side, not strict-greater."

    elapsed=2 days < scheduled_interval_days=3 → reject with
    ERR_LINEN_REPLACEMENT_NOT_DUE.
    """
    room = create_room()
    hk = create_housekeeper_on_shift()
    lt = create_linen_type(
        replacement_policy="SCHEDULED", scheduled_interval_days=3,
    )
    seed = create_linen_movement(
        room_id=room["id"], linen_type_id=lt["id"],
        collected_quantity=2,
        actor_headers=make_housekeeper_headers(hk["id"]),
    )
    handover_linen(seed["id"], hk["id"])
    api.laundry_return_event(
        laundry_return_payload(seed["id"], 2, 0, 0),
        TEST_USERS["system_integration_headers"],
    )
    advance_clock(2 * MINUTES_PER_DAY)
    payload = create_linen_movement_payload(
        room_id=room["id"], linen_type_id=lt["id"], collected_quantity=1,
    )
    res = api.create_linen_movement(
        payload, make_housekeeper_headers(hk["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LINEN_REPLACEMENT_NOT_DUE.value)


def test_boundary_linen_scheduled_replacement_at_exact_interval_succeeds(api):
    """# difficulty: boundary_precision_check/linen_scheduled_replacement_at_exact_interval

    PRD §3.12: "the boundary is inclusive on the upper side, not
    strict-greater." elapsed=3 == 3 must succeed.
    """
    room = create_room()
    hk = create_housekeeper_on_shift()
    lt = create_linen_type(
        replacement_policy="SCHEDULED", scheduled_interval_days=3,
    )
    seed = create_linen_movement(
        room_id=room["id"], linen_type_id=lt["id"],
        collected_quantity=2,
        actor_headers=make_housekeeper_headers(hk["id"]),
    )
    handover_linen(seed["id"], hk["id"])
    api.laundry_return_event(
        laundry_return_payload(seed["id"], 2, 0, 0),
        TEST_USERS["system_integration_headers"],
    )
    advance_clock(3 * MINUTES_PER_DAY)
    payload = create_linen_movement_payload(
        room_id=room["id"], linen_type_id=lt["id"], collected_quantity=1,
    )
    res = api.create_linen_movement(
        payload, make_housekeeper_headers(hk["id"]),
    )
    data = validate_success(res, expected_status=201)
    assert data["status"] == "COLLECTED"


# ===========================================================================
# boundary_precision_check / priority_tier_threshold_at_exact_urgent_boundary
# ===========================================================================
def test_boundary_priority_urgent_at_exactly_100(api):
    """# difficulty: boundary_precision_check/priority_tier_threshold_at_exact_urgent_boundary

    PRD §3.5: "a score of at least 100 yields URGENT, a score below
    100 but at least 70 yields HIGH."

    Combo to hit exactly 100: CHECK_OUT (50) + VIP (30) + expedite
    (20) = 100, with early_bonus=0 (no synergy).
    """
    room, hk, task = setup_high_priority_task_inputs(
        vip_flag=True, expedite_flag=True, early_check_in=False,
        task_source="CHECK_OUT",
    )
    assert task["priority_score"] == 100
    assert task["priority_tier"] == "URGENT"


def test_boundary_priority_high_just_below_urgent_threshold(api):
    """# difficulty: boundary_precision_check/priority_tier_threshold_at_exact_urgent_boundary

    PRD §3.5: "a score below 100 but at least 70 yields HIGH."

    Drop the VIP bonus: CHECK_OUT (50) + expedite (20) = 70 →
    boundary HIGH.
    """
    room, hk, task = setup_high_priority_task_inputs(
        vip_flag=False, expedite_flag=True, early_check_in=False,
        task_source="CHECK_OUT",
    )
    assert task["priority_score"] == 70
    assert task["priority_tier"] == "HIGH"


# ===========================================================================
# cross_entity_state_dependency /
#   cleaning_task_dispatch_requires_housekeeper_on_shift
# ===========================================================================
def test_cross_entity_dispatch_requires_on_shift_housekeeper(api):
    """# difficulty: cross_entity_state_dependency/cleaning_task_dispatch_requires_housekeeper_on_shift

    PRD §3.3: "if the candidate pool is empty, the task stays PENDING
    and a manual dispatch attempt returns ERR_NO_ELIGIBLE_HOUSEKEEPER."
    """
    room = create_room()
    # OFF_SHIFT housekeeper in zone.
    hk = create_housekeeper(
        assigned_zone=room["zone_code"], on_shift=False,
    )
    res = api.create_cleaning_task(
        {"room_id": room["id"], "task_source": "SCHEDULED"},
        TEST_USERS["supervisor_headers"],
    )
    task = validate_success(res, expected_status=201)
    assert task["status"] == "PENDING"
    res = api.dispatch_cleaning_task(
        task["id"], TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_HOUSEKEEPER.value)
    # After bringing the housekeeper on shift, dispatch must succeed.
    api.toggle_housekeeper_shift(
        hk["id"], {"shift_status": "ON_SHIFT"},
        TEST_USERS["supervisor_headers"],
    )
    res = api.dispatch_cleaning_task(
        task["id"], TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "ASSIGNED"
    assert data["assigned_housekeeper_id"] == hk["id"]


# ===========================================================================
# cross_entity_state_dependency /
#   maintenance_dispatch_requires_room_not_already_isolated
# ===========================================================================
def test_cross_entity_maintenance_dispatch_blocked_by_room_isolation(api):
    """# difficulty: cross_entity_state_dependency/maintenance_dispatch_requires_room_not_already_isolated

    PRD §3.7: "the room must be free of any prior isolation:
    dispatching an isolating ticket against a room whose
    out_of_order_ticket_id is already set to a different ticket is
    rejected with ERR_ROOM_ALREADY_ISOLATED."

    Cross-entity dependency: MaintenanceTicket.dispatch precondition
    references Room.out_of_order_ticket_id.
    """
    room, hk, m1 = setup_room_isolated_by_ticket(severity="CRITICAL")
    m2 = create_maintenance_ticket(
        room_id=room["id"], reporter_housekeeper_id=hk["id"],
        severity="CRITICAL",
    )
    res = api.dispatch_maintenance_ticket(
        m2["id"],
        dispatch_maintenance_ticket_payload("eng-2"),
        TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_ROOM_ALREADY_ISOLATED.value)
    # m2 must remain REPORTED.
    res = api.get_maintenance_ticket(
        m2["id"], TEST_USERS["supervisor_headers"],
    )
    final = validate_success(res)
    assert final["status"] == "REPORTED"


# ===========================================================================
# resource_temporal_overlap / room_isolation_exclusive_capacity_one
# ===========================================================================
def test_temporal_room_isolation_exclusive_capacity_one(api):
    """# difficulty: resource_temporal_overlap/room_isolation_exclusive_capacity_one

    PRD §3.7: "Room.out_of_order_ticket_id to the ticket's id ... the
    room must be free of any prior isolation."

    Aggregate capacity of 1 on Room.out_of_order_ticket_id: only one
    isolating ticket may hold it at a time. After verifying m1, the
    capacity opens up and m2 can dispatch.
    """
    room, hk, m1 = setup_room_isolated_by_ticket(severity="CRITICAL")
    m2 = create_maintenance_ticket(
        room_id=room["id"], reporter_housekeeper_id=hk["id"],
        severity="CRITICAL",
    )
    # Initially: m2 dispatch must be rejected.
    res = api.dispatch_maintenance_ticket(
        m2["id"],
        dispatch_maintenance_ticket_payload("eng-2"),
        TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_ROOM_ALREADY_ISOLATED.value)
    # Walk m1 through repair → verify.
    drive_ticket_through_repair(m1["id"])
    api.verify_maintenance_ticket(
        m1["id"], TEST_USERS["supervisor_headers"],
    )
    # Re-fetch room → out_of_order_ticket_id cleared.
    res = api.get_room(room["id"], TEST_USERS["supervisor_headers"])
    final_room = validate_success(res)
    assert final_room["out_of_order_ticket_id"] is None
    # m2 dispatch now succeeds.
    res = api.dispatch_maintenance_ticket(
        m2["id"],
        dispatch_maintenance_ticket_payload("eng-2"),
        TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "DISPATCHED"


# ===========================================================================
# resource_temporal_overlap / minibar_dispute_window_half_open_temporal
# ===========================================================================
def test_temporal_minibar_dispute_half_open_window_72h_exclusive(api):
    """# difficulty: resource_temporal_overlap/minibar_dispute_window_half_open_temporal

    PRD §3.11: "The window is half-open — strictly less than 72 hours
    — so an attempt at exactly 72 hours is rejected with
    ERR_DISPUTE_WINDOW_EXPIRED; an attempt outside POSTED is rejected
    with ERR_CONSUMPTION_NOT_POSTED."

    Both endpoints of the boundary: at 72h-1min the dispute succeeds;
    at exactly 72h it fails.
    """
    from test_helpers.fixtures import setup_consumption_in_state
    # Just-inside branch
    _r1, _items1, posted_a = setup_consumption_in_state(target="POSTED")
    advance_clock(MINIBAR_DISPUTE_WINDOW_HOURS * MINUTES_PER_HOUR - 1)
    res = api.dispute_minibar_consumption(
        posted_a["id"], dispute_minibar_payload("just inside"),
        TEST_USERS["frontdesk_headers"],
    )
    inside = validate_success(res)
    assert inside["status"] == "DISPUTED"

    # Exactly-72h branch
    _r2, _items2, posted_b = setup_consumption_in_state(target="POSTED")
    advance_clock(MINIBAR_DISPUTE_WINDOW_HOURS * MINUTES_PER_HOUR)
    res = api.dispute_minibar_consumption(
        posted_b["id"], dispute_minibar_payload("at exact 72h"),
        TEST_USERS["frontdesk_headers"],
    )
    validate_error(res, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED.value)


# ===========================================================================
# compensating_invariant / minibar_waiver_net_zero_folio_invariant
# ===========================================================================
def test_compensating_minibar_waiver_net_zero(api):
    """# difficulty: compensating_invariant/minibar_waiver_net_zero_folio_invariant

    PRD §3.11: "The waiver path preserves a strict invariant: the
    absolute reversal recorded at resolution exactly equals the
    gross_amount_cents plus tax_cents posted on the original
    folio-post action, so a posted-then-waived charge nets to zero on
    the folio."

    Two 25¢ items → posted 55. After waive, POST + WAIVE audit pair
    must net to zero on amount_cents.
    """
    room, items, pending = setup_consumption_two_25c_items()
    posted = post_consumption(pending["id"])
    assert posted["posted_amount_cents"] == 55
    waived = drive_consumption_to_state(
        posted, target="WAIVED", keep_charge=False,
    )
    assert waived["status"] == "WAIVED"
    audit = list_audit_entries_for_subject(pending["id"])
    posts = [
        a for a in audit if a["action_type"] == "MINIBAR_CONSUMPTION_POST"
    ]
    waives = [
        a for a in audit if a["action_type"] == "MINIBAR_CONSUMPTION_WAIVE"
    ]
    assert len(posts) == 1 and len(waives) == 1
    pa = posts[0]["detail"].get("amount_cents") \
        or posts[0]["detail"].get("posted_amount_cents")
    wa = waives[0]["detail"].get("amount_cents") \
        or waives[0]["detail"].get("posted_amount_cents")
    assert pa == 55, f"POST amount_cents must be 55, got {pa}"
    assert wa == 55, (
        "PRD §3.11 invariant: the WAIVE detail amount must equal the "
        f"posted amount (55), got {wa}"
    )


# ===========================================================================
# compensating_invariant / linen_unit_conservation_invariant
# ===========================================================================
def test_compensating_linen_unit_conservation_invariant(api):
    """# difficulty: compensating_invariant/linen_unit_conservation_invariant

    PRD §3.12: "the server enforces the invariant that
    returned_quantity plus loss_quantity plus damage_quantity equals
    sent_to_laundry_quantity, otherwise the event is rejected with
    ERR_LAUNDRY_RETURN_QUANTITY_MISMATCH."

    Conserved unit count: 7 + 2 + 1 == 10 must accept; 7 + 2 + 0 != 10
    must reject on a sibling movement.
    """
    # Accepted branch
    room, hk, lt, m_ok = setup_linen_movement_at_handover(
        replacement_policy="PER_STAY", collected_quantity=10,
    )
    res = api.laundry_return_event(
        laundry_return_payload(m_ok["id"], 7, 2, 1),
        TEST_USERS["system_integration_headers"],
    )
    data_ok = validate_success(res)
    assert data_ok["returned_quantity"] == 7
    assert data_ok["loss_quantity"] == 2
    assert data_ok["damage_quantity"] == 1
    assert (
        data_ok["returned_quantity"]
        + data_ok["loss_quantity"]
        + data_ok["damage_quantity"]
        == data_ok["sent_to_laundry_quantity"]
        == 10
    )
    # Rejected branch
    _r2, _hk2, _lt2, m_bad = setup_linen_movement_at_handover(
        replacement_policy="PER_STAY", collected_quantity=10,
    )
    res = api.laundry_return_event(
        laundry_return_payload(m_bad["id"], 7, 2, 0),
        TEST_USERS["system_integration_headers"],
    )
    validate_error(
        res, ApiErrorId.ERR_LAUNDRY_RETURN_QUANTITY_MISMATCH.value,
    )


# ===========================================================================
# Second-pass coverage — every difficulty instance needs >= 2 tests.
# ===========================================================================

# --- transitive_cascade / dispatch_isolate_room_triple_hop (2nd test) ----
def test_transitive_cascade_dispatch_room_status_event_recorded(api):
    """# difficulty: transitive_cascade/dispatch_isolate_room_triple_hop

    PRD §3.7: "appends a RoomStatusEvent whose change_reason is
    MAINTENANCE_ISOLATE, and appends an AuditLog."

    Distinct angle on the same triple-hop cascade: verify the event
    record at hop 2 (the room flip) is materialised with the precise
    change_reason from the closed set in PRD §2.7.
    """
    from test_helpers.fixtures import list_room_status_events
    room, hk, task = setup_room_hk_task(task_source="CHECK_OUT")
    ticket = create_maintenance_ticket(
        room_id=room["id"], reporter_housekeeper_id=hk["id"],
        severity="HIGH",
    )
    dispatch_ticket(ticket["id"], "eng-1")
    events = list_room_status_events(room["id"])
    isolate_events = [
        e for e in events
        if e["change_reason"] == "MAINTENANCE_ISOLATE"
    ]
    assert len(isolate_events) == 1, (
        "PRD §3.7: exactly one MAINTENANCE_ISOLATE event must be "
        "appended on isolating dispatch."
    )
    ev = isolate_events[0]
    assert ev["new_status"] == "OUT_OF_ORDER"


# --- transitive_cascade / inspect_fail_rework_chain_depth_two (2nd) ---
def test_transitive_cascade_inspect_fail_recomputes_provisional(api):
    """# difficulty: transitive_cascade/inspect_fail_rework_chain_depth_two

    PRD §3.3: "The original assignee's provisional_workload_minutes
    is recomputed in either branch."

    PRD §3.8: "On a FAIL inspection, the cleaning task advances to
    CANCELLED ... The original assignee's provisional_workload_minutes
    is recomputed in either branch."

    A FAIL inspection on a CHECK_OUT task (40 min estimated): after
    FAIL, the task is CANCELLED; the rework is auto-dispatched to the
    same assignee and brings 40 min back in. Net provisional remains
    40 (= rework's estimated).
    """
    room, hk, task = setup_task_in_state(
        target="SUBMITTED",
        task_source="CHECK_OUT",
        clock_advance_minutes_between_start_submit=20,
    )
    api.inspect_cleaning_task(
        task["id"],
        inspect_cleaning_task_payload(outcome="FAIL"),
        TEST_USERS["supervisor_headers"],
    )
    res = api.get_housekeeper(
        hk["id"], TEST_USERS["supervisor_headers"],
    )
    final = validate_success(res)
    # Rework auto-dispatched with estimated_minutes 40 (same room).
    assert final["provisional_workload_minutes"] == 40


# --- priority_pair_validation_conflict /
#     state_vs_business_safety (2nd test) ----------------------------------
def test_validation_priority_state_precedes_business_safety_after_repair(api):
    """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_dispatch_already_dispatched_on_isolated_room

    PRD §2.6: state-machine eligibility (priority 5) precedes the
    business-safety isolating-ticket conflict (priority 7). A second
    isolating dispatch attempt against a room held by m1 surfaces the
    business-safety error ERR_ROOM_ALREADY_ISOLATED (m2 is REPORTED so
    no state error fires); contrast that with the prior test where m1
    itself is DISPATCHED (no longer REPORTED) and ERR_TICKET_NOT_REPORTED
    fires instead.
    """
    room, hk, m1 = setup_room_isolated_by_ticket(severity="CRITICAL")
    m2 = create_maintenance_ticket(
        room_id=room["id"], reporter_housekeeper_id=hk["id"],
        severity="CRITICAL",
    )
    # m2.status == REPORTED, room is held by m1 → state check passes
    # for m2; business_safety check fires.
    res = api.dispatch_maintenance_ticket(
        m2["id"],
        dispatch_maintenance_ticket_payload("eng-2"),
        TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_ROOM_ALREADY_ISOLATED.value)


# --- priority_pair_validation_conflict /
#     state_vs_business_referential (2nd test) ------------------------------
def test_validation_priority_state_precedes_business_referential_on_submit(api):
    """# difficulty: priority_pair_validation_conflict/state_vs_business_referential_accept_completed_task_by_nonassignee

    PRD §2.6: state check (priority 5) precedes actor-identity check
    (priority 8). A non-assignee /submit attempt against a task that
    is not IN_PROGRESS surfaces ERR_TASK_NOT_IN_PROGRESS, not
    ERR_NOT_TASK_ASSIGNEE.
    """
    import uuid as _uuid
    zone = unique_zone()
    sfx = _uuid.uuid4().hex[:6]
    room = create_room(zone_code=zone)
    alice = create_housekeeper_on_shift(
        assigned_zone=zone, employee_code=f"HK-AAA-001-{sfx}",
    )
    bob = create_housekeeper_on_shift(
        assigned_zone=zone, employee_code=f"HK-BBB-002-{sfx}",
    )
    task = create_cleaning_task(
        room_id=room["id"], task_source="CHECK_OUT",
    )
    # Auto-dispatched to Alice. Alice accepts (ACCEPTED); does NOT
    # start.
    api.accept_cleaning_task(
        task["id"], make_housekeeper_headers(alice["id"]),
    )
    # Bob (non-assignee) attempts /submit while task is ACCEPTED (not
    # IN_PROGRESS).
    res = api.submit_cleaning_task(
        task["id"], make_housekeeper_headers(bob["id"]),
    )
    validate_error(res, ApiErrorId.ERR_TASK_NOT_IN_PROGRESS.value)


# --- cross_entity_state_dependency /
#     cleaning_task_dispatch_requires_housekeeper_on_shift (2nd test) ------
def test_cross_entity_auto_dispatch_blocked_when_zone_has_only_off_shift(api):
    """# difficulty: cross_entity_state_dependency/cleaning_task_dispatch_requires_housekeeper_on_shift

    PRD §3.3: "If at least one Housekeeper is on shift in the room's
    zone at the moment of creation, the system auto-dispatches the
    task right away and advances it from PENDING to ASSIGNED; if no
    eligible housekeeper is on shift, the task remains PENDING."

    Distinct angle: auto-dispatch path (vs manual /dispatch in the
    first test). Same cross-entity dependency on Housekeeper.shift_status.
    """
    zone = unique_zone()
    room = create_room(zone_code=zone)
    create_housekeeper(assigned_zone=zone, on_shift=False)
    res = api.create_cleaning_task(
        {"room_id": room["id"], "task_source": "SCHEDULED"},
        TEST_USERS["supervisor_headers"],
    )
    task = validate_success(res, expected_status=201)
    assert task["status"] == "PENDING", (
        "No on-shift housekeeper in zone — task must remain PENDING."
    )
    assert task.get("assigned_housekeeper_id") is None


# --- cross_entity_state_dependency /
#     maintenance_dispatch_requires_room_not_already_isolated (2nd) --------
def test_cross_entity_maintenance_dispatch_low_severity_unaffected_by_isolation(api):
    """# difficulty: cross_entity_state_dependency/maintenance_dispatch_requires_room_not_already_isolated

    PRD §3.7: "If the ticket isolates the room, that dispatch
    atomically forces the parent room into OUT_OF_ORDER ... the room
    must be free of any prior isolation."

    PRD §3.7: "the server computes isolates_room as true exactly when
    severity is one of HIGH or CRITICAL — that single field is the
    gate to the isolation cascade."

    Distinct cross-entity angle: a LOW-severity ticket (isolates_room
    false) dispatches successfully even on a room held by another
    isolating ticket, because the isolation-conflict guard only
    applies to isolating tickets.
    """
    room, hk, m1 = setup_room_isolated_by_ticket(severity="CRITICAL")
    m_low = create_maintenance_ticket(
        room_id=room["id"], reporter_housekeeper_id=hk["id"],
        severity="LOW",
    )
    assert m_low["isolates_room"] is False
    res = api.dispatch_maintenance_ticket(
        m_low["id"],
        dispatch_maintenance_ticket_payload("eng-low"),
        TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "DISPATCHED", (
        "PRD §3.7: a non-isolating ticket dispatch is unaffected by "
        "the room's current isolation state."
    )


# --- resource_temporal_overlap / room_isolation_exclusive_capacity_one (2nd) -
def test_temporal_room_isolation_capacity_one_releases_after_verify(api):
    """# difficulty: resource_temporal_overlap/room_isolation_exclusive_capacity_one

    PRD §3.7: "verification advances the ticket to VERIFIED, sets
    verified_at, appends an AuditLog, and — when the ticket had
    isolated the room — cascades the room from OUT_OF_ORDER back to
    VACANT_DIRTY, clears Room.out_of_order_ticket_id."

    Distinct angle: after verify, Room.status leaves OUT_OF_ORDER. The
    "isolation interval" closes.
    """
    room, hk, m1 = setup_room_isolated_by_ticket(severity="HIGH")
    drive_ticket_through_repair(m1["id"])
    res = api.verify_maintenance_ticket(
        m1["id"], TEST_USERS["supervisor_headers"],
    )
    verified = validate_success(res)
    assert verified["status"] == "VERIFIED"
    res = api.get_room(room["id"], TEST_USERS["supervisor_headers"])
    final = validate_success(res)
    assert final["status"] == "VACANT_DIRTY"
    assert final["out_of_order_ticket_id"] is None


# --- resource_temporal_overlap / minibar_dispute_window_half_open_temporal (2nd) -
def test_temporal_minibar_dispute_window_long_after_expiry_rejected(api):
    """# difficulty: resource_temporal_overlap/minibar_dispute_window_half_open_temporal

    PRD §3.11: "The window is half-open — strictly less than 72 hours
    — so an attempt at exactly 72 hours is rejected with
    ERR_DISPUTE_WINDOW_EXPIRED."

    Distinct boundary angle: well after the half-open window
    (72h + 30min) → same error fires.
    """
    from test_helpers.fixtures import setup_consumption_in_state
    room, items, posted = setup_consumption_in_state(target="POSTED")
    advance_clock(MINIBAR_DISPUTE_WINDOW_HOURS * MINUTES_PER_HOUR + 30)
    res = api.dispute_minibar_consumption(
        posted["id"], dispute_minibar_payload("far past window"),
        TEST_USERS["frontdesk_headers"],
    )
    validate_error(res, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED.value)


# --- compensating_invariant / minibar_waiver_net_zero_folio_invariant (2nd) -
def test_compensating_minibar_waiver_3_line_net_zero(api):
    """# difficulty: compensating_invariant/minibar_waiver_net_zero_folio_invariant

    PRD §3.11: "The waiver path preserves a strict invariant: the
    absolute reversal recorded at resolution exactly equals the
    gross_amount_cents plus tax_cents posted on the original
    folio-post action, so a posted-then-waived charge nets to zero
    on the folio."

    Distinct values from the 2x25¢ scenario: three lines at
    100¢/qty=2 → gross 600, tax 60, posted 660. WAIVE detail must
    record 660.
    """
    from test_helpers.fixtures import setup_consumption_in_state
    room, items, posted = setup_consumption_in_state(
        target="POSTED", unit_price_cents=100, line_count=3,
        quantity_each=2,
    )
    assert posted["posted_amount_cents"] == 660
    waived = drive_consumption_to_state(
        posted, target="WAIVED", keep_charge=False,
    )
    assert waived["status"] == "WAIVED"
    audit = list_audit_entries_for_subject(posted["id"])
    waives = [
        a for a in audit if a["action_type"] == "MINIBAR_CONSUMPTION_WAIVE"
    ]
    assert len(waives) == 1
    wa = waives[0]["detail"].get("amount_cents") \
        or waives[0]["detail"].get("posted_amount_cents")
    assert wa == 660, (
        f"PRD §3.11 invariant: WAIVE amount must equal posted (660), got {wa}"
    )


# --- compensating_invariant / linen_unit_conservation_invariant (2nd) ------
def test_compensating_linen_unit_conservation_zero_loss_zero_damage(api):
    """# difficulty: compensating_invariant/linen_unit_conservation_invariant

    PRD §3.12: "the server enforces the invariant that
    returned_quantity plus loss_quantity plus damage_quantity equals
    sent_to_laundry_quantity, otherwise the event is rejected with
    ERR_LAUNDRY_RETURN_QUANTITY_MISMATCH."

    Distinct conservation scenario: full return, 0 loss, 0 damage —
    invariant 10+0+0 = 10 must accept and transition to RESOLVED (no
    LOSS_REPORTED intermediate). A sibling rejected case where
    9+0+0 != 10 confirms the invariant goes both ways.
    """
    room, hk, lt, m_ok = setup_linen_movement_at_handover(
        replacement_policy="PER_STAY", collected_quantity=10,
    )
    res = api.laundry_return_event(
        laundry_return_payload(m_ok["id"], 10, 0, 0),
        TEST_USERS["system_integration_headers"],
    )
    data = validate_success(res)
    assert data["returned_quantity"] == 10
    assert data["loss_quantity"] == 0
    assert data["damage_quantity"] == 0
    assert data["status"] == "RESOLVED"

    # Sibling rejection branch (under-by-one).
    _r2, _hk2, _lt2, m_bad = setup_linen_movement_at_handover(
        replacement_policy="PER_STAY", collected_quantity=10,
    )
    res = api.laundry_return_event(
        laundry_return_payload(m_bad["id"], 9, 0, 0),
        TEST_USERS["system_integration_headers"],
    )
    validate_error(
        res, ApiErrorId.ERR_LAUNDRY_RETURN_QUANTITY_MISMATCH.value,
    )
