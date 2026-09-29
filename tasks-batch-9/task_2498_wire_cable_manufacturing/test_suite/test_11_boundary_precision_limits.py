"""Three limits where the discriminating input is the last digit.

A partial-discharge reading exactly on the picocoulomb limit passes and the next
tenth fails. A float window holding exactly the minimum number of settlements
prices, one short refuses, and a settlement dated one day before the window opens
must stay out of the mean. And a concentricity ratio is compared after it has
been rounded, so a hundredth of a mil of wall decides the verdict.
"""

from test_helpers import (
    BILLING,
    CLERK,
    ENGINEER,
    QE_RELEASER,
    QE_TESTER,
    advance_lot_to_stranded,
    assert_credit_exposure_identity,
    assert_four_decimal_price,
    assert_lot_dimensions,
    assert_money,
    create_lot,
    create_metal_quote,
    create_reel,
    create_rod_lot,
    create_shipment_payload,
    current_order_version,
    get_success_data,
    load_reel_payload,
    read_customer,
    read_lot,
    read_shipment,
    release_lot,
    rework_lot,
    set_clock,
    setup_baseline,
    setup_mv_catalog,
    validate_error,
    validate_success,
)

MV_EXTRUSION = {
    "step": "EXTRUSION",
    "measured_min_wall_mils": 160.0,
    "measured_max_wall_mils": 175.0,
    "measured_avg_od_mm": 21.6,
}
MV_HIPOT = {
    "test_type": "HIPOT",
    "test_voltage_kv": 35.0,
    "breakdown_detected": False,
    "duration_sec": 900,
}
SPARK = {"test_type": "SPARK", "faults_detected": 0, "duration_sec": 60}
# The order is booked off the 2026-07-28 settlement; the four later settlements
# decide the float windows.
BOOKING_QUOTE = {
    "effective_date": "2026-07-28", "settlement_price_usd_per_lb": 3.90,
}
LATE_SERIES = (
    ("2026-07-31", 3.00),
    ("2026-08-01", 4.00),
    ("2026-08-03", 4.05),
    ("2026-08-05", 4.10),
)
SECOND_LINE_WINDOW = {
    "line_code": "EXT-2",
    "scheduled_start_at": "2026-08-02T08:00:00Z",
    "scheduled_end_at": "2026-08-02T12:00:00Z",
}


def _mv_lot_at_tested(api):
    """An MV_15KV lot promoted by the in-line pair, still owing its lab result."""
    world = setup_mv_catalog(api)
    world["customer"] = None
    world["order"] = None
    world["rod_lot"] = create_rod_lot(api)
    lot = create_lot(api, world, lot_code="LOT-PD", planned_length_ft=2000)
    advance_lot_to_stranded(api, lot["id"])
    extruded = get_success_data(
        api.create_process_step(lot["id"], MV_EXTRUSION, ENGINEER)
    )
    assert extruded["concentricity_pct"] == 91.43, (
        "one hundred times 160.0 divided by 175.0, well clear of the 85 minimum"
    )
    get_success_data(api.create_cable_test(lot["id"], SPARK, QE_TESTER))
    get_success_data(api.create_cable_test(lot["id"], MV_HIPOT, QE_TESTER))
    promoted = read_lot(api, lot["id"])
    assert_lot_dimensions(promoted, "TESTED", "PENDING")
    return world, promoted


def _pd_row(api, lot_id, pd_level_pc):
    return get_success_data(
        api.create_cable_test(
            lot_id,
            {"test_type": "PARTIAL_DISCHARGE", "pd_level_pc": pd_level_pc,
             "duration_sec": 600},
            QE_TESTER,
        )
    )


def _float_world(api):
    """One SHIP_DATE_FLOAT order with two staged shipments: one whose window holds
    exactly three settlements and one whose window holds only two."""
    world = setup_baseline(
        api,
        quote_overrides=BOOKING_QUOTE,
        order_overrides={
            "order_number": "SO-FLT", "ordered_kft": 10.000,
            "price_basis": "SHIP_DATE_FLOAT",
        },
        rod_overrides={"heat_number": "H-77Q", "purchase_weight_lbs": 20000.00},
    )
    order = world["order"]
    get_success_data(api.price_lock_customer_order(order["id"], BILLING))

    lots = []
    for lot_code, overrides in (
        ("LOT-FLT-A", {}), ("LOT-FLT-B", SECOND_LINE_WINDOW),
    ):
        lot = create_lot(
            api, world, lot_code=lot_code, planned_length_ft=5000, **overrides
        )
        advance_lot_to_stranded(api, lot["id"])
        get_success_data(
            api.create_process_step(
                lot["id"],
                {"step": "EXTRUSION", "measured_min_wall_mils": 25.5,
                 "measured_max_wall_mils": 30.0, "measured_avg_od_mm": 4.1,
                 "surface_marking_text": world["product"]["required_marking_text"]},
                ENGINEER,
            )
        )
        get_success_data(api.create_cable_test(lot["id"], SPARK, QE_TESTER))
        get_success_data(
            api.create_cable_test(
                lot["id"],
                {"test_type": "HIPOT", "test_voltage_kv": 2.5,
                 "breakdown_detected": False, "duration_sec": 300},
                QE_TESTER,
            )
        )
        release_lot(api, lot["id"], 5000)
        lots.append(lot)

    set_clock(api, "2026-08-06T00:00:00Z")
    for effective_date, price in LATE_SERIES:
        create_metal_quote(
            api, effective_date=effective_date, settlement_price_usd_per_lb=price
        )

    shipments = []
    for lot, serial, ship_date in (
        (lots[0], "R-FLT-A", "2026-08-05"), (lots[1], "R-FLT-B", "2026-08-02"),
    ):
        reel = create_reel(api, reel_serial=serial)
        get_success_data(
            api.load_reel(
                reel["id"],
                load_reel_payload(lot["id"], 5000,
                                  occupancy_start_at="2026-08-03T00:00:00Z"),
                CLERK,
            )
        )
        shipments.append(
            validate_success(
                api.create_shipment(
                    create_shipment_payload(
                        order["id"], lot["id"], reel["id"], 5000,
                        current_order_version(api, order["id"]), ship_date=ship_date,
                    ),
                    CLERK,
                ),
                201,
            )
        )
    return world, shipments


def test_a_partial_discharge_reading_exactly_on_the_limit_passes(api):
    """The picocoulomb comparison is inclusive, so 5.0 pC on a 15 kV class is a pass,
    exactly as 4.9 pC is, and neither touches the process dimension the in-line
    pair already advanced.

    PRD 3.7: "A `PARTIAL_DISCHARGE` row passes when `pd_level_pc` is at most the
    limit for the SKU's voltage class — 5.0 picocoulombs for both `MV_5KV` and
    `MV_15KV`, and a tighter 3.0 picocoulombs for `MV_35KV` — comparing at one
    decimal place, with a reading exactly on the limit passing."

    PRD 3.7: "Only spark and high-potential testing gate that promotion, and the
    omission is intentional."

    Design: Difficulty/boundary_precision_check/partial_discharge_exactly_at_pd_limit_passes
    """
    world, lot = _mv_lot_at_tested(api)
    assert world["product"]["pd_test_required"] is True, (
        "a 15 kV class SKU owes a partial-discharge result"
    )

    below = _pd_row(api, lot["id"], 4.9)
    assert below["result"] == "PASS", "4.9 pC is unremarkably inside the limit"

    at_the_limit = _pd_row(api, lot["id"], 5.0)
    assert at_the_limit["result"] == "PASS", (
        "5.0 pC is at most the 5.0 pC limit, so the agency accepts it"
    )
    assert at_the_limit["pd_level_pc"] == 5.0

    settled = read_lot(api, lot["id"])
    assert_lot_dimensions(settled, "TESTED", "PENDING")
    released = validate_success(
        api.release_production_lot(lot["id"], {"packaged_length_ft": 2000}, QE_RELEASER),
        200,
    )
    assert released["quality_state"] == "CONFORMING", (
        "a lot sitting exactly on the limit is releasable"
    )


def test_one_tenth_over_the_partial_discharge_limit_poisons_the_quality_dimension(api):
    """5.1 pC fails, and the failing off-line row moves the quality dimension to
    `NONCONFORMING` without rewinding the process dimension that the in-line pair
    had already advanced.

    PRD 3.7: "A `PARTIAL_DISCHARGE` row passes when `pd_level_pc` is at most the
    limit for the SKU's voltage class — 5.0 picocoulombs for both `MV_5KV` and
    `MV_15KV`, and a tighter 3.0 picocoulombs for `MV_35KV` — comparing at one
    decimal place, with a reading exactly on the limit passing."

    PRD 3.7: "If `result` is `FAIL` and the lot's quality dimension currently reads
    `PENDING`, the quality dimension moves `PENDING` → `NONCONFORMING` and `version`
    is incremented by one."

    Design: Difficulty/boundary_precision_check/partial_discharge_exactly_at_pd_limit_passes
    """
    _, lot = _mv_lot_at_tested(api)

    over = _pd_row(api, lot["id"], 5.1)
    assert over["result"] == "FAIL", "5.1 pC is strictly more than the 5.0 pC limit"

    poisoned = read_lot(api, lot["id"])
    assert_lot_dimensions(poisoned, "TESTED", "NONCONFORMING")
    assert poisoned["version"] > lot["version"], (
        "the failing row is a versioned mutation of the lot"
    )


def test_a_float_window_holding_exactly_three_settlements_prices_the_invoice(api):
    """Three quotes are enough to average, and the settlement dated the day before
    the window opens stays out of the mean: 4.0500 rather than the 3.7875 that
    letting it in would produce.

    PRD 3.9: "Under `SHIP_DATE_FLOAT`, `metal_price_used_usd_per_lb` is the
    arithmetic mean of `settlement_price_usd_per_lb` across every quote whose
    `metal` equals the SKU's `conductor_metal` and whose `effective_date` falls
    inside an inclusive five-calendar-day window running from four days before the
    shipment's `ship_date` through `ship_date` itself, rounded half up to four
    decimal places."

    PRD 3.9: "`unit_price_usd_per_kft` is the order's `conversion_price_usd_per_kft`
    plus that component, rounded half up to four decimal places."

    PRD 3.9: "`invoice_amount_usd` is then the extension plus the cut fee plus the
    surcharge, rounded half up to two decimals, and `invoice_date` is the logical
    clock's current date."

    Design: Difficulty/boundary_precision_check/ship_date_float_window_at_exactly_three_quotes
    """
    _, shipments = _float_world(api)

    invoice = get_success_data(api.invoice_shipment(shipments[0]["id"], BILLING))

    assert invoice["price_variant_applied"] == "SHIP_DATE_FLOAT"
    assert_four_decimal_price(
        invoice["metal_price_used_usd_per_lb"], 4.0500,
        "4.00, 4.05 and 4.10 average to 4.0500; the 3.00 settlement dated five days "
        "before the ship date is outside the window",
    )
    assert_four_decimal_price(
        invoice["unit_price_usd_per_kft"], 105.7900, "85.00 plus 19.8 x 1.05"
    )
    assert_money(invoice["extended_amount_usd"], 528.95, "105.79 over 5.000 kft")
    assert_money(invoice["cut_fee_usd"], 0.00, "this order is not cut to length")
    assert_money(invoice["volatility_surcharge_usd"], 10.58, "two percent of 528.95")
    assert_money(invoice["invoice_amount_usd"], 539.53, "the floated invoice")
    assert invoice["status"] == "INVOICED"


def test_a_float_window_one_settlement_short_refuses_and_changes_nothing(api):
    """The other shipment's window catches only two settlements, so invoicing is
    refused with `ERR_INSUFFICIENT_PRICE_HISTORY` and the shipment is left exactly
    where it was.

    PRD 3.9: "If fewer than three quotes fall inside that window there is not enough
    market to average, and the invoice is refused with
    `ERR_INSUFFICIENT_PRICE_HISTORY` while the shipment stays exactly where it was at
    `STAGED`."

    PRD 3.8: "A staged shipment is born at `STAGED` with `deposit_charged_usd` taken
    from the reel's `deposit_usd`, and with `metal_price_used_usd_per_lb`,
    `price_variant_applied`, `unit_price_usd_per_kft`, `extended_amount_usd`,
    `cut_fee_usd`, `volatility_surcharge_usd`, `invoice_amount_usd` and
    `invoice_date` all still null — nothing is priced until it is invoiced."

    PRD 2.11: "Checks are evaluated in the following order, and the first failure ends
    the request with no persisted effect whatsoever:"

    Design: Difficulty/boundary_precision_check/ship_date_float_window_at_exactly_three_quotes
    """
    world, shipments = _float_world(api)
    get_success_data(api.invoice_shipment(shipments[0]["id"], BILLING))

    validate_error(
        api.invoice_shipment(shipments[1]["id"], BILLING),
        "ERR_INSUFFICIENT_PRICE_HISTORY", 422,
    )

    untouched = read_shipment(api, shipments[1]["id"])
    assert untouched["status"] == "STAGED", "the refused invoice moved nothing"
    assert untouched["invoice_amount_usd"] is None
    assert untouched["invoice_date"] is None
    assert untouched["metal_price_used_usd_per_lb"] is None
    assert_money(untouched["deposit_charged_usd"], 450.00, "the deposit was charged "
                 "at staging and is unaffected by the refusal")

    account = read_customer(api, world["customer"]["id"])
    assert_money(account["open_ar_usd"], 539.53, "only the priced shipment is billed")
    assert_money(account["reel_deposit_balance_usd"], 900.00, "two reels are out")
    assert_money(account["credit_exposure_usd"], 1439.53, "539.53 plus 900.00")
    assert_credit_exposure_identity(account)


def test_a_concentricity_ratio_exactly_on_the_rounded_minimum_conforms(api):
    """25.5 of a 30.0 maximum wall rounds to exactly 85.00, which is inclusive, so the
    lot leaves extrusion with its quality dimension still at `PENDING`.

    PRD 3.6: "Extrusion stores all four values and derives `concentricity_pct` as one
    hundred multiplied by `measured_min_wall_mils`, divided by
    `measured_max_wall_mils`, rounded half up to two decimals."

    PRD 3.6: "The in-line quality gate then applies concentricity **only**: when
    `concentricity_pct` is strictly less than the SKU's `concentricity_min_pct` the
    quality dimension moves `PENDING` → `NONCONFORMING`, and otherwise the quality
    dimension is left at `PENDING`. A lot sitting exactly on the concentricity limit
    conforms."

    Design: Difficulty/boundary_precision_check/concentricity_exactly_at_sku_minimum_passes_extrusion
    """
    world = setup_baseline(
        api,
        product_overrides={"min_wall_pct": 90, "concentricity_min_pct": 85},
        order_overrides={"order_number": "SO-CON", "ordered_kft": 10.000},
    )
    lot = create_lot(api, world, lot_code="LOT-CON-OK", planned_length_ft=5000)
    advance_lot_to_stranded(api, lot["id"])

    extruded = get_success_data(
        api.create_process_step(
            lot["id"],
            {"step": "EXTRUSION", "measured_min_wall_mils": 25.5,
             "measured_max_wall_mils": 30.0, "measured_avg_od_mm": 4.1,
             "surface_marking_text": world["product"]["required_marking_text"]},
            ENGINEER,
        )
    )

    assert extruded["concentricity_pct"] == 85.00, (
        "one hundred times 25.5 divided by 30.0 is exactly the SKU minimum"
    )
    assert_lot_dimensions(extruded, "EXTRUDED", "PENDING")
    assert extruded["measured_min_wall_mils"] == 25.5, (
        "25.5 also clears the 25.20 mil minimum wall, so concentricity is the only "
        "thing under examination"
    )


def test_a_hundredth_of_a_mil_less_wall_rounds_below_the_minimum_and_condemns_the_lot(
    api,
):
    """25.49 of the same 30.0 maximum rounds to 84.97, one hundredth of a percent under
    the minimum, so the quality dimension is condemned while the process dimension
    still advances — and the lot is recoverable by rework.

    PRD 3.6: "The in-line quality gate then applies concentricity **only**: when
    `concentricity_pct` is strictly less than the SKU's `concentricity_min_pct` the
    quality dimension moves `PENDING` → `NONCONFORMING`, and otherwise the quality
    dimension is left at `PENDING`."

    PRD 3.6: "The minimum-wall gate is deliberately *not* applied here — it is
    re-checked independently at release — which means a lot can be perfectly
    concentric yet uniformly under-walled, pass extrusion, pass testing, and only be
    stopped at the very end."

    PRD 3.7: "A `REWORK` disposition is available from process state `EXTRUDED` and is
    refused once `rework_count` has already reached the limit of 2 — at that point the
    lot must be scrapped — with `ERR_REWORK_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/concentricity_exactly_at_sku_minimum_passes_extrusion
    """
    world = setup_baseline(
        api,
        product_overrides={"min_wall_pct": 90, "concentricity_min_pct": 85},
        order_overrides={"order_number": "SO-CON", "ordered_kft": 10.000},
    )
    lot = create_lot(api, world, lot_code="LOT-CON-NG", planned_length_ft=5000)
    advance_lot_to_stranded(api, lot["id"])

    extruded = get_success_data(
        api.create_process_step(
            lot["id"],
            {"step": "EXTRUSION", "measured_min_wall_mils": 25.49,
             "measured_max_wall_mils": 30.0, "measured_avg_od_mm": 4.1,
             "surface_marking_text": world["product"]["required_marking_text"]},
            ENGINEER,
        )
    )

    assert extruded["concentricity_pct"] == 84.97, (
        "one hundred times 25.49 divided by 30.0 is 84.9666..., which rounds half up"
    )
    assert_lot_dimensions(extruded, "EXTRUDED", "NONCONFORMING")
    assert extruded["measured_min_wall_mils"] == 25.49, (
        "25.49 still clears the 25.20 mil minimum wall, so only the rounded "
        "concentricity ratio separates this lot from the conforming one"
    )

    rework_lot(api, lot["id"])
    rewound = read_lot(api, lot["id"])
    assert_lot_dimensions(rewound, "STRANDED", "PENDING")
    assert rewound["rework_count"] == 1, "the condemned lot gets another attempt"
