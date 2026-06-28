"""Second-pass coverage for each difficulty instance: a complementary scenario
or boundary partner that asserts the same PRD rule from a distinct angle."""
import pytest

from test_helpers import (
    api_client as api, get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_technician_headers,
    create_active_pricing_config, create_home_with_systems, create_home_with_active_plan,
    create_crew, create_quoted_work_order, create_scheduled_work_order,
    create_in_progress_work_order, create_completed_work_order, complete, quote, inspect,
    create_route, commit, enroll_plan,
    NON_EXISTENT_UUID, duct_line, dryer_line,
)

PA = TEST_USERS["plan_admin_headers"]
DI = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# dual_variant_calc
# ===========================================================================
def test_invoice_equals_estimate_when_lines_and_home_unchanged():
    """PRD §3.8: "When the performed lines match the requested lines and the home's
    counts have not changed, the invoice equals the estimate; otherwise the two
    figures legitimately differ."

    Design: Difficulty/dual_variant_calc/dual_variant_estimate_vs_invoice_diverge_on_system_change
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(3, register_count=8, zone_code="Z1",
                                            square_footage=2000)
    crew = create_crew(home_zone_code="Z1", certified_for_uv=True)
    lines = [duct_line(systems[0]["id"]), dryer_line()]
    wo, route = create_in_progress_work_order(
        home["id"], lines, crew["id"], scheduled_start_minute=540, addons=["UV"],
        inspect_overrides={"before_photo_count": 3, "dust_severity": 5},
        service_date="2026-06-10")
    estimate = wo["estimate_total_cents"]
    completed = complete(wo["id"], crew["id"],
                        [duct_line(systems[0]["id"]), dryer_line()],
                        after_photo_count=4, dust_severity=5, performed_addons=["UV"])
    assert completed["invoice_total_cents"] == estimate, \
        f"unchanged lines/home: invoice {completed['invoice_total_cents']} must equal estimate {estimate}"


def test_referral_severity_snapshot_tracks_after_inspection_not_invoice():
    """PRD §3.10: "severity_at_referral, a snapshot of the AFTER inspection's
    dust_severity at referral time."

    Design: Difficulty/dual_variant_calc/dual_variant_cost_vs_contamination_risk_different_domains
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(3, register_count=8, zone_code="Z1",
                                            square_footage=1800)
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_in_progress_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"], scheduled_start_minute=600,
        inspect_overrides={"before_photo_count": 2, "dust_severity": 6},
        service_date="2026-06-11")
    # AFTER severity 7 differs from the BEFORE severity 6 and from any cost figure.
    complete(wo["id"], crew["id"], [duct_line(systems[0]["id"])],
             after_photo_count=3, dust_severity=7, recommend_hvac_repair=True)
    referrals, _ = validate_paginated(
        api.list_upsell_referrals(PA, params={"work_order_id": wo["id"]}))
    assert referrals[0]["severity_at_referral"] == 7, \
        f"severity_at_referral must snapshot AFTER severity 7, got {referrals[0]['severity_at_referral']}"


# ===========================================================================
# combinatorial_formula
# ===========================================================================
def test_duration_no_big_home_factor_when_single_system_high_sqft():
    """PRD §3.5: "a non-linear "big-home" surcharge then applies, but only to the
    per-line component and only when two conditions hold together: the home's
    active system count is at least two and the home's square_footage is at least
    three thousand."

    Design: Difficulty/combinatorial_formula/combinatorial_duration_nonlinear_big_home_factor
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=6, zone_code="Z1",
                                            square_footage=3500)
    crew = create_crew(home_zone_code="Z1", certified_for_uv=True)
    lines = [duct_line(systems[0]["id"]), dryer_line()]
    wo = create_quoted_work_order(home["id"], lines, crew["id"], addons=["UV"],
                                 inspect_overrides={"before_photo_count": 2, "dust_severity": 5})
    # n=1 so no factor: per_line 60 + setup 20 + addon 10 = 90.
    assert wo["duration_minutes"] == 90, \
        f"single-system high-sqft must NOT apply factor: expected 90, got {wo['duration_minutes']}"


def test_estimate_round_per_step_single_duct_with_plan():
    """PRD §2.7: "the multi-system discount is rounded, then the plan-member
    discount is rounded, then the tax is rounded, and only then are the rounded
    parts summed."

    Design: Difficulty/combinatorial_formula/combinatorial_estimate_pinned_eval_order_discount_then_plan_then_tax
    """
    create_active_pricing_config()
    home, systems, plan = create_home_with_active_plan(cadence_months=12, num_systems=1,
                                                      register_count=5, zone_code="Z1",
                                                      square_footage=1500)
    crew = create_crew(home_zone_code="Z1")
    wo = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                 inspect_overrides={"before_photo_count": 1, "dust_severity": 2})
    # n=1: duct 12000 (no multi-sys discount); plan discount round(12000*0.85)=10200;
    # tax round(10200*0.08)=816; total 11016.
    assert wo["estimate_total_cents"] == 11016, \
        f"Expected 11016 (plan-discount then tax, rounded per step), got {wo['estimate_total_cents']}"


# ===========================================================================
# non_linear_state_machine
# ===========================================================================
def test_requote_after_reinspect_repins_pricing_config():
    """PRD §3.3: "On a successful quote the active config's id is pinned onto the
    work order as pricing_config_id, capturing a snapshot of the price book for
    the rest of this work order's life."

    Design: Difficulty/non_linear_state_machine/nonlinear_work_order_reinspect_cycle
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    tech = make_technician_headers(crew["id"])
    wo = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                 inspect_overrides={"before_photo_count": 2, "dust_severity": 4})
    get_success_data(api.inspect_work_order(wo["id"], {"before_photo_count": 5, "dust_severity": 7}, tech))
    requoted = validate_success(api.quote_work_order(wo["id"], tech), expected_status=200)
    assert requoted["status"] == "QUOTED"
    assert requoted["pricing_config_id"] is not None, \
        "re-quote must re-pin pricing_config_id"


def test_resolve_already_resolved_ticket_rejected_bad_state():
    """PRD §3.11: "A transition attempted on a ticket not in the required state is
    rejected with ERR_TICKET_BAD_STATE."

    Design: Difficulty/non_linear_state_machine/nonlinear_callback_ticket_reopen_cycle
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_completed_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"],
        inspect_overrides={"before_photo_count": 2, "dust_severity": 3},
        complete_overrides={"after_photo_count": 2, "dust_severity": 3},
        service_date="2026-06-12")
    ticket = get_success_data(api.create_callback_ticket(
        {"work_order_id": wo["id"], "reason": "redo"}, DI))
    get_success_data(api.resolve_callback_ticket(ticket["id"], DI))
    # Ticket is RESOLVED; resolving again is not a valid transition.
    resp = api.resolve_callback_ticket(ticket["id"], DI)
    validate_error(resp, ApiErrorId.ERR_TICKET_BAD_STATE.value)


# ===========================================================================
# transitive_cascade
# ===========================================================================
def test_no_referral_when_recommend_repair_false():
    """PRD §3.8: "if the AFTER inspection's recommend_hvac_repair is true, the
    system creates an UpsellReferral in PENDING status"

    Design: Difficulty/transitive_cascade/cascade_depth3_complete_triggers_referral_touches_home
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(3, register_count=8, zone_code="Z1",
                                            square_footage=1700)
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_in_progress_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"],
        inspect_overrides={"before_photo_count": 2, "dust_severity": 6},
        service_date="2026-06-13")
    complete(wo["id"], crew["id"], [duct_line(systems[0]["id"])],
             after_photo_count=3, dust_severity=4, recommend_hvac_repair=False)
    _, meta = validate_paginated(
        api.list_upsell_referrals(PA, params={"work_order_id": wo["id"]}))
    assert meta["total_count"] == 0, \
        f"no referral expected when recommend_hvac_repair is false, got {meta['total_count']}"


def test_cancel_recomputes_home_has_active_plan_to_false():
    """PRD §3.9: "Pausing, resuming, and cancelling each recompute the home's
    has_active_plan and cascade to the home — pause and cancel can drop it to
    false (when no other active plan remains)"

    Design: Difficulty/transitive_cascade/cascade_depth2_decommission_recomputes_active_count_and_plan_flag
    """
    home, systems, plan = create_home_with_active_plan(cadence_months=6, num_systems=1,
                                                      register_count=5, zone_code="Z1")
    cancelled = validate_success(api.cancel_recurring_plan(plan["id"], PA), expected_status=200)
    assert cancelled["lifecycle_status"] == "CANCELLED"
    home_after = get_success_data(api.get_home(home["id"], PA))
    assert home_after["has_active_plan"] is False, \
        "cancel must drop has_active_plan to false"


# ===========================================================================
# priority_pair_validation_conflict
# ===========================================================================
def test_commit_state_check_beats_zone_match_check():
    """PRD §2.10: "Sixth, the target resource's own state is checked against the
    requested transition."
    PRD §2.10: "Only after all of those do the domain-specific business rules run:
    crew UV certification, zone matching, shift-window containment, slot overlap,
    crew double-booking, the after-photo minimum, active-pricing-config rules, the
    one-plan-per-home rule, and finally the optimistic-concurrency version checks."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_business_safety_on_commit
    """
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z2")
    crew = create_crew(home_zone_code="Z1")
    route = create_route(crew["id"], zone_code="Z1", service_date="2026-06-14")
    # DRAFT (un-quoted) work order whose home zone (Z2) also mismatches the route (Z1).
    wo = get_success_data(api.create_work_order(
        {"home_id": home["id"], "service_lines": [duct_line(systems[0]["id"])],
         "requested_start_minute": 540}, DI))
    resp = api.commit_slot(route["id"],
                          {"work_order_id": wo["id"], "scheduled_start_minute": 540,
                           "expected_route_plan_version": route["version"]}, DI)
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_BAD_STATE.value)


def test_commit_path_route_existence_beats_body_checks():
    """PRD §2.6: "The system validates path identifiers left to right and rejects
    on the first one that does not resolve, before evaluating any deeper identifier
    or any business rule."
    PRD §2.6: "a missing route yields ERR_ROUTE_NOT_FOUND"

    Design: Difficulty/priority_pair_validation_conflict/priority_existence_beats_business_temporal_on_commit
    """
    resp = api.commit_slot(NON_EXISTENT_UUID,
                          {"work_order_id": NON_EXISTENT_UUID, "scheduled_start_minute": 540,
                           "expected_route_plan_version": 1}, DI)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_FOUND.value)


# ===========================================================================
# boundary_precision_check
# ===========================================================================
def test_quote_zero_systems_below_threshold_total():
    """PRD §3.4: "where that per-line price is duct_base_cents plus
    duct_per_system_cents times the number of active systems beyond the first —
    that is, the greater of zero and the active system count minus one."

    Design: Difficulty/boundary_precision_check/boundary_multi_system_discount_triggers_at_two_not_one
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(3, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                 inspect_overrides={"before_photo_count": 1, "dust_severity": 2})
    # n=3: per-line 12000 + 2*4000 = 20000; discount round(20000*0.9)=18000;
    # tax round(18000*0.08)=1440; total 19440.
    assert wo["estimate_total_cents"] == 19440, \
        f"n=3 discounted duct line: expected 19440, got {wo['estimate_total_cents']}"


def test_lock_succeeds_once_route_has_committed_minutes():
    """PRD §3.6: "a route may only be locked once its committed_minutes is greater
    than zero"

    Design: Difficulty/boundary_precision_check/boundary_lock_rejects_empty_route_zero_committed_minutes
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_scheduled_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"], scheduled_start_minute=540,
        inspect_overrides={"before_photo_count": 1, "dust_severity": 2},
        service_date="2026-06-16")
    assert route["committed_minutes"] == 55
    locked = validate_success(api.lock_route_plan(route["id"], DI), expected_status=200)
    assert locked["status"] == "LOCKED"


# ===========================================================================
# cross_entity_state_dependency
# ===========================================================================
def test_start_succeeds_once_route_locked():
    """PRD §3.8: "Once a route is locked, a Technician begins a scheduled work
    order, advancing it SCHEDULED → IN_PROGRESS."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_start_requires_route_locked
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_scheduled_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"], scheduled_start_minute=540,
        inspect_overrides={"before_photo_count": 2, "dust_severity": 4},
        service_date="2026-06-17")
    get_success_data(api.lock_route_plan(route["id"], DI))
    started = validate_success(
        api.start_work_order(wo["id"], make_technician_headers(crew["id"])),
        expected_status=200)
    assert started["status"] == "IN_PROGRESS"


def test_resolve_succeeds_once_work_order_completed():
    """PRD §3.11: "A Dispatcher resolves an OPEN or REOPENED ticket, moving it to
    RESOLVED, but only if the referenced work order's status is COMPLETED"

    Design: Difficulty/cross_entity_state_dependency/cross_entity_resolve_requires_work_order_completed
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_completed_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"],
        inspect_overrides={"before_photo_count": 2, "dust_severity": 4},
        complete_overrides={"after_photo_count": 2, "dust_severity": 4},
        service_date="2026-06-18")
    ticket = get_success_data(api.create_callback_ticket(
        {"work_order_id": wo["id"], "reason": "after the fact"}, DI))
    resolved = validate_success(api.resolve_callback_ticket(ticket["id"], DI), expected_status=200)
    assert resolved["status"] == "RESOLVED"


# ===========================================================================
# resource_temporal_overlap
# ===========================================================================
def test_commit_succeeds_with_buffer_sized_gap():
    """PRD §3.7: "two slots which merely touch with zero gap do collide once the
    buffer is applied; adjacent slots therefore need a gap of at least fifteen
    minutes between them."

    Design: Difficulty/resource_temporal_overlap/overlap_buffer_extended_slot_collision_on_route
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo1, route = create_scheduled_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"], scheduled_start_minute=540,
        inspect_overrides={"before_photo_count": 1, "dust_severity": 3},
        service_date="2026-06-19")
    # wo1 occupies [540,595); a 15-min gap means the next slot may start at 610.
    wo2 = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                  requested_start_minute=610,
                                  inspect_overrides={"before_photo_count": 1, "dust_severity": 3})
    route_now = get_success_data(api.get_route_plan(route["id"], DI))
    committed = validate_success(
        api.commit_slot(route_now["id"],
                       {"work_order_id": wo2["id"], "scheduled_start_minute": 610,
                        "expected_route_plan_version": route_now["version"]}, DI),
        expected_status=200)
    assert committed["status"] == "SCHEDULED"


def test_crew_non_overlapping_windows_same_date_allowed():
    """PRD §3.6: "the chosen crew member must not already own another route on the
    same service_date whose shift window overlaps the new one."

    Design: Difficulty/resource_temporal_overlap/overlap_crew_double_booked_across_routes_same_date
    """
    crew = create_crew(home_zone_code="Z1")
    create_route(crew["id"], zone_code="Z1", service_date="2026-06-20",
                 shift_start_minute=480, shift_end_minute=600)
    # Second window [601,720] does not overlap [480,600].
    resp = api.create_route_plan(
        {"crew_member_id": crew["id"], "zone_code": "Z1", "service_date": "2026-06-20",
         "shift_start_minute": 601, "shift_end_minute": 720}, DI)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "OPEN"


# ===========================================================================
# compensating_invariant
# ===========================================================================
def test_committed_minutes_no_drift_after_cancel_then_recommit():
    """PRD §3.7: "the incremental running total must always equal a full
    recomputation over that filtered set. The two are reconciled so that a commit
    of some duration paired with its compensating cancel of the same duration
    leaves committed_minutes exactly where it began."

    Design: Difficulty/compensating_invariant/compensating_route_committed_minutes_restored_on_cancel
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo1, route = create_scheduled_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"], scheduled_start_minute=540,
        inspect_overrides={"before_photo_count": 1, "dust_severity": 3},
        service_date="2026-06-21")
    get_success_data(api.cancel_work_order(wo1["id"], DI))
    # A second, fresh commit must land committed_minutes at exactly 55 — no residue.
    wo2 = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                  requested_start_minute=700,
                                  inspect_overrides={"before_photo_count": 1, "dust_severity": 3})
    route_now = get_success_data(api.get_route_plan(route["id"], DI))
    commit(route_now["id"], wo2["id"], 700, route_now["version"])
    final = get_success_data(api.get_route_plan(route["id"], DI))
    assert final["committed_minutes"] == 55, \
        f"no drift: committed_minutes must be 55 after cancel+recommit, got {final['committed_minutes']}"


def test_resume_restores_plan_membership_so_reenroll_blocked():
    """PRD §3.9: "A home may hold at most one plan whose lifecycle_status is ACTIVE
    or PAUSED at a time; a second enrollment attempt is rejected with
    ERR_PLAN_ALREADY_EXISTS."

    Design: Difficulty/compensating_invariant/compensating_pricing_config_active_count_invariant
    """
    home, systems, plan = create_home_with_active_plan(cadence_months=12, num_systems=1,
                                                      register_count=5, zone_code="Z1")
    get_success_data(api.pause_recurring_plan(plan["id"], PA))
    get_success_data(api.resume_recurring_plan(plan["id"], PA))
    home_now = get_success_data(api.get_home(home["id"], PA))
    assert home_now["has_active_plan"] is True
    resp = api.create_recurring_plan(
        home["id"], {"cadence_months": 6, "expected_home_version": home_now["version"]}, PA)
    validate_error(resp, ApiErrorId.ERR_PLAN_ALREADY_EXISTS.value)
