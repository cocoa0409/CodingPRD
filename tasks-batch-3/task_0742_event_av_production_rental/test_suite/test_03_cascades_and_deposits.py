"""Transitive cascades and the deposit ledger: order-cancel release chains,
damage-check-in auto-filing, deposit HOLD/RELEASE conservation, HOLD-vs-settlement
divergence, and the HOLD ledger entry."""
from test_helpers import (
    validate_success,
    setup_confirmed_order_single_led, setup_in_event_order_single_led,
    setup_confirmed_order_led_and_array, add_sub_rental,
    assert_deposit_conservation_cancelled, assert_deposit_conservation_settled,
)


# ─── transitive_cascade / order_cancel_release_subrental_recompute_depth3 ──
def _confirmed_order_with_linked_subrental(api, warehouse_manager_headers):
    ctx = setup_confirmed_order_single_led(qty=1)  # deposit HOLD = round(0.2*500000) = 100000
    sr = add_sub_rental(ctx["ord_id"], ctx["led_id"], reservation_id=ctx["res_id"],
                        direction="SUB_IN", qty=1, cost_cents=20000)
    validate_success(api.confirm_sub_rental(sr["id"], warehouse_manager_headers), 200)
    ctx["sub_rental"] = sr
    return ctx


def test_cancel_confirmed_order_releases_reservation_and_cancels_linked_subrental(
        api, account_manager_headers, warehouse_manager_headers):
    """PRD §3.9: "The cascade runs in full: every non-terminal reservation is moved to
    `RELEASED`; each released reservation's linked `CONFIRMED` sub-rental is moved to
    `CANCELLED`, and each such cancellation removes that sub-rental's `cost_cents` from
    the order's `sub_rental_cost_cents`; and every `SCHEDULED` crew assignment is moved
    to `CANCELLED`."

    Design: Difficulty/transitive_cascade/order_cancel_release_subrental_recompute_depth3
    """
    ctx = _confirmed_order_with_linked_subrental(api, warehouse_manager_headers)

    cancelled = validate_success(api.cancel_order(ctx["ord_id"], account_manager_headers), 200)
    assert cancelled["status"] == "CANCELLED"
    reservation = validate_success(
        api.get_reservation(ctx["res_id"], warehouse_manager_headers), 200)
    assert reservation["status"] == "RELEASED"
    sub_rental = validate_success(
        api.get_sub_rental(ctx["sub_rental"]["id"], warehouse_manager_headers), 200)
    assert sub_rental["status"] == "CANCELLED"


def test_cancel_recomputes_subrental_cost_and_reverses_deposit_hold(
        api, account_manager_headers, warehouse_manager_headers):
    """PRD §3.9: "each such cancellation removes that sub-rental's `cost_cents` from the
    order's `sub_rental_cost_cents`; and every `SCHEDULED` crew assignment is moved to
    `CANCELLED`."
    PRD §3.9: "a deposit ledger entry of type `RELEASE` is written for the current
    `deposit_outstanding_cents`, the order's `deposit_released_cents` is recomputed as
    the sum of all `RELEASE` amounts, and `deposit_outstanding_cents` is driven to zero."

    Design: Difficulty/transitive_cascade/order_cancel_release_subrental_recompute_depth3
    """
    ctx = _confirmed_order_with_linked_subrental(api, warehouse_manager_headers)

    cancelled = validate_success(api.cancel_order(ctx["ord_id"], account_manager_headers), 200)
    assert cancelled["sub_rental_cost_cents"] == 0, cancelled["sub_rental_cost_cents"]
    assert cancelled["deposit_released_cents"] == 100000, cancelled["deposit_released_cents"]
    assert cancelled["deposit_outstanding_cents"] == 0, cancelled["deposit_outstanding_cents"]


# ─── transitive_cascade / reservation_damage_checkin_files_report_recompute_depth3 ──
# Note: the PRD defines deposit_at_risk_cents as the summed assessed_cost_cents of open
# reports (§3.8); the auto-filed report is FILED with assessed_cost_cents = 0, so only
# the PRD-derivable effects (DAMAGED status, open_damage_count, auto-created report) are
# asserted here.
def test_damaged_checkin_marks_reservation_and_increments_open_damage_count(
        api, account_manager_headers, warehouse_manager_headers):
    """PRD §3.8: "When `damaged` is true, the reservation moves from `CHECKED_OUT` to
    `DAMAGED`: the reservation's `lost_units` is set from the body's `lost_units` value,
    a damage report is automatically opened in `FILED` status against that reservation
    carrying the same lost-unit count, and the order's `open_damage_count` is
    incremented and its `deposit_at_risk_cents` recomputed."

    Design: Difficulty/transitive_cascade/reservation_damage_checkin_files_report_recompute_depth3
    """
    ctx = setup_in_event_order_single_led(qty=2)

    reservation = validate_success(api.check_in_reservation(
        ctx["res_id"], {"damaged": True, "lost_units": 1}, warehouse_manager_headers), 200)
    assert reservation["status"] == "DAMAGED"
    order = validate_success(api.get_order(ctx["ord_id"], account_manager_headers), 200)
    assert order["open_damage_count"] == 1, order["open_damage_count"]


def test_damaged_checkin_auto_files_damage_report(api, warehouse_manager_headers):
    """PRD §3.8: "a damage report is automatically opened in `FILED` status against that
    reservation carrying the same lost-unit count, and the order's `open_damage_count` is
    incremented and its `deposit_at_risk_cents` recomputed."

    Design: Difficulty/transitive_cascade/reservation_damage_checkin_files_report_recompute_depth3
    """
    ctx = setup_in_event_order_single_led(qty=2)

    validate_success(api.check_in_reservation(
        ctx["res_id"], {"damaged": True, "lost_units": 1}, warehouse_manager_headers), 200)
    listed = api.list_damage_reports(warehouse_manager_headers, params={"order_id": ctx["ord_id"]})
    reports = listed.json()["data"]
    auto = [r for r in reports if r["reservation_id"] == ctx["res_id"]]
    assert len(auto) == 1, f"expected exactly one auto-filed report, got {reports}"
    assert auto[0]["status"] == "FILED"
    assert auto[0]["lost_units"] == 1, auto[0]["lost_units"]


# ─── compensating_invariant / deposit_hold_release_conserved ──────────
def test_confirm_holds_deposit_then_cancel_releases_full_amount(api, account_manager_headers):
    """PRD §3.7: "A single deposit ledger entry of type `HOLD` is written for that
    amount, and the order's `deposit_held_cents` (the sum of all `HOLD` amounts) and
    `deposit_outstanding_cents` are recomputed accordingly."
    PRD §3.9: "the order's `deposit_released_cents` is recomputed as the sum of all
    `RELEASE` amounts, and `deposit_outstanding_cents` is driven to zero."

    Design: Difficulty/compensating_invariant/deposit_hold_release_conserved
    """
    ctx = setup_confirmed_order_led_and_array()
    assert ctx["order"]["deposit_held_cents"] == 360000, ctx["order"]["deposit_held_cents"]

    cancelled = validate_success(api.cancel_order(ctx["ord_id"], account_manager_headers), 200)
    assert cancelled["deposit_held_cents"] == 360000
    assert cancelled["deposit_released_cents"] == 360000, cancelled["deposit_released_cents"]


def test_deposit_outstanding_zero_after_release(api, account_manager_headers):
    """PRD §3.9: "For a confirmed order that is later cancelled instead of settled, the
    released amount equals the entire held amount and nothing remains outstanding."

    Design: Difficulty/compensating_invariant/deposit_hold_release_conserved
    """
    ctx = setup_confirmed_order_led_and_array()

    cancelled = validate_success(api.cancel_order(ctx["ord_id"], account_manager_headers), 200)
    assert cancelled["deposit_outstanding_cents"] == 0, cancelled["deposit_outstanding_cents"]
    assert_deposit_conservation_cancelled(cancelled)


# ─── dual_variant_calc / deposit_hold_vs_settlement_diverges ──────────
def test_deposit_hold_is_flat_rate_of_replacement_value(api):
    """PRD §3.7: "The `deposit_required_cents` is a flat deposit rate of 20% applied to
    the summed replacement exposure of the order — that is, for every reservation that is
    not `RELEASED`, the equipment item's `replacement_value_cents` multiplied by that
    reservation's `qty`, summed across those reservations and then multiplied by 0.20 and
    rounded half up."

    Design: Difficulty/dual_variant_calc/deposit_hold_vs_settlement_diverges
    """
    ctx = setup_confirmed_order_led_and_array()
    # 0.20 * (500000*2 + 800000*1) = 0.20 * 1,800,000 = 360000.
    assert ctx["order"]["deposit_held_cents"] == 360000, ctx["order"]["deposit_held_cents"]


def test_settlement_captures_actual_damage_and_refunds_remainder(
        api, account_manager_headers, warehouse_manager_headers):
    """PRD §3.9: "Settlement then refunds whatever deposit remains: a deposit ledger
    entry of type `REFUND` is written for the amount `deposit_held_cents` less
    `deposit_captured_cents`, and the order's `deposit_refunded_cents` and
    `deposit_outstanding_cents` are recomputed."

    Design: Difficulty/dual_variant_calc/deposit_hold_vs_settlement_diverges
    """
    ctx = setup_confirmed_order_led_and_array()
    validate_success(api.load_out_order(ctx["ord_id"], warehouse_manager_headers), 200)
    validate_success(api.check_out_reservation(ctx["res_led_id"], warehouse_manager_headers), 200)
    validate_success(api.check_out_reservation(ctx["res_arr_id"], warehouse_manager_headers), 200)
    validate_success(api.start_event_order(ctx["ord_id"], account_manager_headers), 200)

    dr1 = validate_success(api.create_damage_report(
        ctx["ord_id"], {"reservation_id": ctx["res_led_id"], "damaged_units": 1},
        warehouse_manager_headers), 201)
    dr2 = validate_success(api.create_damage_report(
        ctx["ord_id"], {"reservation_id": ctx["res_arr_id"], "damaged_units": 1},
        warehouse_manager_headers), 201)
    validate_success(api.assess_damage_report(dr1["id"], {"assessed_cost_cents": 100000},
                                              warehouse_manager_headers), 200)
    validate_success(api.assess_damage_report(dr2["id"], {"assessed_cost_cents": 80000},
                                              warehouse_manager_headers), 200)
    validate_success(api.charge_damage_report(dr1["id"], account_manager_headers), 200)
    validate_success(api.charge_damage_report(dr2["id"], account_manager_headers), 200)
    validate_success(api.check_in_reservation(ctx["res_led_id"], {"damaged": False},
                                              warehouse_manager_headers), 200)
    validate_success(api.check_in_reservation(ctx["res_arr_id"], {"damaged": False},
                                              warehouse_manager_headers), 200)
    validate_success(api.load_in_order(ctx["ord_id"], warehouse_manager_headers), 200)

    settled = validate_success(api.settle_order(ctx["ord_id"], account_manager_headers), 200)
    # HOLD 360000; captured 100000 + 80000 = 180000; refund 360000 - 180000 = 180000.
    assert settled["deposit_captured_cents"] == 180000, settled["deposit_captured_cents"]
    assert settled["deposit_refunded_cents"] == 180000, settled["deposit_refunded_cents"]
    assert settled["deposit_held_cents"] != settled["deposit_captured_cents"]
    assert_deposit_conservation_settled(settled)


# ─── entities / deposit_hold_ledger_entry_created_on_confirm ──────────
def test_confirm_creates_hold_deposit_ledger_entry(api, account_manager_headers):
    """PRD §3.7: "A single deposit ledger entry of type `HOLD` is written for that
    amount, and the order's `deposit_held_cents` (the sum of all `HOLD` amounts) and
    `deposit_outstanding_cents` are recomputed accordingly."

    Design: Corner/entities/deposit_hold_ledger_entry_created_on_confirm
    """
    ctx = setup_confirmed_order_single_led(qty=1)  # HOLD = round(0.2*500000) = 100000
    assert ctx["order"]["deposit_held_cents"] == 100000, ctx["order"]["deposit_held_cents"]

    listed = api.list_deposit_ledger(account_manager_headers, params={"order_id": ctx["ord_id"]})
    entries = [e for e in listed.json()["data"] if e["order_id"] == ctx["ord_id"]]
    holds = [e for e in entries if e["entry_type"] == "HOLD"]
    assert len(holds) == 1, f"expected exactly one HOLD entry, got {entries}"
    assert holds[0]["amount_cents"] == 100000, holds[0]["amount_cents"]
