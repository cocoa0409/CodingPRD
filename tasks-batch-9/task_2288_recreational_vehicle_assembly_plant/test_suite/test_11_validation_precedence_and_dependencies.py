"""Validation precedence on colliding rules, and cross-entity state coupling.

Every test drives the plant through PRD §4 endpoints only and starts from an
empty database.
"""
from test_helpers import (
    ApiErrorId,
    assert_cents,
    assert_hours,
    assert_vin_format,
    build_canon_kit,
    canon_option_ids,
    create_chassis_receipt,
    create_dealer,
    create_floor_plan,
    create_option_item,
    create_order,
    create_production_line,
    create_supplier,
    decide_funding,
    make_dealer_principal_headers,
    match_chassis,
    read_build,
    read_dealer,
    read_order,
    release_to_line,
    replace_configuration,
    request_funding,
    reserve_slot,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)

CANCEL_REASON = "Customer withdrew"


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


def _slotted_and_matched_class_a_order():
    """A SOLD Class A order holding a RESERVED slot and a MATCHED chassis."""
    supplier = create_supplier(
        supplier_code="SUP-CH",
        name="Cascade Chassis Works",
        component_categories=["CHASSIS"],
    )
    floor_plan = _create_class_a_floor_plan()
    option = create_option_item(
        option_code="OPT-AC2",
        category="ELECTRICAL",
        install_station="ROOF_SET",
        price_cents=385000,
        weight_lbs=95,
        added_station_hours=2.50,
        amp_draw=16,
        water_demand_gal=0,
    )
    dealer = _create_big_dealer()
    line = create_production_line(
        line_code="LINE-A",
        chassis_class_supported="CLASS_A",
        daily_station_hour_capacity=240.00,
        max_units_per_day=4,
    )
    chassis = create_chassis_receipt(
        supplier["id"],
        chassis_serial="CH-0001",
        chassis_class="CLASS_A",
        gvwr_lbs=26000,
        wheelbase_in=242,
    )
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="SOLD",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-09-15T00:00:00Z",
    )
    order = submit_order(order["id"], dealer["id"])
    slot = reserve_slot(order["id"], line["id"], "2026-08-05T00:00:00Z", order["version"])
    match_chassis(order["id"])
    return {
        "dealer": dealer,
        "floor_plan": floor_plan,
        "line": line,
        "chassis": chassis,
        "order": order,
        "slot": slot,
    }


def _tight_credit_kit():
    """FP-3410, the five options, LINE-A and a dealer whose credit line is thin."""
    return build_canon_kit(
        with_chassis=False,
        with_booth=False,
        with_lot=False,
        dealer={"dealer_code": "D-TIGHT", "floor_plan_credit_limit_cents": 15272000},
    )


def _funded_five_option_order(kit, requested_delivery_date="2026-09-15T00:00:00Z"):
    dealer_id = kit["dealer"]["id"]
    order = create_order(
        dealer_id,
        kit["floor_plan"]["id"],
        order_type="STOCK",
        selected_option_ids=canon_option_ids(kit),
        requested_delivery_date=requested_delivery_date,
    )
    submit_order(order["id"], dealer_id)
    request_funding(order["id"], dealer_id)
    decide_funding(order["id"], "APPROVED")
    return read_order(order["id"])


def _submitted_five_option_order(kit, requested_delivery_date="2026-09-20T00:00:00Z"):
    dealer_id = kit["dealer"]["id"]
    order = create_order(
        dealer_id,
        kit["floor_plan"]["id"],
        order_type="STOCK",
        selected_option_ids=canon_option_ids(kit),
        requested_delivery_date=requested_delivery_date,
    )
    return submit_order(order["id"], dealer_id)


def _overweight_class_c_order():
    """FP-2810 plus three options: 10 lb over the GVWR and two closures unmet."""
    floor_plan = create_floor_plan(
        model_code="FP-2810",
        chassis_class="CLASS_C",
        length_ft=28,
        base_msrp_cents=9850000,
        base_station_hours=34.00,
        base_dry_weight_lbs=13900,
        gvwr_lbs=14200,
        required_wheelbase_in=208,
        electrical_service_amps=30,
        fresh_water_capacity_gal=44,
    )
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
    solar = create_option_item(
        option_code="OPT-SOLAR",
        category="ELECTRICAL",
        install_station="ROOF_SET",
        price_cents=325000,
        weight_lbs=70,
        added_station_hours=4.00,
        amp_draw=0,
        water_demand_gal=0,
        requires_option_codes=["OPT-INV"],
    )
    dishwasher = create_option_item(
        option_code="OPT-DISH",
        category="APPLIANCE",
        install_station="APPLIANCE_INSTALL",
        price_cents=139500,
        weight_lbs=60,
        added_station_hours=1.50,
        amp_draw=10,
        water_demand_gal=3,
        requires_option_codes=["OPT-WSOFT"],
    )
    dealer = _create_big_dealer()
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="SOLD",
        selected_option_ids=[washer["id"], solar["id"], dishwasher["id"]],
        requested_delivery_date="2026-09-15T00:00:00Z",
    )
    return {
        "floor_plan": floor_plan,
        "washer": washer,
        "solar": solar,
        "dishwasher": dishwasher,
        "dealer": dealer,
        "order": order,
    }


def test_slot_reservation_on_a_cancelled_order_reports_the_state_code_not_the_credit_hold(
    api, scheduler_headers
):
    """PRD §2.8: "Validation is a strictly ordered ladder, not a set of independent checks. The **first** violated rule determines the response; later rules are never reported even when they are also violated."

    PRD §3.3: "Reservation is permitted when the order's `status` is `CONFIG_VALIDATED` or already `SLOTTED` — any other status is `ERR_ORDER_NOT_SLOTTABLE`."

    PRD §2.8: "**Fiscal**, last of all and in this internal order: `ERR_DEALER_CREDIT_HOLD` (the dealer's `credit_status` is `CREDIT_HOLD`), then `ERR_DEALER_CURTAILMENT_DELINQUENT` (some order of the dealer is `CURTAILED` with a positive `curtailment_due_cents`), then `ERR_DEALER_ALLOCATION_EXCEEDED`, then `ERR_FLOOR_PLAN_FUNDING_REQUIRED`, then `ERR_GOODWILL_BUDGET_EXHAUSTED`."

    PRD §3.7: "Because both comparisons are strict, exactly 9500 basis points is `WATCH` and 9501 is `CREDIT_HOLD`."

    Design: Difficulty/priority_pair_validation_conflict/slot_reserve_on_cancelled_order_reports_state_before_credit_hold
    """
    kit = _tight_credit_kit()
    dealer_id = kit["dealer"]["id"]
    dealer_headers = make_dealer_principal_headers(dealer_id)

    funded_order = _funded_five_option_order(kit)
    cancelled_order = _submitted_five_option_order(kit)
    cancelled_order = validate_success(
        api.cancel_order(
            cancelled_order["id"], dealer_headers, {"cancel_reason": CANCEL_REASON}
        )
    )

    response = api.reserve_production_slot(
        cancelled_order["id"],
        {
            "line_id": kit["line"]["id"],
            "slot_date": "2026-08-05T00:00:00Z",
            "expected_unit_order_version": cancelled_order["version"],
        },
        scheduler_headers,
    )

    error = validate_error(response, ApiErrorId.ERR_ORDER_NOT_SLOTTABLE)
    assert response.status_code == 409
    # The fiscal rule is live on this very request but sits last in the ladder.
    assert error["error_id"] != ApiErrorId.ERR_DEALER_CREDIT_HOLD

    dealer = read_dealer(dealer_id)
    assert dealer["credit_utilization_bp"] == 9501
    assert dealer["credit_status"] == "CREDIT_HOLD"
    assert_cents(read_order(funded_order["id"])["financed_principal_cents"], 14510453)
    assert read_order(cancelled_order["id"])["status"] == "CANCELLED"

    rows, meta = validate_paginated(
        api.list_production_slots(
            scheduler_headers, params={"unit_order_id": cancelled_order["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_credit_hold_is_reported_on_the_same_reservation_once_the_order_state_admits_it(
    api, scheduler_headers
):
    """PRD §3.3: "The dealer must be in good order: its `status` must be `ACTIVE` and its `credit_status` must not be `CREDIT_HOLD`, and no order belonging to that dealer may be sitting `CURTAILED` with a positive `curtailment_due_cents` — those two fiscal failures are `ERR_DEALER_CREDIT_HOLD` and `ERR_DEALER_CURTAILMENT_DELINQUENT` respectively."

    PRD §3.7: "Its `credit_utilization_bp` is that exposure multiplied by 10000 and divided by its `floor_plan_credit_limit_cents`, truncated toward zero to a whole number of basis points — and zero when the credit limit is zero."

    PRD §3.7: "Because both comparisons are strict, exactly 9500 basis points is `WATCH` and 9501 is `CREDIT_HOLD`."

    Design: Difficulty/priority_pair_validation_conflict/slot_reserve_on_cancelled_order_reports_state_before_credit_hold
    """
    kit = _tight_credit_kit()
    dealer_id = kit["dealer"]["id"]

    funded_order = _funded_five_option_order(kit)
    second_order = _submitted_five_option_order(kit)

    response = api.reserve_production_slot(
        second_order["id"],
        {
            "line_id": kit["line"]["id"],
            "slot_date": "2026-08-05T00:00:00Z",
            "expected_unit_order_version": second_order["version"],
        },
        scheduler_headers,
    )

    validate_error(response, ApiErrorId.ERR_DEALER_CREDIT_HOLD)
    assert response.status_code == 422

    dealer = read_dealer(dealer_id)
    assert dealer["credit_utilization_bp"] == 9501
    assert dealer["credit_status"] == "CREDIT_HOLD"
    assert_cents(read_order(funded_order["id"])["financed_principal_cents"], 14510453)
    assert read_order(second_order["id"])["status"] == "CONFIG_VALIDATED"

    _rows, meta = validate_paginated(
        api.list_production_slots(
            scheduler_headers, params={"unit_order_id": second_order["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_submit_reports_the_gross_weight_failure_ahead_of_the_unsatisfied_requires_closure(
    api, plant_admin_headers
):
    """PRD §2.8: "**Gross weight.** `config_weight_lbs` may not exceed the floor plan's `gvwr_lbs`, else `ERR_PAYLOAD_CAPACITY_EXCEEDED` (422). This is the first physical rule and it outranks every option-compatibility rule: a configuration that is both overweight and missing a required companion option reports the weight."

    PRD §3.2: "`config_weight_lbs` is the floor plan's `base_dry_weight_lbs` plus the sum of `weight_lbs` across the selected options. `payload_remaining_lbs` is the floor plan's `gvwr_lbs` minus `config_weight_lbs`."

    PRD §3.1: "The plant derives `max_payload_lbs` as the gross vehicle weight rating minus the base dry weight, and re-derives it whenever the plan is edited."

    Design: Difficulty/priority_pair_validation_conflict/submit_reports_payload_capacity_before_option_requires_missing
    """
    setup = _overweight_class_c_order()
    dealer_headers = make_dealer_principal_headers(setup["dealer"]["id"])

    response = api.submit_order(setup["order"]["id"], dealer_headers)

    error = validate_error(response, ApiErrorId.ERR_PAYLOAD_CAPACITY_EXCEEDED)
    assert response.status_code == 422
    # Both OPT-SOLAR and OPT-DISH name a companion the selection never carries,
    # yet the physical rule outranks the option-set rule.
    assert error["error_id"] != ApiErrorId.ERR_OPTION_REQUIRES_MISSING

    order = read_order(setup["order"]["id"])
    assert order["status"] == "DRAFT"
    assert order["config_weight_lbs"] == 14210
    assert order["payload_remaining_lbs"] == -10
    assert_cents(order["provisional_invoice_cents"], 0)

    floor_plan = validate_success(
        api.get_floor_plan(setup["floor_plan"]["id"], plant_admin_headers)
    )
    assert floor_plan["max_payload_lbs"] == 300


def test_submit_reports_the_requires_closure_once_the_configuration_is_inside_the_gvwr(api):
    """PRD §2.8: "**Option-set consistency**, in this internal order: `ERR_OPTION_DISCONTINUED` (a selected option whose `status` is `DISCONTINUED`), then `ERR_OPTION_REQUIRES_MISSING` (the transitive requires closure is unsatisfied), then `ERR_OPTION_MUTUALLY_EXCLUSIVE` (an excluding pair is present), then `ERR_STATION_HOURS_LIMIT_EXCEEDED` (the computed `required_station_hours` exceeds the single-unit ceiling). All four carry HTTP 422."

    PRD §3.2: "Then the **requires** relation is resolved transitively: if a selected option lists a companion `option_code` in its `requires_option_codes`, that companion must also be present in the selection, and so must anything *that* companion requires, and so on to closure — an unsatisfied closure at any depth is `ERR_OPTION_REQUIRES_MISSING`."

    PRD §3.2: "`config_weight_lbs` is the floor plan's `base_dry_weight_lbs` plus the sum of `weight_lbs` across the selected options. `payload_remaining_lbs` is the floor plan's `gvwr_lbs` minus `config_weight_lbs`."

    Design: Difficulty/priority_pair_validation_conflict/submit_reports_payload_capacity_before_option_requires_missing
    """
    setup = _overweight_class_c_order()
    dealer_id = setup["dealer"]["id"]
    dealer_headers = make_dealer_principal_headers(dealer_id)

    # Drop the 180 lb washer: 13900 + 70 + 60 leaves 170 lb of payload spare,
    # while OPT-SOLAR still wants OPT-INV and OPT-DISH still wants OPT-WSOFT.
    replace_configuration(
        setup["order"]["id"],
        dealer_id,
        [setup["solar"]["id"], setup["dishwasher"]["id"]],
    )

    response = api.submit_order(setup["order"]["id"], dealer_headers)

    validate_error(response, ApiErrorId.ERR_OPTION_REQUIRES_MISSING)
    assert response.status_code == 422

    order = read_order(setup["order"]["id"])
    assert order["status"] == "DRAFT"
    assert order["config_weight_lbs"] == 14030
    assert order["payload_remaining_lbs"] == 170
    assert_cents(order["provisional_invoice_cents"], 0)


def test_release_to_line_is_refused_while_the_dealer_is_suspended_and_succeeds_once_reinstated(
    api, plant_admin_headers, scheduler_headers
):
    """PRD §3.1: "A `PlantAdmin` may later flip a dealer's `status` between `ACTIVE` and `SUSPENDED`; a `SUSPENDED` dealer can no longer submit orders, reserve slots, request funding, be released to a line, or receive a shipment, and each of those attempts is rejected with `ERR_DEALER_SUSPENDED`."

    PRD §3.4: "**Releasing to the line** is the handoff from paperwork to production, driving the order `SLOTTED → IN_PRODUCTION` and returning the newly created build."

    PRD §3.4: "It receives a `build_sequence` equal to the plant-wide build counter plus one, a one-based monotonic figure in build-creation order, and a `vin` formed from the floor plan's `model_code`, then a hyphen, then that `build_sequence` zero-padded to six digits."

    PRD §3.4: "In the same operation the slot moves `RESERVED → CONSUMED` and the chassis moves `MATCHED → INSTALLED`."

    Design: Difficulty/cross_entity_state_dependency/release_to_line_depends_on_dealer_status_not_on_order_state
    """
    setup = _slotted_and_matched_class_a_order()
    order_id = setup["order"]["id"]
    dealer_id = setup["dealer"]["id"]
    validate_success(
        api.set_dealer_status(dealer_id, {"status": "SUSPENDED"}, plant_admin_headers)
    )

    refused = api.release_to_line(order_id, scheduler_headers)
    validate_error(refused, ApiErrorId.ERR_DEALER_SUSPENDED)
    assert refused.status_code == 409

    assert read_order(order_id)["status"] == "SLOTTED"
    _rows, meta = validate_paginated(
        api.list_unit_builds(scheduler_headers, params={"unit_order_id": order_id})
    )
    assert meta["total_count"] == 0

    validate_success(
        api.set_dealer_status(dealer_id, {"status": "ACTIVE"}, plant_admin_headers)
    )
    build = validate_success(api.release_to_line(order_id, scheduler_headers), 201)

    assert read_order(order_id)["status"] == "IN_PRODUCTION"
    assert build["current_station"] == "CHASSIS_PREP"
    assert build["build_sequence"] == 1
    assert_vin_format(build["vin"], "FP-3410", 1)
    assert build["vin"] == "FP-3410-000001"

    chassis = validate_success(
        api.get_chassis_receipt(setup["chassis"]["id"], scheduler_headers)
    )
    assert chassis["status"] == "INSTALLED"
    slot = validate_success(api.get_production_slot(setup["slot"]["id"], scheduler_headers))
    assert slot["status"] == "CONSUMED"


def test_a_release_refused_on_dealer_status_leaves_the_slot_and_chassis_untouched(
    api, plant_admin_headers, scheduler_headers
):
    """PRD §3.1: "A `PlantAdmin` may later flip a dealer's `status` between `ACTIVE` and `SUSPENDED`; a `SUSPENDED` dealer can no longer submit orders, reserve slots, request funding, be released to a line, or receive a shipment, and each of those attempts is rejected with `ERR_DEALER_SUSPENDED`."

    PRD §3.4: "Release creates the **unit build**, the shop-floor record of one physical coach."

    PRD §3.4: "In the same operation the slot moves `RESERVED → CONSUMED` and the chassis moves `MATCHED → INSTALLED`."

    Design: Difficulty/cross_entity_state_dependency/release_to_line_depends_on_dealer_status_not_on_order_state
    """
    setup = _slotted_and_matched_class_a_order()
    order_id = setup["order"]["id"]
    dealer_id = setup["dealer"]["id"]

    chassis_before = validate_success(
        api.get_chassis_receipt(setup["chassis"]["id"], scheduler_headers)
    )
    assert chassis_before["status"] == "MATCHED"
    assert chassis_before["matched_unit_order_id"] == order_id
    slot_before = validate_success(
        api.get_production_slot(setup["slot"]["id"], scheduler_headers)
    )
    assert slot_before["status"] == "RESERVED"

    validate_success(
        api.set_dealer_status(dealer_id, {"status": "SUSPENDED"}, plant_admin_headers)
    )
    refused = api.release_to_line(order_id, scheduler_headers)
    validate_error(refused, ApiErrorId.ERR_DEALER_SUSPENDED)

    assert read_dealer(dealer_id)["status"] == "SUSPENDED"
    assert read_order(order_id)["status"] == "SLOTTED"

    chassis_after = validate_success(
        api.get_chassis_receipt(setup["chassis"]["id"], scheduler_headers)
    )
    assert chassis_after["status"] == "MATCHED"
    assert chassis_after["matched_unit_order_id"] == order_id
    slot_after = validate_success(
        api.get_production_slot(setup["slot"]["id"], scheduler_headers)
    )
    assert slot_after["status"] == "RESERVED"

    _rows, meta = validate_paginated(
        api.list_unit_builds(scheduler_headers, params={"unit_order_id": order_id})
    )
    assert meta["total_count"] == 0


def test_advance_is_refused_while_the_line_is_paused_and_banks_the_hours_once_it_resumes(
    api, scheduler_headers, supervisor_headers
):
    """PRD §3.5: "Every advancement carries the same two ambient conditions. The line the build occupies — the line of the slot the build consumed — must have `status` `RUNNING`, else `ERR_LINE_NOT_RUNNING`."

    PRD §3.5: "On success the reported `station_hours_used` is added to the build's `actual_station_hours`, which accumulates across the whole build including every rework loop, and which later becomes the overtime term of the final invoice."

    PRD §3.4: "It stands at `current_station` `CHASSIS_PREP` with `actual_station_hours` `0.00`, `rework_count` 0, `defect_points_total` 0, `water_test_passed` false, `pdi_passed` false, and `recall_hold` false."

    Design: Difficulty/cross_entity_state_dependency/build_advance_depends_on_production_line_status
    """
    setup = _slotted_and_matched_class_a_order()
    order_id = setup["order"]["id"]
    line_id = setup["line"]["id"]
    build = release_to_line(order_id)
    validate_success(
        api.set_production_line_status(line_id, {"status": "PAUSED"}, scheduler_headers)
    )

    refused = api.advance_build(
        build["id"], {"to_station": "SIDEWALL_LAM", "station_hours_used": 8.00}, supervisor_headers
    )
    validate_error(refused, ApiErrorId.ERR_LINE_NOT_RUNNING)
    assert refused.status_code == 409

    held = read_build(build["id"])
    assert held["current_station"] == "CHASSIS_PREP"
    assert_hours(held["actual_station_hours"], "0.00")

    validate_success(
        api.set_production_line_status(line_id, {"status": "RUNNING"}, scheduler_headers)
    )
    advanced = validate_success(
        api.advance_build(
            build["id"],
            {"to_station": "SIDEWALL_LAM", "station_hours_used": 8.00},
            supervisor_headers,
        )
    )

    assert advanced["current_station"] == "SIDEWALL_LAM"
    # The refused call added nothing, so the station banks its hours exactly once.
    assert_hours(advanced["actual_station_hours"], "8.00")
    assert_hours(read_build(build["id"])["actual_station_hours"], "8.00")
    line = validate_success(api.get_production_line(line_id, scheduler_headers))
    assert line["status"] == "RUNNING"
    assert read_order(order_id)["status"] == "IN_PRODUCTION"


def test_repeated_advances_refused_on_a_paused_line_never_accumulate_station_hours(
    api, scheduler_headers, supervisor_headers
):
    """PRD §3.1: "A line may be paused and resumed by either a `PlantAdmin` or a `ProductionScheduler`; while `PAUSED` it blocks station advancement for every build occupying it with `ERR_LINE_NOT_RUNNING`, though slots already reserved on it keep their committed hours and continue to count toward capacity."

    PRD §3.5: "On success the reported `station_hours_used` is added to the build's `actual_station_hours`, which accumulates across the whole build including every rework loop, and which later becomes the overtime term of the final invoice."

    Design: Difficulty/cross_entity_state_dependency/build_advance_depends_on_production_line_status
    """
    setup = _slotted_and_matched_class_a_order()
    line_id = setup["line"]["id"]
    build = release_to_line(setup["order"]["id"])
    validate_success(
        api.set_production_line_status(line_id, {"status": "PAUSED"}, scheduler_headers)
    )

    for _attempt in range(2):
        refused = api.advance_build(
            build["id"],
            {"to_station": "SIDEWALL_LAM", "station_hours_used": 8.00},
            supervisor_headers,
        )
        validate_error(refused, ApiErrorId.ERR_LINE_NOT_RUNNING)
        held = read_build(build["id"])
        assert held["current_station"] == "CHASSIS_PREP"
        assert_hours(held["actual_station_hours"], "0.00")

    paused = validate_success(api.get_production_line(line_id, scheduler_headers))
    assert paused["status"] == "PAUSED"

    validate_success(
        api.set_production_line_status(line_id, {"status": "RUNNING"}, scheduler_headers)
    )
    advanced = validate_success(
        api.advance_build(
            build["id"],
            {"to_station": "SIDEWALL_LAM", "station_hours_used": 8.00},
            supervisor_headers,
        )
    )
    assert advanced["current_station"] == "SIDEWALL_LAM"
    assert_hours(advanced["actual_station_hours"], "8.00")
