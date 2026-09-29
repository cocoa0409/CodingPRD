"""Lifecycle-state conflicts: PRD §2.7 band 4 refusals on every state machine.

These tests address rows that exist and carry well-formed bodies, and are
refused solely because the row is in the wrong state. The undo-style edges are
grouped first because they share one shape — a repeat of an action that has
already landed is never a quiet success — then the two independent finished-unit
axes, the trailer machine, the cycle machine, the mould machine and the two
warranty axes.
"""

from test_helpers import (
    ApiErrorId,
    Q_CUBE,
    Q_MASS,
    Q_PERCENT,
    abort_payload,
    assert_decimal_equals,
    assert_instant_equals,
    assert_money_equals,
    cancel_order_payload,
    complete_service_payload,
    create_customer,
    create_plant_baseline,
    create_production_order,
    create_shipment,
    demold_payload,
    depart_payload,
    enter_cooling_payload,
    get_success_data,
    inspect_payload,
    load_unit,
    mark_down_payload,
    mold_payload,
    product_model_payload,
    release_storage_payload,
    remove_line_payload,
    retire_mold_payload,
    service_hold_payload,
    set_clock,
    setup_delivered_units,
    setup_scheduled_cycle,
    setup_stored_units,
    start_oven_payload,
    storage_review_payload,
    store_payload,
    suspend_payload,
    trim_payload,
    unseal_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    waive_storage_finding_payload,
    warranty_claim_payload,
)

CLOCK_START = "2026-08-01T00:00:00Z"


class TestUndoEdgesAreNeverIdempotent:
    """PRD §3.1 and §3.3 give five codes whose only job is refusing a repeat."""

    def test_restore_reinstate_and_cancel_refuse_the_repeat_without_moving_version(
        self, api, admin_headers, planner_headers
    ):
        """PRD §3.1: "Taking a station down that is already `DOWN` is
        `ERR_OVEN_STATION_DOWN` (HTTP 409); restoring a station that is already up
        is `ERR_OVEN_STATION_ALREADY_OPERATIONAL` (HTTP 409)." PRD §3.1: "A bay
        already down reports `ERR_COOLING_BAY_DOWN`, and restoring an operational
        bay reports `ERR_COOLING_BAY_ALREADY_OPERATIONAL`." PRD §3.1:
        "Reinstatement takes no body, requires `status` `SUSPENDED`, and otherwise
        reports `ERR_TECHNICIAN_ALREADY_ACTIVE` (HTTP 409)." PRD §3.1:
        "Reinstatement requires `status` `SUSPENDED`, otherwise
        `ERR_CUSTOMER_ALREADY_ACTIVE` (HTTP 409)." PRD §3.3: cancellation "is
        legal from `DRAFT`, `READY_TO_SCHEDULE`, `BLOCKED_RESIN`,
        `BLOCKED_WAREHOUSE` or `IN_PRODUCTION`; from `COMPLETE` or `CANCELLED` it
        is refused with `ERR_ORDER_ALREADY_TERMINAL` (HTTP 409)." PRD §2.4:
        `version` "increments by exactly 1 on every persisted mutation".

        Design: Corner/errors/err_409_no_op_family_restore_reinstate_and_cancel_are_never_idempotent
        """
        ctx = create_plant_baseline()
        customer = create_customer()
        order = create_production_order(ctx)
        cancelled = get_success_data(
            api.cancel_production_order(
                order["id"], cancel_order_payload("dealer withdrew the order"), planner_headers
            )
        )
        assert cancelled["status"] == "CANCELLED"

        station_id = ctx["oven_station_id"]
        res = api.restore_oven_station(station_id, admin_headers)
        validate_error(res, ApiErrorId.OVEN_STATION_ALREADY_OPERATIONAL)
        assert api.read_version("get_oven_station", station_id, admin_headers) == 1

        bay_id = ctx["cooling_bay_id"]
        res = api.restore_cooling_bay(bay_id, admin_headers)
        validate_error(res, ApiErrorId.COOLING_BAY_ALREADY_OPERATIONAL)
        assert api.read_version("get_cooling_bay", bay_id, admin_headers) == 1

        tech_id = ctx["resin_technician_id"]
        res = api.reinstate_technician(tech_id, admin_headers)
        validate_error(res, ApiErrorId.TECHNICIAN_ALREADY_ACTIVE)
        held = api.read_entity("get_technician", tech_id, admin_headers)
        assert held["status"] == "ACTIVE"
        assert held["version"] == 1

        # PRD.md §4: "POST `/customers/{customer_id}/reinstate` ... PlantAdmin".
        res = api.reinstate_customer(customer["customer_id"], admin_headers)
        validate_error(res, ApiErrorId.CUSTOMER_ALREADY_ACTIVE)
        assert api.read_version("get_customer", customer["customer_id"], planner_headers) == 1

        cancelled_version = cancelled["version"]
        res = api.cancel_production_order(
            order["id"], cancel_order_payload("dealer withdrew the order again"), planner_headers
        )
        validate_error(res, ApiErrorId.ORDER_ALREADY_TERMINAL)
        assert (
            api.read_version("get_production_order", order["id"], admin_headers)
            == cancelled_version
        )

        # The same restore that was refused above is admitted once the station is
        # genuinely down, and refused again immediately afterwards.
        down = get_success_data(
            api.mark_down_oven_station(
                station_id, mark_down_payload("thermocouple drift"), admin_headers
            )
        )
        assert down["status"] == "DOWN"
        assert down["version"] == 2
        up = get_success_data(api.restore_oven_station(station_id, admin_headers))
        assert up["status"] == "OPERATIONAL"
        assert up["version"] == 3
        res = api.restore_oven_station(station_id, admin_headers)
        validate_error(res, ApiErrorId.OVEN_STATION_ALREADY_OPERATIONAL)
        assert api.read_version("get_oven_station", station_id, admin_headers) == 3


class TestTheTwoFinishedUnitAxes:
    """One hull answers three different 409 codes depending on which axis blocks."""

    def test_build_axis_and_logistics_axis_refuse_with_their_own_codes(
        self, api, admin_headers, planner_headers
    ):
        """PRD §3.6: "Both operations additionally require `logistics_status`
        `UNALLOCATED`; a hull that has been stored, loaded, shipped or delivered
        can no longer be trimmed, outfitted, re-inspected or scrapped, and the
        attempt is refused with `ERR_UNIT_NOT_REINSPECTABLE` (HTTP 409)."
        PRD §3.7: "**Storing** a hull requires `build_status` `SELLABLE`
        (`ERR_UNIT_INVALID_BUILD_STATE`), `logistics_status` `UNALLOCATED`
        (`ERR_UNIT_INVALID_LOGISTICS_STATE`)". PRD §3.7: "**Releasing storage**
        requires `logistics_status` `STORED` and a `release_reason`", and its
        cascade means "the hull moves `STORED` to `UNALLOCATED`, its
        `warehouse_id`, `storage_zone_code`, `stored_at` and `demand_bucket_id`
        are cleared, its `stored_footprint_cube_m3` is set to 0.0000 and
        `is_zone_anchor` to false", while "the earliest surviving occupant of the
        same site-zone-model group ... is promoted: its `is_zone_anchor` becomes
        true and its `stored_footprint_cube_m3` is re-charged to the full
        `gross_cube_m3`". PRD §3.6: "Trimming is legal from `build_status`
        `DEMOLDED` or `REWORK` ... any other build state is
        `ERR_UNIT_INVALID_BUILD_STATE` (HTTP 409)."

        Design: Corner/errors/err_409_parallel_axis_family_build_state_versus_logistics_state_on_one_hull
        """
        ctx = setup_stored_units()
        anchor_id, follower_id = ctx["stored_unit_ids"]

        # SELLABLE is an inspectable build state, so only the logistics axis can
        # be refusing this re-inspection.
        res = api.inspect_finished_unit(anchor_id, inspect_payload(), ctx["inspector_headers"])
        validate_error(res, ApiErrorId.UNIT_NOT_REINSPECTABLE)

        warehouse_version_before = api.read_version(
            "get_warehouse", ctx["warehouse_id"], planner_headers
        )
        res = api.store_finished_unit(
            anchor_id, store_payload(warehouse_version_before), planner_headers
        )
        validate_error(res, ApiErrorId.UNIT_INVALID_LOGISTICS_STATE)
        assert (
            api.read_version("get_warehouse", ctx["warehouse_id"], planner_headers)
            == warehouse_version_before
        )

        released = get_success_data(
            api.release_storage(
                anchor_id,
                release_storage_payload("pulled for a dealer demo"),
                planner_headers,
            )
        )
        assert released["logistics_status"] == "UNALLOCATED"
        assert released["storage_zone_code"] is None
        assert released["is_zone_anchor"] is False
        assert_decimal_equals(
            released["stored_footprint_cube_m3"], "0.0000", Q_CUBE, "stored_footprint_cube_m3"
        )

        promoted = api.read_entity("get_finished_unit", follower_id, admin_headers)
        assert promoted["is_zone_anchor"] is True
        assert_decimal_equals(
            promoted["stored_footprint_cube_m3"], "2.0000", Q_CUBE, "stored_footprint_cube_m3"
        )
        site = api.read_entity("get_warehouse", ctx["warehouse_id"], planner_headers)
        assert_decimal_equals(site["committed_cube_m3"], "2.0000", Q_CUBE, "committed_cube_m3")
        assert_decimal_equals(site["utilization_pct"], "10.00", Q_PERCENT, "utilization_pct")
        assert site["posture"] == "NORMAL"

        res = api.release_storage(
            anchor_id, release_storage_payload("pulled again"), planner_headers
        )
        validate_error(res, ApiErrorId.UNIT_INVALID_LOGISTICS_STATE)

        # The very same hull is now UNALLOCATED, so the build axis is the only
        # thing left that can refuse a trim.
        res = api.trim_finished_unit(anchor_id, trim_payload(0.2), ctx["assembly_headers"])
        validate_error(res, ApiErrorId.UNIT_INVALID_BUILD_STATE)

        # And the inspection that was refused above now lands, proving the
        # earlier refusal came only from the logistics axis.
        reinspected = get_success_data(
            api.inspect_finished_unit(anchor_id, inspect_payload(), ctx["inspector_headers"])
        )
        assert reinspected["inspection_verdict"] == "PASS"
        assert reinspected["build_status"] == "SELLABLE"


class TestTrailerRefusals:
    """The trailer's four refusal codes, separated on one shipment."""

    def test_seal_depart_and_remove_each_refuse_from_their_own_precondition(
        self, api, planner_headers, admin_headers
    ):
        """PRD §3.8: "**Sealing** commits the load and prices it. The shipment
        must be `LOADING` (`ERR_SHIPMENT_INVALID_STATE`), it must carry at least
        one `LOADED` line (`ERR_SHIPMENT_EMPTY`, HTTP 409), its
        `cube_utilization_pct` must be at or above the minimum seal utilisation
        of 60.00 percent (`ERR_TRAILER_UNDERUTILIZED`, HTTP 409, with exactly
        60.00 passing)". PRD §3.8: "**Unsealing** carries an `unseal_reason` and
        is permitted only while `departed_at` is null; it returns the shipment
        from `SEALED` to `LOADING` and clears both `quoted_freight_cents` and
        `sealed_at` to null. **Departing** requires `SEALED` and a non-null
        `quoted_freight_cents`, otherwise `ERR_FREIGHT_QUOTE_MISSING`
        (HTTP 409)." PRD §3.8: "The line must be `LOADED`, otherwise
        `ERR_SHIPMENT_LINE_ALREADY_REMOVED` (HTTP 409)". PRD §3.8: "The first
        accepted line on a `PLANNED` shipment moves it to `LOADING`", and
        `cube_utilization_pct` is "`nested_cube_m3` divided by
        `trailer_cube_capacity_m3` times 100, rounded to two decimals".

        Design: Corner/errors/err_409_shipment_family_empty_underutilized_and_the_null_quote_near_miss
        """
        ctx = setup_stored_units()
        first_unit, second_unit = ctx["stored_units"]
        shipment = create_shipment(ctx)

        # PLANNED and empty at once: PRD §3.8 names a code for each of those two
        # preconditions in the same sentence, so either identifier honours it.
        res = api.seal_shipment(shipment["id"], planner_headers)
        validate_error_is_one_of(
            res, [ApiErrorId.SHIPMENT_INVALID_STATE, ApiErrorId.SHIPMENT_EMPTY]
        )
        assert api.read_entity("get_shipment", shipment["id"], planner_headers)["status"] == "PLANNED"

        load_unit(ctx, shipment, first_unit)
        loading = api.read_entity("get_shipment", shipment["id"], planner_headers)
        assert loading["status"] == "LOADING"
        assert_decimal_equals(loading["nested_cube_m3"], "2.0000", Q_CUBE, "nested_cube_m3")
        assert_decimal_equals(
            loading["cube_utilization_pct"], "40.00", Q_PERCENT, "cube_utilization_pct"
        )

        # LOADING with one line, so only the utilisation floor can refuse it.
        res = api.seal_shipment(shipment["id"], planner_headers)
        validate_error(res, ApiErrorId.TRAILER_UNDERUTILIZED)
        assert api.read_entity("get_shipment", shipment["id"], planner_headers)[
            "quoted_freight_cents"
        ] is None

        second_line = load_unit(ctx, shipment, second_unit)
        full = api.read_entity("get_shipment", shipment["id"], planner_headers)
        assert_decimal_equals(full["nested_cube_m3"], "3.0000", Q_CUBE, "nested_cube_m3")
        assert_decimal_equals(
            full["cube_utilization_pct"], "60.00", Q_PERCENT, "cube_utilization_pct"
        )

        # Exactly 60.00 passes.
        sealed = get_success_data(api.seal_shipment(shipment["id"], planner_headers))
        assert sealed["status"] == "SEALED"
        assert_instant_equals(sealed["sealed_at"], "2026-08-01T10:35:00Z", "sealed_at")
        first_quote = sealed["quoted_freight_cents"]
        assert isinstance(first_quote, int) and first_quote > 0

        unsealed = get_success_data(
            api.unseal_shipment(
                shipment["id"], unseal_payload("re-checking the hull count"), planner_headers
            )
        )
        assert unsealed["status"] == "LOADING"
        assert unsealed["quoted_freight_cents"] is None
        assert unsealed["sealed_at"] is None

        # The trailer now sits in exactly the state ERR_FREIGHT_QUOTE_MISSING
        # describes — quoted_freight_cents is null — but it is also no longer
        # SEALED, and PRD §3.8 attaches one code to both halves of that
        # requirement while PRD §3.8 gives the trailer machine its own code.
        res = api.depart_shipment(
            shipment["id"], depart_payload("2026-08-01T10:35:00Z"), planner_headers
        )
        validate_error_is_one_of(
            res, [ApiErrorId.SHIPMENT_INVALID_STATE, ApiErrorId.FREIGHT_QUOTE_MISSING]
        )

        removed = get_success_data(
            api.remove_shipment_line(
                second_line["id"],
                remove_line_payload("hull held back for a dealer demo"),
                planner_headers,
            )
        )
        assert removed["status"] == "REMOVED"
        assert api.read_entity("get_finished_unit", second_unit["id"], admin_headers)[
            "logistics_status"
        ] == "STORED"
        assert api.read_entity("get_shipment", shipment["id"], planner_headers)["status"] == "LOADING"

        res = api.remove_shipment_line(
            second_line["id"], remove_line_payload("removing it a second time"), planner_headers
        )
        validate_error(res, ApiErrorId.SHIPMENT_LINE_ALREADY_REMOVED)

        # One LOADED line survives, so the trailer is not empty — it is short of
        # the utilisation floor again.
        res = api.seal_shipment(shipment["id"], planner_headers)
        validate_error(res, ApiErrorId.TRAILER_UNDERUTILIZED)

        # Re-loading the same hull restores 60.00 percent, and the reseal
        # recomputes the identical quote, which is why no SEALED trailer can ever
        # carry a null quote.
        load_unit(ctx, shipment, second_unit)
        resealed = get_success_data(api.seal_shipment(shipment["id"], planner_headers))
        assert resealed["status"] == "SEALED"
        assert resealed["quoted_freight_cents"] == first_quote


class TestCycleLifecycleRefusals:
    """Out-of-order cycle edges, and the cooling floor asserted on the minute."""

    def test_out_of_order_edges_and_a_twenty_nine_minute_cool_are_both_refused(
        self, api, admin_headers
    ):
        """PRD §3.5: "A cycle addressed in the wrong state is refused with
        `ERR_CYCLE_INVALID_STATE` (HTTP 409): `SCHEDULED` is required to start the
        oven, `OVEN_RUNNING` to enter cooling, `COOLING` to demould, and
        `SCHEDULED`, `OVEN_RUNNING` or `COOLING` to abort." PRD §3.5: "Every
        `RESERVED` charge on the cycle becomes `CONSUMED`, moving `charge_kg` from
        its lot's `reserved_kg` to its lot's `consumed_kg` while `available_kg` is
        untouched". PRD §3.5: "**Demoulding** supplies `actual_cooling_end_at` and
        requires that the floored whole minutes elapsed since `actual_oven_end_at`
        reach the model's `min_cooling_minutes`, equality passing, otherwise
        `ERR_COOLING_TIME_INSUFFICIENT` (HTTP 422)." PRD §3.5: "One hull is then
        minted per cavity."

        Design: Corner/errors/err_cycle_lifecycle_invalid_state_and_the_cooling_time_floor
        """
        ctx = setup_scheduled_cycle()
        cycle_id = ctx["molding_cycle_id"]
        lot_id = ctx["resin_lot_id"]

        res = api.enter_cooling(
            cycle_id, enter_cooling_payload(CLOCK_START), ctx["operator_headers"]
        )
        validate_error(res, ApiErrorId.CYCLE_INVALID_STATE)
        assert api.read_entity("get_molding_cycle", cycle_id, admin_headers)["status"] == "SCHEDULED"

        res = api.demold(cycle_id, demold_payload(CLOCK_START), ctx["operator_headers"])
        validate_error(res, ApiErrorId.CYCLE_INVALID_STATE)
        assert (
            validate_paginated(
                api.list_finished_units({"molding_cycle_id": cycle_id}, admin_headers)
            )[1]["total_count"]
            == 0
        )

        set_clock("2026-08-01T09:00:00Z")
        running = get_success_data(
            api.start_oven(
                cycle_id,
                start_oven_payload("2026-08-01T09:00:00Z"),
                ctx["operator_headers"],
            )
        )
        assert running["status"] == "OVEN_RUNNING"
        assert (
            api.read_entity("get_resin_charge", ctx["resin_charge_id"], admin_headers)["status"]
            == "CONSUMED"
        )
        assert_decimal_equals(
            api.read_entity("get_resin_lot", lot_id, admin_headers)["consumed_kg"],
            "24.000",
            Q_MASS,
            "consumed_kg",
        )

        # A second start-oven must not consume the shot a second time.
        res = api.start_oven(
            cycle_id, start_oven_payload("2026-08-01T09:00:00Z"), ctx["operator_headers"]
        )
        validate_error(res, ApiErrorId.CYCLE_INVALID_STATE)
        assert_decimal_equals(
            api.read_entity("get_resin_lot", lot_id, admin_headers)["consumed_kg"],
            "24.000",
            Q_MASS,
            "consumed_kg",
        )

        set_clock("2026-08-01T10:00:00Z")
        cooling = get_success_data(
            api.enter_cooling(
                cycle_id,
                enter_cooling_payload("2026-08-01T10:00:00Z"),
                ctx["operator_headers"],
            )
        )
        assert cooling["status"] == "COOLING"

        # Twenty-nine floored minutes against min_cooling_minutes 30.
        set_clock("2026-08-01T10:29:00Z")
        res = api.demold(
            cycle_id, demold_payload("2026-08-01T10:29:00Z"), ctx["operator_headers"]
        )
        validate_error(res, ApiErrorId.COOLING_TIME_INSUFFICIENT)
        assert api.read_entity("get_molding_cycle", cycle_id, admin_headers)["status"] == "COOLING"

        # Exactly thirty passes.
        set_clock("2026-08-01T10:30:00Z")
        demolded = get_success_data(
            api.demold(
                cycle_id, demold_payload("2026-08-01T10:30:00Z"), ctx["operator_headers"]
            )
        )
        assert demolded["status"] == "DEMOLDED"
        assert demolded["actual_cooling_minutes"] == 30

        units, meta = validate_paginated(
            api.list_finished_units({"molding_cycle_id": cycle_id}, admin_headers)
        )
        assert meta["total_count"] == 2
        assert [unit["build_status"] for unit in units] == ["DEMOLDED", "DEMOLDED"]


class TestMoldLifecycleRefusals:
    """The mould's three refusals, separated by exactly what is wrong."""

    def test_service_retire_and_replacement_each_report_their_own_failure(
        self, api, admin_headers
    ):
        """PRD §3.1: "A hold attempted on a tool that is not `AVAILABLE` is
        `ERR_MOLD_NOT_AVAILABLE` (HTTP 409)." PRD §3.1: "Completing service
        requires `status` `MAINTENANCE`". PRD §3.1: "Retiring a tool requires a
        `retire_reason` and requires `status` to be `AVAILABLE` or `MAINTENANCE`;
        `RETIRED` is terminal and makes the tool a legal `replaces_mold_id`
        target. A retirement is refused with `ERR_MOLD_HAS_ACTIVE_CYCLES`
        (HTTP 409) when any cycle on that tool sits in `SCHEDULED`,
        `OVEN_RUNNING` or `COOLING`." PRD §3.1: `replaces_mold_id` "must resolve
        (`ERR_MOLD_NOT_FOUND`, HTTP 404), must name a *different* tool of the
        *same* `product_model_id`, and that tool's `status` must already be
        `RETIRED` — any of those three failing yields
        `ERR_INVALID_MOLD_REPLACEMENT` (HTTP 422)". PRD §3.5: "an abort returns it
        `IN_CYCLE` to `AVAILABLE` without wearing it."

        Design: Corner/errors/err_mold_lifecycle_family_not_available_active_cycles_and_bad_replacement
        """
        ctx = setup_scheduled_cycle()
        mold_id = ctx["mold_id"]

        # complete-service demands MAINTENANCE, and this tool is AVAILABLE.
        res = api.complete_service_mold(
            mold_id, complete_service_payload("nothing was serviced"), admin_headers
        )
        validate_error(res, ApiErrorId.MOLD_NOT_AVAILABLE)
        held = api.read_entity("get_mold", mold_id, admin_headers)
        assert held["status"] == "AVAILABLE"
        assert held["version"] == 1

        # The status itself was retireable, so the complaint is about the cycle.
        res = api.retire_mold(mold_id, retire_mold_payload("cavity crack"), admin_headers)
        validate_error(res, ApiErrorId.MOLD_HAS_ACTIVE_CYCLES)

        aborted = get_success_data(
            api.abort_molding_cycle(
                ctx["molding_cycle_id"], abort_payload("OPERATOR_ABORT"), ctx["operator_headers"]
            )
        )
        assert aborted["status"] == "ABORTED"
        assert api.read_entity("get_mold", mold_id, admin_headers)["status"] == "AVAILABLE"

        retired = get_success_data(
            api.retire_mold(mold_id, retire_mold_payload("cavity crack"), admin_headers)
        )
        assert retired["status"] == "RETIRED"

        res = api.service_hold_mold(
            mold_id, service_hold_payload("too late"), admin_headers
        )
        validate_error(res, ApiErrorId.MOLD_NOT_AVAILABLE)

        # A RETIRED tool of a *different* hull model is not a legal predecessor.
        other_model = get_success_data(
            api.create_product_model(
                product_model_payload(size_class="TANDEM", nominal_charge_kg=30.0),
                admin_headers,
            )
        )
        res = api.create_mold(
            mold_payload(
                other_model["id"],
                size_class="TANDEM",
                cavity_count=1,
                nominal_charge_kg=30.0,
                replaces_mold_id=mold_id,
            ),
            admin_headers,
        )
        validate_error(res, ApiErrorId.INVALID_MOLD_REPLACEMENT)

        # The same predecessor is legal for a different tool of its own model.
        successor = get_success_data(
            api.create_mold(
                mold_payload(ctx["product_model_id"], replaces_mold_id=mold_id),
                admin_headers,
            )
        )
        assert successor["replaces_mold_id"] == mold_id
        assert successor["status"] == "AVAILABLE"
        assert successor["cycles_since_service"] == 0

        chain, meta = validate_paginated(
            api.list_molds({"replaces_mold_id": mold_id}, admin_headers)
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in chain] == [successor["id"]]


class TestWarrantyIntakeAndStorageAxis:
    """PRD §3.9 separates the deformation threshold from the storage axis.

    PRD.md §3.9: "for `claim_type` `HULL_DEFORMATION` the
    `reported_deformation_mm` must be at or above the deformation threshold of
    3.00 millimetres, otherwise `ERR_DEFORMATION_BELOW_THRESHOLD` (HTTP 422);
    exactly 3.00 is accepted". PRD.md §3.9 also states that deciding the storage
    axis "must be `UNDER_REVIEW` (`ERR_CLAIM_INVALID_STATE`) and the storage
    axis must still be `NOT_STARTED`, otherwise `ERR_STORAGE_REVIEW_ALREADY_DONE`
    (HTTP 409)", that "An outcome of `VERIFIED` additionally requires that the
    customer's `storage_guidance_acknowledged_at` is not null **and** falls at or
    before the hull's `delivered_at`, otherwise
    `ERR_STORAGE_GUIDANCE_NOT_ACKNOWLEDGED` (HTTP 422)", and that a waiver's
    "axis must read `GUIDANCE_VIOLATED`, otherwise
    `ERR_STORAGE_FINDING_NOT_WAIVABLE` (HTTP 409)".
    """

    def test_the_three_millimetre_boundary_and_the_storage_axis_refusals(
        self, api, admin_headers, warranty_agent_headers
    ):
        """2.99 mm is refused, exactly 3.00 mm is claimable, and the storage axis
        refuses an unacknowledged VERIFIED, a repeat decision and a repeat waiver.

        PRD.md §3.9: "A deformation claim must be substantiated: for `claim_type`
        `HULL_DEFORMATION` the `reported_deformation_mm` must be at or above the
        deformation threshold of 3.00 millimetres, otherwise
        `ERR_DEFORMATION_BELOW_THRESHOLD` (HTTP 422); exactly 3.00 is accepted".
        PRD.md §3.9: "A new claim starts with `claim_status` `SUBMITTED`,
        `storage_review_status` `NOT_STARTED` ... and every money field ... and
        `denial_reason` null, with `version` 1."
        PRD.md §3.9: "Starting review moves `claim_status` `SUBMITTED` to
        `UNDER_REVIEW` ... It computes and freezes `months_in_service` as the
        number of complete calendar months from the hull's `delivered_at` to the
        logical clock, floored".
        PRD.md §3.9: "Deciding the storage axis never moves the adjudication axis
        — the claim stays `UNDER_REVIEW`".
        PRD.md §3.9: "`VERIFIED` sets the axis to `GUIDANCE_VERIFIED` ...
        `VIOLATED` sets it to `GUIDANCE_VIOLATED`. Either way the submitted
        `storage_description` is stored and only the claim's `version` advances."
        PRD.md §3.9: "Waiving a storage finding is reserved to `PlantAdmin` and
        carries a `waiver_note`. The axis must read `GUIDANCE_VIOLATED` ... The
        axis becomes `WAIVED`."
        PRD.md §3.2: "the suspension voids that customer's open warranty claims,
        moving every claim in `claim_status` `SUBMITTED` or `UNDER_REVIEW` to
        `VOIDED` with `denial_reason` `APPROVAL_VOIDED`. No money moves on those
        voids, because no payout had been booked."

        Design: Corner/errors/err_warranty_intake_and_storage_axis_family_with_the_3_00_mm_boundary
        """
        ctx = setup_delivered_units()
        model_id = ctx["product_model_id"]
        hull_id = ctx["delivered_unit_ids"][0]
        # A dealer who never read the storage guidance: the acknowledgement
        # timestamp the VERIFIED outcome needs stays null.
        account = create_customer()
        customer_id = account["customer_id"]
        assert account["customer"]["storage_guidance_acknowledged_at"] is None

        # 2.99 mm sits one hundredth below the threshold.
        validate_error(
            api.create_warranty_claim(
                warranty_claim_payload(
                    hull_id,
                    customer_id,
                    claim_code="CLM-CD-2",
                    claim_type="HULL_DEFORMATION",
                    reported_deformation_mm=2.99,
                ),
                warranty_agent_headers,
            ),
            ApiErrorId.DEFORMATION_BELOW_THRESHOLD,
        )
        _, meta = validate_paginated(api.list_warranty_claims({}, admin_headers))
        assert meta["total_count"] == 0, "the refused claim must not consume CLM-CD-2"

        # Exactly 3.00 mm is claimable, and the same code is still free.
        claim = get_success_data(
            api.create_warranty_claim(
                warranty_claim_payload(
                    hull_id,
                    customer_id,
                    claim_code="CLM-CD-2",
                    claim_type="HULL_DEFORMATION",
                    reported_deformation_mm=3.0,
                ),
                warranty_agent_headers,
            )
        )
        claim_id = claim["id"]
        assert claim["claim_code"] == "CLM-CD-2"
        assert claim["claim_status"] == "SUBMITTED"
        assert claim["storage_review_status"] == "NOT_STARTED"
        assert claim["payout_basis"] is None
        assert claim["pre_fee_gross_cents"] is None
        assert claim["storage_deduction_cents"] is None
        assert claim["admin_fee_cents"] is None
        assert claim["net_payout_cents"] is None
        assert claim["denial_reason"] is None
        assert claim["version"] == 1

        reviewed = get_success_data(
            api.start_claim_review(claim_id, warranty_agent_headers)
        )
        assert reviewed["claim_status"] == "UNDER_REVIEW"
        # The clock stands on the hull's own delivered_at, so no complete
        # calendar month has elapsed.
        assert reviewed["months_in_service"] == 0

        # VERIFIED needs an acknowledgement dated at or before delivery.
        validate_error(
            api.submit_storage_review(
                claim_id,
                storage_review_payload(
                    outcome="VERIFIED",
                    storage_description="stored on a cradle indoors",
                ),
                warranty_agent_headers,
            ),
            ApiErrorId.STORAGE_GUIDANCE_NOT_ACKNOWLEDGED,
        )
        held = api.read_entity("get_warranty_claim", claim_id, admin_headers)
        assert held["storage_review_status"] == "NOT_STARTED"
        assert held["claim_status"] == "UNDER_REVIEW"

        # VIOLATED carries no acknowledgement precondition at all.
        violated = get_success_data(
            api.submit_storage_review(
                claim_id,
                storage_review_payload(
                    outcome="VIOLATED",
                    storage_description="stored hull-down on gravel",
                ),
                warranty_agent_headers,
            )
        )
        assert violated["storage_review_status"] == "GUIDANCE_VIOLATED"
        assert violated["storage_description"] == "stored hull-down on gravel"
        # Deciding the storage axis leaves the adjudication axis alone.
        assert violated["claim_status"] == "UNDER_REVIEW"

        # The axis is decided once per pass through review.
        validate_error(
            api.submit_storage_review(
                claim_id,
                storage_review_payload(
                    outcome="VIOLATED",
                    storage_description="second look, same finding",
                ),
                warranty_agent_headers,
            ),
            ApiErrorId.STORAGE_REVIEW_ALREADY_DONE,
        )
        after_repeat = api.read_entity("get_warranty_claim", claim_id, admin_headers)
        assert after_repeat["storage_review_status"] == "GUIDANCE_VIOLATED"
        assert after_repeat["storage_description"] == "stored hull-down on gravel"

        waived = get_success_data(
            api.waive_storage_finding(
                claim_id,
                waive_storage_finding_payload(
                    waiver_note="dealer corrected the cradle"
                ),
                admin_headers,
            )
        )
        assert waived["storage_review_status"] == "WAIVED"
        assert waived["claim_status"] == "UNDER_REVIEW"

        # WAIVED is no longer GUIDANCE_VIOLATED, so the waiver cannot repeat.
        validate_error(
            api.waive_storage_finding(
                claim_id,
                waive_storage_finding_payload(waiver_note="waiving it twice"),
                admin_headers,
            ),
            ApiErrorId.STORAGE_FINDING_NOT_WAIVABLE,
        )

        # Suspending the dealer voids the open claim without touching money.
        suspended = get_success_data(
            api.suspend_customer(
                customer_id,
                suspend_payload("unpaid dealer account"),
                admin_headers,
            )
        )
        assert suspended["status"] == "SUSPENDED"
        voided = api.read_entity("get_warranty_claim", claim_id, admin_headers)
        assert voided["claim_status"] == "VOIDED"
        assert voided["denial_reason"] == "APPROVAL_VOIDED"
        model = api.read_entity("get_product_model", model_id, admin_headers)
        assert_money_equals(
            model["warranty_reserve_cents"], 500000, "warranty_reserve_cents"
        )
        assert_money_equals(model["warranty_paid_cents"], 0, "warranty_paid_cents")
