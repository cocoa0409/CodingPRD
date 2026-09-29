"""Refusal behaviour: chassis matching, pinned configuration drift, component lot
protection, the quality gates along a build's path, and the two fiscal ceilings.
"""
from test_helpers import (
    ApiErrorId,
    advance_build,
    assert_cents,
    build_tow_kit,
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
    draft_campaign,
    inject_delivered_unit,
    make_dealer_principal_headers,
    match_chassis,
    open_campaign,
    read_dealer,
    read_order,
    release_to_line,
    request_funding,
    reserve_slot,
    submit_order,
    tow_slotted_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def walk_to_rough_in(kit):
    """Walk a towable order through to a live build standing at ROUGH_IN."""
    kit, order, _slot = tow_slotted_order(kit=kit)
    match_chassis(order["id"])
    build = release_to_line(order["id"])
    for station in ("SIDEWALL_LAM", "ROOF_SET", "ROUGH_IN"):
        build = advance_build(build["id"], station, 6.00)
    return kit, read_order(order["id"]), build


def test_matching_reports_no_candidate_then_holds_one_chassis_per_order(
    api, plant_admin_headers, scheduler_headers
):
    """PRD §3.4: "It takes no body and demands a great deal of alignment: the order must be `SLOTTED`; a chassis must exist whose `matched_unit_order_id` names this order and whose `status` is `MATCHED`, else `ERR_CHASSIS_NOT_MATCHED`; the order's slot must still be `RESERVED` rather than expired or released; the dealer's `status` must be `ACTIVE` and its `credit_status` must not be `CREDIT_HOLD`, and it must carry no delinquent curtailment; and the pinned floor-plan and option versions must still match, else `ERR_CONFIG_REFERENCE_STALE`."

    PRD §3.4: "When the eligible set is empty the request is rejected with `ERR_NO_MATCHING_CHASSIS`."
    PRD §3.4: "Matching is available while the order's `status` is `CONFIG_VALIDATED` or `SLOTTED`, and only when no other chassis already names this order in its `matched_unit_order_id`; an order that already holds a matched or installed chassis is rejected with `ERR_ORDER_ALREADY_MATCHED`."
    PRD §3.4: "It stands at `current_station` `CHASSIS_PREP` with `actual_station_hours` `0.00`, `rework_count` 0, `defect_points_total` 0, `water_test_passed` false, `pdi_passed` false, and `recall_hold` false. In the same operation the slot moves `RESERVED → CONSUMED` and the chassis moves `MATCHED → INSTALLED`."

    Design: Corner/errors/chassis_errors_not_matched_then_no_candidate_then_already_matched
    """
    kit = build_tow_kit(with_chassis=False, with_booth=False)
    kit, order, _slot = tow_slotted_order(kit=kit)
    order_id = order["id"]
    assert order["status"] == "SLOTTED"

    validate_error(
        api.release_to_line(order_id, scheduler_headers), ApiErrorId.ERR_CHASSIS_NOT_MATCHED
    )
    validate_error(
        api.match_chassis(order_id, scheduler_headers), ApiErrorId.ERR_NO_MATCHING_CHASSIS
    )

    chassis = create_chassis_receipt(
        kit["supplier"]["id"],
        chassis_serial="CH-T1",
        chassis_class="TOWABLE",
        gvwr_lbs=9000,
        wheelbase_in=180,
    )
    matched = validate_success(api.match_chassis(order_id, scheduler_headers))
    assert matched["id"] == chassis["id"]
    assert matched["status"] == "MATCHED"

    validate_error(
        api.match_chassis(order_id, scheduler_headers), ApiErrorId.ERR_ORDER_ALREADY_MATCHED
    )
    held = validate_success(api.get_chassis_receipt(chassis["id"], plant_admin_headers))
    assert held["matched_unit_order_id"] == order_id

    build = validate_success(api.release_to_line(order_id, scheduler_headers), 201)
    assert build["id"] is not None
    assert build["current_station"] == "CHASSIS_PREP"
    assert (
        validate_success(api.get_chassis_receipt(chassis["id"], plant_admin_headers))["status"]
        == "INSTALLED"
    )


def test_pinned_floor_plan_and_option_drift_are_both_reported_as_stale(
    api, plant_admin_headers, scheduler_headers
):
    """PRD §3.2: "An order that clears all of it is stamped: the roll-up is recomputed, `provisional_invoice_cents` is written, `locked_floor_plan_version` is pinned to the floor plan's current `version`, and `locked_option_versions` is pinned as one entry per selected option carrying that option's identifier, its `version`, and its `price_cents` at the moment of submit."

    PRD §3.4: "Before selecting, the system re-checks that the order's pinned references still hold — if the floor plan's current `version` no longer equals `locked_floor_plan_version`, or if any entry of `locked_option_versions` no longer matches its option's current `version`, the request fails with `ERR_CONFIG_REFERENCE_STALE`, and the dealer must revise and resubmit."
    PRD §3.1: "A floor plan may later be repriced through `base_msrp_cents` or retired by setting `status` to `RETIRED`; either edit increments the plan's `version`, which invalidates the pinned reference on every already-submitted order that names it."
    PRD §3.1: "Repricing `price_cents` or setting `status` to `DISCONTINUED` increments the option's `version`, invalidating the matching pinned entry on every already-submitted order that selected it."

    Design: Corner/errors/config_reference_stale_is_reported_for_floor_plan_and_option_drift
    """
    supplier = create_supplier(
        supplier_code="SUP-CH", name="Cascade Chassis Works", component_categories=["CHASSIS"]
    )
    plan_a = create_floor_plan(model_code="FP-TOW")
    plan_b = create_floor_plan(model_code="FP-TOW2")
    option = create_option_item(option_code="OPT-E1")
    dealer = create_dealer(dealer_code="D-TOW")
    line = create_production_line(line_code="LINE-T")
    chassis_1 = create_chassis_receipt(
        supplier["id"],
        chassis_serial="CH-T1",
        chassis_class="TOWABLE",
        gvwr_lbs=9000,
        wheelbase_in=180,
    )
    create_chassis_receipt(
        supplier["id"],
        chassis_serial="CH-T2",
        chassis_class="TOWABLE",
        gvwr_lbs=9000,
        wheelbase_in=180,
    )

    order_a = create_order(
        dealer["id"],
        plan_a["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )
    submitted_a = submit_order(order_a["id"], dealer["id"])
    assert submitted_a["locked_floor_plan_version"] == 1
    slot_a = reserve_slot(order_a["id"], line["id"], "2026-08-05T00:00:00Z", submitted_a["version"])
    match_chassis(order_a["id"])
    invoice_a_before = read_order(order_a["id"])["provisional_invoice_cents"]

    order_b = create_order(
        dealer["id"],
        plan_b["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )
    submitted_b = submit_order(order_b["id"], dealer["id"])
    invoice_b_before = submitted_b["provisional_invoice_cents"]

    repriced_plan = validate_success(
        api.patch_floor_plan(plan_a["id"], {"base_msrp_cents": 8400000}, plant_admin_headers)
    )
    assert repriced_plan["version"] == 2

    validate_error(
        api.release_to_line(order_a["id"], scheduler_headers),
        ApiErrorId.ERR_CONFIG_REFERENCE_STALE,
    )
    assert read_order(order_a["id"])["status"] == "SLOTTED"
    assert (
        validate_success(api.get_production_slot(slot_a["id"], scheduler_headers))["status"]
        == "RESERVED"
    )
    assert (
        validate_success(api.get_chassis_receipt(chassis_1["id"], plant_admin_headers))["status"]
        == "MATCHED"
    )

    repriced_option = validate_success(
        api.patch_option_item(option["id"], {"price_cents": 120000}, plant_admin_headers)
    )
    assert repriced_option["version"] == 2

    validate_error(
        api.match_chassis(order_b["id"], scheduler_headers), ApiErrorId.ERR_CONFIG_REFERENCE_STALE
    )
    assert read_order(order_b["id"])["floor_plan_id"] == plan_b["id"]

    pinned = read_order(order_b["id"])["locked_option_versions"]
    assert len(pinned) == 1
    assert pinned[0]["version"] == 1
    assert_cents(pinned[0]["price_cents"], 100000)

    assert_cents(read_order(order_a["id"])["provisional_invoice_cents"], invoice_a_before)
    assert_cents(read_order(order_b["id"])["provisional_invoice_cents"], invoice_b_before)


def test_installation_refuses_more_pieces_than_a_lot_holds_and_refuses_a_frozen_lot(
    api, supervisor_headers, recall_coordinator_headers
):
    """PRD §3.5: "A lot under recall quarantine cannot be installed and is refused with `ERR_LOT_QUARANTINED`; a `quantity` above the lot's `quantity_available` is refused with `ERR_LOT_QUANTITY_INSUFFICIENT`."

    PRD §3.5: "On success the lot's `quantity_available` decreases by the installed quantity and its `quantity_installed` increases by the same amount, conserving the piece total, and a lot whose `quantity_available` reaches exactly zero moves `AVAILABLE → DEPLETED`."
    PRD §3.5: "The new installation starts at `status` `INSTALLED` with `recall_campaign_id` null."
    PRD §3.9: "Every matching lot moves to `QUARANTINED` — from `AVAILABLE` or from `DEPLETED` alike — by adding its remaining `quantity_available` to its `quantity_quarantined` and then setting `quantity_available` to zero."
    PRD §3.5: "Installations are listable with filters on `unit_build_id`, `component_lot_id`, `recall_campaign_id`, and `status`."

    Design: Corner/errors/installation_errors_insufficient_quantity_then_quarantined_lot
    """
    kit = build_tow_kit(
        with_booth=False,
        supplier={
            "supplier_code": "SUP-C",
            "name": "Cascade Components",
            "component_categories": ["APPLIANCE", "CHASSIS"],
        },
    )
    lot_1 = create_component_lot(
        kit["supplier"]["id"],
        part_number="PN-FRIDGE",
        lot_code="L-1",
        category="APPLIANCE",
        quantity_received=2,
    )
    lot_2 = create_component_lot(
        kit["supplier"]["id"],
        part_number="PN-FRIDGE",
        lot_code="L-2",
        category="APPLIANCE",
        quantity_received=10,
    )
    kit, _order, build = walk_to_rough_in(kit)

    campaign = draft_campaign(
        kit["supplier"]["id"],
        campaign_code="RC-L2",
        part_number="PN-FRIDGE",
        lot_codes=["L-2"],
        severity="COMPLIANCE",
    )
    opened = open_campaign(campaign["id"])
    assert opened["status"] == "OPEN"

    validate_error(
        api.create_component_installation(
            {
                "unit_build_id": build["id"],
                "component_lot_id": lot_1["id"],
                "station": "ROUGH_IN",
                "quantity": 3,
            },
            supervisor_headers,
        ),
        ApiErrorId.ERR_LOT_QUANTITY_INSUFFICIENT,
    )
    assert (
        validate_success(api.get_component_lot(lot_1["id"], supervisor_headers))[
            "quantity_available"
        ]
        == 2
    )

    installation = validate_success(
        api.create_component_installation(
            {
                "unit_build_id": build["id"],
                "component_lot_id": lot_1["id"],
                "station": "ROUGH_IN",
                "quantity": 2,
            },
            supervisor_headers,
        ),
        201,
    )
    assert installation["status"] == "INSTALLED"

    depleted = validate_success(api.get_component_lot(lot_1["id"], supervisor_headers))
    assert depleted["status"] == "DEPLETED"
    assert depleted["quantity_available"] == 0
    assert depleted["quantity_installed"] == 2

    validate_error(
        api.create_component_installation(
            {
                "unit_build_id": build["id"],
                "component_lot_id": lot_1["id"],
                "station": "ROUGH_IN",
                "quantity": 1,
            },
            supervisor_headers,
        ),
        ApiErrorId.ERR_LOT_QUANTITY_INSUFFICIENT,
    )

    frozen = validate_success(api.get_component_lot(lot_2["id"], recall_coordinator_headers))
    assert frozen["status"] == "QUARANTINED"
    assert frozen["quantity_quarantined"] == 10
    assert frozen["quantity_available"] == 0

    validate_error(
        api.create_component_installation(
            {
                "unit_build_id": build["id"],
                "component_lot_id": lot_2["id"],
                "station": "ROUGH_IN",
                "quantity": 1,
            },
            supervisor_headers,
        ),
        ApiErrorId.ERR_LOT_QUARANTINED,
    )

    _rows, meta = validate_paginated(
        api.list_component_installations(supervisor_headers, params={"unit_build_id": build["id"]})
    )
    assert meta["total_count"] == 1


def test_quality_gates_refuse_a_down_booth_an_early_grade_and_unpassed_tests(
    api, plant_admin_headers, supervisor_headers, inspector_headers, inspector_2_headers
):
    """PRD §3.5: "Entering `PDI` from `WATER_TEST` requires the build's `water_test_passed` to be true, else `ERR_WATER_TEST_NOT_PASSED`. Entering `READY_TO_SHIP` from `PDI` requires `pdi_passed` to be true, else `ERR_PDI_NOT_PASSED`. Reaching `READY_TO_SHIP` is also the moment the paperwork catches up: the owning order moves `IN_PRODUCTION → BUILT` in the same operation."

    PRD §3.1: "A `PlantAdmin` may take a booth `DOWN`, after which new reservations are rejected with `ERR_BOOTH_NOT_OPEN` while already-`SCHEDULED` windows are left untouched."
    PRD §3.6: "The build must be standing at the right station: a `WATER_TEST` inspection requires `current_station` to be `WATER_TEST`, a `PDI` inspection requires `current_station` to be `PDI`, and a `FUNCTIONAL` inspection is accepted while the build stands at either `WATER_TEST` or `PDI`. A mismatch is rejected with `ERR_INSPECTION_STATION_MISMATCH`."
    PRD §3.6: "A `PASS` or `CONDITIONAL` on a `WATER_TEST` sets the build's `water_test_passed` to true and leaves `current_station` where it is — a conditional pass is a pass, and the coach proceeds."
    PRD §2.11: "When a `QualityInspector` completes a `PDI` inspection on a build, their `X-User-ID` must differ from the `completed_by_user_id` recorded on that build's most recently completed `WATER_TEST` inspection."
    PRD §3.6: "Completion always does two things regardless of grade: it stamps `completed_by_user_id` from the acting `X-User-ID`, and it adds the recorded `defect_points` to the build's `defect_points_total`, which accumulates over every completed inspection and later becomes a credit against the coach's invoice."

    Design: Corner/errors/quality_gate_errors_from_booth_down_to_station_mismatch_to_unpassed_tests
    """
    supplier = create_supplier(
        supplier_code="SUP-CH", name="Cascade Chassis Works", component_categories=["CHASSIS"]
    )
    floor_plan = create_floor_plan(model_code="FP-TOW")
    option = create_option_item(option_code="OPT-E1")
    dealer = create_dealer(dealer_code="D-TOW")
    line = create_production_line(line_code="LINE-T")
    booth = create_test_booth(booth_code="BOOTH-W")
    create_chassis_receipt(
        supplier["id"],
        chassis_serial="CH-T1",
        chassis_class="TOWABLE",
        gvwr_lbs=9000,
        wheelbase_in=180,
    )

    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="SOLD",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )
    submitted = submit_order(order["id"], dealer["id"])
    reserve_slot(order["id"], line["id"], "2026-08-05T00:00:00Z", submitted["version"])
    match_chassis(order["id"])
    build = release_to_line(order["id"])
    build_id = build["id"]
    for station in ("SIDEWALL_LAM", "ROOF_SET", "ROUGH_IN", "APPLIANCE_INSTALL", "FINISH"):
        advance_build(build_id, station, 6.00)
    at_water_test = advance_build(build_id, "WATER_TEST", 5.00)
    assert at_water_test["current_station"] == "WATER_TEST"
    assert at_water_test["water_test_passed"] is False

    validate_error(
        api.advance_build(build_id, {"to_station": "PDI", "station_hours_used": 1.00}, supervisor_headers),
        ApiErrorId.ERR_WATER_TEST_NOT_PASSED,
    )

    booth_down = validate_success(
        api.set_test_booth_status(booth["id"], {"status": "DOWN"}, plant_admin_headers)
    )
    assert booth_down["status"] == "DOWN"

    validate_error(
        api.create_quality_inspection(
            {
                "unit_build_id": build_id,
                "inspection_type": "WATER_TEST",
                "test_booth_id": booth["id"],
                "window_start": "2026-08-05T09:00:00Z",
                "window_end": "2026-08-05T10:00:00Z",
            },
            inspector_headers,
        ),
        ApiErrorId.ERR_BOOTH_NOT_OPEN,
    )
    _none, none_meta = validate_paginated(
        api.list_quality_inspections(inspector_headers, params={"unit_build_id": build_id})
    )
    assert none_meta["total_count"] == 0

    booth_open = validate_success(
        api.set_test_booth_status(booth["id"], {"status": "OPEN"}, plant_admin_headers)
    )
    assert booth_open["status"] == "OPEN"

    pdi = validate_success(
        api.create_quality_inspection(
            {"unit_build_id": build_id, "inspection_type": "PDI"}, inspector_headers
        ),
        201,
    )
    assert pdi["status"] == "SCHEDULED"

    validate_error(
        api.complete_inspection(
            pdi["id"], {"defect_points": 1, "leak_detected": False}, inspector_headers
        ),
        ApiErrorId.ERR_INSPECTION_STATION_MISMATCH,
    )
    assert (
        validate_success(api.get_quality_inspection(pdi["id"], inspector_headers))["status"]
        == "SCHEDULED"
    )

    water_test = validate_success(
        api.create_quality_inspection(
            {
                "unit_build_id": build_id,
                "inspection_type": "WATER_TEST",
                "test_booth_id": booth["id"],
                "window_start": "2026-08-05T09:00:00Z",
                "window_end": "2026-08-05T10:00:00Z",
            },
            inspector_headers,
        ),
        201,
    )
    graded_water_test = validate_success(
        api.complete_inspection(
            water_test["id"], {"defect_points": 3, "leak_detected": False}, inspector_headers
        )
    )
    assert graded_water_test["result"] == "PASS"
    assert (
        validate_success(api.get_unit_build(build_id, supervisor_headers))["water_test_passed"]
        is True
    )

    at_pdi = validate_success(
        api.advance_build(build_id, {"to_station": "PDI", "station_hours_used": 1.00}, supervisor_headers)
    )
    assert at_pdi["current_station"] == "PDI"
    assert at_pdi["pdi_passed"] is False

    validate_error(
        api.advance_build(
            build_id, {"to_station": "READY_TO_SHIP", "station_hours_used": 1.00}, supervisor_headers
        ),
        ApiErrorId.ERR_PDI_NOT_PASSED,
    )

    validate_error(
        api.complete_inspection(
            pdi["id"], {"defect_points": 2, "leak_detected": False}, inspector_headers
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    graded_pdi = validate_success(
        api.complete_inspection(
            pdi["id"], {"defect_points": 2, "leak_detected": False}, inspector_2_headers
        )
    )
    assert graded_pdi["result"] == "PASS"

    ready = validate_success(
        api.advance_build(
            build_id, {"to_station": "READY_TO_SHIP", "station_hours_used": 1.00}, supervisor_headers
        )
    )
    assert ready["current_station"] == "READY_TO_SHIP"
    assert read_order(order["id"])["status"] == "BUILT"
    assert ready["defect_points_total"] == 5
    assert ready["rework_count"] == 0


def test_floor_plan_payment_and_goodwill_are_both_capped(
    api, plant_admin_headers, warranty_admin_headers
):
    """PRD §3.7: "The amount must be greater than zero and no greater than the remaining principal — that is, no greater than `financed_principal_cents` minus `curtailment_paid_cents` — and an amount above that remainder is rejected with `ERR_PAYMENT_EXCEEDS_PRINCIPAL`."

    PRD §3.7: "A payment that brings the paid total to exactly the full `financed_principal_cents` retires the advance: `curtailment_paid_cents` becomes the full principal, `curtailment_due_cents` becomes zero, and `financing_status` moves to the terminal `PAID_OFF` from either `FLOOR_PLAN_FUNDED` or `CURTAILED`, removing the unit from the dealer's exposure set."
    PRD §3.7: "An approval requires a positive `provisional_invoice_cents` and advances `financing_status` `FUNDING_REQUESTED → FLOOR_PLAN_FUNDED`: the plant advances 9000 basis points of the provisional invoice, so `financed_principal_cents` is the provisional invoice multiplied by 9000, divided by 10000, and rounded half up to whole cents, and `funded_at` is stamped from the logical clock."
    PRD §3.8: "An approval is blocked when goodwill is requested and the dealer's remaining goodwill budget is zero, which is `ERR_GOODWILL_BUDGET_EXHAUSTED`; a claim requesting no goodwill still approves against an exhausted budget."
    PRD §3.8: "Goodwill is throttled by independent ceilings and the authorised amount is the smallest of them. The candidates are the dealer's `goodwill_requested_cents`; the tier ceiling, which is 75000 cents for `TIER_A`, 150000 cents for `TIER_B`, and zero for `TIER_C` — the largest claims carry no goodwill authority at all; the percentage ceiling, which is 2000 basis points of the step-3 subtotal, computed by multiplying the subtotal by 2000, dividing by 10000, and rounding half up to whole cents; and the dealer's remaining budget, which is its `goodwill_budget_cents` minus its `goodwill_used_cents`."
    PRD §3.8: "When `component_lot_id` is null there is no supplier to charge and `supplier_chargeback_cents` is zero."

    Design: Corner/errors/fiscal_writes_reject_overpayment_and_exhausted_goodwill
    """
    floor_plan = create_floor_plan(model_code="FP-TOW")
    option = create_option_item(option_code="OPT-E1")
    dealer = create_dealer(dealer_code="D-TOW", goodwill_budget_cents=74140)
    dealer_id = dealer["id"]
    dealer_headers = make_dealer_principal_headers(dealer_id)

    order = create_order(
        dealer_id,
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )
    submit_order(order["id"], dealer_id)
    request_funding(order["id"], dealer_id)
    funded = decide_funding(order["id"], "APPROVED")
    assert_cents(funded["financed_principal_cents"], 5958315)

    build_1 = inject_delivered_unit(dealer_id, floor_plan["id"])
    build_2 = inject_delivered_unit(dealer_id, floor_plan["id"])
    build_3 = inject_delivered_unit(dealer_id, floor_plan["id"])

    validate_error(
        api.floor_plan_payment(order["id"], {"amount_cents": 5958316}, dealer_headers),
        ApiErrorId.ERR_PAYMENT_EXCEEDS_PRINCIPAL,
    )

    paid_off = validate_success(
        api.floor_plan_payment(order["id"], {"amount_cents": 5958315}, dealer_headers)
    )
    assert paid_off["financing_status"] == "PAID_OFF"
    assert_cents(paid_off["curtailment_paid_cents"], 5958315)
    assert_cents(read_dealer(dealer_id)["financed_exposure_cents"], 0)

    claim_1 = validate_success(
        api.create_warranty_claim(
            {
                "unit_build_id": build_1["id"],
                "claim_type": "STRUCTURAL",
                "labor_hours": 8.00,
                "parts_cost_cents": 250000,
                "narrative": "sidewall delamination at the front cap",
                "goodwill_requested_cents": 150000,
            },
            dealer_headers,
        ),
        201,
    )
    approved_1 = validate_success(
        api.decide_claim(claim_1["id"], {"decision": "APPROVED"}, warranty_admin_headers)
    )
    assert approved_1["authority_tier"] == "TIER_B"
    assert_cents(approved_1["labor_reimbursement_cents"], 83200)
    assert_cents(approved_1["parts_reimbursement_cents"], 287500)
    assert_cents(approved_1["goodwill_authorized_cents"], 74140)
    assert_cents(approved_1["total_reimbursement_cents"], 444840)
    assert_cents(read_dealer(dealer_id)["goodwill_used_cents"], 74140)

    claim_2 = validate_success(
        api.create_warranty_claim(
            {
                "unit_build_id": build_2["id"],
                "claim_type": "STRUCTURAL",
                "labor_hours": 8.00,
                "parts_cost_cents": 250000,
                "narrative": "second sidewall delamination",
                "goodwill_requested_cents": 5000,
            },
            dealer_headers,
        ),
        201,
    )
    validate_error(
        api.decide_claim(claim_2["id"], {"decision": "APPROVED"}, warranty_admin_headers),
        ApiErrorId.ERR_GOODWILL_BUDGET_EXHAUSTED,
    )
    assert (
        validate_success(api.get_warranty_claim(claim_2["id"], plant_admin_headers))["status"]
        == "SUBMITTED"
    )

    claim_3 = validate_success(
        api.create_warranty_claim(
            {
                "unit_build_id": build_3["id"],
                "claim_type": "STRUCTURAL",
                "labor_hours": 8.00,
                "parts_cost_cents": 250000,
                "narrative": "third sidewall delamination, no goodwill sought",
            },
            dealer_headers,
        ),
        201,
    )
    approved_3 = validate_success(
        api.decide_claim(claim_3["id"], {"decision": "APPROVED"}, warranty_admin_headers)
    )
    assert approved_3["status"] == "APPROVED"
    assert_cents(approved_3["goodwill_authorized_cents"], 0)
    assert_cents(approved_3["total_reimbursement_cents"], 370700)

    assert_cents(approved_1["supplier_chargeback_cents"], 0)
    assert_cents(
        validate_success(api.get_warranty_claim(claim_2["id"], plant_admin_headers))[
            "supplier_chargeback_cents"
        ],
        0,
    )
    assert_cents(approved_3["supplier_chargeback_cents"], 0)
