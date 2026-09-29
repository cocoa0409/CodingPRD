"""Creation contracts: server-owned defaults, required inputs, derived reads.

Covers what a caller may and may not supply on a create, what the server stamps
on its own authority, and the two existence checks that fire before any
business rule.
"""

import pytest
from test_helpers import (
    ADMIN,
    ANALYST,
    ERR_COUNTERPARTY_NOT_FOUND,
    ERR_DUPLICATE_STATION_CODE,
    ERR_INVALID_REQUEST,
    ERR_PROGRAM_NOT_FOUND,
    OPS,
    TREASURY,
    assert_identity_fields,
    assert_immutable_audit_record,
    assert_millisecond_timestamp,
    assert_money,
    assert_pagination_meta,
    assert_pct,
    assert_program_coverage,
    assert_ratio,
    assert_request_meta,
    assert_station_supply,
    factories as f,
    fixtures as fx,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The corner baseline policy: a wide-open concentration cap and a generous
#: volatility limit, so only the rule under test can bite.
CORNER_POLICY = dict(
    policy_code="FY27-CORNER",
    min_coverage_pct=5.00,
    max_single_counterparty_pct=100.00,
    max_earnings_volatility_usd=500000.00,
)

#: A well-formed UUID that names nothing.
UNKNOWN_UUID = "6f1a5c92-0b3d-4c77-9f21-8ad4e2b70c11"
UNKNOWN_COUNTERPARTY_UUID = "9c2b7d41-5e6f-4a08-b3c9-7d1e0f2a5b64"


class TestHedgePolicyCreation:
    def test_new_policy_is_active_with_no_open_exceptions_at_version_one(self, api):
        """PRD §2.9: "the new row is created `ACTIVE` with `open_exception_count`
        at 0."

        PRD §2.4: "a `version` integer that starts at 1 on creation and
        increments by exactly one on every mutation the server applies to that
        row."

        Design: Corner/entities/hedge_policy_create_returns_201_with_system_defaults
        """
        response = api.create_hedge_policy(
            f.hedge_policy_payload(
                **CORNER_POLICY,
                max_coverage_pct=60.00,
                max_tankering_uplift_gallons=12000,
                min_days_cover=3.00,
            ),
            headers=ADMIN,
        )
        data = validate_success(response, 201)

        assert data["status"] == "ACTIVE"
        assert data["open_exception_count"] == 0
        assert data["version"] == 1
        assert_pct(data["max_coverage_pct"], 60.00, "max_coverage_pct")
        assert_pct(data["min_coverage_pct"], 5.00, "min_coverage_pct")
        assert_pct(
            data["max_single_counterparty_pct"], 100.00, "max_single_counterparty_pct"
        )
        assert data["permitted_instrument_types"] == ["SWAP", "COLLAR", "CALL_OPTION"]
        assert data["eligible_fleet_types"] == ["NARROWBODY", "WIDEBODY", "REGIONAL"]

    def test_new_policy_identity_is_a_bare_uuid_with_millisecond_stamps(self, api):
        """PRD §2.4: "Every resource carries an `id`, which is a server-minted
        UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC
        form with three fractional digits."

        Design: Corner/entities/hedge_policy_create_returns_201_with_system_defaults
        """
        data = validate_success(
            api.create_hedge_policy(
                f.hedge_policy_payload(**CORNER_POLICY), headers=ADMIN
            ),
            201,
        )

        assert is_valid_uuid(data["id"]), f"id carries a type prefix: {data['id']!r}"
        assert_millisecond_timestamp(data["created_at"], "created_at")
        assert_millisecond_timestamp(data["updated_at"], "updated_at")


class TestStationCreation:
    def test_station_without_the_days_cover_denominator_is_rejected(self, api):
        """PRD §3.2: "an `avg_daily_liftings_gallons` strictly greater than zero
        which serves as the denominator for days of cover."

        PRD §2.5: "**Request shape.** On every write endpoint: every required input
        field present, every type correct, every enumeration member recognised, every
        numeric constraint honoured, the conditional strike fields consistent with
        the declared instrument type, and any required version-pinning field present.
        Otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/station_create_missing_required_avg_daily_liftings_returns_400
        """
        response = api.create_station(
            {
                "iata_code": "MEM",
                "name": "Memphis International",
                "into_plane_fee_usd_per_gal": 0.0500,
            },
            headers=ADMIN,
        )
        validate_error(response, ERR_INVALID_REQUEST, 400)

    def test_rejected_station_create_persists_no_row_to_collide_with(self, api):
        """PRD §2.5: "`policy_code`, `counterparty_code`, `iata_code`,
        `program_code`, a mark-to-market run's `period_month`, and the pair of
        `flight_number` with `departure_date` are each unique across the whole
        system".

        A repeat of the same `iata_code` is `ERR_DUPLICATE_STATION_CODE`, so a
        clean create after the rejected one proves the rejected request minted
        no row.

        Design: Corner/entities/station_create_missing_required_avg_daily_liftings_returns_400
        """
        validate_error(
            api.create_station(
                {
                    "iata_code": "MEM",
                    "name": "Memphis International",
                    "into_plane_fee_usd_per_gal": 0.0500,
                },
                headers=ADMIN,
            ),
            ERR_INVALID_REQUEST,
            400,
        )

        complete = f.station_payload(
            iata_code="MEM",
            name="Memphis International",
            into_plane_fee_usd_per_gal=0.0500,
            avg_daily_liftings_gallons=100000,
        )
        validate_success(api.create_station(complete, headers=ADMIN), 201)

        # Only now does the code collide.
        validate_error(
            api.create_station(complete, headers=ADMIN), ERR_DUPLICATE_STATION_CODE, 409
        )

    def test_station_omitting_consortium_inputs_is_born_short_with_zero_stock(self, api):
        """PRD §3.2: "`consortium_member` defaults to false,
        `consortium_share_pct` (between 0 and 100 inclusive, two decimal places)
        defaults to 0, and `consortium_pool_gallons` (at least zero) defaults to
        0."

        PRD §3.2: "A new station starts with `inventory_gallons` at 0, and its
        supply posture is computed immediately on creation." With a `days_cover`
        of 0.00 against a `min_days_cover` of 3.00, "below that minimum the
        station is `SHORT`".

        Design: Corner/entities/station_create_applies_consortium_and_inventory_defaults
        """
        fx.do_create_policy(api, **CORNER_POLICY, min_days_cover=3.00)

        data = validate_success(
            api.create_station(
                f.station_payload(
                    iata_code="MEM",
                    name="Memphis International",
                    into_plane_fee_usd_per_gal=0.0500,
                    avg_daily_liftings_gallons=100000,
                ),
                headers=ADMIN,
            ),
            201,
        )

        assert data["consortium_member"] is False
        assert_money(data["consortium_share_pct"], 0, "consortium_share_pct")
        assert_money(data["consortium_pool_gallons"], 0, "consortium_pool_gallons")
        assert_station_supply(
            data,
            inventory_gallons=0,
            effective_inventory_gallons=0,
            days_cover=0.00,
            supply_posture="SHORT",
        )
        assert data["version"] == 1


class TestFlightLegUpliftCap:
    def test_each_of_the_three_headroom_terms_can_be_the_binding_one(self, api):
        """PRD §3.8: "the server derives `uplift_cap_gallons`, the maximum
        gallons this leg may ever tanker, as the smallest of three headrooms.
        Tank headroom is `tank_capacity_gallons` less `planned_burn_gallons` less
        a fixed 900-gallon reserve that is never available for tankering. Weight
        headroom is `max_landing_weight_lbs` less `landing_weight_lbs`,
        converted from pounds to gallons by dividing by 6.7 pounds per gallon.
        The third term is the `max_tankering_uplift_gallons` of the single
        `ACTIVE` hedging policy".

        Design: Corner/entities/flight_leg_uplift_cap_binding_term_differs_across_three_legs
        """
        fx.do_create_policy(api, **CORNER_POLICY, max_tankering_uplift_gallons=12000)
        dfw = fx.do_create_station(
            api,
            iata_code="DFW",
            name="Dallas Fort Worth",
            into_plane_fee_usd_per_gal=0.0450,
            avg_daily_liftings_gallons=100000,
        )
        ord_station = fx.do_create_station(
            api,
            iata_code="ORD",
            name="Chicago OHare",
            into_plane_fee_usd_per_gal=0.0800,
            avg_daily_liftings_gallons=80000,
        )

        # Tank headroom binds: 26500 - 15000 - 900 = 10600.00, under both the
        # 11194.03 weight headroom and the 12000 policy ceiling.
        leg_a = fx.do_create_leg(
            api,
            dfw["id"],
            ord_station["id"],
            flight_number="FA100",
            departure_date="2027-02-10",
            planned_block_minutes=210,
            planned_burn_gallons=15000,
            tank_capacity_gallons=26500,
            payload_lbs=22000,
            max_takeoff_payload_lbs=45000,
            landing_weight_lbs=130000,
            max_landing_weight_lbs=205000,
        )
        # Landing-weight headroom binds: (145000 - 128000) / 6.7 = 2537.31.
        leg_b = fx.do_create_leg(
            api,
            dfw["id"],
            ord_station["id"],
            flight_number="FB200",
            departure_date="2027-02-10",
            planned_block_minutes=210,
            planned_burn_gallons=15000,
            tank_capacity_gallons=26500,
            payload_lbs=22000,
            max_takeoff_payload_lbs=45000,
            landing_weight_lbs=128000,
            max_landing_weight_lbs=145000,
        )
        # The policy ceiling binds: 19100 tank headroom, 14925.37 weight headroom.
        leg_c = fx.do_create_leg(
            api,
            dfw["id"],
            ord_station["id"],
            flight_number="FC300",
            departure_date="2027-02-10",
            fleet_type="WIDEBODY",
            planned_block_minutes=400,
            planned_burn_gallons=20000,
            tank_capacity_gallons=40000,
            payload_lbs=60000,
            max_takeoff_payload_lbs=120000,
            landing_weight_lbs=100000,
            max_landing_weight_lbs=200000,
        )

        read_a = validate_success(api.get_flight_leg(leg_a["id"], headers=OPS))
        read_b = validate_success(api.get_flight_leg(leg_b["id"], headers=OPS))
        read_c = validate_success(api.get_flight_leg(leg_c["id"], headers=OPS))

        assert_money(read_a["uplift_cap_gallons"], 10600.00, "FA100 uplift_cap_gallons")
        assert_money(read_b["uplift_cap_gallons"], 2537.31, "FB200 uplift_cap_gallons")
        assert_money(read_c["uplift_cap_gallons"], 12000.00, "FC300 uplift_cap_gallons")

    def test_a_leg_reports_no_flown_data_before_reconciliation(self, api):
        """PRD §3.8: "A new leg has `actual_block_minutes` and
        `actual_uplift_gallons` null until it is reconciled."

        Design: Corner/entities/flight_leg_uplift_cap_binding_term_differs_across_three_legs
        """
        fx.do_create_policy(api, **CORNER_POLICY, max_tankering_uplift_gallons=12000)
        dfw = fx.do_create_station(
            api, iata_code="DFW", name="Dallas Fort Worth", avg_daily_liftings_gallons=100000
        )
        ord_station = fx.do_create_station(
            api, iata_code="ORD", name="Chicago OHare", avg_daily_liftings_gallons=80000
        )
        leg = fx.do_create_leg(
            api,
            dfw["id"],
            ord_station["id"],
            flight_number="FA100",
            departure_date="2027-02-10",
        )

        data = validate_success(api.get_flight_leg(leg["id"], headers=OPS))
        assert data["actual_block_minutes"] is None
        assert data["actual_uplift_gallons"] is None


class TestExistenceChecks:
    def test_unknown_programme_on_the_path_is_a_not_found_error(self, api):
        """PRD §2.5: "Every resource named by a path segment must exist; the
        first segment that does not resolve determines the error, which is one of
        `ERR_POLICY_NOT_FOUND`, `ERR_COUNTERPARTY_NOT_FOUND`,
        `ERR_STATION_NOT_FOUND`, `ERR_FORECAST_NOT_FOUND`,
        `ERR_PROGRAM_NOT_FOUND`".

        Design: Corner/entities/get_hedge_program_unknown_id_returns_404
        """
        response = api.get_hedge_program(UNKNOWN_UUID, headers=ANALYST)
        validate_error(response, ERR_PROGRAM_NOT_FOUND, 404)

        body = response.json()
        assert body["response_type"] == "error"
        assert_request_meta(body)

    def test_unknown_counterparty_in_the_body_leaves_the_programme_untouched(self, api):
        """PRD §2.5: "Every identifier supplied in a request body — `policy_id`,
        `counterparty_id`, `hedge_instrument_id`, `origin_station_id`,
        `destination_station_id`, `hedge_program_id` or
        `tankering_directive_id` — must resolve to an existing row".

        The path programme resolves, so the body foreign key is what fails; and
        because the failure precedes every cascade, PRD §3.4's "increments the
        parent programme's `open_instrument_count` by one" never runs.

        Design: Corner/entities/instrument_create_unknown_counterparty_id_returns_404
        """
        ctx = fx.setup_single_forecast_sized_program(
            api,
            policy_overrides=CORNER_POLICY,
            program_overrides=dict(
                program_code="HP-CORNER",
                route_groups=["DOMESTIC_SHORT"],
                target_coverage_pct=30.00,
            ),
        )
        program = ctx["program"]
        assert program["version"] == 2

        response = api.create_hedge_instrument(
            program["id"],
            f.swap_payload(
                UNKNOWN_COUNTERPARTY_UUID,
                program["version"],
                notional_gallons=1000000,
                strike_usd_per_gal=2.5000,
            ),
            headers=ANALYST,
        )
        validate_error(response, ERR_COUNTERPARTY_NOT_FOUND, 404)

        after = fx.read_program(api, program["id"])
        assert after["version"] == 2
        assert_program_coverage(
            after,
            consumption_basis_gallons=fx.SINGLE_FORECAST_BASIS_GALLONS,
            open_instrument_count=0,
            planned_coverage_pct_delta=0.00,
        )


class TestForecastCreationAndListing:
    def test_season_outside_the_enumeration_is_rejected(self, api):
        """PRD §3.3: "A `FuelAnalyst` records a consumption forecast naming a
        `fleet_type` of `NARROWBODY`, `WIDEBODY` or `REGIONAL`, a `route_group` of
        `DOMESTIC_SHORT`, `DOMESTIC_LONG`, `TRANSATLANTIC`, `TRANSPACIFIC` or
        `LATAM`, and a `season` of `WINTER`, `SPRING`, `SUMMER` or `FALL`."

        An unrecognised enumeration member is a request-shape failure, and the
        request-shape rung answers with `ERR_INVALID_REQUEST` (400).

        Design: Corner/entities/forecast_create_invalid_enum_season_returns_400
        """
        response = api.create_consumption_forecast(
            f.consumption_forecast_payload(season="MONSOON"), headers=ANALYST
        )
        validate_error(response, ERR_INVALID_REQUEST, 400)

    def test_status_filter_narrows_total_count_before_the_page_window_applies(self, api):
        """PRD §2.3: "`limit` caps the number of items returned; it defaults to
        10, may not be lower than 1, and may not be higher than 100." Both are
        "echoed back in the `meta` object of the envelope alongside
        `total_count` (the number of items matching the query before pagination)
        and `has_more` (true when items remain beyond the current window)."

        PRD §2.3: "consumption forecasts are ordered by `period_start_month`
        ascending and then `created_at` ascending".

        Design: Corner/entities/consumption_forecast_list_filters_then_paginates
        """
        f1 = fx.do_create_forecast(
            api,
            fleet_type="NARROWBODY",
            route_group="DOMESTIC_SHORT",
            season="SUMMER",
            forecast_gallons=4000000,
        )
        f2 = fx.do_create_forecast(
            api,
            fleet_type="WIDEBODY",
            route_group="TRANSATLANTIC",
            season="SUMMER",
            forecast_gallons=3000000,
        )
        fx.do_create_forecast(
            api,
            fleet_type="NARROWBODY",
            route_group="DOMESTIC_SHORT",
            season="WINTER",
            forecast_gallons=1000000,
        )
        fx.do_create_forecast(
            api,
            fleet_type="REGIONAL",
            route_group="DOMESTIC_LONG",
            season="FALL",
            period_start_month="2027-05",
            period_end_month="2027-08",
            forecast_gallons=500000,
        )
        fx.do_create_forecast(
            api,
            fleet_type="WIDEBODY",
            route_group="TRANSPACIFIC",
            season="SPRING",
            period_start_month="2027-03",
            period_end_month="2027-06",
            forecast_gallons=2000000,
        )
        fx.do_publish_forecast(api, f1["id"])
        fx.do_publish_forecast(api, f2["id"])

        response = api.list_consumption_forecasts(
            headers=TREASURY, params={"status": "PUBLISHED", "limit": 1, "offset": 1}
        )
        rows, meta = validate_paginated(response)

        assert response.json()["response_type"] == "array"
        assert len(rows) == 1
        assert_pagination_meta(meta, total_count=2, limit=1, offset=1, has_more=False)
        assert rows[0]["fleet_type"] == "WIDEBODY"
        assert rows[0]["route_group"] == "TRANSATLANTIC"
        assert rows[0]["status"] == "PUBLISHED"

    def test_fleet_type_filter_spans_both_forecast_statuses_at_default_paging(self, api):
        """PRD §2.3: "The forecast list accepts `status`, `fleet_type`,
        `route_group` and `season`." The filters are independent equality
        filters, so a `fleet_type` filter returns DRAFT and PUBLISHED rows alike
        under the default window — `limit` "defaults to 10" and `offset`
        "defaults to 0".

        Design: Corner/entities/consumption_forecast_list_filters_then_paginates
        """
        f1 = fx.do_create_forecast(
            api, fleet_type="NARROWBODY", route_group="DOMESTIC_SHORT", season="SUMMER"
        )
        fx.do_create_forecast(
            api,
            fleet_type="NARROWBODY",
            route_group="DOMESTIC_SHORT",
            season="WINTER",
            forecast_gallons=1000000,
        )
        fx.do_create_forecast(
            api,
            fleet_type="REGIONAL",
            route_group="DOMESTIC_LONG",
            season="FALL",
            period_start_month="2027-05",
            period_end_month="2027-08",
            forecast_gallons=500000,
        )
        fx.do_publish_forecast(api, f1["id"])

        rows, meta = validate_paginated(
            api.list_consumption_forecasts(
                headers=TREASURY, params={"fleet_type": "NARROWBODY"}
            )
        )

        assert len(rows) == 2
        assert_pagination_meta(meta, total_count=2, limit=10, offset=0, has_more=False)
        assert [row["status"] for row in rows] == ["PUBLISHED", "DRAFT"]


class TestEffectivenessTestImmutability:
    def test_effectiveness_test_row_carries_no_updated_at_and_no_version(self, api):
        """PRD §2.4: "An `EffectivenessTest` carries only `id` and `created_at`;
        it has neither `updated_at` nor `version`, and the server never rewrites
        one once it has been created."

        PRD §3.6: "The test records `tested_by_user_id` from the caller's
        `X-User-ID`."

        Design: Corner/entities/effectiveness_test_row_is_immutable_and_carries_no_version
        """
        ctx = fx.setup_active_program_with_executed_swap(
            api,
            single_forecast=True,
            policy_overrides=CORNER_POLICY,
            counterparty_overrides=dict(
                counterparty_code="DLRC",
                legal_name="Dealer C Bank NA",
                credit_rating="A",
            ),
            program_overrides=dict(
                program_code="HP-CORNER",
                route_groups=["DOMESTIC_SHORT"],
                target_coverage_pct=30.00,
            ),
            swap_overrides=dict(
                notional_gallons=1000000,
                strike_usd_per_gal=2.5000,
                maturity_month="2027-03",
            ),
        )
        instrument_id = ctx["instrument"]["id"]
        fx.do_designate_instrument(api, instrument_id)

        data = validate_success(
            api.create_effectiveness_test(
                instrument_id,
                f.effectiveness_test_payload("2027-02", -120000.00, 100000.00),
                headers=fx.ACCOUNTANT,
            ),
            201,
        )

        assert_ratio(data["period_ratio"], 1.2000, "period_ratio")
        assert_ratio(data["cumulative_ratio"], 1.2000, "cumulative_ratio")
        assert data["result"] == "PASS"
        assert data["hedge_instrument_id"] == instrument_id
        assert data["tested_by_user_id"] == "u_acct_1"
        assert_immutable_audit_record(data, "effectiveness test")

    def test_a_filed_test_is_readable_back_as_append_only_evidence(self, api):
        """PRD §2.4: "The single exception is the effectiveness test, which is an
        immutable audit record."

        PRD §2.3: "The effectiveness-test list accepts `result`."

        Design: Corner/entities/effectiveness_test_row_is_immutable_and_carries_no_version
        """
        ctx = fx.setup_active_program_with_executed_swap(
            api,
            single_forecast=True,
            policy_overrides=CORNER_POLICY,
            program_overrides=dict(
                program_code="HP-CORNER",
                route_groups=["DOMESTIC_SHORT"],
                target_coverage_pct=30.00,
            ),
            swap_overrides=dict(
                notional_gallons=1000000,
                strike_usd_per_gal=2.5000,
                maturity_month="2027-03",
            ),
        )
        instrument_id = ctx["instrument"]["id"]
        fx.do_designate_instrument(api, instrument_id)

        filed = fx.do_file_effectiveness_test(
            api, instrument_id, "2027-02", -120000.00, 100000.00
        )

        rows, meta = validate_paginated(
            api.list_effectiveness_tests(
                instrument_id, headers=fx.ACCOUNTANT, params={"result": "PASS"}
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert rows[0]["created_at"] == filed["created_at"]
        assert_identity_fields(rows[0], "effectiveness test")
