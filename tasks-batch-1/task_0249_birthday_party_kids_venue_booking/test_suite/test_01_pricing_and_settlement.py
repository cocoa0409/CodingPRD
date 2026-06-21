"""Quote estimate vs. settlement, deposit derivation, and add-on re-pricing.

Covers the dual-variant calculation pair (estimate quote vs. peak settlement),
the pinned deposit/balance evaluation order, the half-open room geometry on hold,
and the add-on pricing/duration reconciliation.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_config, create_quote_draft_booking, hold_booking, add_addon,
    record_roster, take_payment, sign_n_waivers, create_staff, assign_staff,
    set_clock, reset_clock_base,
    create_confirmed_booking, assert_instant_eq,
)

VM = "venue_manager_headers"
COORD = "coordinator_headers"


# ─── Difficulty: dual_variant_calc / dvc_quote_estimate_vs_settlement_peak ──────

def test_settlement_charges_peak_while_quote_charges_net(api, coordinator_headers):
    """PRD 3.10: "Where the quote estimate prices against the net-current children
    count, the settlement prices against the *peak* children count realized over the
    booking's history — these diverge whenever head count was raised and later
    lowered, because the estimate sees only the net while the settlement charges the
    peak."

    Design: Difficulty/dual_variant_calc/dvc_quote_estimate_vs_settlement_peak
    """
    venue, room, package = setup_config(
        base_price_cents=30000, included_children=8, per_extra_child_cents=1500,
        deposit_pct=0.25, max_capacity=20)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    add_addon(bid, "CAKE", 4500)
    add_addon(bid, "CHARACTER", 12000)
    hold_booking(bid)
    host = create_staff(venue["id"], "Host H", ["HOST"])
    assign_staff(bid, host["id"], "HOST")
    ent = create_staff(venue["id"], "Ent E", ["ENTERTAINER"])
    assign_staff(bid, ent["id"], "ENTERTAINER")
    cook = create_staff(venue["id"], "Cook C", ["COOK"])
    assign_staff(bid, cook["id"], "COOK")
    sign_n_waivers(bid, 8)
    take_payment(bid, 46500, direction="CHARGE", purpose="BALANCE")
    get_success_data(api.confirm_booking(bid, coordinator_headers))

    # Raise to 14 children, then lower to 9: net is 9, peak is 14.
    record_roster(bid, children_delta=6, reason="more kids")
    record_roster(bid, children_delta=-5, reason="fewer kids")
    # Clear the settlement balance (peak overage adds 7500 over the net quote).
    take_payment(bid, 9000, direction="CHARGE", purpose="BALANCE")
    set_clock("2026-07-01T13:00:00Z")

    completed = validate_success(api.complete_booking(bid, coordinator_headers), 200)
    assert completed["status"] == "COMPLETED"
    # Net-current 9 children: overage 1 -> package 31500 + addons 16500 = 48000.
    assert completed["quote_total_cents"] == 48000
    # Peak 14 children: overage 6 -> package 39000 + addons 16500 = 55500.
    assert completed["final_total_cents"] == 55500
    assert completed["final_total_cents"] != completed["quote_total_cents"]


def test_quote_uses_net_current_children_count(api, coordinator_headers):
    """PRD 3.2: "It prices the booking forward from its currently active line items.
    First the system finds how many children exceed the package's included allotment
    — the overage is the children count minus `included_children`, but never below
    zero."

    Design: Difficulty/dual_variant_calc/dvc_quote_estimate_vs_settlement_peak
    """
    venue, room, package = setup_config(
        base_price_cents=30000, included_children=8, per_extra_child_cents=1500)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    add_addon(bid, "CAKE", 4500)
    add_addon(bid, "CHARACTER", 12000)
    # Raise to 14 then lower to 9; the live quote estimate must track the net (9).
    record_roster(bid, children_delta=6)
    record_roster(bid, children_delta=-5)
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    # Net 9: overage 1 -> 30000 + 1500 + 4500 + 12000 = 48000.
    assert booking["quote_total_cents"] == 48000


# ─── Corner: calculations / quote_overage_pricing_correct ──────────────────────

def test_quote_overage_pricing_correct(api, coordinator_headers):
    """PRD 3.2: "The package charge is `base_price_cents` plus that overage multiplied
    by `per_extra_child_cents`."

    Design: Corner/calculations/quote_overage_pricing_correct
    """
    venue, room, package = setup_config(
        base_price_cents=30000, included_children=8, per_extra_child_cents=1500,
        max_capacity=20)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=11)
    # Overage 3 -> 30000 + 3*1500 = 34500, no add-ons.
    assert booking["quote_total_cents"] == 34500


# ─── Corner: calculations / quote_excludes_removed_addons ──────────────────────

def test_quote_excludes_removed_addons(api, coordinator_headers):
    """PRD 3.2: "the sum, over every add-on still in `ACTIVE` status, of its
    `unit_price_cents` multiplied by its `quantity`."
    PRD 3.3: "An add-on starts `ACTIVE` and may be removed to `REMOVED`, at which point
    it drops out of both pricing and duration."

    Design: Corner/calculations/quote_excludes_removed_addons
    """
    venue, room, package = setup_config(base_price_cents=30000, included_children=8)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    addon = add_addon(bid, "CAKE", 4500)
    removed = validate_success(api.delete_add_on(bid, addon["id"], coordinator_headers), 200)
    assert removed["status"] == "REMOVED"
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["quote_total_cents"] == 30000


# ─── Corner: calculations / deposit_due_ceiling_rounding ───────────────────────

def test_deposit_due_ceiling_rounding(api, coordinator_headers):
    """PRD 3.7: "then `deposit_due_cents` is set to `quote_total_cents` multiplied by
    the package's `deposit_pct`, taken up to the next whole cent by ceiling".

    Design: Corner/calculations/deposit_due_ceiling_rounding
    """
    venue, room, package = setup_config(
        base_price_cents=30001, included_children=8, deposit_pct=0.25)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    held = validate_success(api.hold_booking(booking["id"], coordinator_headers), 200)
    assert held["quote_total_cents"] == 30001
    # ceil(30001 * 0.25) = ceil(7500.25) = 7501.
    assert held["deposit_due_cents"] == 7501


# ─── Difficulty: combinatorial_formula / cf_deposit_balance_eval_order ─────────

def test_deposit_and_balance_pinned_evaluation_order(api, coordinator_headers):
    """PRD 3.7: "First `quote_total_cents` is computed from the line items alone; then
    `deposit_due_cents` is set to `quote_total_cents` multiplied by the package's
    `deposit_pct`, taken up to the next whole cent by ceiling; then `balance_due_cents`
    is computed as `quote_total_cents` minus `amount_paid_cents`."

    Design: Difficulty/combinatorial_formula/cf_deposit_balance_eval_order
    """
    venue, room, package = setup_config(
        base_price_cents=30000, included_children=8, deposit_pct=0.25)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    add_addon(bid, "CAKE", 4500)
    add_addon(bid, "CHARACTER", 12000)
    held = validate_success(api.hold_booking(bid, coordinator_headers), 200)
    assert held["quote_total_cents"] == 46500
    assert held["deposit_due_cents"] == 11625        # ceil(46500 * 0.25)
    assert held["balance_due_cents"] == 46500        # quote - 0 paid


def test_balance_independent_of_deposit(api, coordinator_headers):
    """PRD 3.7: "The balance depends on the quote and the amount paid, not on the
    deposit, so once this order is fixed there is no real cycle."

    Design: Difficulty/combinatorial_formula/cf_deposit_balance_eval_order
    """
    venue, room, package = setup_config(
        base_price_cents=30000, included_children=8, deposit_pct=0.25)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    add_addon(bid, "CAKE", 4500)
    add_addon(bid, "CHARACTER", 12000)
    held = validate_success(api.hold_booking(bid, coordinator_headers), 200)
    # balance is quote - amount_paid (= 46500 - 0), NOT quote - deposit.
    assert held["balance_due_cents"] == held["quote_total_cents"] - held["amount_paid_cents"]
    assert held["balance_due_cents"] != held["quote_total_cents"] - held["deposit_due_cents"]


# ─── Difficulty: combinatorial_formula / cf_room_window_geometry_half_open ─────

def test_adjacent_hold_at_buffer_edge_accepted(api, coordinator_headers):
    """PRD 3.7: "Because the intervals are half-open, exact adjacency — one booking's
    buffered end equal to the next's start — is not a conflict, so a room can host
    back-to-back parties as long as the cleanup buffer fits between them."

    Design: Difficulty/combinatorial_formula/cf_room_window_geometry_half_open
    """
    venue, room, package = setup_config(
        buffer_minutes=30, base_duration_minutes=120, max_capacity=20)
    a = create_quote_draft_booking(room["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-01T10:00:00Z")
    hold_booking(a["id"])  # occupies [10:00, 12:30)
    b = create_quote_draft_booking(room["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-01T12:30:00Z")
    held_b = validate_success(api.hold_booking(b["id"], coordinator_headers), 200)
    assert held_b["status"] == "HELD"
    assert_instant_eq(held_b["event_end_utc"], "2026-07-01T14:30:00Z")


def test_overlapping_hold_inside_buffer_conflicts(api, coordinator_headers):
    """PRD 3.7: "Two such occupancies conflict when the first starts strictly before
    the second's buffered end and the second starts strictly before the first's
    buffered end."

    Design: Difficulty/combinatorial_formula/cf_room_window_geometry_half_open
    """
    venue, room, package = setup_config(
        buffer_minutes=30, base_duration_minutes=120, max_capacity=20)
    a = create_quote_draft_booking(room["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-01T10:00:00Z")
    hold_booking(a["id"])  # occupies [10:00, 12:30)
    # A second hold starting at 12:29 falls strictly inside the first's buffered end.
    b = create_quote_draft_booking(room["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-01T12:29:00Z")
    res = api.hold_booking(b["id"], coordinator_headers)
    validate_error(res, "ERR_ROOM_WINDOW_CONFLICT")


# ─── Corner: calculations / extra_time_addon_extends_effective_duration ────────

def test_extra_time_addon_extends_effective_duration(api, coordinator_headers):
    """PRD 3.3: "The booking's `effective_duration_minutes` is the package's
    `base_duration_minutes` plus, summed over every active extra-time add-on, that
    add-on's `extra_minutes` multiplied by its `quantity`."

    Design: Corner/calculations/extra_time_addon_extends_effective_duration
    """
    venue, room, package = setup_config(base_duration_minutes=120)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    add_addon(bid, "EXTRA_TIME", 5000, extra_minutes=60)
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["effective_duration_minutes"] == 180
    assert_instant_eq(booking["event_end_utc"], "2026-07-01T13:00:00Z")
