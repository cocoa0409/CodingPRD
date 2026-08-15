"""Order cancellation: stock restoration, remnant scrapping, capacity release,
and derived-field reconciliation."""
from test_helpers import (
    CLERK,
    PLAN,
    accept_quote,
    create_customer,
    create_full_sheet,
    create_grade,
    create_machine,
    create_submitted_quote,
    find_remnant_for_order,
    get_order,
    rep_headers,
    validate_paginated,
    validate_success,
)

NEST_LINE = {"bbox_width_mm": 300, "bbox_height_mm": 200, "hole_count": 0,
             "corner_fillet_count": 0, "bend_count": 0, "weld_inches": 0,
             "finish": "NONE"}
SMALL_LINE = {"bbox_width_mm": 100, "bbox_height_mm": 100, "hole_count": 0,
              "corner_fillet_count": 0, "bend_count": 0, "weld_inches": 0,
              "finish": "NONE"}


def _accepted_nested_order():
    """10x 300x200 on one sheet: consumed parent + stocked remnant, NESTED."""
    grade = create_grade()
    customer = create_customer()
    sheet = create_full_sheet(grade["id"])
    create_machine("LASER")
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides=NEST_LINE, qty=10)
    order = accept_quote(submitted["id"], customer["id"])
    assert order["status"] == "NESTED"
    return grade, customer, sheet, order


# --- conservation (Difficulty: order_cancel_restores_stock_and_releases_capacity)

def test_cancel_restores_stock_and_scraps_remnant(api):
    """PRD §3.5: "Cancelling an order — permitted only while it is in NESTING
    or NESTED, otherwise `ERR_ORDER_NOT_CANCELLABLE` — deletes all of its
    nest-sheet rows, restores its consumed sheets to AVAILABLE, moves the
    remnant rows its nest generated to SCRAPPED, zeroes the committed totals,
    releases the capacity reservations of any PENDING routing steps, and
    appends an ORDER_CANCELLED audit event."

    Design: Difficulty/compensating_invariant/order_cancel_restores_stock_and_releases_capacity
    """
    grade, customer, sheet, order = _accepted_nested_order()
    remnant = find_remnant_for_order(order["id"])
    assert remnant is not None

    cancelled = validate_success(api.cancel_order(order["id"], PLAN))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["committed_total_cents"] == 0
    assert cancelled["committed_subtotal_cents"] == 0

    parent = validate_success(api.get_sheet_stock(sheet["id"], CLERK))
    assert parent["status"] == "AVAILABLE", "consumed parent sheet restored"

    rows, _meta = validate_paginated(
        api.list_sheet_stock(CLERK, params={"source_order_id": order["id"]}))
    assert rows, "the nest-generated remnant row still exists"
    assert all(r["status"] == "SCRAPPED" for r in rows), (
        "nest-generated remnants are scrapped, not returned to the pool"
    )


def test_cancel_releases_booked_machine_minutes(api):
    """PRD §2.11: "An order cancellation releases its nest — consumed sheets
    return to AVAILABLE, nest-generated remnant rows are scrapped — and frees
    reserved machine minutes."

    Design: Difficulty/compensating_invariant/order_cancel_restores_stock_and_releases_capacity
    """
    grade = create_grade()
    customer = create_customer()
    # 1 minute/day: 12-day capacity 12, cap 0.90 -> 10.8 feasible minutes;
    # each small order books 6 LASER minutes.
    create_machine("LASER", shift_minutes_per_day=1)
    sheet = create_full_sheet(grade["id"])

    q1 = create_submitted_quote(customer["id"], grade["id"],
                                line_overrides=SMALL_LINE, qty=2)
    order1 = accept_quote(q1["id"], customer["id"])

    validate_success(api.cancel_order(order1["id"], PLAN))

    # With the booked minutes freed and the sheet restored, an identical
    # follow-on order nests on the same sheet and fits the capacity window.
    q2 = create_submitted_quote(customer["id"], grade["id"],
                                line_overrides=SMALL_LINE, qty=2)
    resp = api.accept_quote(q2["id"], rep_headers(customer))
    order2 = validate_success(resp, 201)
    assert order2["total_plate_area_cm2"] > 0

    parent = validate_success(api.get_sheet_stock(sheet["id"], CLERK))
    assert parent["status"] == "CONSUMED", "restored sheet is re-selectable"


# --- derived field reconciliation (Corner: derived_plate_area_reconciles_after_cancel)

def test_derived_plate_area_reconciles_after_cancel(api):
    """PRD §3.5: "The order's `total_plate_area_cm2` is the sum of
    `plate_in_area_cm2` across its nest sheets." PRD §3.5: "Cancelling an
    order ... deletes all of its nest-sheet rows, restores its consumed sheets
    to AVAILABLE, moves the remnant rows its nest generated to SCRAPPED,
    zeroes the committed totals ..."

    Design: Corner/cross_cutting_layers/derived_plate_area_reconciles_after_cancel
    """
    grade, customer, sheet, order = _accepted_nested_order()
    assert order["total_plate_area_cm2"] == 11000

    validate_success(api.cancel_order(order["id"], PLAN))

    after = get_order(order["id"])
    assert after["status"] == "CANCELLED"
    assert after["total_plate_area_cm2"] == 0, (
        "the sum over zero remaining nest sheets is zero — no stale cache"
    )
    assert after["committed_total_cents"] == 0
    sheets, _meta = validate_paginated(
        api.list_order_nest_sheets(order["id"], PLAN))
    assert sheets == []
