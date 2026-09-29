"""What a creation body must carry, what it may leave out, and what it may not say.

Three concerns share this file because all three are decided before any state
rule runs: an absent required field or a wrong JSON type (PRD.md section 2.4),
the declared default of an omissible field (PRD.md section 2.8), and the four
distinct 422 identifiers the type-constraint families raise.
"""

from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT_UTC,
    dec,
    demand_forecast_bucket_payload,
    get_success_data,
    mold_payload,
    product_model_payload,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    warehouse_payload,
)


class TestRequiredFieldsAndDeclaredTypes:
    """An absent required field and a wrong JSON type are both ERR_VALIDATION."""

    @staticmethod
    def _model_and_site(api, admin_headers):
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)
        model = get_success_data(
            api.create_product_model(
                product_model_payload(
                    model_code="PM-CD-REQ", size_class="MID", nominal_charge_kg=24.0
                ),
                admin_headers,
            )
        )
        site = get_success_data(
            api.create_warehouse(
                warehouse_payload(
                    site_code="WHS-CD-REQ",
                    footprint_capacity_cube_m3=20.0,
                    zones=[{"zone_code": "ZN-CD-A", "capacity_cube_m3": 20.0}],
                ),
                admin_headers,
            )
        )
        return model, site

    def test_warehouse_without_its_zone_array_is_refused(self, api, admin_headers):
        """`zones` is required, so a site body that omits it is a schema fault.

        PRD.md section 2.4: "A field whose declared type does not match the
        supplied JSON type, a required field that is absent, and a timestamp or
        date string that does not parse are all `ERR_VALIDATION`."

        PRD.md section 2.8, Warehouse: "`zones` (required array of 1 to 12
        elements, each an object holding `zone_code` — 2–16 characters and
        unique within the site, a repeat being `ERR_DUPLICATE_CODE` — and
        `capacity_cube_m3`, greater than zero with four decimals)".

        Design: Corner/entities/ent_required_fields_and_declared_types_enforced_on_creation
        """
        self._model_and_site(api, admin_headers)

        refused = api.create_warehouse(
            {"site_code": "WHS-CD-NOZONES", "footprint_capacity_cube_m3": 20.0},
            admin_headers,
        )

        validate_error(refused, ApiErrorId.VALIDATION, 422)
        rows, meta = validate_paginated(api.list_warehouses(None, admin_headers))
        assert meta["total_count"] == 1
        assert all(row["site_code"] != "WHS-CD-NOZONES" for row in rows)

    def test_mold_without_its_service_interval_is_refused(self, api, admin_headers):
        """`service_interval_cycles` is required on a tool registration.

        PRD.md section 2.4: "A field whose declared type does not match the
        supplied JSON type, a required field that is absent, and a timestamp or
        date string that does not parse are all `ERR_VALIDATION`."

        PRD.md section 2.8, Mold: "`service_interval_cycles` (required integer,
        at least 1)".

        Design: Corner/entities/ent_required_fields_and_declared_types_enforced_on_creation
        """
        model, _site = self._model_and_site(api, admin_headers)

        refused = api.create_mold(
            {
                "mold_code": "MLD-CD-NOINT",
                "product_model_id": model["id"],
                "size_class": "MID",
                "cavity_count": 1,
                "nominal_charge_kg": 24.0,
            },
            admin_headers,
        )

        validate_error(refused, ApiErrorId.VALIDATION, 422)
        _rows, meta = validate_paginated(api.list_molds(None, admin_headers))
        assert meta["total_count"] == 0

    def test_order_without_ordered_qty_is_a_schema_fault_not_a_range_fault(
        self, api, admin_headers
    ):
        """An absent `ordered_qty` is ERR_VALIDATION, not ERR_INVALID_QUANTITY.

        PRD.md section 2.4: "A field whose declared type does not match the
        supplied JSON type, a required field that is absent, and a timestamp or
        date string that does not parse are all `ERR_VALIDATION`."

        PRD.md section 2.4: "where a field declares numeric bounds, a value
        outside those bounds is reported as `ERR_INVALID_QUANTITY` (HTTP 422)".

        Design: Corner/entities/ent_required_fields_and_declared_types_enforced_on_creation
        """
        model, site = self._model_and_site(api, admin_headers)

        refused = api.create_production_order(
            {
                "order_code": "POR-CD-NOQTY",
                "product_model_id": model["id"],
                "target_warehouse_id": site["id"],
            },
            admin_headers,
        )

        validate_error(refused, ApiErrorId.VALIDATION, 422)
        _rows, meta = validate_paginated(
            api.list_production_orders(None, admin_headers)
        )
        assert meta["total_count"] == 0

    def test_station_arm_count_supplied_as_a_string_is_refused(
        self, api, admin_headers
    ):
        """A declared integer supplied as a JSON string is a type mismatch.

        PRD.md section 2.4: "A field whose declared type does not match the
        supplied JSON type, a required field that is absent, and a timestamp or
        date string that does not parse are all `ERR_VALIDATION`."

        PRD.md section 2.8, OvenStation: "`arm_count` (required integer, 1 to 6
        inclusive — the number of independently schedulable rotating arms)".

        Design: Corner/entities/ent_required_fields_and_declared_types_enforced_on_creation
        """
        self._model_and_site(api, admin_headers)

        refused = api.create_oven_station(
            {
                "station_code": "OVN-CD-BADTYPE",
                "arm_count": "two",
                "max_size_class": "OVERSIZE",
                "changeover_buffer_min": 15,
                "energy_cents_per_min": 100,
            },
            admin_headers,
        )

        validate_error(refused, ApiErrorId.VALIDATION, 422)
        _rows, meta = validate_paginated(api.list_oven_stations(None, admin_headers))
        assert meta["total_count"] == 0


class TestDeclaredDefaultsOnOmittedFields:
    """The five body fields that may be omitted land on their declared defaults."""

    def test_site_thresholds_default_to_eighty_five_and_ninety_five(
        self, api, admin_headers
    ):
        """A site created without either threshold reads 85.00 and 95.00.

        PRD.md section 2.8, Warehouse: "`restricted_threshold_pct` (greater than
        0.00 and strictly less than `frozen_threshold_pct`, two decimals,
        default 85.00, compared with at-or-above); and
        `frozen_threshold_pct` (strictly greater than
        `restricted_threshold_pct` and at most 100.00, two decimals, default
        95.00, compared with at-or-above)."

        PRD.md section 2.8, Warehouse: "Derived: `committed_cube_m3` (four
        decimals, default 0.0000, held equal to the rounded sum of
        `stored_footprint_cube_m3` over the site's units whose
        `logistics_status` is `STORED` or `LOADED`); `utilization_pct` (two
        decimals, default 0.00); and `posture` (default `NORMAL`, one of
        `NORMAL`, `RESTRICTED`, `FROZEN`)."

        Design: Corner/entities/ent_defaults_warehouse_thresholds_bucket_cap_pct_and_null_optional_fks
        """
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)

        site = validate_success(
            api.create_warehouse(
                {
                    "site_code": "WHS-CD-DEF",
                    "footprint_capacity_cube_m3": 20.0,
                    "zones": [{"zone_code": "ZN-CD-A", "capacity_cube_m3": 20.0}],
                },
                admin_headers,
            ),
            expected_status=201,
        )

        assert dec(site["restricted_threshold_pct"]) == dec("85.00")
        assert dec(site["frozen_threshold_pct"]) == dec("95.00")
        assert dec(site["committed_cube_m3"]) == dec("0.0000")
        assert dec(site["utilization_pct"]) == dec("0.00")
        assert site["posture"] == "NORMAL"

    def test_bucket_cap_pct_defaults_and_the_derived_cap_qty_floors(
        self, api, admin_headers
    ):
        """The derived cap is floored from the *defaulted* percentage.

        PRD.md section 2.8, DemandForecastBucket: "`build_ahead_cap_pct`
        (greater than 0.00 and at most 100.00, two decimals, default 60.00)".

        PRD.md section 3.7: "A bucket's `build_ahead_cap_qty` is the floor of
        `forecast_qty` multiplied by `build_ahead_cap_pct` divided by 100."

        PRD.md section 2.8, DemandForecastBucket: "Derived:
        `build_ahead_cap_qty` (integer, default 0) and
        `build_ahead_committed_qty` (integer, default 0, never exceeding
        `build_ahead_cap_qty`)."

        Design: Corner/entities/ent_defaults_warehouse_thresholds_bucket_cap_pct_and_null_optional_fks
        """
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)
        model = get_success_data(
            api.create_product_model(
                product_model_payload(
                    model_code="PM-CD-DEF", nominal_charge_kg=24.0
                ),
                admin_headers,
            )
        )

        bucket = validate_success(
            api.create_demand_forecast_bucket(
                {
                    "season_code": "SEA-CD-2026",
                    "product_model_id": model["id"],
                    "forecast_qty": 26,
                    "window_start_on": "2026-08-01",
                    "window_end_on": "2026-10-31",
                },
                admin_headers,
            ),
            expected_status=201,
        )

        assert dec(bucket["build_ahead_cap_pct"]) == dec("60.00")
        # floor(26 * 60.00 / 100) is floor(15.6); a rounded 16 would be wrong.
        assert bucket["build_ahead_cap_qty"] == 15
        assert bucket["build_ahead_committed_qty"] == 0

    def test_optional_foreign_keys_default_to_null(self, api, admin_headers):
        """A tool omits `replaces_mold_id` and an order omits `demand_bucket_id`.

        PRD.md section 2.8, Mold: "and the optional `replaces_mold_id` (default
        null; when present it must resolve or `ERR_MOLD_NOT_FOUND`, must have
        `status` `RETIRED` or `ERR_MOLD_NOT_AVAILABLE`, and must reference a
        tool of the same `product_model_id` — and must not be the tool itself —
        or `ERR_INVALID_MOLD_REPLACEMENT`)."

        PRD.md section 2.8, ProductionOrder: "the optional `demand_bucket_id`
        (default null; when present it must resolve or
        `ERR_DEMAND_BUCKET_NOT_FOUND`, and its own `product_model_id` must equal
        the order's or `ERR_VALIDATION`)".

        PRD.md section 2.8, ProductionOrder: "Derived: `completed_qty` and
        `scrapped_qty` (integers, default 0); `status` (default `DRAFT`, one of
        `DRAFT`, `READY_TO_SCHEDULE`, `BLOCKED_RESIN`, `BLOCKED_WAREHOUSE`,
        `IN_PRODUCTION`, `COMPLETE`, `CANCELLED`); `blocked_reason` (default
        null, and when set either `NO_QUALIFIED_RESIN_LOT` or
        `WAREHOUSE_FROZEN`)".

        Design: Corner/entities/ent_defaults_warehouse_thresholds_bucket_cap_pct_and_null_optional_fks
        """
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)
        model = get_success_data(
            api.create_product_model(
                product_model_payload(
                    model_code="PM-CD-DEF-FK", nominal_charge_kg=24.0
                ),
                admin_headers,
            )
        )
        site = get_success_data(
            api.create_warehouse(
                warehouse_payload(site_code="WHS-CD-DEF-FK"), admin_headers
            )
        )

        mold = validate_success(
            api.create_mold(
                {
                    "mold_code": "MLD-CD-DEF",
                    "product_model_id": model["id"],
                    "size_class": "MID",
                    "cavity_count": 1,
                    "nominal_charge_kg": 24.0,
                    "service_interval_cycles": 10,
                },
                admin_headers,
            ),
            expected_status=201,
        )
        order = validate_success(
            api.create_production_order(
                {
                    "order_code": "POR-CD-DEF",
                    "product_model_id": model["id"],
                    "target_warehouse_id": site["id"],
                    "ordered_qty": 1,
                },
                admin_headers,
            ),
            expected_status=201,
        )

        assert mold.get("replaces_mold_id") is None
        assert order.get("demand_bucket_id") is None
        assert order["status"] == "DRAFT"
        assert order["completed_qty"] == 0
        assert order["scrapped_qty"] == 0
        assert order.get("blocked_reason") is None
        assert order["material_cost_cents"] == 0
        assert order["oven_energy_cost_cents"] == 0
        assert order["overhead_cents"] == 0
        assert order["total_cost_cents"] == 0
        # PRD.md section 2.8 calls unit_cost_cents an integer defaulting to 0
        # while leaving no per-unit figure meaningful before any hull completes,
        # so both spellings of "nothing booked yet" are accepted here.
        assert order.get("unit_cost_cents") in (0, None)


class TestTypeConstraintFamilies:
    """Four constraint families, four distinct 422 identifiers."""

    @staticmethod
    def _tandem_model(api, admin_headers):
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)
        return get_success_data(
            api.create_product_model(
                product_model_payload(
                    model_code="PM-CD-TYPE",
                    size_class="TANDEM",
                    nominal_charge_kg=12.0,
                ),
                admin_headers,
            )
        )

    def test_undeclared_enum_member_is_an_enum_failure(self, api, admin_headers):
        """A size class outside the declared four is ERR_INVALID_ENUM_VALUE.

        PRD.md section 2.4: "A value outside an enum's declared set is
        `ERR_INVALID_ENUM_VALUE`."

        PRD.md section 2.8, Mold: "`size_class` (required, one of the four
        classes, and must equal the referenced model's `size_class` or
        `ERR_MOLD_SIZE_CLASS_MISMATCH`)".

        Design: Corner/entities/ent_type_constraints_enum_member_numeric_range_and_window_order
        """
        model = self._tandem_model(api, admin_headers)

        refused = api.create_mold(
            mold_payload(
                model["id"],
                mold_code="MLD-CD-TYPE-ENUM",
                size_class="GIANT",
                cavity_count=2,
                nominal_charge_kg=24.0,
            ),
            admin_headers,
        )

        validate_error(refused, ApiErrorId.INVALID_ENUM_VALUE, 422)
        _rows, meta = validate_paginated(
            api.list_molds({"product_model_id": model["id"]}, admin_headers)
        )
        assert meta["total_count"] == 0

    def test_declared_member_that_disagrees_with_the_parent_row_is_a_mismatch(
        self, api, admin_headers
    ):
        """`MID` is a legal member, so what fails is the equality with the model.

        PRD.md section 3.1: "A tool whose `size_class` disagrees with its
        model's is rejected with `ERR_MOLD_SIZE_CLASS_MISMATCH`."

        Design: Corner/entities/ent_type_constraints_enum_member_numeric_range_and_window_order
        """
        model = self._tandem_model(api, admin_headers)

        refused = api.create_mold(
            mold_payload(
                model["id"],
                mold_code="MLD-CD-TYPE-SIZE",
                size_class="MID",
                cavity_count=2,
                nominal_charge_kg=24.0,
            ),
            admin_headers,
        )

        validate_error(refused, ApiErrorId.MOLD_SIZE_CLASS_MISMATCH, 422)
        _rows, meta = validate_paginated(
            api.list_molds({"product_model_id": model["id"]}, admin_headers)
        )
        assert meta["total_count"] == 0

    def test_cavity_count_above_its_declared_ceiling_is_a_quantity_failure(
        self, api, admin_headers
    ):
        """Five cavities is outside the declared 1..4 band.

        PRD.md section 2.8, Mold: "`cavity_count` (required integer, 1 to 4
        inclusive — the number of hulls one completed cycle yields)".

        PRD.md section 2.4: "where a field declares numeric bounds, a value
        outside those bounds is reported as `ERR_INVALID_QUANTITY` (HTTP 422)".

        Design: Corner/entities/ent_type_constraints_enum_member_numeric_range_and_window_order
        """
        model = self._tandem_model(api, admin_headers)

        refused = api.create_mold(
            mold_payload(
                model["id"],
                mold_code="MLD-CD-TYPE-CAV",
                size_class="TANDEM",
                cavity_count=5,
                nominal_charge_kg=60.0,
            ),
            admin_headers,
        )

        validate_error(refused, ApiErrorId.INVALID_QUANTITY, 422)
        _rows, meta = validate_paginated(
            api.list_molds({"product_model_id": model["id"]}, admin_headers)
        )
        assert meta["total_count"] == 0

    def test_arm_count_above_its_declared_ceiling_is_a_quantity_failure(
        self, api, admin_headers
    ):
        """Seven arms is outside the declared 1..6 band.

        PRD.md section 2.8, OvenStation: "`arm_count` (required integer, 1 to 6
        inclusive — the number of independently schedulable rotating arms)".

        PRD.md section 2.4: "where a field declares numeric bounds, a value
        outside those bounds is reported as `ERR_INVALID_QUANTITY` (HTTP 422)".

        Design: Corner/entities/ent_type_constraints_enum_member_numeric_range_and_window_order
        """
        self._tandem_model(api, admin_headers)

        refused = api.create_oven_station(
            {
                "station_code": "OVN-CD-TYPE",
                "arm_count": 7,
                "max_size_class": "OVERSIZE",
                "changeover_buffer_min": 15,
                "energy_cents_per_min": 100,
            },
            admin_headers,
        )

        validate_error(refused, ApiErrorId.INVALID_QUANTITY, 422)

    def test_negative_offset_on_a_list_read_is_refused(self, api, admin_headers):
        """The bound on `offset` applies to reads, not only to writes.

        PRD.md section 2.3: "`offset` is the zero-based index of the first row
        returned; it defaults to 0 and must not be negative."

        Design: Corner/entities/ent_type_constraints_enum_member_numeric_range_and_window_order
        """
        self._tandem_model(api, admin_headers)

        refused = api.list_molds({"limit": 1, "offset": -1}, admin_headers)

        assert refused.status_code == 422
        validate_error_is_one_of(
            refused, [ApiErrorId.VALIDATION, ApiErrorId.INVALID_QUANTITY]
        )

    def test_inverted_bucket_window_is_a_window_failure(
        self, api, planner_headers, admin_headers
    ):
        """An end date earlier than the start date has its own identifier.

        PRD.md section 2.8, DemandForecastBucket: "`window_end_on` (required,
        `YYYY-MM-DD`, not earlier than `window_start_on` — an inverted window is
        `ERR_INVALID_WINDOW`)."

        Design: Corner/entities/ent_type_constraints_enum_member_numeric_range_and_window_order
        """
        model = self._tandem_model(api, admin_headers)

        refused = api.create_demand_forecast_bucket(
            demand_forecast_bucket_payload(
                model["id"],
                season_code="SSN-CD-TYPE-W",
                forecast_qty=20,
                build_ahead_cap_pct=60.0,
                window_start_on="2026-12-31",
                window_end_on="2026-01-01",
            ),
            planner_headers,
        )

        validate_error(refused, ApiErrorId.INVALID_WINDOW, 422)

    def test_cap_percentage_above_one_hundred_is_a_quantity_failure(
        self, api, planner_headers, admin_headers
    ):
        """A 120.00 cap percentage is outside its declared band, window legal.

        PRD.md section 2.8, DemandForecastBucket: "`build_ahead_cap_pct`
        (greater than 0.00 and at most 100.00, two decimals, default 60.00)".

        PRD.md section 2.4: "where a field declares numeric bounds, a value
        outside those bounds is reported as `ERR_INVALID_QUANTITY` (HTTP 422)".

        Design: Corner/entities/ent_type_constraints_enum_member_numeric_range_and_window_order
        """
        model = self._tandem_model(api, admin_headers)

        refused = api.create_demand_forecast_bucket(
            demand_forecast_bucket_payload(
                model["id"],
                season_code="SSN-CD-TYPE-P",
                forecast_qty=20,
                build_ahead_cap_pct=120.0,
                window_start_on="2026-09-01",
                window_end_on="2026-10-31",
            ),
            planner_headers,
        )

        validate_error(refused, ApiErrorId.INVALID_QUANTITY, 422)

    def test_single_day_window_at_the_inclusive_cap_edge_is_accepted(
        self, api, planner_headers, admin_headers
    ):
        """A window whose two bounds are equal is legal, and 100.00 is in band.

        PRD.md section 2.8, DemandForecastBucket: "`window_end_on` (required,
        `YYYY-MM-DD`, not earlier than `window_start_on` — an inverted window is
        `ERR_INVALID_WINDOW`)."

        PRD.md section 3.7: "A bucket's `build_ahead_cap_qty` is the floor of
        `forecast_qty` multiplied by `build_ahead_cap_pct` divided by 100."

        Design: Corner/entities/ent_type_constraints_enum_member_numeric_range_and_window_order
        """
        model = self._tandem_model(api, admin_headers)

        bucket = validate_success(
            api.create_demand_forecast_bucket(
                demand_forecast_bucket_payload(
                    model["id"],
                    season_code="SSN-CD-TYPE-OK",
                    forecast_qty=20,
                    build_ahead_cap_pct=100.0,
                    window_start_on="2026-09-01",
                    window_end_on="2026-09-01",
                ),
                planner_headers,
            ),
            expected_status=201,
        )

        assert dec(bucket["build_ahead_cap_pct"]) == dec("100.00")
        assert bucket["build_ahead_cap_qty"] == 20
