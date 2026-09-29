"""Refusal ordering and refusal reasons: the precedence ladder, dealer ownership, the
three physical ceilings, the option-set band, booth and clock bounds, and the fiscal
gates that stand between a finished coach and the road.
"""
from test_helpers import (
    advance_build,
    advance_clock,
    assert_cents,
    assert_hours,
    complete_inspection,
    create_dealer,
    create_floor_plan,
    create_option_item,
    create_order,
    create_production_line,
    create_test_booth,
    inject_delivered_unit,
    make_dealer_principal_headers,
    read_build,
    read_dealer,
    read_order,
    run_daily_close,
    schedule_booth_inspection,
    schedule_pdi,
    submit_order,
    tow_build_at_station,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)

DELIVERY_DATE = "2026-10-01T00:00:00Z"

UNKNOWN_FLOOR_PLAN_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_ORDER_ID = "22222222-2222-4222-8222-222222222222"
UNKNOWN_LINE_ID = "33333333-3333-4333-8333-333333333333"
UNKNOWN_ORDER_ID_2 = "44444444-4444-4444-8444-444444444444"


def _finish_option(option_code, **overrides):
    """Publish a 1.00 h, 100000 cent FINISH-station option."""
    payload = {
        "option_code": option_code,
        "category": "INTERIOR",
        "install_station": "FINISH",
        "price_cents": 100000,
        "weight_lbs": 0,
        "added_station_hours": 1.00,
        "amp_draw": 0,
        "water_demand_gal": 0,
    }
    payload.update(overrides)
    return create_option_item(**payload)


def test_precedence_rejects_auth_then_role_then_schema_then_path_then_body_ids(
    api, plant_admin_headers, scheduler_headers, inspector_headers
):
    """PRD §2.8: "Validation is a strictly ordered ladder, not a set of independent checks.
    The **first** violated rule determines the response; later rules are never reported
    even when they are also violated. Implementations must therefore evaluate in exactly
    this order." and "Every foreign key supplied in the request **body** resolves to an
    existing row, using the same per-entity 404 codes, and checked in the field order the
    endpoint declares its inputs. Body keys are always checked after path identifiers."

    Design: Corner/validations/precedence_rejects_auth_then_role_then_schema_then_path_then_body_ids
    """
    floor_plan = create_floor_plan()
    option = create_option_item()
    dealer = create_dealer()
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date=DELIVERY_DATE,
    )

    malformed = {
        "dealer_id": dealer["id"],
        "floor_plan_id": floor_plan["id"],
        "order_type": "NOT_A_TYPE",
        "selected_option_ids": [],
        "requested_delivery_date": DELIVERY_DATE,
    }
    unauthenticated = api.create_unit_order(malformed, {})
    wrong_role = api.create_unit_order(malformed, inspector_headers)
    bad_enum_and_unknown_plan = api.create_unit_order(
        {
            "dealer_id": dealer["id"],
            "floor_plan_id": UNKNOWN_FLOOR_PLAN_ID,
            "order_type": "NOT_A_TYPE",
            "selected_option_ids": [option["id"]],
            "requested_delivery_date": DELIVERY_DATE,
        },
        dealer_headers,
    )
    unknown_plan = api.create_unit_order(
        {
            "dealer_id": dealer["id"],
            "floor_plan_id": UNKNOWN_FLOOR_PLAN_ID,
            "order_type": "STOCK",
            "selected_option_ids": [option["id"]],
            "requested_delivery_date": DELIVERY_DATE,
        },
        dealer_headers,
    )
    unknown_path_and_body = api.reserve_production_slot(
        UNKNOWN_ORDER_ID,
        {
            "line_id": UNKNOWN_LINE_ID,
            "slot_date": "2026-08-05T00:00:00Z",
            "expected_unit_order_version": order["version"],
        },
        scheduler_headers,
    )
    unknown_body_line = api.reserve_production_slot(
        order["id"],
        {
            "line_id": UNKNOWN_LINE_ID,
            "slot_date": "2026-08-05T00:00:00Z",
            "expected_unit_order_version": order["version"],
        },
        scheduler_headers,
    )

    # Identity outranks the undeclared order_type in the very same body.
    validate_error(unauthenticated, ApiErrorId.ERR_UNAUTHENTICATED)
    # A wrong-role caller never learns the body is malformed.
    validate_error(wrong_role, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
    # The schema fault outranks the non-existent floor_plan_id.
    validate_error(bad_enum_and_unknown_plan, ApiErrorId.ERR_INVALID_REQUEST)
    validate_error(unknown_plan, ApiErrorId.ERR_FLOOR_PLAN_NOT_FOUND)
    # The path identifier is resolved before the body line_id.
    validate_error(unknown_path_and_body, ApiErrorId.ERR_UNIT_ORDER_NOT_FOUND)
    # Body existence outranks the DRAFT state gate, so this is not ERR_ORDER_NOT_SLOTTABLE.
    validate_error(unknown_body_line, ApiErrorId.ERR_PRODUCTION_LINE_NOT_FOUND)

    still_draft = read_order(order["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["version"] == 1
    _rows, meta = validate_paginated(
        api.list_production_slots(plant_admin_headers, {"unit_order_id": order["id"]})
    )
    assert meta["total_count"] == 0


def test_dealer_scope_is_checked_after_existence_and_forbidden_across_dealers(api):
    """PRD §2.1: "Ownership is evaluated after existence. A `DealerPrincipal` probing an
    order identifier that does not exist receives a 404, not a 403 that would leak the
    identifier space." and "Concretely, a `DealerPrincipal` may only address a `UnitOrder`
    whose `dealer_id` equals its `X-User-ID`, may only file or resubmit a `WarrantyClaim`
    whose `dealer_id` equals its `X-User-ID`, and on order creation must supply a
    `dealer_id` in the body equal to its own `X-User-ID`; any of these mismatches is
    rejected with `ERR_DEALER_SCOPE_VIOLATION` (403)."

    Design: Corner/validations/dealer_scope_is_checked_after_existence_and_forbidden_across_dealers
    """
    floor_plan = create_floor_plan()
    option = create_option_item()
    dealer_a = create_dealer(dealer_code="D-A", region="CENTRAL")
    dealer_b = create_dealer(dealer_code="D-B", region="EAST")
    headers_a = make_dealer_principal_headers(dealer_a["id"])
    headers_b = make_dealer_principal_headers(dealer_b["id"])
    order_a = create_order(
        dealer_a["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date=DELIVERY_DATE,
    )

    missing_probe = api.get_unit_order(UNKNOWN_ORDER_ID_2, headers_b)
    foreign_read = api.get_unit_order(order_a["id"], headers_b)
    foreign_write = api.submit_order(order_a["id"], headers_b)
    foreign_body = api.create_unit_order(
        {
            "dealer_id": dealer_a["id"],
            "floor_plan_id": floor_plan["id"],
            "order_type": "STOCK",
            "selected_option_ids": [option["id"]],
            "requested_delivery_date": DELIVERY_DATE,
        },
        headers_b,
    )
    own_read = validate_success(api.get_unit_order(order_a["id"], headers_a))

    # Existence precedes ownership, so the identifier space is not leaked.
    validate_error(missing_probe, ApiErrorId.ERR_UNIT_ORDER_NOT_FOUND)
    validate_error(foreign_read, ApiErrorId.ERR_DEALER_SCOPE_VIOLATION)
    validate_error(foreign_write, ApiErrorId.ERR_DEALER_SCOPE_VIOLATION)
    untouched = read_order(order_a["id"])
    assert untouched["status"] == "DRAFT"
    assert untouched["version"] == 1
    # A body dealer_id other than X-User-ID is the same violation as addressing a
    # foreign row.
    validate_error(foreign_body, ApiErrorId.ERR_DEALER_SCOPE_VIOLATION)
    assert own_read["status"] == "DRAFT"


def test_physical_band_rejects_weight_before_amps_before_water(api):
    """PRD §2.8: "**Gross weight.** `config_weight_lbs` may not exceed the floor plan's
    `gvwr_lbs`, else `ERR_PAYLOAD_CAPACITY_EXCEEDED` (422). This is the first physical rule
    and it outranks every option-compatibility rule: a configuration that is both
    overweight and missing a required companion option reports the weight." and "**Shore
    power.** `total_amp_draw` may not exceed the floor plan's `electrical_service_amps`,
    else `ERR_ELECTRICAL_SERVICE_EXCEEDED` (422). Checked after weight and before the water
    system." and "**Water system.** `total_water_demand_gal` may not exceed the
    plumbed-demand ceiling of §3.2, else `ERR_WATER_SYSTEM_CAPACITY_EXCEEDED` (422)."

    Design: Corner/validations/physical_band_rejects_weight_before_amps_before_water
    """
    floor_plan = create_floor_plan()
    heavy = _finish_option("OPT-HEAVY", weight_lbs=3001)
    amp_60 = _finish_option(
        "OPT-AMP60", category="ELECTRICAL", install_station="ROUGH_IN", amp_draw=60
    )
    water_31 = _finish_option(
        "OPT-WAT31", category="PLUMBING", install_station="ROUGH_IN", water_demand_gal=31
    )
    amp_50 = _finish_option(
        "OPT-AMP50", category="ELECTRICAL", install_station="ROUGH_IN", amp_draw=50
    )
    water_30 = _finish_option(
        "OPT-WAT30", category="PLUMBING", install_station="ROUGH_IN", water_demand_gal=30
    )
    dealer = create_dealer()
    dealer_headers = make_dealer_principal_headers(dealer["id"])

    def draft(option_ids):
        return create_order(
            dealer["id"],
            floor_plan["id"],
            order_type="STOCK",
            selected_option_ids=option_ids,
            requested_delivery_date=DELIVERY_DATE,
        )

    order_all = draft([heavy["id"], amp_60["id"], water_31["id"]])
    order_amp = draft([amp_60["id"], water_31["id"]])
    order_water = draft([water_31["id"]])
    order_edge = draft([amp_50["id"], water_30["id"]])

    refused_all = api.submit_order(order_all["id"], dealer_headers)
    refused_amp = api.submit_order(order_amp["id"], dealer_headers)
    refused_water = api.submit_order(order_water["id"], dealer_headers)
    edge = validate_success(api.submit_order(order_edge["id"], dealer_headers))

    # 9001 > 9000, reported even though 60 A and 31 gal are also over their ceilings.
    validate_error(refused_all, ApiErrorId.ERR_PAYLOAD_CAPACITY_EXCEEDED)
    # 60 > 50, reported even though 31 gal is also over its ceiling.
    validate_error(refused_amp, ApiErrorId.ERR_ELECTRICAL_SERVICE_EXCEEDED)
    # 31 > 30, the 5000 bp ceiling of the 60 gal tank.
    validate_error(refused_water, ApiErrorId.ERR_WATER_SYSTEM_CAPACITY_EXCEEDED)
    # Both ceilings are inclusive.
    assert edge["status"] == "CONFIG_VALIDATED"
    assert edge["total_amp_draw"] == 50
    assert edge["total_water_demand_gal"] == 30

    for refused_order in (order_all, order_amp, order_water):
        unchanged = read_order(refused_order["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["version"] == 1
        assert_cents(unchanged["provisional_invoice_cents"], 0)


def test_transitive_requires_closure_satisfied_passes_submit(api):
    """PRD §3.2: "Then the **requires** relation is resolved transitively: if a selected
    option lists a companion `option_code` in its `requires_option_codes`, that companion
    must also be present in the selection, and so must anything *that* companion requires,
    and so on to closure — an unsatisfied closure at any depth is
    `ERR_OPTION_REQUIRES_MISSING`."

    Design: Corner/validations/transitive_requires_closure_satisfied_passes_submit
    """
    floor_plan = create_floor_plan()
    base = _finish_option("OPT-BASE")
    mid = _finish_option("OPT-MID", requires_option_codes=["OPT-BASE"])
    top = _finish_option("OPT-TOP", requires_option_codes=["OPT-MID"])
    dealer = create_dealer()
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[top["id"], mid["id"], base["id"]],
        requested_delivery_date=DELIVERY_DATE,
    )

    submitted = validate_success(
        api.submit_order(order["id"], make_dealer_principal_headers(dealer["id"]))
    )

    # The closure OPT-BASE, OPT-MID, OPT-TOP is complete.
    assert submitted["status"] == "CONFIG_VALIDATED"
    assert_hours(submitted["required_station_hours"], "43.00")
    assert_cents(submitted["option_price_total_cents"], 300000)
    assert len(submitted["locked_option_versions"]) == 3
    for pinned in submitted["locked_option_versions"]:
        assert pinned["version"] == 1
    assert submitted["version"] == 2
    # PRD §3.7: base 8000000 at STOCK 2200 bp is 6240000; each INTERIOR option
    # 100000 at 1350 bp rounds to 86500 per line; freight is 180000 + 4200 x 28 ft
    # with no CENTRAL surcharge.
    assert_cents(submitted["provisional_invoice_cents"], 6797100)


def test_option_band_reports_discontinued_before_mutual_exclusion(api, plant_admin_headers):
    """PRD §2.8: "**Option-set consistency**, in this internal order:
    `ERR_OPTION_DISCONTINUED` (a selected option whose `status` is `DISCONTINUED`), then
    `ERR_OPTION_REQUIRES_MISSING` (the transitive requires closure is unsatisfied), then
    `ERR_OPTION_MUTUALLY_EXCLUSIVE` (an excluding pair is present), then
    `ERR_STATION_HOURS_LIMIT_EXCEEDED` (the computed `required_station_hours` exceeds the
    single-unit ceiling). All four carry HTTP 422."
    PRD §3.2: "Then the **excludes** relation is checked pairwise: if any selected option
    lists another selected option's `option_code` in its `excludes_option_codes`, the pair
    is illegal and the request fails with `ERR_OPTION_MUTUALLY_EXCLUSIVE`."

    Design: Corner/validations/option_band_reports_discontinued_before_mutual_exclusion
    """
    floor_plan = create_floor_plan()
    option_x1 = _finish_option("OPT-X1")
    option_x2 = _finish_option("OPT-X2", excludes_option_codes=["OPT-X1"])
    dealer = create_dealer()
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option_x1["id"], option_x2["id"]],
        requested_delivery_date=DELIVERY_DATE,
    )
    withdrawn = validate_success(
        api.patch_option_item(option_x1["id"], {"status": "DISCONTINUED"}, plant_admin_headers)
    )

    first_refusal = api.submit_order(order["id"], dealer_headers)
    reinstated = validate_success(
        api.patch_option_item(option_x1["id"], {"status": "ACTIVE"}, plant_admin_headers)
    )
    second_refusal = api.submit_order(order["id"], dealer_headers)
    reconfigured = validate_success(
        api.replace_configuration(
            order["id"], {"selected_option_ids": [option_x2["id"]]}, dealer_headers
        )
    )
    final = validate_success(api.submit_order(order["id"], dealer_headers))

    assert withdrawn["status"] == "DISCONTINUED"
    # The withdrawal is reported even though the exclusion pair is also present.
    validate_error(first_refusal, ApiErrorId.ERR_OPTION_DISCONTINUED)
    assert reinstated["status"] == "ACTIVE"
    # The same order and the same body now yield a different code.
    validate_error(second_refusal, ApiErrorId.ERR_OPTION_MUTUALLY_EXCLUSIVE)
    # Replacing the configuration returns the order to DRAFT.
    assert reconfigured["status"] == "DRAFT"
    assert final["status"] == "CONFIG_VALIDATED"
    # The pair was refused although only OPT-X2 declared the exclusion.
    assert option_x2["excludes_option_codes"] == ["OPT-X1"]
    assert option_x1["excludes_option_codes"] == []


def test_booth_window_and_clock_bounds_are_rejected_as_invalid_request(
    api, plant_admin_headers, inspector_headers
):
    """PRD §2.8: "This band also covers a booth window whose `window_end` is at or before
    its `window_start`, a booth window shorter than 30 or longer than 240 minutes, an
    installation `quantity` of zero or less, an `amount_cents` of zero or less,
    `labor_hours` of zero or less, duplicate entries in `selected_option_ids`, a pagination
    `limit` outside 1 through 100, a `test_booth_id` absent for a `WATER_TEST` or
    `FUNCTIONAL` inspection or present for a `PDI` inspection, a `test_booth_id` whose
    booth `booth_type` does not equal the requested `inspection_type`, and a clock value
    not strictly after the current clock."
    PRD §2.5: "The clock may only move forward — a supplied value equal to or earlier than
    the current clock is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/booth_window_and_clock_bounds_are_rejected_as_invalid_request
    """
    booth = create_test_booth()
    floor_plan = create_floor_plan()
    dealer = create_dealer()
    build = inject_delivered_unit(dealer["id"], floor_plan["id"])

    def booth_request(window_start, window_end):
        return api.create_quality_inspection(
            {
                "unit_build_id": build["id"],
                "inspection_type": "WATER_TEST",
                "test_booth_id": booth["id"],
                "window_start": window_start,
                "window_end": window_end,
            },
            inspector_headers,
        )

    equal_window = booth_request("2026-08-05T10:00:00Z", "2026-08-05T10:00:00Z")
    inverted_window = booth_request("2026-08-05T10:00:00Z", "2026-08-05T09:00:00Z")
    short_window = booth_request("2026-08-05T10:00:00Z", "2026-08-05T10:29:00Z")
    long_window = booth_request("2026-08-05T10:00:00Z", "2026-08-05T14:01:00Z")
    pdi_with_booth = api.create_quality_inspection(
        {
            "unit_build_id": build["id"],
            "inspection_type": "PDI",
            "test_booth_id": booth["id"],
        },
        inspector_headers,
    )
    backwards_clock = api.set_clock({"current_utc": "2026-08-01T00:00:00Z"}, plant_admin_headers)

    # window_end equal to window_start is not strictly after it.
    validate_error(equal_window, ApiErrorId.ERR_INVALID_REQUEST)
    validate_error(inverted_window, ApiErrorId.ERR_INVALID_REQUEST)
    # 29 minutes is below the 30 minute floor.
    validate_error(short_window, ApiErrorId.ERR_INVALID_REQUEST)
    # 241 minutes is above the 240 minute ceiling.
    validate_error(long_window, ApiErrorId.ERR_INVALID_REQUEST)
    # A pre-delivery inspection must omit the booth and the window.
    validate_error(pdi_with_booth, ApiErrorId.ERR_INVALID_REQUEST)
    # 2026-08-01T00:00:00Z is not strictly after itself.
    validate_error(backwards_clock, ApiErrorId.ERR_INVALID_REQUEST)

    _rows, meta = validate_paginated(
        api.list_quality_inspections(plant_admin_headers, {"unit_build_id": build["id"]})
    )
    assert meta["total_count"] == 0


def test_monthly_allocation_aggregate_rejects_the_second_slot(
    api, plant_admin_headers, scheduler_headers
):
    """PRD §3.3: "Multiply that by the dealer's `allocation_share_bp` and divide by 10000,
    rounding half up to two decimals: that is the dealer's `entitlement_hours`. Multiply
    the entitlement by 10500 basis points and divide by 10000, rounding half up to two
    decimals: that is the tolerance ceiling, which permits a five-percent
    oversubscription." and "Against that ceiling, sum the `station_hours_committed` of every
    slot belonging to this dealer's orders whose `status` is `RESERVED` or `CONSUMED` and
    whose `slot_date` falls in the same calendar month as the requested `slot_date`, again
    excluding the slot this request just released — that sum is the dealer's
    `allocation_hours_consumed` for the month. If that sum plus this order's
    `required_station_hours` exceeds the tolerance ceiling, the request fails with
    `ERR_DEALER_ALLOCATION_EXCEEDED`; landing exactly on the ceiling is admitted."

    Design: Corner/validations/monthly_allocation_aggregate_rejects_the_second_slot
    """
    floor_plan = create_floor_plan()
    option = create_option_item()
    dealer = create_dealer(dealer_code="D-SMALL", region="CENTRAL", allocation_share_bp=100)
    line = create_production_line()
    orders = []
    for _ in range(2):
        order = create_order(
            dealer["id"],
            floor_plan["id"],
            order_type="STOCK",
            selected_option_ids=[option["id"]],
            requested_delivery_date=DELIVERY_DATE,
        )
        orders.append(submit_order(order["id"], dealer["id"]))
    order_one, order_two = orders

    first_slot = validate_success(
        api.reserve_production_slot(
            order_one["id"],
            {
                "line_id": line["id"],
                "slot_date": "2026-08-05T00:00:00Z",
                "expected_unit_order_version": order_one["version"],
            },
            scheduler_headers,
        ),
        201,
    )
    refused = api.reserve_production_slot(
        order_two["id"],
        {
            "line_id": line["id"],
            "slot_date": "2026-08-06T00:00:00Z",
            "expected_unit_order_version": order_two["version"],
        },
        scheduler_headers,
    )
    dealer_after = validate_success(api.get_dealer(dealer["id"], plant_admin_headers))

    # 0.00 + 41.00 fits inside the 50.40 tolerance.
    assert first_slot["id"] is not None
    assert_hours(first_slot["station_hours_committed"], "41.00")
    # 41.00 + 41.00 = 82.00 over the whole August bucket, even though 2026-08-06 is a
    # different day and LINE-T still has 240.00 hours free on it.
    validate_error(refused, ApiErrorId.ERR_DEALER_ALLOCATION_EXCEEDED)
    assert_hours(dealer_after["entitlement_hours"], "48.00")
    assert_hours(dealer_after["allocation_hours_consumed"], "41.00")

    assert read_order(order_two["id"])["status"] == "CONFIG_VALIDATED"
    _rows, meta = validate_paginated(
        api.list_production_slots(plant_admin_headers, {"unit_order_id": order_two["id"]})
    )
    assert meta["total_count"] == 0


def test_floor_plan_funding_requirement_applies_only_to_stock_orders(
    api, plant_admin_headers, scheduler_headers, inspector_headers, inspector_2_headers
):
    """PRD §3.7: "And the funding gate applies to inventory units only: a `STOCK` order may
    ship only when its `financing_status` is `FLOOR_PLAN_FUNDED`, else
    `ERR_FLOOR_PLAN_FUNDING_REQUIRED`; `SOLD` and `DEMO` orders carry no such requirement."
    and "`final_invoice_cents` is then the discounted subtotal plus freight plus the
    overtime surcharge plus the rework surcharge, minus the quality credit."

    Design: Corner/validations/floor_plan_funding_requirement_applies_only_to_stock_orders
    """
    kit, order, build = tow_build_at_station("FINISH", order_type="STOCK")
    dealer_headers = make_dealer_principal_headers(kit["dealer"]["id"])
    advance_build(build["id"], "WATER_TEST", 5.00)
    water_test = schedule_booth_inspection(
        build["id"],
        kit["booth"]["id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        headers=inspector_headers,
    )
    water_test_done = complete_inspection(water_test["id"], 3, False, headers=inspector_headers)
    advance_build(build["id"], "PDI", 3.00)
    pdi = schedule_pdi(build["id"], headers=inspector_2_headers)
    pdi_done = complete_inspection(pdi["id"], 2, False, headers=inspector_2_headers)
    ready = advance_build(build["id"], "READY_TO_SHIP", 2.00)

    refused = api.ship_order(order["id"], scheduler_headers)
    # The refused shipment must leave both rows exactly where they stood, so the
    # snapshot is taken before funding moves the order on.
    order_after_refusal = read_order(order["id"])
    build_after_refusal = read_build(build["id"])
    requested = validate_success(api.request_funding(order["id"], dealer_headers))
    approved = validate_success(
        api.funding_decision(order["id"], {"decision": "APPROVED"}, plant_admin_headers)
    )
    shipped = validate_success(api.ship_order(order["id"], scheduler_headers))

    # The safety band is clear before the fiscal band is reached.
    assert water_test_done["result"] == "PASS"
    assert pdi_done["result"] == "PASS"
    assert ready["current_station"] == "READY_TO_SHIP"
    # The order is BUILT, NOT_FINANCED and of type STOCK.
    validate_error(refused, ApiErrorId.ERR_FLOOR_PLAN_FUNDING_REQUIRED)
    assert order_after_refusal["status"] == "BUILT"
    assert order_after_refusal["financing_status"] == "NOT_FINANCED"
    assert build_after_refusal["current_station"] == "READY_TO_SHIP"
    assert requested["financing_status"] == "FUNDING_REQUESTED"
    assert approved["financing_status"] == "FLOOR_PLAN_FUNDED"
    assert_cents(approved["financed_principal_cents"], 5958315)
    assert shipped["status"] == "SHIPPED"
    assert read_build(build["id"])["current_station"] == "SHIPPED"
    # No overtime (40.00 actual against 41.00 planned), no rework, and a 7500 cent
    # quality credit for 5 defect points.
    assert_cents(shipped["final_invoice_cents"], 6612850)


def test_dealer_curtailment_delinquency_cascades_onto_a_sibling_order(
    api, plant_admin_headers, scheduler_headers
):
    """PRD §2.8: "**Fiscal**, last of all and in this internal order:
    `ERR_DEALER_CREDIT_HOLD` (the dealer's `credit_status` is `CREDIT_HOLD`), then
    `ERR_DEALER_CURTAILMENT_DELINQUENT` (some order of the dealer is `CURTAILED` with a
    positive `curtailment_due_cents`), then `ERR_DEALER_ALLOCATION_EXCEEDED`, then
    `ERR_FLOOR_PLAN_FUNDING_REQUIRED`, then `ERR_GOODWILL_BUDGET_EXHAUSTED`."
    PRD §3.7: "At 365 days or more the cumulative requirement is 5000 basis points of
    `financed_principal_cents`; at 270 days or more but under 365 it is 2500 basis points;
    at 180 days or more but under 270 it is 1000 basis points; and below 180 days nothing is
    required. Each boundary is inclusive — a coach exactly 180 days old already owes the
    first stage." and "A payment that leaves the paid total short of the full
    principal adds `amount_cents` to `curtailment_paid_cents` and recomputes
    `curtailment_due_cents`; if the order was `CURTAILED` and the recomputed amount due
    reaches zero, it returns `CURTAILED → FLOOR_PLAN_FUNDED`, where a later sweep may curtail
    it again — this is a genuine cycle, not a one-way door."

    Design: Corner/validations/dealer_curtailment_delinquency_cascades_onto_a_sibling_order
    """
    floor_plan = create_floor_plan()
    option = create_option_item()
    dealer = create_dealer()
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    line = create_production_line()

    order_one = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date=DELIVERY_DATE,
    )
    submit_order(order_one["id"], dealer["id"])
    validate_success(api.request_funding(order_one["id"], dealer_headers))
    funded_one = validate_success(
        api.funding_decision(order_one["id"], {"decision": "APPROVED"}, plant_admin_headers)
    )
    # Exactly 180 whole days after funded_at.
    advance_clock("2027-01-28T00:00:00Z")
    close = run_daily_close()
    order_two = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2027-04-01T00:00:00Z",
    )
    order_two = submit_order(order_two["id"], dealer["id"])

    aged = validate_success(api.get_unit_order(order_one["id"], plant_admin_headers))
    slot_payload = {
        "line_id": line["id"],
        "slot_date": "2027-02-05T00:00:00Z",
        "expected_unit_order_version": order_two["version"],
    }
    refused = api.reserve_production_slot(order_two["id"], slot_payload, scheduler_headers)
    version_after_refusal = read_order(order_two["id"])["version"]
    dealer_at_refusal = read_dealer(dealer["id"])
    paid = validate_success(
        api.floor_plan_payment(order_one["id"], {"amount_cents": 595832}, dealer_headers)
    )
    retried = validate_success(
        api.reserve_production_slot(order_two["id"], slot_payload, scheduler_headers), 201
    )

    assert_cents(funded_one["financed_principal_cents"], 5958315)
    # At age exactly 180 days the stage-one requirement of 1000 bp turns positive.
    assert close["curtailed_order_count"] == 1
    assert aged["financing_status"] == "CURTAILED"
    assert_cents(aged["curtailment_due_cents"], 595832)
    # Order two is itself neither funded nor delinquent, yet the dealer-wide check bites.
    validate_error(refused, ApiErrorId.ERR_DEALER_CURTAILMENT_DELINQUENT)
    # Not a credit hold: utilisation is far below the hold threshold.
    assert dealer_at_refusal["credit_utilization_bp"] == 595
    assert dealer_at_refusal["credit_status"] != "CREDIT_HOLD"
    assert paid["financing_status"] == "FLOOR_PLAN_FUNDED"
    assert_cents(paid["curtailment_paid_cents"], 595832)
    assert_cents(paid["curtailment_due_cents"], 0)
    # The payment alone unblocks the sibling, with no change to order two.
    assert retried["sequence_position"] == 1
    assert retried["line_id"] == line["id"]
    assert retried["slot_date"].startswith("2027-02-05")
    assert version_after_refusal == order_two["version"]


def test_station_hours_limit_rejects_a_single_over_long_unit(api):
    """PRD §3.2: "A configuration whose `required_station_hours` comes out above 96.00 hours
    is more coach than the plant will build in one pass and is rejected at submit with
    `ERR_STATION_HOURS_LIMIT_EXCEEDED`." and "Then choose a class factor from the floor
    plan's `chassis_class`: a towable is 1.00, a Class C is 1.10, and a Class A is 1.15."

    Design: Corner/validations/station_hours_limit_rejects_a_single_over_long_unit
    """
    floor_plan = create_floor_plan(
        model_code="FP-BIG",
        chassis_class="CLASS_A",
        length_ft=34,
        base_msrp_cents=18500000,
        base_station_hours=80.00,
        base_dry_weight_lbs=22400,
        gvwr_lbs=26000,
        required_wheelbase_in=242,
        electrical_service_amps=50,
        fresh_water_capacity_gal=90,
    )
    big_option = _finish_option("OPT-BIG5", added_station_hours=5.00)
    dealer = create_dealer(dealer_code="D-WEST", region="WEST")
    dealer_headers = make_dealer_principal_headers(dealer["id"])

    order_bare = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[],
        requested_delivery_date=DELIVERY_DATE,
    )
    order_long = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[big_option["id"]],
        requested_delivery_date=DELIVERY_DATE,
    )

    bare = validate_success(api.submit_order(order_bare["id"], dealer_headers))
    refused = api.submit_order(order_long["id"], dealer_headers)

    # 80.00 * 1.00 * 1.15 sits under the ceiling.
    assert_hours(order_bare["required_station_hours"], "92.00")
    assert bare["status"] == "CONFIG_VALIDATED"
    # 85.00 * 1.00 * 1.15: the 5.00 hour option contributes 5.75 hours after the class
    # factor, which is what crosses 96.00.
    assert_hours(order_long["required_station_hours"], "97.75")
    validate_error(refused, ApiErrorId.ERR_STATION_HOURS_LIMIT_EXCEEDED)

    stored = read_order(order_long["id"])
    assert stored["status"] == "DRAFT"
    assert stored["version"] == 1
    # The total is stored even though the order cannot be validated.
    assert_hours(stored["required_station_hours"], "97.75")
    # No physical ceiling was breached.
    assert stored["config_weight_lbs"] == 22400
    assert stored["total_amp_draw"] == 0
    assert stored["total_water_demand_gal"] == 0
