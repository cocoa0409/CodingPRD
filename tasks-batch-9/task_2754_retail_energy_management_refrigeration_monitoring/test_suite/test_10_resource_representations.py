"""Resource representations: fields, defaults, ownership and path resolution."""
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as a, factories as f, fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import STORE_DEFAULTS
from test_helpers.test_users import make_store_manager_headers

FULLY_SPECIFIED_STORE = {
    "code": "STR-C1",
    "climate_zone": "MIXED",
    "store_format": "SUPERCENTER",
    "floor_area_sqft": 120000,
    "blended_rate_usd_per_kwh": 0.1250,
    "override_budget_kwh_month": 800.00,
    "lighting_on_time_local": "06:00",
    "lighting_off_time_local": "22:30",
    "daylight_harvest_enabled": False,
    "occupancy_control_enabled": False,
}


class TestStoreRepresentation:
    def test_creation_echoes_every_supplied_input(self, api):
        """All ten inputs come back at the values sent.

        The PRD states: "Four further inputs are optional and carry declared
        defaults: `blended_rate_usd_per_kwh`, a positive rate carried to four
        decimal places and defaulting to 0.11, which is how kilowatt-hour savings
        become dollars; `override_budget_kwh_month`, a non-negative allowance at
        two decimal places defaulting to 500.00 kWh; and the lighting schedule pair
        `lighting_on_time_local` and `lighting_off_time_local`, local
        twenty-four-hour times of day defaulting to `05:30` and `23:00`
        respectively."

        Design: Corner/entities/store_creation_returns_full_declared_representation
        """
        fx.set_clock(api)

        response = api.create_store(dict(FULLY_SPECIFIED_STORE), fx.ADMIN)
        store = validate_success(response, 201)

        a.assert_store(store)
        assert store["code"] == "STR-C1"
        assert store["climate_zone"] == "MIXED"
        assert store["store_format"] == "SUPERCENTER"
        assert store["floor_area_sqft"] == 120000
        assert store["blended_rate_usd_per_kwh"] == pytest.approx(0.1250, abs=0.0001)
        assert store["override_budget_kwh_month"] == pytest.approx(800.00, abs=0.01)
        assert store["lighting_on_time_local"] == "06:00"
        assert store["lighting_off_time_local"] == "22:30"
        assert store["daylight_harvest_enabled"] is False
        assert store["occupancy_control_enabled"] is False

    def test_creation_reports_every_derived_field_at_its_zero_point(self, api):
        """A freshly registered store has nothing deployed and nothing derived.

        The PRD states: "A freshly registered store has nothing deployed. Its
        `bms_status` is `NOT_DEPLOYED`, its `active_standard_id` is null, its
        `energy_posture` is `NORMAL` and its `version` is 1. Every derived quantity
        starts at its zero point: `override_kwh_used_month` and
        `verified_savings_kwh_ytd` are 0.00, `alarm_case_count` and
        `urgent_work_order_count` are 0, `eui_kbtu_per_sqft` and
        `benchmark_percentile` are null, `benchmark_outlier_flag` is false, and
        `portfolio_realization_rate` sits at its portfolio default of 0.8500
        because the store has no measured project yet."

        Design: Corner/entities/store_creation_returns_full_declared_representation
        """
        fx.set_clock(api)

        store = validate_success(api.create_store(dict(FULLY_SPECIFIED_STORE), fx.ADMIN), 201)

        assert store["bms_status"] == "NOT_DEPLOYED"
        assert store["active_standard_id"] is None
        assert store["energy_posture"] == "NORMAL"
        assert store["override_kwh_used_month"] == pytest.approx(0.00, abs=0.01)
        assert store["verified_savings_kwh_ytd"] == pytest.approx(0.00, abs=0.01)
        assert store["alarm_case_count"] == 0
        assert store["urgent_work_order_count"] == 0
        assert store["eui_kbtu_per_sqft"] is None
        assert store["benchmark_percentile"] is None
        assert store["benchmark_outlier_flag"] is False
        assert store["portfolio_realization_rate"] == pytest.approx(0.8500, abs=0.0001)
        assert store["version"] == 1
        assert store["created_at"].startswith("2026-08-01T00:00:00")
        assert store["updated_at"] == store["created_at"]

    def test_omitted_optional_inputs_fall_back_to_their_declared_defaults(self, api):
        """Absent booleans default to true, not to false.

        The PRD states: "Two boolean control flags, `daylight_harvest_enabled` and
        `occupancy_control_enabled`, both default to true."

        Design: Corner/entities/store_defaults_applied_when_optional_inputs_omitted
        """
        fx.set_clock(api)

        store = validate_success(
            api.create_store(
                {
                    "code": "STR-C2", "climate_zone": "COLD",
                    "store_format": "EXPRESS", "floor_area_sqft": 18000,
                },
                fx.ADMIN,
            ),
            201,
        )

        assert store["blended_rate_usd_per_kwh"] == pytest.approx(
            STORE_DEFAULTS["blended_rate_usd_per_kwh"], abs=0.0001
        )
        assert store["override_budget_kwh_month"] == pytest.approx(500.00, abs=0.01)
        assert store["lighting_on_time_local"] == "05:30"
        assert store["lighting_off_time_local"] == "23:00"
        assert store["daylight_harvest_enabled"] is True
        assert store["occupancy_control_enabled"] is True
        assert store["portfolio_realization_rate"] == pytest.approx(0.8500, abs=0.0001)
        assert store["bms_status"] == "NOT_DEPLOYED"
        assert store["version"] == 1


class TestStoreSystemFieldsAreServerOwned:
    def test_client_supplied_system_keys_are_ignored_at_creation(self, api):
        """An injected bms_status, id and version make no difference.

        The PRD states: "Every persisted resource is identified by `id`, a
        server-minted UUID carrying no type prefix — clients never supply it."

        Design: Corner/entities/store_system_fields_are_server_owned_and_advance_on_write
        """
        fx.set_clock(api)

        store = validate_success(
            api.create_store(
                {
                    "code": "STR-C3B", "climate_zone": "MIXED",
                    "store_format": "SUPERCENTER", "floor_area_sqft": 120000,
                    "id": "str_injected", "version": 9, "bms_status": "ACTIVE",
                    "active_standard_id": "std_injected",
                    "created_at": "2020-01-01T00:00:00Z",
                },
                fx.ADMIN,
            ),
            201,
        )

        a.assert_id_has_no_prefix(store["id"])
        assert store["id"] != "str_injected"
        assert store["bms_status"] == "NOT_DEPLOYED"
        assert store["active_standard_id"] is None
        assert store["version"] == 1
        assert store["created_at"].startswith("2026-08-01T00:00:00")

    def test_the_version_advances_only_through_declared_transitions(self, api):
        """Commissioning takes version 1 to 2 and activation 2 to 3.

        The PRD states: "`version`, an integer that begins at 1 when the row is
        created and increases by exactly 1 on every mutation of that row.
        `updated_at` is refreshed to the current logical clock on every mutation."

        Design: Corner/entities/store_system_fields_are_server_owned_and_advance_on_write
        """
        fx.set_clock(api)
        store = fx.create_store(
            api, code="STR-C3", climate_zone="MIXED", store_format="SUPERCENTER",
            floor_area_sqft=120000,
        )
        standard = fx.create_published_standard(
            api, climate_zone="MIXED", store_format="SUPERCENTER",
        )
        assert store["bms_status"] == "NOT_DEPLOYED"
        assert store["active_standard_id"] is None
        assert store["version"] == 1

        fx.set_clock(api, "2026-08-02T00:00:00Z")
        commissioned = fx.commission_store(
            api, store["id"], standard["id"], store["version"]
        )
        activated = fx.activate_store_bms(api, store["id"])

        assert commissioned["version"] == 2
        assert commissioned["bms_status"] == "COMMISSIONING"
        assert commissioned["active_standard_id"] == standard["id"]
        assert commissioned["updated_at"].startswith("2026-08-02T00:00:00")
        assert commissioned["created_at"].startswith("2026-08-01T00:00:00")
        assert activated["version"] == 3
        assert activated["bms_status"] == "ACTIVE"
        assert activated["energy_posture"] == "NORMAL"
        assert activated["updated_at"].startswith("2026-08-02T00:00:00")


class TestStoreListingWindow:
    def test_two_filters_are_anded_before_the_page_is_cut(self, api):
        """total_count reports the filtered cardinality, not the table's.

        The PRD states: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count` and `has_more`, where `total_count` is the number of
        rows matching the filters before pagination is applied and `has_more` is
        true when rows remain beyond the current page."

        Design: Corner/entities/store_listing_filters_combine_with_offset_window
        """
        fx.set_clock(api)
        fx.create_store(
            api, code="STR-L1", climate_zone="MIXED", store_format="EXPRESS",
            floor_area_sqft=12000,
        )
        second = fx.create_store(
            api, code="STR-L2", climate_zone="MIXED", store_format="EXPRESS",
            floor_area_sqft=14000,
        )
        fx.create_store(
            api, code="STR-L3", climate_zone="COLD", store_format="EXPRESS",
            floor_area_sqft=16000,
        )

        rows, meta = validate_paginated(
            api.list_stores(
                fx.ANALYST,
                {
                    "climate_zone": "MIXED", "store_format": "EXPRESS",
                    "limit": 1, "offset": 1,
                },
            )
        )

        assert len(rows) == 1
        assert rows[0]["id"] == second["id"]
        assert rows[0]["code"] == "STR-L2"
        assert meta["total_count"] == 2
        assert meta["limit"] == 1
        assert meta["offset"] == 1
        assert meta["has_more"] is False

    def test_an_unfiltered_read_uses_the_declared_pagination_defaults(self, api):
        """limit defaults to 10 and offset to 0.

        The PRD states: "`limit` controls page size: it defaults to 10, may be no
        smaller than 1 and no larger than 100. `offset` controls the starting
        position: it defaults to 0 and may not be negative."

        Design: Corner/entities/store_listing_filters_combine_with_offset_window
        """
        fx.set_clock(api)
        for code, zone in [("STR-L1", "MIXED"), ("STR-L2", "MIXED"), ("STR-L3", "COLD")]:
            fx.create_store(
                api, code=code, climate_zone=zone, store_format="EXPRESS",
                floor_area_sqft=12000,
            )

        rows, meta = fx.list_stores(api, fx.ANALYST)

        assert len(rows) == 3
        assert meta["total_count"] == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False


CASE_R1 = {
    "case_code": "CASE-R1",
    "case_type": "MEDIUM_TEMP",
    "product_class": "DAIRY",
    "alarm_high_f": 41.0,
    "alarm_low_f": 28.0,
    "product_value_usd": 4200.00,
}


class TestRefrigerationCaseRetrieval:
    def test_the_read_back_returns_the_persisted_row_not_the_request_body(self, api):
        """A case read by id carries its declared inputs and its initial monitoring state.

        The PRD states: "A new case is persisted with `monitoring_state` `ARMED`,
        `consecutive_breach_count` 0, and `last_reading_temp_f` and
        `last_reading_iso` both null."

        Design: Corner/entities/refrigeration_case_retrieval_returns_stored_row
        """
        ctx = fx.setup_commissioned_store(api, code="STR-R1")
        created = fx.create_case(api, ctx["store_id"], **CASE_R1)

        read_back = get_success_data(api.get_refrigeration_case(created["id"], fx.OFFICER))

        a.assert_refrigeration_case(read_back)
        assert read_back["id"] == created["id"]
        assert read_back["case_code"] == "CASE-R1"
        assert read_back["case_type"] == "MEDIUM_TEMP"
        assert read_back["product_class"] == "DAIRY"
        assert read_back["alarm_high_f"] == pytest.approx(41.0, abs=0.05)
        assert read_back["alarm_low_f"] == pytest.approx(28.0, abs=0.05)
        assert read_back["product_value_usd"] == pytest.approx(4200.00, abs=0.01)
        assert read_back["monitoring_state"] == "ARMED"
        assert read_back["consecutive_breach_count"] == 0
        assert read_back["last_reading_temp_f"] is None
        assert read_back["last_reading_iso"] is None
        assert read_back["version"] == 1
        assert read_back["created_at"].startswith("2026-08-01T00:00:00")

    def test_the_owning_store_is_taken_from_the_creation_path(self, api):
        """store_id is a system field resolved from the path, never a body field.

        The PRD states: "Cases are registered against a commissioned store by a
        `PlatformAdmin` or an `EnergyManager`."

        Design: Corner/entities/refrigeration_case_retrieval_returns_stored_row
        """
        ctx = fx.setup_commissioned_store(api, code="STR-R1")
        other = fx.create_store(
            api, code="STR-R1-OTHER", climate_zone="COLD", store_format="EXPRESS",
            floor_area_sqft=14000,
        )
        created = validate_success(
            api.create_refrigeration_case(
                ctx["store_id"],
                {**f.create_refrigeration_case_payload(**CASE_R1), "store_id": other["id"]},
                fx.MANAGER,
            ),
            201,
        )

        read_back = get_success_data(api.get_refrigeration_case(created["id"], fx.OFFICER))

        assert read_back["store_id"] == ctx["store_id"]
        assert read_back["store_id"] != other["id"]
        a.assert_id_has_no_prefix(read_back["id"])
        rows, meta = fx.list_cases(api, ctx["store_id"])
        assert meta["total_count"] == 1
        assert rows[0]["id"] == created["id"]


class TestExcursionNotFound:
    def test_an_unknown_excursion_id_is_reported_as_the_excursion_404(self, api):
        """A well-formed but unknown id yields the excursion family's own code.

        The PRD states: "Each entity family has its own not-found code, and when
        several could apply they are evaluated in this fixed order: store,
        setpoint standard, utility account, utility bill, demand-response event,
        refrigeration case, temperature excursion, lighting override, fault
        diagnostic, maintenance work order, retrofit project — yielding
        respectively `ERR_STORE_NOT_FOUND`, `ERR_STANDARD_NOT_FOUND`,
        `ERR_ACCOUNT_NOT_FOUND`, `ERR_BILL_NOT_FOUND`, `ERR_DR_EVENT_NOT_FOUND`,
        `ERR_CASE_NOT_FOUND`, `ERR_EXCURSION_NOT_FOUND`, `ERR_OVERRIDE_NOT_FOUND`,
        `ERR_FAULT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND` and
        `ERR_RETROFIT_NOT_FOUND`. All eleven are HTTP 404."

        Design: Corner/entities/excursion_get_with_unknown_id_returns_not_found
        """
        fx.set_clock(api)

        response = api.get_excursion(NON_EXISTENT_UUID, fx.OFFICER)

        error = validate_error(response, ApiErrorId.ERR_EXCURSION_NOT_FOUND.value, 404)
        body = response.json()
        assert body["response_type"] == "error"
        assert error["error_id"] == "ERR_EXCURSION_NOT_FOUND"
        assert isinstance(error["message"], str) and error["message"].strip()
        a.assert_envelope_meta(body)


ACCOUNT_WITHOUT_OFF_PEAK_RATE = {
    "utility_name": "Statewide Power",
    "rate_schedule_code": "GS-3",
    "rate_family": "TOU_DEMAND",
    "demand_charge_per_kw": 14.50,
    "rate_on_peak": 0.1450,
}


class TestUtilityAccountRequiredRates:
    def test_omitting_the_off_peak_rate_is_rejected_as_an_invalid_request(self, api):
        """rate_off_peak has no default, so its absence is a schema failure.

        The PRD states: "Its price list is `demand_charge_per_kw`, a positive
        amount at two decimal places charged per billable kilowatt, together with
        `rate_on_peak` and `rate_off_peak`, positive per-kilowatt-hour rates at
        four decimal places."

        Design: Corner/entities/utility_account_create_missing_required_rate_rejected
        """
        fx.set_clock(api)
        store = fx.create_store(api, code="STR-RQ")

        response = api.create_utility_account(
            store["id"], ACCOUNT_WITHOUT_OFF_PEAK_RATE, fx.MANAGER
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_the_rejected_create_persists_nothing(self, api):
        """The store's account collection is still empty after the refusal.

        The PRD states: "`total_count` is the number of rows matching the filters
        before pagination is applied and `has_more` is true when rows remain
        beyond the current page."

        Design: Corner/entities/utility_account_create_missing_required_rate_rejected
        """
        fx.set_clock(api)
        store = fx.create_store(api, code="STR-RQ")

        api.create_utility_account(store["id"], ACCOUNT_WITHOUT_OFF_PEAK_RATE, fx.MANAGER)

        rows, meta = fx.list_accounts(api, store["id"])

        assert rows == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

    def test_the_optional_ratchet_and_candidate_inputs_are_not_mandatory(self, api):
        """Supplying only the six required inputs is accepted.

        The PRD states: "`ratchet_peak_kw` records the highest demand billed over
        the trailing eleven months, a non-negative value at one decimal place
        defaulting to 0.0, and feeds the ratchet floor."

        Design: Corner/entities/utility_account_create_missing_required_rate_rejected
        """
        fx.set_clock(api)
        store = fx.create_store(api, code="STR-RQ")

        created = get_success_data(
            api.create_utility_account(
                store["id"],
                {**ACCOUNT_WITHOUT_OFF_PEAK_RATE, "rate_off_peak": 0.0800},
                fx.MANAGER,
            )
        )

        a.assert_utility_account(created)
        assert created["ratchet_peak_kw"] == pytest.approx(0.0, abs=0.05)
        assert created["candidate_rate_schedule_code"] is None
        assert created["candidate_rate_family"] is None
        assert created["candidate_demand_charge_per_kw"] is None
        assert created["candidate_rate_on_peak"] is None
        assert created["candidate_rate_off_peak"] is None
        assert created["tariff_state"] == "STABLE"


STANDARD_SCOPE = {
    "climate_zone": "MIXED",
    "store_format": "SUPERCENTER",
    "cooling_setpoint_f": 74.0,
    "heating_setpoint_f": 68.0,
    "deadband_f": 2.0,
    "lighting_lux_target": 750,
}


class TestSetpointStandardEnumAndRangeConstraints:
    def test_an_undeclared_season_is_rejected(self, api):
        """season admits only SUMMER and WINTER.

        The PRD states: "Drafting a standard fixes its governing scope as a
        triple of `climate_zone`, `store_format` and `season`, where `season` is
        either `SUMMER` or `WINTER`".

        Design: Corner/entities/setpoint_standard_enum_and_range_constraints_rejected
        """
        fx.set_clock(api)

        response = api.create_setpoint_standard(
            {**STANDARD_SCOPE, "season": "SPRING"}, fx.MANAGER
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_a_cooling_setpoint_above_the_declared_ceiling_is_rejected(self, api):
        """85.0 degrees is the top of the admitted cooling range.

        The PRD states: "`cooling_setpoint_f`, which must be at least 60.0 and at
        most 85.0 degrees".

        Design: Corner/entities/setpoint_standard_enum_and_range_constraints_rejected
        """
        fx.set_clock(api)

        response = api.create_setpoint_standard(
            {**STANDARD_SCOPE, "season": "SUMMER", "cooling_setpoint_f": 92.0}, fx.MANAGER
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_equal_heating_and_cooling_setpoints_violate_the_ordering_rule(self, api):
        """Strict ordering refuses equality, and no draft survives the refusals.

        The PRD states: "`heating_setpoint_f`, which must be at least 55.0 and at
        most 78.0 degrees and strictly below the cooling setpoint".

        Design: Corner/entities/setpoint_standard_enum_and_range_constraints_rejected
        """
        fx.set_clock(api)
        api.create_setpoint_standard({**STANDARD_SCOPE, "season": "SPRING"}, fx.MANAGER)
        api.create_setpoint_standard(
            {**STANDARD_SCOPE, "season": "SUMMER", "cooling_setpoint_f": 92.0}, fx.MANAGER
        )

        response = api.create_setpoint_standard(
            {
                **STANDARD_SCOPE,
                "season": "SUMMER",
                "cooling_setpoint_f": 72.0,
                "heating_setpoint_f": 72.0,
            },
            fx.MANAGER,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        rows, meta = fx.list_standards(api)
        assert rows == []
        assert meta["total_count"] == 0


INTERVAL_ISO = "2026-06-15T14:00:00Z"


class TestDemandIntervalImmutability:
    def test_an_interval_row_carries_no_version_and_no_updated_at(self, api):
        """The leaner entity keeps only id and created_at.

        The PRD states: "One entity is deliberately leaner. A metered demand
        interval is an immutable event: it carries only `id` and `created_at`. It
        has no `updated_at` and no `version`, because nothing ever modifies it
        after ingestion."

        Design: Corner/entities/demand_interval_is_an_immutable_event_row
        """
        fx.set_clock(api)
        store = fx.create_store(api, code="STR-IM")
        account = fx.create_account(api, store["id"])

        ingested = fx.ingest_intervals(
            api, account["id"], [f.demand_interval(INTERVAL_ISO, 900.0, True)]
        )

        assert len(ingested) == 1
        row = ingested[0]
        a.assert_demand_interval(row)
        assert "version" not in row
        assert "updated_at" not in row
        assert row["utility_account_id"] == account["id"]
        assert row["interval_start_iso"].startswith("2026-06-15T14:00:00")
        assert row["kw_demand"] == pytest.approx(900.0, abs=0.05)
        assert row["is_on_peak"] is True
        assert row["is_dr_event_day"] is False
        assert row["created_at"].startswith("2026-08-01T00:00:00")

    def test_a_second_post_of_the_same_instant_appends_a_new_row(self, api):
        """Re-ingesting the same instant never edits the earlier row.

        The PRD states: "Accepted intervals are persisted in the order supplied,
        each carrying a `utility_account_id` that points at the account they were
        ingested under and each stamped with `created_at` from the logical clock,
        and each is immutable thereafter — nothing in the API edits or deletes an
        interval."

        Design: Corner/entities/demand_interval_is_an_immutable_event_row
        """
        fx.set_clock(api)
        store = fx.create_store(api, code="STR-IM")
        account = fx.create_account(api, store["id"])
        first = fx.ingest_intervals(
            api, account["id"], [f.demand_interval(INTERVAL_ISO, 900.0, True)]
        )

        second = fx.ingest_intervals(
            api, account["id"], [f.demand_interval(INTERVAL_ISO, 950.0, True)]
        )

        rows, meta = fx.list_intervals(api, account["id"])
        assert second[0]["id"] != first[0]["id"]
        assert meta["total_count"] == 2
        assert len(rows) == 2
        assert rows[0]["kw_demand"] == pytest.approx(900.0, abs=0.05)
        assert rows[1]["kw_demand"] == pytest.approx(950.0, abs=0.05)
        for row in rows:
            assert "version" not in row
            assert "updated_at" not in row
            assert row["is_dr_event_day"] is False


CASE_PR = {
    "case_code": "CASE-PR",
    "case_type": "LOW_TEMP",
    "product_class": "FROZEN",
    "alarm_high_f": 5.0,
    "alarm_low_f": -10.0,
    "product_value_usd": 9000.00,
}


class TestRefrigerationCaseParentResolution:
    def test_an_unknown_store_in_the_path_is_the_stores_own_not_found(self, api):
        """The leftmost unresolvable segment decides the error.

        The PRD states: "Path segments are always resolved left to right, and the
        leftmost unresolvable segment determines the error. A request naming an
        unknown store returns `ERR_STORE_NOT_FOUND` even if the nested identifier
        is also nonsense."

        Design: Corner/entities/refrigeration_case_requires_an_existing_parent_store
        """
        fx.set_clock(api)
        fx.create_store(api, code="STR-PR")

        response = api.create_refrigeration_case(NON_EXISTENT_UUID, CASE_PR, fx.ADMIN)

        validate_error(response, ApiErrorId.ERR_STORE_NOT_FOUND.value, 404)

    def test_existence_outranks_the_commissioning_requirement(self, api):
        """A resolvable but undeployed store is refused for a different reason.

        The PRD states: "Existence of every referenced resource, in the family
        order given in §2.6." at rank four and "Referential business gates —
        `ERR_STANDARD_NOT_PUBLISHED`, then `ERR_STANDARD_SCOPE_MISMATCH`, then
        `ERR_BMS_NOT_COMMISSIONED`, then `ERR_DR_ENROLLMENT_SUSPENDED`, then
        `ERR_TARIFF_SWITCH_IN_PROGRESS`." at rank ten.

        Design: Corner/entities/refrigeration_case_requires_an_existing_parent_store
        """
        fx.set_clock(api)
        deployed_nothing = fx.create_store(api, code="STR-PR")

        unknown = api.create_refrigeration_case(NON_EXISTENT_UUID, CASE_PR, fx.ADMIN)
        undeployed = api.create_refrigeration_case(
            deployed_nothing["id"], CASE_PR, fx.ADMIN
        )

        unknown_error = validate_error(unknown, ApiErrorId.ERR_STORE_NOT_FOUND.value, 404)
        undeployed_error = validate_error(
            undeployed, ApiErrorId.ERR_BMS_NOT_COMMISSIONED.value, 409
        )
        assert unknown_error["error_id"] != undeployed_error["error_id"]
        rows, meta = fx.list_cases(api, deployed_nothing["id"])
        assert rows == []
        assert meta["total_count"] == 0


def _two_populated_stores(api):
    """Stores A and B share one published standard; A carries a case, an account,
    an override and a fault, B carries a case and a retrofit project."""
    fx.set_clock(api, "2026-08-01T12:00:00Z")
    store_a = fx.create_store(api, code="STR-HA", floor_area_sqft=120000)
    store_b = fx.create_store(api, code="STR-HB", floor_area_sqft=110000)
    standard = fx.create_published_standard(
        api, climate_zone="MIXED", store_format="SUPERCENTER",
    )
    for store in (store_a, store_b):
        fx.commission_store(api, store["id"], standard["id"], store["version"])
        fx.activate_store_bms(api, store["id"])
    ctx = {"store_a": store_a["id"], "store_b": store_b["id"]}
    ctx["case_a"] = fx.create_case(
        api, store_a["id"], case_code="CASE-HA", case_type="MEDIUM_TEMP",
        product_class="DAIRY", alarm_high_f=41.0, alarm_low_f=28.0,
        product_value_usd=4200.00,
    )["id"]
    ctx["case_b"] = fx.create_case(
        api, store_b["id"], case_code="CASE-HB", case_type="ICE_CREAM",
        product_class="FROZEN", alarm_high_f=2.0, alarm_low_f=-15.0,
        product_value_usd=7000.00,
    )["id"]
    ctx["account_a"] = fx.create_account(api, store_a["id"])["id"]
    ctx["override_a"] = fx.create_override(
        api, store_a["id"], zone="SALES_FLOOR", override_type="SCHEDULE_EXTEND",
        start_iso="2026-08-01T10:00:00Z", end_iso="2026-08-01T16:00:00Z",
        zone_load_kw=25.0, requested_reason="inventory night",
    )["id"]
    ctx["fault_a"] = fx.create_fault(
        api, store_a["id"], equipment_ref="RTU-1", equipment_class="HVAC",
        fault_code="SAT-DRIFT", severity="MINOR", occurrence_count=2,
        affected_load_kw=30.0,
    )["id"]
    ctx["project_b"] = fx.create_retrofit(
        api, store_b["id"], proposer_user_id="u_analyst_hb",
        measure_type="LED_RETROFIT", capex_usd=260000.00,
        projected_annual_savings_kwh=520000.00,
    )["id"]
    return ctx


class TestHybridTopologyOwnership:
    def test_each_store_collection_returns_only_its_own_children(self, api):
        """Four child families of store A list one row each and none of B's.

        The PRD states: "Several collections are addressed through their parent —
        a store's utility accounts, refrigeration cases, lighting overrides, fault
        diagnostics and retrofit projects; an account's bills, demand intervals and
        demand-response events; a case's excursions; a fault's work orders."

        Design: Corner/entities/hybrid_topology_children_resolve_under_their_own_store_only
        """
        ctx = _two_populated_stores(api)

        cases, cases_meta = fx.list_cases(api, ctx["store_a"])
        accounts, accounts_meta = fx.list_accounts(api, ctx["store_a"])
        overrides, overrides_meta = fx.list_overrides(api, ctx["store_a"])
        faults, faults_meta = fx.list_faults(api, ctx["store_a"])

        assert [row["id"] for row in cases] == [ctx["case_a"]]
        assert cases_meta["total_count"] == 1
        assert [row["id"] for row in accounts] == [ctx["account_a"]]
        assert accounts_meta["total_count"] == 1
        assert [row["id"] for row in overrides] == [ctx["override_a"]]
        assert overrides_meta["total_count"] == 1
        assert [row["id"] for row in faults] == [ctx["fault_a"]]
        assert faults_meta["total_count"] == 1

    def test_a_family_absent_from_one_store_lists_empty_there(self, api):
        """Store A has no retrofit project and store B no override.

        The PRD states: "Once resolution succeeds, the nested identifier must
        genuinely belong to the named parent; a mismatch is treated as
        non-existence of the child."

        Design: Corner/entities/hybrid_topology_children_resolve_under_their_own_store_only
        """
        ctx = _two_populated_stores(api)

        projects_a, projects_a_meta = fx.list_projects(api, ctx["store_a"])
        projects_b, projects_b_meta = fx.list_projects(api, ctx["store_b"])
        overrides_b, overrides_b_meta = fx.list_overrides(api, ctx["store_b"])
        cases_b, cases_b_meta = fx.list_cases(api, ctx["store_b"])

        assert projects_a == []
        assert projects_a_meta["total_count"] == 0
        assert [row["id"] for row in projects_b] == [ctx["project_b"]]
        assert projects_b_meta["total_count"] == 1
        assert overrides_b == []
        assert overrides_b_meta["total_count"] == 0
        assert [row["id"] for row in cases_b] == [ctx["case_b"]]
        assert cases_b_meta["total_count"] == 1

    def test_every_child_row_names_the_store_it_was_created_under(self, api):
        """No child leaks the wrong owner into its representation.

        The PRD states: "A request naming an unknown store returns
        `ERR_STORE_NOT_FOUND` even if the nested identifier is also nonsense."

        Design: Corner/entities/hybrid_topology_children_resolve_under_their_own_store_only
        """
        ctx = _two_populated_stores(api)

        for reader in (fx.list_cases, fx.list_accounts, fx.list_overrides, fx.list_faults):
            rows, _ = reader(api, ctx["store_a"])
            for row in rows:
                assert row["store_id"] == ctx["store_a"]
        for reader in (fx.list_cases, fx.list_projects):
            rows, _ = reader(api, ctx["store_b"])
            for row in rows:
                assert row["store_id"] == ctx["store_b"]

        unknown = api.list_store_refrigeration_cases(NON_EXISTENT_UUID, fx.MANAGER)
        validate_error(unknown, ApiErrorId.ERR_STORE_NOT_FOUND.value, 404)
