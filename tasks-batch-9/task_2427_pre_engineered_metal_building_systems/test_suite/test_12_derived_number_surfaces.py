"""The derived numbers a caller reads back off a row or a computed read.

Rollups that filter their own input set, load constants that move one field and
leave the neighbouring ones alone, kit extensions that travel into two different
totals by two different routes, and the projection that puts truckloads into
erection order.
"""

from test_helpers import (
    PLANNER,
    SALES,
    assert_erection_sequence,
    assert_order_dimensions,
    assert_rate,
    assert_weight,
    add_accessory_kit,
    authorize_builder,
    cancel_lot,
    chain_authorized_builder,
    chain_released_order,
    complete_lot,
    connection_component_payload,
    create_builder,
    create_configuration,
    create_jurisdiction,
    create_production_line,
    create_quote,
    dispatch_load,
    get_erection_sequence,
    get_order,
    get_production_lot,
    get_shipment_load,
    lock_configuration,
    member_component_payload,
    minimal_bom,
    plan_load,
    schedule_lot,
    set_clock,
    validate_paginated,
)

#: A bill spanning the anchorage, the primary frame and the secondary frame, with
#: two separate anchor marks so two trucks can share the earliest stage.
SEQUENCE_BILL = [
    member_component_payload(
        mark="C-1", member_type="COLUMN", quantity=10, length_ft=24.5, weight_per_ft=62.35
    ),
    member_component_payload(
        mark="P-1",
        component_class="SECONDARY_MEMBER",
        member_type="PURLIN",
        erection_stage="SECONDARY_FRAME",
        quantity=40,
        length_ft=25.083,
        weight_per_ft=3.375,
    ),
    member_component_payload(
        mark="AB-1",
        component_class="ANCHOR_PACKAGE",
        member_type="ANCHOR_BOLT",
        erection_stage="ANCHORAGE",
        quantity=10,
        length_ft=1.5,
        weight_per_ft=2.2,
    ),
    member_component_payload(
        mark="AB-2",
        component_class="ANCHOR_PACKAGE",
        member_type="ANCHOR_BOLT",
        erection_stage="ANCHORAGE",
        quantity=6,
        length_ft=1.5,
        weight_per_ft=2.2,
    ),
    connection_component_payload(
        mark="K-1", connection_type="KNEE", capacity_moment_kip_ft=1100
    ),
    connection_component_payload(
        mark="B-1", connection_type="BASE", capacity_moment_kip_ft=900,
        erection_stage="ANCHORAGE",
    ),
]

#: The window the cancelled roll-forming lot occupied and then gave back.
ROLL_FORM_WINDOW = {
    "window_start": "2026-08-11T08:00:00Z",
    "window_end": "2026-08-11T12:00:00Z",
}


def _released_order_and_three_lines():
    """A released order with one line for each of the three fabrication steps."""
    chain = chain_released_order(components=minimal_bom())
    chain["plate"] = create_production_line(
        code="PL-1", name="Plate Line 1", line_type="PLATE_CUT_WELD"
    )
    chain["roll"] = create_production_line(
        code="PL-2", name="Roll Former 1", line_type="ROLL_FORM"
    )
    chain["panel"] = create_production_line(
        code="PL-3", name="Panel Line 1", line_type="PANEL_ROLL"
    )
    return chain


def _order_with_four_planned_trucks():
    """One released order carrying four trucks planned out of erection order."""
    chain = chain_released_order(components=SEQUENCE_BILL)
    order_id = chain["order"]["id"]
    chain["secondary"] = plan_load(
        order_id,
        component_marks=["P-1"],
        erection_stage="SECONDARY_FRAME",
        unload_window_start="2026-09-17T08:00:00Z",
        unload_window_end="2026-09-17T12:00:00Z",
    )
    chain["anchorage_first"] = plan_load(
        order_id,
        component_marks=["AB-1"],
        erection_stage="ANCHORAGE",
        unload_window_start="2026-09-15T08:00:00Z",
        unload_window_end="2026-09-15T12:00:00Z",
    )
    chain["primary"] = plan_load(
        order_id,
        component_marks=["C-1"],
        erection_stage="PRIMARY_FRAME",
        unload_window_start="2026-09-16T08:00:00Z",
        unload_window_end="2026-09-16T12:00:00Z",
    )
    chain["anchorage_second"] = plan_load(
        order_id,
        component_marks=["AB-2"],
        erection_stage="ANCHORAGE",
        unload_window_start="2026-09-18T08:00:00Z",
        unload_window_end="2026-09-18T12:00:00Z",
    )
    return chain


def test_01_a_cancelled_lot_leaves_the_production_rollup_input_set():
    """Cancelling a lot cannot advance the order, because it is no longer counted.

    PRD §3.8: "Otherwise the projection looks at the order's active lots, meaning
    those whose ``status`` is ``SCHEDULED`` or ``COMPLETE``, with ``CANCELLED``
    lots excluded from the rollup entirely."

    PRD §3.8: "In every other case the result is ``PROD_IN_FABRICATION`` — which
    covers both a lot still ``SCHEDULED`` and the case where all lots are complete
    but one of the three required fabrication steps was never scheduled."

    PRD §3.8: "A planner may instead cancel a ``SCHEDULED`` lot, which sets
    ``status`` to ``CANCELLED``, frees the lot's line window for future
    scheduling, re-runs the rollup, and increments both versions."

    Design: Corner/calculations/cancelled_lots_leave_the_rollup_input_set_and_free_their_line_window
    """
    chain = _released_order_and_three_lines()
    order_id = chain["order"]["id"]

    frame_lot = schedule_lot(
        order_id, chain["plate"]["id"],
        lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
        window_start="2026-08-10T08:00:00Z", window_end="2026-08-10T12:00:00Z",
    )
    assert get_order(order_id)["production_status"] == "PROD_IN_FABRICATION"

    complete_lot(frame_lot["id"])
    # One of the three required fabrication steps is complete, the other two were
    # never scheduled, so the order cannot be finished.
    assert get_order(order_id)["production_status"] == "PROD_IN_FABRICATION"

    roll_lot = schedule_lot(
        order_id, chain["roll"]["id"],
        lot_type="SECONDARY_ROLL_FORM", paint_color="POLAR_WHITE",
        **ROLL_FORM_WINDOW,
    )
    cancel_lot(roll_lot["id"])

    assert get_order(order_id)["production_status"] == "PROD_IN_FABRICATION"
    cancelled = get_production_lot(roll_lot["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["completed_at"] is None


def test_02_a_cancelled_lot_hands_its_line_window_back(api):
    """The replacement lot books the identical window and finishes the order.

    PRD §3.8: "The occupants of a line are its lots whose ``status`` is
    ``SCHEDULED`` or ``COMPLETE``; a ``CANCELLED`` lot frees its window entirely
    and is never an occupant."

    PRD §3.8: "If every active lot is ``COMPLETE`` **and** the set of ``lot_type``
    values across those lots is exactly the three required types
    ``PRIMARY_FRAME_FAB``, ``SECONDARY_ROLL_FORM`` and ``PANEL_RUN``, the result is
    ``PROD_COMPLETE``."

    Design: Corner/calculations/cancelled_lots_leave_the_rollup_input_set_and_free_their_line_window
    """
    chain = _released_order_and_three_lines()
    order_id = chain["order"]["id"]
    frame_lot = schedule_lot(
        order_id, chain["plate"]["id"],
        lot_type="PRIMARY_FRAME_FAB", paint_color="POLAR_WHITE",
        window_start="2026-08-10T08:00:00Z", window_end="2026-08-10T12:00:00Z",
    )
    complete_lot(frame_lot["id"])
    cancelled_roll_lot = schedule_lot(
        order_id, chain["roll"]["id"],
        lot_type="SECONDARY_ROLL_FORM", paint_color="POLAR_WHITE",
        **ROLL_FORM_WINDOW,
    )
    cancel_lot(cancelled_roll_lot["id"])

    replacement = schedule_lot(
        order_id, chain["roll"]["id"],
        lot_type="SECONDARY_ROLL_FORM", paint_color="POLAR_WHITE",
        **ROLL_FORM_WINDOW,
    )
    complete_lot(replacement["id"])
    panel_lot = schedule_lot(
        order_id, chain["panel"]["id"],
        lot_type="PANEL_RUN", paint_color="POLAR_WHITE",
        window_start="2026-08-12T08:00:00Z", window_end="2026-08-12T12:00:00Z",
    )
    complete_lot(panel_lot["id"])

    assert replacement["status"] == "SCHEDULED"
    assert_order_dimensions(get_order(order_id), "ENG_SEALED", "PROD_COMPLETE")
    lots, meta = validate_paginated(
        api.list_production_lots(PLANNER, params={"order_id": order_id})
    )
    assert meta["total_count"] == 4
    assert len([lot for lot in lots if lot["status"] == "CANCELLED"]) == 1


def test_03_the_exposure_coefficient_moves_the_wind_pressure_and_nothing_else():
    """Two jurisdictions differing only in exposure produce one differing load.

    PRD §3.3: "An exposure coefficient is selected from the jurisdiction's
    ``exposure_category``: exposure ``B`` gives 0.70, exposure ``C`` gives 0.85,
    and exposure ``D`` gives 1.03."

    PRD §3.3: "The velocity pressure is 0.00256 multiplied by that exposure
    coefficient multiplied by the square of the jurisdiction's
    ``design_wind_speed_mph``, rounded half up to four decimal places."

    PRD §3.3: "``design_wind_pressure_psf`` is the velocity pressure multiplied by
    the governing pressure coefficient multiplied by the height factor, rounded
    half up to two decimal places."

    Design: Corner/calculations/exposure_category_constant_alone_shifts_the_design_wind_pressure
    """
    set_clock()
    harris = create_jurisdiction()
    galveston = create_jurisdiction(
        code="TX-GALVESTON", name="Galveston County TX", exposure_category="D"
    )
    builder = create_builder(harris["id"])
    authorize_builder(builder["id"])
    exposure_c = create_configuration(builder["id"], harris["id"])
    exposure_d = create_configuration(builder["id"], galveston["id"])

    locked_c = lock_configuration(exposure_c["id"])
    locked_d = lock_configuration(exposure_d["id"])

    assert locked_c["design_wind_pressure_psf"] == 48.79
    assert locked_d["design_wind_pressure_psf"] == 59.12
    for locked in (locked_c, locked_d):
        # The pitch of 1 selects the roof coefficient 1.10 over the wall value
        # 0.90, and the 24 ft eave earns a height factor of 1.04, in both.
        assert locked["dead_load_psf"] == 3.08
        assert locked["roof_snow_load_psf"] == 3.50
        assert_rate(locked["roof_slope_factor"], 1.0035)
        assert_weight(locked["panel_area_sqft"], 19635.00)
        assert_weight(locked["estimated_frame_weight_lbs"], 49680.00)


def test_04_a_kit_extends_its_price_exactly_and_its_weight_by_rounding(api):
    """Money extends as an exact integer, weight extends and then rounds.

    PRD §3.4: "The kit stores its ``configuration_id`` and the server immediately
    derives two extensions: ``extended_price_cents`` is ``unit_price_cents``
    multiplied by ``quantity``, an exact integer with no rounding, and
    ``extended_weight_lbs`` is ``unit_weight_lbs`` multiplied by ``quantity``,
    rounded half up to two decimal places."

    PRD §3.4: "Kits are never cancelled and have no lifecycle state, so every kit
    ever attached to a configuration participates in every subsequent price and
    weight computation for that configuration."

    Design: Corner/calculations/accessory_kit_extended_amounts_aggregate_into_cost_and_freight
    """
    chain = chain_authorized_builder()
    configuration = create_configuration(
        chain["builder"]["id"], chain["jurisdiction"]["id"]
    )

    door = add_accessory_kit(
        configuration["id"],
        kit_type="OVERHEAD_DOOR", quantity=2,
        unit_price_cents=385075, unit_weight_lbs=640.5,
        erection_stage="TRIM_ACCESSORY",
    )
    vent = add_accessory_kit(
        configuration["id"],
        kit_type="VENTILATION", quantity=3,
        unit_price_cents=129933, unit_weight_lbs=88.25,
        erection_stage="ROOF_PANEL",
    )

    assert door["extended_price_cents"] == 770150
    assert_weight(door["extended_weight_lbs"], 1281.00)
    assert vent["extended_price_cents"] == 389799
    assert_weight(vent["extended_weight_lbs"], 264.75)
    kits, meta = validate_paginated(
        api.list_accessory_kits(configuration["id"], SALES)
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in kits} == {door["id"], vent["id"]}


def test_05_kit_money_reaches_the_subtotal_and_kit_weight_reaches_the_freight():
    """The two extensions are aggregated by two different steps of the pipeline.

    PRD §3.4: "``accessory_cost_cents`` is the sum of ``extended_price_cents`` over
    every accessory kit of the configuration, with no status filter because kits
    have no status."

    PRD §3.4: "``billable_weight_lbs`` is ``billable_frame_weight_lbs`` plus the
    sum of ``extended_weight_lbs`` over every accessory kit of the configuration,
    rounded half up to two decimal places."

    PRD §3.4: "``billable_tons`` is ``billable_weight_lbs`` divided by 2000,
    rounded half up to three decimal places."

    PRD §3.4: "``freight_cost_cents`` is ``billable_tons`` multiplied by the rate
    for the jurisdiction's ``freight_zone`` multiplied by the quote's
    ``freight_distance_miles``, rounded half up to whole cents."

    Design: Corner/calculations/accessory_kit_extended_amounts_aggregate_into_cost_and_freight
    """
    chain = chain_authorized_builder()
    configuration = create_configuration(
        chain["builder"]["id"], chain["jurisdiction"]["id"]
    )
    add_accessory_kit(
        configuration["id"],
        kit_type="OVERHEAD_DOOR", quantity=2,
        unit_price_cents=385075, unit_weight_lbs=640.5,
        erection_stage="TRIM_ACCESSORY",
    )
    add_accessory_kit(
        configuration["id"],
        kit_type="VENTILATION", quantity=3,
        unit_price_cents=129933, unit_weight_lbs=88.25,
        erection_stage="ROOF_PANEL",
    )
    lock_configuration(configuration["id"])

    quote = create_quote(
        chain["builder"]["id"], configuration["id"],
        freight_distance_miles=240, adjustment_cents=0,
    )

    assert quote["accessory_cost_cents"] == 1159949
    # Steel 4570560 plus panel 4123350 plus accessories 1159949.
    assert quote["subtotal_cents"] == 9853859
    # The estimated frame weight 49680.00 plus 1545.75 pounds of kits.
    assert_weight(quote["billable_weight_lbs"], 51225.75)
    assert quote["billable_tons"] == 25.613
    # Zone 3 bills 27 cents per ton-mile over 240 miles; leaving the kit weight
    # out of the tonnage would have produced 160963.
    assert quote["freight_cost_cents"] == 165972


def test_06_the_erection_projection_sorts_by_stage_then_by_creation_time():
    """Four trucks planned out of order come back in the order the crew needs.

    PRD §3.9: "It considers the order's shipment loads whose ``status`` is
    ``PLANNED`` or ``DISPATCHED``, excluding ``CANCELLED`` ones, and sorts them by
    ``stage_sequence`` ascending with ``created_at`` ascending as the tie-break;
    the sort never falls back to ``id``."

    PRD §2.12: "The six stages are ``ANCHORAGE``, ``PRIMARY_FRAME``,
    ``SECONDARY_FRAME``, ``ROOF_PANEL``, ``WALL_PANEL``, ``TRIM_ACCESSORY``, and
    they carry sequence numbers 1 through 6 in exactly that order: anchorage is 1,
    primary frame is 2, secondary frame is 3, roof panel is 4, wall panel is 5,
    trim and accessory is 6."

    PRD §3.9: "and ``blocked_load_count``, the number of ``PLANNED`` loads whose
    ``stage_sequence`` is strictly greater than the smallest ``stage_sequence``
    found among the ``PLANNED`` loads."

    Design: Corner/calculations/erection_sequence_orders_by_stage_then_creation_time
    """
    chain = _order_with_four_planned_trucks()

    projection = get_erection_sequence(chain["order"]["id"])

    assert_erection_sequence(
        projection,
        order_id=chain["order"]["id"],
        sequence="ANCHORAGE>ANCHORAGE>PRIMARY_FRAME>SECONDARY_FRAME",
        next_dispatchable_stage="ANCHORAGE",
        planned_load_count=4,
        # The smallest stage_sequence among the PLANNED loads is 1, and both
        # anchorage trucks sit at 1; only the primary-frame (2) and
        # secondary-frame (3) trucks are strictly greater than it.
        blocked_load_count=2,
        dispatched_load_count=0,
    )
    assert chain["anchorage_first"]["stage_sequence"] == 1
    assert chain["secondary"]["stage_sequence"] == 3


def test_07_a_dispatched_truck_stays_in_the_projection_and_stops_blocking():
    """Sending the first anchor load moves the counts, not the ordering.

    PRD §3.9: "The response carries the ``order_id``; ``sequence``, the ordered
    ``erection_stage`` values joined with the ">" character;
    ``next_dispatchable_stage``, the ``erection_stage`` of the first load in that
    ordering whose ``status`` is ``PLANNED``, or the literal string "NONE" when no
    load is still planned; ``planned_load_count``, the number of loads whose
    ``status`` is ``PLANNED``; ``dispatched_load_count``, the number whose
    ``status`` is ``DISPATCHED``; and ``blocked_load_count``, the number of
    ``PLANNED`` loads whose ``stage_sequence`` is strictly greater than the
    smallest ``stage_sequence`` found among the ``PLANNED`` loads."

    PRD §3.9: "The stages ``ANCHORAGE`` and ``TRIM_ACCESSORY`` map to no
    fabrication step, so this check is skipped entirely for loads at those
    stages."

    Design: Corner/calculations/erection_sequence_orders_by_stage_then_creation_time
    """
    chain = _order_with_four_planned_trucks()

    dispatched = dispatch_load(chain["anchorage_first"]["id"])

    assert dispatched["status"] == "DISPATCHED"
    projection = get_erection_sequence(chain["order"]["id"])
    assert_erection_sequence(
        projection,
        order_id=chain["order"]["id"],
        # The second anchor truck is still PLANNED at stage_sequence 1.
        sequence="ANCHORAGE>ANCHORAGE>PRIMARY_FRAME>SECONDARY_FRAME",
        next_dispatchable_stage="ANCHORAGE",
        planned_load_count=3,
        dispatched_load_count=1,
        blocked_load_count=2,
    )
    assert get_shipment_load(chain["anchorage_second"]["id"])["status"] == "PLANNED"
