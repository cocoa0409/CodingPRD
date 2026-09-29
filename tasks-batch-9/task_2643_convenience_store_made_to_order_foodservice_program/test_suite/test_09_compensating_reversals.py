"""Reversals that must land in the right column, not merely balance.

Voiding a committed order has to return reserved units to the case rather
than write them off, and refunding a settled order has to claw back points
without rewriting the member's history. Both are checked column by column.
"""

import test_helpers as H
from test_helpers import factories as F
from test_helpers import fixtures as X

CLOCK_BREAKFAST = "2026-08-01T08:00:00Z"
CLOCK_LUNCH = "2026-08-01T11:00:00Z"

SEED_POINTS = 495
SEED_REASON = "MIGRATION_OPENING_BALANCE"


def _placed_order_reserving_twelve_pretzels(api):
    """A committed order holding 12 of a 40-unit pan, plus a coffee ticket."""
    store, unit, pretzel, batch = X.setup_lunch_trade_with_par_baked_stock(api, CLOCK_LUNCH, 40)
    coffee = X.create_coffee(api)
    order = X.create_draft_order(api, store["id"])
    pretzel_line = X.add_order_line(api, order["id"], pretzel["id"], 12)
    X.add_order_line(api, order["id"], coffee["id"], 1)
    placed = X.place_order(api, order["id"])
    return store, batch, placed, pretzel_line


def _settled_order_for_a_member_five_points_below_plus(api):
    """A member seeded to 495 lifetime points, with one settled 899c order."""
    store = X.setup_store_open_for_lunch(api, CLOCK_LUNCH)
    hoagie = X.create_hoagie(api)
    account = X.create_loyalty_account(api, member_code="WAWA-M-495")
    seeded = X.seed_points(api, account["id"], SEED_POINTS, SEED_REASON)
    order = X.create_draft_order(api, store["id"], loyalty_account_id=account["id"])
    X.add_order_line(api, order["id"], hoagie["id"], 1)
    placed = X.place_order(api, order["id"])
    X.authorize_order(api, placed["id"], "CARD")
    settled = X.settle_order(api, placed["id"])
    return store, account, seeded, placed, settled


def test_void_returns_reserved_units_to_the_case_not_to_the_discard_column(api):
    """The released units come back as available stock.

    Placement moved 12 units across: "the line's `reserved_qty` is set to the
    line's `qty`, and on the batch the same quantity is subtracted from
    `remaining_qty` and added to `reserved_qty`". The void reverses exactly
    that column: "that reserved quantity is added back to the batch's
    `remaining_qty` and subtracted from the batch's `reserved_qty`, the line's
    `reserved_qty` is set to 0 ... the batch's status is unchanged, because the
    released units simply return to the case."

    Design: Difficulty/compensating_invariant/voiding_a_placed_order_restores_the_batch_quantity_ledger_exactly
    """
    store, batch, placed, pretzel_line = _placed_order_reserving_twelve_pretzels(api)
    assert placed["production_status"] == "PLACED"
    assert placed["subtotal_gross_cents"] == 2637
    mid = X.read_batch(api, batch["id"])
    assert mid["remaining_qty"] == 28
    assert mid["reserved_qty"] == 12

    voided = H.get_success_data(
        api.void_order(placed["id"], F.void_payload(), H.STORE_TERMINAL_HEADERS)
    )

    assert voided["production_status"] == "VOIDED"
    after = X.read_batch(api, batch["id"])
    assert after["baked_qty"] == 40
    assert after["remaining_qty"] == 40
    assert after["reserved_qty"] == 0
    assert after["sold_qty"] == 0
    assert after["discarded_qty"] == 0
    assert after["status"] == "HOLDING"
    H.assert_batch_quantity_ledger(after)
    assert X.read_order_line(api, pretzel_line["id"])["reserved_qty"] == 0


def test_void_books_no_waste_and_keeps_the_case_slot_occupied(api):
    """A release is not a write-off, so no waste is recorded anywhere.

    Nothing in the void reversal touches the waste ledger, and the pan keeps
    its slot because its status does not change - a slot is only freed when
    "Batches that have reached `SOLD_OUT` or `DISCARDED` free their slot
    immediately". Waste rows and the store's waste accumulator belong to the
    write-off paths instead - the events "writing off unreserved remaining
    units, appending waste records, accumulating the store's waste cost and
    freeing hot-case slots" - and a void is none of them.

    Design: Difficulty/compensating_invariant/voiding_a_placed_order_restores_the_batch_quantity_ledger_exactly
    """
    store, batch, placed, pretzel_line = _placed_order_reserving_twelve_pretzels(api)

    H.get_success_data(api.void_order(placed["id"], F.void_payload(), H.STORE_TERMINAL_HEADERS))

    after_store = X.read_store(api, store["id"])
    assert after_store["hot_case_slots_used"] == 1
    assert after_store["waste_cost_cents_mtd"] == 0

    rows, meta = H.validate_paginated(
        api.list_batch_waste_logs(batch["id"], H.STORE_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_void_cancels_every_open_kitchen_ticket_of_the_order(api):
    """The station queues are cleared by the same reversal.

    "Every kitchen ticket of the order whose `status` is `QUEUED` or
    `IN_PROGRESS` goes to `VOIDED` and leaves its station queue, with each
    ticket's `version` incrementing by one; tickets already `DONE` are left
    untouched." No ticket of this order was ever completed, so all of them end
    in the cancelled posture.

    Design: Difficulty/compensating_invariant/voiding_a_placed_order_restores_the_batch_quantity_ledger_exactly
    """
    store, batch, placed, pretzel_line = _placed_order_reserving_twelve_pretzels(api)
    before = X.list_order_tickets(api, placed["id"])
    assert before, "placement must cut at least one kitchen ticket"

    H.get_success_data(api.void_order(placed["id"], F.void_payload(), H.STORE_TERMINAL_HEADERS))

    after = X.list_order_tickets(api, placed["id"])
    assert len(after) == len(before)
    assert all(ticket["status"] == "VOIDED" for ticket in after)


def test_the_two_accruals_lift_the_member_across_the_plus_boundary(api):
    """Provisional then final accrual take 495 lifetime points to 506.

    The seed is an earning event - "A positive delta is treated as an earning
    event: it is added to `points_balance` and added to
    `lifetime_points_earned`" - leaving the member 5 points short, since "the
    tier is `ELITE` when lifetime earnings are at least 2000 points, `PLUS`
    when they are at least 500 but below 2000, and `BASIC` below 500". Commit
    accrues on the order total at the pre-order multiplier, 8 points, which
    itself lifts the tier; settlement then re-reads it, because its "tier
    multiplier is re-read from the member's `tier` **after** the provisional
    accrual has already lifted it", giving 11 and a delta of 3.

    Design: Difficulty/compensating_invariant/refund_reverses_final_points_while_lifetime_earned_and_tier_stay_put
    """
    store, account, seeded, placed, settled = _settled_order_for_a_member_five_points_below_plus(api)

    assert seeded["tier"] == "BASIC"
    assert seeded["points_balance"] == 495
    assert seeded["lifetime_points_earned"] == 495
    assert placed["total_cents"] == 899
    assert placed["points_provisional"] == 8
    assert settled["settlement_status"] == "SETTLED"
    assert settled["points_final"] == 11

    after_settlement = X.read_loyalty_account(api, account["id"])
    assert after_settlement["points_balance"] == 506
    assert after_settlement["lifetime_points_earned"] == 506
    assert after_settlement["tier"] == "PLUS"
    H.assert_loyalty_ledger(after_settlement)


def test_refund_claws_back_final_points_but_never_rewrites_history(api):
    """The balance falls by 11 while lifetime earnings and tier hold still.

    "the account's `points_balance` is reduced by `points_final` and its
    `points_reversed_total` is increased by `points_final` ...
    `lifetime_points_earned` and the derived `tier` deliberately stay exactly
    where settlement left them, because lifetime earnings are historical."
    Demotion is impossible by construction: "Because only
    `lifetime_points_earned` feeds the derivation, reversals and redemptions
    never demote a member." The reversal is asymmetric on purpose - it claws
    back the final figure, not the provisional one.

    Design: Difficulty/compensating_invariant/refund_reverses_final_points_while_lifetime_earned_and_tier_stay_put
    """
    store, account, seeded, placed, settled = _settled_order_for_a_member_five_points_below_plus(api)
    production_before = X.read_order(api, placed["id"])["production_status"]

    refunded = H.get_success_data(
        api.refund_order(placed["id"], F.refund_payload(), H.STORE_MANAGER_HEADERS)
    )

    assert refunded["settlement_status"] == "REFUNDED"
    assert refunded["points_provisional"] == 8
    assert refunded["points_final"] == 11
    assert refunded["production_status"] == production_before

    after = X.read_loyalty_account(api, account["id"])
    assert after["points_balance"] == 495
    assert after["points_reversed_total"] == 11
    assert after["lifetime_points_earned"] == 506
    assert after["lifetime_points_redeemed"] == 0
    assert after["tier"] == "PLUS"
    H.assert_loyalty_ledger(after)
