"""Entity surface: creation, defaults, stamped fields, reads, lists and lookups.

Covers the field-level contract of the eleven resource kinds — which inputs the
client supplies, which values the server stamps, which references it insists on
resolving, and what a missing row answers with.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    create_agreement_payload,
    create_dispenser_unit_payload,
    create_maintenance_task_payload,
    create_outlet_payload,
    create_route_payload,
    create_route_stop_payload,
    create_supply_item_payload,
    create_supply_position_payload,
    create_telemetry_payload,
    create_van_part_stock_payload,
    outlet_status_change_payload,
    pin_clock,
    read_route,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]
DRIVER = TEST_USERS["driver_headers"]
TECH = TEST_USERS["technician_headers"]
OFFICER = TEST_USERS["officer_headers"]


def _three_outlets(api):
    pin_clock()
    first = validate_success(
        api.create_outlet(
            create_outlet_payload(
                name="Riverside Diner", account_code="OUT-1001", region_code="R-WEST"
            ),
            ADMIN,
        ),
        201,
    )
    second = validate_success(
        api.create_outlet(
            create_outlet_payload(
                name="Corner Deli", account_code="OUT-1002", region_code="R-WEST"
            ),
            ADMIN,
        ),
        201,
    )
    third = validate_success(
        api.create_outlet(
            create_outlet_payload(
                name="Harbor Cafe", account_code="OUT-1003", region_code="R-EAST"
            ),
            ADMIN,
        ),
        201,
    )
    return first, second, third


def _outlet_with_unit(api):
    """One outlet, one DRAFT agreement, one IN_SERVICE unit and one SKU."""
    pin_clock()
    outlet = validate_success(
        api.create_outlet(
            create_outlet_payload(
                name="Riverside Diner", account_code="OUT-1001", region_code="R-WEST"
            ),
            ADMIN,
        ),
        201,
    )
    agreement = validate_success(
        api.create_agreement(
            create_agreement_payload(
                outlet["id"], outlet["version"],
                annual_commitment_gallons=8000, equipment_value_cents=480000,
            ),
            ADMIN,
        ),
        201,
    )
    unit = validate_success(
        api.create_dispenser_unit(
            create_dispenser_unit_payload(
                outlet["id"], agreement["id"], serial_number="SN-9001",
                installed_at="2025-11-01T00:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )
    item = validate_success(
        api.create_supply_item(
            create_supply_item_payload(
                sku_code="SKU-COLA", brand_name="Cola Classic",
                supply_form="CARTRIDGE", case_pack_units=4, ounces_per_unit=1000,
            ),
            ADMIN,
        ),
        201,
    )
    return outlet, agreement, unit, item


class TestOutletCreation:
    def test_every_declared_input_field_is_echoed_back(self, api):
        """PRD §3.1: "A `NetworkAdmin` registers one by supplying its trading `name`,
        an operator-assigned `account_code` and the `region_code` of the depot that
        will serve it."

        Design: Corner/entities/outlet_creation_with_all_input_fields_returns_full_entity
        """
        pin_clock()
        created = validate_success(
            api.create_outlet(
                create_outlet_payload(
                    name="Riverside Diner", account_code="OUT-1001",
                    region_code="R-WEST", throughput_tier="LARGE",
                    water_hardness_gpg=25,
                ),
                ADMIN,
            ),
            201,
        )
        assert created["name"] == "Riverside Diner"
        assert created["account_code"] == "OUT-1001"
        assert created["region_code"] == "R-WEST"
        assert created["throughput_tier"] == "LARGE"
        assert created["water_hardness_gpg"] == 25
        assert created["status"] == "ACTIVE"
        assert created["version"] == 1

    def test_omitted_tier_and_hardness_take_their_declared_defaults(self, api):
        """PRD §3.1: "`throughput_tier` is the volume band used by the projected
        forecast variant and must be one of `SMALL`, `MEDIUM` or `LARGE`; when it is
        omitted the outlet is recorded as `MEDIUM`. `water_hardness_gpg` is the
        feed-water hardness in grains per gallon, accepted from 0 through 60
        inclusive, and defaults to 10 when omitted".

        Design: Corner/entities/outlet_creation_omitting_optionals_applies_tier_and_hardness_defaults
        """
        pin_clock()
        created = validate_success(
            api.create_outlet(
                create_outlet_payload(
                    name="Corner Deli", account_code="OUT-1002", region_code="R-WEST"
                ),
                ADMIN,
            ),
            201,
        )
        assert created["throughput_tier"] == "MEDIUM"
        assert created["water_hardness_gpg"] == 10

    def test_the_server_stamps_status_posture_counters_and_version(self, api):
        """PRD §3.1: "A freshly registered outlet opens for business immediately: its
        `status` is `ACTIVE`, its derived `service_posture` is `OPEN`, both of its
        compliance counters — `open_compliance_hold_count` and `overdue_task_count` —
        stand at 0, its `last_hold_placed_by_user_id` is null, and its `version` is
        1."

        Design: Corner/entities/outlet_system_and_computed_fields_stamped_on_create
        """
        pin_clock()
        created = validate_success(
            api.create_outlet(
                create_outlet_payload(
                    name="Riverside Diner", account_code="OUT-1001",
                    region_code="R-WEST",
                ),
                ADMIN,
            ),
            201,
        )
        assert is_valid_uuid(created["id"])
        assert created["version"] == 1
        assert is_iso8601_timestamp(created["created_at"])
        assert created["status"] == "ACTIVE"
        assert created["service_posture"] == "OPEN"
        assert created["open_compliance_hold_count"] == 0
        assert created["overdue_task_count"] == 0
        assert created["last_hold_placed_by_user_id"] is None

    def test_a_missing_account_code_is_a_malformed_request(self, api):
        """PRD §2.6: "**Request shape.** The body parses, every required input field
        is present, every enum-valued field carries a declared member, numeric fields
        respect their declared ranges (no negative units, ounces, gallons or
        capacities), and any supplied `limit` lies between 1 and 100 inclusive.
        Otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/outlet_creation_missing_account_code_rejected
        """
        pin_clock()
        response = api.create_outlet(
            {"name": "Riverside Diner", "region_code": "R-WEST"}, ADMIN
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        _rows, meta = validate_paginated(api.list_outlets(ADMIN))
        assert meta["total_count"] == 0

    def test_an_undeclared_throughput_tier_member_is_rejected(self, api):
        """PRD §3.1: "`throughput_tier` is the volume band used by the projected
        forecast variant and must be one of `SMALL`, `MEDIUM` or `LARGE`".

        Design: Corner/entities/outlet_undeclared_throughput_tier_enum_member_rejected
        """
        pin_clock()
        response = api.create_outlet(
            create_outlet_payload(
                name="Riverside Diner", account_code="OUT-1001",
                region_code="R-WEST", throughput_tier="HUGE",
            ),
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        _rows, meta = validate_paginated(api.list_outlets(ADMIN))
        assert meta["total_count"] == 0


class TestOutletReads:
    def test_a_planner_reads_back_exactly_what_the_admin_persisted(self, api):
        """PRD §3.1: "Reading a single outlet returns its counters and derived posture
        alongside its input fields".

        Design: Corner/entities/outlet_retrieval_returns_stored_field_values
        """
        pin_clock()
        created = validate_success(
            api.create_outlet(
                create_outlet_payload(
                    name="Riverside Diner", account_code="OUT-1001",
                    region_code="R-WEST", throughput_tier="LARGE",
                    water_hardness_gpg=25,
                ),
                ADMIN,
            ),
            201,
        )

        fetched = validate_success(api.get_outlet(created["id"], PLANNER))
        assert fetched["account_code"] == "OUT-1001"
        assert fetched["throughput_tier"] == "LARGE"
        assert fetched["water_hardness_gpg"] == 25
        assert fetched["service_posture"] == "OPEN"

    def test_the_default_page_reports_ten_zero_and_the_full_count(self, api):
        """PRD §2.3: "`limit` caps the number of items returned; when it is omitted it
        defaults to 10, its minimum accepted value is 1 and its maximum accepted value
        is 100. A `limit` below 1 or above 100 is a malformed request and is rejected
        with `ERR_INVALID_REQUEST` and HTTP 400. `offset` is the number of items to
        skip and defaults to 0."

        Design: Corner/entities/outlet_listing_default_pagination_envelope_shape
        """
        _three_outlets(api)

        rows, meta = validate_paginated(api.list_outlets(ADMIN))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(rows) == 3

    def test_paging_two_at_a_time_flips_has_more_and_keeps_the_total(self, api):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
        `has_more` in the `meta` object of the envelope, where `total_count` is the
        number of rows matching the filters before pagination is applied and
        `has_more` is true when rows remain beyond the returned page."

        Design: Corner/entities/outlet_listing_limit_and_offset_paging_flips_has_more
        """
        _three_outlets(api)

        first_page, first_meta = validate_paginated(
            api.list_outlets(ADMIN, {"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            api.list_outlets(ADMIN, {"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

    def test_a_limit_of_one_hundred_and_one_is_refused(self, api):
        """PRD §2.3: "`limit` caps the number of items returned; when it is omitted it
        defaults to 10, its minimum accepted value is 1 and its maximum accepted value
        is 100. A `limit` below 1 or above 100 is a malformed request and is rejected
        with `ERR_INVALID_REQUEST` and HTTP 400."

        Design: Corner/entities/outlet_listing_limit_above_maximum_rejected
        """
        pin_clock()
        validate_success(
            api.create_outlet(
                create_outlet_payload(
                    name="Riverside Diner", account_code="OUT-1001",
                    region_code="R-WEST",
                ),
                ADMIN,
            ),
            201,
        )

        response = api.list_outlets(ADMIN, {"limit": 101})
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_a_limit_of_zero_is_refused_rather_than_returning_an_empty_page(self, api):
        """PRD §2.6: "**Request shape.** The body parses, every required input field
        is present, every enum-valued field carries a declared member, numeric fields
        respect their declared ranges (no negative units, ounces, gallons or
        capacities), and any supplied `limit` lies between 1 and 100 inclusive.
        Otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/outlet_listing_limit_below_minimum_rejected
        """
        pin_clock()
        validate_success(
            api.create_outlet(
                create_outlet_payload(
                    name="Riverside Diner", account_code="OUT-1001",
                    region_code="R-WEST",
                ),
                ADMIN,
            ),
            201,
        )

        response = api.list_outlets(ADMIN, {"limit": 0})
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_region_and_status_filters_narrow_the_list_together(self, api):
        """PRD §3.1: "the outlet list can be narrowed by `region_code`, by `status`
        and by `service_posture` in addition to the usual `limit` and `offset`."

        Design: Corner/entities/outlet_listing_combined_region_and_status_filter
        """
        first, second, _third = _three_outlets(api)
        validate_success(
            api.outlet_status_change(
                second["id"], outlet_status_change_payload("SUSPEND"), ADMIN
            )
        )

        rows, meta = validate_paginated(
            api.list_outlets(ADMIN, {"region_code": "R-WEST", "status": "ACTIVE"})
        )
        assert len(rows) == 1
        assert rows[0]["id"] == first["id"]
        assert meta["total_count"] == 1
        assert validate_success(api.get_outlet(second["id"], ADMIN))["status"] == "SUSPENDED"


class TestUnknownIdentifiers:
    """Rung 4 of §2.6: the 404 code names the resource kind that is missing."""

    def test_an_unknown_outlet_id_answers_outlet_not_found(self, api):
        """PRD §2.6: "The 404 code is the one belonging to the missing resource kind:
        `ERR_OUTLET_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_DISPENSER_UNIT_NOT_FOUND`, `ERR_SUPPLY_ITEM_NOT_FOUND`,
        `ERR_SUPPLY_POSITION_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`,
        `ERR_ROUTE_STOP_NOT_FOUND`, `ERR_MAINTENANCE_TASK_NOT_FOUND`,
        `ERR_SERVICE_CALL_NOT_FOUND`, `ERR_VAN_PART_STOCK_NOT_FOUND` or
        `ERR_TELEMETRY_READING_NOT_FOUND`."

        Design: Corner/entities/outlet_not_found_on_unknown_id
        """
        pin_clock()
        validate_error(
            api.get_outlet(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_OUTLET_NOT_FOUND.value,
            404,
        )

    def test_an_unknown_agreement_id_answers_agreement_not_found(self, api):
        """PRD §2.6: "**Path existence.** Every identifier in the request path must
        resolve to an existing row, validated strictly left to right, so the leftmost
        unresolvable identifier decides the error."

        Design: Corner/entities/agreement_not_found_on_unknown_id
        """
        pin_clock()
        validate_error(
            api.get_agreement(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
            404,
        )

    def test_an_unknown_dispenser_unit_id_answers_dispenser_unit_not_found(self, api):
        """PRD §2.6: "**Path existence.** Every identifier in the request path must
        resolve to an existing row, validated strictly left to right, so the leftmost
        unresolvable identifier decides the error."

        Design: Corner/entities/dispenser_unit_not_found_on_unknown_id
        """
        pin_clock()
        validate_error(
            api.get_dispenser_unit(NON_EXISTENT_UUID, TECH),
            ApiErrorId.ERR_DISPENSER_UNIT_NOT_FOUND.value,
            404,
        )

    def test_an_unknown_supply_item_id_answers_supply_item_not_found(self, api):
        """PRD §2.6: "**Path existence.** Every identifier in the request path must
        resolve to an existing row, validated strictly left to right, so the leftmost
        unresolvable identifier decides the error."

        Design: Corner/entities/supply_item_not_found_on_unknown_id
        """
        pin_clock()
        validate_error(
            api.get_supply_item(NON_EXISTENT_UUID, PLANNER),
            ApiErrorId.ERR_SUPPLY_ITEM_NOT_FOUND.value,
            404,
        )

    def test_an_unknown_supply_position_id_answers_supply_position_not_found(self, api):
        """PRD §2.6: "**Path existence.** Every identifier in the request path must
        resolve to an existing row, validated strictly left to right, so the leftmost
        unresolvable identifier decides the error."

        Design: Corner/entities/supply_position_not_found_on_unknown_id
        """
        pin_clock()
        validate_error(
            api.get_supply_position(NON_EXISTENT_UUID, PLANNER),
            ApiErrorId.ERR_SUPPLY_POSITION_NOT_FOUND.value,
            404,
        )

    def test_an_unknown_route_id_answers_route_not_found(self, api):
        """PRD §2.6: "**Path existence.** Every identifier in the request path must
        resolve to an existing row, validated strictly left to right, so the leftmost
        unresolvable identifier decides the error."

        Design: Corner/entities/route_not_found_on_unknown_id
        """
        pin_clock()
        validate_error(
            api.get_route(NON_EXISTENT_UUID, PLANNER),
            ApiErrorId.ERR_ROUTE_NOT_FOUND.value,
            404,
        )

    def test_an_unknown_route_stop_id_answers_route_stop_not_found(self, api):
        """PRD §2.6: "**Path existence.** Every identifier in the request path must
        resolve to an existing row, validated strictly left to right, so the leftmost
        unresolvable identifier decides the error."

        Design: Corner/entities/route_stop_not_found_on_unknown_id
        """
        pin_clock()
        validate_error(
            api.get_route_stop(NON_EXISTENT_UUID, DRIVER),
            ApiErrorId.ERR_ROUTE_STOP_NOT_FOUND.value,
            404,
        )

    def test_an_unknown_task_id_answers_maintenance_task_not_found(self, api):
        """PRD §2.6: "**Path existence.** Every identifier in the request path must
        resolve to an existing row, validated strictly left to right, so the leftmost
        unresolvable identifier decides the error."

        Design: Corner/entities/maintenance_task_not_found_on_unknown_id
        """
        pin_clock()
        validate_error(
            api.get_maintenance_task(NON_EXISTENT_UUID, OFFICER),
            ApiErrorId.ERR_MAINTENANCE_TASK_NOT_FOUND.value,
            404,
        )

    def test_an_unknown_service_call_id_answers_service_call_not_found(self, api):
        """PRD §2.6: "**Path existence.** Every identifier in the request path must
        resolve to an existing row, validated strictly left to right, so the leftmost
        unresolvable identifier decides the error."

        Design: Corner/entities/service_call_not_found_on_unknown_id
        """
        pin_clock()
        validate_error(
            api.get_service_call(NON_EXISTENT_UUID, TECH),
            ApiErrorId.ERR_SERVICE_CALL_NOT_FOUND.value,
            404,
        )

    def test_an_unknown_van_stock_id_answers_van_part_stock_not_found(self, api):
        """PRD §2.6: "**Path existence.** Every identifier in the request path must
        resolve to an existing row, validated strictly left to right, so the leftmost
        unresolvable identifier decides the error."

        Design: Corner/entities/van_part_stock_not_found_on_unknown_id
        """
        pin_clock()
        validate_error(
            api.get_van_part_stock(NON_EXISTENT_UUID, TECH),
            ApiErrorId.ERR_VAN_PART_STOCK_NOT_FOUND.value,
            404,
        )

    def test_an_unknown_reading_id_answers_telemetry_reading_not_found(self, api):
        """PRD §2.6: "**Path existence.** Every identifier in the request path must
        resolve to an existing row, validated strictly left to right, so the leftmost
        unresolvable identifier decides the error."

        Design: Corner/entities/telemetry_reading_not_found_on_unknown_id
        """
        pin_clock()
        validate_error(
            api.get_telemetry_reading(NON_EXISTENT_UUID, PLANNER),
            ApiErrorId.ERR_TELEMETRY_READING_NOT_FOUND.value,
            404,
        )


class TestBodyReferences:
    def test_a_position_naming_an_unknown_sku_creates_nothing(self, api):
        """PRD §2.6: "**Body reference existence.** Every foreign reference named in
        the body — `outlet_id`, `agreement_id`, `dispenser_unit_id`, `supply_item_id`,
        and every member of `supply_position_ids` — must resolve, otherwise the
        corresponding 404 code above is returned."

        Design: Corner/entities/supply_position_create_with_unknown_supply_item_id_rejected
        """
        pin_clock()
        outlet = validate_success(
            api.create_outlet(
                create_outlet_payload(
                    name="Riverside Diner", account_code="OUT-1001",
                    region_code="R-WEST",
                ),
                ADMIN,
            ),
            201,
        )

        response = api.create_supply_position(
            create_supply_position_payload(
                outlet["id"], NON_EXISTENT_UUID, on_hand_units=4
            ),
            PLANNER,
        )
        validate_error(response, ApiErrorId.ERR_SUPPLY_ITEM_NOT_FOUND.value, 404)

        _rows, meta = validate_paginated(
            api.list_supply_positions(PLANNER, {"outlet_id": outlet["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_reading_naming_an_unknown_machine_stores_nothing(self, api):
        """PRD §2.6: "This rung applies to agreement creation, dispenser-unit
        creation, telemetry ingestion, supply-position creation, route-stop creation,
        stop allocation, maintenance-task creation and service-call creation."

        Design: Corner/entities/telemetry_create_with_unknown_dispenser_unit_id_rejected
        """
        pin_clock()
        item = validate_success(
            api.create_supply_item(
                create_supply_item_payload(
                    sku_code="SKU-COLA", brand_name="Cola Classic",
                    supply_form="CARTRIDGE", case_pack_units=4, ounces_per_unit=1000,
                ),
                ADMIN,
            ),
            201,
        )

        response = api.create_telemetry_reading(
            create_telemetry_payload(
                NON_EXISTENT_UUID, item["id"], 1000, "2026-07-28T00:00:00Z"
            ),
            PLANNER,
        )
        validate_error(response, ApiErrorId.ERR_DISPENSER_UNIT_NOT_FOUND.value, 404)

        _rows, meta = validate_paginated(
            api.list_telemetry_readings(PLANNER, {"supply_item_id": item["id"]})
        )
        assert meta["total_count"] == 0


class TestStampedAndComputedFields:
    def test_a_reading_carries_no_version_and_no_updated_at(self, api):
        """PRD §2.5: "Telemetry readings are the single exception. A telemetry reading
        is an immutable event: it carries `id` and `created_at` only, and both
        `updated_at` and `version` are absent from its representation. A reading is
        never edited, never deleted and never superseded."

        Design: Corner/entities/telemetry_reading_is_immutable_no_version_and_no_write_endpoint
        """
        _outlet, _agreement, unit, item = _outlet_with_unit(api)
        reading = validate_success(
            api.create_telemetry_reading(
                create_telemetry_payload(
                    unit["id"], item["id"], 1000, "2026-07-28T00:00:00Z"
                ),
                PLANNER,
            ),
            201,
        )

        fetched = validate_success(api.get_telemetry_reading(reading["id"], OFFICER))
        assert fetched["dispensed_ounces"] == 1000
        assert fetched["window_days"] == 7
        assert fetched["source"] == "TELEMETRY"
        assert is_iso8601_timestamp(fetched["created_at"])
        assert "version" not in fetched
        assert "updated_at" not in fetched

    def test_the_odometer_rounds_half_up_to_two_decimals(self, api):
        """PRD §3.4: "Each ingestion refreshes the receiving machine's
        `lifetime_dispensed_gallons`, which is defined as the total ounces ever
        reported for that unit divided by 128 and then rounded half up to two decimal
        places."

        Design: Corner/entities/dispenser_unit_lifetime_gallons_rounds_half_up_to_two_decimals
        """
        _outlet, _agreement, unit, item = _outlet_with_unit(api)

        validate_success(
            api.create_telemetry_reading(
                create_telemetry_payload(
                    unit["id"], item["id"], 128.64, "2026-07-28T00:00:00Z"
                ),
                PLANNER,
            ),
            201,
        )

        machine = validate_success(api.get_dispenser_unit(unit["id"], TECH))
        assert machine["lifetime_dispensed_gallons"] == 1.01
        assert machine["gallons_at_last_filter_change"] == 0
        assert machine["version"] == 2

    def test_a_new_sku_starts_non_promotional_with_an_empty_pool(self, api):
        """PRD §3.6: "Three optional inputs describe limited-time flavours:
        `promotional`, which defaults to false; and `promo_window_start` and
        `promo_window_end`, both null by default and meaningful only for promotional
        SKUs. A final optional input, `national_allocation_units`, defaults to 0, must
        be zero or greater, and is the finite national pool of units the network may
        commit to routes. Registration answers 201 with `reserved_pool_units` at 0 and
        `version` 1".

        Design: Corner/entities/supply_item_creation_defaults_promotional_and_pool_fields
        """
        pin_clock()
        created = validate_success(
            api.create_supply_item(
                create_supply_item_payload(
                    sku_code="SKU-COLA", brand_name="Cola Classic",
                    supply_form="BAG_IN_BOX", case_pack_units=3, ounces_per_unit=2000,
                ),
                ADMIN,
            ),
            201,
        )
        assert created["promotional"] is False
        assert created["national_allocation_units"] == 0
        assert created["reserved_pool_units"] == 0
        assert created["promo_window_start"] is None
        assert created["promo_window_end"] is None
        assert created["version"] == 1

    def test_a_new_van_row_freezes_its_loaded_baseline(self, api):
        """PRD §3.8: "Creation answers 201 recording `initial_units` equal to the
        units supplied — a fixed baseline that never changes again — with
        `reserved_units`, `consumed_units` and `restocked_units` all 0 and `version`
        1; none of the four counters may ever go negative."

        Design: Corner/entities/van_part_stock_creation_freezes_initial_units_baseline
        """
        pin_clock()
        created = validate_success(
            api.create_van_part_stock(
                create_van_part_stock_payload("VAN-7", "PUMP_ASSY_12", 5), ADMIN
            ),
            201,
        )
        assert created["initial_units"] == 5
        assert created["on_van_units"] == 5
        assert created["reserved_units"] == 0
        assert created["consumed_units"] == 0
        assert created["restocked_units"] == 0

    def test_a_new_position_starts_with_a_zero_forecast_and_no_alert(self, api):
        """PRD §3.6: "A newly opened position answers 201 with `forecast_variant`
        recorded as `TRAILING_ACTUAL`, `forecast_units` at 0, `requested_units` at 0,
        `allocated_units` at 0, `planned_route_stop_id` null, `alert_level` `NONE`,
        `promo_suppressed` false, `alert_acknowledged_by_user_id` null and `version`
        1."

        Design: Corner/entities/supply_position_creation_defaults_zero_forecast_and_none_alert
        """
        pin_clock()
        outlet = validate_success(
            api.create_outlet(
                create_outlet_payload(
                    name="Riverside Diner", account_code="OUT-1001",
                    region_code="R-WEST",
                ),
                ADMIN,
            ),
            201,
        )
        item = validate_success(
            api.create_supply_item(
                create_supply_item_payload(
                    sku_code="SKU-COLA", brand_name="Cola Classic",
                    supply_form="CARTRIDGE", case_pack_units=4, ounces_per_unit=1000,
                ),
                ADMIN,
            ),
            201,
        )

        created = validate_success(
            api.create_supply_position(
                create_supply_position_payload(outlet["id"], item["id"], on_hand_units=6),
                PLANNER,
            ),
            201,
        )
        assert created["on_hand_units"] == 6
        assert created["forecast_variant"] == "TRAILING_ACTUAL"
        assert created["forecast_units"] == 0
        assert created["requested_units"] == 0
        assert created["allocated_units"] == 0
        assert created["planned_route_stop_id"] is None
        assert created["alert_level"] == "NONE"
        assert created["promo_suppressed"] is False
        assert created["alert_acknowledged_by_user_id"] is None

    def test_a_sanitation_task_starts_scheduled_with_no_breach_recorded(self, api):
        """PRD §3.5: "Creation answers 201 with `status` `SCHEDULED`, `breach_kind`
        null, `completed_at`, `completed_by_user_id`, `calibration_outcome`,
        `waiver_reason` and `waived_by_user_id` all null, and `version` 1."

        Design: Corner/entities/maintenance_task_creation_defaults_scheduled_with_null_breach_kind
        """
        outlet, agreement, unit, _item = _outlet_with_unit(api)
        validate_success(api.activate_agreement(agreement["id"], ADMIN))

        created = validate_success(
            api.create_maintenance_task(
                create_maintenance_task_payload(
                    unit["id"], "SANITATION", "2026-08-15T00:00:00Z"
                ),
                OFFICER,
            ),
            201,
        )
        assert created["status"] == "SCHEDULED"
        assert created["breach_kind"] is None
        assert created["effective_gallon_interval"] is None
        assert created["calibration_outcome"] is None
        assert created["version"] == 1
        assert validate_success(api.get_outlet(outlet["id"], ADMIN))["overdue_task_count"] == 0


class TestCrossReferenceIntegrity:
    def test_a_unit_cannot_be_placed_under_another_outlets_agreement(self, api):
        """PRD §3.3: "the submitted `outlet_id` must match the `outlet_id` recorded on
        the submitted agreement, with `ERR_OUTLET_AGREEMENT_MISMATCH` when the two
        disagree."

        Design: Corner/entities/outlet_agreement_mismatch_on_dispenser_unit_create
        """
        pin_clock()
        first = validate_success(
            api.create_outlet(
                create_outlet_payload(
                    name="Riverside Diner", account_code="OUT-1001",
                    region_code="R-WEST",
                ),
                ADMIN,
            ),
            201,
        )
        second = validate_success(
            api.create_outlet(
                create_outlet_payload(
                    name="Corner Deli", account_code="OUT-1002", region_code="R-WEST"
                ),
                ADMIN,
            ),
            201,
        )
        agreement = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    first["id"], first["version"],
                    annual_commitment_gallons=8000, equipment_value_cents=480000,
                ),
                ADMIN,
            ),
            201,
        )

        response = api.create_dispenser_unit(
            create_dispenser_unit_payload(
                second["id"], agreement["id"], serial_number="SN-9001",
                installed_at="2025-11-01T00:00:00Z",
            ),
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_OUTLET_AGREEMENT_MISMATCH.value, 422)

        _rows, meta = validate_paginated(
            api.list_dispenser_units(ADMIN, {"agreement_id": agreement["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_stop_outside_the_depot_region_is_refused(self, api):
        """PRD §3.7: "The visited outlet's `region_code` must equal the route's
        `depot_region_code`, a mismatch being `ERR_REGION_MISMATCH` — a van out of the
        wrong depot is never dispatched to an outlet it does not serve."

        Design: Corner/entities/region_mismatch_between_stop_outlet_and_route_depot
        """
        pin_clock()
        outlet = validate_success(
            api.create_outlet(
                create_outlet_payload(
                    name="Harbor Cafe", account_code="OUT-1003", region_code="R-EAST"
                ),
                ADMIN,
            ),
            201,
        )
        route = validate_success(
            api.create_route(
                create_route_payload(
                    route_code="RT-01", depot_region_code="R-WEST",
                    service_date="2026-08-03T00:00:00Z", van_code="VAN-7",
                    capacity_units=60,
                ),
                PLANNER,
            ),
            201,
        )

        response = api.create_route_stop(
            route["id"],
            create_route_stop_payload(
                outlet["id"], route["version"], 1,
                "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z",
            ),
            PLANNER,
        )
        validate_error(response, ApiErrorId.ERR_REGION_MISMATCH.value, 422)

        assert read_route(route["id"])["version"] == 1
        _rows, meta = validate_paginated(
            api.list_route_stops(PLANNER, {"route_id": route["id"]})
        )
        assert meta["total_count"] == 0

    def test_stops_are_reverse_reachable_from_their_own_route(self, api):
        """PRD §3.7: "Stops can be listed filtered by `route_id`, by `outlet_id` and
        by `status`."

        Design: Corner/entities/route_stop_reverse_lookup_by_route_id_returns_child_rows
        """
        first, second, _third = _three_outlets(api)
        route = validate_success(
            api.create_route(
                create_route_payload(
                    route_code="RT-01", depot_region_code="R-WEST",
                    service_date="2026-08-03T00:00:00Z", van_code="VAN-7",
                    capacity_units=60,
                ),
                PLANNER,
            ),
            201,
        )
        stop_one = validate_success(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(
                    first["id"], route["version"], 1,
                    "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z",
                ),
                PLANNER,
            ),
            201,
        )
        stop_two = validate_success(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(
                    second["id"], read_route(route["id"])["version"], 2,
                    "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z",
                ),
                PLANNER,
            ),
            201,
        )
        other_route = validate_success(
            api.create_route(
                create_route_payload(
                    route_code="RT-02", depot_region_code="R-WEST",
                    service_date="2026-08-04T00:00:00Z", van_code="VAN-8",
                    capacity_units=60,
                ),
                PLANNER,
            ),
            201,
        )
        foreign_stop = validate_success(
            api.create_route_stop(
                other_route["id"],
                create_route_stop_payload(
                    first["id"], other_route["version"], 1,
                    "2026-08-04T09:00:00Z", "2026-08-04T10:00:00Z",
                ),
                PLANNER,
            ),
            201,
        )

        rows, meta = validate_paginated(
            api.list_route_stops(PLANNER, {"route_id": route["id"]})
        )
        assert {row["id"] for row in rows} == {stop_one["id"], stop_two["id"]}
        assert meta["total_count"] == 2
        assert foreign_stop["id"] not in {row["id"] for row in rows}
        assert rows[0]["status"] == "PENDING"
        assert rows[0]["delivered_units"] == 0
