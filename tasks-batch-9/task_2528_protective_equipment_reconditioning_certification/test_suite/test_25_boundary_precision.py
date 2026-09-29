"""Inclusive edges and exact-quantity boundaries.

A severity index sitting exactly on the pass ceiling must certify, and a
reservation for exactly the stock on the shelf must succeed while one unit more
must fail without moving anything.
"""
from test_helpers import (
    ApiErrorId,
    PASS_IMPACTS,
    REPAIR_IMPACTS,
    TECHNICIAN_1,
    add_part_line,
    api_client,
    assert_part_stock_conserved,
    create_part,
    open_repair_order,
    read_part,
    read_repair_order,
    setup_determined_units,
    setup_tested_units,
    submit_repair_order,
    validate_error,
)


def test_an_index_exactly_on_the_pass_ceiling_is_a_pass():
    """Three 300 g readings weight and cap to 150.0, 90.0 and 60.0 for an index of
    exactly 300.0, which equals the model's pass ceiling.

    PRD §3.5: "Against a model whose `pass_si_max` is 300.0 that is a `PASS`,
    because the band is inclusive at its upper edge."

    Design: Difficulty/boundary_precision_check/severity_index_exactly_at_pass_limit_is_inclusive_pass
    """
    ctx = setup_tested_units(unit_count=1, impacts=PASS_IMPACTS)

    session = ctx["shell_test"]
    assert ctx["model"]["pass_si_max"] == 300.0
    assert session["severity_index"] == 300.0
    assert session["computed_result"] == "PASS"
    assert ctx["unit"]["current_si"] == 300.0


def test_two_tenths_of_a_point_over_the_ceiling_is_a_repair():
    """Lifting the crown reading to 310 g adds two points to the index, which
    pushes it past the pass ceiling and into the repair band.

    PRD §3.5: "`computed_result` is then the band the index falls into: `PASS`
    when `severity_index` is less than or equal to the model's `pass_si_max`,
    otherwise `REPAIR` when it is less than or equal to the model's
    `repair_si_max`, and otherwise `CONDEMN`."

    Design: Difficulty/boundary_precision_check/severity_index_exactly_at_pass_limit_is_inclusive_pass
    """
    ctx = setup_tested_units(unit_count=1, impacts=(300, 300, 310))

    session = ctx["shell_test"]
    assert session["severity_index"] == 302.0
    assert session["computed_result"] == "REPAIR"


def test_reserving_exactly_the_stock_on_the_shelf_succeeds():
    """A four-unit line against a part holding exactly four on the shelf moves the
    whole shelf into reservation and prices the order at four times 4,500 cents.

    PRD §3.6: "On success each line's quantity moves out of its part's
    `on_hand_qty` and into that part's `reserved_qty`, each line's `status` moves
    `DRAFT → RESERVED`, the order's `reserved_parts_cents` is recomputed as the
    sum of `line_total_cents` over every line whose `status` is `RESERVED`, the
    order advances `DRAFT → PARTS_PENDING`, and its `version` advances by one."

    Design: Difficulty/boundary_precision_check/part_reservation_at_exact_on_hand_then_one_over
    """
    ctx = setup_determined_units(
        unit_count=1, determination="REPAIR", impacts=REPAIR_IMPACTS
    )
    part = create_part(ctx["model"]["id"], received_qty=4)

    order = open_repair_order(ctx["unit"]["id"])
    add_part_line(order["id"], part["id"], 4)
    order = submit_repair_order(order["id"])

    assert order["status"] == "PARTS_PENDING"
    assert order["reserved_parts_cents"] == 18000

    part = read_part(part["id"])
    assert part["received_qty"] == 4
    assert part["on_hand_qty"] == 0
    assert part["reserved_qty"] == 4
    assert part["consumed_qty"] == 0
    assert_part_stock_conserved(part)


def test_reserving_one_unit_more_than_the_shelf_holds_moves_no_stock_at_all():
    """With the shelf already empty a further single-unit line is refused with
    ERR_PART_STOCK_INSUFFICIENT and every bucket is left where it was.

    PRD §3.6: "Every line is checked against its part's `on_hand_qty` first,
    across all lines, before any bucket is touched: if any line's `quantity`
    exceeds its part's `on_hand_qty`, the whole submission is refused with
    `ERR_PART_STOCK_INSUFFICIENT` (HTTP 409) and every stock bucket in the plant
    is left exactly as it was."

    Design: Difficulty/boundary_precision_check/part_reservation_at_exact_on_hand_then_one_over
    """
    ctx = setup_determined_units(
        unit_count=2, determination="REPAIR", impacts=REPAIR_IMPACTS
    )
    part = create_part(ctx["model"]["id"], received_qty=4)

    order_a = open_repair_order(ctx["units"][0]["id"])
    add_part_line(order_a["id"], part["id"], 4)
    submit_repair_order(order_a["id"])

    order_b = open_repair_order(ctx["units"][1]["id"])
    add_part_line(order_b["id"], part["id"], 1, lot_code="LOT-B")
    response = api_client.submit_repair_order(order_b["id"], TECHNICIAN_1)

    validate_error(response, ApiErrorId.ERR_PART_STOCK_INSUFFICIENT, 409)

    order_b = read_repair_order(order_b["id"])
    assert order_b["status"] == "DRAFT"
    assert order_b["reserved_parts_cents"] == 0
    assert order_b["part_lines"][0]["status"] == "DRAFT"

    part = read_part(part["id"])
    assert part["on_hand_qty"] == 0
    assert part["reserved_qty"] == 4
    assert part["consumed_qty"] == 0
    assert_part_stock_conserved(part)
