"""Dimensional control, the two status dimensions and the weight budget.

Covers the inclusive frame tolerance of PRD 3.3, the inclusive 3000 lb brake
threshold of PRD 3.4 read from the pinned rating, the independence of the
build and compliance dimensions, and the exact compensation an option removal
owes the weight budget under PRD 3.5.
"""

import test_helpers as H
from test_helpers import (
    ASSEMBLY_TECH,
    WELD_SUPERVISOR,
    validate_error,
    validate_success,
)


class TestFrameDeviationTolerance:
    def test_a_deviation_of_exactly_three_millimetres_passes_the_frame(self, api):
        """3 mm is inside tolerance, so the verdict is PASS with no reasons.

        PRD 3.3: "If `max_deviation_mm` is greater than 3.0 millimetres,
        `MAX_DEVIATION` joins the list; a deviation of exactly 3.0 millimetres is
        within tolerance and does not."

        Design: Difficulty/boundary_precision_check/frame_deviation_tolerance_inclusive_at_three_millimetres
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        jig = H.commission_jig(api)
        unit = H.open_unit(api, model["id"], "SN-000101")
        H.reserve_jig_window(api, jig["id"], unit["id"], window=H.JIG_WINDOW_1)

        response = api.create_frame_inspection(
            unit["id"],
            H.inspection_payload(measured_length_mm=4270),
            headers=WELD_SUPERVISOR,
        )

        inspection = validate_success(response, expected_status=201)
        H.assert_one_decimal(inspection["length_deviation_mm"], 3)
        H.assert_one_decimal(inspection["width_deviation_mm"], 0)
        H.assert_one_decimal(inspection["max_deviation_mm"], 3)
        H.assert_one_decimal(inspection["squareness_delta_mm"], 0)
        assert inspection["result"] == H.InspectionResult.PASS
        assert inspection["failure_reasons"] == []
        assert inspection["inspection_seq"] == 1
        H.assert_append_only_audit_fields(inspection)
        after = H.read_unit(api, unit["id"])
        assert after["build_status"] == H.BuildStatus.FRAME_WELDED
        assert after["frame_fail_count"] == 0

    def test_a_deviation_of_four_millimetres_fails_the_frame_into_rework(self, api):
        """One millimetre further out is a FAIL carrying exactly one reason code.

        PRD 3.3: "The `result` is `PASS` when and only when `failure_reasons` is
        empty, and `FAIL` otherwise; a passing inspection stores
        `failure_reasons` as an empty array."

        Design: Difficulty/boundary_precision_check/frame_deviation_tolerance_inclusive_at_three_millimetres
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        jig = H.commission_jig(api)
        unit = H.open_unit(api, model["id"], "SN-000102")
        H.reserve_jig_window(api, jig["id"], unit["id"], window=H.JIG_WINDOW_1)

        response = api.create_frame_inspection(
            unit["id"],
            H.inspection_payload(measured_length_mm=4271),
            headers=WELD_SUPERVISOR,
        )

        inspection = validate_success(response, expected_status=201)
        H.assert_one_decimal(inspection["length_deviation_mm"], 4)
        H.assert_one_decimal(inspection["max_deviation_mm"], 4)
        assert inspection["result"] == H.InspectionResult.FAIL
        assert inspection["failure_reasons"] == [H.FRAME_FAILURE_MAX_DEVIATION]
        assert inspection["inspection_seq"] == 1
        H.assert_append_only_audit_fields(inspection)
        after = H.read_unit(api, unit["id"])
        assert after["build_status"] == H.BuildStatus.FRAME_REWORK
        assert after["frame_fail_count"] == 1


def _stage_single_axle_unit_at_lighting_verified(api, model_payload, serial_number, window):
    """A single-axle trailer welded and lamp-verified, ready for the brake stage."""
    model = H.create_certified_model(api, payload=model_payload)
    jig = H.commission_jig(api, payload=H.sa_jig_payload())
    unit = H.open_unit(api, model["id"], serial_number)
    H.reserve_jig_window(api, jig["id"], unit["id"], window=window)
    api.create_frame_inspection(unit["id"], H.sa_inspection_payload(), headers=WELD_SUPERVISOR)
    H.install_lighting(api, unit["id"])
    return model, unit


class TestBrakeThresholdIsInclusive:
    def test_a_pinned_rating_of_exactly_three_thousand_pounds_demands_brakes(self, api):
        """At 3000 lb the brake stage is refused and both dimensions hold still.

        PRD 3.4: "From 3000 pounds upward, inclusive, the trailer must have at
        least 1 braked axle installed and `breakaway_kit_installed` must be true."

        Design: Difficulty/boundary_precision_check/brake_requirement_inclusive_at_gvwr_exactly_3000
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model, unit = _stage_single_axle_unit_at_lighting_verified(
            api, H.sa_heavy_model_payload(), "SN-000201", H.JIG_WINDOW_1
        )
        assert model["provisional_gvwr_lbs"] == H.SA_HEAVY_PROVISIONAL_GVWR_LBS
        assert model["certified_gvwr_lbs"] == H.SA_HEAVY_CERTIFIED_GVWR_LBS
        pinned = H.read_unit(api, unit["id"])
        assert pinned["gvwr_lbs"] == H.SA_HEAVY_CERTIFIED_GVWR_LBS
        assert pinned["payload_capacity_lbs"] == H.SA_HEAVY_PAYLOAD_CAPACITY_LBS

        response = api.install_systems(
            unit["id"],
            H.brake_payload(installed_braked_axle_count=0, breakaway_kit_installed=False),
            headers=ASSEMBLY_TECH,
        )

        validate_error(response, H.ERR_BRAKE_REQUIREMENT_UNMET)
        after = H.read_unit(api, unit["id"])
        H.assert_unit_dimensions(
            after, H.BuildStatus.FRAME_WELDED, H.ComplianceStatus.LIGHTING_VERIFIED
        )

    def test_a_pinned_rating_of_two_thousand_nine_hundred_ninety_needs_no_brakes(self, api):
        """Ten pounds lighter and the same unbraked stage is accepted.

        PRD 3.4: "Below 3000 pounds there is no braking requirement at all."

        Design: Difficulty/boundary_precision_check/brake_requirement_inclusive_at_gvwr_exactly_3000
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model, unit = _stage_single_axle_unit_at_lighting_verified(
            api, H.sa_light_model_payload(), "SN-000202", H.JIG_WINDOW_1
        )
        assert model["certified_gvwr_lbs"] == H.SA_LIGHT_CERTIFIED_GVWR_LBS
        pinned = H.read_unit(api, unit["id"])
        assert pinned["gvwr_lbs"] == H.SA_LIGHT_CERTIFIED_GVWR_LBS
        assert pinned["payload_capacity_lbs"] == H.SA_LIGHT_PAYLOAD_CAPACITY_LBS

        response = api.install_systems(
            unit["id"],
            H.brake_payload(installed_braked_axle_count=0, breakaway_kit_installed=False),
            headers=ASSEMBLY_TECH,
        )

        updated = validate_success(response)
        H.assert_unit_dimensions(
            updated, H.BuildStatus.SYSTEMS_INSTALLED, H.ComplianceStatus.FULLY_COMPLIANT
        )
        assert updated["installed_braked_axle_count"] == 0


class TestIndependentStatusDimensions:
    def test_the_lighting_stage_moves_compliance_and_leaves_the_build_alone(self, api):
        """Lamps verified, build dimension untouched at FRAME_WELDED.

        PRD 3.4: "In both cases the trailer's `build_status` is deliberately left
        untouched — this is precisely where the two dimensions move
        independently, and a supervisor watching only the build dimension will
        see nothing happen."

        Design: Difficulty/non_linear_state_machine/unit_build_and_compliance_dimensions_advance_independently
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        jig = H.commission_jig(api)
        unit = H.open_unit(api, model["id"], "SN-000101")
        H.reserve_jig_window(api, jig["id"], unit["id"], window=H.JIG_WINDOW_1)
        H.inspect_frame(api, unit["id"])

        response = api.install_systems(unit["id"], H.lighting_payload(), headers=ASSEMBLY_TECH)

        lit = validate_success(response)
        H.assert_unit_dimensions(
            lit, H.BuildStatus.FRAME_WELDED, H.ComplianceStatus.LIGHTING_VERIFIED
        )
        assert lit["clearance_lamp_count"] == 0

        repeated = api.install_systems(unit["id"], H.lighting_payload(), headers=ASSEMBLY_TECH)
        validate_error(repeated, H.ERR_COMPLIANCE_STAGE_OUT_OF_ORDER)

    def test_the_brake_stage_recouples_the_two_dimensions_on_one_call(self, api):
        """BRAKE_AND_AXLE advances compliance and the build together.

        PRD 3.4: "It records `installed_braked_axle_count` and
        `breakaway_kit_installed` on the trailer, moves `compliance_status` from
        `LIGHTING_VERIFIED` to `FULLY_COMPLIANT`, and on the very same call moves
        `build_status` to `SYSTEMS_INSTALLED`."

        Design: Difficulty/non_linear_state_machine/unit_build_and_compliance_dimensions_advance_independently
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        jig = H.commission_jig(api)
        unit = H.open_unit(api, model["id"], "SN-000101")
        H.reserve_jig_window(api, jig["id"], unit["id"], window=H.JIG_WINDOW_1)
        H.inspect_frame(api, unit["id"])
        H.install_lighting(api, unit["id"])

        response = api.install_systems(unit["id"], H.brake_payload(), headers=ASSEMBLY_TECH)

        braked = validate_success(response)
        H.assert_unit_dimensions(
            braked, H.BuildStatus.SYSTEMS_INSTALLED, H.ComplianceStatus.FULLY_COMPLIANT
        )
        assert braked["installed_braked_axle_count"] == 1
        assert braked["breakaway_kit_installed"] is True


class TestOptionRemovalCompensation:
    def test_charging_a_flooring_option_moves_the_weight_budget(self, api):
        """The extended amounts and the rederived budget are both visible at once.

        PRD 3.5: "`total_weight_lbs` is the `quantity` multiplied by
        `unit_weight_lbs`, and `total_price_cents` is the `quantity` multiplied by
        `unit_price_cents`."

        Design: Difficulty/compensating_invariant/option_removal_restores_the_unit_weight_budget_exactly
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        plant = H.setup_plant(api)
        staged = H.unit_at_systems_installed(plant, api)

        response = api.create_option_install(
            staged["unit"]["id"],
            H.option_payload(
                option_code="SPECIALTY_FLOORING",
                quantity=2,
                unit_weight_lbs=150,
                unit_price_cents=17250,
                labor_hours=1.5,
            ),
            headers=ASSEMBLY_TECH,
        )

        line = validate_success(response, expected_status=201)
        assert line["status"] == H.OptionStatus.PENDING
        assert line["total_weight_lbs"] == 300
        H.assert_money(line["total_price_cents"], 34500)
        charged = H.read_unit(api, staged["unit"]["id"])
        assert charged["curb_weight_lbs"] == 2280
        assert charged["payload_capacity_lbs"] == 4020
        H.assert_weight_budget_balances(charged)

    def test_removing_the_option_restores_the_budget_with_no_drift(self, api):
        """The removed line keeps its amounts while the trailer returns to 1980 and 4320.

        PRD 3.5: "Removal rederives `curb_weight_lbs` and
        `payload_capacity_lbs`, and a charge-then-remove pair must return both
        fields to their exact prior values with no drift whatsoever."

        Design: Difficulty/compensating_invariant/option_removal_restores_the_unit_weight_budget_exactly
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        plant = H.setup_plant(api)
        staged = H.unit_at_systems_installed(plant, api)
        line = H.charge_option(
            api,
            staged["unit"]["id"],
            option_code="SPECIALTY_FLOORING",
            quantity=2,
            unit_weight_lbs=150,
            unit_price_cents=17250,
            labor_hours=1.5,
        )

        response = api.delete_option_install(
            line["id"],
            H.removal_payload(removal_reason="customer dropped the flooring upgrade"),
            headers=ASSEMBLY_TECH,
        )

        removed = validate_success(response)
        assert removed["status"] == H.OptionStatus.REMOVED
        assert removed["total_weight_lbs"] == 300
        H.assert_money(removed["total_price_cents"], 34500)
        after = H.read_unit(api, staged["unit"]["id"])
        assert after["curb_weight_lbs"] == H.TA_BASE_CURB_WEIGHT_LBS
        assert after["payload_capacity_lbs"] == H.TA_PAYLOAD_CAPACITY_LBS
        assert after["gvwr_lbs"] == H.TA_CERTIFIED_GVWR_LBS
        H.assert_weight_budget_balances(after)
        assert after["build_status"] == H.BuildStatus.SYSTEMS_INSTALLED
        visible, _meta = H.validate_paginated(
            api.list_option_installs(staged["unit"]["id"], headers=ASSEMBLY_TECH)
        )
        assert visible == []
        with_removed, _meta2 = H.validate_paginated(
            api.list_option_installs(
                staged["unit"]["id"], params={"include_removed": "true"}, headers=ASSEMBLY_TECH
            )
        )
        assert len(with_removed) == 1
