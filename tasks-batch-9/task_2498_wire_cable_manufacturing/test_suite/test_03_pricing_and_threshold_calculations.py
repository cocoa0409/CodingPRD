"""Derived money, derived strings and derived verdicts.

Everything asserted here is a figure the server computes rather than a figure a
caller supplies: the quote breakdown, the surface print, the exposure ledger,
the electrical verdicts and the inspection cadence arithmetic.
"""

import pytest

from test_helpers import (
    BILLING,
    CERT_OFFICER,
    CLERK,
    QE_TESTER,
    advance_lot_to_extruded,
    create_customer_order_payload,
    create_draft_product,
    create_factory_inspection_payload,
    create_insulation_compound_payload,
    create_listing_certification_payload,
    create_lot,
    create_metal_quote,
    create_qualified_compound,
    create_reel,
    create_released_product,
    current_order_version,
    get_success_data,
    read_customer,
    read_certification,
    read_lot,
    setup_baseline,
    setup_definitions_and_rod,
    setup_released_lot,
    setup_staged_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_booked_order_reports_the_five_step_quote_breakdown(api):
    """The quote is not one number but five, and each intermediate is visible on the
    order so the customer can see where the metal ends and the conversion begins.

    PRD 3.5: "Otherwise it is the SKU's `conductor_lbs_per_kft` multiplied by the
    difference between `quoted_metal_price_usd_per_lb` and a fixed base metal
    price — three dollars per pound for a `COPPER` conductor and one dollar per
    pound for an `ALUMINUM` conductor."

    PRD 3.5: "**Step five totals the quote:** `quoted_total_usd` is
    `quoted_subtotal_usd` plus `quoted_cut_fee_usd` plus `quoted_surcharge_usd`,
    rounded half up to two decimals."

    Design: Corner/calculations/order_quote_totals_computed_from_pass_through_and_tier
    """
    world = setup_baseline(api)
    order = world["order"]

    assert order["quoted_metal_price_usd_per_lb"] == pytest.approx(4.1000, abs=0.00005), (
        "the 2026-07-30 copper settlement is the latest on or before the order date"
    )
    assert order["quoted_unit_price_usd_per_kft"] == pytest.approx(106.7800, abs=0.00005), (
        "85.00 conversion plus 19.8 lbs/kft x (4.1000 - 3.00 copper base) = 21.78"
    )
    assert order["quoted_subtotal_usd"] == pytest.approx(533.90, abs=0.01), (
        "106.7800 extended over 5.0 thousand feet"
    )
    assert order["quoted_cut_fee_usd"] == pytest.approx(0.00, abs=0.01), (
        "a bulk order carries no cut fee"
    )
    assert order["quoted_surcharge_usd"] == pytest.approx(10.68, abs=0.01), (
        "533.90 is below five thousand dollars, so the surcharge rate is two percent"
    )
    assert order["quoted_total_usd"] == pytest.approx(544.58, abs=0.01), (
        "533.90 + 0.00 + 10.68"
    )


def test_the_surface_print_and_the_heat_trace_string_are_composed_token_by_token(api):
    """Two strings in this domain are assembled rather than typed, and both are
    compared later for exact equality.

    PRD 3.4: "A SKU listed under a UL file numbered `E12345`, sized `12`, rated
    `THHN`, at 90 degrees and 600 volts therefore prints as
    `UL E12345 12AWG THHN 90C 600V`."

    PRD 3.6: "The lot's `traceability_code` is composed as the rod lot's
    `heat_number`, then a single hyphen, then the lot's own `lot_code`, so that a
    reel of finished wire can always be walked back to the heat it was drawn from."

    Design: Corner/calculations/marking_text_and_traceability_code_are_composed_exactly
    """
    world = setup_baseline(api, with_order=False)
    assert world["product"]["required_marking_text"] == "UL E12345 12AWG THHN 90C 600V", (
        "agency, file number, size with AWG appended, rating, temperature with C, "
        "voltage with V, single spaces and no trailing space"
    )

    big_cable = create_draft_product(
        api, world["insulation"]["id"], world["certification"]["id"],
        product_code="MV105-4/0-CU", awg_size="4/0", application_rating="MV_105",
        voltage_class="MV_35KV", temp_rating_c=105, insulation_thickness_mils=345.0,
        conductor_lbs_per_kft=690.0, base_target_kft=8.0,
    )
    assert big_cable["required_marking_text"] == "UL E12345 4/0AWG MV_105 105C 35000V", (
        "the size label is printed as the plant writes it and the derived voltage "
        "rating supplies the volts token"
    )

    lot = create_lot(api, world, lot_code="LOT-TRACE", planned_length_ft=1000)
    assert lot["traceability_code"] == "H-77Q-LOT-TRACE", (
        f"heat H-77Q joined to LOT-TRACE by one hyphen, got {lot['traceability_code']!r}"
    )


def test_quote_selection_reads_only_this_metal_and_never_a_later_settlement(api):
    """Metal price selection is a ranked lookup restricted to the SKU's own metal
    and to settlements no later than the order date.

    PRD 3.5: "The candidate quotes are those whose `metal` equals the SKU's
    `conductor_metal` and whose `effective_date` is on or before `order_date`; no
    status filter applies, because settlement prices are immutable."

    PRD 3.5: "If there is no candidate at all the order is refused outright with
    `ERR_NO_METAL_QUOTE` and nothing is created."

    Design: Corner/calculations/quote_selection_ignores_future_dates_and_other_metals
    """
    world = setup_baseline(api, with_order=False)
    create_metal_quote(api, metal="COPPER", effective_date="2026-07-28",
                       settlement_price_usd_per_lb=3.90)
    create_metal_quote(api, metal="COPPER", effective_date="2026-08-05",
                       settlement_price_usd_per_lb=5.00)
    create_metal_quote(api, metal="ALUMINUM", effective_date="2026-07-30",
                       settlement_price_usd_per_lb=1.50)

    on_date = validate_success(
        api.create_customer_order(
            create_customer_order_payload(
                world["customer"]["id"], world["product"]["id"],
                order_number="SO-SEL-1", order_date="2026-07-30",
            ),
            BILLING,
        ),
        201,
    )
    assert on_date["quoted_metal_price_usd_per_lb"] == pytest.approx(4.1000, abs=0.00005), (
        "the 2026-08-05 copper settlement is later than the order date and the "
        "1.50 aluminium settlement is the wrong metal"
    )

    day_before = validate_success(
        api.create_customer_order(
            create_customer_order_payload(
                world["customer"]["id"], world["product"]["id"],
                order_number="SO-SEL-2", order_date="2026-07-29",
            ),
            BILLING,
        ),
        201,
    )
    assert day_before["quoted_metal_price_usd_per_lb"] == pytest.approx(3.9000, abs=0.00005), (
        "on 2026-07-29 the newest eligible copper settlement is the 2026-07-28 one"
    )
    assert day_before["quoted_unit_price_usd_per_kft"] == pytest.approx(102.8200, abs=0.00005), (
        "85.00 plus 19.8 x (3.9000 - 3.00)"
    )

    validate_error(
        api.create_customer_order(
            create_customer_order_payload(
                world["customer"]["id"], world["product"]["id"],
                order_number="SO-SEL-3", order_date="2026-07-27",
            ),
            BILLING,
        ),
        "ERR_NO_METAL_QUOTE", 422,
    )
    rows, meta = validate_paginated(api.list_customer_orders(BILLING))
    assert meta["total_count"] == 2, "the refused booking created nothing"


def test_exposure_counts_invoiced_receivables_but_every_outstanding_deposit(api):
    """The two halves of exposure are gathered differently: staged deliveries owe
    nothing yet, while their reel deposits are already at risk.

    PRD 3.5: "That evaluation is the same one used everywhere else: `open_ar_usd`
    is the sum of `invoice_amount_usd` across the account's shipments whose own
    status is `INVOICED`, with staged-but-uninvoiced shipments contributing
    nothing; `reel_deposit_balance_usd` carries the deposits still outstanding on
    reels the account holds, meaning reels currently at `SHIPPED` or
    `RETURN_PENDING`; and `credit_exposure_usd` is `open_ar_usd` plus
    `reel_deposit_balance_usd` minus `credit_memo_balance_usd`, rounded half up
    to two decimals."

    Design: Corner/calculations/credit_exposure_counts_invoiced_shipments_only
    """
    world = setup_baseline(
        api, order_overrides={"order_number": "SO-EXP", "ordered_kft": 10.0}
    )
    get_success_data(api.price_lock_customer_order(world["order"]["id"], BILLING))
    world, lot_a, reel_a, shipment_a = setup_staged_shipment(api, world=world)

    world, lot_b = setup_released_lot(
        api, world=world,
        lot_overrides={"lot_code": "LOT-B", "line_code": "EXT-2"},
    )
    reel_b = create_reel(api, reel_serial="R-002")
    get_success_data(
        api.load_reel(
            reel_b["id"],
            {"lot_id": lot_b["id"], "load_length_ft": 5000,
             "occupancy_start_at": "2026-08-03T00:00:00Z"},
            CLERK,
        )
    )
    shipment_b = get_success_data(
        api.create_shipment(
            {"order_id": world["order"]["id"], "lot_id": lot_b["id"],
             "reel_id": reel_b["id"], "shipped_length_ft": 5000,
             "ship_date": "2026-08-01", "cuts_count": 0,
             "expected_order_version": current_order_version(api, world["order"]["id"])},
            CLERK,
        )
    )
    assert shipment_b["status"] == "STAGED"

    staged_only = read_customer(api, world["customer"]["id"])
    assert staged_only["open_ar_usd"] == pytest.approx(0.00, abs=0.01), (
        "neither delivery has been billed yet"
    )
    assert staged_only["reel_deposit_balance_usd"] == pytest.approx(900.00, abs=0.01), (
        "both 450.00 deposits are outstanding on reels the account holds"
    )
    assert staged_only["credit_exposure_usd"] == pytest.approx(900.00, abs=0.01)

    get_success_data(api.invoice_shipment(shipment_a["id"], BILLING))
    after_one = read_customer(api, world["customer"]["id"])
    assert after_one["open_ar_usd"] == pytest.approx(544.58, abs=0.01), (
        "only the invoiced delivery contributes receivable"
    )
    assert after_one["reel_deposit_balance_usd"] == pytest.approx(900.00, abs=0.01), (
        "the invoiced reel moved to RETURN_PENDING and its deposit is still out"
    )
    assert after_one["credit_memo_balance_usd"] == pytest.approx(0.00, abs=0.01)
    assert after_one["credit_exposure_usd"] == pytest.approx(1444.58, abs=0.01), (
        "544.58 receivable plus 900.00 of deposits minus no credit memo"
    )
    assert after_one["status"] == "ACTIVE"


def test_the_base_metal_deduction_is_three_dollars_for_copper_and_one_for_aluminium(api):
    """Pass-through prices the *movement* of metal away from a fixed base, and the
    base is a different constant for each conductor metal.

    PRD 3.5: "Note that the difference may be negative when the market sits below
    the base, in which case pass-through reduces the price."

    Design: Corner/calculations/base_metal_price_constant_is_keyed_by_conductor_metal
    """
    world = setup_baseline(api, with_order=False)
    create_metal_quote(api, metal="ALUMINUM", effective_date="2026-07-30",
                       settlement_price_usd_per_lb=1.50)
    create_metal_quote(api, metal="COPPER", effective_date="2026-07-20",
                       settlement_price_usd_per_lb=2.50)

    aluminium_sku = create_released_product(
        api, world["insulation"]["id"], world["certification"]["id"],
        product_code="THHN-2-AL", awg_size="2", conductor_metal="ALUMINUM",
        conductor_lbs_per_kft=19.8, base_target_kft=30.0,
    )

    copper_order = validate_success(
        api.create_customer_order(
            create_customer_order_payload(
                world["customer"]["id"], world["product"]["id"],
                order_number="SO-CU", order_date="2026-07-30",
            ),
            BILLING,
        ),
        201,
    )
    aluminium_order = validate_success(
        api.create_customer_order(
            create_customer_order_payload(
                world["customer"]["id"], aluminium_sku["id"],
                order_number="SO-AL", order_date="2026-07-30",
            ),
            BILLING,
        ),
        201,
    )
    assert copper_order["quoted_unit_price_usd_per_kft"] == pytest.approx(
        106.7800, abs=0.00005
    ), "copper deducts a 3.00 base from a 4.1000 market"
    assert aluminium_order["quoted_unit_price_usd_per_kft"] == pytest.approx(
        94.9000, abs=0.00005
    ), "aluminium deducts a 1.00 base from a 1.5000 market: 19.8 x 0.50 = 9.90"

    below_base = validate_success(
        api.create_customer_order(
            create_customer_order_payload(
                world["customer"]["id"], world["product"]["id"],
                order_number="SO-CU-LOW", order_date="2026-07-20",
            ),
            BILLING,
        ),
        201,
    )
    assert below_base["quoted_metal_price_usd_per_lb"] == pytest.approx(2.5000, abs=0.00005)
    assert below_base["quoted_unit_price_usd_per_kft"] == pytest.approx(
        75.1000, abs=0.00005
    ), "a 2.5000 copper market sits below the 3.00 base, so pass-through is -9.90"


def test_spark_and_high_potential_verdicts_read_their_declared_limit_tables(api):
    """A spark row tolerates no faults at all, and a high-potential row is judged
    against the kilovolts its own voltage class demands.

    PRD 3.7: "A `SPARK` row passes when `faults_detected` is at most the permitted
    maximum of zero — that is, only a completely fault-free pass qualifies — and
    fails otherwise."

    PRD 3.7: "A `HIPOT` row fails immediately when `breakdown_detected` is true;
    otherwise it passes when `test_voltage_kv` is at least the voltage the SKU's
    `voltage_class` demands, which is 2.5 kilovolts for `LV_600`, 15.0 kilovolts
    for `MV_5KV`, 35.0 kilovolts for `MV_15KV` and 70.0 kilovolts for `MV_35KV`,
    and fails when the applied voltage falls short."

    Design: Corner/calculations/spark_and_hipot_thresholds_come_from_their_constant_maps
    """
    world = setup_definitions_and_rod(api)
    lv_lot = create_lot(api, world, lot_code="LOT-LV", planned_length_ft=2000)
    advance_lot_to_extruded(api, lv_lot["id"])

    faulted = get_success_data(
        api.create_cable_test(
            lv_lot["id"], {"test_type": "SPARK", "faults_detected": 1, "duration_sec": 60},
            QE_TESTER,
        )
    )
    assert faulted["result"] == "FAIL", "one fault is one too many"

    under_volts = get_success_data(
        api.create_cable_test(
            lv_lot["id"], {"test_type": "HIPOT", "test_voltage_kv": 2.4,
                           "breakdown_detected": False, "duration_sec": 300},
            QE_TESTER,
        )
    )
    assert under_volts["result"] == "FAIL", "2.4 kV falls short of the 2.5 kV LV_600 demand"

    broke_down = get_success_data(
        api.create_cable_test(
            lv_lot["id"], {"test_type": "HIPOT", "test_voltage_kv": 2.5,
                           "breakdown_detected": True, "duration_sec": 300},
            QE_TESTER,
        )
    )
    assert broke_down["result"] == "FAIL", "a breakdown fails regardless of applied voltage"

    clean_spark = get_success_data(
        api.create_cable_test(
            lv_lot["id"], {"test_type": "SPARK", "faults_detected": 0, "duration_sec": 60},
            QE_TESTER,
        )
    )
    assert clean_spark["result"] == "PASS"
    assert read_lot(api, lv_lot["id"])["process_state"] == "EXTRUDED", (
        "the latest high-potential row still reads FAIL, so nothing is promoted"
    )

    at_the_limit = get_success_data(
        api.create_cable_test(
            lv_lot["id"], {"test_type": "HIPOT", "test_voltage_kv": 2.5,
                           "breakdown_detected": False, "duration_sec": 300},
            QE_TESTER,
        )
    )
    assert at_the_limit["result"] == "PASS", "exactly 2.5 kV meets the LV_600 demand"
    assert read_lot(api, lv_lot["id"])["process_state"] == "TESTED"

    mv_compound = create_qualified_compound(
        api,
        create_insulation_compound_payload(
            compound_code="EPR-105-INS", temp_rating_c=105, max_voltage_v=15000,
            flame_test="FT4", filler_pct=8.0,
        ),
    )
    mv_sku = create_released_product(
        api, mv_compound["id"], world["certification"]["id"],
        product_code="MV105-2-CU", awg_size="2", application_rating="MV_105",
        voltage_class="MV_15KV", temp_rating_c=105,
        insulation_thickness_mils=175.0, conductor_lbs_per_kft=205.0,
        base_target_kft=20.0,
    )
    mv_lot = create_lot(
        api, dict(world, product=mv_sku), lot_code="LOT-MV",
        planned_length_ft=2000, line_code="EXT-2",
    )
    advance_lot_to_extruded(
        api, mv_lot["id"],
        extrusion_overrides={"measured_min_wall_mils": 160.0,
                             "measured_max_wall_mils": 175.0,
                             "measured_avg_od_mm": 22.0,
                             "surface_marking_text": None},
    )
    mv_short = get_success_data(
        api.create_cable_test(
            mv_lot["id"], {"test_type": "HIPOT", "test_voltage_kv": 34.9,
                           "breakdown_detected": False, "duration_sec": 300},
            QE_TESTER,
        )
    )
    assert mv_short["result"] == "FAIL", "MV_15KV demands 35.0 kV, so 34.9 kV falls short"
    mv_ok = get_success_data(
        api.create_cable_test(
            mv_lot["id"], {"test_type": "HIPOT", "test_voltage_kv": 35.0,
                           "breakdown_detected": False, "duration_sec": 300},
            QE_TESTER,
        )
    )
    assert mv_ok["result"] == "PASS", "exactly 35.0 kV meets the MV_15KV demand"


def test_the_volatility_surcharge_rounds_a_half_cent_upward(api):
    """The surcharge lands on an exact half cent, which is where a truncating
    implementation and a half-up implementation part company.

    PRD 2.5: "Every monetary amount in this service is carried to **2 decimal
    places and rounded half up**."

    PRD 3.5: "`quoted_surcharge_usd` is the subtotal multiplied by that rate,
    rounded half up to two decimals, and the tier is chosen from the
    already-rounded subtotal."

    Design: Corner/calculations/surcharge_rounds_half_up_on_an_exact_half_cent
    """
    world = setup_baseline(api, with_order=False)

    two_percent = validate_success(
        api.create_customer_order(
            create_customer_order_payload(
                world["customer"]["id"], world["product"]["id"],
                order_number="SO-HALF-1", ordered_kft=1.0,
                conversion_price_usd_per_kft=78.47,
            ),
            BILLING,
        ),
        201,
    )
    assert two_percent["quoted_unit_price_usd_per_kft"] == pytest.approx(
        100.2500, abs=0.00005
    ), "78.47 conversion plus 21.78 pass-through"
    assert two_percent["quoted_subtotal_usd"] == pytest.approx(100.25, abs=0.005)
    assert two_percent["quoted_surcharge_usd"] == pytest.approx(2.01, abs=0.005), (
        "100.25 x 0.020 is exactly 2.005, which rounds half up to 2.01 and not down "
        "to 2.00"
    )
    assert two_percent["quoted_total_usd"] == pytest.approx(102.26, abs=0.005)

    one_and_a_half_percent = validate_success(
        api.create_customer_order(
            create_customer_order_payload(
                world["customer"]["id"], world["product"]["id"],
                order_number="SO-HALF-2", ordered_kft=50.0,
                conversion_price_usd_per_kft=78.24,
            ),
            BILLING,
        ),
        201,
    )
    assert one_and_a_half_percent["quoted_subtotal_usd"] == pytest.approx(5001.00, abs=0.005), (
        "100.0200 extended over 50.0 thousand feet"
    )
    assert one_and_a_half_percent["quoted_surcharge_usd"] == pytest.approx(75.02, abs=0.005), (
        "a subtotal of 5001.00 sits in the one-and-a-half-percent tier: 75.015 "
        "rounds half up to 75.02"
    )
    assert one_and_a_half_percent["quoted_total_usd"] == pytest.approx(5076.02, abs=0.005)


def test_the_inspection_cadence_guard_counts_whole_days_and_admits_exactly_sixty(api):
    """The agency's anti-stuffing rule is a strict whole-day comparison against the
    file's latest visit, and the cadence fields are pure date arithmetic.

    PRD 3.3: "A visit dated strictly fewer than 60 days after the previous one is
    rejected with `ERR_INSPECTION_WINDOW_CONFLICT`; a visit falling exactly 60
    days later is accepted."

    PRD 3.3: "`next_inspection_due_date` becomes that `inspection_date` advanced
    by `inspection_interval_days` whole calendar days."

    Design: Corner/calculations/inspection_cadence_gap_is_strict_and_counted_in_whole_days
    """
    cert = validate_success(
        api.create_listing_certification(
            create_listing_certification_payload(
                initial_listing_date="2026-01-01", inspection_interval_days=90
            ),
            CERT_OFFICER,
        ),
        201,
    )
    first = validate_success(
        api.create_factory_inspection(
            cert["id"],
            create_factory_inspection_payload(
                inspection_date="2026-03-01", inspector_code="INS-1",
                findings_count=0, outcome="PASS",
            ),
            CERT_OFFICER,
        ),
        201,
    )
    assert first["status"] == "CLOSED", "a PASS row is born closed"
    assert first["corrective_action_due_date"] is None, "a PASS carries no corrective action"
    after_first = read_certification(api, cert["id"])
    assert after_first["status"] == "ACTIVE", "the initial listing audit activates the file"
    assert after_first["last_inspection_date"] == "2026-03-01"
    assert after_first["next_inspection_due_date"] == "2026-05-30", (
        "2026-03-01 advanced by 90 whole calendar days"
    )
    assert after_first["open_variation_count"] == 0

    validate_error(
        api.create_factory_inspection(
            cert["id"],
            create_factory_inspection_payload(
                inspection_date="2026-04-29", inspector_code="INS-2",
                findings_count=0, outcome="PASS",
            ),
            CERT_OFFICER,
        ),
        "ERR_INSPECTION_WINDOW_CONFLICT", 409,
    )

    get_success_data(
        api.create_factory_inspection(
            cert["id"],
            create_factory_inspection_payload(
                inspection_date="2026-04-30", inspector_code="INS-3",
                findings_count=0, outcome="PASS",
            ),
            CERT_OFFICER,
        )
    )
    after_second = read_certification(api, cert["id"])
    assert after_second["status"] == "ACTIVE", (
        "a PASS on an already active file refreshes cadence without moving status"
    )
    assert after_second["last_inspection_date"] == "2026-04-30"
    assert after_second["next_inspection_due_date"] == "2026-07-29"

    validate_error(
        api.create_factory_inspection(
            cert["id"],
            create_factory_inspection_payload(
                inspection_date="2026-06-28", inspector_code="INS-4",
                findings_count=1, outcome="VARIATION",
            ),
            CERT_OFFICER,
        ),
        "ERR_INSPECTION_WINDOW_CONFLICT", 409,
    )

    variation = validate_success(
        api.create_factory_inspection(
            cert["id"],
            create_factory_inspection_payload(
                inspection_date="2026-06-29", inspector_code="INS-5",
                findings_count=3, outcome="VARIATION",
            ),
            CERT_OFFICER,
        ),
        201,
    )
    assert variation["status"] == "OPEN", "a variation row is born open"
    assert variation["corrective_action_due_date"] == "2026-07-29", (
        "the corrective window is the inspection date advanced by 30 calendar days"
    )
    after_variation = read_certification(api, cert["id"])
    assert after_variation["status"] == "VARIATION_NOTICE"
    assert after_variation["open_variation_count"] == 1
    assert after_variation["next_inspection_due_date"] == "2026-09-27"
