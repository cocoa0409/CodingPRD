"""Lifecycle behaviour of the plant's entity state machines.

Every test builds its own world from an empty database through PRD §4
endpoints and then exercises exactly one transition, refusal or cascade.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    advance_build,
    assert_cents,
    assert_hours,
    assert_lot_counter_invariant,
    assert_two_decimals,
    assert_vin_format,
    complete_inspection,
    create_chassis_receipt,
    create_component_lot,
    create_dealer,
    create_floor_plan,
    create_option_item,
    create_order,
    create_production_line,
    create_supplier,
    create_test_booth,
    draft_campaign,
    install_pieces,
    make_dealer_principal_headers,
    make_quality_inspector_headers,
    match_chassis,
    open_campaign,
    release_to_line,
    request_funding,
    reserve_slot,
    schedule_booth_inspection,
    schedule_pdi,
    ship_order,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── Master data of the towable coach used by most of these tests ──────────
FP_TOW = {
    "model_code": "FP-TOW",
    "chassis_class": "TOWABLE",
    "length_ft": 28,
    "base_msrp_cents": 8000000,
    "base_station_hours": 40.00,
    "base_dry_weight_lbs": 6000,
    "gvwr_lbs": 9000,
    "required_wheelbase_in": 180,
    "electrical_service_amps": 50,
    "fresh_water_capacity_gal": 60,
}
OPT_E1 = {
    "option_code": "OPT-E1",
    "category": "ELECTRICAL",
    "install_station": "ROUGH_IN",
    "price_cents": 100000,
    "weight_lbs": 0,
    "added_station_hours": 1.00,
    "amp_draw": 20,
    "water_demand_gal": 0,
}
D_TOW = {
    "dealer_code": "D-TOW",
    "region": "CENTRAL",
    "allocation_share_bp": 1500,
    "floor_plan_credit_limit_cents": 100000000,
    "goodwill_budget_cents": 500000,
}
LINE_T = {
    "line_code": "LINE-T",
    "chassis_class_supported": "TOWABLE",
    "daily_station_hour_capacity": 240.00,
    "max_units_per_day": 4,
}
CH_T1 = {
    "chassis_serial": "CH-T1",
    "chassis_class": "TOWABLE",
    "gvwr_lbs": 9000,
    "wheelbase_in": 180,
}
BOOTH_W = {
    "booth_code": "BOOTH-W",
    "booth_type": "WATER_TEST",
    "bay_count": 1,
    "turnaround_minutes": 30,
}


def _instant(value):
    """Parse an ISO 8601 UTC timestamp so fractional digits do not matter."""
    assert value is not None, "expected an ISO 8601 instant, got null"
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _tow_order_ingredients():
    """Floor plan FP-TOW, option OPT-E1 and dealer D-TOW."""
    return (
        create_floor_plan(**FP_TOW),
        create_option_item(**OPT_E1),
        create_dealer(**D_TOW),
    )


def test_submit_pins_reference_versions_and_writes_the_provisional_invoice(api):
    """PRD §3.2: "**Submitting** the order is the moment the configuration becomes a commitment, moving `status` from `DRAFT` to `CONFIG_VALIDATED`."

    PRD §3.2: "An order that clears all of it is stamped: the roll-up is recomputed, `provisional_invoice_cents` is written, `locked_floor_plan_version` is pinned to the floor plan's current `version`, and `locked_option_versions` is pinned as one entry per selected option carrying that option's identifier, its `version`, and its `price_cents` at the moment of submit."

    PRD §3.2: "The seventh figure is money, and §3.7 develops it fully; at submit the order's `provisional_invoice_cents` is written from the provisional variant of the invoice calculation, and `final_invoice_cents` stays null until the coach ships."

    PRD §3.7: "Under the **provisional variant**, computed at submit, no build exists yet, so the three build-derived adjustments are all zero and `provisional_invoice_cents` is simply the discounted subtotal plus freight."

    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the row."

    Design: Corner/state_machines/submit_transition_pins_reference_versions_and_prices_the_order
    """
    floor_plan, option, dealer = _tow_order_ingredients()
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )

    submitted = validate_success(api.submit_order(order["id"], dealer_headers))

    assert submitted["status"] == "CONFIG_VALIDATED"
    assert_cents(submitted["provisional_invoice_cents"], 6620350)
    assert submitted["final_invoice_cents"] is None
    assert submitted["financing_status"] == "NOT_FINANCED"
    assert submitted["locked_floor_plan_version"] == 1
    assert submitted["locked_option_versions"] == [
        {"option_id": option["id"], "version": 1, "price_cents": 100000}
    ]
    assert_hours(submitted["required_station_hours"], "41.00")
    assert submitted["config_weight_lbs"] == 6000
    assert submitted["version"] == 2


def test_every_machine_opens_in_its_declared_first_state(api, plant_admin_headers):
    """PRD §3.1: "The plant stamps `received_at` from the logical clock — this is the primary ranking key of the matching selector in §3.4 — sets `status` to `RECEIVED`, and leaves `matched_unit_order_id` null."

    PRD §3.2: "The new order begins with `status` `DRAFT` and `financing_status` `NOT_FINANCED`, and the configuration roll-up runs immediately."

    PRD §3.3: "The created slot is stamped `RESERVED` with `station_hours_committed` copied from the order's `required_station_hours` at the moment of reservation, a one-based `sequence_position` equal to the day bucket's occupied-unit count plus one (which is the coach's build order on that line that day), and an `expires_at` exactly 72 hours after the slot's `created_at`."

    PRD §3.4: "It receives a `build_sequence` equal to the plant-wide build counter plus one, a one-based monotonic figure in build-creation order, and a `vin` formed from the floor plan's `model_code`, then a hyphen, then that `build_sequence` zero-padded to six digits."

    PRD §3.4: "It stands at `current_station` `CHASSIS_PREP` with `actual_station_hours` `0.00`, `rework_count` 0, `defect_points_total` 0, `water_test_passed` false, `pdi_passed` false, and `recall_hold` false."

    PRD §3.1: "On receipt `quantity_available` equals `quantity_received`, `quantity_installed` is 0, `quantity_quarantined` is 0, and `status` is `AVAILABLE`."

    PRD §3.9: "The campaign starts at `status` `DRAFT` with `opened_at` null, all three counters — `affected_installation_count`, `remedied_installation_count`, and `quarantined_piece_count` — at zero, and `ship_stop` derived from severity: it is true exactly when `severity` is `SAFETY` and false for `COMPLIANCE` and `ADVISORY`."

    Design: Corner/state_machines/initial_states_of_order_slot_chassis_build_lot_and_campaign
    """
    supplier = create_supplier(
        supplier_code="SUP-CH",
        name="Cascade Chassis Works",
        component_categories=["CHASSIS", "APPLIANCE"],
    )
    floor_plan, option, dealer = _tow_order_ingredients()
    line = create_production_line(**LINE_T)
    lot = create_component_lot(
        supplier["id"],
        part_number="WH-6G-2026",
        lot_code="L-2211",
        category="APPLIANCE",
        quantity_received=20,
    )
    campaign = draft_campaign(
        supplier["id"],
        campaign_code="RC-2026-01",
        part_number="WH-6G-2026",
        lot_codes=["L-2211"],
        severity="ADVISORY",
    )

    chassis = validate_success(
        api.create_chassis_receipt({"supplier_id": supplier["id"], **CH_T1}, plant_admin_headers),
        201,
    )
    order = validate_success(
        api.create_unit_order(
            {
                "dealer_id": dealer["id"],
                "floor_plan_id": floor_plan["id"],
                "order_type": "STOCK",
                "selected_option_ids": [option["id"]],
                "requested_delivery_date": "2026-10-01T00:00:00Z",
            },
            make_dealer_principal_headers(dealer["id"]),
        ),
        201,
    )
    submitted = submit_order(order["id"], dealer["id"])
    slot = reserve_slot(
        order["id"], line["id"], "2026-08-05T00:00:00Z", submitted["version"]
    )
    match_chassis(order["id"])
    build = release_to_line(order["id"])

    assert chassis["status"] == "RECEIVED"
    assert chassis["matched_unit_order_id"] is None
    assert order["status"] == "DRAFT"
    assert order["financing_status"] == "NOT_FINANCED"
    assert slot["status"] == "RESERVED"
    assert build["current_station"] == "CHASSIS_PREP"
    assert_hours(build["actual_station_hours"], "0.00")
    assert build["rework_count"] == 0
    assert build["defect_points_total"] == 0
    assert build["water_test_passed"] is False
    assert build["pdi_passed"] is False
    assert build["recall_hold"] is False
    assert build["build_sequence"] == 1
    assert_vin_format(build["vin"], "FP-TOW", 1)
    assert build["vin"] == "FP-TOW-000001"
    lot_row = validate_success(api.get_component_lot(lot["id"], plant_admin_headers))
    assert lot_row["status"] == "AVAILABLE"
    campaign_row = validate_success(api.get_recall_campaign(campaign["id"], plant_admin_headers))
    assert campaign_row["status"] == "DRAFT"
    assert campaign_row["opened_at"] is None
    assert campaign_row["ship_stop"] is False
    assert campaign_row["affected_installation_count"] == 0
    assert campaign_row["remedied_installation_count"] == 0


def test_submit_rejects_an_order_whose_floor_plan_was_retired_after_creation(
    api, plant_admin_headers
):
    """PRD §3.1: "A floor plan may later be repriced through `base_msrp_cents` or retired by setting `status` to `RETIRED`; either edit increments the plan's `version`, which invalidates the pinned reference on every already-submitted order that names it. Submitting an order against a `RETIRED` plan is rejected with `ERR_FLOOR_PLAN_RETIRED`."

    PRD §3.2: "It requires the order to be `DRAFT` — a second submit of an already `CONFIG_VALIDATED` order is rejected with `ERR_ORDER_NOT_SUBMITTABLE` — requires the acting `X-User-ID` to be the order's dealer, requires the referenced floor plan's `status` to be `ACTIVE` and the dealer's `status` to be `ACTIVE`, and requires every selected option's `status` to be `ACTIVE`."

    PRD §3.2: "An order that clears all of it is stamped: the roll-up is recomputed, `provisional_invoice_cents` is written, `locked_floor_plan_version` is pinned to the floor plan's current `version`, and `locked_option_versions` is pinned as one entry per selected option carrying that option's identifier, its `version`, and its `price_cents` at the moment of submit."

    Design: Corner/state_machines/submit_precondition_rejects_a_retired_floor_plan
    """
    floor_plan, option, dealer = _tow_order_ingredients()
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )
    retired = validate_success(
        api.patch_floor_plan(floor_plan["id"], {"status": "RETIRED"}, plant_admin_headers)
    )

    validate_error(
        api.submit_order(order["id"], dealer_headers), ApiErrorId.ERR_FLOOR_PLAN_RETIRED
    )

    assert retired["version"] == 2
    assert retired["status"] == "RETIRED"
    after = validate_success(api.get_unit_order(order["id"], dealer_headers))
    assert after["status"] == "DRAFT"
    assert after["version"] == 1
    assert_cents(after["provisional_invoice_cents"], 0)
    assert after["locked_floor_plan_version"] is None


def test_release_to_line_consumes_the_slot_and_chassis_and_mints_the_build(
    api, plant_admin_headers, scheduler_headers
):
    """PRD §3.4: "**Releasing to the line** is the handoff from paperwork to production, driving the order `SLOTTED → IN_PRODUCTION` and returning the newly created build."

    PRD §3.4: "It records the order it serves as `unit_order_id` and the chassis it consumed as `chassis_receipt_id` — both taken from the operation's context, never from a body."

    PRD §3.4: "It receives a `build_sequence` equal to the plant-wide build counter plus one, a one-based monotonic figure in build-creation order, and a `vin` formed from the floor plan's `model_code`, then a hyphen, then that `build_sequence` zero-padded to six digits."

    PRD §3.4: "In the same operation the slot moves `RESERVED → CONSUMED` and the chassis moves `MATCHED → INSTALLED`."

    PRD §3.3: "Multiply that by the dealer's `allocation_share_bp` and divide by 10000, rounding half up to two decimals: that is the dealer's `entitlement_hours`."

    PRD §3.3: "Against that ceiling, sum the `station_hours_committed` of every slot belonging to this dealer's orders whose `status` is `RESERVED` or `CONSUMED` and whose `slot_date` falls in the same calendar month as the requested `slot_date`, again excluding the slot this request just released — that sum is the dealer's `allocation_hours_consumed` for the month."

    Design: Corner/state_machines/release_to_line_side_effects_consume_slot_and_chassis_and_open_build
    """
    supplier = create_supplier(
        supplier_code="SUP-CH", name="Cascade Chassis Works", component_categories=["CHASSIS"]
    )
    floor_plan, option, dealer = _tow_order_ingredients()
    line = create_production_line(**LINE_T)
    chassis = create_chassis_receipt(supplier["id"], **CH_T1)
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )
    submitted = submit_order(order["id"], dealer["id"])
    slot = reserve_slot(order["id"], line["id"], "2026-08-05T00:00:00Z", submitted["version"])
    matched = match_chassis(order["id"])

    build = validate_success(api.release_to_line(order["id"], scheduler_headers), 201)

    assert build["current_station"] == "CHASSIS_PREP"
    assert build["build_sequence"] == 1
    assert build["vin"] == "FP-TOW-000001"
    assert build["unit_order_id"] == order["id"]
    assert build["chassis_receipt_id"] == chassis["id"]
    assert matched["id"] == chassis["id"]
    chassis_row = validate_success(api.get_chassis_receipt(chassis["id"], scheduler_headers))
    assert chassis_row["status"] == "INSTALLED"
    slot_row = validate_success(api.get_production_slot(slot["id"], scheduler_headers))
    assert slot_row["status"] == "CONSUMED"
    order_row = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
    assert order_row["status"] == "IN_PRODUCTION"
    assert order_row["version"] == 4
    dealer_row = validate_success(api.get_dealer(dealer["id"], plant_admin_headers))
    assert_hours(dealer_row["allocation_hours_consumed"], "41.00")


def test_draft_order_refuses_ship_match_release_and_funding_requests(
    api, plant_admin_headers, scheduler_headers
):
    """PRD §2.8: "The addressed entity is in a state from which the requested transition exists, and the required companion rows are in their required states. The generic code is `ERR_INVALID_STATE` (409), but a specific code takes its place wherever one is defined: `ERR_ORDER_NOT_SUBMITTABLE`, `ERR_ORDER_NOT_SLOTTABLE`, `ERR_ORDER_ALREADY_MATCHED`, `ERR_CHASSIS_NOT_MATCHED`, `ERR_DEALER_SUSPENDED`, `ERR_FLOOR_PLAN_RETIRED`, `ERR_STATION_SEQUENCE_VIOLATION`, `ERR_LINE_NOT_RUNNING`, `ERR_BOOTH_NOT_OPEN`, `ERR_INSPECTION_STATION_MISMATCH`, `ERR_LOT_QUANTITY_INSUFFICIENT`, `ERR_CLAIM_NOT_DECIDABLE`, `ERR_INFO_REQUEST_LIMIT_REACHED`, `ERR_CAMPAIGN_NOT_CLOSEABLE`, `ERR_PAYMENT_EXCEEDS_PRINCIPAL`, and `ERR_QUALITY_HOLD`."

    PRD §3.7: "The order must be `BUILT` and its `ship_hold_reason` must be `NONE`."

    PRD §3.4: "Matching is available while the order's `status` is `CONFIG_VALIDATED` or `SLOTTED`, and only when no other chassis already names this order in its `matched_unit_order_id`; an order that already holds a matched or installed chassis is rejected with `ERR_ORDER_ALREADY_MATCHED`."

    PRD §3.4: "It takes no body and demands a great deal of alignment: the order must be `SLOTTED`; a chassis must exist whose `matched_unit_order_id` names this order and whose `status` is `MATCHED`, else `ERR_CHASSIS_NOT_MATCHED`; the order's slot must still be `RESERVED` rather than expired or released; the dealer's `status` must be `ACTIVE` and its `credit_status` must not be `CREDIT_HOLD`, and it must carry no delinquent curtailment; and the pinned floor-plan and option versions must still match, else `ERR_CONFIG_REFERENCE_STALE`."

    PRD §3.7: "A `DealerPrincipal` requests funding on its own order, driving `financing_status` `NOT_FINANCED → FUNDING_REQUESTED` while leaving `status` untouched; the request is admissible only while the order's `status` is `CONFIG_VALIDATED`, `SLOTTED`, `IN_PRODUCTION`, or `BUILT`, and only while the dealer's `status` is `ACTIVE`."

    Design: Corner/state_machines/invalid_triggers_from_draft_order_return_invalid_state
    """
    supplier = create_supplier(
        supplier_code="SUP-CH", name="Cascade Chassis Works", component_categories=["CHASSIS"]
    )
    floor_plan, option, dealer = _tow_order_ingredients()
    chassis = create_chassis_receipt(supplier["id"], **CH_T1)
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )

    validate_error(api.ship_order(order["id"], scheduler_headers), ApiErrorId.ERR_INVALID_STATE)
    validate_error(api.match_chassis(order["id"], scheduler_headers), ApiErrorId.ERR_INVALID_STATE)
    validate_error(
        api.release_to_line(order["id"], scheduler_headers), ApiErrorId.ERR_INVALID_STATE
    )
    validate_error(
        api.request_funding(order["id"], dealer_headers), ApiErrorId.ERR_INVALID_STATE
    )

    after = validate_success(api.get_unit_order(order["id"], dealer_headers))
    assert after["status"] == "DRAFT"
    assert after["financing_status"] == "NOT_FINANCED"
    assert after["version"] == 1
    chassis_row = validate_success(api.get_chassis_receipt(chassis["id"], scheduler_headers))
    assert chassis_row["status"] == "RECEIVED"
    assert chassis_row["matched_unit_order_id"] is None
    _builds, meta = validate_paginated(
        api.list_unit_builds(plant_admin_headers, params={"unit_order_id": order["id"]})
    )
    assert meta["total_count"] == 0


def test_shipped_order_and_build_refuse_cancel_submit_advance_and_reship(
    api, plant_admin_headers, scheduler_headers, supervisor_headers
):
    """PRD §3.7: "On success `shipped_at` is stamped from the logical clock, `final_invoice_cents` is written from the final variant, and the build moves `READY_TO_SHIP → SHIPPED`."

    PRD §3.7: "`final_invoice_cents` is then the discounted subtotal plus freight plus the overtime surcharge plus the rework surcharge, minus the quality credit."

    PRD §3.2: "Cancellation attempted from `IN_PRODUCTION`, `BUILT`, `SHIPPED`, or `CANCELLED` is rejected with `ERR_INVALID_STATE`."

    PRD §3.2: "It requires the order to be `DRAFT` — a second submit of an already `CONFIG_VALIDATED` order is rejected with `ERR_ORDER_NOT_SUBMITTABLE` — requires the acting `X-User-ID` to be the order's dealer, requires the referenced floor plan's `status` to be `ACTIVE` and the dealer's `status` to be `ACTIVE`, and requires every selected option's `status` to be `ACTIVE`."

    PRD §3.5: "The supplied `to_station` must be the immediate successor of the build's `current_station`; anything else — skipping a station, naming the current one, moving backwards, or touching a build already at `SHIPPED` or `SCRAPPED` — is rejected with `ERR_STATION_SEQUENCE_VIOLATION`."

    PRD §3.7: "The order must be `BUILT` and its `ship_hold_reason` must be `NONE`."

    Design: Corner/state_machines/terminal_shipped_order_and_build_reject_every_further_trigger
    """
    supplier = create_supplier(
        supplier_code="SUP-CH", name="Cascade Chassis Works", component_categories=["CHASSIS"]
    )
    floor_plan, option, dealer = _tow_order_ingredients()
    line = create_production_line(**LINE_T)
    booth = create_test_booth(**BOOTH_W)
    create_chassis_receipt(supplier["id"], **CH_T1)
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    inspector_1 = make_quality_inspector_headers("QI-1")
    inspector_2 = make_quality_inspector_headers("QI-2")
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="SOLD",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
        customer_reference="RETAIL-77",
    )
    submitted = submit_order(order["id"], dealer["id"])
    reserve_slot(order["id"], line["id"], "2026-08-05T00:00:00Z", submitted["version"])
    match_chassis(order["id"])
    build = release_to_line(order["id"])
    for station in ("SIDEWALL_LAM", "ROOF_SET", "ROUGH_IN", "APPLIANCE_INSTALL", "FINISH", "WATER_TEST"):
        advance_build(build["id"], station, 5.00)
    water_test = schedule_booth_inspection(
        build["id"],
        booth["id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        headers=inspector_1,
    )
    complete_inspection(water_test["id"], 0, False, headers=inspector_1)
    advance_build(build["id"], "PDI", 5.00)
    pdi = schedule_pdi(build["id"], headers=inspector_2)
    complete_inspection(pdi["id"], 0, False, headers=inspector_2)
    advance_build(build["id"], "READY_TO_SHIP", 5.00)
    shipped = ship_order(order["id"])

    assert_cents(shipped["final_invoice_cents"], 6740350)

    validate_error(
        api.cancel_order(
            order["id"], dealer_headers, {"cancel_reason": "dealer changed its mind"}
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )
    validate_error(
        api.submit_order(order["id"], dealer_headers), ApiErrorId.ERR_ORDER_NOT_SUBMITTABLE
    )
    validate_error(
        api.advance_build(
            build["id"], {"to_station": "READY_TO_SHIP", "station_hours_used": 1.00}, supervisor_headers
        ),
        ApiErrorId.ERR_STATION_SEQUENCE_VIOLATION,
    )
    validate_error(api.ship_order(order["id"], scheduler_headers), ApiErrorId.ERR_INVALID_STATE)

    order_row = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
    assert order_row["status"] == "SHIPPED"
    assert _instant(order_row["shipped_at"]) == _instant("2026-08-01T00:00:00Z")
    assert_cents(order_row["final_invoice_cents"], 6740350)
    build_row = validate_success(api.get_unit_build(build["id"], plant_admin_headers))
    assert build_row["current_station"] == "SHIPPED"
    assert_hours(build_row["actual_station_hours"], "40.00")


def test_replayed_submit_and_campaign_open_are_refused_while_daily_close_repeats_cleanly(
    api, plant_admin_headers, recall_coordinator_headers
):
    """PRD §3.2: "It requires the order to be `DRAFT` — a second submit of an already `CONFIG_VALIDATED` order is rejected with `ERR_ORDER_NOT_SUBMITTABLE` — requires the acting `X-User-ID` to be the order's dealer, requires the referenced floor plan's `status` to be `ACTIVE` and the dealer's `status` to be `ACTIVE`, and requires every selected option's `status` to be `ACTIVE`."

    PRD §3.9: "**Opening** the campaign drives `status` `DRAFT → OPEN` and fires the plant's deepest cascade."

    PRD §2.8: "The addressed entity is in a state from which the requested transition exists, and the required companion rows are in their required states. The generic code is `ERR_INVALID_STATE` (409), but a specific code takes its place wherever one is defined: `ERR_ORDER_NOT_SUBMITTABLE`, `ERR_ORDER_NOT_SLOTTABLE`, `ERR_ORDER_ALREADY_MATCHED`, `ERR_CHASSIS_NOT_MATCHED`, `ERR_DEALER_SUSPENDED`, `ERR_FLOOR_PLAN_RETIRED`, `ERR_STATION_SEQUENCE_VIOLATION`, `ERR_LINE_NOT_RUNNING`, `ERR_BOOTH_NOT_OPEN`, `ERR_INSPECTION_STATION_MISMATCH`, `ERR_LOT_QUANTITY_INSUFFICIENT`, `ERR_CLAIM_NOT_DECIDABLE`, `ERR_INFO_REQUEST_LIMIT_REACHED`, `ERR_CAMPAIGN_NOT_CLOSEABLE`, `ERR_PAYMENT_EXCEEDS_PRINCIPAL`, and `ERR_QUALITY_HOLD`."

    PRD §3.9: "Its `open_recall_count` increases by one, its `penalty_event_count` increases by one, and its `quality_score` and `supplier_status` are recomputed — which can drop it to `PROBATION` or `SUSPENDED` and thereby, in one stroke, remove its chassis from the matching pool of §3.4 and raise the chargeback rate applied to its warranty claims in §3.8."

    PRD §3.9: "The event set is the same for both: every campaign of that supplier whose `status` is `OPEN` or `CLOSED` and whose `opened_at` is not null, weighted by severity at 15.0 for `SAFETY`, 10.0 for `COMPLIANCE`, and 4.0 for `ADVISORY`, timestamped at `opened_at`; plus every `APPROVED` or `PAID` warranty claim whose component lot belongs to that supplier and whose `supplier_chargeback_cents` is positive, weighted at 2.0 and timestamped at the claim's `created_at`."

    PRD §3.9: "`Supplier.quality_score` always holds the **rolling** figure, and `supplier_status` is derived from it alone: a score of 70.00 or more is `ACTIVE`, a score from 50.00 up to but not including 70.00 is `PROBATION`, and anything below 50.00 is `SUSPENDED`."

    PRD §2.5: "The response reports `released_slot_count`, the `released_order_ids` array of orders that came back out of `SLOTTED`, `curtailed_order_count`, the `curtailed_order_ids` array, and the `evaluated_at` instant at which the checkpoint ran. The checkpoint is idempotent within one clock instant: running it a second time without advancing the clock releases and curtails nothing further and reports zero counts."

    Design: Corner/state_machines/second_submit_and_second_campaign_open_are_rejected_while_daily_close_is_idempotent
    """
    supplier = create_supplier(
        supplier_code="SUP-CH",
        name="Cascade Chassis Works",
        component_categories=["CHASSIS", "APPLIANCE"],
    )
    create_component_lot(
        supplier["id"],
        part_number="WH-6G-2026",
        lot_code="L-2211",
        category="APPLIANCE",
        quantity_received=20,
    )
    campaign = draft_campaign(
        supplier["id"],
        campaign_code="RC-2026-01",
        part_number="WH-6G-2026",
        lot_codes=["L-2211"],
        severity="ADVISORY",
    )
    opened = open_campaign(campaign["id"])
    floor_plan, option, dealer = _tow_order_ingredients()
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )
    submitted = submit_order(order["id"], dealer["id"])

    validate_error(
        api.submit_order(order["id"], dealer_headers), ApiErrorId.ERR_ORDER_NOT_SUBMITTABLE
    )
    validate_error(
        api.open_recall_campaign(campaign["id"], recall_coordinator_headers),
        ApiErrorId.ERR_INVALID_STATE,
    )
    first_close = validate_success(api.daily_close(plant_admin_headers))
    second_close = validate_success(api.daily_close(plant_admin_headers))

    assert submitted["version"] == 2
    order_row = validate_success(api.get_unit_order(order["id"], dealer_headers))
    assert order_row["version"] == 2
    assert_cents(order_row["provisional_invoice_cents"], 6620350)
    assert opened["version"] == 2
    campaign_row = validate_success(
        api.get_recall_campaign(campaign["id"], recall_coordinator_headers)
    )
    assert campaign_row["version"] == 2
    assert campaign_row["affected_installation_count"] == 0
    supplier_row = validate_success(api.get_supplier(supplier["id"], plant_admin_headers))
    assert supplier_row["open_recall_count"] == 1
    assert supplier_row["penalty_event_count"] == 1
    assert_two_decimals(supplier_row["quality_score"], "96.00")
    assert supplier_row["supplier_status"] == "ACTIVE"
    assert first_close["released_slot_count"] == 0
    assert first_close["curtailed_order_count"] == 0
    assert second_close["released_slot_count"] == 0
    assert second_close["curtailed_order_count"] == 0
    assert _instant(first_close["evaluated_at"]) == _instant("2026-08-01T00:00:00Z")
    assert _instant(second_close["evaluated_at"]) == _instant("2026-08-01T00:00:00Z")


def test_replacing_the_option_set_walks_a_validated_order_back_to_draft_and_reprices(api):
    """PRD §3.2: "Replacement overwrites those two fields with the supplied values, re-runs the roll-up, and — when the order was `CONFIG_VALIDATED` — walks it back to `DRAFT`, clearing `locked_floor_plan_version`, emptying `locked_option_versions`, and resetting `provisional_invoice_cents` to 0. This is the revision cycle: `CONFIG_VALIDATED → DRAFT → CONFIG_VALIDATED`, traversable as many times as the dealer needs."

    PRD §3.2: "`option_price_total_cents` is the sum of `price_cents` across the selected options at list price."

    PRD §3.2: "Next choose a complexity factor from the *count* of selected options: four or fewer options (including none at all) gives 1.00; five through nine gives 1.05; ten through fourteen gives 1.12; fifteen or more gives 1.20."

    PRD §3.7: "Under the **provisional variant**, computed at submit, no build exists yet, so the three build-derived adjustments are all zero and `provisional_invoice_cents` is simply the discounted subtotal plus freight."

    PRD §3.7: "Freight is never discounted. It is a base of 180000 cents, plus 4200 cents for each foot of the floor plan's `length_ft`, plus a regional surcharge drawn from the dealer's `region`: 95000 cents for `WEST`, nothing for `CENTRAL`, 60000 cents for `EAST`, and 35000 cents for `SOUTH`."

    Design: Corner/state_machines/configuration_revision_cycle_returns_a_validated_order_to_draft
    """
    floor_plan, option, dealer = _tow_order_ingredients()
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )
    first = submit_order(order["id"], dealer["id"])

    edited = validate_success(
        api.replace_configuration(
            order["id"],
            {"selected_option_ids": [], "requested_delivery_date": "2026-11-01T00:00:00Z"},
            dealer_headers,
        )
    )
    resubmitted = validate_success(api.submit_order(order["id"], dealer_headers))

    assert_cents(first["provisional_invoice_cents"], 6620350)
    assert edited["status"] == "DRAFT"
    assert_cents(edited["provisional_invoice_cents"], 0)
    assert_hours(edited["required_station_hours"], "40.00")
    assert edited["locked_floor_plan_version"] is None
    assert edited["locked_option_versions"] == []
    assert _instant(edited["requested_delivery_date"]) == _instant("2026-11-01T00:00:00Z")
    assert_cents(edited["option_price_total_cents"], 0)
    assert_cents(resubmitted["provisional_invoice_cents"], 6537600)
    assert resubmitted["status"] == "CONFIG_VALIDATED"
    assert_hours(resubmitted["required_station_hours"], "40.00")
    assert resubmitted["total_amp_draw"] == 0
    assert resubmitted["config_weight_lbs"] == 6000
    assert resubmitted["payload_remaining_lbs"] == 3000
    assert resubmitted["locked_floor_plan_version"] == 1
    assert resubmitted["locked_option_versions"] == []
    assert resubmitted["version"] == 4


def test_slot_reservation_refuses_a_line_tooled_for_another_chassis_class(
    api, plant_admin_headers, scheduler_headers
):
    """PRD §3.3: "The line must be tooled for the coach: the line's `chassis_class_supported` must equal the floor plan's `chassis_class`, else `ERR_LINE_CLASS_MISMATCH`."

    PRD §2.8: "One further consequence of the ladder is worth stating plainly: `ERR_LINE_CLASS_MISMATCH` (422) — raised when the chosen line's `chassis_class_supported` does not equal the floor plan's `chassis_class` — is a configuration incompatibility, not a temporal or fiscal one, and it is reported before the day-bucket capacity checks of band 15."

    PRD §3.3: "A successful reservation drives the order's `status` from `CONFIG_VALIDATED` to `SLOTTED`."

    PRD §3.3: "The created slot is stamped `RESERVED` with `station_hours_committed` copied from the order's `required_station_hours` at the moment of reservation, a one-based `sequence_position` equal to the day bucket's occupied-unit count plus one (which is the coach's build order on that line that day), and an `expires_at` exactly 72 hours after the slot's `created_at`."

    PRD §2.7: "`POST /unit-orders/{id}/production-slots` requires `expected_unit_order_version`, carrying the client's last observed `version` of the target `UnitOrder`."

    Design: Corner/state_machines/slot_reservation_is_guarded_by_the_line_chassis_class
    """
    floor_plan, option, dealer = _tow_order_ingredients()
    line_c = create_production_line(
        line_code="LINE-C",
        chassis_class_supported="CLASS_C",
        daily_station_hour_capacity=240.00,
        max_units_per_day=4,
    )
    line_t = create_production_line(**LINE_T)
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )
    submitted = submit_order(order["id"], dealer["id"])

    validate_error(
        api.reserve_production_slot(
            order["id"],
            {
                "line_id": line_c["id"],
                "slot_date": "2026-08-05T00:00:00Z",
                "expected_unit_order_version": submitted["version"],
            },
            scheduler_headers,
        ),
        ApiErrorId.ERR_LINE_CLASS_MISMATCH,
    )

    after_refusal = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
    assert after_refusal["status"] == "CONFIG_VALIDATED"
    assert after_refusal["version"] == 2
    _rows, meta = validate_paginated(
        api.list_production_slots(scheduler_headers, params={"line_id": line_c["id"]})
    )
    assert meta["total_count"] == 0

    slot = validate_success(
        api.reserve_production_slot(
            order["id"],
            {
                "line_id": line_t["id"],
                "slot_date": "2026-08-05T00:00:00Z",
                "expected_unit_order_version": 2,
            },
            scheduler_headers,
        ),
        201,
    )
    assert slot["status"] == "RESERVED"
    assert slot["sequence_position"] == 1
    assert_hours(slot["station_hours_committed"], "41.00")
    assert _instant(slot["expires_at"]) == _instant("2026-08-04T00:00:00Z")
    order_row = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
    assert order_row["status"] == "SLOTTED"
    assert order_row["version"] == 3


def test_funding_approval_and_payoff_move_the_dealer_exposure_together(api, plant_admin_headers):
    """PRD §3.7: "A `DealerPrincipal` requests funding on its own order, driving `financing_status` `NOT_FINANCED → FUNDING_REQUESTED` while leaving `status` untouched; the request is admissible only while the order's `status` is `CONFIG_VALIDATED`, `SLOTTED`, `IN_PRODUCTION`, or `BUILT`, and only while the dealer's `status` is `ACTIVE`."

    PRD §3.7: "An approval requires a positive `provisional_invoice_cents` and advances `financing_status` `FUNDING_REQUESTED → FLOOR_PLAN_FUNDED`: the plant advances 9000 basis points of the provisional invoice, so `financed_principal_cents` is the provisional invoice multiplied by 9000, divided by 10000, and rounded half up to whole cents, and `funded_at` is stamped from the logical clock."

    PRD §3.7: "A dealer's `financed_exposure_cents` is the sum, across every one of its orders whose `financing_status` is `FLOOR_PLAN_FUNDED` or `CURTAILED`, of that order's `financed_principal_cents` minus its `curtailment_paid_cents`. Its `credit_utilization_bp` is that exposure multiplied by 10000 and divided by its `floor_plan_credit_limit_cents`, truncated toward zero to a whole number of basis points — and zero when the credit limit is zero. Its `credit_status` follows from two strictly-greater-than comparisons: utilisation above 9500 basis points is `CREDIT_HOLD`, utilisation above 8000 basis points (but not above 9500) is `WATCH`, and anything at or below 8000 is `GOOD_STANDING`."

    PRD §3.7: "A payment that brings the paid total to exactly the full `financed_principal_cents` retires the advance: `curtailment_paid_cents` becomes the full principal, `curtailment_due_cents` becomes zero, and `financing_status` moves to the terminal `PAID_OFF` from either `FLOOR_PLAN_FUNDED` or `CURTAILED`, removing the unit from the dealer's exposure set."

    Design: Corner/state_machines/funding_approval_syncs_the_dealer_exposure_ledger
    """
    floor_plan = create_floor_plan(**FP_TOW)
    option = create_option_item(**OPT_E1)
    dealer = create_dealer(
        dealer_code="D-LEDGER",
        region="CENTRAL",
        allocation_share_bp=1500,
        floor_plan_credit_limit_cents=12000000,
        goodwill_budget_cents=500000,
    )
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )
    submit_order(order["id"], dealer["id"])
    requested = request_funding(order["id"], dealer["id"])

    funded = validate_success(
        api.funding_decision(order["id"], {"decision": "APPROVED"}, plant_admin_headers)
    )
    dealer_after_funding = validate_success(api.get_dealer(dealer["id"], plant_admin_headers))
    paid = validate_success(
        api.floor_plan_payment(order["id"], {"amount_cents": 5958315}, dealer_headers)
    )
    dealer_after_payoff = validate_success(api.get_dealer(dealer["id"], plant_admin_headers))

    assert requested["financing_status"] == "FUNDING_REQUESTED"
    assert requested["status"] == "CONFIG_VALIDATED"
    assert_cents(funded["financed_principal_cents"], 5958315)
    assert _instant(funded["funded_at"]) == _instant("2026-08-01T00:00:00Z")
    assert funded["financing_status"] == "FLOOR_PLAN_FUNDED"
    assert_cents(funded["curtailment_due_cents"], 0)
    assert_cents(dealer_after_funding["financed_exposure_cents"], 5958315)
    assert dealer_after_funding["credit_utilization_bp"] == 4965
    assert dealer_after_funding["credit_status"] == "GOOD_STANDING"
    assert paid["financing_status"] == "PAID_OFF"
    assert_cents(paid["curtailment_paid_cents"], 5958315)
    assert_cents(dealer_after_payoff["financed_exposure_cents"], 0)
    assert dealer_after_payoff["credit_utilization_bp"] == 0
    assert dealer_after_payoff["credit_status"] == "GOOD_STANDING"


def test_cancelling_a_slotted_order_releases_the_slot_and_frees_the_chassis(
    api, plant_admin_headers, scheduler_headers
):
    """PRD §3.2: "A dealer may **cancel** an order whose `status` is `DRAFT`, `CONFIG_VALIDATED`, or `SLOTTED`, optionally supplying a `cancel_reason`, driving `status` to `CANCELLED`. Cancellation from `SLOTTED` unwinds the commitments the order was holding: its `RESERVED` slot moves `RESERVED → RELEASED`, any chassis whose `matched_unit_order_id` names this order and whose `status` is `MATCHED` moves `MATCHED → RECEIVED` with `matched_unit_order_id` cleared, and the dealer's `allocation_slots_reserved` and `allocation_hours_consumed` are recomputed."

    PRD §3.4: "The winning chassis moves `RECEIVED → MATCHED` with `matched_unit_order_id` set to the order."

    PRD §3.4: "Eligibility is a six-part filter, and every part must hold. The candidate's `status` must be `RECEIVED`. Its `matched_unit_order_id` must be null."

    PRD §3.3: "In every case the released hours stop counting toward both the line-day and the monthly ceilings, and the dealer's allocation counters are recomputed."

    Design: Corner/state_machines/cancelling_a_slotted_order_compensates_the_slot_and_the_chassis
    """
    supplier = create_supplier(
        supplier_code="SUP-CH", name="Cascade Chassis Works", component_categories=["CHASSIS"]
    )
    floor_plan, option, dealer = _tow_order_ingredients()
    line = create_production_line(**LINE_T)
    chassis = create_chassis_receipt(supplier["id"], **CH_T1)
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
    )
    submitted = submit_order(order["id"], dealer["id"])
    slot = reserve_slot(order["id"], line["id"], "2026-08-05T00:00:00Z", submitted["version"])
    matched = match_chassis(order["id"])

    cancelled = validate_success(
        api.cancel_order(
            order["id"], dealer_headers, {"cancel_reason": "retail deal fell through"}
        )
    )
    chassis_row = validate_success(api.get_chassis_receipt(chassis["id"], scheduler_headers))
    slot_row = validate_success(api.get_production_slot(slot["id"], scheduler_headers))
    dealer_row = validate_success(api.get_dealer(dealer["id"], plant_admin_headers))

    assert matched["status"] == "MATCHED"
    assert cancelled["status"] == "CANCELLED"
    assert chassis_row["status"] == "RECEIVED"
    assert chassis_row["matched_unit_order_id"] is None
    assert slot_row["status"] == "RELEASED"
    assert dealer_row["allocation_slots_reserved"] == 0
    assert_hours(dealer_row["allocation_hours_consumed"], "0.00")
    _receipts, receipt_meta = validate_paginated(
        api.list_chassis_receipts(scheduler_headers, params={"status": "RECEIVED"})
    )
    assert receipt_meta["total_count"] == 1
    _builds, build_meta = validate_paginated(
        api.list_unit_builds(plant_admin_headers, params={"unit_order_id": order["id"]})
    )
    assert build_meta["total_count"] == 0


def test_the_last_remedy_clears_the_recall_hold_and_lets_the_campaign_close(
    api, plant_admin_headers, scheduler_headers, supervisor_headers, recall_coordinator_headers
):
    """PRD §3.9: "Hop one freezes supply. Every matching lot moves to `QUARANTINED` — from `AVAILABLE` or from `DEPLETED` alike — by adding its remaining `quantity_available` to its `quantity_quarantined` and then setting `quantity_available` to zero."

    PRD §3.9: "Every installation drawing from those lots whose `status` is `INSTALLED` moves `INSTALLED → RECALL_AFFECTED`, records the campaign as its `recall_campaign_id`, and increments the campaign's `affected_installation_count`. Each such labelling sets `recall_hold` to true on the build that received the pieces, which immediately blocks that build from advancing another station."

    PRD §3.9: "For every held build not already `SHIPPED`, when the campaign's `ship_stop` is true the owning order's `ship_hold_reason` becomes `RECALL_HOLD`."

    PRD §3.9: "A `RecallCoordinator` records that a `RECALL_AFFECTED` installation has been remedied, optionally with a `remedy_note`, while the labelling campaign is still `OPEN`, moving the installation `RECALL_AFFECTED → REMEDIED` and incrementing the campaign's `remedied_installation_count`. When that leaves no installation on the build still `RECALL_AFFECTED`, the build's `recall_hold` returns to false, and if the owning order's `ship_hold_reason` was `RECALL_HOLD` it is set back to `NONE` — releasing both the line and the yard."

    PRD §3.9: "**Closing** a campaign drives `status` `OPEN → CLOSED` and requires that `remedied_installation_count` equal `affected_installation_count` — an unfinished campaign is refused with `ERR_CAMPAIGN_NOT_CLOSEABLE`. Closing decrements the supplier's `open_recall_count` by one and rescores it, but the penalty event itself survives the close: a closed campaign still weighs on the trust score. Quarantined pieces are never returned to `quantity_available`; recalled stock stays frozen permanently."

    PRD §3.5: "Note that a lot's `quantity_installed` counts pieces held by installations in `INSTALLED`, `RECALL_AFFECTED`, or `REMEDIED` — a recall re-labels an installation without returning its pieces, so only reversal moves them back."

    PRD §3.9: "The event set is the same for both: every campaign of that supplier whose `status` is `OPEN` or `CLOSED` and whose `opened_at` is not null, weighted by severity at 15.0 for `SAFETY`, 10.0 for `COMPLIANCE`, and 4.0 for `ADVISORY`, timestamped at `opened_at`; plus every `APPROVED` or `PAID` warranty claim whose component lot belongs to that supplier and whose `supplier_chargeback_cents` is positive, weighted at 2.0 and timestamped at the claim's `created_at`."

    PRD §3.9: "`Supplier.quality_score` always holds the **rolling** figure, and `supplier_status` is derived from it alone: a score of 70.00 or more is `ACTIVE`, a score from 50.00 up to but not including 70.00 is `PROBATION`, and anything below 50.00 is `SUSPENDED`."

    Design: Corner/state_machines/remedying_the_last_affected_installation_clears_the_build_hold
    """
    supplier = create_supplier(
        supplier_code="SUP-CH",
        name="Cascade Chassis Works",
        component_categories=["CHASSIS", "APPLIANCE"],
    )
    floor_plan, option, dealer = _tow_order_ingredients()
    line = create_production_line(**LINE_T)
    create_chassis_receipt(supplier["id"], **CH_T1)
    lot = create_component_lot(
        supplier["id"],
        part_number="WH-6G-2026",
        lot_code="L-2211",
        category="APPLIANCE",
        quantity_received=20,
    )
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="SOLD",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
        customer_reference="RETAIL-91",
    )
    submitted = submit_order(order["id"], dealer["id"])
    reserve_slot(order["id"], line["id"], "2026-08-05T00:00:00Z", submitted["version"])
    match_chassis(order["id"])
    build = release_to_line(order["id"])
    for station in ("SIDEWALL_LAM", "ROOF_SET", "ROUGH_IN", "APPLIANCE_INSTALL"):
        advance_build(build["id"], station, 5.00)
    installation_a = install_pieces(build["id"], lot["id"], "APPLIANCE_INSTALL", 5)
    installation_b = install_pieces(build["id"], lot["id"], "APPLIANCE_INSTALL", 3)
    campaign = draft_campaign(
        supplier["id"],
        campaign_code="RC-2026-07",
        part_number="WH-6G-2026",
        lot_codes=["L-2211"],
        severity="SAFETY",
    )
    opened = open_campaign(campaign["id"])

    assert opened["affected_installation_count"] == 2
    lot_after_open = validate_success(api.get_component_lot(lot["id"], plant_admin_headers))
    assert lot_after_open["status"] == "QUARANTINED"
    assert lot_after_open["quantity_quarantined"] == 12
    assert lot_after_open["quantity_available"] == 0
    assert lot_after_open["quantity_installed"] == 8
    assert_lot_counter_invariant(lot_after_open)

    validate_error(
        api.close_recall_campaign(campaign["id"], recall_coordinator_headers),
        ApiErrorId.ERR_CAMPAIGN_NOT_CLOSEABLE,
    )

    remedied_a = validate_success(
        api.remedy_installation(
            installation_a["id"], recall_coordinator_headers, {"remedy_note": "harness clamp replaced"}
        )
    )
    assert remedied_a["status"] == "REMEDIED"
    campaign_mid = validate_success(
        api.get_recall_campaign(campaign["id"], recall_coordinator_headers)
    )
    assert campaign_mid["remedied_installation_count"] == 1
    build_mid = validate_success(api.get_unit_build(build["id"], supervisor_headers))
    assert build_mid["recall_hold"] is True

    remedied_b = validate_success(
        api.remedy_installation(
            installation_b["id"],
            recall_coordinator_headers,
            {"remedy_note": "second harness clamp replaced"},
        )
    )
    assert remedied_b["status"] == "REMEDIED"
    campaign_end = validate_success(
        api.get_recall_campaign(campaign["id"], recall_coordinator_headers)
    )
    assert campaign_end["remedied_installation_count"] == 2
    build_end = validate_success(api.get_unit_build(build["id"], supervisor_headers))
    assert build_end["recall_hold"] is False
    order_end = validate_success(api.get_unit_order(order["id"], scheduler_headers))
    assert order_end["ship_hold_reason"] == "NONE"

    closed = validate_success(
        api.close_recall_campaign(campaign["id"], recall_coordinator_headers)
    )
    assert closed["status"] == "CLOSED"
    supplier_row = validate_success(api.get_supplier(supplier["id"], plant_admin_headers))
    assert supplier_row["open_recall_count"] == 0
    assert supplier_row["penalty_event_count"] == 1
    assert_two_decimals(supplier_row["quality_score"], "85.00")
    assert supplier_row["supplier_status"] == "ACTIVE"
    lot_end = validate_success(api.get_component_lot(lot["id"], plant_admin_headers))
    assert lot_end["quantity_available"] == 0


def test_water_test_entry_waits_for_an_installation_from_a_plumbing_lot(
    api, plant_admin_headers, supervisor_headers
):
    """PRD §3.5: "Entering `WATER_TEST` from `FINISH` requires that the systems actually installed match what the order bought: for each of the categories `APPLIANCE` and `PLUMBING` that appears among the order's selected options, at least one installation on this build must be in `status` `INSTALLED` drawing from a component lot of that same category."

    PRD §2.8: "The addressed entity is in a state from which the requested transition exists, and the required companion rows are in their required states. The generic code is `ERR_INVALID_STATE` (409), but a specific code takes its place wherever one is defined: `ERR_ORDER_NOT_SUBMITTABLE`, `ERR_ORDER_NOT_SLOTTABLE`, `ERR_ORDER_ALREADY_MATCHED`, `ERR_CHASSIS_NOT_MATCHED`, `ERR_DEALER_SUSPENDED`, `ERR_FLOOR_PLAN_RETIRED`, `ERR_STATION_SEQUENCE_VIOLATION`, `ERR_LINE_NOT_RUNNING`, `ERR_BOOTH_NOT_OPEN`, `ERR_INSPECTION_STATION_MISMATCH`, `ERR_LOT_QUANTITY_INSUFFICIENT`, `ERR_CLAIM_NOT_DECIDABLE`, `ERR_INFO_REQUEST_LIMIT_REACHED`, `ERR_CAMPAIGN_NOT_CLOSEABLE`, `ERR_PAYMENT_EXCEEDS_PRINCIPAL`, and `ERR_QUALITY_HOLD`."

    PRD §3.2: "It then walks the physical and commercial gates in the fixed order of §2.8: gross weight first, where `config_weight_lbs` may not exceed the floor plan's `gvwr_lbs`; then shore power, where `total_amp_draw` may not exceed the floor plan's `electrical_service_amps`; then the water system, where `total_water_demand_gal` may not exceed half of the floor plan's `fresh_water_capacity_gal` — the ceiling is 5000 basis points of tank capacity, rounded half up to a whole gallon, and plumbed options may claim at most that much; then the option-set consistency band."

    PRD §3.5: "On success the reported `station_hours_used` is added to the build's `actual_station_hours`, which accumulates across the whole build including every rework loop, and which later becomes the overtime term of the final invoice."

    PRD §3.5: "On success the lot's `quantity_available` decreases by the installed quantity and its `quantity_installed` increases by the same amount, conserving the piece total, and a lot whose `quantity_available` reaches exactly zero moves `AVAILABLE → DEPLETED`. The new installation starts at `status` `INSTALLED` with `recall_campaign_id` null."

    Design: Corner/state_machines/water_test_gate_applies_only_when_a_plumbed_option_is_ordered
    """
    supplier = create_supplier(
        supplier_code="SUP-CH",
        name="Cascade Chassis Works",
        component_categories=["CHASSIS", "PLUMBING"],
    )
    floor_plan = create_floor_plan(**FP_TOW)
    option = create_option_item(
        option_code="OPT-P1",
        category="PLUMBING",
        install_station="ROUGH_IN",
        price_cents=100000,
        weight_lbs=0,
        added_station_hours=1.00,
        amp_draw=0,
        water_demand_gal=20,
    )
    dealer = create_dealer(**D_TOW)
    line = create_production_line(**LINE_T)
    create_chassis_receipt(supplier["id"], **CH_T1)
    lot = create_component_lot(
        supplier["id"],
        part_number="PL-TANK-40",
        lot_code="L-PL",
        category="PLUMBING",
        quantity_received=10,
    )
    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="SOLD",
        selected_option_ids=[option["id"]],
        requested_delivery_date="2026-10-01T00:00:00Z",
        customer_reference="RETAIL-104",
    )
    submitted = submit_order(order["id"], dealer["id"])
    reserve_slot(order["id"], line["id"], "2026-08-05T00:00:00Z", submitted["version"])
    match_chassis(order["id"])
    build = release_to_line(order["id"])
    at_finish = None
    for station in ("SIDEWALL_LAM", "ROOF_SET", "ROUGH_IN", "APPLIANCE_INSTALL", "FINISH"):
        at_finish = advance_build(build["id"], station, 5.00)

    assert submitted["total_water_demand_gal"] == 20
    assert_hours(submitted["required_station_hours"], "41.00")

    validate_error(
        api.advance_build(
            build["id"], {"to_station": "WATER_TEST", "station_hours_used": 5.00}, supervisor_headers
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )

    assert_hours(at_finish["actual_station_hours"], "25.00")
    build_after_refusal = validate_success(api.get_unit_build(build["id"], supervisor_headers))
    assert_hours(build_after_refusal["actual_station_hours"], "25.00")
    assert build_after_refusal["current_station"] == "FINISH"

    installation = validate_success(
        api.create_component_installation(
            {
                "unit_build_id": build["id"],
                "component_lot_id": lot["id"],
                "station": "FINISH",
                "quantity": 1,
            },
            supervisor_headers,
        ),
        201,
    )
    assert installation["status"] == "INSTALLED"
    assert installation["quantity"] == 1
    lot_row = validate_success(api.get_component_lot(lot["id"], plant_admin_headers))
    assert lot_row["quantity_available"] == 9
    assert lot_row["quantity_installed"] == 1

    advanced = validate_success(
        api.advance_build(
            build["id"], {"to_station": "WATER_TEST", "station_hours_used": 5.00}, supervisor_headers
        )
    )
    assert advanced["current_station"] == "WATER_TEST"
    assert_hours(advanced["actual_station_hours"], "30.00")


def test_commissioning_a_second_line_raises_every_dealer_entitlement(
    api, plant_admin_headers, scheduler_headers
):
    """PRD §3.1: "Commissioning a line moves every dealer's `entitlement_hours`, because the entitlement formula reads total plant capacity rather than a stored constant."

    PRD §3.3: "Sum the `daily_station_hour_capacity` of every commissioned line whose `status` is `RUNNING` or `PAUSED` — a paused line still counts toward the plant's nominal capacity — multiply by twenty working days per month, and round half up to two decimals: that is the plant's monthly hours. Multiply that by the dealer's `allocation_share_bp` and divide by 10000, rounding half up to two decimals: that is the dealer's `entitlement_hours`."

    PRD §3.1: "A dealer's derived position — `financed_exposure_cents`, `credit_utilization_bp`, `credit_status` (initialised to `GOOD_STANDING`), `goodwill_used_cents`, `entitlement_hours`, `allocation_hours_consumed`, and `allocation_slots_reserved` — is recomputed whenever the dealer record is read, so a read is always current."

    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the row."

    Design: Corner/state_machines/commissioning_a_line_moves_every_dealer_entitlement
    """
    dealer = create_dealer(**D_TOW)
    create_production_line(**LINE_T)

    first_read = validate_success(api.get_dealer(dealer["id"], plant_admin_headers))
    second_line = validate_success(
        api.create_production_line(
            {
                "line_code": "LINE-T2",
                "chassis_class_supported": "TOWABLE",
                "daily_station_hour_capacity": 240.00,
                "max_units_per_day": 4,
            },
            plant_admin_headers,
        ),
        201,
    )
    second_read = validate_success(api.get_dealer(dealer["id"], plant_admin_headers))
    paused = validate_success(
        api.set_production_line_status(second_line["id"], {"status": "PAUSED"}, scheduler_headers)
    )
    third_read = validate_success(api.get_dealer(dealer["id"], plant_admin_headers))

    assert_hours(first_read["entitlement_hours"], "720.00")
    assert_hours(second_read["entitlement_hours"], "1440.00")
    assert first_read["version"] == 1
    assert second_read["version"] == 1
    assert paused["status"] == "PAUSED"
    assert_hours(third_read["entitlement_hours"], "1440.00")
    for read in (first_read, second_read, third_read):
        assert_hours(read["allocation_hours_consumed"], "0.00")
        assert read["allocation_slots_reserved"] == 0
