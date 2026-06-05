"""Validation-priority conflicts (state beats business rules), cross-entity state
dependencies, and temporal-overlap geometry (half-open seating intervals and
closed buffered staff-shift intervals).
"""
from test_helpers import (
    get_success_data, validate_error, ApiErrorId, TEST_USERS,
    make_server_headers, create_restaurant_payload, set_clock_payload,
    create_menu_item_payload, create_table_payload, create_staff_member_payload,
    create_seating_payload, create_check_payload, create_course_payload,
    create_order_item_payload, create_payment_payload, create_staff_shift_payload,
    setup_fired_single_item,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]


# ===========================================================================
# Queue A — Rule 5: priority_pair_validation_conflict
# ===========================================================================
def test_fire_on_void_check_state_beats_item_86(api):
    """PRD §2.7: "then whether the target resource is in a state from which the
    requested transition is legal (ERR_INVALID_STATE, HTTP 409) ... Business rules
    are evaluated only after all of the foregoing pass".
    PRD §3.4: "Firing a course sends it to the kitchen and is legal only when the
    course's status is BUILDING, its owning check's status is OPEN".

    Design: Difficulty/priority_pair_validation_conflict/fire_closed_check_state_beats_item_86_safety
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R9", tax_rate_bps=0), MANAGER))
    api.set_clock(set_clock_payload(r["id"], "2026-06-02T10:00:00Z"), MANAGER)
    mi = get_success_data(api.create_menu_item(create_menu_item_payload(
        r["id"], name="Special", station="GRILL", base_price_cents=1000,
        happy_hour_price_cents=1000, initial_available_count=1), MANAGER))
    tbl1 = get_success_data(api.create_table(create_table_payload(
        r["id"], table_number="T1", capacity=4), MANAGER))
    tbl2 = get_success_data(api.create_table(create_table_payload(
        r["id"], table_number="T2", capacity=4), MANAGER))
    sm = get_success_data(api.create_staff_member(create_staff_member_payload(
        r["id"], name="Sam", role="SERVER", tip_weight_bps=10000), MANAGER))
    sh = make_server_headers(sm["id"])
    seat1 = get_success_data(api.create_seating(create_seating_payload(
        r["id"], tbl1["id"], party_size=2), HOST))
    chk1 = get_success_data(api.create_check(create_check_payload(
        r["id"], seat1["id"], sm["id"], party_size=2), sh))
    crs1 = get_success_data(api.create_course(create_course_payload(
        r["id"], chk1["id"], course_number=1), sh))
    api.create_order_item(create_order_item_payload(
        r["id"], crs1["id"], mi["id"], quantity=1), sh)
    api.fire_course(crs1["id"], sh)  # consumes the 1 portion → item 86'd
    seat2 = get_success_data(api.create_seating(create_seating_payload(
        r["id"], tbl2["id"], party_size=2), HOST))
    chk2 = get_success_data(api.create_check(create_check_payload(
        r["id"], seat2["id"], sm["id"], party_size=2), sh))
    crs2 = get_success_data(api.create_course(create_course_payload(
        r["id"], chk2["id"], course_number=1), sh))
    api.create_order_item(create_order_item_payload(
        r["id"], crs2["id"], mi["id"], quantity=1), sh)
    api.void_check(chk2["id"], MANAGER)  # check 2 now VOID (not OPEN)
    # Firing crs2 would fail BOTH state (check VOID) and 86 (count 0) → state wins.
    validate_error(api.fire_course(crs2["id"], sh), ApiErrorId.ERR_INVALID_STATE.value)


def test_comp_on_closed_check_state_beats_comp_cap(api):
    """PRD §2.7: "then whether the target resource is in a state from which the
    requested transition is legal (ERR_INVALID_STATE, HTTP 409) ... Business rules
    are evaluated only after all of the foregoing pass".
    PRD §3.5: "An item may be comped from FIRED or from SERVED; the precondition in
    both cases is that the item is in the respective state, its owning check is
    OPEN or PRESENTED, and the resulting comp would not breach the comp cap."

    Design: Difficulty/priority_pair_validation_conflict/comp_on_closed_check_state_beats_comp_cap_fiscal
    """
    # comp_cap_bps=0 → any comp breaches the fiscal cap; but the check is CLOSED so
    # the state check (priority 5) pre-empts the fiscal check (priority 10).
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        initial_available_count=5, clock_iso="2026-06-02T10:00:00Z",
        party_size=2, name="R10", tax_rate_bps=0, comp_cap_bps=0)
    sh = ctx["server_headers"]
    api.present_check(ctx["check"]["id"], sh)
    api.create_payment(create_payment_payload(
        ctx["restaurant"]["id"], ctx["check"]["id"], amount_cents=1000,
        tip_cents=0, method="CASH"), sh)
    api.close_check(ctx["check"]["id"], sh)
    validate_error(api.comp_order_item(ctx["order_item"]["id"], MANAGER),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue A — Rule 7: cross_entity_state_dependency
# ===========================================================================
def test_fire_second_course_after_present_rejected_check_not_open(api):
    """PRD §3.4: "Firing a course sends it to the kitchen and is legal only when
    the course's status is BUILDING, its owning check's status is OPEN".
    PRD §3.7: "Presenting computes and locks final_subtotal_cents and recomputes
    comp_total_cents, auto_gratuity_cents, tax_cents, and total_due_cents on that
    locked subtotal, moving the check from OPEN to PRESENTED."

    Design: Difficulty/cross_entity_state_dependency/course_fire_requires_check_open_orderitem_to_check
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        initial_available_count=50, clock_iso="2026-06-02T10:00:00Z",
        party_size=2, name="R13", tax_rate_bps=0)
    sh = ctx["server_headers"]
    r = ctx["restaurant"]
    # Present first — legal because the only course (crs1) is already FIRED, so
    # no course is still BUILDING (PRD §3.7). The check moves OPEN -> PRESENTED.
    get_success_data(api.present_check(ctx["check"]["id"], sh))
    # Now build a second BUILDING course with a PENDING item on the PRESENTED
    # check, then attempt to fire it. Firing requires the owning check be OPEN
    # (PRD §3.4); the check is PRESENTED, so the fire is rejected.
    crs2 = get_success_data(api.create_course(create_course_payload(
        r["id"], ctx["check"]["id"], course_number=2), sh))
    api.create_order_item(create_order_item_payload(
        r["id"], crs2["id"], ctx["menu_item"]["id"], quantity=1), sh)
    validate_error(api.fire_course(crs2["id"], sh), ApiErrorId.ERR_INVALID_STATE.value)


def test_seating_create_on_seated_table_rejected(api):
    """PRD §3.3: "Seating is permitted only when the table's occupancy_status is
    AVAILABLE and no open seating already references that table; otherwise the
    create is rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/seating_create_requires_table_available_seating_to_table
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R14", tax_rate_bps=0), MANAGER))
    api.set_clock(set_clock_payload(r["id"], "2026-06-03T12:00:00Z"), MANAGER)
    tbl = get_success_data(api.create_table(create_table_payload(
        r["id"], table_number="T1", capacity=4), MANAGER))
    api.create_seating(create_seating_payload(r["id"], tbl["id"], party_size=2), HOST)
    # table now SEATED; a second seating on it must be rejected with INVALID_STATE.
    validate_error(
        api.create_seating(create_seating_payload(r["id"], tbl["id"], party_size=2), HOST),
        ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue A — Rule 8: resource_temporal_overlap
# ===========================================================================
def test_seating_half_open_interval_rejects_interior_start(api):
    """PRD §3.3: "A new seating must also not collide on the floor: its occupation
    interval, the half-open span from seated_at up to but not including cleared_at,
    must not overlap any other seating interval on the same table, with no buffer
    between them; an overlap is rejected with ERR_TABLE_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/seating_half_open_overlap_on_table_rejects_interior_start
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R15", tax_rate_bps=0), MANAGER))
    tbl = get_success_data(api.create_table(create_table_payload(
        r["id"], table_number="T1", capacity=4), MANAGER))
    api.set_clock(set_clock_payload(r["id"], "2026-06-05T10:00:00Z"), MANAGER)  # minute 600
    seat1 = get_success_data(api.create_seating(create_seating_payload(
        r["id"], tbl["id"], party_size=2), HOST))
    api.set_clock(set_clock_payload(r["id"], "2026-06-05T11:00:00Z"), MANAGER)  # minute 660
    api.clear_seating(seat1["id"], HOST)  # interval [600,660)
    tv = get_success_data(api.get_table(tbl["id"], HOST))["version"]
    from test_helpers import buss_table_payload
    api.buss_table(tbl["id"], buss_table_payload(tv), HOST)  # back to AVAILABLE
    api.set_clock(set_clock_payload(r["id"], "2026-06-05T10:30:00Z"), MANAGER)  # minute 630 interior
    validate_error(
        api.create_seating(create_seating_payload(r["id"], tbl["id"], party_size=2), HOST),
        ApiErrorId.ERR_TABLE_DOUBLE_BOOKED.value)


def test_staff_shift_buffered_interval_rejects_adjacency_within_rest(api):
    """PRD §3.8: "A new shift must not collide with another shift of the same staff
    member on the same business date: each shift's closed interval is expanded by
    min_rest_minutes on each side, and if that expanded interval touches or
    overlaps another shift of the same member that day, the new shift is rejected
    with ERR_SHIFT_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/staff_shift_closed_buffered_overlap_rejects_adjacency_within_rest
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R16", tax_rate_bps=0, min_rest_minutes=30), MANAGER))
    sm = get_success_data(api.create_staff_member(create_staff_member_payload(
        r["id"], name="Pat", role="SERVER", tip_weight_bps=10000), MANAGER))
    api.create_staff_shift(create_staff_shift_payload(
        r["id"], sm["id"], business_date="2026-06-05",
        clock_in_minute=600, clock_out_minute=1080), MANAGER)
    # shift1 end 1080 + 30 rest = 1110 > 1109 new start → buffered overlap.
    validate_error(
        api.create_staff_shift(create_staff_shift_payload(
            r["id"], sm["id"], business_date="2026-06-05",
            clock_in_minute=1109, clock_out_minute=1320), MANAGER),
        ApiErrorId.ERR_SHIFT_OVERLAP.value)
