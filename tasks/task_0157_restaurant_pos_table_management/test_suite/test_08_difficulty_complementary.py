"""Second, complementary assertions for each difficulty-design instance.

Every difficulty instance is exercised by two tests: the primary translation
lives in test_01..test_03; this file adds a second test asserting a distinct,
PRD-uniquely-derivable facet (the opposite boundary side, the negative/positive
branch, a different conserved-quantity path, or a divergent side-effect set).
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_server_headers,
    create_restaurant_payload, set_clock_payload, create_menu_item_payload,
    create_table_payload, create_staff_member_payload, create_seating_payload,
    create_check_payload, create_course_payload, create_order_item_payload,
    create_waitlist_payload, create_staff_shift_payload, create_payment_payload,
    buss_table_payload,
    setup_fired_single_item, setup_dirty_table, setup_closed_check_with_tip,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]
KITCHEN = TEST_USERS["kitchen_headers"]


# ===========================================================================
# Rule 1: dual_variant_calc
# ===========================================================================
def test_tip_pool_even_by_hours_split_uses_hours_only(api):
    """PRD §3.8: "under EVEN_BY_HOURS the weight is the shift's hours_worked_x100
    alone, while under WEIGHTED_BY_ROLE the weight is the shift's hours_worked_x100
    multiplied by the staff member's tip_weight_bps".

    Design: Difficulty/dual_variant_calc/tip_pool_even_vs_weighted_diverge_on_same_shifts
    """
    # Same shifts (hours 800 and 500); EVEN_BY_HOURS → [6154, 3846], distinct from
    # the WEIGHTED_BY_ROLE split [7619, 2381] asserted in test_01.
    ctx = setup_closed_check_with_tip(
        tip_cents=10000, business_date="2026-06-01",
        clock_iso="2026-06-01T20:00:00Z", distribution_mode="EVEN_BY_HOURS",
        name="R2b",
        shifts=[
            {"role": "SERVER", "tip_weight_bps": 10000,
             "clock_in_minute": 600, "clock_out_minute": 1080},
            {"role": "BUSSER", "tip_weight_bps": 5000,
             "clock_in_minute": 1020, "clock_out_minute": 1320},
        ])
    distributed = validate_success(api.distribute_tip_pool(ctx["pool"]["id"], MANAGER))
    assert distributed["distributed_cents"] == 10000
    allocs, _ = validate_paginated(
        api.list_tip_allocations(MANAGER, params={"tip_pool_id": ctx["pool"]["id"]}))
    by_shift = {a["staff_shift_id"]: a["amount_cents"] for a in allocs}
    assert by_shift[ctx["shifts"][0]["id"]] == 6154
    assert by_shift[ctx["shifts"][1]["id"]] == 3846


# ===========================================================================
# Rule 2: combinatorial_formula
# ===========================================================================
def test_each_fired_line_subtotal_computed_per_line(api):
    """PRD §3.4: "its line_subtotal_cents is computed as quantity times that
    snapshotted unit price plus quantity times the sum of its modifiers'
    surcharge_cents".

    Design: Difficulty/combinatorial_formula/final_subtotal_rounds_per_line_then_sums_mode_b
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R3b", tax_rate_bps=0), MANAGER))
    api.set_clock(set_clock_payload(r["id"], "2026-06-02T10:00:00Z"), MANAGER)
    mia = get_success_data(api.create_menu_item(create_menu_item_payload(
        r["id"], name="A", station="SAUTE", base_price_cents=950,
        happy_hour_price_cents=950, initial_available_count=50), MANAGER))
    mib = get_success_data(api.create_menu_item(create_menu_item_payload(
        r["id"], name="B", station="FRY", base_price_cents=535,
        happy_hour_price_cents=535, initial_available_count=50), MANAGER))
    tbl = get_success_data(api.create_table(create_table_payload(
        r["id"], table_number="T1", capacity=4), MANAGER))
    sm = get_success_data(api.create_staff_member(create_staff_member_payload(
        r["id"], name="Sam", role="SERVER", tip_weight_bps=10000), MANAGER))
    sh = make_server_headers(sm["id"])
    seat = get_success_data(api.create_seating(create_seating_payload(
        r["id"], tbl["id"], party_size=2), HOST))
    chk = get_success_data(api.create_check(create_check_payload(
        r["id"], seat["id"], sm["id"], party_size=2), sh))
    crs = get_success_data(api.create_course(create_course_payload(
        r["id"], chk["id"], course_number=1), sh))
    oia = get_success_data(api.create_order_item(create_order_item_payload(
        r["id"], crs["id"], mia["id"], quantity=2), sh))
    oib = get_success_data(api.create_order_item(create_order_item_payload(
        r["id"], crs["id"], mib["id"], quantity=3), sh))
    api.fire_course(crs["id"], sh)
    a = get_success_data(api.get_order_item(oia["id"], sh))
    b = get_success_data(api.get_order_item(oib["id"], sh))
    assert a["line_subtotal_cents"] == 1900, f"line A 2*950=1900, got {a['line_subtotal_cents']}"
    assert b["line_subtotal_cents"] == 1605, f"line B 3*535=1605, got {b['line_subtotal_cents']}"


def test_auto_gratuity_keys_off_full_base_when_no_comp(api):
    """PRD §3.6: "Then the comped subtotal is the base subtotal minus
    comp_total_cents — this is the figure both gratuity and tax key off. Then
    auto_gratuity_cents is set: when the check's party_size is greater than or
    equal to the restaurant's large_party_threshold, it is the comped subtotal
    times auto_gratuity_bps divided by 10000, rounded half-up".

    Design: Difficulty/combinatorial_formula/auto_gratuity_keys_off_comped_subtotal_pinned_eval_order_mode_c
    """
    # No comp → comped_subtotal == base 2700; gratuity = round(2700*0.20)=540.
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R4b", tax_rate_bps=0, auto_gratuity_bps=2000,
        large_party_threshold=8, comp_cap_bps=10000), MANAGER))
    api.set_clock(set_clock_payload(r["id"], "2026-06-02T10:00:00Z"), MANAGER)
    mix = get_success_data(api.create_menu_item(create_menu_item_payload(
        r["id"], name="X", station="GRILL", base_price_cents=1200,
        happy_hour_price_cents=1200, initial_available_count=50), MANAGER))
    miy = get_success_data(api.create_menu_item(create_menu_item_payload(
        r["id"], name="Y", station="COLD", base_price_cents=800,
        happy_hour_price_cents=800, initial_available_count=50), MANAGER))
    tbl = get_success_data(api.create_table(create_table_payload(
        r["id"], table_number="T1", capacity=10), MANAGER))
    sm = get_success_data(api.create_staff_member(create_staff_member_payload(
        r["id"], name="Sam", role="SERVER", tip_weight_bps=10000), MANAGER))
    sh = make_server_headers(sm["id"])
    seat = get_success_data(api.create_seating(create_seating_payload(
        r["id"], tbl["id"], party_size=8), HOST))
    chk = get_success_data(api.create_check(create_check_payload(
        r["id"], seat["id"], sm["id"], party_size=8), sh))
    crs = get_success_data(api.create_course(create_course_payload(
        r["id"], chk["id"], course_number=1), sh))
    oix = get_success_data(api.create_order_item(create_order_item_payload(
        r["id"], crs["id"], mix["id"], quantity=1), sh))
    api.create_item_modifier({"restaurant_id": r["id"], "order_item_id": oix["id"],
                              "name": "truffle", "surcharge_cents": 700}, sh)
    api.create_order_item(create_order_item_payload(
        r["id"], crs["id"], miy["id"], quantity=1), sh)
    api.fire_course(crs["id"], sh)
    presented = validate_success(api.present_check(chk["id"], sh))
    assert presented["comp_total_cents"] == 0
    assert presented["final_subtotal_cents"] == 2700
    assert presented["auto_gratuity_cents"] == 540, \
        f"gratuity on full base 2700 → 540, got {presented['auto_gratuity_cents']}"
    assert presented["total_due_cents"] == 3240


# ===========================================================================
# Rule 3: non_linear_state_machine
# ===========================================================================
def test_present_locks_final_subtotal_and_moves_to_presented(api):
    """PRD §3.7: "Presenting computes and locks final_subtotal_cents and recomputes
    comp_total_cents, auto_gratuity_cents, tax_cents, and total_due_cents on that
    locked subtotal, moving the check from OPEN to PRESENTED."

    Design: Difficulty/non_linear_state_machine/check_cyclic_open_present_reopen_open
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        clock_iso="2026-06-02T10:00:00Z", party_size=2, name="R5b", tax_rate_bps=0)
    presented = validate_success(api.present_check(ctx["check"]["id"], ctx["server_headers"]))
    assert presented["status"] == "PRESENTED", \
        f"present must move OPEN→PRESENTED, got {presented['status']}"
    assert presented["final_subtotal_cents"] == 1000, \
        f"present must lock final_subtotal 1000, got {presented['final_subtotal_cents']}"


def test_serve_branch_changes_only_status_no_count_restore(api):
    """PRD §3.5: "KitchenStaff mark a fired item done, moving it from FIRED to
    SERVED. This is purely a status change — no pricing recomputation, no portion
    restoration — legal only when the item's status is FIRED."

    Design: Difficulty/non_linear_state_machine/order_item_branching_fired_to_comped_vs_served_divergent_effects
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        initial_available_count=5, clock_iso="2026-06-02T10:00:00Z",
        party_size=2, name="R6b", tax_rate_bps=0)
    served = validate_success(api.serve_order_item(ctx["order_item"]["id"], KITCHEN))
    assert served["status"] == "SERVED"
    mi = get_success_data(api.get_menu_item(ctx["menu_item"]["id"], MANAGER))
    # SERVE restores nothing: count stays at 4 (5→4 on fire), unlike VOID (→5).
    assert mi["available_count"] == 4, \
        f"SERVE must not restore the count (stays 4), got {mi['available_count']}"
    chk = get_success_data(api.get_check(ctx["check"]["id"], ctx["server_headers"]))
    assert chk["provisional_subtotal_cents"] == 1000, "SERVE must not change the subtotal"


# ===========================================================================
# Rule 4: transitive_cascade
# ===========================================================================
def test_buss_promotion_creates_open_seating_on_table(api):
    """PRD §3.3: "the promotion creates a new seating with status OPEN on this
    table, sets the table's occupancy_status back to SEATED, records the new
    seating's id on the entry's seating_id".

    Design: Difficulty/transitive_cascade/buss_depth3_free_table_promotes_waitlist_creates_seating
    """
    dt = setup_dirty_table(clock_iso="2026-06-03T12:00:00Z", table_capacity=4,
                           seating_party_size=3, name="R7b", tax_rate_bps=0)
    r, tbl, tv = dt["restaurant"], dt["table"], dt["table_version"]
    wl = get_success_data(api.create_waitlist_entry(create_waitlist_payload(
        r["id"], party_name="Lee", party_size=2), HOST))
    api.buss_table(tbl["id"], buss_table_payload(tv), HOST)
    wl_after = get_success_data(api.get_waitlist_entry(wl["id"], HOST))
    seatings, _ = validate_paginated(api.list_seatings(
        HOST, params={"table_id": tbl["id"], "waitlist_entry_id": wl["id"]}))
    assert len(seatings) == 1, f"promotion must create one seating for the entry, got {len(seatings)}"
    new_seating = seatings[0]
    assert new_seating["status"] == "OPEN", "the promotion seating must be OPEN"
    assert wl_after["seating_id"] == new_seating["id"], \
        "entry.seating_id must reference the created promotion seating"


def test_void_from_served_also_restores_count(api):
    """PRD §3.5: "An item may be voided either from FIRED or from SERVED, and in
    both cases the precondition is identical ... it restores the menu item's
    available_count by the item's quantity ... The void from FIRED and the void
    from SERVED are specified identically here precisely because they behave
    identically."

    Design: Difficulty/transitive_cascade/void_item_depth2_restores_86_count_and_subtotal
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=2,
        initial_available_count=5, clock_iso="2026-06-02T10:00:00Z",
        party_size=2, name="R8b", tax_rate_bps=0)
    # Move to SERVED first, then void from SERVED — count must still restore 3→5.
    api.serve_order_item(ctx["order_item"]["id"], KITCHEN)
    voided = validate_success(api.void_order_item(ctx["order_item"]["id"], MANAGER))
    assert voided["status"] == "VOIDED"
    mi = get_success_data(api.get_menu_item(ctx["menu_item"]["id"], MANAGER))
    assert mi["available_count"] == 5, \
        f"void-from-SERVED must restore count to 5, got {mi['available_count']}"


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
def test_item_86_fires_when_check_open_lower_priority_reachable(api):
    """PRD §3.4: "the corresponding menu item's available_count must be at least
    that item's quantity; if any item would drive a count below zero, the entire
    fire is rejected with ERR_ITEM_86 (HTTP 409) and nothing changes."

    Design: Difficulty/priority_pair_validation_conflict/fire_closed_check_state_beats_item_86_safety
    """
    # Same setup as the precedence test, but check 2 stays OPEN → the lower-priority
    # 86 rule is now the one that fires (it was only pre-empted by state before).
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R9b", tax_rate_bps=0), MANAGER))
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
    api.fire_course(crs1["id"], sh)  # 86 the item
    seat2 = get_success_data(api.create_seating(create_seating_payload(
        r["id"], tbl2["id"], party_size=2), HOST))
    chk2 = get_success_data(api.create_check(create_check_payload(
        r["id"], seat2["id"], sm["id"], party_size=2), sh))
    crs2 = get_success_data(api.create_course(create_course_payload(
        r["id"], chk2["id"], course_number=1), sh))
    api.create_order_item(create_order_item_payload(
        r["id"], crs2["id"], mi["id"], quantity=1), sh)
    # chk2 stays OPEN → only the 86 rule fails.
    validate_error(api.fire_course(crs2["id"], sh), ApiErrorId.ERR_ITEM_86.value)


def test_comp_cap_fires_when_check_open_lower_priority_reachable(api):
    """PRD §3.5: "A comp whose addition would push comp_total_cents above that cap
    is rejected with ERR_COMP_CAP_EXCEEDED (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/comp_on_closed_check_state_beats_comp_cap_fiscal
    """
    # comp_cap_bps=0 and check left OPEN → the fiscal cap rule is the one that
    # fires (it was only pre-empted by state in the precedence test).
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        initial_available_count=5, clock_iso="2026-06-02T10:00:00Z",
        party_size=2, name="R10b", tax_rate_bps=0, comp_cap_bps=0)
    validate_error(api.comp_order_item(ctx["order_item"]["id"], MANAGER),
                   ApiErrorId.ERR_COMP_CAP_EXCEEDED.value)


# ===========================================================================
# Rule 6: boundary_precision_check
# ===========================================================================
def test_auto_gratuity_zero_below_threshold(api):
    """PRD §3.6: "when the check's party_size is greater than or equal to the
    restaurant's large_party_threshold, it is the comped subtotal times
    auto_gratuity_bps divided by 10000, rounded half-up; otherwise it is exactly
    zero."

    Design: Difficulty/boundary_precision_check/auto_gratuity_threshold_inclusive_at_party_size_8
    """
    # party_size 7 == threshold-1 → gratuity exactly 0.
    ctx = setup_fired_single_item(
        base_price_cents=1900, happy_hour_price_cents=1900, quantity=1,
        initial_available_count=50, clock_iso="2026-06-02T10:00:00Z",
        party_size=7, table_capacity=10, name="R11b", tax_rate_bps=0,
        auto_gratuity_bps=2000, large_party_threshold=8)
    presented = validate_success(api.present_check(ctx["check"]["id"], ctx["server_headers"]))
    assert presented["auto_gratuity_cents"] == 0, \
        f"party_size 7 < threshold 8 → gratuity 0, got {presented['auto_gratuity_cents']}"
    assert presented["total_due_cents"] == 1900


def test_fire_at_exactly_available_count_succeeds(api):
    """PRD §3.4: "the corresponding menu item's available_count must be at least
    that item's quantity; if any item would drive a count below zero, the entire
    fire is rejected with ERR_ITEM_86 (HTTP 409) and nothing changes."

    Design: Difficulty/boundary_precision_check/fire_at_exactly_zero_available_count_returns_item_86
    """
    # available_count == quantity (1 == 1): the fire succeeds and drives count to 0.
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        initial_available_count=1, clock_iso="2026-06-02T10:00:00Z",
        party_size=2, name="R12b", tax_rate_bps=0)
    mi = get_success_data(api.get_menu_item(ctx["menu_item"]["id"], MANAGER))
    assert mi["available_count"] == 0, "fire at count==quantity succeeds, count → 0"
    assert mi["is_86"] is True, "is_86 must become true at available_count 0"


# ===========================================================================
# Rule 7: cross_entity_state_dependency
# ===========================================================================
def test_fire_second_course_while_check_open_succeeds(api):
    """PRD §3.4: "Firing a course sends it to the kitchen and is legal only when
    the course's status is BUILDING, its owning check's status is OPEN".

    Design: Difficulty/cross_entity_state_dependency/course_fire_requires_check_open_orderitem_to_check
    """
    # Complement: the same second course fires fine while the check is still OPEN.
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        initial_available_count=50, clock_iso="2026-06-02T10:00:00Z",
        party_size=2, name="R13b", tax_rate_bps=0)
    sh, r = ctx["server_headers"], ctx["restaurant"]
    crs2 = get_success_data(api.create_course(create_course_payload(
        r["id"], ctx["check"]["id"], course_number=2), sh))
    api.create_order_item(create_order_item_payload(
        r["id"], crs2["id"], ctx["menu_item"]["id"], quantity=1), sh)
    fired = validate_success(api.fire_course(crs2["id"], sh))
    assert fired["status"] == "FIRED", "second course fires while check is OPEN"


def test_seating_create_on_dirty_table_rejected(api):
    """PRD §3.3: "Seating is permitted only when the table's occupancy_status is
    AVAILABLE and no open seating already references that table; otherwise the
    create is rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/seating_create_requires_table_available_seating_to_table
    """
    # DIRTY (not just SEATED) also blocks a new seating — table not AVAILABLE.
    dt = setup_dirty_table(clock_iso="2026-06-03T12:00:00Z", table_capacity=4,
                           name="R14b", tax_rate_bps=0)
    validate_error(
        api.create_seating(create_seating_payload(
            dt["restaurant"]["id"], dt["table"]["id"], party_size=2), HOST),
        ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
def test_seating_adjacent_at_cleared_at_boundary_allowed(api):
    """PRD §3.3: "its occupation interval, the half-open span from seated_at up to
    but not including cleared_at, must not overlap any other seating interval on
    the same table, with no buffer between them".

    Design: Difficulty/resource_temporal_overlap/seating_half_open_overlap_on_table_rejects_interior_start
    """
    # Prior interval [600,660); a new seating whose seated_at is exactly 660 is
    # adjacent (half-open) and must be ALLOWED.
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R15b", tax_rate_bps=0), MANAGER))
    tbl = get_success_data(api.create_table(create_table_payload(
        r["id"], table_number="T1", capacity=4), MANAGER))
    api.set_clock(set_clock_payload(r["id"], "2026-06-05T10:00:00Z"), MANAGER)  # 600
    seat1 = get_success_data(api.create_seating(create_seating_payload(
        r["id"], tbl["id"], party_size=2), HOST))
    api.set_clock(set_clock_payload(r["id"], "2026-06-05T11:00:00Z"), MANAGER)  # 660
    api.clear_seating(seat1["id"], HOST)  # interval [600,660)
    tv = get_success_data(api.get_table(tbl["id"], HOST))["version"]
    api.buss_table(tbl["id"], buss_table_payload(tv), HOST)  # AVAILABLE again
    # Clock still at minute 660 → new seated_at == 660 == prior cleared_at: allowed.
    seat2 = validate_success(api.create_seating(create_seating_payload(
        r["id"], tbl["id"], party_size=2), HOST), expected_status=201)
    assert seat2["status"] == "OPEN", "adjacency at the exclusive boundary is allowed"


def test_staff_shift_clear_of_buffer_allowed(api):
    """PRD §3.8: "each shift's closed interval is expanded by min_rest_minutes on
    each side, and if that expanded interval touches or overlaps another shift of
    the same member that day, the new shift is rejected with ERR_SHIFT_OVERLAP
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/staff_shift_closed_buffered_overlap_rejects_adjacency_within_rest
    """
    # shift1 [600,1080] + 30 rest → reaches 1110; a new shift starting at 1200 is
    # well clear of the buffer and must be ALLOWED.
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R16b", tax_rate_bps=0, min_rest_minutes=30), MANAGER))
    sm = get_success_data(api.create_staff_member(create_staff_member_payload(
        r["id"], name="Pat", role="SERVER", tip_weight_bps=10000), MANAGER))
    api.create_staff_shift(create_staff_shift_payload(
        r["id"], sm["id"], business_date="2026-06-05",
        clock_in_minute=600, clock_out_minute=1080), MANAGER)
    shift2 = validate_success(api.create_staff_shift(create_staff_shift_payload(
        r["id"], sm["id"], business_date="2026-06-05",
        clock_in_minute=1200, clock_out_minute=1320), MANAGER), expected_status=201)
    assert shift2["clock_in_minute"] == 1200, "a shift clear of the rest buffer is allowed"


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
def test_restored_count_is_usable_by_subsequent_fire(api):
    """PRD §3.1: "The conserved invariant for portions is that available_count plus
    the total quantity across all of this menu item's order items that are
    currently fired, served, or comped always equals initial_available_count."

    Design: Difficulty/compensating_invariant/void_item_conserves_menu_item_available_count
    """
    # Fire qty 10 (exhaust), void (restore to 10), then a fresh fire of qty 10
    # succeeds — the restored count is genuinely usable, proving no drift.
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=10,
        initial_available_count=10, clock_iso="2026-06-02T10:00:00Z",
        party_size=2, name="R17b", tax_rate_bps=0)
    sh, r = ctx["server_headers"], ctx["restaurant"]
    api.void_order_item(ctx["order_item"]["id"], MANAGER)
    mi = get_success_data(api.get_menu_item(ctx["menu_item"]["id"], MANAGER))
    assert mi["available_count"] == 10
    crs2 = get_success_data(api.create_course(create_course_payload(
        r["id"], ctx["check"]["id"], course_number=2), sh))
    api.create_order_item(create_order_item_payload(
        r["id"], crs2["id"], ctx["menu_item"]["id"], quantity=10), sh)
    fired = validate_success(api.fire_course(crs2["id"], sh))
    assert fired["status"] == "FIRED", "restored 86-count fully usable by a new fire"
    mi2 = get_success_data(api.get_menu_item(ctx["menu_item"]["id"], MANAGER))
    assert mi2["available_count"] == 0


def test_single_shift_receives_entire_pool(api):
    """PRD §3.8: "After distribution the pool's distributed_cents is set to the sum
    of all allocation amount_cents, which must equal pooled_cents exactly".

    Design: Difficulty/compensating_invariant/distribute_then_payout_conserves_tip_pool_cents
    """
    # Degenerate conservation: one shift → the lone allocation equals pooled_cents.
    ctx = setup_closed_check_with_tip(
        tip_cents=7777, business_date="2026-06-01",
        clock_iso="2026-06-01T20:00:00Z", distribution_mode="EVEN_BY_HOURS",
        name="R18b",
        shifts=[{"role": "SERVER", "tip_weight_bps": 10000,
                 "clock_in_minute": 600, "clock_out_minute": 1080}])
    distributed = validate_success(api.distribute_tip_pool(ctx["pool"]["id"], MANAGER))
    assert distributed["pooled_cents"] == 7777
    assert distributed["distributed_cents"] == 7777
    allocs, _ = validate_paginated(
        api.list_tip_allocations(MANAGER, params={"tip_pool_id": ctx["pool"]["id"]}))
    assert len(allocs) == 1
    assert allocs[0]["amount_cents"] == 7777, \
        f"single shift gets the whole pool, got {allocs[0]['amount_cents']}"
