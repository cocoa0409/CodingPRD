"""Depth-3 cascades, conserved-quantity invariants, and the state-before-fiscal
validation precedence.

Covers Difficulty queue: transitive_cascade, compensating_invariant,
priority_pair_validation_conflict (state vs fiscal).
"""

from test_helpers import (
    validate_success,
    validate_error,
    create_rate_card_payload,
    create_lane_payload,
    create_customer_payload,
    create_reservation_payload,
    create_rental_item_payload,
    create_rental_line_payload,
    assert_deposit_ledger_conserved,
    assert_rental_inventory_conserved,
    setup_held_and_waitlisted_on_same_lane,
    set_clock,
    CM, FD,
)


# =============================================================================
# Difficulty / transitive_cascade
# =============================================================================
def test_cancel_promotes_waitlist_and_debits_deposit_depth3(api):
    """PRD §3.7: "When a cancellation or an expiry frees a contended window, the
    system looks for the earliest waitlisted reservation — ordered by `created_at`
    ascending — among the candidates on that same resource and window whose freed
    window now has no temporal-overlap conflict, and promotes it from
    `WAITLISTED` to `HELD`."
    PRD §3.7: "Promotion prices the booking exactly as a hold would: it recomputes
    the quoted total and the held deposit, captures that deposit by adding it to
    the customer's `deposit_balance_cents`, moves the reservation to `HELD`, and
    increments its `version`."

    Design: Difficulty/transitive_cascade/cancel_releases_window_promotes_waitlist_debits_deposit_depth3
    """
    ctx = setup_held_and_waitlisted_on_same_lane(
        "2026-08-01T18:00:00.000Z", "2026-08-01T19:00:00.000Z",
        rate_card_overrides={"per_game_cents": 1000, "per_hour_cents": 0, "deposit_pct_bps": 2000})
    # R2 quoted = 1000*3*2 = 6000; deposit 20% = 1200
    validate_success(api.cancel_reservation(ctx["held"]["id"], FD), 200)

    r2 = validate_success(api.get_reservation(ctx["waitlisted"]["id"], FD), 200)
    assert r2["status"] == "HELD"
    assert r2["held_deposit_cents"] == 1200

    c2 = validate_success(api.get_customer(ctx["c2"]["id"], FD), 200)
    assert c2["deposit_balance_cents"] == 1200


def test_suspend_expires_holds_returns_rentals_depth3(api):
    """PRD §3.2: "Every reservation of that customer currently in `HELD` status is
    driven to `EXPIRED`. Each such expiry releases that reservation's held deposit
    (debiting `deposit_balance_cents` and crediting the released amount to
    `wallet_credit_cents`) and returns every open rental line on that reservation,
    restoring the rented units to their items' `available_count`."

    Design: Difficulty/transitive_cascade/suspend_customer_expires_holds_returns_rentals_depth3
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Susp", per_game_cents=1000, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    ri = validate_success(api.create_rental_item(create_rental_item_payload(
        kind="SHOES", label="Mens 10", unit_price_cents=300, total_count=4), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-02T18:00:00.000Z", end_at="2026-08-02T19:00:00.000Z",
        bowler_count=2, game_count=2), FD), 201)
    validate_success(api.hold_reservation(res["id"], FD), 200)
    validate_success(api.create_rental_line(
        create_rental_line_payload(res["id"], ri["id"], 2), FD), 201)

    validate_success(api.suspend_customer(cust["id"], CM), 200)

    r_after = validate_success(api.get_reservation(res["id"], FD), 200)
    assert r_after["status"] == "EXPIRED"
    ri_after = validate_success(api.get_rental_item(ri["id"], FD), 200)
    assert ri_after["available_count"] == 4
    assert_rental_inventory_conserved(ri_after)
    cust_after = validate_success(api.get_customer(cust["id"], FD), 200)
    assert cust_after["deposit_balance_cents"] == 0


# =============================================================================
# Difficulty / compensating_invariant
# =============================================================================
def test_deposit_ledger_conserved_on_full_refund_cancel(api):
    """PRD §3.6: "On cancellation the held deposit leaves the customer's
    `deposit_balance_cents` and the computed `refund_cents` is added to their
    `wallet_credit_cents`".
    PRD §3.2: "The deposit balance is not a free-floating number; at all times it
    equals the sum of `held_deposit_cents` across that customer's reservations in
    the `HELD`, `CONFIRMED`, and `CHECKED_IN` states."

    Design: Difficulty/compensating_invariant/deposit_ledger_conserved_on_cancel_full_refund
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="I1", per_game_cents=800, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    set_clock("2026-08-15T10:00:00.000Z")
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-20T18:00:00.000Z", end_at="2026-08-20T19:00:00.000Z",
        bowler_count=4, game_count=3), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    assert held["held_deposit_cents"] == 1920
    after_hold = validate_success(api.get_customer(cust["id"], FD), 200)
    assert after_hold["deposit_balance_cents"] == 1920

    # >=24h notice from 2026-08-15 to 2026-08-20 -> full refund
    validate_success(api.cancel_reservation(res["id"], FD), 200)
    after = validate_success(api.get_customer(cust["id"], FD), 200)
    assert after["deposit_balance_cents"] == 0
    assert after["wallet_credit_cents"] == 1920
    assert_deposit_ledger_conserved(after, original_deposit_cents=1920)


def test_rental_inventory_conserved_on_take_then_return(api):
    """PRD §3.1: "Across the whole system the rental inventory is conserved: for
    any rental item, `total_count` always equals `available_count` plus
    `out_on_rent_count`".
    PRD §3.4: "Returning a line moves its `status` from `OPEN` to `RETURNED`,
    lowers the item's `out_on_rent_count` by the line's quantity and restores its
    `available_count`".

    Design: Difficulty/compensating_invariant/rental_inventory_conserved_on_take_then_return
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="I2", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    ri = validate_success(api.create_rental_item(create_rental_item_payload(
        kind="BALL", label="12lb", unit_price_cents=400, total_count=5), CM), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-16T18:00:00.000Z", end_at="2026-08-16T19:00:00.000Z",
        bowler_count=3, game_count=1), FD), 201)
    validate_success(api.hold_reservation(res["id"], FD), 200)
    rl = validate_success(api.create_rental_line(
        create_rental_line_payload(res["id"], ri["id"], 3), FD), 201)

    mid = validate_success(api.get_rental_item(ri["id"], FD), 200)
    assert mid["available_count"] == 2
    assert mid["out_on_rent_count"] == 3
    assert_rental_inventory_conserved(mid)

    validate_success(api.return_rental_line(rl["id"], FD), 200)
    after = validate_success(api.get_rental_item(ri["id"], FD), 200)
    assert after["available_count"] == 5
    assert after["out_on_rent_count"] == 0
    assert_rental_inventory_conserved(after)


# =============================================================================
# Difficulty / priority_pair_validation_conflict (state beats fiscal)
# =============================================================================
def test_re_hold_expired_suspended_reservation_state_beats_fiscal(api):
    """PRD §2.6: "State preconditions are evaluated after these structural checks,
    which is why a cancel on an already checked-in reservation surfaces the state
    rejection rather than a fiscal one. Cross-entity dependency checks,
    temporal-conflict and capacity checks, and fiscal checks follow in turn".

    A re-hold of a reservation that suspension drove to EXPIRED trips both the
    state precondition (EXPIRED is not DRAFT) and the suspended-customer fiscal
    check; PRD orders state ahead of fiscal, so ERR_INVALID_STATE is returned.

    Design: Difficulty/priority_pair_validation_conflict/cancel_checked_in_state_beats_fiscal_refund
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="P1", per_game_cents=1000, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-03T18:00:00.000Z", end_at="2026-08-03T19:00:00.000Z",
        bowler_count=2, game_count=2), FD), 201)
    validate_success(api.hold_reservation(res["id"], FD), 200)
    validate_success(api.suspend_customer(cust["id"], CM), 200)

    expired = validate_success(api.get_reservation(res["id"], FD), 200)
    assert expired["status"] == "EXPIRED"

    resp = api.hold_reservation(res["id"], FD)
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


# =============================================================================
# Difficulty — second tests (distinct PRD-derivable facet per instance)
# =============================================================================
def test_cancel_releases_blocking_reservation_deposit_to_wallet(api):
    """PRD §3.6: "On cancellation the held deposit leaves the customer's
    `deposit_balance_cents` and the computed `refund_cents` is added to their
    `wallet_credit_cents` ... The reservation moves to `CANCELLED`".

    The first hop of the cascade — the freeing cancellation itself — releases R1's
    deposit from C1's balance into wallet credit.

    Design: Difficulty/transitive_cascade/cancel_releases_window_promotes_waitlist_debits_deposit_depth3
    """
    ctx = setup_held_and_waitlisted_on_same_lane(
        "2026-08-01T18:00:00.000Z", "2026-08-01T19:00:00.000Z",
        rate_card_overrides={"per_game_cents": 1000, "per_hour_cents": 0, "deposit_pct_bps": 2000})
    # R1 quoted = 1000*3*2 = 6000; deposit 1200
    before = validate_success(api.get_customer(ctx["c1"]["id"], FD), 200)
    assert before["deposit_balance_cents"] == 1200

    cancelled = validate_success(api.cancel_reservation(ctx["held"]["id"], FD), 200)
    assert cancelled["status"] == "CANCELLED"

    c1_after = validate_success(api.get_customer(ctx["c1"]["id"], FD), 200)
    assert c1_after["deposit_balance_cents"] == 0


def test_suspend_full_deposit_waived_to_wallet(api):
    """PRD §3.6: "There are two paths into `EXPIRED`, and both treat the deposit
    identically: the entire held deposit is waived back to the customer rather than
    forfeited — `refund_cents` is set to the full `held_deposit_cents`, that amount
    is debited from `deposit_balance_cents` and credited to `wallet_credit_cents`".
    PRD §3.2: "A `CenterManager` may suspend a customer, moving `status` from
    `ACTIVE` to `SUSPENDED`".

    Design: Difficulty/transitive_cascade/suspend_customer_expires_holds_returns_rentals_depth3
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Susp2", per_game_cents=1000, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-02T18:00:00.000Z", end_at="2026-08-02T19:00:00.000Z",
        bowler_count=2, game_count=2), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    deposit = held["held_deposit_cents"]  # 1000*2*2 *20% = 800

    suspended = validate_success(api.suspend_customer(cust["id"], CM), 200)
    assert suspended["status"] == "SUSPENDED"
    after = validate_success(api.get_customer(cust["id"], FD), 200)
    assert after["wallet_credit_cents"] == deposit


def test_deposit_ledger_conserved_on_partial_refund_cancel(api):
    """PRD §3.6: "On cancellation the held deposit leaves the customer's
    `deposit_balance_cents` and the computed `refund_cents` is added to their
    `wallet_credit_cents`".
    PRD §3.6: "when the notice is at least 120 minutes (2 hours), the refund is
    half the held deposit".

    Even on a partial-refund cancel, the released deposit is fully accounted for:
    the forfeited portion leaves the balance and the refunded portion lands in the
    wallet, so balance + wallet still totals the original held deposit.

    Design: Difficulty/compensating_invariant/deposit_ledger_conserved_on_cancel_full_refund
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="I1b", per_game_cents=800, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-20T18:00:00.000Z", end_at="2026-08-20T19:00:00.000Z",
        bowler_count=4, game_count=3), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    assert held["held_deposit_cents"] == 1920
    # 200 minutes notice -> 50% tier -> refund 960
    set_clock("2026-08-20T14:40:00.000Z")
    cancelled = validate_success(api.cancel_reservation(res["id"], FD), 200)
    assert cancelled["refund_cents"] == 960
    after = validate_success(api.get_customer(cust["id"], FD), 200)
    assert after["deposit_balance_cents"] == 0
    assert after["wallet_credit_cents"] == 960


def test_rental_inventory_conserved_across_two_open_lines(api):
    """PRD §3.1: "Across the whole system the rental inventory is conserved: for
    any rental item, `total_count` always equals `available_count` plus
    `out_on_rent_count`, where `out_on_rent_count` is the sum of the `quantity` of
    every open rental line referencing that item across all reservations."

    Design: Difficulty/compensating_invariant/rental_inventory_conserved_on_take_then_return
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="I2b", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    ri = validate_success(api.create_rental_item(create_rental_item_payload(
        kind="BALL", label="12lb", unit_price_cents=400, total_count=5), CM), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-16T18:00:00.000Z", end_at="2026-08-16T19:00:00.000Z",
        bowler_count=3, game_count=1), FD), 201)
    validate_success(api.hold_reservation(res["id"], FD), 200)
    validate_success(api.create_rental_line(
        create_rental_line_payload(res["id"], ri["id"], 2), FD), 201)
    validate_success(api.create_rental_line(
        create_rental_line_payload(res["id"], ri["id"], 1), FD), 201)
    item = validate_success(api.get_rental_item(ri["id"], FD), 200)
    # out_on_rent_count = 2 + 1 across two OPEN lines
    assert item["out_on_rent_count"] == 3
    assert item["available_count"] == 2
    assert_rental_inventory_conserved(item)


def test_confirm_on_expired_suspended_reservation_state_beats_fiscal(api):
    """PRD §2.6: "State preconditions are evaluated after these structural checks
    ... Cross-entity dependency checks, temporal-conflict and capacity checks, and
    fiscal checks follow in turn".

    A confirm (not just a hold) on the EXPIRED reservation also surfaces the state
    rejection rather than any fiscal one, since confirming requires a HELD source
    state and EXPIRED is terminal.

    Design: Difficulty/priority_pair_validation_conflict/cancel_checked_in_state_beats_fiscal_refund
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="P1b", per_game_cents=1000, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-03T18:00:00.000Z", end_at="2026-08-03T19:00:00.000Z",
        bowler_count=2, game_count=2), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    validate_success(api.suspend_customer(cust["id"], CM), 200)
    expired = validate_success(api.get_reservation(res["id"], FD), 200)
    assert expired["status"] == "EXPIRED"

    resp = api.confirm_reservation(
        res["id"], {"expected_reservation_version": held["version"]}, FD)
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
