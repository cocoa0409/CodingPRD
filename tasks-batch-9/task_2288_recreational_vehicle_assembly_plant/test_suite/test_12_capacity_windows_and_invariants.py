"""Contended booths and line days, and the quantities the plant conserves.

Every test drives the plant through PRD §4 endpoints only and starts from an
empty database.
"""
from test_helpers import (
    CANON_OPTION_SPECS,
    ApiErrorId,
    advance_clock,
    assert_cents,
    assert_hours,
    assert_lot_counter_invariant,
    build_canon_kit,
    canon_option_ids,
    create_chassis_receipt,
    create_component_lot,
    create_dealer,
    create_floor_plan,
    create_option_item,
    create_order,
    create_production_line,
    create_supplier,
    create_test_booth,
    decide_funding,
    inject_delivered_unit,
    install_pieces,
    make_dealer_principal_headers,
    match_chassis,
    read_build,
    read_dealer,
    read_lot,
    read_order,
    release_to_line,
    request_funding,
    reserve_slot,
    schedule_booth_inspection,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    walk_build,
)

WATER_TEST_WINDOW_START = "2026-08-05T09:00:00Z"
WATER_TEST_WINDOW_END = "2026-08-05T10:00:00Z"


def _create_class_a_floor_plan():
    """FP-3410: the 34 ft Class A coach on a 242 in wheelbase."""
    return create_floor_plan(
        model_code="FP-3410",
        chassis_class="CLASS_A",
        length_ft=34,
        base_msrp_cents=18500000,
        base_station_hours=46.00,
        base_dry_weight_lbs=22400,
        gvwr_lbs=26000,
        required_wheelbase_in=242,
        electrical_service_amps=50,
        fresh_water_capacity_gal=90,
    )


def _create_big_dealer():
    """D-BIG: a 1500 bp dealer with a credit line far above one coach."""
    return create_dealer(
        dealer_code="D-BIG",
        region="WEST",
        allocation_share_bp=1500,
        floor_plan_credit_limit_cents=100000000,
        goodwill_budget_cents=500000,
    )


def _water_test_payload(build_id, booth_id, window_start, window_end):
    return {
        "unit_build_id": build_id,
        "inspection_type": "WATER_TEST",
        "test_booth_id": booth_id,
        "window_start": window_start,
        "window_end": window_end,
    }


def _five_option_line_b_plant():
    """FP-3410, the five options, D-BIG and LINE-B as the plant's only line."""
    floor_plan = _create_class_a_floor_plan()
    options = {spec["option_code"]: create_option_item(**spec) for spec in CANON_OPTION_SPECS}
    dealer = _create_big_dealer()
    line = create_production_line(
        line_code="LINE-B",
        chassis_class_supported="CLASS_A",
        daily_station_hour_capacity=142.48,
        max_units_per_day=4,
    )
    return {"floor_plan": floor_plan, "options": options, "dealer": dealer, "line": line}


def _five_option_ids(plant):
    options = plant["options"]
    return [
        options["OPT-AC2"]["id"],
        options["OPT-WASH"]["id"],
        options["OPT-SOLAR"]["id"],
        options["OPT-INV"]["id"],
        options["OPT-BATT"]["id"],
    ]


def _three_submitted_five_option_orders(plant):
    dealer_id = plant["dealer"]["id"]
    orders = []
    for requested_delivery_date in (
        "2026-09-20T00:00:00Z",
        "2026-09-21T00:00:00Z",
        "2026-09-22T00:00:00Z",
    ):
        order = create_order(
            dealer_id,
            plant["floor_plan"]["id"],
            order_type="STOCK",
            selected_option_ids=_five_option_ids(plant),
            requested_delivery_date=requested_delivery_date,
        )
        orders.append(submit_order(order["id"], dealer_id))
    return orders


def _slot_payload(line_id, slot_date, expected_version):
    return {
        "line_id": line_id,
        "slot_date": slot_date,
        "expected_unit_order_version": expected_version,
    }


def _build_at_appliance_install_with_a_forty_piece_lot():
    """A Class A build standing at APPLIANCE_INSTALL with 25 of 40 pieces in."""
    chassis_supplier = create_supplier(
        supplier_code="SUP-CH",
        name="Cascade Chassis Works",
        component_categories=["CHASSIS"],
    )
    appliance_supplier = create_supplier(
        supplier_code="SUP-APP",
        name="Northline Appliance",
        component_categories=["APPLIANCE"],
    )
    floor_plan = _create_class_a_floor_plan()
    washer = create_option_item(
        option_code="OPT-WASH",
        category="APPLIANCE",
        install_station="APPLIANCE_INSTALL",
        price_cents=245500,
        weight_lbs=180,
        added_station_hours=3.00,
        amp_draw=12,
        water_demand_gal=0,
    )
    dealer = _create_big_dealer()
    line = create_production_line(
        line_code="LINE-A",
        chassis_class_supported="CLASS_A",
        daily_station_hour_capacity=240.00,
        max_units_per_day=4,
    )
    create_chassis_receipt(
        chassis_supplier["id"],
        chassis_serial="CH-0001",
        chassis_class="CLASS_A",
        gvwr_lbs=26000,
        wheelbase_in=242,
    )
    lot = create_component_lot(
        appliance_supplier["id"],
        part_number="WH-6G-2026",
        lot_code="L-2211",
        category="APPLIANCE",
        quantity_received=40,
    )
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="SOLD",
        selected_option_ids=[washer["id"]],
        requested_delivery_date="2026-09-15T00:00:00Z",
    )
    order = submit_order(order["id"], dealer["id"])
    reserve_slot(order["id"], line["id"], "2026-08-05T00:00:00Z", order["version"])
    match_chassis(order["id"])
    build = release_to_line(order["id"])
    walk_build(
        build["id"],
        [
            ("SIDEWALL_LAM", 1.00),
            ("ROOF_SET", 1.00),
            ("ROUGH_IN", 1.00),
            ("APPLIANCE_INSTALL", 1.00),
        ],
    )
    first_installation = install_pieces(build["id"], lot["id"], "APPLIANCE_INSTALL", 25)
    return {
        "dealer": dealer,
        "order": order,
        "build": build,
        "lot": lot,
        "first_installation": first_installation,
    }


def _installation_payload(build_id, lot_id, quantity):
    return {
        "unit_build_id": build_id,
        "component_lot_id": lot_id,
        "station": "APPLIANCE_INSTALL",
        "quantity": quantity,
    }


def _funded_canonical_order_at_one_hundred_eighty_days():
    """The canonical STOCK coach funded on day zero, read 180 days later."""
    kit = build_canon_kit(with_chassis=False, with_booth=False, with_lot=False)
    dealer_id = kit["dealer"]["id"]
    order = create_order(
        dealer_id,
        kit["floor_plan"]["id"],
        order_type="STOCK",
        selected_option_ids=canon_option_ids(kit),
        requested_delivery_date="2026-09-15T00:00:00Z",
    )
    submit_order(order["id"], dealer_id)
    request_funding(order["id"], dealer_id)
    decide_funding(order["id"], "APPROVED")
    advance_clock("2027-01-28T00:00:00Z")
    return kit, read_order(order["id"])


def test_a_window_starting_one_minute_before_the_buffered_end_conflicts_on_a_single_bay_booth(
    api, inspector_headers
):
    """PRD §3.6: "The **effective footprint** of any reservation runs from its `window_start` inclusive to its `window_end` plus the booth's `turnaround_minutes` exclusive — the dry-out period after a water test is as much an occupancy as the test itself."

    PRD §3.6: "Count every existing inspection on that booth whose `status` is `SCHEDULED` or `COMPLETED` that conflicts with the request; if that count plus one would exceed the booth's `bay_count`, the reservation is rejected with `ERR_BOOTH_WINDOW_CONFLICT`."

    PRD §3.6: "Because the right edge is exclusive, a window starting exactly at a predecessor's buffered end is admitted, while one starting a single minute earlier is not; a two-bay booth admits that earlier window and refuses only a third overlapping one."

    Design: Difficulty/resource_temporal_overlap/booth_turnaround_buffer_makes_a_one_minute_early_window_conflict
    """
    floor_plan = _create_class_a_floor_plan()
    dealer = _create_big_dealer()
    booth_one_bay = create_test_booth(
        booth_code="BOOTH-1", booth_type="WATER_TEST", bay_count=1, turnaround_minutes=30
    )
    booth_two_bay = create_test_booth(
        booth_code="BOOTH-2", booth_type="WATER_TEST", bay_count=2, turnaround_minutes=30
    )
    build = inject_delivered_unit(dealer["id"], floor_plan["id"])
    first_on_one_bay = schedule_booth_inspection(
        build["id"], booth_one_bay["id"], WATER_TEST_WINDOW_START, WATER_TEST_WINDOW_END
    )
    schedule_booth_inspection(
        build["id"], booth_two_bay["id"], WATER_TEST_WINDOW_START, WATER_TEST_WINDOW_END
    )

    refused = api.create_quality_inspection(
        _water_test_payload(
            build["id"], booth_one_bay["id"], "2026-08-05T10:29:00Z", "2026-08-05T11:00:00Z"
        ),
        inspector_headers,
    )
    validate_error(refused, ApiErrorId.ERR_BOOTH_WINDOW_CONFLICT)
    assert refused.status_code == 409

    admitted = validate_success(
        api.create_quality_inspection(
            _water_test_payload(
                build["id"], booth_two_bay["id"], "2026-08-05T10:29:00Z", "2026-08-05T11:00:00Z"
            ),
            inspector_headers,
        ),
        201,
    )
    assert admitted["status"] == "SCHEDULED"
    assert admitted["test_booth_id"] == booth_two_bay["id"]

    rows, meta = validate_paginated(
        api.list_quality_inspections(
            inspector_headers, params={"test_booth_id": booth_one_bay["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first_on_one_bay["id"]

    _two_bay_rows, two_bay_meta = validate_paginated(
        api.list_quality_inspections(
            inspector_headers, params={"test_booth_id": booth_two_bay["id"]}
        )
    )
    assert two_bay_meta["total_count"] == 2

    on_the_buffered_edge = validate_success(
        api.create_quality_inspection(
            _water_test_payload(
                build["id"], booth_one_bay["id"], "2026-08-05T10:30:00Z", "2026-08-05T11:30:00Z"
            ),
            inspector_headers,
        ),
        201,
    )
    assert on_the_buffered_edge["status"] == "SCHEDULED"
    assert on_the_buffered_edge["test_booth_id"] == booth_one_bay["id"]


def test_a_two_bay_booth_admits_a_second_overlapping_window_and_refuses_a_third(
    api, inspector_headers
):
    """PRD §3.6: "Count every existing inspection on that booth whose `status` is `SCHEDULED` or `COMPLETED` that conflicts with the request; if that count plus one would exceed the booth's `bay_count`, the reservation is rejected with `ERR_BOOTH_WINDOW_CONFLICT`."

    PRD §3.6: "Because the right edge is exclusive, a window starting exactly at a predecessor's buffered end is admitted, while one starting a single minute earlier is not; a two-bay booth admits that earlier window and refuses only a third overlapping one."

    PRD §3.6: "Two reservations conflict when each one's start falls strictly before the other one's effective end."

    Design: Difficulty/resource_temporal_overlap/booth_turnaround_buffer_makes_a_one_minute_early_window_conflict
    """
    floor_plan = _create_class_a_floor_plan()
    dealer = _create_big_dealer()
    booth_two_bay = create_test_booth(
        booth_code="BOOTH-2", booth_type="WATER_TEST", bay_count=2, turnaround_minutes=30
    )
    build = inject_delivered_unit(dealer["id"], floor_plan["id"])
    schedule_booth_inspection(
        build["id"], booth_two_bay["id"], WATER_TEST_WINDOW_START, WATER_TEST_WINDOW_END
    )

    second_bay = validate_success(
        api.create_quality_inspection(
            _water_test_payload(
                build["id"], booth_two_bay["id"], "2026-08-05T10:29:00Z", "2026-08-05T11:00:00Z"
            ),
            inspector_headers,
        ),
        201,
    )
    assert second_bay["status"] == "SCHEDULED"

    third_overlap = api.create_quality_inspection(
        _water_test_payload(
            build["id"], booth_two_bay["id"], "2026-08-05T09:30:00Z", "2026-08-05T10:30:00Z"
        ),
        inspector_headers,
    )
    validate_error(third_overlap, ApiErrorId.ERR_BOOTH_WINDOW_CONFLICT)
    assert third_overlap.status_code == 409

    _rows, meta = validate_paginated(
        api.list_quality_inspections(
            inspector_headers, params={"test_booth_id": booth_two_bay["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_two_units_exactly_fill_the_line_day_hours_bucket_and_the_third_is_refused_on_hours(
    api, scheduler_headers
):
    """PRD §3.3: "Only then is the hours ceiling checked — if the summed committed hours plus this order's `required_station_hours` would exceed the line's `daily_station_hour_capacity`, the request fails with `ERR_LINE_DAY_HOURS_EXCEEDED`. The hours ceiling is inclusive: a total landing exactly on the line's daily capacity is admitted, and one hundredth of an hour more is refused."

    PRD §3.3: "The unit ceiling is checked first — if the count plus one would exceed the line's `max_units_per_day`, the request fails with `ERR_LINE_DAY_UNIT_CAP_EXCEEDED`."

    PRD §3.3: "The created slot is stamped `RESERVED` with `station_hours_committed` copied from the order's `required_station_hours` at the moment of reservation, a one-based `sequence_position` equal to the day bucket's occupied-unit count plus one (which is the coach's build order on that line that day), and an `expires_at` exactly 72 hours after the slot's `created_at`."

    PRD §3.3: "The dealer's `allocation_slots_reserved` — the count of that dealer's slots in `RESERVED` or `CONSUMED` — and `allocation_hours_consumed` are recomputed, and the order's `version` increments."

    Design: Difficulty/resource_temporal_overlap/line_day_hours_bucket_admits_exact_equality_then_overflows
    """
    plant = _five_option_line_b_plant()
    first, second, third = _three_submitted_five_option_orders(plant)
    line_id = plant["line"]["id"]
    slot_date = "2026-09-14T00:00:00Z"

    first_slot = validate_success(
        api.reserve_production_slot(
            first["id"], _slot_payload(line_id, slot_date, first["version"]), scheduler_headers
        ),
        201,
    )
    assert_hours(first_slot["station_hours_committed"], "71.24")
    assert first_slot["sequence_position"] == 1
    assert first_slot["status"] == "RESERVED"

    second_slot = validate_success(
        api.reserve_production_slot(
            second["id"], _slot_payload(line_id, slot_date, second["version"]), scheduler_headers
        ),
        201,
    )
    assert_hours(second_slot["station_hours_committed"], "71.24")
    assert second_slot["sequence_position"] == 2
    assert second_slot["status"] == "RESERVED"

    refused = api.reserve_production_slot(
        third["id"], _slot_payload(line_id, slot_date, third["version"]), scheduler_headers
    )
    error = validate_error(refused, ApiErrorId.ERR_LINE_DAY_HOURS_EXCEEDED)
    assert refused.status_code == 409
    # Two units against a ceiling of four leaves the unit cap untouched.
    assert error["error_id"] != ApiErrorId.ERR_LINE_DAY_UNIT_CAP_EXCEEDED

    assert read_order(third["id"])["status"] == "CONFIG_VALIDATED"
    _rows, meta = validate_paginated(
        api.list_production_slots(scheduler_headers, params={"unit_order_id": third["id"]})
    )
    assert meta["total_count"] == 0

    dealer = read_dealer(plant["dealer"]["id"])
    assert dealer["allocation_slots_reserved"] == 2
    assert_hours(dealer["allocation_hours_consumed"], "142.48")

    assert first_slot["expires_at"].startswith("2026-08-04T00:00:00")


def test_a_full_line_day_bucket_does_not_block_the_next_calendar_day_on_the_same_line(
    api, scheduler_headers
):
    """PRD §3.3: "The **line-day ceiling** looks at one calendar-day bucket on one line. Day buckets never overlap; a slot occupies a whole day keyed by `slot_date`, not an instant range."

    PRD §3.3: "Only then is the hours ceiling checked — if the summed committed hours plus this order's `required_station_hours` would exceed the line's `daily_station_hour_capacity`, the request fails with `ERR_LINE_DAY_HOURS_EXCEEDED`. The hours ceiling is inclusive: a total landing exactly on the line's daily capacity is admitted, and one hundredth of an hour more is refused."

    PRD §3.3: "The created slot is stamped `RESERVED` with `station_hours_committed` copied from the order's `required_station_hours` at the moment of reservation, a one-based `sequence_position` equal to the day bucket's occupied-unit count plus one (which is the coach's build order on that line that day), and an `expires_at` exactly 72 hours after the slot's `created_at`."

    Design: Difficulty/resource_temporal_overlap/line_day_hours_bucket_admits_exact_equality_then_overflows
    """
    plant = _five_option_line_b_plant()
    first, second, third = _three_submitted_five_option_orders(plant)
    line_id = plant["line"]["id"]
    full_day = "2026-09-14T00:00:00Z"
    next_day = "2026-09-15T00:00:00Z"

    validate_success(
        api.reserve_production_slot(
            first["id"], _slot_payload(line_id, full_day, first["version"]), scheduler_headers
        ),
        201,
    )
    validate_success(
        api.reserve_production_slot(
            second["id"], _slot_payload(line_id, full_day, second["version"]), scheduler_headers
        ),
        201,
    )

    refused = api.reserve_production_slot(
        third["id"], _slot_payload(line_id, full_day, third["version"]), scheduler_headers
    )
    validate_error(refused, ApiErrorId.ERR_LINE_DAY_HOURS_EXCEEDED)

    third_slot = validate_success(
        api.reserve_production_slot(
            third["id"], _slot_payload(line_id, next_day, third["version"]), scheduler_headers
        ),
        201,
    )
    assert_hours(third_slot["station_hours_committed"], "71.24")
    assert third_slot["sequence_position"] == 1
    assert third_slot["status"] == "RESERVED"
    assert read_order(third["id"])["status"] == "SLOTTED"

    dealer = read_dealer(plant["dealer"]["id"])
    assert dealer["allocation_slots_reserved"] == 3
    # Three coaches of 71.24 hours all fall in the same calendar month.
    assert_hours(dealer["allocation_hours_consumed"], "213.72")


def test_lot_piece_counters_are_conserved_across_a_depleting_install_and_its_reversal(
    api, supervisor_headers
):
    """PRD §3.1: "Those three counters are an invariant, not bookkeeping: available plus installed plus quarantined always equals `quantity_received`, and every operation in §3.5 and §3.9 that moves one moves another to preserve it."

    PRD §3.5: "On success the lot's `quantity_available` decreases by the installed quantity and its `quantity_installed` increases by the same amount, conserving the piece total, and a lot whose `quantity_available` reaches exactly zero moves `AVAILABLE → DEPLETED`."

    PRD §3.5: "Reversal moves the installation `INSTALLED → REVERSED` and gives the pieces back: the lot's `quantity_installed` decreases by the installation's quantity and its `quantity_available` increases by the same amount, and a lot that had been `DEPLETED` returns `DEPLETED → AVAILABLE` once its `quantity_available` is above zero."

    Design: Difficulty/compensating_invariant/component_lot_piece_count_is_conserved_across_install_and_reverse
    """
    setup = _build_at_appliance_install_with_a_forty_piece_lot()
    build_id = setup["build"]["id"]
    lot_id = setup["lot"]["id"]

    second_installation = validate_success(
        api.create_component_installation(
            _installation_payload(build_id, lot_id, 15), supervisor_headers
        ),
        201,
    )
    reversed_installation = validate_success(
        api.reverse_installation(
            second_installation["id"],
            supervisor_headers,
            {"reversal_reason": "Wrong part revision staged at the station"},
        )
    )

    lot = read_lot(lot_id)
    assert lot["quantity_available"] == 15
    assert lot["quantity_installed"] == 25
    assert lot["quantity_quarantined"] == 0
    assert_lot_counter_invariant(lot)
    assert lot["quantity_received"] == 40
    # The lot passed through DEPLETED when the second install took the last
    # fifteen pieces and came back when they were returned.
    assert lot["status"] == "AVAILABLE"

    first = validate_success(
        api.get_component_installation(setup["first_installation"]["id"], supervisor_headers)
    )
    assert first["status"] == "INSTALLED"
    assert first["quantity"] == 25
    assert reversed_installation["status"] == "REVERSED"
    assert reversed_installation["quantity"] == 15

    _rows, meta = validate_paginated(
        api.list_component_installations(supervisor_headers, params={"component_lot_id": lot_id})
    )
    assert meta["total_count"] == 2

    build = read_build(build_id)
    assert build["current_station"] == "APPLIANCE_INSTALL"
    assert_hours(build["actual_station_hours"], "4.00")


def test_the_lot_invariant_holds_before_the_depleting_install_at_depletion_and_after_reversal(
    api, supervisor_headers
):
    """PRD §3.1: "Those three counters are an invariant, not bookkeeping: available plus installed plus quarantined always equals `quantity_received`, and every operation in §3.5 and §3.9 that moves one moves another to preserve it."

    PRD §3.5: "On success the lot's `quantity_available` decreases by the installed quantity and its `quantity_installed` increases by the same amount, conserving the piece total, and a lot whose `quantity_available` reaches exactly zero moves `AVAILABLE → DEPLETED`."

    PRD §3.5: "Reversal moves the installation `INSTALLED → REVERSED` and gives the pieces back: the lot's `quantity_installed` decreases by the installation's quantity and its `quantity_available` increases by the same amount, and a lot that had been `DEPLETED` returns `DEPLETED → AVAILABLE` once its `quantity_available` is above zero."

    Design: Difficulty/compensating_invariant/component_lot_piece_count_is_conserved_across_install_and_reverse
    """
    setup = _build_at_appliance_install_with_a_forty_piece_lot()
    build_id = setup["build"]["id"]
    lot_id = setup["lot"]["id"]

    before = read_lot(lot_id)
    assert before["quantity_available"] == 15
    assert before["quantity_installed"] == 25
    assert before["quantity_quarantined"] == 0
    assert before["status"] == "AVAILABLE"
    assert_lot_counter_invariant(before)

    second_installation = validate_success(
        api.create_component_installation(
            _installation_payload(build_id, lot_id, 15), supervisor_headers
        ),
        201,
    )
    assert second_installation["status"] == "INSTALLED"

    depleted = read_lot(lot_id)
    assert depleted["quantity_available"] == 0
    assert depleted["quantity_installed"] == 40
    assert depleted["quantity_quarantined"] == 0
    assert depleted["status"] == "DEPLETED"
    assert_lot_counter_invariant(depleted)

    validate_success(
        api.reverse_installation(
            second_installation["id"],
            supervisor_headers,
            {"reversal_reason": "Wrong part revision staged at the station"},
        )
    )

    after = read_lot(lot_id)
    assert after["quantity_available"] == 15
    assert after["quantity_installed"] == 25
    assert after["quantity_quarantined"] == 0
    assert after["status"] == "AVAILABLE"
    assert_lot_counter_invariant(after)
    assert after["quantity_received"] == 40


def test_floor_plan_principal_is_conserved_across_curtailment_partial_payment_and_payoff(
    api, plant_admin_headers
):
    """PRD §3.7: "The required amount is the principal multiplied by that basis-point figure, divided by 10000, rounded half up to whole cents; and `curtailment_due_cents` is that required amount minus whatever `curtailment_paid_cents` has already been paid, floored at zero."

    PRD §3.7: "A payment that leaves the paid total short of the full principal adds `amount_cents` to `curtailment_paid_cents` and recomputes `curtailment_due_cents`; if the order was `CURTAILED` and the recomputed amount due reaches zero, it returns `CURTAILED → FLOOR_PLAN_FUNDED`, where a later sweep may curtail it again — this is a genuine cycle, not a one-way door."

    PRD §3.7: "A payment that brings the paid total to exactly the full `financed_principal_cents` retires the advance: `curtailment_paid_cents` becomes the full principal, `curtailment_due_cents` becomes zero, and `financing_status` moves to the terminal `PAID_OFF` from either `FLOOR_PLAN_FUNDED` or `CURTAILED`, removing the unit from the dealer's exposure set."

    PRD §3.7: "A dealer's `financed_exposure_cents` is the sum, across every one of its orders whose `financing_status` is `FLOOR_PLAN_FUNDED` or `CURTAILED`, of that order's `financed_principal_cents` minus its `curtailment_paid_cents`."

    Design: Difficulty/compensating_invariant/floor_plan_principal_is_conserved_across_curtailment_and_payoff
    """
    kit, order = _funded_canonical_order_at_one_hundred_eighty_days()
    dealer_id = kit["dealer"]["id"]
    dealer_headers = make_dealer_principal_headers(dealer_id)
    order_id = order["id"]

    closed = validate_success(api.daily_close(plant_admin_headers))
    assert closed["curtailed_order_count"] == 1
    assert closed["curtailed_order_ids"] == [order_id]
    assert closed["released_slot_count"] == 0

    curtailed = read_order(order_id)
    assert curtailed["financing_status"] == "CURTAILED"
    assert_cents(curtailed["curtailment_due_cents"], 1451045)
    assert_cents(curtailed["financed_principal_cents"], 14510453)
    assert curtailed["status"] == "CONFIG_VALIDATED"

    validate_success(
        api.floor_plan_payment(order_id, {"amount_cents": 1451045}, dealer_headers)
    )

    after_stage_one = read_order(order_id)
    assert after_stage_one["financing_status"] == "FLOOR_PLAN_FUNDED"
    assert_cents(after_stage_one["curtailment_paid_cents"], 1451045)
    assert_cents(after_stage_one["curtailment_due_cents"], 0)
    assert_cents(after_stage_one["financed_principal_cents"], 14510453)
    assert after_stage_one["status"] == "CONFIG_VALIDATED"

    dealer = read_dealer(dealer_id)
    assert_cents(dealer["financed_exposure_cents"], 13059408)
    assert after_stage_one["curtailment_paid_cents"] + dealer["financed_exposure_cents"] == 14510453
    assert dealer["credit_utilization_bp"] == 8550
    assert dealer["credit_status"] == "WATCH"

    validate_success(
        api.floor_plan_payment(order_id, {"amount_cents": 13059408}, dealer_headers)
    )

    paid_off = read_order(order_id)
    assert paid_off["financing_status"] == "PAID_OFF"
    assert_cents(paid_off["curtailment_paid_cents"], 14510453)
    assert_cents(paid_off["curtailment_due_cents"], 0)
    assert_cents(paid_off["financed_principal_cents"], 14510453)
    assert paid_off["status"] == "CONFIG_VALIDATED"

    settled_dealer = read_dealer(dealer_id)
    assert_cents(settled_dealer["financed_exposure_cents"], 0)
    assert settled_dealer["credit_utilization_bp"] == 0
    assert settled_dealer["credit_status"] == "GOOD_STANDING"


def test_a_paid_stage_one_curtailment_is_not_swept_again_at_the_same_clock(
    api, plant_admin_headers
):
    """PRD §2.5: "The curtailment sweep finds every `UnitOrder` whose `financing_status` is `FLOOR_PLAN_FUNDED` and whose computed curtailment obligation is positive and moves it `FLOOR_PLAN_FUNDED → CURTAILED`, persisting the recomputed `curtailment_due_cents`."

    PRD §3.7: "The required amount is the principal multiplied by that basis-point figure, divided by 10000, rounded half up to whole cents; and `curtailment_due_cents` is that required amount minus whatever `curtailment_paid_cents` has already been paid, floored at zero."

    PRD §3.7: "A payment that leaves the paid total short of the full principal adds `amount_cents` to `curtailment_paid_cents` and recomputes `curtailment_due_cents`; if the order was `CURTAILED` and the recomputed amount due reaches zero, it returns `CURTAILED → FLOOR_PLAN_FUNDED`, where a later sweep may curtail it again — this is a genuine cycle, not a one-way door."

    PRD §3.7: "A dealer's `financed_exposure_cents` is the sum, across every one of its orders whose `financing_status` is `FLOOR_PLAN_FUNDED` or `CURTAILED`, of that order's `financed_principal_cents` minus its `curtailment_paid_cents`."

    Design: Difficulty/compensating_invariant/floor_plan_principal_is_conserved_across_curtailment_and_payoff
    """
    kit, order = _funded_canonical_order_at_one_hundred_eighty_days()
    dealer_id = kit["dealer"]["id"]
    dealer_headers = make_dealer_principal_headers(dealer_id)
    order_id = order["id"]

    first_close = validate_success(api.daily_close(plant_admin_headers))
    assert first_close["curtailed_order_count"] == 1
    assert first_close["curtailed_order_ids"] == [order_id]

    validate_success(
        api.floor_plan_payment(order_id, {"amount_cents": 1451045}, dealer_headers)
    )

    second_close = validate_success(api.daily_close(plant_admin_headers))
    assert second_close["curtailed_order_count"] == 0
    assert second_close["curtailed_order_ids"] == []
    assert second_close["released_slot_count"] == 0

    settled = read_order(order_id)
    assert settled["financing_status"] == "FLOOR_PLAN_FUNDED"
    assert_cents(settled["curtailment_paid_cents"], 1451045)
    assert_cents(settled["curtailment_due_cents"], 0)
    assert_cents(settled["financed_principal_cents"], 14510453)
    assert settled["status"] == "CONFIG_VALIDATED"

    dealer = read_dealer(dealer_id)
    assert_cents(dealer["financed_exposure_cents"], 13059408)
    assert settled["curtailment_paid_cents"] + dealer["financed_exposure_cents"] == 14510453
    assert dealer["credit_utilization_bp"] == 8550
    assert dealer["credit_status"] == "WATCH"
