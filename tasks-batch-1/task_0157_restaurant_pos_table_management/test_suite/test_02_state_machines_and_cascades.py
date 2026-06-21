"""Cyclic check lifecycle, FIRED-item branching, the clear-free-promote cascade,
the void-restores-86 cascade, and the two conservation invariants (86-count and
pooled tip cents).
"""
from test_helpers import (
    get_success_data, validate_success, validate_paginated, TEST_USERS,
    make_server_headers, create_restaurant_payload, set_clock_payload,
    create_menu_item_payload, create_table_payload, create_staff_member_payload,
    create_seating_payload, create_check_payload, create_course_payload,
    create_order_item_payload, create_waitlist_payload, buss_table_payload,
    create_payment_payload,
    setup_fired_single_item, setup_dirty_table, setup_closed_check_with_tip,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]


# ===========================================================================
# Queue A — Rule 3: non_linear_state_machine
# ===========================================================================
def test_check_cycles_open_present_reopen_to_open(api):
    """PRD §3.7: "Reopening moves the check from PRESENTED back to OPEN and clears
    final_subtotal_cents to null, making the check editable again."

    Design: Difficulty/non_linear_state_machine/check_cyclic_open_present_reopen_open
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        clock_iso="2026-06-02T10:00:00Z", party_size=2, name="R5", tax_rate_bps=0)
    sh = ctx["server_headers"]
    presented = validate_success(api.present_check(ctx["check"]["id"], sh))
    assert presented["final_subtotal_cents"] == 1000
    reopened = validate_success(api.reopen_check(ctx["check"]["id"], sh))
    assert reopened["status"] == "OPEN", f"reopen must return to OPEN, got {reopened['status']}"
    assert reopened["final_subtotal_cents"] is None, \
        f"reopen must clear final_subtotal_cents to null, got {reopened['final_subtotal_cents']}"


def test_comp_branch_keeps_count_consumed_unlike_void(api):
    """PRD §3.5: "Comping sets the item's comp_amount_cents to its full
    line_subtotal_cents, moves its status to COMPED, and recomputes the owning
    check's comp_total_cents and the downstream auto-gratuity, tax, and total.
    Crucially, a comp does not restore available_count — the portion was prepared
    and consumed, so it stays decremented."

    Design: Difficulty/non_linear_state_machine/order_item_branching_fired_to_comped_vs_served_divergent_effects
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        initial_available_count=5, clock_iso="2026-06-02T10:00:00Z",
        party_size=2, name="R6", tax_rate_bps=0, comp_cap_bps=10000)
    comped = validate_success(api.comp_order_item(ctx["order_item"]["id"], MANAGER))
    assert comped["status"] == "COMPED"
    assert comped["comp_amount_cents"] == 1000, \
        f"comp_amount must equal line_subtotal 1000, got {comped['comp_amount_cents']}"
    mi = get_success_data(api.get_menu_item(ctx["menu_item"]["id"], MANAGER))
    # 5 → 4 on fire; COMP leaves it at 4 (not restored to 5 as VOID would).
    assert mi["available_count"] == 4, \
        f"COMP must NOT restore the count (stays 4), got {mi['available_count']}"


# ===========================================================================
# Queue A — Rule 4: transitive_cascade
# ===========================================================================
def test_buss_promotes_head_waitlist_and_creates_seating(api):
    """PRD §3.3: "having freed the table, it auto-promotes the head of the
    waitlist: among WAITING entries whose party_size is less than or equal to this
    table's capacity, it selects the entry with the earliest quoted_at (tie-broken
    by earliest created_at); if such an entry exists, that entry moves from WAITING
    to PROMOTED. Third, the promotion creates a new seating with status OPEN on
    this table, sets the table's occupancy_status back to SEATED, records the new
    seating's id on the entry's seating_id, and advances the entry from PROMOTED
    to SEATED."

    Design: Difficulty/transitive_cascade/buss_depth3_free_table_promotes_waitlist_creates_seating
    """
    dt = setup_dirty_table(clock_iso="2026-06-03T12:00:00Z", table_capacity=4,
                           seating_party_size=3, name="R7", tax_rate_bps=0)
    r, tbl, tv = dt["restaurant"], dt["table"], dt["table_version"]
    wl = get_success_data(api.create_waitlist_entry(create_waitlist_payload(
        r["id"], party_name="Lee", party_size=2), HOST))
    bussed = validate_success(api.buss_table(tbl["id"], buss_table_payload(tv), HOST))
    assert bussed["occupancy_status"] == "SEATED", \
        f"table must be re-seated by the promotion, got {bussed['occupancy_status']}"
    wl_after = get_success_data(api.get_waitlist_entry(wl["id"], HOST))
    assert wl_after["status"] == "SEATED", \
        f"head waitlist entry must reach SEATED, got {wl_after['status']}"
    assert wl_after["seating_id"] is not None, \
        "promotion must record the created seating's id on the entry"


def test_void_item_restores_count_and_drops_from_provisional(api):
    """PRD §3.5: "Voiding is the compensating action for the eighty-six count: it
    restores the menu item's available_count by the item's quantity, recomputes
    is_86, sets the item's status to VOIDED, and recomputes the owning check's
    provisional_subtotal_cents so the line drops out of the gross subtotal
    entirely."

    Design: Difficulty/transitive_cascade/void_item_depth2_restores_86_count_and_subtotal
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=2,
        initial_available_count=5, clock_iso="2026-06-02T10:00:00Z",
        party_size=2, name="R8", tax_rate_bps=0)
    voided = validate_success(api.void_order_item(ctx["order_item"]["id"], MANAGER))
    assert voided["status"] == "VOIDED"
    mi = get_success_data(api.get_menu_item(ctx["menu_item"]["id"], MANAGER))
    assert mi["available_count"] == 5, \
        f"void must restore count 3→5, got {mi['available_count']}"
    chk = get_success_data(api.get_check(ctx["check"]["id"], ctx["server_headers"]))
    assert chk["provisional_subtotal_cents"] == 0, \
        f"voided line must drop out of provisional, got {chk['provisional_subtotal_cents']}"


# ===========================================================================
# Queue A — Rule 9: compensating_invariant
# ===========================================================================
def test_void_item_conserves_available_count_no_drift(api):
    """PRD §3.1: "The conserved invariant for portions is that available_count plus
    the total quantity across all of this menu item's order items that are
    currently fired, served, or comped always equals initial_available_count."
    PRD §3.5: "Voiding is the compensating action for the eighty-six count: it
    restores the menu item's available_count by the item's quantity".

    Design: Difficulty/compensating_invariant/void_item_conserves_menu_item_available_count
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=3,
        initial_available_count=10, clock_iso="2026-06-02T10:00:00Z",
        party_size=2, name="R17", tax_rate_bps=0)
    api.void_order_item(ctx["order_item"]["id"], MANAGER)
    mi = get_success_data(api.get_menu_item(ctx["menu_item"]["id"], MANAGER))
    # 10 → 7 on fire (qty 3) → 10 on void; conserved with no drift.
    assert mi["available_count"] == 10, \
        f"available_count must conserve back to 10, got {mi['available_count']}"
    assert mi["is_86"] is False, "is_86 must be false when count > 0"


def test_distribute_conserves_pooled_cents_across_shifts(api):
    """PRD §3.8: "After distribution the pool's distributed_cents is set to the sum
    of all allocation amount_cents, which must equal pooled_cents exactly, and the
    pool's status becomes DISTRIBUTED."

    Design: Difficulty/compensating_invariant/distribute_then_payout_conserves_tip_pool_cents
    """
    ctx = setup_closed_check_with_tip(
        tip_cents=10000, business_date="2026-06-01",
        clock_iso="2026-06-01T20:00:00Z", distribution_mode="EVEN_BY_HOURS",
        name="R18", tax_rate_bps=0,
        shifts=[
            {"role": "SERVER", "tip_weight_bps": 10000,
             "clock_in_minute": 600, "clock_out_minute": 1080},
            {"role": "BUSSER", "tip_weight_bps": 5000,
             "clock_in_minute": 1020, "clock_out_minute": 1320},
        ])
    distributed = validate_success(api.distribute_tip_pool(ctx["pool"]["id"], MANAGER))
    assert distributed["pooled_cents"] == 10000
    assert distributed["distributed_cents"] == 10000, \
        f"distributed must equal pooled with no drift, got {distributed['distributed_cents']}"
    assert distributed["status"] == "DISTRIBUTED"
    allocs, _ = validate_paginated(
        api.list_tip_allocations(MANAGER, params={"tip_pool_id": ctx["pool"]["id"]}))
    # EVEN_BY_HOURS: hours 800 and 500 → shares 6153.8 and 3846.2 → 6154 + 3846.
    amounts = sorted(a["amount_cents"] for a in allocs)
    assert amounts == [3846, 6154], f"EVEN_BY_HOURS split must be [3846,6154], got {amounts}"
    assert sum(amounts) == 10000
