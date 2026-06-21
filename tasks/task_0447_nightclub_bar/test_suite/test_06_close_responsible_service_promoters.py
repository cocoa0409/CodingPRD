"""Venue close cascade, last-call/over-service alcohol gates, posture lockdown,
clock-driven close, promoter comp budget, and FK integrity.

Difficulty (A): transitive_cascade (venue close depth-3).
Corner (B): last-call/over-service gates, venue-closed gate, clock-to-close auto,
comp-budget, fk-not-found, comp release on cancel, exit-already-exited.
"""
from test_helpers import validate_success, validate_error
from test_helpers import fixtures as fx
from test_helpers.constants import NONEXISTENT_UUID

ADMIN = fx.ADMIN
FLOOR = fx.FLOOR
DOOR = fx.DOOR
BAR = fx.BAR


# ── Venue close depth-3 cascade ──────────────────────────────────────────────

def test_venue_close_cascade_reservation_tab_preauth_depth3(api):
    """PRD §3.8: "Every reservation in `SEATED` is settled — moved
    `SEATED → SETTLED` with its `minimum_shortfall_cents` computed exactly as in
    §3.7 — which in turn drives the settlement of its linked tab, appending the
    minimum top-up where one is owed. Every tab still in `OPEN` or `RUNNING` is
    settled, its `final_total_cents` computed per §3.7 and its pre-authorization
    captured up to that total with the remainder released ...."
    PRD §3.8: "at the end the venue's `posture` becomes `CLOSED` ...."

    Design: Difficulty/transitive_cascade/venue_close_cascade_reservation_tab_preauth_depth3
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
    closed = validate_success(api.close_venue(venue["id"], FLOOR), 200)
    assert closed["posture"] == "CLOSED"
    res_after = validate_success(api.get_reservation(res["id"], FLOOR), 200)
    assert res_after["status"] == "SETTLED"
    assert res_after["minimum_shortfall_cents"] == 42800
    rt_after = validate_success(api.get_tab(rt["id"], BAR), 200)
    assert rt_after["status"] == "SETTLED"
    assert rt_after["final_total_cents"] == 50000


def test_venue_close_cascade_exits_inside_entries(api):
    """PRD §3.8: "Every entry still `INSIDE` is moved to `EXITED` with
    `exited_at_utc` stamped, driving the venue's `occupancy_count` to 0."

    Design: Difficulty/transitive_cascade/venue_close_cascade_reservation_tab_preauth_depth3
    """
    venue = fx.create_venue(name="V", fire_code_capacity=10)
    entry, _ = fx.admit_patron(venue["id"], venue["version"], patron_name="A")
    closed = validate_success(api.close_venue(venue["id"], FLOOR), 200)
    assert closed["posture"] == "CLOSED"
    assert closed["occupancy_count"] == 0
    entry_after = validate_success(api.get_entry(entry["id"], DOOR), 200)
    assert entry_after["status"] == "EXITED"


# ── Clock-driven auto close ──────────────────────────────────────────────────

def test_clock_to_close_auto_transitions_posture_closed(api):
    """PRD §3.8: "the system also closes a venue automatically when the logical
    clock reaches its `closing_time_utc`."
    PRD §3.8: "The venue moves to `CLOSED` once the clock reaches `closing_time_utc`."

    Design: Corner/cross_cutting_complexity_layers/clock_to_close_auto_transitions_posture_closed
    """
    venue = fx.create_venue(name="V", closing_time_utc="2026-03-16T06:00:00Z")
    fx.set_clock("2026-03-16T06:00:00Z")
    venue_after = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    assert venue_after["posture"] == "CLOSED"


# ── Venue-closed gate blocks child mutations ─────────────────────────────────

def test_venue_closed_blocks_child_mutation(api):
    """PRD §3.1: "No child mutation of any kind — no admission, exit, reservation or
    tab transition, item add or void, incident, or guest-list add — is permitted
    once a venue's `posture` is `CLOSED`; any such attempt is rejected with
    `ERR_VENUE_CLOSED`."

    Design: Corner/state_machines/venue_closed_blocks_child_mutation_returns_venue_closed
    """
    venue = fx.closed_venue(name="V")
    res = api.create_tab({"venue_id": venue["id"], "patron_name": "Late",
                          "preauth_cents": 5000}, BAR)
    validate_error(res, "ERR_VENUE_CLOSED", expected_status=409)


# ── Last-call gate blocks new alcohol ────────────────────────────────────────

def test_last_call_blocks_new_alcohol_item(api):
    """PRD §3.7: "The last-call gate forbids any new `ALCOHOL` item while the venue's
    `posture` is `LAST_CALL`, rejecting the add with `ERR_LAST_CALL_NO_ALCOHOL`."

    Design: Corner/state_machines/last_call_blocks_new_alcohol_item
    """
    venue = fx.create_venue(name="V", closing_time_utc="2026-03-16T06:00:00Z",
                            last_call_offset_minutes=30)
    tab = fx.open_tab(venue["id"], patron_name="T", preauth_cents=50000)
    fx.set_clock("2026-03-16T05:45:00Z")
    venue_lc = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    assert venue_lc["posture"] == "LAST_CALL"
    res = api.add_tab_item(tab["id"], {"name": "Whiskey", "category": "ALCOHOL",
                                       "qty": 1, "unit_price_cents": 1500}, BAR)
    validate_error(res, "ERR_LAST_CALL_NO_ALCOHOL", expected_status=422)


# ── Over-service gate ────────────────────────────────────────────────────────

def test_over_service_strike_cap_blocks_alcohol(api):
    """PRD §3.7: "The over-service gate forbids a new `ALCOHOL` item once the tab's
    `bac_strikes` has reached the venue's `max_alcohol_strikes` cap — that is, when
    `bac_strikes` is at least `max_alcohol_strikes` — rejecting the add with
    `ERR_OVER_SERVICE_REFUSED`."

    Design: Corner/state_machines/over_service_strike_cap_blocks_alcohol
    """
    venue = fx.create_venue(name="V", max_alcohol_strikes=2)
    tab, _ = fx.tab_with_items(
        venue["id"],
        [{"name": "Beer1", "category": "ALCOHOL", "qty": 1, "unit_price_cents": 1000},
         {"name": "Beer2", "category": "ALCOHOL", "qty": 1, "unit_price_cents": 1000}],
        patron_name="T", preauth_cents=50000,
    )
    tab_read = validate_success(api.get_tab(tab["id"], BAR), 200)
    assert tab_read["bac_strikes"] == 2
    res = api.add_tab_item(tab["id"], {"name": "Beer3", "category": "ALCOHOL",
                                       "qty": 1, "unit_price_cents": 1000}, BAR)
    validate_error(res, "ERR_OVER_SERVICE_REFUSED", expected_status=422)


# ── Exit already-exited entry ────────────────────────────────────────────────

def test_exit_already_exited_entry_rejected(api):
    """PRD §3.5: "Exit is permitted only while the entry's status is `INSIDE`;
    exiting an already-terminal entry is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/exit_already_exited_entry_returns_invalid_state
    """
    venue = fx.create_venue(name="V", fire_code_capacity=10)
    entry, _ = fx.admit_patron(venue["id"], venue["version"], patron_name="A")
    validate_success(api.exit_entry(entry["id"], DOOR), 200)
    res = api.exit_entry(entry["id"], DOOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    venue_after = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    assert venue_after["occupancy_count"] == 0


# ── Comp budget gate ─────────────────────────────────────────────────────────

def test_comp_budget_exceeded_on_guest_list_add(api):
    """PRD §3.2: "the entry's `comp_value_cents` must not push that promoter's
    `comp_committed_cents` above its `comp_budget_cents`. If accepting the entry
    would carry the committed total past the budget ceiling, the add is rejected
    with `ERR_COMP_BUDGET_EXCEEDED`."

    Design: Corner/validations/comp_budget_exceeded_on_guest_list_add
    """
    venue = fx.create_venue(name="V")
    promoter = fx.create_promoter(venue["id"], name="PR", comp_budget_cents=1000,
                                  guest_discount_pct=0.5)
    fx.create_guest_list_entry(venue["id"], guest_name="G1", party_size=1,
                               promoter_id=promoter["id"], comp_value_cents=800)
    res = api.create_guest_list_entry(
        {"venue_id": venue["id"], "guest_name": "G2", "party_size": 1,
         "promoter_id": promoter["id"], "comp_value_cents": 500},
        DOOR,
    )
    validate_error(res, "ERR_COMP_BUDGET_EXCEEDED", expected_status=422)
    promoter_after = validate_success(api.get_promoter(promoter["id"], FLOOR), 200)
    assert promoter_after["comp_committed_cents"] == 800


# ── FK not found on unknown promoter ─────────────────────────────────────────

def test_fk_not_found_on_unknown_promoter(api):
    """PRD §2.8: "when a write body carries a foreign key — a `promoter_id`, a
    `reservation_id`, a `guest_list_entry_id`, an `id_check_id`, or a
    `subject_entry_id` — the referenced row must exist and must belong to the same
    venue as the resource being written; a dangling or cross-venue reference is
    rejected with `ERR_FK_NOT_FOUND`."

    Design: Corner/validations/fk_not_found_on_unknown_promoter_in_guest_list
    """
    venue = fx.create_venue(name="V")
    res = api.create_guest_list_entry(
        {"venue_id": venue["id"], "guest_name": "G", "party_size": 1,
         "promoter_id": NONEXISTENT_UUID, "comp_value_cents": 100},
        DOOR,
    )
    validate_error(res, "ERR_FK_NOT_FOUND", expected_status=404)


# ── Comp committed reconciles on cancel ──────────────────────────────────────

def test_comp_committed_releases_on_cancel(api):
    """PRD §3.2: "Cancelling a guest-list entry sets its `status` to `CANCELLED` and
    recomputes the promoter's `comp_committed_cents`, releasing that entry's comp
    back into the budget — because a `CANCELLED` entry no longer counts toward the
    committed sum."

    Design: Corner/cross_cutting_complexity_layers/derived_promoter_comp_committed_releases_on_cancel
    """
    venue = fx.create_venue(name="V")
    promoter = fx.create_promoter(venue["id"], name="PR", comp_budget_cents=5000)
    gle = fx.create_guest_list_entry(venue["id"], guest_name="G", party_size=1,
                                     promoter_id=promoter["id"], comp_value_cents=800)
    cancelled = validate_success(api.cancel_guest_list_entry(gle["id"], DOOR), 200)
    assert cancelled["status"] == "CANCELLED"
    promoter_after = validate_success(api.get_promoter(promoter["id"], FLOOR), 200)
    assert promoter_after["comp_committed_cents"] == 0
