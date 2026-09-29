"""Three entities whose lifecycles are not a line.

A production lot carries a process dimension and a quality dimension that move
independently, and a rework rewinds the first while resetting the second, so the
same row visits `EXTRUDED` twice with different measurements. A customer order
carries a pricing dimension and a fulfillment dimension that cross without
touching. And a listing file closes a genuine loop, `ACTIVE` to
`VARIATION_NOTICE` and back, with the finding count going 0 to 1 to 0.
"""

from test_helpers import (
    BILLING,
    CERT_OFFICER,
    CLERK,
    ENGINEER,
    advance_lot_to_extruded,
    assert_extrusion_measurements_cleared,
    assert_four_decimal_price,
    assert_lot_dimensions,
    assert_money,
    assert_order_dimensions,
    create_active_certification,
    create_factory_inspection_payload,
    create_lot,
    create_reel,
    create_shipment_payload,
    current_order_version,
    extrusion_step_payload,
    get_success_data,
    load_reel_payload,
    read_certification,
    read_lot,
    read_order,
    read_product,
    record_inline_tests,
    release_lot,
    rework_lot,
    set_clock,
    setup_baseline,
    setup_nonconforming_lot,
    validate_paginated,
    validate_success,
)

# min wall 23.0 of a 30.0 max is a concentricity of 76.67, below the SKU minimum
# of 85, so the in-line gate moves the quality dimension to NONCONFORMING.
OFF_CENTRE_EXTRUSION = {"measured_min_wall_mils": 23.0}
PARTIAL_ORDER = {"order_number": "SO-PAR", "ordered_kft": 10.000}
VARIATION_VISIT = {
    "inspection_date": "2026-08-10",
    "inspector_code": "INS-9",
    "findings_count": 2,
    "outcome": "VARIATION",
}


def _inspection_row(api, certification_id, inspection_id):
    rows, _ = validate_paginated(
        api.list_factory_inspections(certification_id, CERT_OFFICER)
    )
    matches = [row for row in rows if row["id"] == inspection_id]
    assert matches, f"inspection {inspection_id} is missing from the file's history"
    return matches[0]


def test_a_rework_rewinds_one_dimension_and_resets_the_other(api):
    """The disposition moves the process dimension backwards to `STRANDED` and the
    quality dimension forwards out of `NONCONFORMING` to `PENDING` in the same
    request, and wipes the measurement record that condemned the lot.

    PRD 3.7: "Rework clears the measurement record completely, setting
    `measured_min_wall_mils`, `measured_max_wall_mils`, `measured_avg_od_mm`,
    `concentricity_pct` and `surface_marking_text` all back to null, and increments
    `rework_count` by one."

    PRD 3.7: "The process dimension rewinds to `STRANDED` for any construction other
    than `SOLID`, giving the rewind cycle `EXTRUDED` → `STRANDED` → `EXTRUDED`, and
    rewinds to `DRAWN` for a `SOLID` construction."

    PRD 3.7: "On the quality dimension the lot passes through `REWORK` and ends the
    same request at `PENDING`: `REWORK` is observable only as the transient the
    disposition response reports, and the persisted end state is always `PENDING`."

    Design: Difficulty/non_linear_state_machine/production_lot_rework_rewind_across_parallel_dimensions
    """
    world, lot = setup_nonconforming_lot(
        api, extrusion_overrides=OFF_CENTRE_EXTRUSION,
        order_overrides={"order_number": "SO-RWK"},
    )
    assert_lot_dimensions(lot, "EXTRUDED", "NONCONFORMING")
    assert lot["concentricity_pct"] == 76.67, (
        "one hundred times 23.0 divided by 30.0, rounded half up to two decimals"
    )
    assert lot["rework_count"] == 0

    rework_lot(api, lot["id"], rewind_to="STRANDED", reason="concentricity 76.67")

    rewound = read_lot(api, lot["id"])
    assert_lot_dimensions(rewound, "STRANDED", "PENDING")
    assert rewound["rework_count"] == 1, "the rewind counts against the limit of two"
    assert_extrusion_measurements_cleared(rewound)
    assert rewound["version"] > lot["version"], "the rewind is a versioned mutation"
    assert world["order"] is not None


def test_the_same_row_visits_extruded_twice_with_different_measurements(api):
    """After the rewind the lot is re-extruded on the same row: the process dimension
    returns to `EXTRUDED`, the concentricity that was 76.67 is now 85.00, and the
    in-line pair promotes it to `TESTED` while the quality dimension holds at
    `PENDING`.

    PRD 3.6: "Extrusion stores all four values and derives `concentricity_pct` as one
    hundred multiplied by `measured_min_wall_mils`, divided by
    `measured_max_wall_mils`, rounded half up to two decimals."

    PRD 3.6: "A lot sitting exactly on the concentricity limit conforms."

    PRD 3.7: "If `result` is `PASS` and the lot's latest `SPARK` row and latest
    `HIPOT` row both read `PASS`, the process dimension moves `EXTRUDED` → `TESTED`
    with `version` incremented by one, while the quality dimension is untouched and
    stays at `PENDING` until a quality engineer releases the lot."

    Design: Difficulty/non_linear_state_machine/production_lot_rework_rewind_across_parallel_dimensions
    """
    _, lot = setup_nonconforming_lot(
        api, extrusion_overrides=OFF_CENTRE_EXTRUSION,
        order_overrides={"order_number": "SO-RWK"},
    )
    rework_lot(api, lot["id"])

    get_success_data(
        api.create_process_step(lot["id"], extrusion_step_payload(), ENGINEER)
    )
    re_extruded = read_lot(api, lot["id"])
    assert_lot_dimensions(re_extruded, "EXTRUDED", "PENDING")
    assert re_extruded["concentricity_pct"] == 85.00, (
        "25.5 of a 30.0 maximum wall sits exactly on the SKU minimum, which conforms"
    )
    assert re_extruded["measured_min_wall_mils"] == 25.5

    record_inline_tests(api, lot["id"])
    tested = read_lot(api, lot["id"])
    assert_lot_dimensions(tested, "TESTED", "PENDING")
    assert tested["rework_count"] == 1, (
        "a second pass through EXTRUDED does not reset the rework counter"
    )

    rows, _ = validate_paginated(api.list_cable_tests(lot["id"], ENGINEER))
    assert len(rows) == 2, "the spark and hipot rows recorded after the rework"
    assert [row["result"] for row in rows] == ["PASS", "PASS"]


def test_a_compound_suspension_holds_the_price_while_fulfillment_stays_open(api):
    """Two dimensions of one order move on different axes: a formulation suspension
    drives pricing `QUOTED` to `HELD` and the later price confirmation drives it
    back to `LOCKED`, and through both the fulfillment dimension never leaves
    `OPEN`.

    PRD 3.5: "The two dimensions are genuinely independent: `pricing_status` moves
    among `QUOTED`, `LOCKED`, `HELD` and `INVOICED`, while `fulfillment_status` moves
    among `OPEN`, `PARTIALLY_SHIPPED`, `FULFILLED` and the terminal `CANCELLED`, and
    neither dimension constrains the other except where a rule says so explicitly."

    PRD 3.2: "In the second hop, caused by each of those SKU suspensions, every order
    placed against that SKU whose fulfillment dimension is `OPEN` or
    `PARTIALLY_SHIPPED` *and* whose pricing dimension is `QUOTED` or `LOCKED`,
    processed in ascending `created_at` order, has its pricing dimension set to
    `HELD` and its `hold_reason` set to the exact string `COMPOUND_SUSPENDED`, with
    `version` incremented by one."

    PRD 3.5: "The same action also lifts an order sitting at `HELD` back to `LOCKED`
    once the blocking formulation or listing problem has been resolved, clearing
    `hold_reason` back to null as it does so."

    Design: Difficulty/non_linear_state_machine/customer_order_pricing_and_fulfillment_dimensions_move_independently
    """
    world = setup_baseline(api, order_overrides=PARTIAL_ORDER)
    order = world["order"]
    assert_order_dimensions(order, "QUOTED", "OPEN")
    assert_money(order["quoted_total_usd"], 1089.16, "1067.80 plus a 21.36 surcharge")
    assert order["hold_reason"] is None

    get_success_data(
        api.suspend_compound(
            world["insulation"]["id"],
            ENGINEER,
            {"suspension_reason": "filler lot out of spec"},
        )
    )

    held = read_order(api, order["id"])
    assert_order_dimensions(held, "HELD", "OPEN")
    assert held["hold_reason"] == "COMPOUND_SUSPENDED"
    assert read_product(api, world["product"]["id"])["status"] == "SUSPENDED"

    get_success_data(api.qualify_compound(world["insulation"]["id"], ENGINEER))
    get_success_data(api.release_catalog_product(world["product"]["id"], ENGINEER))
    locked = get_success_data(api.price_lock_customer_order(order["id"], BILLING))

    assert_order_dimensions(locked, "LOCKED", "OPEN")
    assert locked["hold_reason"] is None, "confirming the price clears the hold reason"
    assert locked["shipped_kft"] == 0.000, "nothing has shipped on either dimension"


def test_a_partial_shipment_moves_fulfillment_and_leaves_pricing_locked(api):
    """Half of a ten thousand foot order ships and is invoiced: the fulfillment
    dimension advances to `PARTIALLY_SHIPPED` while the pricing dimension stays at
    `LOCKED`, because the invoiced move is reserved for an order that is finished.

    PRD 3.9: "The order's `invoiced_total_usd` is increased by `invoice_amount_usd`,
    and its pricing dimension moves `LOCKED` → `INVOICED` — with `version`
    incremented by one — but only when the order's fulfillment dimension reads
    `FULFILLED` after this invoice *and* every shipment of the order has reached
    `INVOICED`."

    PRD 3.5: "`shipped_kft` accumulates each shipment's shipped length converted from
    feet to thousands of feet, and `invoiced_total_usd` accumulates
    `invoice_amount_usd` across the order's shipments that have reached `INVOICED`."

    PRD 3.5: "The two dimensions are genuinely independent: `pricing_status` moves
    among `QUOTED`, `LOCKED`, `HELD` and `INVOICED`, while `fulfillment_status` moves
    among `OPEN`, `PARTIALLY_SHIPPED`, `FULFILLED` and the terminal `CANCELLED`, and
    neither dimension constrains the other except where a rule says so explicitly."

    Design: Difficulty/non_linear_state_machine/customer_order_pricing_and_fulfillment_dimensions_move_independently
    """
    world = setup_baseline(api, order_overrides=PARTIAL_ORDER)
    order = world["order"]
    get_success_data(api.price_lock_customer_order(order["id"], BILLING))

    lot = create_lot(api, world, lot_code="LOT-PAR", planned_length_ft=5000)
    advance_lot_to_extruded(api, lot["id"])
    record_inline_tests(api, lot["id"])
    release_lot(api, lot["id"], 5000)
    reel = create_reel(api, reel_serial="R-PAR")
    get_success_data(
        api.load_reel(reel["id"], load_reel_payload(lot["id"], 5000), CLERK)
    )
    shipment = validate_success(
        api.create_shipment(
            create_shipment_payload(
                order["id"], lot["id"], reel["id"], 5000,
                current_order_version(api, order["id"]), ship_date="2026-08-05",
            ),
            CLERK,
        ),
        201,
    )

    shipped = read_order(api, order["id"])
    assert_order_dimensions(shipped, "LOCKED", "PARTIALLY_SHIPPED")
    assert shipped["shipped_kft"] == 5.000, "5000 ft of the ordered 10.000 kft"

    invoice = get_success_data(api.invoice_shipment(shipment["id"], BILLING))
    assert_four_decimal_price(invoice["unit_price_usd_per_kft"], 106.7800, "unit price")
    assert_money(invoice["invoice_amount_usd"], 544.58, "533.90 plus a 10.68 surcharge")

    invoiced = read_order(api, order["id"])
    assert_order_dimensions(invoiced, "LOCKED", "PARTIALLY_SHIPPED")
    assert_money(invoiced["invoiced_total_usd"], 544.58, "one invoice so far")


def test_a_variation_notice_opens_a_finding_and_advances_the_cadence(api):
    """A file that a passing audit made `ACTIVE` is pushed to `VARIATION_NOTICE` by the
    next visit, which opens its own row with a corrective deadline and pushes the
    follow-up cadence out by the file's interval.

    PRD 3.3: "A `VARIATION` recorded on an `ACTIVE` file moves it `ACTIVE` →
    `VARIATION_NOTICE`; products stay `RELEASED` under a variation notice, because
    only a suspension freezes the downstream chain."

    PRD 3.3: "`next_inspection_due_date` becomes that `inspection_date` advanced by
    `inspection_interval_days` whole calendar days."

    PRD 3.3: "The row's `corrective_action_due_date` is set to its `inspection_date`
    advanced by 30 calendar days whenever `outcome` is anything other than `PASS`,
    and is left null on a `PASS`."

    Design: Difficulty/non_linear_state_machine/listing_certification_variation_notice_cycle
    """
    set_clock(api)
    certification = create_active_certification(api)
    assert certification["status"] == "ACTIVE"
    assert certification["open_variation_count"] == 0
    assert certification["last_inspection_date"] == "2026-06-05"
    assert certification["next_inspection_due_date"] == "2026-09-03", (
        "2026-06-05 advanced by the file's 90 day interval"
    )
    passing_rows, _ = validate_paginated(
        api.list_factory_inspections(certification["id"], CERT_OFFICER)
    )
    assert passing_rows[0]["status"] == "CLOSED", "a PASS row is born closed"
    assert passing_rows[0]["corrective_action_due_date"] is None

    variation = validate_success(
        api.create_factory_inspection(
            certification["id"],
            create_factory_inspection_payload(**VARIATION_VISIT),
            CERT_OFFICER,
        ),
        201,
    )

    noticed = read_certification(api, certification["id"])
    assert noticed["status"] == "VARIATION_NOTICE"
    assert noticed["open_variation_count"] == 1, "one row on the file is now OPEN"
    assert noticed["last_inspection_date"] == "2026-08-10"
    assert noticed["next_inspection_due_date"] == "2026-11-08", (
        "2026-08-10 advanced by the same 90 day interval"
    )
    assert variation["status"] == "OPEN", "a VARIATION row is born open"
    assert variation["corrective_action_due_date"] == "2026-09-09", (
        "2026-08-10 advanced by the 30 day corrective action window"
    )


def test_the_reinstatement_closes_the_loop_the_variation_opened(api):
    """The cycle comes back round: reinstatement inside the corrective window closes
    the open row, resets the finding count to 0 and returns the file to `ACTIVE`
    with both visits still on its history.

    PRD 3.3: "When the condition holds, every `OPEN` row on the file, processed in
    ascending `created_at` order, moves `OPEN` → `CLOSED` with its own `version`
    incremented by one; `open_variation_count` is reset to 0; and the file's `status`
    becomes `ACTIVE` with `version` incremented by one."

    PRD 3.3: "The agency's condition for reinstatement is that no corrective action
    has gone past its deadline: if any `OPEN` inspection row on the file carries a
    `corrective_action_due_date` earlier than the current logical date, the 30-day
    corrective action window has lapsed and the agency requires a fresh inspection
    rather than a reinstatement, so the request is rejected with
    `ERR_OPEN_VARIATION_UNRESOLVED`."

    PRD 3.3: "Recorded visits may be listed per file and narrowed by `outcome`."

    Design: Difficulty/non_linear_state_machine/listing_certification_variation_notice_cycle
    """
    set_clock(api)
    certification = create_active_certification(api)
    variation = validate_success(
        api.create_factory_inspection(
            certification["id"],
            create_factory_inspection_payload(**VARIATION_VISIT),
            CERT_OFFICER,
        ),
        201,
    )
    assert read_certification(api, certification["id"])["status"] == "VARIATION_NOTICE"

    reinstated = get_success_data(
        api.reinstate_listing_certification(certification["id"], CERT_OFFICER)
    )

    assert reinstated["status"] == "ACTIVE", "the file completes the loop it opened"
    assert reinstated["open_variation_count"] == 0, "0 to 1 and back to 0"
    assert reinstated["version"] > certification["version"]
    assert _inspection_row(api, certification["id"], variation["id"])["status"] == (
        "CLOSED"
    ), "the reinstatement closes the row that opened the notice"

    rows, _ = validate_paginated(
        api.list_factory_inspections(certification["id"], CERT_OFFICER)
    )
    assert [row["inspection_date"] for row in rows] == ["2026-06-05", "2026-08-10"], (
        "both visits stay on the file's history in chronological order"
    )
