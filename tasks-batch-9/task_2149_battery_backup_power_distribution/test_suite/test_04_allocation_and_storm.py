"""Allocation: lot selection, charge posture and the storm contest."""
import pytest

from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS,
    create_warehouse, create_account, create_battery_model, receive_lot, create_order,
    add_line, submit_order, read_order, read_order_line, read_lot, read_storm_event,
    declare_storm_event, open_storm_allocation, allocate_order,
)

REP = TEST_USERS["sales_rep_headers"]
OPERATOR = TEST_USERS["warehouse_operator_headers"]


def _storm_order_from_the_wrong_state():
    """An OK-state account drawing on a TX storm event whose pool holds 5 units."""
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Red River Coop", account_tier="PLATINUM",
                             state_code="OK", credit_limit_cents=100000000,
                             storm_priority_rank=1)
    model = create_battery_model("IB-AGM-95")
    lot = receive_lot(model["id"], warehouse["id"], manufactured_on="2026-06-01",
                      quantity_on_hand=30)
    storm = declare_storm_event(name="Hurricane Ledger", region_state_code="TX",
                                severity_tier="WARNING", allocation_pool_units=5)
    open_storm_allocation(storm["id"])
    order = create_order(account["id"], warehouse["id"],
                         requested_ship_date="2026-08-06", storm_event_id=storm["id"])
    add_line(order["id"], model["id"], 10, core_expected_count=0)
    order = submit_order(order["id"])
    return {"warehouse": warehouse, "account": account, "model": model, "lot": lot,
            "storm": storm, "order": order}


def test_storm_region_mismatch_is_reported_ahead_of_the_exhausted_pool(api):
    """PRD §3.4: "Three storm gates then apply, and their relative order is
    fixed. First, the buying account's `state_code` must equal the event's
    `region_state_code`, and a mismatch is refused with
    `ERR_STORM_REGION_MISMATCH` (HTTP 422). Second, the computed score must be
    at least the event's `min_priority_score`; the comparison is inclusive, so a
    score exactly equal to the minimum passes, and a score below it is refused
    with `ERR_STORM_PRIORITY_TOO_LOW` (HTTP 403). Third, the sum of the order's
    line quantities must be no greater than the event's `remaining_pool_units`,
    and a shortfall is refused with `ERR_STORM_POOL_EXHAUSTED` (HTTP 422)."
    PRD §3.4: "The declaration opens with `status` at `DECLARED`,
    `allocated_units` at 0, `remaining_pool_units` equal to the whole pool, and
    `min_priority_score` fixed from the severity tier: a `WATCH` sets no floor
    at all with a minimum of 0, a `WARNING` sets a minimum of 45, and an
    `EMERGENCY` sets a minimum of 70."

    Design: Difficulty/priority_pair_validation_conflict/storm_region_mismatch_outranks_pool_exhaustion
    """
    ctx = _storm_order_from_the_wrong_state()
    assert ctx["storm"]["min_priority_score"] == 45
    assert ctx["order"]["subtotal_cents"] == 226200

    resp = api.allocate_order(ctx["order"]["id"], OPERATOR)
    error = validate_error(resp, ApiErrorId.ERR_STORM_REGION_MISMATCH.value)
    assert error["error_id"] != ApiErrorId.ERR_STORM_POOL_EXHAUSTED.value, \
        "The referential rung outranks the fiscal pool rung"


def test_refused_storm_allocation_draws_nothing_from_the_pool_or_the_lot(api):
    """PRD §3.4: "For a storm order, the event's `allocated_units` increases by
    the sum of the order's line quantities and its `remaining_pool_units` is
    re-derived."
    PRD §3.4: "A successful allocation writes `allocation_priority_score` onto
    the order, advances `fulfillment_status` from `SUBMITTED` to `ALLOCATED`,
    and for each line writes the chosen lot into `allocated_lot_id`, sets
    `allocated_quantity` equal to the line's `quantity`, and increments that
    lot's `quantity_reserved` by the same amount, with `quantity_available`
    re-derived."

    Design: Difficulty/priority_pair_validation_conflict/storm_region_mismatch_outranks_pool_exhaustion
    """
    ctx = _storm_order_from_the_wrong_state()
    api.allocate_order(ctx["order"]["id"], OPERATOR)

    assert read_order(ctx["order"]["id"])["fulfillment_status"] == "SUBMITTED"
    storm = read_storm_event(ctx["storm"]["id"])
    assert storm["allocated_units"] == 0
    assert storm["remaining_pool_units"] == 5
    assert read_lot(ctx["lot"]["id"])["quantity_reserved"] == 0


def _two_lots_across_the_refresh_threshold():
    """One lot at exactly 75.0 percent and an older sibling at 70.0 percent."""
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Hill Country Solar", account_tier="STANDARD",
                             state_code="TX", credit_limit_cents=100000000,
                             storm_priority_rank=9)
    model = create_battery_model("IB-SLF-5")
    lot_old = receive_lot(model["id"], warehouse["id"], manufactured_on="2026-01-15",
                          quantity_on_hand=20)
    lot_on = receive_lot(model["id"], warehouse["id"], manufactured_on="2026-03-01",
                         quantity_on_hand=20)
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-09")
    line = add_line(order["id"], model["id"], 5, core_expected_count=0)
    order = submit_order(order["id"])
    return {"warehouse": warehouse, "account": account, "model": model,
            "lot_old": lot_old, "lot_on": lot_on, "order": order, "line": line}


def test_lot_at_exactly_the_refresh_threshold_stays_sellable():
    """PRD §3.2: "Both comparisons against the refresh threshold are strict, so
    a lot sitting at exactly 75.0 percent is `SELLABLE`, not
    `REFRESH_REQUIRED`."
    PRD §3.2: "The model's `self_discharge_pct_per_month` is multiplied by that
    whole month count, the product is subtracted from 100.0, the result is
    floored at 0.0 so `state_of_charge_pct` is never negative, and the value is
    rounded half up to one decimal place."

    Design: Difficulty/boundary_precision_check/state_of_charge_exactly_at_threshold_stays_sellable
    """
    ctx = _two_lots_across_the_refresh_threshold()

    assert ctx["lot_on"]["state_of_charge_pct"] == pytest.approx(75.0, abs=1e-9)
    assert ctx["lot_on"]["condition_state"] == "SELLABLE"
    assert ctx["lot_old"]["state_of_charge_pct"] == pytest.approx(70.0, abs=1e-9)
    assert ctx["lot_old"]["condition_state"] == "REFRESH_REQUIRED"


def test_allocation_skips_the_older_refresh_required_lot():
    """PRD §3.4: "A lot is a candidate for a line only when all four of these
    hold: the lot's `battery_model_id` matches the line's model; the lot's
    `warehouse_id` matches the order's warehouse; the lot's `condition_state` is
    exactly `SELLABLE`; and the lot's effective availability — units on hand
    less units reserved, less the storm carve-out for a non-storm order and
    without that deduction for a storm order — is at least the line's whole
    `quantity`."
    PRD §3.4: "Among the candidates, the winner is the lot with the earliest
    `manufactured_on` date, which is strict first-in-first-out on age; ties on
    that date are broken by the earlier `created_at`."

    Design: Difficulty/boundary_precision_check/state_of_charge_exactly_at_threshold_stays_sellable
    """
    ctx = _two_lots_across_the_refresh_threshold()
    assert ctx["order"]["total_cents"] == 113613

    allocated = allocate_order(ctx["order"]["id"])
    assert allocated["fulfillment_status"] == "ALLOCATED"

    line = read_order_line(ctx["line"]["id"])
    assert line["allocated_lot_id"] == ctx["lot_on"]["id"], \
        "The 75.0 percent lot is the only candidate"
    assert line["allocated_quantity"] == 5
    assert read_lot(ctx["lot_on"]["id"])["quantity_reserved"] == 5
    assert read_lot(ctx["lot_old"]["id"])["quantity_reserved"] == 0


def test_a_declared_storm_event_can_be_closed_without_ever_allocating():
    """PRD §3.4: "Closing the event, which is permitted from `DECLARED` and from
    `ALLOCATING` alike, moves it to `CLOSED`, releases the regional carve-out so
    that available quantity rises again for ordinary work, and refuses any
    further draw against that event with `ERR_INVALID_STATE`; draws already made
    are untouched."
    PRD §3.4: "The declaration opens with `status` at `DECLARED`,
    `allocated_units` at 0, `remaining_pool_units` equal to the whole pool, and
    `min_priority_score` fixed from the severity tier: a `WATCH` sets no floor
    at all with a minimum of 0, a `WARNING` sets a minimum of 45, and an
    `EMERGENCY` sets a minimum of 70."

    Design: Corner/state_machines/storm_event_closes_directly_from_declared
    """
    from test_helpers import close_storm_event
    storm = declare_storm_event(name="Gulf Squall Line", region_state_code="TX",
                                severity_tier="WATCH", allocation_pool_units=25)
    assert storm["status"] == "DECLARED"
    assert storm["min_priority_score"] == 0

    closed = close_storm_event(storm["id"])
    assert closed["status"] == "CLOSED"

    stored = read_storm_event(storm["id"])
    assert stored["allocated_units"] == 0
    assert stored["remaining_pool_units"] == 25


def test_allocation_takes_the_oldest_manufactured_lot_first():
    """PRD §3.4: "Among the candidates, the winner is the lot with the earliest
    `manufactured_on` date, which is strict first-in-first-out on age; ties on
    that date are broken by the earlier `created_at`."
    PRD §3.2: "The number of whole storage months elapsed is the number of whole
    days from that baseline date to the logical clock's current date, divided by
    30 and rounded down to a whole number."

    Design: Corner/calculations/allocation_selector_prefers_the_oldest_manufactured_lot
    """
    from test_helpers import read_lot
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Delta Fleet", account_tier="STANDARD", state_code="TX",
                             credit_limit_cents=100000000, storm_priority_rank=5)
    model = create_battery_model("IB-31-FLD")
    newer = receive_lot(model["id"], warehouse["id"], manufactured_on="2026-06-01",
                        quantity_on_hand=30)
    older = receive_lot(model["id"], warehouse["id"], manufactured_on="2026-05-01",
                        quantity_on_hand=30)
    assert newer["state_of_charge_pct"] == pytest.approx(88.0, abs=1e-9)
    assert older["state_of_charge_pct"] == pytest.approx(82.0, abs=1e-9)

    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-10")
    line = add_line(order["id"], model["id"], 5, core_expected_count=0)
    submit_order(order["id"])
    allocate_order(order["id"])

    assert read_order_line(line["id"])["allocated_lot_id"] == older["id"], \
        "First-in-first-out beats creation order"
    assert read_lot(older["id"])["quantity_reserved"] == 5
    assert read_lot(newer["id"])["quantity_reserved"] == 0


def test_storm_carve_out_shrinks_what_an_ordinary_order_may_draw(api):
    """PRD §3.4: "Whenever at least one storm event stands in `DECLARED` or in
    `ALLOCATING` whose region matches a warehouse's own `state_code`, every lot
    at that warehouse carves out the number of units equal to its
    `quantity_on_hand` multiplied by the site's `storm_reserve_pct` and rounded
    **down** to a whole unit. Ordinary non-storm allocation may draw only on the
    units on hand less those already reserved less that carve-out; a storm order
    draws on the units on hand less those already reserved, ignoring the
    carve-out entirely — that is precisely what the carve-out is for."
    PRD §3.4: "When no candidate qualifies, the platform inspects the lots that
    match the line's model and the order's warehouse and whose units on hand
    less units reserved would have covered the line, and it reports the most
    informative reason in this exact order: if any such lot stands in
    `SHELF_EXPIRED`, the request fails with `ERR_LOT_SHELF_EXPIRED` (HTTP 422);
    otherwise if any such lot stands in `REFRESH_REQUIRED`, it fails with
    `ERR_LOT_REFRESH_REQUIRED` (HTTP 422); otherwise it fails with
    `ERR_INSUFFICIENT_SELLABLE_STOCK` (HTTP 422)."

    Design: Corner/calculations/storm_carve_out_shrinks_available_units_for_non_storm_orders
    """
    from test_helpers import read_lot
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.20,
                                 dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Delta Fleet", account_tier="STANDARD", state_code="TX",
                             credit_limit_cents=100000000, storm_priority_rank=5)
    model = create_battery_model("IB-AGM-95")
    lot = receive_lot(model["id"], warehouse["id"], manufactured_on="2026-06-01",
                      quantity_on_hand=30)
    declare_storm_event(name="Gulf Squall Line", region_state_code="TX",
                        severity_tier="WATCH", allocation_pool_units=25)

    big = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-10")
    add_line(big["id"], model["id"], 25, core_expected_count=0)
    submit_order(big["id"])
    small = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-10")
    small_line = add_line(small["id"], model["id"], 24, core_expected_count=0)
    submit_order(small["id"])

    resp = api.allocate_order(big["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SELLABLE_STOCK.value)
    assert read_order(big["id"])["fulfillment_status"] == "SUBMITTED"

    allocated = allocate_order(small["id"])
    assert allocated["fulfillment_status"] == "ALLOCATED", \
        "24 units fit inside the 6-unit carve-out"
    assert read_order_line(small_line["id"])["allocated_lot_id"] == lot["id"]
    stored = read_lot(lot["id"])
    assert stored["quantity_reserved"] == 24
    assert stored["quantity_on_hand"] == 30


def test_storm_draw_scores_the_order_and_decrements_the_pool():
    """PRD §3.4: "The storm score is the sum of four components. Tier points
    come from the account: 40 for `PLATINUM`, 28 for `GOLD` and 12 for
    `STANDARD`. Rank points reward a low `storm_priority_rank`: subtract the
    rank from 6, floor the difference at 0, and multiply by 5 — so rank 1 earns
    25 points, rank 5 earns 5, and ranks 6 through 9 earn nothing. Severity
    points come from the event: 5 for a `WATCH`, 12 for a `WARNING` and 20 for
    an `EMERGENCY`. Value points reward order size: divide the order's frozen
    `subtotal_cents` by 100000 — that is, count whole thousand-dollar increments
    — round down, and cap the result at 15."
    PRD §3.4: "For a storm order, the event's `allocated_units` increases by the
    sum of the order's line quantities and its `remaining_pool_units` is
    re-derived."

    Design: Corner/calculations/storm_order_draw_decrements_the_allocation_pool
    """
    from test_helpers import read_lot
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.20,
                                 dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Pinnacle Power", account_tier="PLATINUM",
                             state_code="TX", credit_limit_cents=100000000,
                             storm_priority_rank=1)
    model = create_battery_model("IB-AGM-95")
    lot = receive_lot(model["id"], warehouse["id"], manufactured_on="2026-06-01",
                      quantity_on_hand=30)
    storm = declare_storm_event(name="Hurricane Ledger", region_state_code="TX",
                                severity_tier="EMERGENCY", allocation_pool_units=20)
    assert storm["min_priority_score"] == 70
    open_storm_allocation(storm["id"])

    order = create_order(account["id"], warehouse["id"],
                         requested_ship_date="2026-08-06", storm_event_id=storm["id"])
    line = add_line(order["id"], model["id"], 10, core_expected_count=0)
    submitted = submit_order(order["id"])
    assert submitted["subtotal_cents"] == 226200

    allocated = allocate_order(order["id"])
    assert allocated["allocation_priority_score"] == 87, \
        f"40 tier plus 25 rank plus 20 severity plus 2 value, got {allocated['allocation_priority_score']}"
    assert allocated["fulfillment_status"] == "ALLOCATED"

    event = read_storm_event(storm["id"])
    assert event["allocated_units"] == 10
    assert event["remaining_pool_units"] == 10
    assert read_lot(lot["id"])["quantity_reserved"] == 10
    assert read_order_line(line["id"])["allocated_lot_id"] == lot["id"]


def test_storm_draw_below_the_event_minimum_is_refused(api):
    """PRD §3.4: "Second, the computed score must be at least the event's
    `min_priority_score`; the comparison is inclusive, so a score exactly equal
    to the minimum passes, and a score below it is refused with
    `ERR_STORM_PRIORITY_TOO_LOW` (HTTP 403)."
    PRD §3.4: "Opening the pool for draws moves the event from `DECLARED` to
    `ALLOCATING`, and only then may a storm order be allocated; an attempt to
    allocate a storm order against an event still in `DECLARED` is refused with
    `ERR_INVALID_STATE`."

    Design: Corner/calculations/storm_priority_below_event_minimum_is_refused
    """
    from test_helpers import read_lot
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0,
                                 dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Backroad Auto", account_tier="STANDARD",
                             state_code="TX", credit_limit_cents=100000000,
                             storm_priority_rank=9)
    model = create_battery_model("IB-AGM-95")
    lot = receive_lot(model["id"], warehouse["id"], manufactured_on="2026-06-01",
                      quantity_on_hand=30)
    storm = declare_storm_event(name="Hurricane Ledger", region_state_code="TX",
                                severity_tier="EMERGENCY", allocation_pool_units=20)
    open_storm_allocation(storm["id"])

    order = create_order(account["id"], warehouse["id"],
                         requested_ship_date="2026-08-06", storm_event_id=storm["id"])
    add_line(order["id"], model["id"], 1, core_expected_count=0)
    submitted = submit_order(order["id"])
    assert submitted["subtotal_cents"] == 26000

    resp = api.allocate_order(order["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_STORM_PRIORITY_TOO_LOW.value)

    assert read_order(order["id"])["fulfillment_status"] == "SUBMITTED"
    event = read_storm_event(storm["id"])
    assert event["allocated_units"] == 0
    assert event["remaining_pool_units"] == 20
    assert read_lot(lot["id"])["quantity_reserved"] == 0


def test_a_draw_larger_than_the_remaining_pool_is_refused(api):
    """PRD §3.4: "Third, the sum of the order's line quantities must be no
    greater than the event's `remaining_pool_units`, and a shortfall is refused
    with `ERR_STORM_POOL_EXHAUSTED` (HTTP 422)."
    PRD §3.4: "A compliance officer or an administrator declares a storm by
    naming it, giving its `region_state_code` as a two-letter code, choosing its
    `severity_tier` from `WATCH`, `WARNING` and `EMERGENCY`, and setting the
    `allocation_pool_units` reserved for it, which must be at least 1."

    Design: Corner/validations/storm_draw_beyond_remaining_pool_returns_pool_exhausted
    """
    from test_helpers import read_lot
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0,
                                 dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Pinnacle Power", account_tier="PLATINUM",
                             state_code="TX", credit_limit_cents=100000000,
                             storm_priority_rank=1)
    model = create_battery_model("IB-AGM-95")
    lot = receive_lot(model["id"], warehouse["id"], manufactured_on="2026-06-01",
                      quantity_on_hand=30)
    storm = declare_storm_event(name="Hurricane Ledger", region_state_code="TX",
                                severity_tier="EMERGENCY", allocation_pool_units=5)
    open_storm_allocation(storm["id"])

    order = create_order(account["id"], warehouse["id"],
                         requested_ship_date="2026-08-06", storm_event_id=storm["id"])
    add_line(order["id"], model["id"], 10, core_expected_count=0)
    submit_order(order["id"])

    resp = api.allocate_order(order["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_STORM_POOL_EXHAUSTED.value)

    assert read_order(order["id"])["fulfillment_status"] == "SUBMITTED"
    event = read_storm_event(storm["id"])
    assert event["allocated_units"] == 0
    assert event["remaining_pool_units"] == 5
    assert read_lot(lot["id"])["quantity_reserved"] == 0


def _submitted_order_against_one_lot(manufactured_on=None, quantity_on_hand=20,
                                     preset="IB-SLF-5", with_lot=True):
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Delta Fleet", account_tier="STANDARD", state_code="TX",
                             credit_limit_cents=100000000, storm_priority_rank=5)
    model = create_battery_model(preset)
    lot = None
    if with_lot:
        lot = receive_lot(model["id"], warehouse["id"], manufactured_on=manufactured_on,
                          quantity_on_hand=quantity_on_hand)
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-10")
    line = add_line(order["id"], model["id"], 5, core_expected_count=0)
    submit_order(order["id"])
    return {"warehouse": warehouse, "account": account, "model": model, "lot": lot,
            "order": order, "line": line}


def test_allocation_against_only_shelf_expired_stock_reports_the_expiry(api):
    """PRD §3.4: "if any such lot stands in `SHELF_EXPIRED`, the request fails
    with `ERR_LOT_SHELF_EXPIRED` (HTTP 422); otherwise if any such lot stands in
    `REFRESH_REQUIRED`, it fails with `ERR_LOT_REFRESH_REQUIRED` (HTTP 422);
    otherwise it fails with `ERR_INSUFFICIENT_SELLABLE_STOCK` (HTTP 422)."
    PRD §3.2: "Second: if the number of whole days from `manufactured_on` to the
    clock's current date is strictly greater than the model's `shelf_life_days`,
    the lot is `SHELF_EXPIRED` — the comparison is strict, so a lot whose age in
    days exactly equals its shelf life is still in service."

    Design: Corner/validations/allocate_with_only_a_shelf_expired_lot_returns_shelf_expired
    """
    from test_helpers import read_lot
    ctx = _submitted_order_against_one_lot(manufactured_on="2024-01-01")
    assert ctx["lot"]["condition_state"] == "SHELF_EXPIRED"

    resp = api.allocate_order(ctx["order"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_LOT_SHELF_EXPIRED.value)

    assert read_order(ctx["order"]["id"])["fulfillment_status"] == "SUBMITTED"
    assert read_order_line(ctx["line"]["id"])["allocated_lot_id"] is None
    assert read_lot(ctx["lot"]["id"])["quantity_reserved"] == 0


def test_allocation_against_only_undercharged_stock_reports_the_refresh_need(api):
    """PRD §3.4: "if any such lot stands in `SHELF_EXPIRED`, the request fails
    with `ERR_LOT_SHELF_EXPIRED` (HTTP 422); otherwise if any such lot stands in
    `REFRESH_REQUIRED`, it fails with `ERR_LOT_REFRESH_REQUIRED` (HTTP 422);
    otherwise it fails with `ERR_INSUFFICIENT_SELLABLE_STOCK` (HTTP 422)."
    PRD §3.2: "Fourth: if its state of charge is below 75.0 percent, the lot is
    `REFRESH_REQUIRED`. Otherwise the lot is `SELLABLE`."

    Design: Corner/validations/allocate_with_only_a_refresh_required_lot_returns_refresh_required
    """
    ctx = _submitted_order_against_one_lot(manufactured_on="2026-01-15")
    assert ctx["lot"]["state_of_charge_pct"] == pytest.approx(70.0, abs=1e-9)
    assert ctx["lot"]["condition_state"] == "REFRESH_REQUIRED"

    resp = api.allocate_order(ctx["order"]["id"], OPERATOR)
    error = validate_error(resp, ApiErrorId.ERR_LOT_REFRESH_REQUIRED.value)
    assert error["error_id"] != ApiErrorId.ERR_LOT_SHELF_EXPIRED.value

    assert read_order(ctx["order"]["id"])["fulfillment_status"] == "SUBMITTED"


def test_allocation_with_no_lot_at_all_reports_insufficient_stock(api):
    """PRD §3.4: "When no candidate qualifies, the platform inspects the lots
    that match the line's model and the order's warehouse and whose units on
    hand less units reserved would have covered the line, and it reports the
    most informative reason in this exact order: if any such lot stands in
    `SHELF_EXPIRED`, the request fails with `ERR_LOT_SHELF_EXPIRED` (HTTP 422);
    otherwise if any such lot stands in `REFRESH_REQUIRED`, it fails with
    `ERR_LOT_REFRESH_REQUIRED` (HTTP 422); otherwise it fails with
    `ERR_INSUFFICIENT_SELLABLE_STOCK` (HTTP 422)."

    Design: Corner/validations/allocate_with_no_lot_for_the_model_returns_insufficient_stock
    """
    ctx = _submitted_order_against_one_lot(preset="IB-AGM-95", with_lot=False)

    resp = api.allocate_order(ctx["order"]["id"], OPERATOR)
    error = validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SELLABLE_STOCK.value)
    assert error["error_id"] != ApiErrorId.ERR_LOT_SHELF_EXPIRED.value

    assert read_order(ctx["order"]["id"])["fulfillment_status"] == "SUBMITTED"
    assert read_order_line(ctx["line"]["id"])["allocated_quantity"] == 0
