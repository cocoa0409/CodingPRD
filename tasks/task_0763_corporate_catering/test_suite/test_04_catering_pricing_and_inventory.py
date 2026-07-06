"""Catering: volume-discount client charge (round-per-line-then-sum), estimate-vs-final
cost divergence, inventory reserve/release conservation, venue temporal overlap, capacity,
and confirm-time validation ordering (PRD §2.8, §2.10, §3.6).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_catering_order, create_site, create_cycle, add_item, create_venue,
    stock_site, get_site_version, get_lot, create_catering_order_payload,
    make_coordinator_headers,
)

FINANCE = TEST_USERS["finance_controller_headers"]

WRAP = {"name": "Wrap", "category": "ENTREE", "price_cents": 350, "standard_recipe_cost_cents": 120}
CUP = {"name": "Cup", "category": "SIDE", "price_cents": 350, "standard_recipe_cost_cents": 120}


def _two_line_order(api, coord_id="coord-1", headcount=25):
    """Site + venue + Wrap & Cup; returns (site, venue, wrap, cup, coord_headers)."""
    site = create_site()
    cycle = create_cycle(site["id"])
    wrap = add_item(cycle["id"], **WRAP)
    cup = add_item(cycle["id"], **CUP)
    venue = create_venue(site["id"])
    coord = make_coordinator_headers(coord_id)
    lines = [{"menu_item_id": wrap["id"], "qty": 1}, {"menu_item_id": cup["id"], "qty": 1}]
    order = validate_success(api.create_catering_order(
        create_catering_order_payload(site["id"], venue["id"], lines, headcount=headcount), coord), 201)
    return site, venue, order, coord


# ─── Difficulty: combinatorial_formula — round per line then sum ─────────────
def test_catering_order_charge_rounds_each_line_then_sums(api):
    """PRD §3.6: "for each line, the `line_charge` is the menu item's `price_cents` times
    `qty` times one minus the discount fraction, rounded half up to whole cents; the
    `order_charge_cents` is the sum of those per-line charges (rounding each line first,
    then summing)."
    PRD §3.6: "a volume discount driven by headcount — 15 percent when `headcount` is at
    least 100, otherwise 10 percent when it is at least 50, otherwise 5 percent when it is
    at least 20, otherwise none."

    Design: Difficulty/combinatorial_formula/catering_per_line_round_then_sum
    """
    site, venue, order, coord = _two_line_order(api, headcount=25)
    submitted = validate_success(api.submit_catering_order(order["id"], coord), 200)
    assert submitted["order_charge_cents"] == 666  # 333 + 333, not 665


def test_catering_service_fee_and_total(api):
    """PRD §3.6: "The `service_fee_cents` is the order charge multiplied by a service-fee
    rate of 18 percent, rounded half up. The `total_charge_cents` is the order charge plus
    the service fee."

    Design: Difficulty/combinatorial_formula/catering_per_line_round_then_sum
    """
    site, venue, order, coord = _two_line_order(api, headcount=25)
    submitted = validate_success(api.submit_catering_order(order["id"], coord), 200)
    assert submitted["service_fee_cents"] == 120  # round_half_up(666 * 0.18) = 120
    assert submitted["total_charge_cents"] == 786


# ─── Difficulty: dual_variant_calc — estimate at submit vs final at fulfill ──
def test_catering_estimated_cost_is_overhead_scaled_recipe(api):
    """PRD §3.6: "The `estimated_cost_cents` is a forward-looking recipe projection: the sum
    over the lines of the menu item's `standard_recipe_cost_cents` times `qty`, multiplied by
    an event overhead factor of 1.20, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/catering_estimate_vs_final_cost
    """
    site, venue, order, coord = _two_line_order(api, headcount=25)
    submitted = validate_success(api.submit_catering_order(order["id"], coord), 200)
    assert submitted["estimated_cost_cents"] == 288  # (120 + 120) * 1.20


def test_catering_final_cost_is_fifo_actual_and_diverges_from_estimate(api):
    """PRD §3.6: "the `final_cost_cents` is computed by FIFO valuation of the consumed lots —
    identical arithmetic to a session close, and the value that replaces the earlier
    estimate."

    Design: Difficulty/dual_variant_calc/catering_estimate_vs_final_cost
    """
    site, venue, order, coord = _two_line_order(api, headcount=25)
    submitted = validate_success(api.submit_catering_order(order["id"], coord), 200)
    stock_site(site["id"], "KIT", 10, 450)
    from test_helpers import make_approver_headers
    validate_success(api.review_catering_order(order["id"], {"decision": "APPROVE"},
                                               make_approver_headers("appr-1")), 200)
    version = get_site_version(site["id"])
    validate_success(api.confirm_catering_order(
        order["id"], {"expected_client_site_version": version,
                      "reserved_ingredients": [{"ingredient": "KIT", "qty": 1}]}, FINANCE), 200)
    fulfilled = validate_success(api.fulfill_catering_order(
        order["id"], {"consumed_ingredients": [{"ingredient": "KIT", "qty": 1}]},
        TEST_USERS["cafeteria_manager_headers"]), 200)
    assert fulfilled["final_cost_cents"] == 450
    assert fulfilled["final_cost_cents"] != submitted["estimated_cost_cents"]


# ─── Difficulty: compensating_invariant — reserve then release conserves on-hand ──
def test_confirm_reserves_without_lowering_on_hand(api):
    """PRD §2.10: "confirming a catering order raises `qty_reserved` on lots in the same
    FIFO order without lowering `qty_on_hand`."

    Design: Difficulty/compensating_invariant/catering_reserve_release_conserves_on_hand
    """
    ctx = setup_catering_order(target="APPROVED", stock=("KIT", 10, 100))
    version = get_site_version(ctx["site"]["id"])
    validate_success(api.confirm_catering_order(
        ctx["order"]["id"], {"expected_client_site_version": version,
                             "reserved_ingredients": [{"ingredient": "KIT", "qty": 4}]}, FINANCE), 200)
    lot = get_lot(ctx["lot"]["id"])
    assert lot["qty_reserved"] == 4
    assert lot["qty_on_hand"] == 10


def test_cancel_confirmed_order_releases_reservation(api):
    """PRD §3.6: "When a `CONFIRMED` order is cancelled, its reservations are released (each
    lot's `qty_reserved` lowered by the amount this order held) and the site's `version` is
    incremented by 1."

    Design: Difficulty/compensating_invariant/catering_reserve_release_conserves_on_hand
    """
    ctx = setup_catering_order(target="APPROVED", stock=("KIT", 10, 100))
    version = get_site_version(ctx["site"]["id"])
    validate_success(api.confirm_catering_order(
        ctx["order"]["id"], {"expected_client_site_version": version,
                             "reserved_ingredients": [{"ingredient": "KIT", "qty": 4}]}, FINANCE), 200)
    validate_success(api.cancel_catering_order(ctx["order"]["id"], FINANCE), 200)
    lot = get_lot(ctx["lot"]["id"])
    assert lot["qty_reserved"] == 0
    assert lot["qty_on_hand"] == 10


# ─── Difficulty: priority_pair_validation_conflict — state beats fiscal ─────
def test_confirm_submitted_order_reports_invalid_state_over_inventory(api):
    """PRD §3.6: "Confirmation is performed by a `FinanceController` and advances the order
    from `APPROVED` to `CONFIRMED`."
    PRD §2.8: "the **first** failing check in this order determines the error returned; a
    later check never masks an earlier one" — State (5) precedes Fiscal sufficiency (10).

    Design: Difficulty/priority_pair_validation_conflict/confirm_invalid_state_beats_insufficient_inventory
    """
    ctx = setup_catering_order(target="SUBMITTED")  # never APPROVED; no inventory at site
    version = get_site_version(ctx["site"]["id"])
    res = api.confirm_catering_order(
        ctx["order"]["id"], {"expected_client_site_version": version,
                             "reserved_ingredients": [{"ingredient": "KIT", "qty": 999}]}, FINANCE)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_confirm_draft_order_reports_invalid_state_over_inventory(api):
    """PRD §3.6: "Confirmation is performed by a `FinanceController` and advances the order
    from `APPROVED` to `CONFIRMED`."
    PRD §2.8: "the **first** failing check in this order determines the error returned; a
    later check never masks an earlier one" — State (5) precedes Fiscal sufficiency (10).

    Design: Difficulty/priority_pair_validation_conflict/confirm_invalid_state_beats_insufficient_inventory
    """
    ctx = setup_catering_order(target="DRAFT")  # DRAFT, no inventory at site
    version = get_site_version(ctx["site"]["id"])
    res = api.confirm_catering_order(
        ctx["order"]["id"], {"expected_client_site_version": version,
                             "reserved_ingredients": [{"ingredient": "KIT", "qty": 999}]}, FINANCE)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ─── Difficulty: resource_temporal_overlap — half-open venue window ─────────
def test_overlapping_venue_windows_rejected(api):
    """PRD §3.6: "that the event window not overlap any other non-terminal order on the same
    venue over the half-open interval from `event_start` up to `event_end` (otherwise
    `ERR_VENUE_TIME_CONFLICT`)."

    Design: Difficulty/resource_temporal_overlap/catering_venue_halfopen_overlap
    """
    site = create_site()
    cycle = create_cycle(site["id"])
    wrap = add_item(cycle["id"], **WRAP)
    venue = create_venue(site["id"])
    coord = make_coordinator_headers("coord-1")
    lines = [{"menu_item_id": wrap["id"], "qty": 1}]

    order_a = validate_success(api.create_catering_order(create_catering_order_payload(
        site["id"], venue["id"], lines,
        event_start="2026-03-10T10:00:00Z", event_end="2026-03-10T11:00:00Z"), coord), 201)
    validate_success(api.submit_catering_order(order_a["id"], coord), 200)

    order_b = validate_success(api.create_catering_order(create_catering_order_payload(
        site["id"], venue["id"], lines,
        event_start="2026-03-10T10:30:00Z", event_end="2026-03-10T11:30:00Z"), coord), 201)
    res = api.submit_catering_order(order_b["id"], coord)
    validate_error(res, ApiErrorId.ERR_VENUE_TIME_CONFLICT.value, expected_status=409)


def test_touching_venue_windows_allowed(api):
    """PRD §3.6: "that the event window not overlap any other non-terminal order on the same
    venue over the half-open interval from `event_start` up to `event_end` (otherwise
    `ERR_VENUE_TIME_CONFLICT`)."

    Design: Difficulty/resource_temporal_overlap/catering_venue_halfopen_overlap
    """
    site = create_site()
    cycle = create_cycle(site["id"])
    wrap = add_item(cycle["id"], **WRAP)
    venue = create_venue(site["id"])
    coord = make_coordinator_headers("coord-1")
    lines = [{"menu_item_id": wrap["id"], "qty": 1}]

    order_a = validate_success(api.create_catering_order(create_catering_order_payload(
        site["id"], venue["id"], lines,
        event_start="2026-03-10T10:00:00Z", event_end="2026-03-10T11:00:00Z"), coord), 201)
    validate_success(api.submit_catering_order(order_a["id"], coord), 200)

    order_b = validate_success(api.create_catering_order(create_catering_order_payload(
        site["id"], venue["id"], lines,
        event_start="2026-03-10T11:00:00Z", event_end="2026-03-10T12:00:00Z"), coord), 201)
    submitted_b = validate_success(api.submit_catering_order(order_b["id"], coord), 200)
    assert submitted_b["status"] == "SUBMITTED"


# ─── Corner: validations — capacity & insufficient inventory ────────────────
def test_catering_headcount_exceeds_venue_capacity(api):
    """PRD §3.6: "that the `headcount` not exceed the venue's `capacity` (otherwise
    `ERR_VENUE_CAPACITY_EXCEEDED`)."

    Design: Corner/validations/catering_headcount_exceeds_venue_capacity
    """
    ctx = setup_catering_order(target="DRAFT", venue_overrides={"capacity": 100},
                               order_overrides={"headcount": 120})
    res = api.submit_catering_order(ctx["order"]["id"], make_coordinator_headers(ctx["coordinator_id"]))
    validate_error(res, ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED.value, expected_status=409)


def test_confirm_insufficient_inventory_rejected(api):
    """PRD §3.6: "that for each reserved line the available quantity — the sum over the
    site's `AVAILABLE` lots of that ingredient of `qty_on_hand` minus `qty_reserved` — be at
    least the requested `qty` (otherwise `ERR_INSUFFICIENT_INVENTORY`)."

    Design: Corner/validations/confirm_insufficient_inventory_isolated
    """
    ctx = setup_catering_order(target="APPROVED", stock=("KIT", 1, 100))
    version = get_site_version(ctx["site"]["id"])
    res = api.confirm_catering_order(
        ctx["order"]["id"], {"expected_client_site_version": version,
                             "reserved_ingredients": [{"ingredient": "KIT", "qty": 5}]}, FINANCE)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value, expected_status=409)
