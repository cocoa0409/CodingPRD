"""Multi-rung rejection ladders and the capacity ceilings underneath them.

PRD.md §2.7 fixes one ascending priority order for every endpoint and returns on
the first failure it finds. These tests walk the endpoints that declare the most
independent rejections — scheduling a cycle, reserving a charge, loading a
trailer — and prove which rung answers when a single request breaks several at
once, including that the stale-version guards of §2.6 sit below every one of
them.
"""

from test_helpers import (
    ApiErrorId,
    Q_CUBE,
    Q_MASS,
    assert_decimal_equals,
    assert_instant_equals,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    get_success_data,
    mark_down_payload,
    mold_payload,
    molding_cycle_payload,
    oven_station_payload,
    production_order_version,
    quarantine_payload,
    release_charge_payload,
    release_quarantine_payload,
    remove_line_payload,
    resin_charge_payload,
    set_clock,
    setup_scheduled_cycle,
    setup_stored_units,
    shipment_line_payload,
    shipment_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    warehouse_payload,
    zone,
)

CLOCK_START = "2026-08-01T00:00:00Z"


class TestMoldingCycleCreateLadder:
    """PRD §3.4 spells the cycle-create order out rung by rung.

    PRD.md §3.4: "Checks run in the order of section 2.7 ... `arm_index` must be
    at least 1 and no greater than the station's `arm_count`. The acting
    technician must be `ACTIVE`. The station's `status` must be `OPERATIONAL`,
    otherwise `ERR_OVEN_STATION_DOWN`; the bay's `status` must be
    `OPERATIONAL`, otherwise `ERR_COOLING_BAY_DOWN` ... The requested
    `cooling_mode` must equal the bay's `airflow_mode`, otherwise
    `ERR_COOLING_MODE_MISMATCH` (HTTP 422) ... `oven_start_at` must be at or
    after the logical clock — equality passes — otherwise
    `ERR_OVEN_START_IN_PAST` (HTTP 422)".
    """

    def test_range_then_resource_state_then_safety_answer_in_that_order(
        self, api, admin_headers
    ):
        """One order collects five refusals, and none of them consumes its version.

        PRD.md §2.8: `arm_index` is "required integer, at least 1 and no greater
        than the station's `arm_count` or `ERR_VALIDATION`".
        PRD.md §3.4: "The station's `status` must be `OPERATIONAL`, otherwise
        `ERR_OVEN_STATION_DOWN`; the bay's `status` must be `OPERATIONAL`,
        otherwise `ERR_COOLING_BAY_DOWN`."
        PRD.md §3.4: "The requested `cooling_mode` must equal the bay's
        `airflow_mode`, otherwise `ERR_COOLING_MODE_MISMATCH` (HTTP 422)."
        PRD.md §3.4: "`oven_start_at` must be at or after the logical clock —
        equality passes — otherwise `ERR_OVEN_START_IN_PAST` (HTTP 422); cycles
        may not be back-dated."
        PRD.md §3.4: "`status` is `SCHEDULED` ... and the order moves
        `READY_TO_SCHEDULE` to `IN_PRODUCTION` on the first accepted cycle. The
        order's `version` advances by 1 in every case. A refused booking writes
        nothing at all — no cycle row, no order version bump."

        Design: Corner/errors/err_molding_cycle_create_rejection_ladder_range_then_resource_then_safety
        """
        set_clock(CLOCK_START)
        ctx = create_plant_baseline()
        create_resin_lot()
        order = create_production_order(ctx)
        order_id = order["id"]
        order_version = order["version"]
        assert order["status"] == "READY_TO_SCHEDULE"
        assert_instant_equals(
            api.read_current_utc(admin_headers), CLOCK_START, "current_utc"
        )
        station_id = ctx["oven_station_id"]
        bay_id = ctx["cooling_bay_id"]
        operator_headers = ctx["operator_headers"]
        assert ctx["oven_station"]["arm_count"] == 2

        def cycle_body(**overrides):
            return molding_cycle_payload(
                order_id, station_id, bay_id, order_version, **overrides
            )

        # Rung 3: arm 3 does not exist on a two-arm station.
        validate_error(
            api.create_molding_cycle(cycle_body(arm_index=3), operator_headers),
            ApiErrorId.VALIDATION,
        )

        # Rungs 5 before 6: the wrong cooling mode answers before the
        # back-dated oven start it also carries.
        validate_error(
            api.create_molding_cycle(
                cycle_body(
                    cooling_mode="AMBIENT", oven_start_at="2026-07-31T23:00:00Z"
                ),
                operator_headers,
            ),
            ApiErrorId.COOLING_MODE_MISMATCH,
        )

        # With the mode agreed, the same back-dated instant is the failure.
        validate_error(
            api.create_molding_cycle(
                cycle_body(oven_start_at="2026-07-31T23:00:00Z"), operator_headers
            ),
            ApiErrorId.OVEN_START_IN_PAST,
        )

        # Rung 4 before rung 5: a DOWN station outranks the wrong mode.
        get_success_data(
            api.mark_down_oven_station(
                station_id, mark_down_payload("burner service"), admin_headers
            )
        )
        validate_error(
            api.create_molding_cycle(
                cycle_body(cooling_mode="AMBIENT"), operator_headers
            ),
            ApiErrorId.OVEN_STATION_DOWN,
        )
        get_success_data(api.restore_oven_station(station_id, admin_headers))

        # The bay carries its own code on the same rung.
        get_success_data(
            api.mark_down_cooling_bay(
                bay_id, mark_down_payload("blower belt"), admin_headers
            )
        )
        validate_error(
            api.create_molding_cycle(cycle_body(), operator_headers),
            ApiErrorId.COOLING_BAY_DOWN,
        )
        get_success_data(api.restore_cooling_bay(bay_id, admin_headers))

        # Five refusals later the order is untouched and holds no cycle.
        refused_order = api.read_entity("get_production_order", order_id, admin_headers)
        assert refused_order["version"] == order_version
        assert refused_order["status"] == "READY_TO_SCHEDULE"
        _, meta = validate_paginated(
            api.list_molding_cycles({"production_order_id": order_id}, admin_headers)
        )
        assert meta["total_count"] == 0

        cycle = get_success_data(
            api.create_molding_cycle(cycle_body(), operator_headers)
        )
        assert cycle["status"] == "SCHEDULED"
        assert cycle["arm_index"] == 1
        accepted_order = api.read_entity(
            "get_production_order", order_id, admin_headers
        )
        assert accepted_order["status"] == "IN_PRODUCTION"
        assert accepted_order["version"] == order_version + 1


class TestResinLotStateBeforeTheVersionGuard:
    """PRD §2.6 puts the stale-version guards last, below the lot-state check.

    PRD.md §2.6: "These guards are evaluated late — after authorization, after
    existence, after schema, after every state and capacity rule the endpoint
    declares — so a request that is both stale and otherwise invalid reports the
    other failure, not the stale-version failure."
    """

    def test_the_same_stale_version_answers_409_while_quarantined_and_412_once_clear(
        self, api, admin_headers
    ):
        """One byte-identical charge body gets two different answers.

        PRD.md §3.2: "the lot's `status` must be `AVAILABLE`, otherwise
        `ERR_RESIN_LOT_NOT_AVAILABLE` (HTTP 409)".
        PRD.md §2.6: "Creating a resin charge requires
        `expected_resin_lot_version`, compared against the `version` of the
        `ResinLot` named by `resin_lot_id`. A mismatch yields
        `ERR_STALE_RESIN_LOT_VERSION`."
        PRD.md §3.2: quarantine is the head of CASCADE-F and "The lot's
        `version` advances by 1", while "Releasing a quarantine ... requires
        `status` `QUARANTINED`; the lot returns to `AVAILABLE` when
        `available_kg` is strictly greater than 0.000".
        PRD.md §3.3: "an order whose qualified-lot count has fallen to zero
        while `completed_qty` is still below `ordered_qty` moves to
        `BLOCKED_RESIN` with `blocked_reason` `NO_QUALIFIED_RESIN_LOT`; that is
        what the quarantine and expiry cascades trigger", and "An order in
        `BLOCKED_RESIN` for which a qualified lot has returned to `AVAILABLE`
        moves to `READY_TO_SCHEDULE` with `blocked_reason` cleared".
        PRD.md §3.2: "A refused charge writes nothing: no row, no mass movement,
        no version increment."
        PRD.md §3.2: "The charge's `status` must be `RESERVED`, otherwise
        `ERR_CHARGE_NOT_RELEASABLE` (HTTP 409)".

        Design: Corner/errors/err_412_occ_is_reached_only_after_the_resin_lot_state_precondition
        """
        set_clock(CLOCK_START)
        ctx = setup_scheduled_cycle(charge=False)
        lot_id = ctx["resin_lot_id"]
        cycle_id = ctx["molding_cycle_id"]
        order_id = ctx["production_order_id"]
        stale_lot_version = ctx["resin_lot"]["version"]
        assert stale_lot_version == 1
        assert ctx["resin_lot"]["status"] == "AVAILABLE"

        quarantined = get_success_data(
            api.quarantine_resin_lot(
                lot_id,
                quarantine_payload("melt index re-test pending"),
                ctx["inspector_headers"],
            )
        )
        assert quarantined["status"] == "QUARANTINED"
        assert quarantined["version"] == 2
        blocked_order = api.read_entity("get_production_order", order_id, admin_headers)
        assert blocked_order["status"] == "BLOCKED_RESIN"
        assert blocked_order["blocked_reason"] == "NO_QUALIFIED_RESIN_LOT"

        # The body is stale AND the lot is unusable: the state rung answers.
        charge_body = resin_charge_payload(cycle_id, lot_id, stale_lot_version)
        validate_error(
            api.create_resin_charge(charge_body, ctx["resin_tech_headers"]),
            ApiErrorId.RESIN_LOT_NOT_AVAILABLE,
        )

        cleared = get_success_data(
            api.release_resin_lot_quarantine(
                lot_id,
                release_quarantine_payload("melt index 4.00 confirmed"),
                ctx["inspector_headers"],
            )
        )
        assert cleared["status"] == "AVAILABLE"
        assert cleared["version"] == 3
        unblocked = api.read_entity("get_production_order", order_id, admin_headers)
        assert unblocked["blocked_reason"] is None
        assert unblocked["status"] == "READY_TO_SCHEDULE"

        # The identical body now reaches the bottom rung.
        validate_error(
            api.create_resin_charge(charge_body, ctx["resin_tech_headers"]),
            ApiErrorId.STALE_RESIN_LOT_VERSION,
        )
        after_412 = api.read_entity("get_resin_lot", lot_id, admin_headers)
        assert after_412["version"] == 3
        assert_decimal_equals(after_412["reserved_kg"], "0.000", Q_MASS, "reserved_kg")
        assert_decimal_equals(
            after_412["available_kg"], "500.000", Q_MASS, "available_kg"
        )

        # The refreshed version books the mass.
        fresh_version = api.read_version("get_resin_lot", lot_id, admin_headers)
        assert fresh_version == 3
        charge = get_success_data(
            api.create_resin_charge(
                resin_charge_payload(cycle_id, lot_id, fresh_version),
                ctx["resin_tech_headers"],
            )
        )
        assert charge["status"] == "RESERVED"
        reserved_lot = api.read_entity("get_resin_lot", lot_id, admin_headers)
        assert_decimal_equals(
            reserved_lot["available_kg"], "476.000", Q_MASS, "available_kg"
        )
        assert_decimal_equals(
            reserved_lot["reserved_kg"], "24.000", Q_MASS, "reserved_kg"
        )
        assert_decimal_equals(
            reserved_lot["consumed_kg"], "0.000", Q_MASS, "consumed_kg"
        )

        released = get_success_data(
            api.release_resin_charge(
                charge["id"],
                # PRD.md §3.2: "The optional `release_reason` supplies
                # `released_reason`", and §2.8 enumerates `released_reason`, so
                # the reason must be one of its members, not free text.
                release_charge_payload("ORDER_CANCELLED"),
                ctx["resin_tech_headers"],
            )
        )
        assert released["status"] == "RELEASED"
        returned_lot = api.read_entity("get_resin_lot", lot_id, admin_headers)
        assert_decimal_equals(
            returned_lot["available_kg"], "500.000", Q_MASS, "available_kg"
        )
        assert_decimal_equals(
            returned_lot["reserved_kg"], "0.000", Q_MASS, "reserved_kg"
        )

        # A RELEASED charge cannot be released again, and no mass is invented.
        validate_error(
            api.release_resin_charge(
                charge["id"],
                release_charge_payload("ORDER_CANCELLED"),
                ctx["resin_tech_headers"],
            ),
            ApiErrorId.CHARGE_NOT_RELEASABLE,
        )
        final_lot = api.read_entity("get_resin_lot", lot_id, admin_headers)
        assert_decimal_equals(
            final_lot["available_kg"], "500.000", Q_MASS, "available_kg"
        )


class TestTrailerCapacityCeilings:
    """PRD §3.8 gates a line on cube, then on payload, both after §2.7 band 6.

    PRD.md §3.8: "The candidate's nested contribution — full gross cube if it
    would take position 1 in its model group, nested cube otherwise — is added to
    `nested_cube_m3`, rounded to four decimals, and must be at or below
    `trailer_cube_capacity_m3`, otherwise `ERR_TRAILER_CUBE_EXCEEDED` (HTTP 409).
    The candidate's `unit_weight_kg` is added to `loaded_weight_kg`, rounded to
    three decimals, and must be at or below `trailer_max_payload_kg`, otherwise
    `ERR_TRAILER_PAYLOAD_EXCEEDED` (HTTP 409)."
    """

    def test_cube_payload_and_origin_each_refuse_with_the_ceiling_that_binds(
        self, api, admin_headers, planner_headers
    ):
        """Three trailers isolate the cube ceiling, the payload ceiling and origin
        agreement, and a refused line never consumes the shipment's version.

        PRD.md §3.8: "A line's `line_gross_cube_m3` is always the model's
        `gross_cube_m3` rounded to four decimals. Its `line_nested_cube_m3` is
        the full gross cube when its `nest_position` is 1, and `gross_cube_m3`
        multiplied by `nest_factor`, rounded to four decimals, for every position
        after the first."
        PRD.md §3.8: "the hull's `warehouse_id` must equal the shipment's
        `origin_warehouse_id`, otherwise `ERR_WAREHOUSE_MISMATCH` (HTTP 422) — a
        trailer cannot pick from two sites."
        PRD.md §3.8: "The candidate is tested **before** the row is written: a
        rejected line leaves no `ShipmentLine` behind, does not touch the hull,
        and does not advance the shipment's `version`, so a caller may retry with
        the same `expected_shipment_version`."
        PRD.md §3.8: "Removing the last `LOADED` line returns the shipment from
        `LOADING` to `PLANNED` and resets every rollup to its initial zero."

        Design: Corner/errors/err_capacity_family_trailer_cube_payload_site_mismatch_and_order_overbuild
        """
        set_clock(CLOCK_START)
        ctx = setup_stored_units()
        warehouse_id = ctx["warehouse_id"]
        hull_a, hull_b = ctx["stored_units"][0], ctx["stored_units"][1]

        # Trailer 1: 2.5000 cube is enough for one hull, not for the nested pair.
        tight_cube = get_success_data(
            api.create_shipment(
                shipment_payload(
                    warehouse_id,
                    destination_zone="Z1",
                    trailer_cube_capacity_m3=2.5,
                    trailer_max_payload_kg=30.0,
                ),
                planner_headers,
            )
        )
        first_line = get_success_data(
            api.create_shipment_line(
                shipment_line_payload(
                    tight_cube["id"], hull_a["id"], tight_cube["version"]
                ),
                planner_headers,
            )
        )
        assert first_line["nest_position"] == 1
        assert_decimal_equals(
            first_line["line_nested_cube_m3"], "2.0000", Q_CUBE, "line_nested_cube_m3"
        )
        loading = api.read_entity("get_shipment", tight_cube["id"], admin_headers)
        assert loading["status"] == "LOADING"
        assert_decimal_equals(
            loading["nested_cube_m3"], "2.0000", Q_CUBE, "nested_cube_m3"
        )
        assert_decimal_equals(
            loading["loaded_weight_kg"], "24.000", Q_MASS, "loaded_weight_kg"
        )

        # The pair would nest to 3.0000 — over the cube — and weigh 48.000 kg,
        # also over the payload. The cube ceiling is the one that answers.
        validate_error(
            api.create_shipment_line(
                shipment_line_payload(
                    tight_cube["id"], hull_b["id"], loading["version"]
                ),
                planner_headers,
            ),
            ApiErrorId.TRAILER_CUBE_EXCEEDED,
        )
        untouched_hull = api.read_entity("get_finished_unit", hull_b["id"], admin_headers)
        assert untouched_hull["logistics_status"] == "STORED"
        after_cube_refusal = api.read_entity(
            "get_shipment", tight_cube["id"], admin_headers
        )
        assert_decimal_equals(
            after_cube_refusal["nested_cube_m3"], "2.0000", Q_CUBE, "nested_cube_m3"
        )
        assert after_cube_refusal["version"] == loading["version"]

        removed = get_success_data(
            api.remove_shipment_line(
                first_line["id"], remove_line_payload("wrong trailer"), planner_headers
            )
        )
        assert removed["status"] == "REMOVED"
        emptied = api.read_entity("get_shipment", tight_cube["id"], admin_headers)
        assert emptied["status"] == "PLANNED"
        assert_decimal_equals(
            emptied["nested_cube_m3"], "0.0000", Q_CUBE, "nested_cube_m3"
        )
        assert (
            api.read_entity("get_finished_unit", hull_a["id"], admin_headers)[
                "logistics_status"
            ]
            == "STORED"
        )

        # Trailer 2: cube is ample at 10.0000, the payload ceiling is the binding
        # one at 30.000 kg against two 24.000 kg hulls.
        tight_payload = get_success_data(
            api.create_shipment(
                shipment_payload(
                    warehouse_id,
                    destination_zone="Z1",
                    trailer_cube_capacity_m3=10.0,
                    trailer_max_payload_kg=30.0,
                ),
                planner_headers,
            )
        )
        get_success_data(
            api.create_shipment_line(
                shipment_line_payload(
                    tight_payload["id"], hull_b["id"], tight_payload["version"]
                ),
                planner_headers,
            )
        )
        half_loaded = api.read_entity("get_shipment", tight_payload["id"], admin_headers)
        assert_decimal_equals(
            half_loaded["nested_cube_m3"], "2.0000", Q_CUBE, "nested_cube_m3"
        )
        assert_decimal_equals(
            half_loaded["loaded_weight_kg"], "24.000", Q_MASS, "loaded_weight_kg"
        )
        validate_error(
            api.create_shipment_line(
                shipment_line_payload(
                    tight_payload["id"], hull_a["id"], half_loaded["version"]
                ),
                planner_headers,
            ),
            ApiErrorId.TRAILER_PAYLOAD_EXCEEDED,
        )

        # Trailer 3 is booked out of a second site, so origin agreement — a §2.7
        # band 6 rule — answers before either capacity ceiling is consulted.
        other_site = get_success_data(
            api.create_warehouse(
                warehouse_payload(
                    footprint_capacity_cube_m3=30.0, zones=[zone("Z-B", 30.0)]
                ),
                admin_headers,
            )
        )
        other_trailer = get_success_data(
            api.create_shipment(
                shipment_payload(
                    other_site["id"],
                    destination_zone="Z1",
                    trailer_cube_capacity_m3=10.0,
                    trailer_max_payload_kg=100.0,
                ),
                planner_headers,
            )
        )
        validate_error(
            api.create_shipment_line(
                shipment_line_payload(
                    other_trailer["id"], hull_a["id"], other_trailer["version"]
                ),
                planner_headers,
            ),
            ApiErrorId.WAREHOUSE_MISMATCH,
        )
        assert (
            api.read_version("get_shipment", other_trailer["id"], planner_headers)
            == other_trailer["version"]
        )


class TestOrderStateAndTheOverbuildCeiling:
    """PRD §3.4 puts the order-state gate five bands above the build ceiling.

    PRD.md §3.4: "The order's `status` must be `READY_TO_SCHEDULE` or
    `IN_PRODUCTION`; a `DRAFT`, `BLOCKED_RESIN`, `BLOCKED_WAREHOUSE`, `COMPLETE`
    or `CANCELLED` order cannot take a new cycle and is refused with
    `ERR_ORDER_NOT_SCHEDULABLE` (HTTP 409) ... Then the oven arm window, then the
    bay slot count, then the mould pool, then the overbuild ceiling".
    """

    def test_a_draft_order_reports_its_state_not_the_ceiling_it_also_breaches(
        self, api, admin_headers
    ):
        """An unreleased one-hull order refuses on state; released, it then refuses
        the second cycle on the ceiling of floor(1 x 1.20) = 1.

        PRD.md §3.4: "an **overbuild ceiling** protects the order from unbounded
        scheduling: the number of scheduled plus completed hulls for an order may
        not exceed `ordered_qty` multiplied by 1.20 and floored to an integer. A
        cycle that would breach it is refused with `ERR_ORDER_OVERBUILD` (HTTP
        409)."
        PRD.md §3.4: "When the request carries `exclude_mold_ids`, those tools are
        removed **after** the eligibility filter and **before** ranking ...
        Ranking is total and deterministic: ascending `cycles_since_service`, then
        ascending `mold_code`."
        PRD.md §3.4: "A refused booking writes nothing at all — no cycle row, no
        order version bump."

        Design: Corner/errors/err_capacity_family_trailer_cube_payload_site_mismatch_and_order_overbuild
        """
        set_clock(CLOCK_START)
        ctx = create_plant_baseline(mold_overrides={"mold_code": "MLD-ZZ-TWIN"})
        create_resin_lot()
        twin_cavity_id = ctx["mold_id"]
        assert ctx["mold"]["cavity_count"] == 2
        # A single-cavity tool that always ranks first: same wear, lower code.
        solo = get_success_data(
            api.create_mold(
                mold_payload(
                    ctx["product_model_id"],
                    mold_code="MLD-AA-SOLO",
                    cavity_count=1,
                    nominal_charge_kg=12.0,
                ),
                admin_headers,
            )
        )
        assert solo["cycles_since_service"] == 0

        order = create_production_order(ctx, release=False, ordered_qty=1)
        order_id = order["id"]
        assert order["status"] == "DRAFT"

        # Excluding the solo tool leaves only the two-cavity tool, so this body
        # would also mint two hulls against a ceiling of one. State answers.
        validate_error(
            api.create_molding_cycle(
                molding_cycle_payload(
                    order_id,
                    ctx["oven_station_id"],
                    ctx["cooling_bay_id"],
                    order["version"],
                    exclude_mold_ids=[solo["id"]],
                ),
                ctx["operator_headers"],
            ),
            ApiErrorId.ORDER_NOT_SCHEDULABLE,
        )

        released = get_success_data(api.release_production_order(order_id, admin_headers))
        assert released["status"] == "READY_TO_SCHEDULE"
        first_cycle = get_success_data(
            api.create_molding_cycle(
                molding_cycle_payload(
                    order_id,
                    ctx["oven_station_id"],
                    ctx["cooling_bay_id"],
                    released["version"],
                ),
                ctx["operator_headers"],
            )
        )
        # Ranking is by wear then code, so the one-cavity tool is chosen.
        assert first_cycle["mold_id"] == solo["id"]
        assert first_cycle["mold_id"] != twin_cavity_id

        # One scheduled hull already fills floor(1 * 1.20) = 1.
        version_before = production_order_version(order_id)
        validate_error(
            api.create_molding_cycle(
                molding_cycle_payload(
                    order_id,
                    ctx["oven_station_id"],
                    ctx["cooling_bay_id"],
                    version_before,
                    oven_start_at="2026-08-01T15:00:00Z",
                ),
                ctx["operator_headers"],
            ),
            ApiErrorId.ORDER_OVERBUILD,
        )
        assert production_order_version(order_id) == version_before
        _, meta = validate_paginated(
            api.list_molding_cycles({"production_order_id": order_id}, admin_headers)
        )
        assert meta["total_count"] == 1


class TestSizeClassFailsInTwoPlaces:
    """PRD §2.8 guards registration; PRD §3.4 makes the station ceiling an
    eligibility clause whose empty pool owns the refusal.

    PRD.md §2.8: a mould's `size_class` "must equal the referenced model's
    `size_class` or `ERR_MOLD_SIZE_CLASS_MISMATCH`".
    PRD.md §3.4: the candidate pool is "every tool whose `product_model_id`
    equals the order's, whose `status` is exactly `AVAILABLE` ... whose
    `size_class` rank is at most the station's `max_size_class` rank", and "When
    the pool is empty the two failure modes are kept distinct: if at least one
    tool for this hull model is in `status` `AVAILABLE` but every such tool was
    removed by the occupancy clause, the request fails with
    `ERR_MOLD_WINDOW_CONFLICT` (HTTP 409); otherwise — no available tool at all,
    or an `exclude_mold_ids` list that emptied the pool — it fails with
    `ERR_NO_ELIGIBLE_MOLD` (HTTP 409)."
    """

    def test_registration_mismatch_and_the_station_ceiling_use_different_codes(
        self, api, admin_headers
    ):
        """A TANDEM tool for a MID model is refused at registration, while a
        COMPACT station empties the candidate pool instead.

        PRD.md §2.8: `size_class` is "required, one of the four classes, and must
        equal the referenced model's `size_class` or
        `ERR_MOLD_SIZE_CLASS_MISMATCH`".
        PRD.md §2.8: `max_size_class` names classes "which are ordered `COMPACT`
        below `MID` below `TANDEM` below `OVERSIZE`".
        PRD.md §3.4: the pool keeps only tools "whose `size_class` rank is at most
        the station's `max_size_class` rank", and an otherwise-empty pool "fails
        with `ERR_NO_ELIGIBLE_MOLD` (HTTP 409)".
        PRD.md §3.4: "The first ranked candidate is written to `mold_id` and
        returned in the response so the choice is observable."
        PRD.md §3.4: "A refused booking writes nothing at all — no cycle row, no
        order version bump."

        Design: Corner/errors/err_size_class_family_registration_mismatch_and_the_station_ceiling_near_miss
        """
        set_clock(CLOCK_START)
        ctx = create_plant_baseline()
        create_resin_lot()
        model_id = ctx["product_model_id"]
        assert ctx["product_model"]["size_class"] == "MID"
        assert ctx["oven_station"]["max_size_class"] == "OVERSIZE"

        validate_error(
            api.create_mold(
                mold_payload(model_id, size_class="TANDEM"), admin_headers
            ),
            ApiErrorId.MOLD_SIZE_CLASS_MISMATCH,
        )
        _, meta = validate_paginated(
            api.list_molds({"product_model_id": model_id}, admin_headers)
        )
        assert meta["total_count"] == 1, "the refused registration wrote no tool"

        compact_station = get_success_data(
            api.create_oven_station(
                oven_station_payload(arm_count=1, max_size_class="COMPACT"),
                admin_headers,
            )
        )
        assert compact_station["max_size_class"] == "COMPACT"

        order = create_production_order(ctx)
        order_id = order["id"]
        order_version = order["version"]
        # MID outranks COMPACT, so the booking is refused on capability. PRD.md
        # §3.4 names two codes for this one condition and never reconciles them:
        # the ladder sentence says "The selected tool's `size_class` must fit the
        # station ... otherwise `ERR_SIZE_CLASS_NOT_SUPPORTED` (HTTP 422)" and
        # places that rung *above* the mould pool, while the pool sentence folds
        # the same predicate into eligibility — "whose `size_class` rank is at
        # most the station's `max_size_class` rank" — which empties the pool and
        # "fails with `ERR_NO_ELIGIBLE_MOLD` (HTTP 409)". Either code is a
        # faithful reading, so only the refusal itself is asserted.
        validate_error_is_one_of(
            api.create_molding_cycle(
                molding_cycle_payload(
                    order_id,
                    compact_station["id"],
                    ctx["cooling_bay_id"],
                    order_version,
                ),
                ctx["operator_headers"],
            ),
            [ApiErrorId.NO_ELIGIBLE_MOLD, ApiErrorId.SIZE_CLASS_NOT_SUPPORTED],
        )
        refused = api.read_entity("get_production_order", order_id, admin_headers)
        assert refused["version"] == order_version
        assert refused["status"] == "READY_TO_SCHEDULE"

        # The identical body on the OVERSIZE station is accepted.
        accepted = get_success_data(
            api.create_molding_cycle(
                molding_cycle_payload(
                    order_id,
                    ctx["oven_station_id"],
                    ctx["cooling_bay_id"],
                    order_version,
                ),
                ctx["operator_headers"],
            )
        )
        assert accepted["mold_id"] == ctx["mold_id"]
        assert accepted["status"] == "SCHEDULED"
