"""Station cycles, the two order dimensions, and the plant's multi-hop cascades."""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    assert_hours,
    assert_two_decimals,
    create_chassis_receipt,
    create_component_lot,
    create_dealer,
    create_floor_plan,
    create_option_item,
    create_production_line,
    create_supplier,
    create_test_booth,
    advance_build,
    advance_clock,
    create_order,
    decide_funding,
    draft_campaign,
    install_pieces,
    make_dealer_principal_headers,
    match_chassis,
    release_to_line,
    request_funding,
    reserve_slot,
    schedule_booth_inspection,
    submit_order,
    complete_inspection,
    validate_error,
    validate_success,
)

# ─── Master data of the Class A plant used by every case below ──────────────

SUP_CH = {
    "supplier_code": "SUP-CH",
    "name": "Cascade Chassis Works",
    "component_categories": ["CHASSIS"],
}
SUP_APP = {
    "supplier_code": "SUP-APP",
    "name": "Northline Appliance",
    "component_categories": ["APPLIANCE"],
}
FP_3410 = {
    "model_code": "FP-3410",
    "chassis_class": "CLASS_A",
    "length_ft": 34,
    "base_msrp_cents": 18500000,
    "base_station_hours": 46.00,
    "base_dry_weight_lbs": 22400,
    "gvwr_lbs": 26000,
    "required_wheelbase_in": 242,
    "electrical_service_amps": 50,
    "fresh_water_capacity_gal": 90,
}
OPT_WASH = {
    "option_code": "OPT-WASH",
    "category": "APPLIANCE",
    "install_station": "APPLIANCE_INSTALL",
    "price_cents": 245500,
    "weight_lbs": 180,
    "added_station_hours": 3.00,
    "amp_draw": 12,
    "water_demand_gal": 0,
}
OPT_AC2 = {
    "option_code": "OPT-AC2",
    "category": "ELECTRICAL",
    "install_station": "ROOF_SET",
    "price_cents": 385000,
    "weight_lbs": 95,
    "added_station_hours": 2.50,
    "amp_draw": 16,
    "water_demand_gal": 0,
}
D_BIG = {
    "dealer_code": "D-BIG",
    "region": "WEST",
    "allocation_share_bp": 1500,
    "floor_plan_credit_limit_cents": 100000000,
    "goodwill_budget_cents": 500000,
}
LINE_A = {
    "line_code": "LINE-A",
    "chassis_class_supported": "CLASS_A",
    "daily_station_hour_capacity": 240.00,
    "max_units_per_day": 4,
}
BOOTH_1 = {
    "booth_code": "BOOTH-1",
    "booth_type": "WATER_TEST",
    "bay_count": 1,
    "turnaround_minutes": 30,
}
CHASSIS_0001 = {
    "chassis_serial": "CH-0001",
    "chassis_class": "CLASS_A",
    "gvwr_lbs": 26000,
    "wheelbase_in": 242,
}
SLOT_DATE = "2026-08-05T00:00:00Z"
DELIVERY_DATE = "2026-09-15T00:00:00Z"

# A SOLD FP-3410 carrying only OPT-AC2, priced per PRD §3.2 and §3.7:
# base line 18500000 at 2050 bp -> 14707500, the ELECTRICAL option line
# 385000 at 1725 bp -> 318588, freight 180000 + 34 * 4200 + WEST 95000 -> 417800.
SOLD_AC2_PROVISIONAL_CENTS = 15443888
# 9000 basis points of that provisional invoice, rounded half up.
SOLD_AC2_PRINCIPAL_CENTS = 13899499


def _instant(value):
    """Parse an ISO 8601 UTC timestamp so two instants compare by value."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _appliance_plant(lot_quantity: int = 20) -> dict:
    """FP-3410 with the single APPLIANCE option, one chassis and one appliance lot."""
    chassis_supplier = create_supplier(**SUP_CH)
    appliance_supplier = create_supplier(**SUP_APP)
    floor_plan = create_floor_plan(**FP_3410)
    option = create_option_item(**OPT_WASH)
    dealer = create_dealer(**D_BIG)
    line = create_production_line(**LINE_A)
    booth = create_test_booth(**BOOTH_1)
    chassis = create_chassis_receipt(chassis_supplier["id"], **CHASSIS_0001)
    lot = create_component_lot(
        appliance_supplier["id"],
        part_number="WH-6G-2026",
        lot_code="L-2211",
        category="APPLIANCE",
        quantity_received=lot_quantity,
    )
    return {
        "chassis_supplier": chassis_supplier,
        "appliance_supplier": appliance_supplier,
        "floor_plan": floor_plan,
        "option": option,
        "dealer": dealer,
        "line": line,
        "booth": booth,
        "chassis": chassis,
        "lot": lot,
    }


def _electrical_plant() -> dict:
    """FP-3410 with the single ELECTRICAL option and one chassis; no lot, no booth."""
    chassis_supplier = create_supplier(**SUP_CH)
    floor_plan = create_floor_plan(**FP_3410)
    option = create_option_item(**OPT_AC2)
    dealer = create_dealer(**D_BIG)
    line = create_production_line(**LINE_A)
    chassis = create_chassis_receipt(chassis_supplier["id"], **CHASSIS_0001)
    return {
        "chassis_supplier": chassis_supplier,
        "floor_plan": floor_plan,
        "option": option,
        "dealer": dealer,
        "line": line,
        "chassis": chassis,
    }


def _sold_order(plant: dict) -> dict:
    """A SOLD order on the plant's single option, submitted."""
    order = create_order(
        plant["dealer"]["id"],
        plant["floor_plan"]["id"],
        order_type="SOLD",
        selected_option_ids=[plant["option"]["id"]],
        requested_delivery_date=DELIVERY_DATE,
    )
    return submit_order(order["id"], plant["dealer"]["id"])


def _slot_and_match(plant: dict, order: dict) -> dict:
    slot = reserve_slot(order["id"], plant["line"]["id"], SLOT_DATE, order["version"])
    match_chassis(order["id"])
    return slot


def _walk_to_appliance_install(build_id: str) -> None:
    """CHASSIS_PREP forward to APPLIANCE_INSTALL, one hour per station."""
    for station in ("SIDEWALL_LAM", "ROOF_SET", "ROUGH_IN", "APPLIANCE_INSTALL"):
        advance_build(build_id, station, 1.00)


def _walk_to_water_test(build_id: str) -> None:
    """APPLIANCE_INSTALL forward to WATER_TEST, one hour per station."""
    advance_build(build_id, "FINISH", 1.00)
    advance_build(build_id, "WATER_TEST", 1.00)


def _rework_back_to_water_test(build_id: str) -> None:
    """ROUGH_IN forward to WATER_TEST again, one hour per station."""
    for station in ("APPLIANCE_INSTALL", "FINISH", "WATER_TEST"):
        advance_build(build_id, station, 1.00)


def _build_at_water_test(lot_quantity: int = 20):
    """A live SOLD build standing at WATER_TEST with 6.00 hours banked.

    Returns (plant, order, build, installation).
    """
    plant = _appliance_plant(lot_quantity=lot_quantity)
    order = _sold_order(plant)
    _slot_and_match(plant, order)
    build = release_to_line(order["id"])
    _walk_to_appliance_install(build["id"])
    installation = install_pieces(build["id"], plant["lot"]["id"], "APPLIANCE_INSTALL", 1)
    _walk_to_water_test(build["id"])
    return plant, order, build, installation


class TestWaterTestFailureCyclesTheStationBackToRoughIn:
    def test_failed_water_test_sends_the_build_back_and_the_station_sequence_repeats(
        self, api, plant_admin_headers, inspector_headers, supervisor_headers
    ):
        """PRD §3.6: "Any water intrusion is decisive: if `leak_detected` is true the `result` is `FAIL` regardless of how few defect points were recorded — zero points with a leak still fails."
        PRD §3.6: "A failed `WATER_TEST` increments `rework_count` by one, clears `water_test_passed` back to false, and moves the build `WATER_TEST → ROUGH_IN`, re-opening the rework cycle `WATER_TEST → ROUGH_IN → APPLIANCE_INSTALL → FINISH → WATER_TEST`."
        PRD §3.6: "Completion always does two things regardless of grade: it stamps `completed_by_user_id` from the acting `X-User-ID`, and it adds the recorded `defect_points` to the build's `defect_points_total`, which accumulates over every completed inspection and later becomes a credit against the coach's invoice."
        PRD §3.5: "On success the reported `station_hours_used` is added to the build's `actual_station_hours`, which accumulates across the whole build including every rework loop, and which later becomes the overtime term of the final invoice."
        PRD §3.2: "Then choose a class factor from the floor plan's `chassis_class`: a towable is 1.00, a Class C is 1.10, and a Class A is 1.15."
        PRD §3.2: "Multiply raw hours by the complexity factor and by the class factor, add the surcharge, and round that single final result half up to two decimal places."

        Design: Difficulty/non_linear_state_machine/unit_build_water_test_fail_cycles_the_station_back_to_rough_in
        """
        plant, order, build, _installation = _build_at_water_test()
        inspection = schedule_booth_inspection(
            build["id"],
            plant["booth"]["id"],
            "2026-08-05T09:00:00Z",
            "2026-08-05T09:30:00Z",
            headers=inspector_headers,
        )

        completed = validate_success(
            api.complete_inspection(
                inspection["id"], {"defect_points": 4, "leak_detected": True}, inspector_headers
            )
        )
        assert completed["result"] == "FAIL"
        assert completed["status"] == "COMPLETED"

        # The coach walks the same forward station a second time.
        validate_success(
            api.advance_build(
                build["id"],
                {"to_station": "APPLIANCE_INSTALL", "station_hours_used": 2.00},
                supervisor_headers,
            )
        )

        after = validate_success(api.get_unit_build(build["id"], plant_admin_headers))
        assert after["current_station"] == "APPLIANCE_INSTALL"
        assert after["rework_count"] == 1
        assert after["water_test_passed"] is False
        assert after["defect_points_total"] == 4
        assert_hours(after["actual_station_hours"], "8.00")

        order_after = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
        assert order_after["status"] == "IN_PRODUCTION"
        assert_hours(order_after["required_station_hours"], "56.35")

    def test_reworked_build_reaches_water_test_a_second_time_accumulating_hours(
        self, api, plant_admin_headers, inspector_headers, supervisor_headers
    ):
        """PRD §3.6: "A failed `WATER_TEST` increments `rework_count` by one, clears `water_test_passed` back to false, and moves the build `WATER_TEST → ROUGH_IN`, re-opening the rework cycle `WATER_TEST → ROUGH_IN → APPLIANCE_INSTALL → FINISH → WATER_TEST`."
        PRD §3.5: "Entering `WATER_TEST` from `FINISH` requires that the systems actually installed match what the order bought: for each of the categories `APPLIANCE` and `PLUMBING` that appears among the order's selected options, at least one installation on this build must be in `status` `INSTALLED` drawing from a component lot of that same category."
        PRD §3.5: "On success the reported `station_hours_used` is added to the build's `actual_station_hours`, which accumulates across the whole build including every rework loop, and which later becomes the overtime term of the final invoice."

        Design: Difficulty/non_linear_state_machine/unit_build_water_test_fail_cycles_the_station_back_to_rough_in
        """
        plant, order, build, _installation = _build_at_water_test()
        inspection = schedule_booth_inspection(
            build["id"],
            plant["booth"]["id"],
            "2026-08-05T09:00:00Z",
            "2026-08-05T09:30:00Z",
            headers=inspector_headers,
        )
        complete_inspection(inspection["id"], 4, True, headers=inspector_headers)

        at_rough_in = validate_success(api.get_unit_build(build["id"], plant_admin_headers))
        assert at_rough_in["current_station"] == "ROUGH_IN"
        assert_hours(at_rough_in["actual_station_hours"], "6.00")

        # The rework cycle re-enters the stations the coach has already passed.
        validate_success(
            api.advance_build(
                build["id"],
                {"to_station": "APPLIANCE_INSTALL", "station_hours_used": 2.00},
                supervisor_headers,
            )
        )
        validate_success(
            api.advance_build(
                build["id"], {"to_station": "FINISH", "station_hours_used": 1.00}, supervisor_headers
            )
        )
        second_pass = validate_success(
            api.advance_build(
                build["id"],
                {"to_station": "WATER_TEST", "station_hours_used": 1.00},
                supervisor_headers,
            )
        )
        assert second_pass["current_station"] == "WATER_TEST"
        assert_hours(second_pass["actual_station_hours"], "10.00")
        assert second_pass["rework_count"] == 1
        assert second_pass["water_test_passed"] is False
        assert second_pass["defect_points_total"] == 4

        order_after = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
        assert order_after["status"] == "IN_PRODUCTION"

    def test_water_test_without_a_leak_passes_and_leaves_the_build_at_water_test(
        self, api, plant_admin_headers, inspector_headers
    ):
        """PRD §3.6: "For a `WATER_TEST` or `FUNCTIONAL` inspection, more than 12 defect points is `FAIL`, 6 through 12 points is `CONDITIONAL`, and fewer than 6 points is `PASS` — so 12 points is still conditional and 13 points fails."
        PRD §3.6: "A `PASS` or `CONDITIONAL` on a `WATER_TEST` sets the build's `water_test_passed` to true and leaves `current_station` where it is — a conditional pass is a pass, and the coach proceeds."

        Design: Difficulty/non_linear_state_machine/unit_build_water_test_fail_cycles_the_station_back_to_rough_in
        """
        plant, order, build, _installation = _build_at_water_test()
        inspection = schedule_booth_inspection(
            build["id"],
            plant["booth"]["id"],
            "2026-08-05T09:00:00Z",
            "2026-08-05T09:30:00Z",
            headers=inspector_headers,
        )

        completed = validate_success(
            api.complete_inspection(
                inspection["id"], {"defect_points": 4, "leak_detected": False}, inspector_headers
            )
        )
        assert completed["result"] == "PASS"
        assert completed["status"] == "COMPLETED"

        after = validate_success(api.get_unit_build(build["id"], plant_admin_headers))
        assert after["current_station"] == "WATER_TEST"
        assert after["rework_count"] == 0
        assert after["water_test_passed"] is True
        assert after["defect_points_total"] == 4
        assert_hours(after["actual_station_hours"], "6.00")

        order_after = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
        assert order_after["status"] == "IN_PRODUCTION"


class TestOrderStatusAndFinancingStatusAdvanceIndependently:
    def test_release_to_line_moves_status_and_leaves_the_advance_outstanding(
        self, api, plant_admin_headers, scheduler_headers
    ):
        """PRD §3.4: "**Releasing to the line** is the handoff from paperwork to production, driving the order `SLOTTED → IN_PRODUCTION` and returning the newly created build."
        PRD §3.7: "`financing_status` and `status` never gate each other except where a precondition explicitly says so — the funding gate on shipment and the status window on funding requests are the only two places they touch."
        PRD §3.7: "A dealer's `financed_exposure_cents` is the sum, across every one of its orders whose `financing_status` is `FLOOR_PLAN_FUNDED` or `CURTAILED`, of that order's `financed_principal_cents` minus its `curtailment_paid_cents`."

        Design: Difficulty/non_linear_state_machine/unit_order_production_status_and_financing_status_advance_independently
        """
        plant = _electrical_plant()
        order = _sold_order(plant)
        assert order["provisional_invoice_cents"] == SOLD_AC2_PROVISIONAL_CENTS
        request_funding(order["id"], plant["dealer"]["id"])
        funded = decide_funding(order["id"], "APPROVED")
        assert funded["financing_status"] == "FLOOR_PLAN_FUNDED"
        principal = SOLD_AC2_PRINCIPAL_CENTS
        assert funded["financed_principal_cents"] == principal
        reserve_slot(order["id"], plant["line"]["id"], SLOT_DATE, funded["version"])
        match_chassis(order["id"])

        build = validate_success(api.release_to_line(order["id"], scheduler_headers), 201)
        assert build["current_station"] == "CHASSIS_PREP"

        after = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
        assert after["status"] == "IN_PRODUCTION"
        assert after["financing_status"] == "FLOOR_PLAN_FUNDED"
        assert after["financed_principal_cents"] == principal
        assert after["curtailment_paid_cents"] == 0
        assert after["curtailment_due_cents"] == 0

        dealer = validate_success(api.get_dealer(plant["dealer"]["id"], plant_admin_headers))
        assert dealer["financed_exposure_cents"] == principal
        assert dealer["credit_status"] == "GOOD_STANDING"

    def test_full_floor_plan_payment_pays_off_while_the_unit_is_still_in_production(
        self, api, plant_admin_headers, scheduler_headers
    ):
        """PRD §3.7: "A payment that brings the paid total to exactly the full `financed_principal_cents` retires the advance: `curtailment_paid_cents` becomes the full principal, `curtailment_due_cents` becomes zero, and `financing_status` moves to the terminal `PAID_OFF` from either `FLOOR_PLAN_FUNDED` or `CURTAILED`, removing the unit from the dealer's exposure set."
        PRD §3.7: "`financing_status` and `status` never gate each other except where a precondition explicitly says so — the funding gate on shipment and the status window on funding requests are the only two places they touch."
        PRD §3.7: "Its `credit_status` follows from two strictly-greater-than comparisons: utilisation above 9500 basis points is `CREDIT_HOLD`, utilisation above 8000 basis points (but not above 9500) is `WATCH`, and anything at or below 8000 is `GOOD_STANDING`."

        Design: Difficulty/non_linear_state_machine/unit_order_production_status_and_financing_status_advance_independently
        """
        plant = _electrical_plant()
        order = _sold_order(plant)
        provisional = SOLD_AC2_PROVISIONAL_CENTS
        assert order["provisional_invoice_cents"] == provisional
        request_funding(order["id"], plant["dealer"]["id"])
        funded = decide_funding(order["id"], "APPROVED")
        principal = SOLD_AC2_PRINCIPAL_CENTS
        assert funded["financed_principal_cents"] == principal
        reserve_slot(order["id"], plant["line"]["id"], SLOT_DATE, funded["version"])
        match_chassis(order["id"])

        build = validate_success(api.release_to_line(order["id"], scheduler_headers), 201)
        paid = validate_success(
            api.floor_plan_payment(
                order["id"],
                {"amount_cents": principal},
                make_dealer_principal_headers(plant["dealer"]["id"]),
            )
        )

        assert paid["status"] == "IN_PRODUCTION"
        assert paid["financing_status"] == "PAID_OFF"
        assert paid["financed_principal_cents"] == principal
        assert paid["curtailment_paid_cents"] == principal
        assert paid["curtailment_due_cents"] == 0
        assert paid["provisional_invoice_cents"] == provisional

        after_build = validate_success(api.get_unit_build(build["id"], plant_admin_headers))
        assert after_build["current_station"] == "CHASSIS_PREP"

        dealer = validate_success(api.get_dealer(plant["dealer"]["id"], plant_admin_headers))
        assert dealer["financed_exposure_cents"] == 0
        assert dealer["credit_utilization_bp"] == 0
        assert dealer["credit_status"] == "GOOD_STANDING"


class TestRecallOpenQuarantinesLotHoldsBuildAndOrder:
    def test_opening_a_safety_campaign_holds_the_build_the_order_and_rescores_the_supplier(
        self,
        api,
        plant_admin_headers,
        supervisor_headers,
        recall_coordinator_headers,
    ):
        """PRD §2.9: "Opening or expanding a recall campaign quarantines matching component lots, which flips every `INSTALLED` installation of those lots to `RECALL_AFFECTED`, which raises `recall_hold` on each affected build, which — for a safety-severity campaign — sets `ship_hold_reason` to `RECALL_HOLD` on each held build's owning order, which in turn rescores the supplier."
        PRD §3.9: "Every matching lot moves to `QUARANTINED` — from `AVAILABLE` or from `DEPLETED` alike — by adding its remaining `quantity_available` to its `quantity_quarantined` and then setting `quantity_available` to zero."
        PRD §3.9: "Hop four rescores the supplier. Its `open_recall_count` increases by one, its `penalty_event_count` increases by one, and its `quality_score` and `supplier_status` are recomputed — which can drop it to `PROBATION` or `SUSPENDED` and thereby, in one stroke, remove its chassis from the matching pool of §3.4 and raise the chargeback rate applied to its warranty claims in §3.8."
        PRD §3.9: "The event set is the same for both: every campaign of that supplier whose `status` is `OPEN` or `CLOSED` and whose `opened_at` is not null, weighted by severity at 15.0 for `SAFETY`, 10.0 for `COMPLIANCE`, and 4.0 for `ADVISORY`, timestamped at `opened_at`; plus every `APPROVED` or `PAID` warranty claim whose component lot belongs to that supplier and whose `supplier_chargeback_cents` is positive, weighted at 2.0 and timestamped at the claim's `created_at`."
        PRD §3.9: "In both cases the score is 100.00 minus the penalty, floored at 0.00 and rounded half up to two decimal places."
        PRD §3.5: "And the build's `recall_hold` must be false, else `ERR_RECALL_SHIP_STOP`; a coach containing a recalled part does not move."

        Design: Difficulty/transitive_cascade/recall_open_quarantines_lot_holds_build_and_order
        """
        plant = _appliance_plant(lot_quantity=40)
        order = _sold_order(plant)
        _slot_and_match(plant, order)
        build = release_to_line(order["id"])
        _walk_to_appliance_install(build["id"])
        installation = install_pieces(
            build["id"], plant["lot"]["id"], "APPLIANCE_INSTALL", 1
        )
        campaign = draft_campaign(
            plant["appliance_supplier"]["id"],
            campaign_code="RC-2026-01",
            part_number="WH-6G-2026",
            lot_codes=["L-2211"],
            severity="SAFETY",
        )

        opened = validate_success(
            api.open_recall_campaign(campaign["id"], recall_coordinator_headers)
        )

        lot = validate_success(api.get_component_lot(plant["lot"]["id"], plant_admin_headers))
        assert lot["status"] == "QUARANTINED"
        assert lot["quantity_available"] == 0
        assert lot["quantity_quarantined"] == 39
        assert lot["quantity_installed"] == 1

        affected = validate_success(
            api.get_component_installation(installation["id"], plant_admin_headers)
        )
        assert affected["status"] == "RECALL_AFFECTED"
        assert affected["recall_campaign_id"] == campaign["id"]

        held_build = validate_success(api.get_unit_build(build["id"], plant_admin_headers))
        assert held_build["recall_hold"] is True

        held_order = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
        assert held_order["ship_hold_reason"] == "RECALL_HOLD"

        supplier = validate_success(
            api.get_supplier(plant["appliance_supplier"]["id"], plant_admin_headers)
        )
        assert supplier["open_recall_count"] == 1
        assert supplier["penalty_event_count"] == 1
        assert_two_decimals(supplier["quality_score"], "85.00")
        assert supplier["supplier_status"] == "ACTIVE"

        assert opened["status"] == "OPEN"
        assert opened["ship_stop"] is True
        assert opened["affected_installation_count"] == 1
        assert opened["remedied_installation_count"] == 0
        assert opened["quarantined_piece_count"] == 39

        blocked = api.advance_build(
            build["id"], {"to_station": "FINISH", "station_hours_used": 1.00}, supervisor_headers
        )
        validate_error(blocked, ApiErrorId.ERR_RECALL_SHIP_STOP)
        stalled = validate_success(api.get_unit_build(build["id"], plant_admin_headers))
        assert stalled["current_station"] == "APPLIANCE_INSTALL"
        assert_hours(stalled["actual_station_hours"], "4.00")

        chassis_supplier = validate_success(
            api.get_supplier(plant["chassis_supplier"]["id"], plant_admin_headers)
        )
        assert_two_decimals(chassis_supplier["quality_score"], "100.00")

    def test_quarantining_a_lot_with_no_installation_leaves_the_build_and_order_free(
        self,
        api,
        plant_admin_headers,
        supervisor_headers,
        recall_coordinator_headers,
    ):
        """PRD §3.9: "Every matching lot moves to `QUARANTINED` — from `AVAILABLE` or from `DEPLETED` alike — by adding its remaining `quantity_available` to its `quantity_quarantined` and then setting `quantity_available` to zero."
        PRD §3.9: "Hop two labels the coaches. Every installation drawing from those lots whose `status` is `INSTALLED` moves `INSTALLED → RECALL_AFFECTED`, records the campaign as its `recall_campaign_id`, and increments the campaign's `affected_installation_count`."
        PRD §3.9: "Hop three stops shipment, but only for safety campaigns. For every held build not already `SHIPPED`, when the campaign's `ship_stop` is true the owning order's `ship_hold_reason` becomes `RECALL_HOLD`."
        PRD §3.9: "Hop four rescores the supplier. Its `open_recall_count` increases by one, its `penalty_event_count` increases by one, and its `quality_score` and `supplier_status` are recomputed — which can drop it to `PROBATION` or `SUSPENDED` and thereby, in one stroke, remove its chassis from the matching pool of §3.4 and raise the chargeback rate applied to its warranty claims in §3.8."
        PRD §3.9: "The event set is the same for both: every campaign of that supplier whose `status` is `OPEN` or `CLOSED` and whose `opened_at` is not null, weighted by severity at 15.0 for `SAFETY`, 10.0 for `COMPLIANCE`, and 4.0 for `ADVISORY`, timestamped at `opened_at`; plus every `APPROVED` or `PAID` warranty claim whose component lot belongs to that supplier and whose `supplier_chargeback_cents` is positive, weighted at 2.0 and timestamped at the claim's `created_at`."
        PRD §3.9: "In both cases the score is 100.00 minus the penalty, floored at 0.00 and rounded half up to two decimal places."

        Design: Difficulty/transitive_cascade/recall_open_quarantines_lot_holds_build_and_order
        """
        plant = _appliance_plant(lot_quantity=40)
        spare_lot = create_component_lot(
            plant["appliance_supplier"]["id"],
            part_number="WH-6G-2026",
            lot_code="L-2299",
            category="APPLIANCE",
            quantity_received=40,
        )
        order = _sold_order(plant)
        _slot_and_match(plant, order)
        build = release_to_line(order["id"])
        _walk_to_appliance_install(build["id"])
        installation = install_pieces(
            build["id"], plant["lot"]["id"], "APPLIANCE_INSTALL", 1
        )
        campaign = draft_campaign(
            plant["appliance_supplier"]["id"],
            campaign_code="RC-2026-02",
            part_number="WH-6G-2026",
            lot_codes=["L-2299"],
            severity="SAFETY",
        )

        opened = validate_success(
            api.open_recall_campaign(campaign["id"], recall_coordinator_headers)
        )

        frozen = validate_success(api.get_component_lot(spare_lot["id"], plant_admin_headers))
        assert frozen["status"] == "QUARANTINED"
        assert frozen["quantity_available"] == 0
        assert frozen["quantity_quarantined"] == 40
        assert frozen["quantity_installed"] == 0

        untouched_lot = validate_success(
            api.get_component_lot(plant["lot"]["id"], plant_admin_headers)
        )
        assert untouched_lot["status"] == "AVAILABLE"
        assert untouched_lot["quantity_available"] == 39
        assert untouched_lot["quantity_quarantined"] == 0

        untouched_installation = validate_success(
            api.get_component_installation(installation["id"], plant_admin_headers)
        )
        assert untouched_installation["status"] == "INSTALLED"
        assert untouched_installation["recall_campaign_id"] is None

        assert opened["status"] == "OPEN"
        assert opened["ship_stop"] is True
        assert opened["affected_installation_count"] == 0
        assert opened["quarantined_piece_count"] == 40

        free_build = validate_success(api.get_unit_build(build["id"], plant_admin_headers))
        assert free_build["recall_hold"] is False
        free_order = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
        assert free_order["ship_hold_reason"] == "NONE"

        moved = validate_success(
            api.advance_build(
                build["id"], {"to_station": "FINISH", "station_hours_used": 1.00}, supervisor_headers
            )
        )
        assert moved["current_station"] == "FINISH"
        assert_hours(moved["actual_station_hours"], "5.00")

        supplier = validate_success(
            api.get_supplier(plant["appliance_supplier"]["id"], plant_admin_headers)
        )
        assert supplier["open_recall_count"] == 1
        assert supplier["penalty_event_count"] == 1
        assert_two_decimals(supplier["quality_score"], "85.00")


class TestDailyCloseSlotExpiryReleasesOrderAndChassis:
    def test_expired_slot_returns_the_order_to_config_validated_and_unmatches_the_chassis(
        self, api, plant_admin_headers
    ):
        """PRD §2.5: "The expiry sweep finds every `ProductionSlot` whose `status` is `RESERVED` and whose `expires_at` is at or before the current clock and moves it `RESERVED → RELEASED`, cascading as described in §3.3."
        PRD §2.5: "The response reports `released_slot_count`, the `released_order_ids` array of orders that came back out of `SLOTTED`, `curtailed_order_count`, the `curtailed_order_ids` array, and the `evaluated_at` instant at which the checkpoint ran."
        PRD §3.3: "The created slot is stamped `RESERVED` with `station_hours_committed` copied from the order's `required_station_hours` at the moment of reservation, a one-based `sequence_position` equal to the day bucket's occupied-unit count plus one (which is the coach's build order on that line that day), and an `expires_at` exactly 72 hours after the slot's `created_at`."
        PRD §3.3: "When the release comes from the expiry sweep and it leaves the order with no slot in `RESERVED` or `CONSUMED`, the cascade continues: the order falls back `SLOTTED → CONFIG_VALIDATED` and loses its slot association, and any chassis whose `matched_unit_order_id` names that order and whose `status` is `MATCHED` falls back `MATCHED → RECEIVED` with `matched_unit_order_id` cleared, re-entering the candidate pool for other orders."
        PRD §3.3: "In every case the released hours stop counting toward both the line-day and the monthly ceilings, and the dealer's allocation counters are recomputed."

        Design: Difficulty/transitive_cascade/daily_close_slot_expiry_releases_order_and_chassis
        """
        plant = _electrical_plant()
        order = _sold_order(plant)
        assert order["provisional_invoice_cents"] == SOLD_AC2_PROVISIONAL_CENTS
        slot = _slot_and_match(plant, order)
        advance_clock("2026-08-04T06:00:00Z")

        close = validate_success(api.daily_close(plant_admin_headers))
        assert close["released_slot_count"] == 1
        assert close["released_order_ids"] == [order["id"]]
        assert close["curtailed_order_count"] == 0
        assert _instant(close["evaluated_at"]) == _instant("2026-08-04T06:00:00Z")

        released = validate_success(api.get_production_slot(slot["id"], plant_admin_headers))
        assert released["status"] == "RELEASED"
        assert _instant(released["expires_at"]) == _instant("2026-08-04T00:00:00Z")

        after_order = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
        assert after_order["status"] == "CONFIG_VALIDATED"

        chassis = validate_success(
            api.get_chassis_receipt(plant["chassis"]["id"], plant_admin_headers)
        )
        assert chassis["status"] == "RECEIVED"
        assert chassis["matched_unit_order_id"] is None

        dealer = validate_success(api.get_dealer(plant["dealer"]["id"], plant_admin_headers))
        assert dealer["allocation_slots_reserved"] == 0
        assert_hours(dealer["allocation_hours_consumed"], "0.00")

        assert after_order["provisional_invoice_cents"] == SOLD_AC2_PROVISIONAL_CENTS

    def test_consumed_slot_of_an_in_production_order_survives_the_daily_close(
        self, api, plant_admin_headers
    ):
        """PRD §2.5: "The expiry sweep finds every `ProductionSlot` whose `status` is `RESERVED` and whose `expires_at` is at or before the current clock and moves it `RESERVED → RELEASED`, cascading as described in §3.3."
        PRD §3.3: "A slot that has already been consumed by a build is never released."
        PRD §3.4: "In the same operation the slot moves `RESERVED → CONSUMED` and the chassis moves `MATCHED → INSTALLED`."
        PRD §3.3: "The dealer's `allocation_slots_reserved` — the count of that dealer's slots in `RESERVED` or `CONSUMED` — and `allocation_hours_consumed` are recomputed, and the order's `version` increments."

        Design: Difficulty/transitive_cascade/daily_close_slot_expiry_releases_order_and_chassis
        """
        plant = _electrical_plant()
        order = _sold_order(plant)
        slot = _slot_and_match(plant, order)
        release_to_line(order["id"])
        advance_clock("2026-08-04T06:00:00Z")

        close = validate_success(api.daily_close(plant_admin_headers))
        assert close["released_slot_count"] == 0
        assert close["released_order_ids"] == []
        assert close["curtailed_order_count"] == 0

        consumed = validate_success(api.get_production_slot(slot["id"], plant_admin_headers))
        assert consumed["status"] == "CONSUMED"

        after_order = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
        assert after_order["status"] == "IN_PRODUCTION"

        chassis = validate_success(
            api.get_chassis_receipt(plant["chassis"]["id"], plant_admin_headers)
        )
        assert chassis["status"] == "INSTALLED"
        assert chassis["matched_unit_order_id"] == order["id"]

        dealer = validate_success(api.get_dealer(plant["dealer"]["id"], plant_admin_headers))
        assert dealer["allocation_slots_reserved"] == 1
        assert_hours(
            dealer["allocation_hours_consumed"], consumed["station_hours_committed"]
        )
        assert_hours(
            consumed["station_hours_committed"], after_order["required_station_hours"]
        )


class TestWaterTestFailureReworkThenScrapCancelsOrder:
    def test_second_failed_water_test_still_reworks_the_build_within_the_limit(
        self, api, plant_admin_headers, inspector_headers
    ):
        """PRD §3.6: "A failed `WATER_TEST` increments `rework_count` by one, clears `water_test_passed` back to false, and moves the build `WATER_TEST → ROUGH_IN`, re-opening the rework cycle `WATER_TEST → ROUGH_IN → APPLIANCE_INSTALL → FINISH → WATER_TEST`."
        PRD §3.6: "Either rework is permitted only while the incremented `rework_count` would remain at 2 or below — that is, a build may be reworked twice."
        PRD §3.6: "Completion always does two things regardless of grade: it stamps `completed_by_user_id` from the acting `X-User-ID`, and it adds the recorded `defect_points` to the build's `defect_points_total`, which accumulates over every completed inspection and later becomes a credit against the coach's invoice."

        Design: Difficulty/transitive_cascade/water_test_failure_rework_then_scrap_cancels_order
        """
        plant, order, build, _installation = _build_at_water_test()
        first = schedule_booth_inspection(
            build["id"],
            plant["booth"]["id"],
            "2026-08-05T09:00:00Z",
            "2026-08-05T09:30:00Z",
            headers=inspector_headers,
        )
        complete_inspection(first["id"], 2, True, headers=inspector_headers)
        _rework_back_to_water_test(build["id"])
        second = schedule_booth_inspection(
            build["id"],
            plant["booth"]["id"],
            "2026-08-05T10:00:00Z",
            "2026-08-05T10:30:00Z",
            headers=inspector_headers,
        )

        completed = validate_success(
            api.complete_inspection(
                second["id"], {"defect_points": 2, "leak_detected": True}, inspector_headers
            )
        )
        assert completed["result"] == "FAIL"

        reworked = validate_success(api.get_unit_build(build["id"], plant_admin_headers))
        assert reworked["current_station"] == "ROUGH_IN"
        assert reworked["rework_count"] == 2
        assert reworked["water_test_passed"] is False
        assert reworked["defect_points_total"] == 4
        assert_hours(reworked["actual_station_hours"], "9.00")

        still_running = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
        assert still_running["status"] == "IN_PRODUCTION"
        assert still_running["ship_hold_reason"] == "NONE"

    def test_third_failed_water_test_scraps_the_build_and_cancels_the_order(
        self,
        api,
        plant_admin_headers,
        inspector_headers,
        supervisor_headers,
        scheduler_headers,
    ):
        """PRD §3.6: "The third failure is terminal. When a build already carrying a `rework_count` of 2 fails again, the rework limit is exhausted: `rework_count` still increments, but instead of moving backwards the build moves `WATER_TEST → SCRAPPED` or `PDI → SCRAPPED` according to where it stood, and the cascade continues into the paperwork — the owning order moves `IN_PRODUCTION → CANCELLED` and its `ship_hold_reason` is stamped `QUALITY_HOLD`."
        PRD §3.6: "Both the build and the order are terminal at that point, and any later attempt to ship that order is refused with `ERR_QUALITY_HOLD`."
        PRD §3.5: "The supplied `to_station` must be the immediate successor of the build's `current_station`; anything else — skipping a station, naming the current one, moving backwards, or touching a build already at `SHIPPED` or `SCRAPPED` — is rejected with `ERR_STATION_SEQUENCE_VIOLATION`."
        PRD §3.4: "In the same operation the slot moves `RESERVED → CONSUMED` and the chassis moves `MATCHED → INSTALLED`."
        PRD §3.5: "On success the reported `station_hours_used` is added to the build's `actual_station_hours`, which accumulates across the whole build including every rework loop, and which later becomes the overtime term of the final invoice."

        Design: Difficulty/transitive_cascade/water_test_failure_rework_then_scrap_cancels_order
        """
        plant = _appliance_plant()
        order = _sold_order(plant)
        slot = _slot_and_match(plant, order)
        build = release_to_line(order["id"])
        _walk_to_appliance_install(build["id"])
        install_pieces(build["id"], plant["lot"]["id"], "APPLIANCE_INSTALL", 1)
        _walk_to_water_test(build["id"])
        first = schedule_booth_inspection(
            build["id"],
            plant["booth"]["id"],
            "2026-08-05T09:00:00Z",
            "2026-08-05T09:30:00Z",
            headers=inspector_headers,
        )
        complete_inspection(first["id"], 2, True, headers=inspector_headers)
        _rework_back_to_water_test(build["id"])
        second = schedule_booth_inspection(
            build["id"],
            plant["booth"]["id"],
            "2026-08-05T10:00:00Z",
            "2026-08-05T10:30:00Z",
            headers=inspector_headers,
        )
        complete_inspection(second["id"], 2, True, headers=inspector_headers)
        _rework_back_to_water_test(build["id"])
        third = schedule_booth_inspection(
            build["id"],
            plant["booth"]["id"],
            "2026-08-05T11:00:00Z",
            "2026-08-05T11:30:00Z",
            headers=inspector_headers,
        )

        completed = validate_success(
            api.complete_inspection(
                third["id"], {"defect_points": 2, "leak_detected": True}, inspector_headers
            )
        )
        assert completed["result"] == "FAIL"

        scrapped = validate_success(api.get_unit_build(build["id"], plant_admin_headers))
        assert scrapped["current_station"] == "SCRAPPED"
        assert scrapped["rework_count"] == 3

        cancelled = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["ship_hold_reason"] == "QUALITY_HOLD"

        assert scrapped["defect_points_total"] == 6
        assert_hours(scrapped["actual_station_hours"], "12.00")
        assert scrapped["water_test_passed"] is False
        assert scrapped["pdi_passed"] is False

        consumed = validate_success(api.get_production_slot(slot["id"], plant_admin_headers))
        assert consumed["status"] == "CONSUMED"

        chassis = validate_success(
            api.get_chassis_receipt(plant["chassis"]["id"], plant_admin_headers)
        )
        assert chassis["status"] == "INSTALLED"
        assert chassis["matched_unit_order_id"] == order["id"]

        refused_ship = api.ship_order(order["id"], scheduler_headers)
        validate_error(refused_ship, ApiErrorId.ERR_QUALITY_HOLD)

        refused_advance = api.advance_build(
            build["id"], {"to_station": "PDI", "station_hours_used": 1.00}, supervisor_headers
        )
        validate_error(refused_advance, ApiErrorId.ERR_STATION_SEQUENCE_VIOLATION)
