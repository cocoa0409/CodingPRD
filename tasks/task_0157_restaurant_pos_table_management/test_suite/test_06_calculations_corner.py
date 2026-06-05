"""Happy-hour price snapshot at fire (in-window and at the exclusive end-minute
edge), tax on the comped subtotal, and even check-split allocation.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_server_headers,
    create_restaurant_payload, set_clock_payload, create_menu_item_payload,
    create_table_payload, create_staff_member_payload, create_seating_payload,
    create_check_payload, create_course_payload, create_order_item_payload,
    create_happy_hour_window_payload, split_check_payload,
    setup_fired_single_item,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]


def _fire_one_item_with_window(api, *, clock_iso, base, happy, window_kwargs):
    """Helper: restaurant + pre-existing window + clock + one fired item; returns
    (order_item, check, server_headers)."""
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R", tax_rate_bps=0), MANAGER))
    api.create_happy_hour_window(create_happy_hour_window_payload(
        r["id"], **window_kwargs), MANAGER)
    api.set_clock(set_clock_payload(r["id"], clock_iso), MANAGER)
    mi = get_success_data(api.create_menu_item(create_menu_item_payload(
        r["id"], name="Burger", station="GRILL", base_price_cents=base,
        happy_hour_price_cents=happy, initial_available_count=50), MANAGER))
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
    oi = get_success_data(api.create_order_item(create_order_item_payload(
        r["id"], crs["id"], mi["id"], quantity=1), sh))
    api.fire_course(crs["id"], sh)
    return oi, chk, sh


def test_happy_hour_price_snapshotted_when_in_window(api):
    """PRD §3.4: "its per-portion price unit_price_cents is snapshotted at this
    instant as happy_hour_price_cents if fired_at falls inside an active
    happy-hour window for the restaurant (per §3.1) and base_price_cents
    otherwise".

    Design: Corner/calculations/happy_hour_price_applied_when_course_fires_in_window
    """
    oi, chk, sh = _fire_one_item_with_window(
        api, clock_iso="2026-06-01T17:30:00Z", base=1200, happy=800,
        window_kwargs={"day_of_week": 1, "start_minute": 1020, "end_minute": 1080})
    oi_after = get_success_data(api.get_order_item(oi["id"], sh))
    assert oi_after["unit_price_cents"] == 800, \
        f"minute 1050 in-window → happy 800, got {oi_after['unit_price_cents']}"
    chk_after = get_success_data(api.get_check(chk["id"], sh))
    assert chk_after["provisional_subtotal_cents"] == 800


def test_happy_hour_end_minute_exclusive_uses_base_price(api):
    """PRD §3.1: "A course that fires at exactly end_minute falls outside the
    window."

    Design: Corner/calculations/happy_hour_end_minute_exclusive_uses_base_price
    """
    oi, chk, sh = _fire_one_item_with_window(
        api, clock_iso="2026-06-01T18:00:00Z", base=1200, happy=800,
        window_kwargs={"day_of_week": 1, "start_minute": 1020, "end_minute": 1080})
    oi_after = get_success_data(api.get_order_item(oi["id"], sh))
    # minute 1080 == end_minute → outside window → base price.
    assert oi_after["unit_price_cents"] == 1200, \
        f"minute 1080 at exclusive end → base 1200, got {oi_after['unit_price_cents']}"


def test_tax_computed_on_comped_subtotal_at_present(api):
    """PRD §3.6: "Then tax_cents is the comped subtotal times tax_rate_bps divided
    by 10000, rounded half-up, computed independently of gratuity."

    Design: Corner/calculations/tax_applied_on_comped_subtotal_at_present
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R", tax_rate_bps=875, auto_gratuity_bps=2000,
        large_party_threshold=8, comp_cap_bps=10000), MANAGER))
    api.set_clock(set_clock_payload(r["id"], "2026-06-02T10:00:00Z"), MANAGER)
    mix = get_success_data(api.create_menu_item(create_menu_item_payload(
        r["id"], name="X", station="GRILL", base_price_cents=1100,
        happy_hour_price_cents=1100, initial_available_count=50), MANAGER))
    miy = get_success_data(api.create_menu_item(create_menu_item_payload(
        r["id"], name="Y", station="COLD", base_price_cents=800,
        happy_hour_price_cents=800, initial_available_count=50), MANAGER))
    tbl = get_success_data(api.create_table(create_table_payload(
        r["id"], table_number="T1", capacity=6), MANAGER))
    sm = get_success_data(api.create_staff_member(create_staff_member_payload(
        r["id"], name="Sam", role="SERVER", tip_weight_bps=10000), MANAGER))
    sh = make_server_headers(sm["id"])
    seat = get_success_data(api.create_seating(create_seating_payload(
        r["id"], tbl["id"], party_size=4), HOST))
    chk = get_success_data(api.create_check(create_check_payload(
        r["id"], seat["id"], sm["id"], party_size=4), sh))
    crs = get_success_data(api.create_course(create_course_payload(
        r["id"], chk["id"], course_number=1), sh))
    api.create_order_item(create_order_item_payload(
        r["id"], crs["id"], mix["id"], quantity=1), sh)
    oiy = get_success_data(api.create_order_item(create_order_item_payload(
        r["id"], crs["id"], miy["id"], quantity=1), sh))
    api.fire_course(crs["id"], sh)
    api.comp_order_item(oiy["id"], MANAGER)  # comp Y (800) → comped_subtotal 1100
    presented = validate_success(api.present_check(chk["id"], sh))
    assert presented["comp_total_cents"] == 800
    assert presented["final_subtotal_cents"] == 1900
    # tax = round_half_up(1100*875/10000) = round(96.25) = 96.
    assert presented["tax_cents"] == 96, \
        f"tax on comped_subtotal 1100 must be 96, got {presented['tax_cents']}"
    assert presented["auto_gratuity_cents"] == 0  # party 4 < threshold 8
    assert presented["total_due_cents"] == 1196


def test_even_split_distributes_remainder_to_first_children(api):
    """PRD §3.7: "An even split divides the parent's total_due_cents by n using
    integer division to get each child's base amount, computes the leftover
    remainder as total_due_cents minus that base times n, and assigns one extra
    cent to each of the first remainder children in creation order, so that the
    children's amounts sum exactly to the parent's total_due_cents with no drift."

    Design: Corner/calculations/even_split_distributes_remainder_to_first_children
    """
    ctx = setup_fired_single_item(
        base_price_cents=1900, happy_hour_price_cents=1900, quantity=1,
        initial_available_count=50, clock_iso="2026-06-02T10:00:00Z",
        party_size=4, table_capacity=6, name="R", tax_rate_bps=875,
        large_party_threshold=8)
    sh = ctx["server_headers"]
    presented = validate_success(api.present_check(ctx["check"]["id"], sh))
    # tax = round(1900*875/10000)=round(166.25)=166; no gratuity → total 2066.
    assert presented["total_due_cents"] == 2066
    # Split is a creation action: POST /checks/{id}/split returns 201 with a
    # Check[] array of the new child checks (PRD §3.7 "split a check evenly into
    # child checks"; not a paginated list query).
    data = validate_success(api.split_check(
        ctx["check"]["id"], split_check_payload(2), sh), expected_status=201)
    dues = sorted(c["total_due_cents"] for c in data)
    assert dues == [1033, 1033], f"2066 split 2 → [1033,1033], got {dues}"
    assert sum(dues) == 2066


def test_split_count_over_party_size_invalid(api):
    """PRD §3.7: "The split count n must satisfy two-or-more and at most the
    check's party_size; a count outside that range is rejected with
    ERR_INVALID_SPLIT (HTTP 422)."

    Design: Corner/calculations/split_count_out_of_range_invalid_split
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        clock_iso="2026-06-02T10:00:00Z", party_size=2, name="R", tax_rate_bps=0)
    sh = ctx["server_headers"]
    api.present_check(ctx["check"]["id"], sh)
    validate_error(api.split_check(ctx["check"]["id"], split_check_payload(5), sh),
                   ApiErrorId.ERR_INVALID_SPLIT.value)
