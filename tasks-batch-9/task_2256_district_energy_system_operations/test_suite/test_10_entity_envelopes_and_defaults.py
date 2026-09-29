"""Stored shapes: envelopes, declared defaults, immutability and parent links."""

from test_helpers import (
    ApiErrorId,
    BILLING_ANALYST,
    DISPATCH_OPERATOR,
    FIELD_TECHNICIAN,
    NETWORK_ENGINEER,
    NON_EXISTENT_UUID,
    SYSTEM_CONTROLLER,
    add_reading,
    api_client,
    assert_append_only_record,
    assert_common_fields,
    assert_energy,
    assert_loop_state,
    assert_pagination_meta,
    assert_read_at_ascending,
    assert_segment_condition,
    campus_dispatch_stack,
    commercial_rate_schedule,
    commissioned_point,
    create_agreement,
    create_asset,
    create_loop,
    create_rate_schedule,
    create_segment,
    get_success_data,
    network_loop_payload,
    pipe_segment_payload,
    plan_orders,
    production_asset_payload,
    rate_schedule_payload,
    read_asset,
    read_loop,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    work_order_payload,
)


def _read_segment(segment_id):
    return get_success_data(api_client.get_pipe_segment(segment_id, NETWORK_ENGINEER))


def _read_point(point_id):
    return get_success_data(api_client.get_metering_point(point_id, FIELD_TECHNICIAN))


class TestStoredEnvelopes:
    """What a create returns and what a subsequent read gives back."""

    def test_loop_registration_returns_every_declared_field(self):
        """A freshly registered loop reports its posture and all three counters.

        PRD: "The new loop opens at `posture` `NORMAL`, with
        `committed_reserved_kw` of 0.0, `open_isolation_count` of 0 and
        `suspect_segment_count` of 0."

        Design: Corner/Entities/network_loop_creation_returns_every_declared_field_in_the_envelope
        """
        set_clock()

        response = api_client.create_network_loop(
            network_loop_payload(
                code="LOOP-Z1",
                name="Zone One Distribution Loop",
                service_mode="DUAL",
                design_supply_temp_c=95.0,
                max_pressure_kpa=1600.0,
                rated_capacity_kw=9000.0,
            ),
            SYSTEM_CONTROLLER,
        )

        loop = validate_success(response, expected_status=201)
        assert loop["code"] == "LOOP-Z1"
        assert loop["service_mode"] == "DUAL"
        assert loop["rated_capacity_kw"] == 9000.0
        assert_loop_state(
            loop,
            posture="NORMAL",
            committed_reserved_kw=0.0,
            open_isolation_count=0,
            suspect_segment_count=0,
            version=1,
        )
        assert_common_fields(loop, expected_version=1)
        assert loop["created_at"].startswith("2026-08-01T00:00:00")

    def test_a_thermal_store_reads_back_with_its_charge_untouched(self):
        """The stored row is returned as written, with no derived rewriting.

        PRD: "`storage_capacity_kwh`, defaulting to 0.0, is the usable stored
        thermal energy and is zero for every non-storage asset.
        `state_of_charge_kwh`, defaulting to 0.0, is the stored energy currently
        available for discharge".

        Design: Corner/Entities/production_asset_retrieval_returns_the_stored_row_unchanged
        """
        set_clock()
        loop = create_loop(code="LOOP-Z1", rated_capacity_kw=9000.0)
        stored = create_asset(
            loop["id"],
            code="Z_STO",
            asset_type="THERMAL_STORAGE",
            rated_capacity_kw=1500.0,
            marginal_cost_per_mwh=6.00,
            emission_factor_kg_per_mwh=0.0,
            storage_capacity_kwh=4000.0,
            state_of_charge_kwh=3500.0,
        )

        fetched = read_asset(stored["id"])

        assert fetched["id"] == stored["id"]
        assert fetched["asset_type"] == "THERMAL_STORAGE"
        assert fetched["rated_capacity_kw"] == 1500.0
        assert fetched["storage_capacity_kwh"] == 4000.0
        assert fetched["state_of_charge_kwh"] == 3500.0
        assert fetched["availability_state"] == "AVAILABLE"
        assert_common_fields(fetched, expected_version=1)

    def test_the_segment_listing_windows_three_rows_two_at_a_time(self):
        """A limit of two over three segments leaves one row beyond the window.

        PRD: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope, where `total_count` is
        the size of the filtered result set before the window is applied and
        `has_more` indicates whether items remain beyond the window."

        Design: Corner/Entities/pipe_segment_listing_paginates_with_total_count_and_has_more
        """
        set_clock()
        loop = create_loop(code="LOOP-Z1", rated_capacity_kw=9000.0)
        create_segment(loop["id"], code="SEG-Z1")
        create_segment(loop["id"], code="SEG-Z2")
        third = create_segment(loop["id"], code="SEG-Z3")

        first_page, first_meta = validate_paginated(
            api_client.list_pipe_segments(
                NETWORK_ENGINEER, {"loop_id": loop["id"], "limit": 2, "offset": 0}
            )
        )
        second_page, second_meta = validate_paginated(
            api_client.list_pipe_segments(
                NETWORK_ENGINEER, {"loop_id": loop["id"], "limit": 2, "offset": 2}
            )
        )

        assert len(first_page) == 2, f"expected two rows, got {len(first_page)}"
        assert_pagination_meta(
            first_meta, total_count=3, has_more=True, limit=2, offset=0
        )
        assert len(second_page) == 1, f"expected one row, got {len(second_page)}"
        assert second_page[0]["id"] == third["id"]
        assert_pagination_meta(
            second_meta, total_count=3, has_more=False, limit=2, offset=2
        )

    def test_system_fields_come_from_the_server_and_the_logical_clock(self):
        """The id is a server-minted UUID and both stamps read off the clock.

        PRD: "Every resource the API persists carries an `id`: a server-minted
        UUID, with no type prefix and no client control over its value."

        Design: Corner/Entities/system_fields_are_server_generated_and_client_values_are_ignored
        """
        set_clock("2026-05-05T00:00:00Z")

        loop = create_loop(code="LOOP-Z5", rated_capacity_kw=9000.0)

        assert_common_fields(loop, expected_version=1)
        assert loop["id"] != "LOOP-Z5"
        assert loop["created_at"].startswith("2026-05-05T00:00:00")
        assert loop["updated_at"].startswith("2026-05-05T00:00:00")


class TestDeclaredDefaults:
    """Every optional input that the specification gives a default value."""

    def test_omitted_segment_inputs_take_their_declared_defaults(self):
        """A segment opens sound and unscored with a null upstream link.

        PRD: "A newly registered segment always opens at `condition` `SOUND` with a
        `leak_risk_score` of 0.0, whatever its inputs suggest; the score is only
        ever populated by an assessment or by a repair sign-off."

        Design: Corner/Entities/optional_inputs_and_computed_counters_take_their_declared_defaults
        """
        set_clock()
        loop = create_loop(code="LOOP-Z1", rated_capacity_kw=9000.0)

        segment = create_segment(loop["id"], code="SEG-Z1")

        assert_segment_condition(
            segment,
            condition="SOUND",
            leak_risk_score=0.0,
            makeup_water_ratio=0.0,
            historical_leak_count=0,
        )
        assert segment["upstream_segment_id"] is None

    def test_a_tariff_defaults_its_ratchet_lookback_to_eleven_months(self):
        """The demand-ratchet window is filled in when the client omits it.

        PRD: "It also declares a `ratchet_lookback_months`, the number of months of
        prior invoices that feed the demand ratchet, which defaults to 11 when
        omitted."

        Design: Corner/Entities/optional_inputs_and_computed_counters_take_their_declared_defaults
        """
        set_clock()

        tariff = create_rate_schedule("COMMERCIAL_OFFICE", code="RS-Z1")

        assert tariff["ratchet_lookback_months"] == 11

    def test_a_new_agreement_and_meter_open_with_empty_ledgers(self):
        """Both counters and both ledgers start at zero on a fresh customer.

        PRD: "A new agreement opens with `contract_state` `PENDING_CAPACITY`,
        `billing_state` `CURRENT`, `billed_demand_ratchet_kw` 0.0 and `balance_due`
        0.0."

        Design: Corner/Entities/optional_inputs_and_computed_counters_take_their_declared_defaults
        """
        set_clock()
        loop = create_loop(code="LOOP-Z1", rated_capacity_kw=9000.0)
        segment = create_segment(loop["id"], code="SEG-Z1")
        tariff = commercial_rate_schedule(code="RS-Z1")

        agreement = create_agreement(loop["id"], tariff["id"], customer_name="Zone One Tower")
        point = get_success_data(
            api_client.create_metering_point(
                {
                    "agreement_id": agreement["id"],
                    "segment_id": segment["id"],
                    "code": "MP-Z1",
                },
                FIELD_TECHNICIAN,
            )
        )

        assert agreement["contract_state"] == "PENDING_CAPACITY"
        assert agreement["billing_state"] == "CURRENT"
        assert agreement["billed_demand_ratchet_kw"] == 0.0
        assert agreement["balance_due"] == 0.0
        assert point["meter_state"] == "INSTALLED"
        assert point["multiplier"] == 1.0
        assert point["last_reading_energy_mwh"] == 0.0
        assert point["reading_count"] == 0

    def test_the_stored_read_multiplies_the_register_by_the_point_multiplier(self):
        """A 2.5 multiplier turns a 1000.000 MWh register into 2500.000 MWh.

        PRD: "Each stored reading also carries `multiplied_energy_mwh`, its
        `cumulative_energy_mwh` multiplied by the owning point's `multiplier` and
        rounded half-up to three decimal places."

        Design: Corner/Entities/meter_reading_multiplied_energy_is_computed_from_the_point_multiplier
        """
        set_clock()
        loop = create_loop(code="LOOP-Z1", rated_capacity_kw=9000.0)
        segment = create_segment(loop["id"], code="SEG-Z1")
        tariff = commercial_rate_schedule(code="RS-Z1")
        agreement = create_agreement(loop["id"], tariff["id"], customer_name="Zone One Tower")
        point = commissioned_point(
            agreement["id"], segment["id"], code="MP-Z2", multiplier=2.5
        )

        reading = add_reading(point["id"], "2026-08-02T00:00:00Z", 1000.000, 400.0)

        assert_energy(reading["multiplied_energy_mwh"], 2500.000)
        refreshed = _read_point(point["id"])
        assert_energy(refreshed["last_reading_energy_mwh"], 1000.000)
        assert refreshed["reading_count"] == 1


class TestRejectedShapes:
    """Malformed or unresolvable creates, and the reads that prove nothing landed."""

    def test_reading_an_unknown_plan_id_reports_plan_not_found(self):
        """A well-formed but unregistered path identifier is a 404, not a 400.

        PRD: "Each path identifier resolves, or the corresponding 404:
        `ERR_LOOP_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`,
        `ERR_FUEL_CONTRACT_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
        `ERR_FORECAST_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`".

        Design: Corner/Entities/dispatch_plan_get_with_unknown_id_returns_plan_not_found
        """
        set_clock()

        response = api_client.get_dispatch_plan(NON_EXISTENT_UUID, DISPATCH_OPERATOR)

        body = validate_error(response, ApiErrorId.PLAN_NOT_FOUND)
        assert body["error_id"] == ApiErrorId.PLAN_NOT_FOUND

    def test_a_tariff_without_a_tier_ladder_is_rejected(self):
        """An omitted and an empty tier array are both malformed ladders.

        PRD: "Finally it declares `tiers`, an ordered array of at least one object,
        each holding a `load_factor_max` and an `energy_rate_per_mwh`, stored and
        walked in `load_factor_max` ascending order."

        Design: Corner/Entities/rate_schedule_creation_without_tiers_is_rejected_as_invalid_request
        """
        set_clock()
        without_tiers = rate_schedule_payload(code="RS-Z1")
        without_tiers.pop("tiers")

        omitted = api_client.create_rate_schedule(without_tiers, BILLING_ANALYST)
        empty = api_client.create_rate_schedule(
            rate_schedule_payload(code="RS-Z2", tiers=[]), BILLING_ANALYST
        )

        validate_error(omitted, ApiErrorId.INVALID_REQUEST)
        validate_error(empty, ApiErrorId.INVALID_REQUEST)
        _, meta = validate_paginated(api_client.list_rate_schedules(BILLING_ANALYST))
        assert_pagination_meta(meta, total_count=0)

    def test_a_non_increasing_tier_ladder_is_rejected(self):
        """Ceilings that fail to rise cannot be walked in ascending order.

        PRD: "The ceilings must be strictly increasing, and the final entry is the
        fallback tier that catches any load factor above every declared ceiling."

        Design: Corner/Entities/rate_schedule_creation_without_tiers_is_rejected_as_invalid_request
        """
        set_clock()

        response = api_client.create_rate_schedule(
            rate_schedule_payload(
                code="RS-Z3",
                tiers=[
                    {"load_factor_max": 60.0, "energy_rate_per_mwh": 88.00},
                    {"load_factor_max": 60.0, "energy_rate_per_mwh": 74.00},
                ],
            ),
            BILLING_ANALYST,
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST)

    def test_an_unknown_asset_type_is_rejected_as_an_invalid_request(self):
        """A heat pump is not one of the five declared machine types.

        PRD: "It supplies the `loop_id` the asset injects into, a `code` unique
        within that loop, an `asset_type` of `BOILER`, `CHILLER`, `CHP`,
        `BIOMASS_BOILER` or `THERMAL_STORAGE`".

        Design: Corner/Entities/production_asset_rejects_an_unknown_asset_type_enum_member
        """
        set_clock()
        loop = create_loop(code="LOOP-Z1", rated_capacity_kw=9000.0)

        response = api_client.create_production_asset(
            production_asset_payload(loop["id"], code="Z_HP", asset_type="HEAT_PUMP"),
            SYSTEM_CONTROLLER,
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST)
        _, meta = validate_paginated(
            api_client.list_production_assets(DISPATCH_OPERATOR, {"loop_id": loop["id"]})
        )
        assert_pagination_meta(meta, total_count=0)

    def test_a_work_order_window_that_runs_backwards_is_rejected(self):
        """The schema check requires the close of the dig to follow its opening.

        PRD: "Required body and query fields present, enum members recognised,
        numbers inside their declared ranges, `limit` within 1 to 100 and `offset`
        at least 0, `window_end` later than `window_start`".

        Design: Corner/Entities/production_asset_rejects_an_unknown_asset_type_enum_member
        """
        set_clock()
        loop = create_loop(code="LOOP-Z1", rated_capacity_kw=9000.0)
        segment = create_segment(loop["id"], code="SEG-Z1")

        response = api_client.create_work_order(
            work_order_payload(
                segment["id"],
                loop["id"],
                "2026-09-02T08:00:00Z",
                "2026-09-01T16:00:00Z",
            ),
            FIELD_TECHNICIAN,
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST)

    def test_a_segment_naming_an_unregistered_loop_is_refused(self):
        """The parent link is resolved before the segment is written.

        PRD: "Every foreign key supplied in the request body resolves to an
        existing row, evaluated in body-field declaration order — `loop_id`, then
        `upstream_segment_id`, then `fuel_contract_id`, then `forecast_id`, then
        `rate_schedule_id`, then `agreement_id`, then `segment_id` — with the first
        unresolved reference yielding `ERR_FK_NOT_FOUND` (404)."

        Design: Corner/Entities/pipe_segment_requires_an_existing_parent_loop
        """
        set_clock()

        response = api_client.create_pipe_segment(
            pipe_segment_payload(NON_EXISTENT_UUID, code="SEG-Z9"), NETWORK_ENGINEER
        )

        validate_error(response, ApiErrorId.FK_NOT_FOUND)
        _, meta = validate_paginated(api_client.list_pipe_segments(NETWORK_ENGINEER))
        assert_pagination_meta(meta, total_count=0)


class TestHydraulicChainAndLedgerRows:
    """The upstream chain, and the two resources nothing ever mutates."""

    def test_an_upstream_link_on_another_loop_is_refused(self):
        """A chain that wanders off the loop is rejected exactly like a cycle.

        PRD: "When a value is supplied it must belong to the same loop, and
        following the chain of upstream links from the new segment must terminate at
        a segment whose upstream link is null without ever revisiting a segment
        already seen on the walk. A chain that closes on itself or wanders off the
        loop is rejected with `ERR_SEGMENT_CYCLE`."

        Design: Corner/Entities/upstream_segment_chain_rejects_a_cycle_and_a_cross_loop_link
        """
        set_clock()
        first_loop = create_loop(code="LOOP-Z1", rated_capacity_kw=9000.0)
        other_loop = create_loop(code="LOOP-Z2", rated_capacity_kw=9000.0)
        foreign_header = create_segment(other_loop["id"], code="SEG-Y1")

        response = api_client.create_pipe_segment(
            pipe_segment_payload(
                first_loop["id"], code="SEG-Z2", upstream_segment_id=foreign_header["id"]
            ),
            NETWORK_ENGINEER,
        )

        validate_error(response, ApiErrorId.SEGMENT_CYCLE)

    def test_a_two_hop_chain_within_one_loop_is_accepted(self):
        """A walk that terminates at a null upstream link is a valid chain.

        PRD: "Each carries an `upstream_segment_id` naming the segment immediately
        upstream of it, which is null for the plant header segment and defaults to
        null when omitted."

        Design: Corner/Entities/upstream_segment_chain_rejects_a_cycle_and_a_cross_loop_link
        """
        set_clock()
        loop = create_loop(code="LOOP-Z1", rated_capacity_kw=9000.0)
        header = create_segment(loop["id"], code="SEG-Z1")

        branch = create_segment(
            loop["id"], code="SEG-Z2", upstream_segment_id=header["id"]
        )

        assert branch["upstream_segment_id"] == header["id"]
        assert _read_segment(branch["id"])["upstream_segment_id"] == header["id"]
        _, meta = validate_paginated(
            api_client.list_pipe_segments(NETWORK_ENGINEER, {"loop_id": loop["id"]})
        )
        assert_pagination_meta(meta, total_count=2)

    def test_register_reads_carry_no_version_and_no_updated_at(self):
        """A register snapshot is an append-only row, not a living entity.

        PRD: "Two resources are append-only records rather than living entities and
        therefore carry **only** `id` and `created_at`: the **DispatchOrder**, which
        is produced and destroyed wholesale by the merit-order optimisation, and the
        **MeterReading**, which is an immutable register snapshot."

        Design: Corner/Entities/meter_reading_and_dispatch_order_are_immutable_ledger_rows
        """
        set_clock()
        loop = create_loop(code="LOOP-Z1", rated_capacity_kw=9000.0)
        segment = create_segment(loop["id"], code="SEG-Z1")
        tariff = commercial_rate_schedule(code="RS-Z1")
        agreement = create_agreement(loop["id"], tariff["id"], customer_name="Zone One Tower")
        point = commissioned_point(agreement["id"], segment["id"], code="MP-Z3")
        add_reading(point["id"], "2026-08-02T00:00:00Z", 100.000, 300.0)
        add_reading(point["id"], "2026-08-03T00:00:00Z", 160.000, 320.0)

        rows, meta = validate_paginated(
            api_client.list_point_readings(point["id"], FIELD_TECHNICIAN)
        )

        assert_pagination_meta(meta, total_count=2)
        assert_read_at_ascending(rows)
        assert_energy(rows[0]["cumulative_energy_mwh"], 100.000)
        for row in rows:
            assert_append_only_record(row)

    def test_dispatch_orders_carry_no_version_and_no_updated_at(self):
        """The optimiser's output rows are equally immutable.

        PRD: "Neither has an `updated_at` field and neither has a `version` field;
        nothing in the API mutates them in place."

        Design: Corner/Entities/meter_reading_and_dispatch_order_are_immutable_ledger_rows
        """
        stack = campus_dispatch_stack(plan_state="OPTIMIZED")

        orders = plan_orders(stack["plan"]["id"])

        assert len(orders) == 3, f"expected three dispatch orders, got {len(orders)}"
        for order in orders:
            assert_append_only_record(order)

    def test_a_created_loop_is_immediately_readable_by_its_minted_id(self):
        """The id the create returned is the id the single-resource read accepts.

        PRD: "Every resource also carries a `created_at`, an ISO 8601 UTC timestamp
        with three fractional digits, taken from the logical clock at the moment of
        creation."

        Design: Corner/Entities/network_loop_creation_returns_every_declared_field_in_the_envelope
        """
        set_clock()
        loop = create_loop(code="LOOP-Z1", rated_capacity_kw=9000.0)

        fetched = read_loop(loop["id"])

        assert fetched["id"] == loop["id"]
        assert fetched["created_at"] == loop["created_at"]
        assert_common_fields(fetched, expected_version=1)
