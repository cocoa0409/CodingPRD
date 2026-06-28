"""Bar tabs, line items, gratuity rounding, reservation minimum top-up, and settlement.

Difficulty (A): dual_variant_calc (tab final), combinatorial_formula (sum-then-round),
non_linear_state_machine (running<->open revert), reservation_shortfall (mode c),
cross_entity_state_dependency (reservation settle drives tab), compensating_invariant
(void conserves subtotal).
Corner (B): met-minimum variant, preauth-insufficient, tab-not-empty, already-settled,
filtered list by reservation_id.
"""
from test_helpers import validate_success, validate_error, validate_paginated
from test_helpers import fixtures as fx

ADMIN = fx.ADMIN
FLOOR = fx.FLOOR
BAR = fx.BAR


# ── Dual variant: walk-up tab vs under-minimum reservation tab ───────────────

def test_tab_final_total_walk_up_vs_reservation_tab(api):
    """PRD §3.7: "For a walk-up tab — one whose `reservation_id` is null — that
    grand total is the whole story, with no minimum top-up."
    PRD §3.7: "When the pre-top-up total falls under the minimum, the shortfall is
    positive, the top-up line is appended at a `unit_price_cents` equal to the
    shortfall, and the tab's `final_total_cents` lands exactly on
    `spend_minimum_cents`."

    Design: Difficulty/dual_variant_calc/tab_final_total_walk_up_vs_reservation_tab
    """
    venue = fx.create_venue(name="V", fire_code_capacity=10, cover_base_cents=2000)
    # Walk-up tab: 5 ALCOHOL @1200 -> subtotal 6000, gratuity 0.2 -> 7200.
    w_tab, _ = fx.tab_with_items(
        venue["id"],
        [{"name": "Vodka", "category": "ALCOHOL", "qty": 5, "unit_price_cents": 1200}],
        patron_name="Walkup", preauth_cents=100000, gratuity_pct=0.2,
    )
    # Reservation tab: same lines, spend_minimum 50000.
    res, version = fx.book_and_seat_reservation(
        venue["id"], venue["version"], table_label="VIP-1", party_size=4,
        window_start_utc="2026-01-01T00:00:00Z", window_end_utc="2026-03-16T05:00:00Z",
        spend_minimum_cents=50000,
    )
    r_tab, _ = fx.reservation_tab_with_items(
        venue["id"], res["id"],
        [{"name": "Vodka", "category": "ALCOHOL", "qty": 5, "unit_price_cents": 1200}],
        patron_name="VIP", preauth_cents=100000, gratuity_pct=0.2,
    )
    w_settled = validate_success(api.settle_tab(w_tab["id"], BAR), 200)
    assert w_settled["final_total_cents"] == 7200
    validate_success(api.settle_reservation(res["id"], FLOOR), 200)
    r_after = validate_success(api.get_tab(r_tab["id"], BAR), 200)
    assert r_after["final_total_cents"] == 50000
    assert w_settled["final_total_cents"] != r_after["final_total_cents"]


def test_walk_up_tab_final_total_is_subtotal_plus_gratuity(api):
    """PRD §3.7: "For a walk-up tab — one whose `reservation_id` is null — that
    grand total is the whole story, with no minimum top-up."
    PRD §3.7: "the grand total is the subtotal plus that single rounded gratuity."

    Design: Difficulty/dual_variant_calc/tab_final_total_walk_up_vs_reservation_tab
    """
    venue = fx.create_venue(name="V")
    tab, _ = fx.tab_with_items(
        venue["id"],
        [{"name": "Vodka", "category": "ALCOHOL", "qty": 5, "unit_price_cents": 1200}],
        patron_name="Walkup", preauth_cents=100000, gratuity_pct=0.2,
    )
    settled = validate_success(api.settle_tab(tab["id"], BAR), 200)
    # subtotal 6000 + round_half_up(6000*0.2)=1200 -> 7200.
    assert settled["final_total_cents"] == 7200


# ── Combinatorial: gratuity is sum-then-round, once ──────────────────────────

def test_tab_gratuity_sum_then_round(api):
    """PRD §3.7: "the gratuity is that summed subtotal multiplied by the tab's
    `gratuity_pct` and then rounded half-up to the nearest cent exactly once on the
    summed figure (sum first, then round — never round each line and then sum); and
    the grand total is the subtotal plus that single rounded gratuity."

    Design: Difficulty/combinatorial_formula/tab_gratuity_sum_then_round_mode_b
    """
    venue = fx.create_venue(name="V")
    tab, _ = fx.tab_with_items(
        venue["id"],
        [{"name": "Steak", "category": "FOOD", "qty": 1, "unit_price_cents": 2510},
         {"name": "Lobster", "category": "FOOD", "qty": 1, "unit_price_cents": 2510}],
        patron_name="T", preauth_cents=100000, gratuity_pct=0.15,
    )
    tab_read = validate_success(api.get_tab(tab["id"], BAR), 200)
    assert tab_read["running_subtotal_cents"] == 5020
    settled = validate_success(api.settle_tab(tab["id"], BAR), 200)
    # gratuity = round_half_up(5020 * 0.15) = 753; grand = 5020 + 753 = 5773.
    assert settled["final_total_cents"] == 5773


def test_tab_gratuity_single_rounding_per_line_would_differ(api):
    """PRD §3.7: "the gratuity is that summed subtotal multiplied by the tab's
    `gratuity_pct` and then rounded half-up to the nearest cent exactly once on the
    summed figure (sum first, then round — never round each line and then sum) ...."

    Design: Difficulty/combinatorial_formula/tab_gratuity_sum_then_round_mode_b
    """
    venue = fx.create_venue(name="V")
    tab, _ = fx.tab_with_items(
        venue["id"],
        [{"name": "A", "category": "FOOD", "qty": 1, "unit_price_cents": 2510},
         {"name": "B", "category": "FOOD", "qty": 1, "unit_price_cents": 2510}],
        patron_name="T", preauth_cents=100000, gratuity_pct=0.15,
    )
    settled = validate_success(api.settle_tab(tab["id"], BAR), 200)
    # round-per-line-then-sum would give 377*2=754 -> grand 5774; sum-then-round is 5773.
    assert settled["final_total_cents"] == 5773
    assert settled["final_total_cents"] != 5774


# ── Reservation shortfall: circular eval order (mode c) ──────────────────────

def test_reservation_shortfall_circular_eval_order(api):
    """PRD §3.7: "First, the linked tab's pre-top-up grand total is computed exactly
    as an ordinary settlement would compute it ... Second, the shortfall is the
    contracted `spend_minimum_cents` minus that pre-top-up grand total, floored at
    zero. Third, if the shortfall is positive, a single `SERVICE` line named
    "Minimum top-up" is appended to the linked tab ... because this line is appended
    only after the gratuity has already been computed in the first step, it does not
    itself attract gratuity. Fourth, the tab then settles, and its
    `final_total_cents` is the pre-top-up grand total plus the shortfall ...."

    Design: Difficulty/dual_variant_calc/reservation_shortfall_circular_eval_order_mode_c
    """
    venue = fx.create_venue(name="V")
    res, version = fx.book_and_seat_reservation(
        venue["id"], venue["version"], table_label="VIP-1", party_size=4,
        window_start_utc="2026-01-01T00:00:00Z", window_end_utc="2026-03-16T05:00:00Z",
        spend_minimum_cents=50000,
    )
    rt, _ = fx.reservation_tab_with_items(
        venue["id"], res["id"],
        [{"name": "Bottle", "category": "ALCOHOL", "qty": 5, "unit_price_cents": 1200}],
        patron_name="VIP", preauth_cents=100000, gratuity_pct=0.2,
    )
    settled_res = validate_success(api.settle_reservation(res["id"], FLOOR), 200)
    # pre-top-up grand = 6000 + 1200 = 7200; shortfall = 50000 - 7200 = 42800.
    assert settled_res["minimum_shortfall_cents"] == 42800
    rt_after = validate_success(api.get_tab(rt["id"], BAR), 200)
    assert rt_after["final_total_cents"] == 50000


def test_reservation_shortfall_appends_service_topup_line(api):
    """PRD §3.7: "if the shortfall is positive, a single `SERVICE` line named
    "Minimum top-up" is appended to the linked tab with `qty` 1 and
    `unit_price_cents` equal to the shortfall ...."

    Design: Difficulty/dual_variant_calc/reservation_shortfall_circular_eval_order_mode_c
    """
    venue = fx.create_venue(name="V")
    res, version = fx.book_and_seat_reservation(
        venue["id"], venue["version"], table_label="VIP-1", party_size=4,
        window_start_utc="2026-01-01T00:00:00Z", window_end_utc="2026-03-16T05:00:00Z",
        spend_minimum_cents=50000,
    )
    rt, _ = fx.reservation_tab_with_items(
        venue["id"], res["id"],
        [{"name": "Bottle", "category": "ALCOHOL", "qty": 5, "unit_price_cents": 1200}],
        patron_name="VIP", preauth_cents=100000, gratuity_pct=0.2,
    )
    validate_success(api.settle_reservation(res["id"], FLOOR), 200)
    items, _ = validate_paginated(api.list_tab_items(rt["id"], BAR))
    service_lines = [it for it in items
                     if it["category"] == "SERVICE" and not it["voided"]]
    assert len(service_lines) == 1
    assert service_lines[0]["unit_price_cents"] == 42800


# ── Met-minimum variant: no top-up ───────────────────────────────────────────

def test_reservation_minimum_met_no_topup(api):
    """PRD §3.7: "When the pre-top-up total already meets or exceeds the minimum,
    the shortfall is zero, no `SERVICE` line is appended, and the tab's
    `final_total_cents` is just the pre-top-up grand total."

    Design: Corner/calculations/reservation_minimum_met_no_topup
    """
    venue = fx.create_venue(name="V")
    res, version = fx.book_and_seat_reservation(
        venue["id"], venue["version"], table_label="VIP-1", party_size=4,
        window_start_utc="2026-01-01T00:00:00Z", window_end_utc="2026-03-16T05:00:00Z",
        spend_minimum_cents=5000,
    )
    fx.reservation_tab_with_items(
        venue["id"], res["id"],
        [{"name": "Platter", "category": "FOOD", "qty": 1, "unit_price_cents": 6000}],
        patron_name="VIP", preauth_cents=100000, gratuity_pct=0.2,
    )
    settled = validate_success(api.settle_reservation(res["id"], FLOOR), 200)
    assert settled["minimum_shortfall_cents"] == 0


# ── Reservation settle drives linked tab (cross-entity) ──────────────────────

def test_reservation_settle_drives_linked_tab(api):
    """PRD §3.7: "its linked tab (the tab whose `reservation_id` names this
    reservation), if one exists, is settled as part of this operation."
    PRD §3.7: "the reservation's `minimum_shortfall_cents` records the same
    shortfall, and the reservation moves `SEATED → SETTLED`."

    Design: Difficulty/cross_entity_state_dependency/reservation_settle_requires_linked_tab_settleable
    """
    venue = fx.create_venue(name="V")
    res, version = fx.book_and_seat_reservation(
        venue["id"], venue["version"], table_label="VIP-1", party_size=4,
        window_start_utc="2026-01-01T00:00:00Z", window_end_utc="2026-03-16T05:00:00Z",
        spend_minimum_cents=5000,
    )
    rt, _ = fx.reservation_tab_with_items(
        venue["id"], res["id"],
        [{"name": "Platter", "category": "FOOD", "qty": 1, "unit_price_cents": 6000}],
        patron_name="VIP", preauth_cents=100000, gratuity_pct=0.2,
    )
    settled_res = validate_success(api.settle_reservation(res["id"], FLOOR), 200)
    assert settled_res["status"] == "SETTLED"
    assert settled_res["minimum_shortfall_cents"] == 0
    rt_after = validate_success(api.get_tab(rt["id"], BAR), 200)
    assert rt_after["status"] == "SETTLED"
    assert rt_after["final_total_cents"] == 7200


def test_reservation_settle_no_linked_tab_shortfall_is_full_minimum(api):
    """PRD §3.7: "If a seated reservation has no linked tab at all, the pre-top-up
    grand total is treated as zero, so the shortfall equals the full
    `spend_minimum_cents`."

    Design: Difficulty/cross_entity_state_dependency/reservation_settle_requires_linked_tab_settleable
    """
    venue = fx.create_venue(name="V")
    res, _ = fx.book_and_seat_reservation(
        venue["id"], venue["version"], table_label="VIP-2", party_size=4,
        window_start_utc="2026-01-01T00:00:00Z", window_end_utc="2026-03-16T05:00:00Z",
        spend_minimum_cents=5000,
    )
    settled = validate_success(api.settle_reservation(res["id"], FLOOR), 200)
    assert settled["status"] == "SETTLED"
    assert settled["minimum_shortfall_cents"] == 5000


# ── Non-linear: RUNNING -> OPEN revert on last void ──────────────────────────

def test_tab_running_to_open_revert_on_last_void(api):
    """PRD §3.7: "If voiding leaves zero non-voided items on the tab, the tab
    reverts `RUNNING → OPEN`, its `running_subtotal_cents` returns to 0, and its
    `bac_strikes` resets to 0."

    Design: Difficulty/non_linear_state_machine/tab_running_to_open_revert_on_last_void
    """
    venue = fx.create_venue(name="V")
    tab, items = fx.tab_with_items(
        venue["id"],
        [{"name": "Beer", "category": "ALCOHOL", "qty": 1, "unit_price_cents": 1200}],
        patron_name="T", preauth_cents=50000,
    )
    validate_success(api.void_tab_item(tab["id"], items[0]["id"], BAR), 200)
    tab_after = validate_success(api.get_tab(tab["id"], BAR), 200)
    assert tab_after["status"] == "OPEN"
    assert tab_after["running_subtotal_cents"] == 0
    assert tab_after["bac_strikes"] == 0


def test_tab_open_to_running_on_first_item(api):
    """PRD §3.7: "The first non-voided item on a tab advances it `OPEN → RUNNING`;
    subsequent adds keep it `RUNNING`."

    Design: Difficulty/non_linear_state_machine/tab_running_to_open_revert_on_last_void
    """
    venue = fx.create_venue(name="V")
    tab = fx.open_tab(venue["id"], patron_name="T", preauth_cents=50000)
    assert tab["status"] == "OPEN"
    fx.add_item(tab["id"], name="Beer", category="ALCOHOL", qty=1, unit_price_cents=1200)
    tab_after = validate_success(api.get_tab(tab["id"], BAR), 200)
    assert tab_after["status"] == "RUNNING"
    assert tab_after["running_subtotal_cents"] == 1200


# ── Compensating: void item conserves subtotal ───────────────────────────────

def test_void_item_conserves_subtotal(api):
    """PRD §3.7: "Voiding a line ... sets that line's `voided` flag to true and
    excludes it from the subtotal; the `running_subtotal_cents` is recomputed
    accordingly."
    PRD §3.7: "Each add recomputes the tab's `running_subtotal_cents`, which is the
    sum over the tab's non-voided lines of each line's `qty` multiplied by its
    `unit_price_cents`."

    Design: Difficulty/compensating_invariant/tab_void_item_then_readd_conserves_subtotal
    """
    venue = fx.create_venue(name="V")
    tab, items = fx.tab_with_items(
        venue["id"],
        [{"name": "A", "category": "FOOD", "qty": 1, "unit_price_cents": 2000},
         {"name": "B", "category": "FOOD", "qty": 1, "unit_price_cents": 1500}],
        patron_name="T", preauth_cents=100000, gratuity_pct=0.2,
    )
    validate_success(api.void_tab_item(tab["id"], items[1]["id"], BAR), 200)
    tab_after = validate_success(api.get_tab(tab["id"], BAR), 200)
    assert tab_after["running_subtotal_cents"] == 2000
    assert tab_after["status"] == "RUNNING"


def test_void_alcohol_item_decrements_strikes_conserving_subtotal(api):
    """PRD §3.7: "If the voided line was `ALCOHOL`, the tab's `bac_strikes` is
    decremented by one."
    PRD §3.7: "the `running_subtotal_cents` is recomputed accordingly."

    Design: Difficulty/compensating_invariant/tab_void_item_then_readd_conserves_subtotal
    """
    venue = fx.create_venue(name="V")
    tab, items = fx.tab_with_items(
        venue["id"],
        [{"name": "Beer", "category": "ALCOHOL", "qty": 1, "unit_price_cents": 2000},
         {"name": "Wine", "category": "ALCOHOL", "qty": 1, "unit_price_cents": 1500}],
        patron_name="T", preauth_cents=100000, gratuity_pct=0.2,
    )
    before = validate_success(api.get_tab(tab["id"], BAR), 200)
    assert before["bac_strikes"] == 2
    assert before["running_subtotal_cents"] == 3500
    validate_success(api.void_tab_item(tab["id"], items[1]["id"], BAR), 200)
    after = validate_success(api.get_tab(tab["id"], BAR), 200)
    assert after["bac_strikes"] == 1
    assert after["running_subtotal_cents"] == 2000


# ── Settlement gates ─────────────────────────────────────────────────────────

def test_settle_preauth_insufficient_rejected(api):
    """PRD §3.7: "Unless the settlement is forced by the venue-close cascade, the
    tab's `preauth_cents` must be at least the projected `final_total_cents`; a
    settlement that would exceed the hold is rejected with
    `ERR_PREAUTH_INSUFFICIENT`."

    Design: Corner/validations/preauth_insufficient_blocks_settle
    """
    venue = fx.create_venue(name="V")
    tab, _ = fx.tab_with_items(
        venue["id"],
        [{"name": "Burger", "category": "FOOD", "qty": 1, "unit_price_cents": 1000}],
        patron_name="T", preauth_cents=1000, gratuity_pct=0.2,
    )
    res = api.settle_tab(tab["id"], BAR)
    validate_error(res, "ERR_PREAUTH_INSUFFICIENT", expected_status=422)
    tab_after = validate_success(api.get_tab(tab["id"], BAR), 200)
    assert tab_after["status"] == "RUNNING"


def test_void_tab_with_charges_rejected(api):
    """PRD §3.7: "A tab void is permitted only when the tab's
    `running_subtotal_cents` is exactly 0 — a tab that is carrying charges cannot be
    voided and must be settled instead, and the attempt to void it is rejected with
    `ERR_TAB_NOT_EMPTY`."

    Design: Corner/state_machines/void_tab_with_charges_returns_tab_not_empty
    """
    venue = fx.create_venue(name="V")
    tab, _ = fx.tab_with_items(
        venue["id"],
        [{"name": "Beer", "category": "ALCOHOL", "qty": 1, "unit_price_cents": 2000}],
        patron_name="T", preauth_cents=50000,
    )
    res = api.void_tab(tab["id"], FLOOR)
    validate_error(res, "ERR_TAB_NOT_EMPTY", expected_status=409)


def test_settle_already_settled_tab_rejected(api):
    """PRD §3.7: "Settling an already-`SETTLED` or `VOIDED` tab is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/settle_already_settled_tab_returns_invalid_state
    """
    venue = fx.create_venue(name="V")
    tab, _ = fx.tab_with_items(
        venue["id"],
        [{"name": "Fries", "category": "FOOD", "qty": 1, "unit_price_cents": 1000}],
        patron_name="T", preauth_cents=50000, gratuity_pct=0.2,
    )
    validate_success(api.settle_tab(tab["id"], BAR), 200)
    res = api.settle_tab(tab["id"], BAR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ── Filtered list by reservation_id ──────────────────────────────────────────

def test_filtered_list_tabs_by_reservation_id(api):
    """PRD §3.7: "Tabs may be listed and filtered by `venue_id`, by `status`, and by
    `reservation_id`."

    Design: Corner/endpoints/filtered_list_tabs_by_reservation_id_reverse_reachability
    """
    venue = fx.create_venue(name="V")
    res, version = fx.book_and_seat_reservation(
        venue["id"], venue["version"], table_label="VIP-1", party_size=4,
        window_start_utc="2026-01-01T00:00:00Z", window_end_utc="2026-03-16T05:00:00Z",
        spend_minimum_cents=10000,
    )
    rt = fx.open_tab(venue["id"], patron_name="VIP", preauth_cents=50000,
                     reservation_id=res["id"])
    fx.open_tab(venue["id"], patron_name="Walk", preauth_cents=50000)
    data, meta = validate_paginated(api.list_tabs(BAR, params={"reservation_id": res["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == rt["id"]
