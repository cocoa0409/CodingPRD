"""Provisional vs final subtotal, comped-subtotal pinned evaluation order, tax,
auto-gratuity threshold, and per-line rounding — the Restaurant POS money engine.

Each test drives the system to a fired/presented check and asserts the literal
cent figures the PRD's pinned calculation order uniquely determines.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, TEST_USERS,
    make_server_headers, create_restaurant_payload, set_clock_payload,
    create_menu_item_payload, create_table_payload, create_staff_member_payload,
    create_seating_payload, create_check_payload, create_course_payload,
    create_order_item_payload, create_item_modifier_payload,
    create_happy_hour_window_payload, create_staff_shift_payload,
    create_tip_pool_payload, create_payment_payload,
    setup_fired_single_item, setup_closed_check_with_tip,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]


# ===========================================================================
# Queue A — Rule 1: dual_variant_calc
# ===========================================================================
def test_provisional_subtotal_uses_fire_time_snapshot_not_late_window(api):
    """PRD §3.6: "The provisional pass trusts the unit_price_cents snapshot taken
    at fire time and does not re-consult the happy-hour schedule."
    PRD §3.4: "its per-portion price unit_price_cents is snapshotted at this
    instant as happy_hour_price_cents if fired_at falls inside an active
    happy-hour window for the restaurant (per §3.1) and base_price_cents
    otherwise; its line_subtotal_cents is computed as quantity times that
    snapshotted unit price plus quantity times the sum of its modifiers'
    surcharge_cents".

    Design: Difficulty/dual_variant_calc/provisional_vs_final_subtotal_diverge_on_late_happy_hour_window
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R1", tax_rate_bps=875, large_party_threshold=8,
        auto_gratuity_bps=2000, comp_cap_bps=10000), MANAGER))
    api.set_clock(set_clock_payload(r["id"], "2026-06-01T17:30:00Z"), MANAGER)
    mi = get_success_data(api.create_menu_item(create_menu_item_payload(
        r["id"], name="Burger", station="GRILL", base_price_cents=1200,
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
    oi = get_success_data(api.create_order_item(create_order_item_payload(
        r["id"], crs["id"], mi["id"], quantity=2), sh))
    api.create_item_modifier(create_item_modifier_payload(
        r["id"], oi["id"], name="extra cheese", surcharge_cents=150), sh)
    # Fire BEFORE any window exists → snapshot uses base price 1200.
    fired = get_success_data(api.fire_course(crs["id"], sh))
    # Now create a window that would have covered minute 1050.
    api.create_happy_hour_window(create_happy_hour_window_payload(
        r["id"], day_of_week=1, start_minute=1020, end_minute=1080), MANAGER)
    chk_now = get_success_data(api.get_check(chk["id"], sh))
    # line = 2*1200 + 2*150 = 2700, from the fire-time snapshot.
    assert chk_now["provisional_subtotal_cents"] == 2700, \
        f"provisional must use fire-time snapshot 2700, got {chk_now['provisional_subtotal_cents']}"


def test_final_subtotal_rederives_price_from_window_at_present(api):
    """PRD §3.6: "The final subtotal is computed and locked when the bill is
    presented and recomputed at close. It re-derives each line's price rather
    than trusting the snapshot."
    PRD §3.6: "for each such course the system re-evaluates whether its fired_at
    falls inside an active happy-hour window for the restaurant. For every order
    item in that course whose status is FIRED, SERVED, or COMPED, the per-line
    price is happy_hour_price_cents if the course is in-window and
    base_price_cents otherwise".

    Design: Difficulty/dual_variant_calc/provisional_vs_final_subtotal_diverge_on_late_happy_hour_window
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R1", tax_rate_bps=875, large_party_threshold=8,
        auto_gratuity_bps=2000, comp_cap_bps=10000), MANAGER))
    api.set_clock(set_clock_payload(r["id"], "2026-06-01T17:30:00Z"), MANAGER)
    mi = get_success_data(api.create_menu_item(create_menu_item_payload(
        r["id"], name="Burger", station="GRILL", base_price_cents=1200,
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
    oi = get_success_data(api.create_order_item(create_order_item_payload(
        r["id"], crs["id"], mi["id"], quantity=2), sh))
    api.create_item_modifier(create_item_modifier_payload(
        r["id"], oi["id"], name="extra cheese", surcharge_cents=150), sh)
    api.fire_course(crs["id"], sh)
    api.create_happy_hour_window(create_happy_hour_window_payload(
        r["id"], day_of_week=1, start_minute=1020, end_minute=1080), MANAGER)
    presented = validate_success(api.present_check(chk["id"], sh))
    # final re-derives: minute 1050 now in-window → happy 800: 2*800 + 2*150 = 1900.
    assert presented["final_subtotal_cents"] == 1900, \
        f"final must re-derive to 1900, got {presented['final_subtotal_cents']}"
    assert presented["provisional_subtotal_cents"] != presented["final_subtotal_cents"], \
        "provisional (2700) and final (1900) must diverge"


def test_tip_pool_weighted_by_role_split_differs_from_even(api):
    """PRD §3.8: "under EVEN_BY_HOURS the weight is the shift's hours_worked_x100
    alone, while under WEIGHTED_BY_ROLE the weight is the shift's hours_worked_x100
    multiplied by the staff member's tip_weight_bps — so two staff who worked
    identical hours can be paid differently."
    PRD §3.8: "Each shift's raw share is pooled_cents times its weight divided by
    the sum of all weights; each raw share is floored to a whole cent; the leftover
    remainder, pooled_cents minus the sum of the floors, is then handed out one cent
    at a time to shifts in descending order of the fractional part of their raw
    share, with created_at ascending as the tie-break (never the id)."

    Design: Difficulty/dual_variant_calc/tip_pool_even_vs_weighted_diverge_on_same_shifts
    """
    # SERVER weight 10000, hours_x100=800 (600..1080); BUSSER weight 5000,
    # hours_x100=500 (1020..1320). WEIGHTED_BY_ROLE weights: 800*10000=8e6,
    # 500*5000=2.5e6 → shares 10000*8/10.5=7619.05, 10000*2.5/10.5=2380.95 →
    # floors 7619, 2380, remainder 1 to the larger fractional part (BUSSER .95) → 2381.
    ctx = setup_closed_check_with_tip(
        tip_cents=10000, business_date="2026-06-01",
        clock_iso="2026-06-01T20:00:00Z", distribution_mode="WEIGHTED_BY_ROLE",
        name="R2",
        shifts=[
            {"role": "SERVER", "tip_weight_bps": 10000,
             "clock_in_minute": 600, "clock_out_minute": 1080},
            {"role": "BUSSER", "tip_weight_bps": 5000,
             "clock_in_minute": 1020, "clock_out_minute": 1320},
        ])
    pool = ctx["pool"]
    distributed = validate_success(api.distribute_tip_pool(pool["id"], MANAGER))
    assert distributed["pooled_cents"] == 10000
    assert distributed["distributed_cents"] == 10000
    allocs, _ = api_validate_allocations(api, pool["id"])
    by_shift = {a["staff_shift_id"]: a["amount_cents"] for a in allocs}
    server_shift = ctx["shifts"][0]["id"]
    busser_shift = ctx["shifts"][1]["id"]
    assert by_shift[server_shift] == 7619, \
        f"WEIGHTED_BY_ROLE SERVER cut must be 7619, got {by_shift[server_shift]}"
    assert by_shift[busser_shift] == 2381, \
        f"WEIGHTED_BY_ROLE BUSSER cut must be 2381, got {by_shift[busser_shift]}"
    # These differ from the EVEN_BY_HOURS split [6154, 3846].
    assert by_shift[server_shift] != 6154 and by_shift[busser_shift] != 3846


def api_validate_allocations(api, pool_id):
    from test_helpers import validate_paginated
    resp = api.list_tip_allocations(MANAGER, params={"tip_pool_id": pool_id})
    return validate_paginated(resp)


# ===========================================================================
# Queue A — Rule 2: combinatorial_formula
# ===========================================================================
def test_final_subtotal_rounds_per_line_then_sums(api):
    """PRD §3.6: "the line value is quantity times that price plus quantity times
    the sum of the item's modifiers' surcharge_cents; and these per-line values are
    summed, in the identical round-per-line-then-sum order as the provisional pass,
    into final_subtotal_cents."

    Design: Difficulty/combinatorial_formula/final_subtotal_rounds_per_line_then_sums_mode_b
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R3", tax_rate_bps=0), MANAGER))
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
    api.create_order_item(create_order_item_payload(
        r["id"], crs["id"], mia["id"], quantity=2), sh)
    api.create_order_item(create_order_item_payload(
        r["id"], crs["id"], mib["id"], quantity=3), sh)
    api.fire_course(crs["id"], sh)
    presented = validate_success(api.present_check(chk["id"], sh))
    # line A = 2*950 = 1900; line B = 3*535 = 1605; sum = 3505.
    assert presented["final_subtotal_cents"] == 3505, \
        f"final must be 1900+1605=3505, got {presented['final_subtotal_cents']}"


def test_auto_gratuity_keys_off_comped_subtotal_pinned_order(api):
    """PRD §3.6: "Then the comped subtotal is the base subtotal minus
    comp_total_cents — this is the figure both gratuity and tax key off. Then
    auto_gratuity_cents is set: when the check's party_size is greater than or
    equal to the restaurant's large_party_threshold, it is the comped subtotal
    times auto_gratuity_bps divided by 10000, rounded half-up; otherwise it is
    exactly zero."
    PRD §3.6: "Finally total_due_cents is the comped subtotal plus tax_cents plus
    auto_gratuity_cents — the amount the guest owes."

    Design: Difficulty/combinatorial_formula/auto_gratuity_keys_off_comped_subtotal_pinned_eval_order_mode_c
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R4", tax_rate_bps=0, auto_gratuity_bps=2000,
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
    api.create_item_modifier(create_item_modifier_payload(
        r["id"], oix["id"], name="truffle", surcharge_cents=700), sh)
    oiy = get_success_data(api.create_order_item(create_order_item_payload(
        r["id"], crs["id"], miy["id"], quantity=1), sh))
    api.fire_course(crs["id"], sh)
    # comp Y (line 800) → comp_total 800; base 2700 → comped_subtotal 1900.
    api.comp_order_item(oiy["id"], MANAGER)
    presented = validate_success(api.present_check(chk["id"], sh))
    assert presented["comp_total_cents"] == 800
    assert presented["final_subtotal_cents"] == 2700
    # gratuity = round_half_up(1900 * 0.20) = 380; tax 0; total = 1900+0+380 = 2280.
    assert presented["auto_gratuity_cents"] == 380, \
        f"gratuity must key off comped_subtotal 1900 → 380, got {presented['auto_gratuity_cents']}"
    assert presented["total_due_cents"] == 2280, \
        f"total_due must be 1900+0+380=2280, got {presented['total_due_cents']}"


# ===========================================================================
# Queue A — Rule 6: boundary_precision_check
# ===========================================================================
def test_auto_gratuity_applies_at_party_size_equal_threshold(api):
    """PRD §3.6: "when the check's party_size is greater than or equal to the
    restaurant's large_party_threshold, it is the comped subtotal times
    auto_gratuity_bps divided by 10000, rounded half-up; otherwise it is exactly
    zero."

    Design: Difficulty/boundary_precision_check/auto_gratuity_threshold_inclusive_at_party_size_8
    """
    ctx = setup_fired_single_item(
        base_price_cents=1900, happy_hour_price_cents=1900, quantity=1,
        initial_available_count=50, clock_iso="2026-06-02T10:00:00Z",
        party_size=8, table_capacity=10, station="GRILL",
        name="R11", tax_rate_bps=0, auto_gratuity_bps=2000,
        large_party_threshold=8)
    presented = validate_success(api.present_check(ctx["check"]["id"], ctx["server_headers"]))
    # party_size 8 == threshold 8 → gratuity = round(1900*0.20)=380; total=1900+0+380.
    assert presented["auto_gratuity_cents"] == 380, \
        f"party_size==threshold must apply gratuity 380, got {presented['auto_gratuity_cents']}"
    assert presented["total_due_cents"] == 2280


def test_fire_at_zero_available_count_rejected_item_86(api):
    """PRD §3.4: "The eighty-six guard is also evaluated at fire: for every PENDING
    item in the course, the corresponding menu item's available_count must be at
    least that item's quantity; if any item would drive a count below zero, the
    entire fire is rejected with ERR_ITEM_86 (HTTP 409) and nothing changes."

    Design: Difficulty/boundary_precision_check/fire_at_exactly_zero_available_count_returns_item_86
    """
    from test_helpers import validate_error, ApiErrorId
    # initial_available_count=1; check 1 consumes it (count → 0), then check 2's
    # fire of qty 1 against the same 86'd menu item is rejected.
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R12", tax_rate_bps=0), MANAGER))
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
    api.fire_course(crs1["id"], sh)  # count 1 → 0, item now 86
    seat2 = get_success_data(api.create_seating(create_seating_payload(
        r["id"], tbl2["id"], party_size=2), HOST))
    chk2 = get_success_data(api.create_check(create_check_payload(
        r["id"], seat2["id"], sm["id"], party_size=2), sh))
    crs2 = get_success_data(api.create_course(create_course_payload(
        r["id"], chk2["id"], course_number=1), sh))
    api.create_order_item(create_order_item_payload(
        r["id"], crs2["id"], mi["id"], quantity=1), sh)
    validate_error(api.fire_course(crs2["id"], sh), ApiErrorId.ERR_ITEM_86.value)
