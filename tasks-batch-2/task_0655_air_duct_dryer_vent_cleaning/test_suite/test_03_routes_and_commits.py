"""Route lifecycle, slot commitment geometry, crew booking, OCC, and the ledger."""
import pytest

from test_helpers import (
    api_client as api, get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_technician_headers,
    create_active_pricing_config, create_home_with_systems, create_crew,
    create_quoted_work_order, create_scheduled_work_order, create_route, commit,
    create_work_order,
    NON_EXISTENT_UUID, duct_line,
)

PA = TEST_USERS["plan_admin_headers"]
DI = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Difficulty: priority_pair_validation_conflict
# ===========================================================================
def test_commit_state_check_beats_uv_certification_check():
    """PRD §2.10: "the target resource's own state is checked against the requested
    transition. Seventh, cross-entity state guards are evaluated. Only after all of
    those do the domain-specific business rules run: crew UV certification, zone
    matching, shift-window containment, slot overlap"
    PRD §3.6: "The work order must be QUOTED, else ERR_WORK_ORDER_BAD_STATE."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_business_safety_on_commit
    """
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1", certified_for_uv=False)
    route = create_route(crew["id"], zone_code="Z1", service_date="2026-04-14")
    # DRAFT (un-quoted) work order carrying a UV add-on.
    wo = get_success_data(api.create_work_order(
        {"home_id": home["id"], "service_lines": [duct_line(systems[0]["id"])],
         "addons": ["UV"], "requested_start_minute": 540}, DI))
    resp = api.commit_slot(route["id"],
                          {"work_order_id": wo["id"], "scheduled_start_minute": 540,
                           "expected_route_plan_version": route["version"]}, DI)
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_BAD_STATE.value)


def test_commit_existence_check_beats_slot_overlap_check():
    """PRD §2.10: "The practical effect is that a structural problem is always
    reported ahead of a business-rule problem, and a state problem is reported
    ahead of a fiscal one."
    PRD §2.6: "A create whose body references a non-existent homeowner, home, crew
    member, work order, or callback ticket is rejected with the corresponding
    not-found error"

    Design: Difficulty/priority_pair_validation_conflict/priority_existence_beats_business_temporal_on_commit
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo1, route = create_scheduled_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"], scheduled_start_minute=540,
        inspect_overrides={"before_photo_count": 2, "dust_severity": 4},
        service_date="2026-04-15")
    route_now = get_success_data(api.get_route_plan(route["id"], DI))
    # Commit a non-existent work order at a slot that would also overlap.
    resp = api.commit_slot(route["id"],
                          {"work_order_id": NON_EXISTENT_UUID, "scheduled_start_minute": 545,
                           "expected_route_plan_version": route_now["version"]}, DI)
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND.value)


# ===========================================================================
# Difficulty: boundary_precision_check (empty-route lock)
# ===========================================================================
def test_lock_rejects_empty_route():
    """PRD §3.6: "a route may only be locked once its committed_minutes is greater
    than zero, so an empty route cannot be locked and the attempt fails with
    ERR_ROUTE_EMPTY."

    Design: Difficulty/boundary_precision_check/boundary_lock_rejects_empty_route_zero_committed_minutes
    """
    crew = create_crew(home_zone_code="Z2")
    route = create_route(crew["id"], zone_code="Z2", service_date="2026-04-16")
    assert route["committed_minutes"] == 0
    resp = api.lock_route_plan(route["id"], DI)
    validate_error(resp, ApiErrorId.ERR_ROUTE_EMPTY.value)


# ===========================================================================
# Difficulty: resource_temporal_overlap
# ===========================================================================
def test_buffered_slot_collision_rejected():
    """PRD §3.7: "A practical consequence is that two slots which merely touch with
    zero gap do collide once the buffer is applied; adjacent slots therefore need a
    gap of at least fifteen minutes between them."
    PRD §3.7: "Any collision rejects the commit with ERR_SLOT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/overlap_buffer_extended_slot_collision_on_route
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo1, route = create_scheduled_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"], scheduled_start_minute=540,
        inspect_overrides={"before_photo_count": 1, "dust_severity": 3},
        service_date="2026-04-19")
    # wo1 occupies [540,575); buffered [525,590). wo2 at 585 collides.
    wo2 = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                  requested_start_minute=585,
                                  inspect_overrides={"before_photo_count": 1, "dust_severity": 3})
    route_now = get_success_data(api.get_route_plan(route["id"], DI))
    resp = api.commit_slot(route["id"],
                          {"work_order_id": wo2["id"], "scheduled_start_minute": 585,
                           "expected_route_plan_version": route_now["version"]}, DI)
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP.value)


def test_crew_double_booked_across_routes_same_date():
    """PRD §3.6: "the chosen crew member must not already own another route on the
    same service_date whose shift window overlaps the new one. This overlap test
    uses the whole closed shift window [shift_start_minute, shift_end_minute] with
    no buffer, so two routes that merely touch at a shared boundary minute do count
    as overlapping; a violation is rejected with ERR_CREW_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/overlap_crew_double_booked_across_routes_same_date
    """
    crew = create_crew(home_zone_code="Z1")
    create_route(crew["id"], zone_code="Z1", service_date="2026-05-05",
                 shift_start_minute=480, shift_end_minute=660)
    resp = api.create_route_plan(
        {"crew_member_id": crew["id"], "zone_code": "Z1", "service_date": "2026-05-05",
         "shift_start_minute": 600, "shift_end_minute": 720}, DI)
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)


# ===========================================================================
# Difficulty: compensating_invariant (committed_minutes)
# ===========================================================================
def test_committed_minutes_restored_after_cancel():
    """PRD §3.8: "If the work order had been committed to a route (its
    route_plan_id is set), cancellation reverses the ledger: the route's
    committed_minutes is decreased by the work order's duration_minutes, the
    route's version is incremented, and the work order's route_plan_id,
    crew_member_id, and scheduled_start_minute are all cleared to null."
    PRD §3.7: "a commit of some duration paired with its compensating cancel of the
    same duration leaves committed_minutes exactly where it began."

    Design: Difficulty/compensating_invariant/compensating_route_committed_minutes_restored_on_cancel
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_scheduled_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"], scheduled_start_minute=540,
        inspect_overrides={"before_photo_count": 1, "dust_severity": 3},
        service_date="2026-04-21")
    after_commit = get_success_data(api.get_route_plan(route["id"], DI))
    assert after_commit["committed_minutes"] == 55, \
        f"Expected committed_minutes 55 after commit, got {after_commit['committed_minutes']}"

    get_success_data(api.cancel_work_order(wo["id"], DI))
    after_cancel = get_success_data(api.get_route_plan(route["id"], DI))
    assert after_cancel["committed_minutes"] == 0, \
        f"Expected committed_minutes 0 after cancel, got {after_cancel['committed_minutes']}"


# ===========================================================================
# Corner: validations (zone, shift window)
# ===========================================================================
def test_zone_mismatch_on_commit_rejected():
    """PRD §3.6: "The route's zone_code must equal the work order's home zone_code,
    else ERR_ZONE_MISMATCH."

    Design: Corner/validations/val_zone_mismatch_on_commit
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z2")
    crew = create_crew(home_zone_code="Z1")
    wo = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                 inspect_overrides={"before_photo_count": 1, "dust_severity": 2})
    route = create_route(crew["id"], zone_code="Z1", service_date="2026-04-27")
    resp = api.commit_slot(route["id"],
                          {"work_order_id": wo["id"], "scheduled_start_minute": 540,
                           "expected_route_plan_version": route["version"]}, DI)
    validate_error(resp, ApiErrorId.ERR_ZONE_MISMATCH.value)


def test_commit_outside_shift_window_rejected():
    """PRD §3.6: "The committed window must fit inside the shift:
    scheduled_start_minute must be at least shift_start_minute, and
    scheduled_start_minute plus the work order's duration_minutes must be no
    greater than shift_end_minute, else ERR_OUTSIDE_SHIFT."

    Design: Corner/validations/val_commit_outside_shift_window_rejected
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    # duration 35; start 1000 -> ends 1035 > shift_end 1020.
    wo = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                 requested_start_minute=1000,
                                 inspect_overrides={"before_photo_count": 1, "dust_severity": 3})
    route = create_route(crew["id"], zone_code="Z1", service_date="2026-05-03",
                        shift_start_minute=480, shift_end_minute=1020)
    resp = api.commit_slot(route["id"],
                          {"work_order_id": wo["id"], "scheduled_start_minute": 1000,
                           "expected_route_plan_version": route["version"]}, DI)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_SHIFT.value)


# ===========================================================================
# Corner: cross_cutting_complexity_layers (OCC + ledger reconcile)
# ===========================================================================
def test_stale_route_version_on_second_commit_rejected():
    """PRD §2.8: "If that value does not equal the route's current version — for
    example, because another writer has already committed a slot and thereby
    advanced the route's committed_minutes and version since the dispatcher read it
    — the commit is rejected with ERR_STALE_ROUTE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_route_version_rejected
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo1 = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                  requested_start_minute=540,
                                  inspect_overrides={"before_photo_count": 1, "dust_severity": 2})
    wo2 = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                  requested_start_minute=700,
                                  inspect_overrides={"before_photo_count": 1, "dust_severity": 2})
    route = create_route(crew["id"], zone_code="Z1", service_date="2026-04-30")
    stale_version = route["version"]
    commit(route["id"], wo1["id"], 540, stale_version)  # advances route.version
    resp = api.commit_slot(route["id"],
                          {"work_order_id": wo2["id"], "scheduled_start_minute": 700,
                           "expected_route_plan_version": stale_version}, DI)
    validate_error(resp, ApiErrorId.ERR_STALE_ROUTE_VERSION.value)


def test_stale_home_version_on_plan_create_rejected():
    """PRD §2.8: "If that value does not equal the home's current version — for
    example, because another writer has already enrolled the home in a plan,
    flipping has_active_plan and re-versioning the home — the create is rejected
    with ERR_STALE_HOME_VERSION (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_home_version_rejected_on_plan_create
    """
    home = get_success_data(api.create_home(
        {"homeowner_id": get_success_data(api.create_homeowner(
            {"full_name": "Xan C", "email": "xanc655@x.com", "phone": "555-0223"}, PA))["id"],
         "address_line": "43 Vent Rd", "zone_code": "Z1", "square_footage": 1500}, PA))
    stale_version = home["version"]
    # Adding a system bumps Home.version.
    get_success_data(api.add_system(home["id"], {"label": "Sys A", "register_count": 5}, PA))
    resp = api.create_recurring_plan(
        home["id"], {"cadence_months": 12, "expected_home_version": stale_version}, PA)
    validate_error(resp, ApiErrorId.ERR_STALE_HOME_VERSION.value)


def test_committed_minutes_reconciles_after_two_commits():
    """PRD §3.7: "A route's committed_minutes is a derived ledger equal to the sum
    of duration_minutes over the work orders whose route_plan_id points at that
    route and whose status is one of SCHEDULED, IN_PROGRESS, or COMPLETED."
    PRD §3.7: "It is maintained incrementally — a commit adds the work order's
    duration, a cancel subtracts it — and the incremental running total must always
    equal a full recomputation over that filtered set."

    Design: Corner/cross_cutting_complexity_layers/derived_committed_minutes_reconciles_after_two_commits
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo1 = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                  requested_start_minute=540,
                                  inspect_overrides={"before_photo_count": 1, "dust_severity": 2})
    wo2 = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                  requested_start_minute=700,
                                  inspect_overrides={"before_photo_count": 1, "dust_severity": 2})
    route = create_route(crew["id"], zone_code="Z1", service_date="2026-05-02")
    commit(route["id"], wo1["id"], 540, route["version"])
    route_after1 = get_success_data(api.get_route_plan(route["id"], DI))
    commit(route["id"], wo2["id"], 700, route_after1["version"])
    route_now = get_success_data(api.get_route_plan(route["id"], DI))
    assert route_now["committed_minutes"] == 110, \
        f"Expected committed_minutes 110 (55+55), got {route_now['committed_minutes']}"
