"""Declared calculations: the finding ladder, rounding order, filtering and selection."""

from test_helpers import (
    assert_four_decimal_places,
    assert_group_reports_cost_per_mile,
    entries_of_type,
    factories,
    fixtures,
    make_tire_technician_headers,
    validate_success,
)


class TestSurveyFindingLadder:
    def test_a_bald_and_underinflated_tire_reports_only_the_tread_finding(self, api):
        """PRD §3.3: "Then `finding_code` is resolved by walking four conditions
        strictly from the top and stopping at the **first** one that holds: it is
        `TREAD_BELOW_MIN` when the measured `tread_depth_32nds` is strictly less than
        the policy's `min_tread_depth_32nds`; otherwise `TREAD_AT_PULL_POINT` when the
        measured `tread_depth_32nds` is less than or equal to the policy's
        `pull_point_32nds`; otherwise `PRESSURE_DEVIATION` when the rounded
        `pressure_deviation_pct` is greater than or equal to the policy's
        `pressure_tolerance_pct`; otherwise `COMPLIANT`."
        PRD §3.3: "The server stamps `surveyed_by_user_id` with the acting
        technician's identifier."

        Design: Corner/calculations/survey_finding_ladder_takes_first_match_only
        """
        program = fixtures.setup_fleet_program()
        technician = fixtures.create_technician(program["location"]["id"])
        vehicle = fixtures.create_vehicle(
            program["fleet"]["id"], current_odometer_miles=300000
        )
        casing = fixtures.create_casing(program["fleet"]["id"])
        asset = fixtures.create_mounted_asset(
            program["fleet"]["id"],
            casing["id"],
            vehicle["id"],
            mounted_at="2026-08-02T09:00:00Z",
            odometer_at_mount=300000,
            tread_depth_at_mount_32nds=24,
        )

        survey = validate_success(
            api.create_tire_survey(
                asset["id"],
                factories.survey_payload("2026-08-14T09:00:00Z", 80, 3, 340000),
                make_tire_technician_headers(technician["id"]),
            ),
            expected_status=201,
        )

        assert survey["finding_code"] == "TREAD_BELOW_MIN", (
            "three thirty-seconds is below the minimum of four, and that first "
            "match ends the walk even though the pull point and the pressure "
            "tolerance are both breached as well"
        )
        assert survey["pressure_deviation_pct"] == 0.2000
        assert_four_decimal_places(
            survey["pressure_deviation_pct"], "pressure_deviation_pct"
        )
        assert survey["pull_recommended"] is True
        assert survey["surveyed_by_user_id"] == technician["id"], (
            "the acting identity, never a client-supplied value"
        )
        assert fixtures.read_tire_asset(asset["id"])["status"] == "PULL_FLAGGED"


class TestPressureDeviationPrecision:
    def test_the_deviation_is_rounded_before_it_is_compared_to_the_tolerance(self, api):
        """PRD §3.3: "First, `pressure_deviation_pct` is the absolute difference
        between the measured `pressure_psi` and the policy's `target_pressure_psi`,
        divided by that same `target_pressure_psi`, rounded half up to four decimal
        places."
        PRD §3.3: "When `finding_code` is `COMPLIANT` and the asset is `PULL_FLAGGED`,
        the flag is cleared and the asset reverts `PULL_FLAGGED → MOUNTED`."

        Design: Corner/calculations/survey_pressure_deviation_rounded_before_comparison
        """
        program = fixtures.setup_fleet_program()
        vehicle = fixtures.create_vehicle(
            program["fleet"]["id"], current_odometer_miles=400000
        )
        casing = fixtures.create_casing(program["fleet"]["id"])
        asset = fixtures.create_mounted_asset(
            program["fleet"]["id"],
            casing["id"],
            vehicle["id"],
            mounted_at="2026-08-02T09:00:00Z",
            odometer_at_mount=400000,
            tread_depth_at_mount_32nds=24,
        )

        flagging = fixtures.record_survey(
            asset["id"], "2026-08-15T09:00:00Z", 100, 6, 430000
        )
        assert flagging["finding_code"] == "TREAD_AT_PULL_POINT"
        assert fixtures.read_tire_asset(asset["id"])["status"] == "PULL_FLAGGED"

        clearing = fixtures.record_survey(
            asset["id"], "2026-08-16T09:00:00Z", 96.5, 8, 431000
        )

        assert clearing["pressure_deviation_pct"] == 0.0350
        assert_four_decimal_places(
            clearing["pressure_deviation_pct"], "pressure_deviation_pct"
        )
        assert clearing["finding_code"] == "COMPLIANT", (
            "0.0350 is short of the 0.10 tolerance, so no pressure finding fires"
        )
        assert clearing["pull_recommended"] is False

        recovered = fixtures.read_tire_asset(asset["id"])
        assert recovered["status"] == "MOUNTED", "a compliant survey clears the flag"
        assert recovered["current_tread_depth_32nds"] == 8


class TestCostPerMileCandidateFiltering:
    def test_an_asset_with_no_wear_signal_leaves_the_numerator_and_denominator(
        self, api
    ):
        """PRD §3.9: "One exclusion applies to **both** variants and removes an asset
        from numerator and denominator alike: an asset whose miles run are 0, or whose
        consumed tread is 0 or negative, is dropped and counted in
        `excluded_asset_count`."
        PRD §3.9: "The candidate assets are that fleet's tire assets whose `status` is
        `MOUNTED`, `PULL_FLAGGED` or `PULLED`; assets sitting in `IN_INVENTORY` have
        not run a mile, and `SCRAPPED` assets have left the program, so both are
        excluded outright."

        Design: Corner/calculations/cost_per_mile_excludes_assets_with_no_wear_signal
        """
        program = fixtures.setup_fleet_program()
        fleet_id = program["fleet"]["id"]
        fixtures.create_policy(fleet_id, position="TRAILER")
        vehicle = fixtures.create_vehicle(fleet_id, current_odometer_miles=500000)

        worn = fixtures.create_mounted_asset(
            fleet_id,
            fixtures.create_casing(fleet_id)["id"],
            vehicle["id"],
            mounted_at="2026-08-02T09:00:00Z",
            odometer_at_mount=500000,
            tread_depth_at_mount_32nds=24,
            cost_basis_cents=50000,
        )
        fixtures.record_survey(worn["id"], "2026-08-18T09:00:00Z", 100, 15, 560000)

        stationary = fixtures.create_mounted_asset(
            fleet_id,
            fixtures.create_casing(fleet_id, intended_position="TRAILER")["id"],
            vehicle["id"],
            mounted_at="2026-08-02T09:00:00Z",
            odometer_at_mount=500000,
            tread_depth_at_mount_32nds=24,
            position="TRAILER",
            cost_basis_cents=99000,
        )
        fixtures.record_survey(stationary["id"], "2026-08-18T09:00:00Z", 100, 20, 500000)

        shelved = fixtures.create_tire_asset(
            fleet_id,
            fixtures.create_casing(fleet_id)["id"],
            cost_basis_cents=77000,
        )
        assert shelved["status"] == "IN_INVENTORY"

        report = validate_success(
            api.get_cost_per_mile(
                fleet_id, fixtures.ADMIN, params={"variant": "HISTORICAL_ACTUAL"}
            )
        )

        assert report["variant"] == "HISTORICAL_ACTUAL"
        assert report["group_count"] == 1
        assert len(report["groups"]) == 1
        group = report["groups"][0]
        assert group["brand"] == "Bridgestone"
        assert group["position"] == "DRIVE"
        assert group["vehicle_type"] == "TRACTOR"
        assert_group_reports_cost_per_mile(group, 0.8333)
        assert report["excluded_asset_count"] == 1, (
            "only the surveyed-but-motionless asset is excluded and counted; the "
            "IN_INVENTORY asset was never a candidate"
        )


class TestCasingCreditDefaultRate:
    def test_a_drafted_agreement_does_not_price_the_credit(self, api):
        """PRD §3.4: "The base rate is the negotiated `casing_credit_rate_cents` of
        the fleet's `ACTIVE` national agreement whose closed window covers the logical
        clock's date; when no such agreement exists, the base rate is the dealer
        default of 12000 cents — one hundred and twenty dollars per casing."
        PRD §3.2: "A `DRAFT` agreement prices nothing and blocks no window — it is
        inert."

        Design: Corner/calculations/casing_credit_uses_default_rate_without_active_agreement
        """
        program = fixtures.setup_fleet_program(
            fleet_overrides={
                "account_type": "NATIONAL_ACCOUNT",
                "billing_mode": "CROSS_LOCATION",
            }
        )
        fleet_id = program["fleet"]["id"]
        agreement = fixtures.create_agreement(
            fleet_id, activate=False, casing_credit_rate_cents=30000
        )
        assert agreement["status"] == "DRAFT"

        collected = fixtures.create_collected_casing(fleet_id, program["location"]["id"])
        graded = validate_success(
            api.inspect_casing(
                collected["id"],
                factories.inspect_casing_payload("A", collected["version"]),
                fixtures.inspector_headers(),
            )
        )

        assert graded["status"] == "INSPECTED"
        assert graded["inspection_grade"] == "A"
        assert graded["inspected_by_user_id"] == "inspector-1"
        assert graded["provisional_credit_cents"] == 12000, (
            "the dealer default of 12000 at grade factor 1.00 and no decay, not the "
            "30000 the inert draft names"
        )

        accruals = entries_of_type(fixtures.list_casing_ledger(collected["id"]), "ACCRUAL")
        assert [entry["amount_cents"] for entry in accruals] == [12000]
        assert fixtures.read_fleet(fleet_id)["casing_credit_balance_cents"] == 12000
        assert fixtures.read_agreement(agreement["id"])["status"] == "DRAFT", (
            "grading a casing does not activate anything"
        )


class TestTechnicianSelector:
    def test_the_selector_breaks_a_certification_tie_on_the_lighter_workload(self, api):
        """PRD §3.6: "The surviving pool is ranked by certification descending,
        treating `TIA_CERTIFIED` as rank 3, `LEVEL_2` as rank 2 and `LEVEL_1` as rank
        1, so the most highly certified technician wins. Where two candidates tie on
        certification, the one with the smaller `completed_call_count` wins — the
        roster self-levels. Where they still tie, the technician whose `created_at` is
        earliest wins."
        PRD §3.6: "On top of that, when the call's `priority` is `EMERGENCY`, only
        technicians whose `certification_level` is `TIA_CERTIFIED` remain eligible; on
        a `NORMAL` call any certification tier qualifies."

        Design: Corner/calculations/technician_dispatch_selector_picks_by_rank_then_load
        """
        program = fixtures.setup_fleet_program()
        fleet_id = program["fleet"]["id"]
        location_id = program["location"]["id"]
        first_unit = fixtures.create_vehicle(fleet_id, current_odometer_miles=7000)
        second_unit = fixtures.create_vehicle(fleet_id, current_odometer_miles=8000)

        junior = fixtures.create_technician(
            location_id, name="Sel One", certification_level="LEVEL_1"
        )
        busy = fixtures.create_technician(
            location_id, name="Sel Two", certification_level="TIA_CERTIFIED"
        )
        idle = fixtures.create_technician(
            location_id, name="Sel Three", certification_level="TIA_CERTIFIED"
        )

        fixtures.run_completed_call(
            fleet_id,
            first_unit["id"],
            location_id,
            busy["id"],
            reported_at="2026-08-19T12:00:00Z",
            dispatched_at="2026-08-19T12:05:00Z",
            arrived_at="2026-08-19T12:30:00Z",
            closed_at="2026-08-19T13:00:00Z",
            labor_hours=0.25,
            dispatch_miles=3,
        )
        assert fixtures.read_technician(busy["id"])["completed_call_count"] == 1
        assert fixtures.read_technician(busy["id"])["status"] == "AVAILABLE"
        assert fixtures.read_technician(idle["id"])["completed_call_count"] == 0
        assert fixtures.read_technician(idle["id"])["status"] == "AVAILABLE"

        emergency = fixtures.open_call(
            fleet_id,
            second_unit["id"],
            location_id,
            "2026-08-19T14:00:00Z",
            priority="EMERGENCY",
        )

        dispatched = validate_success(
            api.dispatch_road_service_call(
                emergency["id"],
                factories.dispatch_payload("2026-08-19T14:10:00Z", 12),
                fixtures.DISPATCHER,
            )
        )

        assert dispatched["technician_id"] == idle["id"], (
            "the earlier-created TIA technician lost on completed_call_count, so "
            "created_at is only the final tie-break"
        )
        assert dispatched["technician_id"] != junior["id"]
        assert fixtures.read_technician(junior["id"])["status"] == "AVAILABLE", (
            "the LEVEL_1 technician never entered the emergency pool"
        )
        assert fixtures.read_technician(idle["id"])["status"] == "ON_CALL"
        assert fixtures.read_vehicle(second_unit["id"])["status"] == "OUT_OF_SERVICE"
