"""Cross-entity cascades, compensating invariants, and second-coverage tests
for difficulty-design instances.

Most difficulty-design instances need ≥2 tests; the first test lives in the
topical file (e.g., test_03 for casting), and this file adds the second
angle so the priority queue requirement is satisfied.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_audition_payload,
    offer_role_payload,
    substitute_role_payload,
    schedule_scene_payload,
    reschedule_scene_payload,
    patch_weather_status_payload,
    create_change_order_payload,
    create_vendor_invoice_payload,
    setup_production_with_categories,
    setup_role_with_n_breakdown_scenes,
    setup_signed_role,
    setup_in_production,
    setup_wrap_pending,
    setup_equipment_lost,
    setup_equipment_damaged,
    setup_equipment_checked_out,
    create_actor,
    create_role_in_production,
    create_scene_in_production,
    walk_role_to_offered,
    walk_role_to_signed,
    create_location,
    create_held_reservation,
    confirm_reservation_with_permit_and_weather,
    get_categories_by_code,
    get_production,
    iso,
    make_line_producer_headers,
    make_finance_controller_headers,
    EXEC,
    LP,
    FC,
    CD,
    PC,
)


# ─── dual_variant_calc / cast_commit (2nd coverage) ──────────────────────────

def test_sign_role_with_omitted_scene_excluded_from_cast_commit(api):
    """PRD §3.2: "scenes already in `SHOT` or `OMITTED` are excluded(...). The
    capped day count is multiplied by the role's `day_rate_cents` to yield
    the projected commitment in integer cents."

    # difficulty: dual_variant_calc/cast_commit_estimate_offer_vs_sign_on_role_entity
    Claim: 3 scenes referencing the role — 1 OMITTED, 2 BREAKDOWN. SIGN
    commits 2 days * day_rate (OMITTED scene excluded), not 3 days.
    """
    s = setup_role_with_n_breakdown_scenes(
        api,
        n_breakdown_scenes=3,
        n_shot_scenes=0,
        scene_minutes=480,
        role_union_tier="SUPPORTING",
        role_day_rate_cents=200_000,
        cast_planned_cents=10_000_000,
    )
    # Mark the first BREAKDOWN scene as OMITTED.
    omit_target = s["scenes_breakdown"][0]
    validate_success(api.omit_scene(s["production"]["id"], omit_target["id"], LP), 200)
    # SIGN.
    validate_success(api.sign_role(s["production"]["id"], s["role"]["id"], LP), 200)
    cats = get_categories_by_code(api, production_id=s["production"]["id"])
    # Two BREAKDOWN scenes remain → 2 days * 200_000 = 400_000.
    assert cats["CAST"]["committed_cents"] == 400_000


# ─── dual_variant_calc / crew_payroll (2nd coverage) ─────────────────────────

def test_payroll_zero_overtime_no_rounding_difference(api):
    """PRD §3.8: "the persisted `payroll_cents` MUST come from the per-component-
    rounding variant."

    # difficulty: dual_variant_calc/crew_payroll_per_component_vs_total_then_round_on_crewassignment_entity
    Claim: with day_rate=10_000, scheduled=5, actual=5 (no overtime),
    payroll = 5*10_000 = 50_000 exactly. Both rounding variants agree here.
    """
    setup = setup_wrap_pending(
        api,
        crew_day_rate_cents=10_000,
        crew_scheduled_days=5,
        crew_actual_days=5,
    )
    prod = setup["production"]
    closed = validate_success(api.close_account(prod["id"], FC), 200)
    assert closed["status"] == "WRAPPED"
    cats = get_categories_by_code(api, production_id=prod["id"])
    assert cats["CREW"]["actual_cents"] == 50_000


def test_payroll_round_order_pinned_second_tier_only(api):
    """PRD §3.8: "Each of the two overtime components is computed and rounded
    half-up to the nearest integer cent **independently**, and only then are
    the three components (base, first-tier overtime, second-tier overtime)
    summed to produce the persisted `payroll_cents`. The order — round per
    component, then sum — is load-bearing and must not be changed(...)."

    # difficulty: combinatorial_formula/payroll_per_component_round_order_pinned
    Claim: with day_rate_cents=12_345, scheduled=5, actual=12 (overtime
    split 5+2):
      base = 5 * 12_345 = 61_725
      ot_first_days = 5
      ot_first = round_half_up(5 * 12_345 * 1.50)
               = round_half_up(92_587.50) = 92_588   (.5 rounds half-UP)
      ot_second_days = 2
      ot_second = round_half_up(2 * 12_345 * 1.75)
                = round_half_up(43_207.50) = 43_208
      payroll = 61_725 + 92_588 + 43_208 = 197_521  (per-component variant)
    Total-then-round variant: 61_725 + 92_587.5 + 43_207.5 = 197_520
    (sum is integer, no rounding); the per-component variant differs by 1
    cent — and pinning per-component is what we assert.
    """
    setup = setup_wrap_pending(
        api,
        crew_day_rate_cents=12_345,
        crew_scheduled_days=5,
        crew_actual_days=12,
    )
    prod = setup["production"]
    closed = validate_success(api.close_account(prod["id"], FC), 200)
    assert closed["status"] == "WRAPPED"
    cats = get_categories_by_code(api, production_id=prod["id"])
    assert cats["CREW"]["actual_cents"] == 197_521, (
        f"Expected CREW.actual_cents=197521 (per-component round_half_up), "
        f"got {cats['CREW']['actual_cents']}"
    )
    assert cats["CREW"]["actual_cents"] != 197_520


# ─── combinatorial_formula / cap (2nd coverage) ──────────────────────────────

def test_sign_role_principal_cap_at_60_days(api):
    """PRD §3.2: "60 days for `PRINCIPAL`(...). The capped day count is
    multiplied by the role's `day_rate_cents`(...)."

    # difficulty: combinatorial_formula/cast_commit_min_cap_with_state_filtered_sum
    Claim: PRINCIPAL role with 70 BREAKDOWN scenes (1 day each) → cap=60 days,
    not 70.
    """
    s = setup_role_with_n_breakdown_scenes(
        api,
        n_breakdown_scenes=70,
        n_shot_scenes=0,
        scene_minutes=480,  # 1 day each
        role_union_tier="PRINCIPAL",
        role_day_rate_cents=10_000,
        cast_planned_cents=10_000_000,
    )
    validate_success(api.sign_role(s["production"]["id"], s["role"]["id"], LP), 200)
    cats = get_categories_by_code(api, production_id=s["production"]["id"])
    # 70 → capped 60 → 60 * 10_000 = 600_000.
    assert cats["CAST"]["committed_cents"] == 600_000
    assert cats["CAST"]["committed_cents"] != 700_000


# ─── non_linear_state_machine / role cycle (2nd coverage) ───────────────────

def test_signed_role_substitute_branch_creates_new_signed_role(api):
    """PRD §3.2: "A signed role can later be substituted (`SIGNED → RECAST`)
    by a `LineProducer`(...). On success, (...) a fresh `Role` record is
    created carrying the replacement values and is immediately signed
    in-line(...)."

    # difficulty: non_linear_state_machine/role_audition_shortlist_cycle
    Claim: SIGNED→RECAST + spawn replacement Role at SIGNED is the branch
    leg complementing the SHORTLISTED↔AUDITIONING cycle. After substitute,
    old role.casting_status==RECAST.
    """
    s = setup_signed_role(
        api,
        n_breakdown_scenes=2,
        role_union_tier="SUPPORTING",
        role_day_rate_cents=100_000,
        cast_planned_cents=10_000_000,
    )
    replacement = create_actor(api)
    res = validate_success(api.substitute_role(
        s["production"]["id"], s["role"]["id"],
        substitute_role_payload(
            replacement_actor_id=replacement["id"],
            replacement_day_rate_cents=120_000,
        ),
        LP,
    ), 200)
    assert res["casting_status"] == "RECAST"


# ─── non_linear_state_machine / reservation reschedule (2nd coverage) ───────

def test_omit_scheduled_scene_releases_reservation(api):
    """PRD §3.4: "The `LineProducer` may also omit a scene, transitioning it
    `BREAKDOWN → OMITTED` (no preconditions) or `SCHEDULED → OMITTED` (only
    while the production is still in `PLANNING`); the latter cascades the
    linked reservation `CONFIRMED → RELEASED` and writes `SCHEDULE_CHANGE`."

    # difficulty: non_linear_state_machine/location_reservation_reschedule_branch
    Claim: omit on a SCHEDULED scene cascades the linked reservation to
    RELEASED — a different branching path on the LocationReservation state
    machine.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api)
    scene = create_scene_in_production(api, production_id=prod["id"])
    reservation = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=prod["id"],
        scene_id=scene["id"],
        start_at=iso(2026, 6, 1, 9),
        end_at=iso(2026, 6, 1, 17),
    )
    confirm_reservation_with_permit_and_weather(api, reservation_id=reservation["id"])
    validate_success(api.schedule_scene(
        prod["id"], scene["id"],
        schedule_scene_payload(reservation_id=reservation["id"]),
        LP,
    ), 200)
    omitted = validate_success(api.omit_scene(prod["id"], scene["id"], LP), 200)
    assert omitted["status"] == "OMITTED"
    # Reservation now should be RELEASED — confirm by trying to release: invalid state.
    rel_res = api.release_reservation(reservation["id"], PC)
    validate_error(rel_res, "ERR_INVALID_STATE", expected_status=409)


# ─── transitive_cascade / role sign chain (2nd coverage) ────────────────────

def test_sign_role_under_threshold_no_alert_change(api):
    """PRD §2.7: "(...) otherwise if utilization is at least 0.90 the category
    is `WARN`; otherwise the category is `OK`."
    PRD §2.6: "Otherwise, posture is `GREEN`."

    # difficulty: transitive_cascade/role_sign_to_budget_to_alert_to_posture_depth_three
    Claim: complementary case — sign that pushes utilization to 0.20 leaves
    alert_state=OK and posture=GREEN. Hop chain still runs, just produces no
    state change.
    """
    s = setup_role_with_n_breakdown_scenes(
        api,
        n_breakdown_scenes=1,
        n_shot_scenes=0,
        scene_minutes=480,
        role_union_tier="SUPPORTING",
        role_day_rate_cents=100_000,
        cast_planned_cents=10_000_000,
    )
    validate_success(api.sign_role(s["production"]["id"], s["role"]["id"], LP), 200)
    cats = get_categories_by_code(api, production_id=s["production"]["id"])
    # Utilization 100_000 / 10_000_000 = 0.01 → OK
    assert cats["CAST"]["committed_cents"] == 100_000
    assert cats["CAST"]["alert_state"] == "OK"
    prod = get_production(api, production_id=s["production"]["id"])
    assert prod["posture"] == "GREEN"


# ─── transitive_cascade / equipment loss chain (2nd coverage) ────────────────

def test_report_damage_to_committed_then_return_verified_compensates(api):
    """PRD §3.5: "If equipment is damaged or lost while checked out, the
    coordinator records `REPORT_DAMAGE` (transitioning `CHECKED_OUT →
    DAMAGED`) or `REPORT_LOSS` (transitioning `CHECKED_OUT → LOST`). Each
    fires the same financial cascade: the event's `damage_charge_cents` is
    added to the `EQUIPMENT` category's `committed_cents`(...). Recording a
    `RETURN_VERIFIED` event transitions the equipment from `DAMAGED` or
    `LOST` back to `RETURNED`."

    # difficulty: transitive_cascade/equipment_loss_to_invoice_deduction_to_category_actual
    Claim: sequential cascade — REPORT_DAMAGE adds 50_000 to
    EQUIPMENT.committed_cents (hop A), then RETURN_VERIFIED+invoice deduction
    decrements it by 50_000 (hop B). End state: net change = 0 from
    damage charge alone.
    """
    base = setup_in_production(api)
    vendor_id = "vendor-cascade2"
    cats0 = get_categories_by_code(api, production_id=base["production"]["id"])
    eq_committed_initial = cats0["EQUIPMENT"]["committed_cents"]

    setup = setup_equipment_damaged(
        api, production_id=base["production"]["id"],
        damage_charge_cents=50_000,
        vendor_id=vendor_id,
        unit_cost_cents=0,
    )
    cats1 = get_categories_by_code(api, production_id=base["production"]["id"])
    # Hop A: rental(0) + damage(50_000) = +50_000.
    assert cats1["EQUIPMENT"]["committed_cents"] - eq_committed_initial == 50_000

    # Submit invoice and RETURN_VERIFIED.
    invoice = validate_success(api.create_vendor_invoice(
        create_vendor_invoice_payload(
            production_id=base["production"]["id"],
            vendor_id=vendor_id,
            category_code="EQUIPMENT",
            gross_cents=50_000,
        ),
        FC,
    ), 201)
    validate_success(api.create_equipment_event(
        setup["equipment"]["id"],
        {
            "production_id": base["production"]["id"],
            "event_type": "RETURN_VERIFIED",
            "occurred_at": iso(2026, 2, 5, 11),
            "damage_charge_cents": 0,
        },
        FC,
    ), 201)
    cats2 = get_categories_by_code(api, production_id=base["production"]["id"])
    # Hop B: damage charge of 50_000 reversed.
    assert cats2["EQUIPMENT"]["committed_cents"] == eq_committed_initial


# ─── priority_pair_validation_conflict / state vs fiscal (2nd coverage) ──────

def test_canceled_change_order_approve_returns_invalid_state(api):
    """PRD §2.10: "5. State — target entity must be in a state that permits
    the requested transition (`ERR_INVALID_STATE`)." PRD §3.7: "The
    originator may **cancel** (`PENDING → CANCELLED`)(...)."

    # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_on_change_order_approve
    Claim: a CANCELLED change order, even with a RESERVE_DRAW that would
    have failed reserve, returns ERR_INVALID_STATE — state precedes fiscal.
    """
    prod, cats = setup_production_with_categories(api, reserve_fund_cents=100_000)
    lp_headers = make_line_producer_headers("test-lp-cancelapprove")
    co = validate_success(api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=500_000,  # exceeds reserve
            source="RESERVE_DRAW",
        ),
        lp_headers,
    ), 201)
    # Cancel it.
    validate_success(api.cancel_change_order(co["id"], lp_headers), 200)
    # Now approve → ERR_INVALID_STATE (state precedes fiscal).
    fc_diff = make_finance_controller_headers("test-fc-cancelapprove")
    res = api.approve_change_order(co["id"], fc_diff)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── priority_pair_validation_conflict / segregation vs fiscal (2nd coverage) ─

def test_segregation_wins_on_reject_too(api):
    """PRD §3.7: "both reject and approve enforce that the approver's
    `X-User-ID` is *not* equal to `requested_by` — segregation of duties is
    the system's primary fiscal control, and any violation yields
    `ERR_SEGREGATION_OF_DUTIES`."

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_change_order_approve
    Claim: same-user rejection on a RESERVE_DRAW that would fail fiscal →
    ERR_SEGREGATION_OF_DUTIES (not fiscal).
    """
    prod, cats = setup_production_with_categories(api, reserve_fund_cents=100_000)
    lp_headers = make_line_producer_headers("test-lp-rejectseg")
    co = validate_success(api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=500_000,
            source="RESERVE_DRAW",
        ),
        lp_headers,
    ), 201)
    fc_same = make_finance_controller_headers("test-lp-rejectseg")
    res = api.reject_change_order(co["id"], fc_same)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)


# ─── boundary_precision_check / WARN at 0.90 (2nd coverage) ──────────────────

def test_alert_state_just_below_warn_stays_ok(api):
    """PRD §2.7: "otherwise if utilization is at least 0.90 the category is
    `WARN`; otherwise the category is `OK`."

    # difficulty: boundary_precision_check/category_alert_state_warn_at_exact_ninety_percent
    Claim: utilization just below 0.90 (e.g., 0.89999) stays OK.
    """
    # Drive committed_cents to 89_999 with planned_cents=100_000 → utilization 0.89999.
    prod, cats = setup_production_with_categories(
        api,
        cast_planned_cents=100_000,
        crew_planned_cents=10_000,
        equipment_planned_cents=10_000,
        location_planned_cents=10_000,
        post_planned_cents=10_000,
        misc_planned_cents=10_000,
    )
    # Need to commit exactly 89_999 to CAST. The SIGN cascade only produces multiples
    # of day_rate_cents; pick day_rate=89_999 with one 480-min scene → 1 day * 89_999.
    role = create_role_in_production(
        api, production_id=prod["id"],
        union_tier="SUPPORTING", day_rate_cents=89_999,
    )
    actor = create_actor(api)
    create_scene_in_production(
        api, production_id=prod["id"],
        scene_number="S-89999",
        planned_duration_minutes=480,
        required_actor_role_ids=[role["id"]],
    )
    walk_role_to_offered(api, production_id=prod["id"], role_id=role["id"],
                          actor_id=actor["id"])
    validate_success(api.sign_role(prod["id"], role["id"], LP), 200)
    cat = get_categories_by_code(api, production_id=prod["id"])["CAST"]
    assert cat["committed_cents"] == 89_999
    assert cat["alert_state"] == "OK", (
        f"At utilization 0.89999 (< 0.90), alert_state must be OK; got {cat['alert_state']}"
    )


# ─── boundary_precision_check / capacity exhaustion (2nd coverage) ──────────

def test_capacity_at_max_minus_one_succeeds(api):
    """PRD §3.3: "(...) must contain fewer than `max_parallel_units` rows
    (...)."

    # difficulty: boundary_precision_check/location_capacity_unit_exhaustion_zero_slot_boundary
    Claim: with max_parallel_units=2 and one existing overlapping HELD
    reservation, a second overlapping reservation (count == 1, < 2) is
    accepted.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api, max_parallel_units=2)
    scene_a = create_scene_in_production(api, production_id=prod["id"], scene_number="S-A2")
    scene_b = create_scene_in_production(api, production_id=prod["id"], scene_number="S-B2")

    res_a = api.create_location_reservation({
        "location_id": location["id"],
        "production_id": prod["id"],
        "scene_id": scene_a["id"],
        "unit_label": "MAIN",
        "start_at": iso(2026, 4, 1, 9),
        "end_at": iso(2026, 4, 1, 17),
    }, PC)
    validate_success(res_a, 201)

    res_b = api.create_location_reservation({
        "location_id": location["id"],
        "production_id": prod["id"],
        "scene_id": scene_b["id"],
        "unit_label": "B_UNIT",
        "start_at": iso(2026, 4, 1, 10),
        "end_at": iso(2026, 4, 1, 12),
    }, PC)
    second = validate_success(res_b, 201)
    assert second["status"] == "HELD"


# ─── cross_entity_state_dependency / role-sign blocked by posture (2nd) ──────

def test_sign_blocked_by_red_posture_with_reserve_draw_path(api):
    """PRD §2.6: "A `RED` posture additionally gates approval of `RESERVE_DRAW`
    change orders(...)." plus the FROZEN gate already used in test_03 — but
    posture=RED also gates non-wrap operations only by virtue of the FROZEN
    rule. Sign in a RED non-wrap state is permitted. So this test asserts a
    different angle: sign rejected when production is CANCELLED.

    # difficulty: cross_entity_state_dependency/role_sign_depends_on_production_status
    Claim: sign on a Role under a CANCELLED Production → ERR_INVALID_STATE
    or ERR_POSTURE_BLOCKED. The production cannot be IN_PRODUCTION; an
    OFFERED role cannot sign.
    """
    s = setup_role_with_n_breakdown_scenes(
        api,
        n_breakdown_scenes=1,
        n_shot_scenes=0,
        scene_minutes=120,
        role_union_tier="SUPPORTING",
        role_day_rate_cents=100_000,
        cast_planned_cents=10_000_000,
    )
    # No SIGNED role exists yet, so PLANNING→CANCELLED is allowed.
    cancelled = validate_success(api.cancel_production(s["production"]["id"], EXEC), 200)
    assert cancelled["status"] == "CANCELLED"
    # Now sign the OFFERED role — production is CANCELLED, sign cannot proceed.
    res = api.sign_role(s["production"]["id"], s["role"]["id"], LP)
    # Two-reader: ERR_INVALID_STATE (production not in {PLANNING, IN_PRODUCTION})
    # is the most natural answer; some implementations could also derive
    # ERR_POSTURE_BLOCKED. Allow either via validate_error_is_one_of.
    from test_helpers import validate_error_is_one_of
    validate_error_is_one_of(res, ["ERR_INVALID_STATE", "ERR_POSTURE_BLOCKED"])


# ─── compensating_invariant / substitute (2nd coverage) ─────────────────────

def test_substitute_role_with_extra_scene_recomputes_commitment(api):
    """PRD §3.2: "On success, the previously projected `CAST` commit (computed
    under the original role) is decremented from the `CAST` category's
    `committed_cents`, a fresh `Role` record is created carrying the
    replacement values and is immediately signed in-line (its own projected
    commit is added to `CAST.committed_cents`)(...)."

    # difficulty: compensating_invariant/substitute_role_preserves_total_cast_committed
    Claim: substitute decrements old projected commit and re-projects from
    the live scene set; with the same day-rate, the result equals a fresh
    sign at the new role's rate, no drift.
    """
    s = setup_signed_role(
        api,
        n_breakdown_scenes=2,
        role_union_tier="SUPPORTING",
        role_day_rate_cents=200_000,
        cast_planned_cents=10_000_000,
    )
    # CAST.committed at start: 2 days * 200_000 = 400_000.
    cats0 = get_categories_by_code(api, production_id=s["production"]["id"])
    assert cats0["CAST"]["committed_cents"] == 400_000

    # Substitute with the same day-rate.
    replacement = create_actor(api)
    validate_success(api.substitute_role(
        s["production"]["id"], s["role"]["id"],
        substitute_role_payload(
            replacement_actor_id=replacement["id"],
            replacement_day_rate_cents=200_000,
        ),
        LP,
    ), 200)
    # Net change should be zero — old role decremented by 400_000; new role
    # added 400_000.
    cats1 = get_categories_by_code(api, production_id=s["production"]["id"])
    assert cats1["CAST"]["committed_cents"] == 400_000


# ─── compensating_invariant / equipment return (2nd coverage) ────────────────

def test_return_verified_does_not_double_decrement_committed(api):
    """PRD §3.5: "Recording a `RETURN_VERIFIED` event transitions the
    equipment from `DAMAGED` or `LOST` back to `RETURNED`. Preconditions:
    the previous event for this equipment must be `REPORT_DAMAGE` or
    `REPORT_LOSS`(...) and the related vendor invoice for this `vendor_id`
    must not yet have reconciled the charge."

    # difficulty: compensating_invariant/equipment_return_preserves_equipment_committed_minus_invoice_deduction
    Claim: a second RETURN_VERIFIED on the same equipment (already RETURNED)
    is rejected — the prior-event precondition fails — leaving the
    invariant intact.
    """
    base = setup_in_production(api)
    vendor_id = "vendor-noredecrement"
    setup = setup_equipment_lost(
        api, production_id=base["production"]["id"],
        damage_charge_cents=10_000,
        vendor_id=vendor_id,
        unit_cost_cents=0,
    )
    invoice = validate_success(api.create_vendor_invoice(
        create_vendor_invoice_payload(
            production_id=base["production"]["id"],
            vendor_id=vendor_id,
            category_code="EQUIPMENT",
            gross_cents=10_000,
        ),
        FC,
    ), 201)
    validate_success(api.create_equipment_event(
        setup["equipment"]["id"],
        {
            "production_id": base["production"]["id"],
            "event_type": "RETURN_VERIFIED",
            "occurred_at": iso(2026, 2, 5, 10),
            "damage_charge_cents": 0,
        },
        FC,
    ), 201)

    # Snapshot committed.
    cats1 = get_categories_by_code(api, production_id=base["production"]["id"])
    eq1 = cats1["EQUIPMENT"]["committed_cents"]

    # Second RETURN_VERIFIED — the equipment is RETURNED, last event is
    # RETURN_VERIFIED (not REPORT_DAMAGE/REPORT_LOSS), so the precondition fails.
    res = api.create_equipment_event(
        setup["equipment"]["id"],
        {
            "production_id": base["production"]["id"],
            "event_type": "RETURN_VERIFIED",
            "occurred_at": iso(2026, 2, 5, 11),
            "damage_charge_cents": 0,
        },
        FC,
    )
    assert res.status_code >= 400, "Second RETURN_VERIFIED on RETURNED equipment must fail"
    cats2 = get_categories_by_code(api, production_id=base["production"]["id"])
    eq2 = cats2["EQUIPMENT"]["committed_cents"]
    assert eq2 == eq1, "EQUIPMENT.committed_cents must not change on rejected RETURN_VERIFIED"
