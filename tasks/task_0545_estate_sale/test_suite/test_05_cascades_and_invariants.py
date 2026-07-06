"""Cascading side effects (cancel, close) and conserved-quantity invariants (money, crew time)."""
from test_helpers import (
    validate_success,
    MANAGER, APPRAISER, CASHIER,
    listed_fixed_lot, listed_bid_lot, crew_booked_event, new_bid,
)


# ---- Difficulty: transitive_cascade / project_cancel_withdraws_lot_voids_bids ---------------
def _bid_lot_with_two_placed_bids(api):
    ctx = listed_bid_lot(api, bid_mode="FIRST_PRICE", reserve_price_cents=10000,
                         min_increment_cents=1000, list_price_cents=20000)
    new_bid(ctx["lot_id"], 12000, "b1", api)
    new_bid(ctx["lot_id"], 15000, "b2", api)
    return ctx


def test_cancel_withdraws_lot(api):
    """PRD §3.9: "A `SaleManager` may cancel a project from any non-terminal state, driving it
    to `CANCELLED`". "First, every non-terminal `Lot` of the project is moved to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/project_cancel_withdraws_lot_voids_bids
    """
    ctx = _bid_lot_with_two_placed_bids(api)
    cancelled = validate_success(api.cancel_project(ctx["project_id"], MANAGER))
    assert cancelled["status"] == "CANCELLED"
    lot = validate_success(api.get_lot(ctx["lot_id"], APPRAISER))
    assert lot["status"] == "WITHDRAWN"


def test_cancel_voids_placed_bids_on_withdrawn_lot(api):
    """PRD §3.9: "Second, for each lot just withdrawn, its `PLACED` bids are moved to `VOIDED`."

    Design: Difficulty/transitive_cascade/project_cancel_withdraws_lot_voids_bids
    """
    ctx = _bid_lot_with_two_placed_bids(api)
    validate_success(api.cancel_project(ctx["project_id"], MANAGER))
    resp = api.list_lot_bids(ctx["lot_id"], APPRAISER)
    body = resp.json()
    bid_list = body["data"]
    assert len(bid_list) == 2
    assert all(b["status"] == "VOIDED" for b in bid_list), [b["status"] for b in bid_list]


# ---- Difficulty: transitive_cascade / sale_close_marks_unsold_and_releases_crew -------------
def _open_sale_with_unsold_lot(api):
    return listed_fixed_lot(api, list_price_cents=5000, reserve_price_cents=100,
                            sale_start="2026-06-01T09:00:00Z", sale_end="2026-06-01T17:00:00Z")


def test_close_marks_listed_lot_unsold(api):
    """PRD §3.6: "Closing cascades: every lot of that project still `LISTED` at close is moved
    to `UNSOLD`, the project's `unsold_lot_count` is recomputed as the count of the project's
    lots in `UNSOLD`, and the closed event's `window_minutes` is released from the crew's
    `booked_minutes`."

    Design: Difficulty/transitive_cascade/sale_close_marks_unsold_and_releases_crew
    """
    ctx = _open_sale_with_unsold_lot(api)
    closed = validate_success(api.close_sale_event(ctx["sale_event_id"], MANAGER))
    assert closed["status"] == "CLOSED"
    lot = validate_success(api.get_lot(ctx["lot_id"], APPRAISER))
    assert lot["status"] == "UNSOLD"
    project = validate_success(api.get_project(ctx["project_id"], MANAGER))
    assert project["unsold_lot_count"] == 1


def test_close_releases_crew_minutes(api):
    """PRD §3.6: "the closed event's `window_minutes` is released from the crew's
    `booked_minutes`."

    Design: Difficulty/transitive_cascade/sale_close_marks_unsold_and_releases_crew
    """
    ctx = _open_sale_with_unsold_lot(api)
    validate_success(api.close_sale_event(ctx["sale_event_id"], MANAGER))
    crew = validate_success(api.get_crew(ctx["crew_id"], MANAGER))
    assert crew["booked_minutes"] == 0


# ---- Difficulty: compensating_invariant / gross_sales_conserved_across_sale_and_void --------
def _recorded_cash_sale(api):
    ctx = listed_fixed_lot(api, list_price_cents=7500, reserve_price_cents=100,
                           sale_start="2026-06-01T00:00:00Z", sale_end="2026-06-02T00:00:00Z")
    txn = validate_success(
        api.create_transaction(
            {"sale_event_id": ctx["sale_event_id"], "lot_id": ctx["lot_id"], "payment_method": "CASH"},
            CASHIER,
        ),
        201,
    )
    return ctx, txn


def test_void_restores_gross_sales_to_zero(api):
    """PRD §3.6: "At any point, `gross_sales_cents` is defined as the sum of `final_price_cents`
    over all of the project's transactions in `RECORDED` status — both consignment sales and
    buyout resales — so recording a sale and voiding one both simply re-derive that sum."

    Design: Difficulty/compensating_invariant/gross_sales_conserved_across_sale_and_void
    """
    ctx, txn = _recorded_cash_sale(api)
    project = validate_success(api.get_project(ctx["project_id"], MANAGER))
    assert project["gross_sales_cents"] == 7500
    voided = validate_success(api.void_transaction(txn["id"], MANAGER))
    assert voided["status"] == "VOIDED"
    project_after = validate_success(api.get_project(ctx["project_id"], MANAGER))
    assert project_after["gross_sales_cents"] == 0


def test_void_returns_lot_to_listed(api):
    """PRD §3.6: "It transitions the transaction `RECORDED → VOIDED`, returns the sold lot to
    the state it can sell from again — `LISTED` for a fixed-price lot or `BID_CLOSED` for a bid
    lot — clears the lot's `final_price_cents`".

    Design: Difficulty/compensating_invariant/gross_sales_conserved_across_sale_and_void
    """
    ctx, txn = _recorded_cash_sale(api)
    validate_success(api.void_transaction(txn["id"], MANAGER))
    lot = validate_success(api.get_lot(ctx["lot_id"], APPRAISER))
    assert lot["status"] == "LISTED"


# ---- Difficulty: compensating_invariant / crew_minutes_conserved_across_booking_and_cancel --
def test_cancel_releases_crew_minutes_to_zero(api):
    """PRD §3.9: "Third, every `SCHEDULED` or `OPEN` `SaleEvent` of the project is moved to
    `CANCELLED`, and each cancelled event's `window_minutes` is released from its crew's
    `booked_minutes`."

    Design: Difficulty/compensating_invariant/crew_minutes_conserved_across_booking_and_cancel
    """
    ctx = crew_booked_event(api, start_at="2026-06-01T09:00:00Z", end_at="2026-06-01T17:00:00Z")
    crew_before = validate_success(api.get_crew(ctx["crew_id"], MANAGER))
    assert crew_before["booked_minutes"] == 480
    validate_success(api.cancel_project(ctx["project_id"], MANAGER))
    crew_after = validate_success(api.get_crew(ctx["crew_id"], MANAGER))
    assert crew_after["booked_minutes"] == 0


def test_cancel_transitions_sale_event_to_cancelled(api):
    """PRD §3.9: "Third, every `SCHEDULED` or `OPEN` `SaleEvent` of the project is moved to
    `CANCELLED`, and each cancelled event's `window_minutes` is released from its crew's
    `booked_minutes`."

    Design: Difficulty/compensating_invariant/crew_minutes_conserved_across_booking_and_cancel
    """
    ctx = crew_booked_event(api, start_at="2026-06-01T09:00:00Z", end_at="2026-06-01T17:00:00Z")
    validate_success(api.cancel_project(ctx["project_id"], MANAGER))
    event = validate_success(api.get_sale_event(ctx["sale_event_id"], MANAGER))
    assert event["status"] == "CANCELLED"
