"""Work-order revision cycles, completion cascades, and cross-entity state guards."""
import pytest

from test_helpers import (
    api_client as api, get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_technician_headers,
    create_active_pricing_config, create_home_with_systems, create_home_with_active_plan,
    create_crew, create_quoted_work_order, create_scheduled_work_order,
    create_in_progress_work_order, create_completed_work_order, complete, inspect, quote,
    enroll_plan, set_clock,
    duct_line, dryer_line,
)

PA = TEST_USERS["plan_admin_headers"]
DI = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Difficulty: non_linear_state_machine
# ===========================================================================
def test_reinspect_clears_estimate_and_pricing_config_then_requote():
    """PRD §3.3: "a Technician re-inspects it, advancing it QUOTED → INSPECTED,
    which replaces the BEFORE inspection row with a fresh one from the new inspect
    body and clears both estimate_total_cents and pricing_config_id back to null
    so a re-quote is required."

    Design: Difficulty/non_linear_state_machine/nonlinear_work_order_reinspect_cycle
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1",
                                            square_footage=1500)
    crew = create_crew(home_zone_code="Z1")
    wo = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                 inspect_overrides={"before_photo_count": 2, "dust_severity": 4})
    assert wo["status"] == "QUOTED"

    tech = make_technician_headers(crew["id"])
    reinspected = validate_success(
        api.inspect_work_order(wo["id"], {"before_photo_count": 5, "dust_severity": 7}, tech),
        expected_status=200)
    assert reinspected["status"] == "INSPECTED"
    assert reinspected["estimate_total_cents"] is None, \
        f"re-inspect must clear estimate, got {reinspected['estimate_total_cents']}"
    assert reinspected["pricing_config_id"] is None, \
        f"re-inspect must clear pricing_config_id, got {reinspected['pricing_config_id']}"

    requoted = validate_success(api.quote_work_order(wo["id"], tech), expected_status=200)
    assert requoted["status"] == "QUOTED"
    assert requoted["estimate_total_cents"] == 12960, \
        f"second quote must recompute estimate 12960, got {requoted['estimate_total_cents']}"


def test_callback_ticket_reopen_then_resolve_cycle():
    """PRD §3.11: "A resolved ticket may be reopened by a dispatcher, moving
    RESOLVED → REOPENED, and a reopened ticket may then be resolved again
    (REOPENED → RESOLVED), forming a revision loop."

    Design: Difficulty/non_linear_state_machine/nonlinear_callback_ticket_reopen_cycle
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_completed_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"],
        inspect_overrides={"before_photo_count": 2, "dust_severity": 3},
        complete_overrides={"after_photo_count": 2, "dust_severity": 3},
        service_date="2026-04-12")
    ticket = get_success_data(api.create_callback_ticket(
        {"work_order_id": wo["id"], "reason": "Still dusty", "redo_required": True}, DI))
    get_success_data(api.resolve_callback_ticket(ticket["id"], DI))

    reopened = validate_success(api.reopen_callback_ticket(ticket["id"], DI), expected_status=200)
    assert reopened["status"] == "REOPENED"
    resolved = validate_success(api.resolve_callback_ticket(ticket["id"], DI), expected_status=200)
    assert resolved["status"] == "RESOLVED"


# ===========================================================================
# Difficulty: transitive_cascade
# ===========================================================================
def test_complete_creates_pending_referral_and_touches_home():
    """PRD §3.8: "if the AFTER inspection's recommend_hvac_repair is true, the
    system creates an UpsellReferral in PENDING status; that referral is born from
    the originating work order and home and snapshots the after-inspection
    severity, and its creation touches the home denormalization so the home's
    updated_at is refreshed."

    Design: Difficulty/transitive_cascade/cascade_depth3_complete_triggers_referral_touches_home
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(3, register_count=8, zone_code="Z1",
                                            square_footage=1700)
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_in_progress_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"],
        inspect_overrides={"before_photo_count": 2, "dust_severity": 6},
        service_date="2026-04-13")
    home_before = get_success_data(api.get_home(home["id"], DI))["version"]

    complete(wo["id"], crew["id"], [duct_line(systems[0]["id"])],
             after_photo_count=3, dust_severity=4, recommend_hvac_repair=True)

    referrals, _ = validate_paginated(
        api.list_upsell_referrals(PA, params={"work_order_id": wo["id"]}))
    assert len(referrals) == 1, f"expected one referral, got {len(referrals)}"
    ref = referrals[0]
    assert ref["status"] == "PENDING"
    assert ref["home_id"] == home["id"]

    # PRD §2.5: touching the home as a cascade mutates it — "its updated_at is
    # refreshed and its version increases by one". The version bump is the
    # deterministic observable of the denormalization touch (the logical clock is
    # frozen, so updated_at refreshes to the same instant).
    home_after = get_success_data(api.get_home(home["id"], DI))["version"]
    assert home_after > home_before, \
        f"Home.version must advance via referral cascade ({home_before} -> {home_after})"


def test_pause_recomputes_home_has_active_plan_to_false():
    """PRD §3.9: "Pausing, resuming, and cancelling each recompute the home's
    has_active_plan and cascade to the home — pause and cancel can drop it to
    false (when no other active plan remains)"

    Design: Difficulty/transitive_cascade/cascade_depth2_decommission_recomputes_active_count_and_plan_flag
    """
    home, systems, plan = create_home_with_active_plan(cadence_months=6, num_systems=1,
                                                      register_count=5, zone_code="Z1")
    paused = validate_success(api.pause_recurring_plan(plan["id"], PA), expected_status=200)
    assert paused["lifecycle_status"] == "PAUSED"

    home_after = get_success_data(api.get_home(home["id"], PA))
    assert home_after["has_active_plan"] is False, \
        "has_active_plan must drop to false after pause"
    assert home_after["active_system_count"] == 1


# ===========================================================================
# Difficulty: cross_entity_state_dependency
# ===========================================================================
def test_start_rejected_while_route_open():
    """PRD §3.8: "the route that the work order is committed to must be LOCKED
    before any work starts, else ERR_ROUTE_NOT_LOCKED."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_start_requires_route_locked
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_scheduled_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"], scheduled_start_minute=540,
        inspect_overrides={"before_photo_count": 2, "dust_severity": 4},
        service_date="2026-04-17")
    assert wo["status"] == "SCHEDULED"
    resp = api.start_work_order(wo["id"], make_technician_headers(crew["id"]))
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_LOCKED.value)


def test_resolve_rejected_while_work_order_not_completed():
    """PRD §3.11: "A Dispatcher resolves an OPEN or REOPENED ticket, moving it to
    RESOLVED, but only if the referenced work order's status is COMPLETED;
    otherwise the resolve is rejected with ERR_WORK_ORDER_NOT_COMPLETED."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_resolve_requires_work_order_completed
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_in_progress_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"],
        inspect_overrides={"before_photo_count": 2, "dust_severity": 4},
        service_date="2026-04-18")
    assert wo["status"] == "IN_PROGRESS"
    ticket = get_success_data(api.create_callback_ticket(
        {"work_order_id": wo["id"], "reason": "Premature complaint"}, DI))
    resp = api.resolve_callback_ticket(ticket["id"], DI)
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_COMPLETED.value)


# ===========================================================================
# Corner: state_machines
# ===========================================================================
def test_inspect_from_completed_rejected_bad_state():
    """PRD §3.3: "A work order whose status is not the one required for the
    requested transition is rejected with ERR_WORK_ORDER_BAD_STATE."

    Design: Corner/state_machines/sm_inspect_from_completed_returns_bad_state
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_completed_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"],
        inspect_overrides={"before_photo_count": 1, "dust_severity": 2},
        complete_overrides={"after_photo_count": 2, "dust_severity": 2},
        service_date="2026-04-22")
    assert wo["status"] == "COMPLETED"
    resp = api.inspect_work_order(wo["id"], {"before_photo_count": 9, "dust_severity": 9},
                                 make_technician_headers(crew["id"]))
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_BAD_STATE.value)


def test_new_work_order_starts_in_draft():
    """PRD §3.3: "A new work order starts in DRAFT."

    Design: Corner/state_machines/sm_work_order_initial_state_is_draft
    """
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    resp = api.create_work_order(
        {"home_id": home["id"],
         "service_lines": [duct_line(systems[0]["id"])],
         "requested_start_minute": 540}, DI)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"


def test_close_blocked_by_scheduled_work_order():
    """PRD §3.6: "A locked route is closed by a dispatcher, moving LOCKED → CLOSED,
    but only once every committed work order has settled: if any committed work
    order is still SCHEDULED or IN_PROGRESS, the close is rejected with
    ERR_ROUTE_HAS_OPEN_WORK."

    Design: Corner/state_machines/sm_route_close_blocked_by_open_work
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_scheduled_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"], scheduled_start_minute=540,
        inspect_overrides={"before_photo_count": 1, "dust_severity": 2},
        service_date="2026-04-23")
    get_success_data(api.lock_route_plan(route["id"], DI))
    resp = api.close_route_plan(route["id"], DI)
    validate_error(resp, ApiErrorId.ERR_ROUTE_HAS_OPEN_WORK.value)


def test_clock_advance_marks_reminder_due():
    """PRD §3.9: "A waiting reminder becomes DUE when the logical clock reaches or
    passes next_reminder_at, provided the plan's lifecycle_status is ACTIVE"

    Design: Corner/state_machines/sm_clock_advance_marks_reminder_due
    """
    home, systems, plan = create_home_with_active_plan(cadence_months=6, num_systems=1,
                                                      register_count=5, zone_code="Z1")
    # enrolled_at default 2026-04-01 -> next_reminder_at 2026-10-01; advance past it.
    set_clock("2026-10-02T00:00:00Z")
    refreshed = validate_success(api.refresh_reminder(plan["id"], PA), expected_status=200)
    assert refreshed["reminder_status"] == "DUE"


def test_decline_pending_referral_branch():
    """PRD §3.10: "A PlanAdmin may decline it, moving PENDING → DECLINED, which
    records an explicit operator decision."

    Design: Corner/state_machines/sm_referral_decline_branch
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_completed_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"],
        inspect_overrides={"before_photo_count": 1, "dust_severity": 5},
        complete_overrides={"after_photo_count": 2, "dust_severity": 5,
                            "recommend_hvac_repair": True},
        service_date="2026-04-24")
    referrals, _ = validate_paginated(
        api.list_upsell_referrals(PA, params={"work_order_id": wo["id"]}))
    ref = referrals[0]
    declined = validate_success(api.decline_referral(ref["id"], PA), expected_status=200)
    assert declined["status"] == "DECLINED"


def test_acknowledge_advances_next_reminder_by_cadence():
    """PRD §3.9: "The advance adds the plan's cadence_months to the prior
    next_reminder_at — not to the current clock — so the cadence never drifts
    across cycles"

    Design: Corner/state_machines/sm_acknowledge_advances_next_reminder_by_cadence
    """
    home, systems, plan = create_home_with_active_plan(cadence_months=6, num_systems=1,
                                                      register_count=5, zone_code="Z1")
    set_clock("2026-10-05T00:00:00Z")
    get_success_data(api.refresh_reminder(plan["id"], PA))
    acked = validate_success(api.acknowledge_reminder(plan["id"], PA), expected_status=200)
    # prior next_reminder_at 2026-10-01 + 6 months = 2027-04-01.
    assert acked["next_reminder_at"] == "2027-04-01T00:00:00.000Z", \
        f"Expected next_reminder_at 2027-04-01T00:00:00.000Z, got {acked['next_reminder_at']}"
    assert acked["reminder_status"] == "WAITING"
