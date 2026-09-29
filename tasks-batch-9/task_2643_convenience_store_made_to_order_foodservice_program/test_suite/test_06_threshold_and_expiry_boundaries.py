"""Inclusive and strict comparisons probed exactly on their boundary.

Two thresholds in the contract point in opposite directions: the peak labor
multiplier engages at or above its transaction threshold, while the stock
selector accepts a batch only strictly before its hold expiry. Both are
exercised at the exact instant/count where an off-by-one flips the answer.
"""

import test_helpers as H
from test_helpers import fixtures as X

CLOCK_LUNCH = "2026-08-01T11:00:00Z"
CLOCK_MID_AFTERNOON = "2026-08-01T14:00:00Z"
CLOCK_AT_A_EXPIRY = "2026-08-01T15:00:00Z"

A_EXPIRES_AT = "2026-08-01T15:00:00Z"
B_EXPIRES_AT = "2026-08-01T18:00:00Z"

BELOW_THRESHOLD = 399
AT_THRESHOLD = 400
SHARE_BP = 4000


def _store_in_lunch(api):
    X.set_clock(api, CLOCK_LUNCH)
    store = X.create_store(api)
    X.transition_daypart(api, store["id"], "LUNCH")
    return store


def _two_pretzel_pans_expiring_three_hours_apart(api):
    """Pan A holding until exactly 15:00, pan B until 18:00, clock at 15:00."""
    store = X.setup_store_open_for_lunch(api, CLOCK_LUNCH)
    unit = X.create_bakery_case(api, store["id"])
    pretzel = X.create_pretzel(api)
    coffee = X.create_coffee(api)

    batch_a = X.create_holding_batch(
        api,
        store["id"],
        pretzel["id"],
        unit["id"],
        slot_index=1,
        planned_qty=40,
        bake_start_at=CLOCK_LUNCH,
    )
    X.set_clock(api, CLOCK_MID_AFTERNOON)
    batch_b = X.create_holding_batch(
        api,
        store["id"],
        pretzel["id"],
        unit["id"],
        slot_index=2,
        planned_qty=40,
        bake_start_at=CLOCK_MID_AFTERNOON,
    )
    X.set_clock(api, CLOCK_AT_A_EXPIRY)

    order = X.create_draft_order(api, store["id"])
    pretzel_line = X.add_order_line(api, order["id"], pretzel["id"], 5)
    X.add_order_line(api, order["id"], coffee["id"], 1)
    return store, pretzel, batch_a, batch_b, order, pretzel_line


def test_one_transaction_below_the_peak_threshold_stays_on_the_base_multiplier(api):
    """A forecast of 399 is an ordinary daypart, not a peak one.

    "The peak indicator `peak_multiplier_bp` is 11500 basis points when the
    `forecast_txn_count` is at least 400 transactions, and 10000 basis points
    otherwise". The station terms come out at nine and six labor hours - "the
    made-to-order transaction count is the forecast count multiplied by the
    made-to-order share in basis points, divided by ten thousand, and
    **rounded up to the next whole transaction**", then each station count is
    "divided by a throughput of 18 transactions per labor hour and rounded up
    to a whole hour" and "divided by a throughput of 45 transactions per labor
    hour and likewise rounded up to a whole hour" - so the raw figure is 900
    minutes and the base multiplier leaves it there.

    Design: Difficulty/boundary_precision_check/peak_multiplier_engages_at_exactly_400_forecast_transactions
    """
    store = _store_in_lunch(api)

    plan = X.create_staffing_plan(
        api,
        store["id"],
        service_date="2026-08-01",
        daypart="LUNCH",
        forecast_txn_count=BELOW_THRESHOLD,
        mto_share_bp=SHARE_BP,
    )

    assert plan["forecast_txn_count"] == BELOW_THRESHOLD
    assert plan["peak_multiplier_bp"] == 10000
    assert plan["planned_labor_minutes"] == 900
    assert plan["status"] == "DRAFT"


def test_exactly_four_hundred_transactions_engages_the_peak_multiplier(api):
    """The threshold is inclusive, so 400 is already peak.

    "the threshold is inclusive, so a forecast of exactly 400 is a peak
    daypart". The raw station sum is the same 900 minutes as at 399, because
    both forecasts round to 160 made-to-order transactions and six grab-and-go
    labor hours, so the whole difference is the multiplier step: "the raw
    figure is multiplied by `peak_multiplier_bp` and divided by ten thousand,
    with the single result rounded half up to whole minutes". The two plans sit
    on different service dates, since "Creating a plan for a store, service
    date and daypart combination that already has one **supersedes** the
    incumbent".

    Design: Difficulty/boundary_precision_check/peak_multiplier_engages_at_exactly_400_forecast_transactions
    """
    store = _store_in_lunch(api)

    below = X.create_staffing_plan(
        api,
        store["id"],
        service_date="2026-08-01",
        daypart="LUNCH",
        forecast_txn_count=BELOW_THRESHOLD,
        mto_share_bp=SHARE_BP,
    )
    at_threshold = X.create_staffing_plan(
        api,
        store["id"],
        service_date="2026-08-02",
        daypart="LUNCH",
        forecast_txn_count=AT_THRESHOLD,
        mto_share_bp=SHARE_BP,
    )

    assert at_threshold["forecast_txn_count"] == AT_THRESHOLD
    assert at_threshold["peak_multiplier_bp"] == 11500
    assert at_threshold["planned_labor_minutes"] == 1035
    assert at_threshold["planned_labor_minutes"] - below["planned_labor_minutes"] == 135
    assert at_threshold["status"] == "DRAFT"


def test_stock_selector_skips_the_pan_whose_hold_expires_at_the_current_instant(api):
    """A pan expiring exactly now loses to a later-expiring pan.

    Each pull "sets `hold_started_at` to the current logical-clock instant and
    `hold_expires_at` to that instant advanced by the item's `hold_minutes`",
    giving 15:00 and 18:00. With the clock at exactly 15:00 the first-expiring
    pan is disqualified rather than preferred, because a candidate is one
    "whose `hold_expires_at` is **strictly** after the current logical clock -
    a batch whose hold expires exactly now is expired and excluded", and the
    reservation records the survivor: "the selected batch is recorded on the
    line as its `fulfillment_batch_id`, the line's `reserved_qty` is set to the
    line's `qty`".

    Design: Difficulty/boundary_precision_check/fefo_excludes_a_batch_whose_hold_expires_exactly_at_the_clock
    """
    store, pretzel, batch_a, batch_b, order, pretzel_line = (
        _two_pretzel_pans_expiring_three_hours_apart(api)
    )
    assert batch_a["hold_expires_at"] == A_EXPIRES_AT
    assert batch_b["hold_expires_at"] == B_EXPIRES_AT

    placed = X.place_order(api, order["id"])
    assert placed["production_status"] == "PLACED"

    line = X.read_order_line(api, pretzel_line["id"])
    assert line["fulfillment_batch_id"] == batch_b["id"]
    assert line["fulfillment_batch_id"] != batch_a["id"]
    assert line["reserved_qty"] == 5


def test_the_expired_pan_keeps_its_units_while_the_live_pan_pays_for_the_line(api):
    """Only the chosen pan's ledger moves; the expired pan is untouched.

    On the winning batch "the same quantity is subtracted from `remaining_qty`
    and added to `reserved_qty`", while the excluded pan keeps all forty units
    and stays on the case, since "The batch's status is not changed by a
    reservation" and an expiry alone writes nothing off. The order's money is
    the plain line sum: "The order's `subtotal_gross_cents` is recomputed as
    the sum of the `line_gross_cents` of all its lines."

    Design: Difficulty/boundary_precision_check/fefo_excludes_a_batch_whose_hold_expires_exactly_at_the_clock
    """
    store, pretzel, batch_a, batch_b, order, pretzel_line = (
        _two_pretzel_pans_expiring_three_hours_apart(api)
    )

    placed = X.place_order(api, order["id"])

    chosen = X.read_batch(api, batch_b["id"])
    assert chosen["remaining_qty"] == 35
    assert chosen["reserved_qty"] == 5
    H.assert_batch_quantity_ledger(chosen)

    expired = X.read_batch(api, batch_a["id"])
    assert expired["remaining_qty"] == 40
    assert expired["reserved_qty"] == 0
    assert expired["status"] == "HOLDING"
    H.assert_batch_quantity_ledger(expired)

    assert placed["subtotal_gross_cents"] == 1244
