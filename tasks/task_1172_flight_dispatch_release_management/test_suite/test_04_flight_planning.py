"""Flight planning: wind variants, fuel computation, alternate selection,
worst-case enforcement, plan OCC, and plan listing (PRD §2.6, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    STANDARD_PLAN,
    TEST_USERS,
    api_client,
    assert_plan,
    create_captain_payload,
    create_dispatcher_payload,
    create_leg_payload,
    create_mel_item_payload,
    create_plan_payload,
    create_station_payload,
    make_captain_headers,
    setup_computed_plan,
    setup_reference_data,
    setup_two_variant_plans,
    add_leg,
    add_plan,
    add_second_leg,
    validate_error,
    validate_paginated,
    validate_success,
)

SUP = TEST_USERS["supervisor_headers"]


class TestWindVariantDivergence:
    def test_forecast_variant_fuel_figures(self, api):
        """PRD §3.3: "Under `FORECAST`, the effective wind component is the
        client-supplied `forecast_wind_kts`." With the standard aircraft (tas
        450, effective burn 2730 kg/h over 5 weight steps) and +30 kt: ground
        speed 480, exact trip 2.5 h * 2730 = 6825, contingency
        max(341.25, 100) -> 341, alternate 90/450*2730 = 546, reserve 1365,
        and "Finally, `required_fuel_kg` is a single round-half-up applied to
        the sum of the penalized exact trip fuel, the exact contingency, the
        exact alternate fuel, and the exact reserve — exactly one rounding at
        the final sum, with no intermediate rounded values feeding it."
        (9077.25 -> 9077).

        Design: Difficulty/dual_variant_calc/trip_fuel_forecast_vs_worst_case_divergence
        """
        ctx = setup_two_variant_plans()
        plan = ctx["plan_forecast"]
        assert_plan(plan)
        assert plan["ground_speed_kts"] == 480
        assert plan["trip_fuel_kg"] == 6825
        assert plan["contingency_kg"] == 341
        assert plan["alternate_fuel_kg"] == 546
        assert plan["final_reserve_kg"] == 1365
        assert plan["required_fuel_kg"] == 9077
        assert plan["alternate_station_id"] == ctx["alt_station"]["id"]

    def test_worst_case_variant_yields_strictly_more_trip_fuel(self, api):
        """PRD §3.3: "Under `WORST_CASE`, the forecast is ignored entirely and a
        50-knot headwind is assumed, so ground speed is the aircraft's
        `cruise_tas_kts` minus 50; for identical legs this yields strictly more
        trip fuel than the forecast variant whenever `forecast_wind_kts` is
        greater than minus 50." (400 kts; trip 3.0 h * 2730 = 8190; required
        rhu(8190 + 409.5 + 546 + 1365) = 10511.)

        Design: Difficulty/dual_variant_calc/trip_fuel_forecast_vs_worst_case_divergence
        """
        ctx = setup_two_variant_plans()
        plan = ctx["plan_worst_case"]
        assert_plan(plan)
        assert plan["ground_speed_kts"] == 400
        assert plan["trip_fuel_kg"] == 8190
        assert plan["required_fuel_kg"] == 10511
        assert plan["alternate_station_id"] == ctx["alt_station"]["id"]
        assert plan["trip_fuel_kg"] > ctx["plan_forecast"]["trip_fuel_kg"]


class TestRequiredFuelCombinatorial:
    def _setup_mel_penalty_plan(self, api):
        """OPEN MEL with fuel_penalty_pct 3 on the aircraft; plan WORST_CASE on
        the standard 1200 NM leg."""
        ctx = setup_reference_data()
        mel = validate_success(
            api.create_mel_item(
                create_mel_item_payload(ctx["aircraft"]["id"], fuel_penalty_pct=3),
                SUP,
            ),
            201,
        )
        ctx["mel"] = mel
        add_leg(ctx, flight_no="FD110", distance_nm=1200)
        add_plan(ctx, wind_assumption="WORST_CASE", forecast_wind_kts=30)
        return ctx

    def test_trip_fuel_and_mel_penalty(self, api):
        """PRD §3.3: "The plan exposes `trip_fuel_kg`, the round-half-up of that
        exact value, and `mel_fuel_penalty_kg`, the round-half-up of the exact
        trip fuel multiplied by the sum of `fuel_penalty_pct` over all `OPEN`
        deferred defects on the aircraft, divided by 100."
        (trip 8190; penalty rhu(8190 * 3/100) = 246.)

        Design: Difficulty/combinatorial_formula/required_fuel_multi_input_branching_mode_a
        """
        ctx = self._setup_mel_penalty_plan(api)
        plan = ctx["plan"]
        assert_plan(plan)
        assert plan["trip_fuel_kg"] == 8190
        assert plan["mel_fuel_penalty_kg"] == 246

    def test_penalized_contingency_and_single_final_rounding(self, api):
        """PRD §3.3: "The `contingency_kg` is the round-half-up of the larger of
        two quantities: five percent of the penalized exact trip fuel, or a
        floor of 100 kg." and "Finally, `required_fuel_kg` is a single
        round-half-up applied to the sum of the penalized exact trip fuel, the
        exact contingency, the exact alternate fuel, and the exact reserve —
        exactly one rounding at the final sum, with no intermediate rounded
        values feeding it." (contingency rhu(421.785) = 422; required
        rhu(10768.485) = 10768.)

        Design: Difficulty/combinatorial_formula/required_fuel_multi_input_branching_mode_a
        """
        ctx = self._setup_mel_penalty_plan(api)
        plan = ctx["plan"]
        assert plan["contingency_kg"] == 422
        assert plan["alternate_fuel_kg"] == 546
        assert plan["final_reserve_kg"] == 1365
        assert plan["required_fuel_kg"] == 10768


class TestAlternateSelection:
    def test_alternate_selector_tie_break_uses_created_at(self, api):
        """PRD §3.3: "Eligible stations are ranked by `alternate_distance_nm`
        ascending, with ties broken by station `created_at` ascending, never by
        id. The winner becomes the plan's `alternate_station_id`."

        Design: Corner/calculations/alternate_selector_tie_break_uses_created_at
        """
        ctx = setup_reference_data(with_alternate=False)
        alt_a = validate_success(
            api.create_station(
                create_station_payload(iata_code="KAL1", alternate_distance_nm=90), SUP
            ),
            201,
        )
        validate_success(
            api.create_station(
                create_station_payload(iata_code="KAL2", alternate_distance_nm=90), SUP
            ),
            201,
        )
        add_leg(ctx, flight_no="FD400", distance_nm=1200)
        plan = add_plan(ctx)
        assert plan["alternate_station_id"] == alt_a["id"], (
            "the earlier-created station wins the 90 NM tie"
        )

    def test_alternate_selector_empty_pool_rejected(self, api):
        """PRD §3.3: "A station is eligible only if its `status` is `OPEN`, it
        is neither the leg's departure nor arrival station, its
        `alternate_distance_nm` is at most 200 nautical miles, and its
        `runway_length_m` is at least the aircraft's `min_runway_m`." and "An
        empty pool rejects the plan creation outright with
        `ERR_NO_SUITABLE_ALTERNATE`."

        Design: Corner/calculations/alternate_selector_empty_pool_rejected
        """
        ctx = setup_reference_data(with_alternate=False)
        # 250 NM > 200 limit
        validate_success(
            api.create_station(
                create_station_payload(iata_code="KFAR", alternate_distance_nm=250),
                SUP,
            ),
            201,
        )
        # runway 1500 < min_runway_m 1800
        validate_success(
            api.create_station(
                create_station_payload(iata_code="KSHORT", runway_length_m=1500,
                                       alternate_distance_nm=60),
                SUP,
            ),
            201,
        )
        # CLOSED
        validate_success(
            api.create_station(
                create_station_payload(iata_code="KCLSD", alternate_distance_nm=70,
                                       status="CLOSED"),
                SUP,
            ),
            201,
        )
        add_leg(ctx, flight_no="FD410", distance_nm=1200)
        res = api.create_plan(
            create_plan_payload(ctx["leg"]["id"], ctx["leg_version"]),
            ctx["d_headers"],
        )
        validate_error(res, ApiErrorId.ERR_NO_SUITABLE_ALTERNATE.value)


class TestWorstCaseEnforcement:
    def test_mel_open_forces_worst_case_assumption(self, api):
        """PRD §3.3: "The worst-case variant is mandatory, not optional, in one
        situation: when any `OPEN` deferred defect on the aircraft carries a
        `fuel_penalty_pct` greater than zero, creating a plan with
        `wind_assumption` `FORECAST` is rejected with `ERR_WORST_CASE_REQUIRED`."

        Design: Corner/calculations/mel_open_forces_worst_case_assumption
        """
        ctx = setup_reference_data()
        validate_success(
            api.create_mel_item(
                create_mel_item_payload(ctx["aircraft"]["id"], fuel_penalty_pct=3),
                SUP,
            ),
            201,
        )
        add_leg(ctx, flight_no="FD420", distance_nm=1200)
        res = api.create_plan(
            create_plan_payload(ctx["leg"]["id"], ctx["leg_version"],
                                wind_assumption="FORECAST", forecast_wind_kts=30),
            ctx["d_headers"],
        )
        validate_error(res, ApiErrorId.ERR_WORST_CASE_REQUIRED.value)


class TestPlanCreateOcc:
    def test_occ_plan_create_stale_leg_version(self, api):
        """PRD §2.6: "Creating a flight plan for a leg requires the request to
        carry `expected_leg_version`, a non-optional field holding the client
        last-observed `version` of the target FlightLeg. If the leg's current
        `version` has advanced beyond that value — for example because another
        plan was created or a delay was accepted in the meantime — the create is
        rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to
        re-read before superseding the leg's current plan."

        Design: Corner/complexity_layers/occ_plan_create_stale_leg_version
        """
        ctx = setup_reference_data()
        add_leg(ctx, flight_no="FD830", distance_nm=1200)
        stale_version = ctx["leg_version"]
        first = validate_success(
            api.create_plan(
                create_plan_payload(ctx["leg"]["id"], stale_version),
                ctx["d_headers"],
            ),
            201,
        )
        assert first["plan_seq"] == 1  # PRD §3.3: plan_seq starts at 1
        res = api.create_plan(
            create_plan_payload(ctx["leg"]["id"], stale_version,
                                route_code="DCT ALT DCT", cruise_altitude_ft=37000,
                                forecast_wind_kts=10),
            ctx["d_headers"],
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


class TestPlanListFilter:
    def test_plans_list_filter_by_leg(self, api):
        """PRD §3.3: "The plan list is filterable by `leg_id` and
        `alternate_station_id`."

        Design: Corner/endpoints/plans_list_filter_by_leg
        """
        ctx = setup_reference_data()
        add_leg(ctx, flight_no="FD700", distance_nm=1200)
        plan1 = add_plan(ctx)
        leg2 = add_second_leg(ctx, flight_no="FD701", distance_nm=300,
                              sched_dep_utc="2026-05-01T15:00:00Z",
                              sched_arr_utc="2026-05-01T16:00:00Z")
        plan2 = validate_success(
            api.create_plan(
                create_plan_payload(leg2["id"], leg2["version"],
                                    cruise_altitude_ft=15000),
                ctx["d_headers"],
            ),
            201,
        )
        data, meta = validate_paginated(
            api.list_plans(ctx["d_headers"], params={"leg_id": ctx["leg"]["id"]})
        )
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == plan1["id"]
        assert data[0]["id"] != plan2["id"]


class TestPlanRbac:
    def test_captain_cannot_create_plan_forbidden(self, api):
        """PRD §2.1: "A request whose role is not in the target endpoint's
        authorized role list is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)." PRD §4 restricts POST /dispatch/plans to Dispatcher.

        Design: Corner/rbac/captain_cannot_create_plan_forbidden
        """
        ctx = setup_reference_data(with_alternate=False)
        add_leg(ctx, flight_no="FD890", distance_nm=400,
                sched_dep_utc="2026-05-01T10:00:00Z",
                sched_arr_utc="2026-05-01T11:00:00Z")
        res = api.create_plan(
            create_plan_payload(ctx["leg"]["id"], ctx["leg_version"]),
            make_captain_headers(ctx["captain"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value,
                       expected_status=403)
