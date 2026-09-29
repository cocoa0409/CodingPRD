"""Build state machines: opening states, the weld loop, scrap and release edges.

The trailer carries two independent status dimensions and several transitions
reach sideways into a jig calendar, a label, an order or a dealer receivable.
Each test walks one declared edge and pins the side effects PRD names for it.
"""

import test_helpers as H
from test_helpers import (
    QUALITY_INSPECTOR,
    WELD_SUPERVISOR,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTrailerOpeningState:
    def test_a_new_build_record_opens_on_both_dimensions_with_nothing_pinned(self, api):
        """Both status dimensions start at their declared values and the snapshots are null.

        PRD 3.2: "The build record opens with its two status dimensions
        independent and both at their starting values: `build_status` is
        `PLANNED` and `compliance_status` is `NOT_VERIFIED`."

        Design: Corner/state_machines/state_new_trailer_unit_starts_in_planned_and_not_verified
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)

        response = api.create_unit(
            H.unit_payload(model["id"], serial_number="SN-000101"), headers=WELD_SUPERVISOR
        )

        unit = validate_success(response, expected_status=201)
        H.assert_unit_dimensions(
            unit, H.BuildStatus.PLANNED, H.ComplianceStatus.NOT_VERIFIED
        )
        assert unit["frame_fail_count"] == 0
        assert unit["rework_cycle_count"] == 0
        assert unit["model_version_pinned"] is None
        assert unit["gvwr_lbs"] is None
        assert unit["curb_weight_lbs"] is None
        assert unit["payload_capacity_lbs"] is None
        assert unit["vin"] is None
        assert unit["dealer_order_id"] is None
        assert unit["released_to_stock_at"] is None
        assert unit["warranty_start_date"] is None
        assert unit["installed_braked_axle_count"] is None
        assert H.read_model(api, model["id"])["active_unit_count"] == 1


class TestFramePassConsumesTheWindow:
    def test_a_passing_inspection_consumes_the_window_without_refunding_minutes(self, api):
        """A consumed window still occupies the jig calendar.

        PRD 3.3: "Consumption deliberately does **not** change the jig's
        `reserved_minutes_total`, because a consumed window still occupies the
        jig's calendar and must keep blocking overlapping bookings."

        Design: Corner/state_machines/state_frame_pass_consumes_the_jig_reservation_without_refunding_minutes
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_jig_reserved(plant, api, window=H.JIG_WINDOW_1)

        inspection = H.inspect_frame(api, staged["unit"]["id"])

        unit = H.read_unit(api, staged["unit"]["id"])
        H.assert_unit_dimensions(
            unit, H.BuildStatus.FRAME_WELDED, H.ComplianceStatus.NOT_VERIFIED
        )
        assert inspection["result"] == H.InspectionResult.PASS
        assert inspection["failure_reasons"] == []
        consumed, _meta = validate_paginated(
            api.list_jig_reservations(
                plant["jig"]["id"],
                params={"status": H.ReservationStatus.CONSUMED},
                headers=WELD_SUPERVISOR,
            )
        )
        assert [row["id"] for row in consumed] == [staged["reservation"]["id"]]
        assert H.read_jig(api, plant["jig"]["id"])["reserved_minutes_total"] == 120


class TestWeldFloorReworkLoop:
    def test_the_second_inspection_closes_the_loop_without_clearing_the_tally(self, api):
        """FRAME_REWORK returns to FRAME_WELDED on the same endpoint that failed it.

        PRD 3.3: "While the recomputed tally is below 3, the trailer moves to
        `FRAME_REWORK` and goes back on the jig; `FRAME_REWORK` and
        `JIG_RESERVED` together with `FRAME_WELDED` form the weld-floor rework
        loop, and a trailer may cycle through it."

        Design: Corner/state_machines/state_frame_rework_loop_returns_to_frame_welded_on_the_second_pass
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_jig_reserved(plant, api, window=H.JIG_WINDOW_1)
        unit_id = staged["unit"]["id"]

        failed = H.inspect_frame(
            api,
            unit_id,
            diagonal_a_mm=4790,
            diagonal_b_mm=4790,
            non_critical_weld_defect_count=3,
        )
        after_failure = H.read_unit(api, unit_id)
        reservations_mid, _mid = validate_paginated(
            api.list_unit_jig_reservations(unit_id, headers=WELD_SUPERVISOR)
        )
        H.inspect_frame(api, unit_id)

        assert failed["result"] == H.InspectionResult.FAIL
        assert failed["failure_reasons"] == [H.FRAME_FAILURE_NON_CRITICAL]
        H.assert_one_decimal(failed["squareness_delta_mm"], 0)
        H.assert_one_decimal(failed["max_deviation_mm"], 0)
        assert after_failure["build_status"] == H.BuildStatus.FRAME_REWORK
        assert reservations_mid[0]["status"] == H.ReservationStatus.RESERVED
        after_pass = H.read_unit(api, unit_id)
        assert after_pass["build_status"] == H.BuildStatus.FRAME_WELDED
        assert after_pass["frame_fail_count"] == 1
        reservations_end, _end = validate_paginated(
            api.list_unit_jig_reservations(unit_id, headers=WELD_SUPERVISOR)
        )
        assert reservations_end[0]["status"] == H.ReservationStatus.CONSUMED
        assert H.read_jig(api, plant["jig"]["id"])["reserved_minutes_total"] == 120


class TestThirdFrameFailureScrapsTheTrailer:
    def test_the_third_failure_scraps_the_trailer_and_refunds_the_jig_calendar(self, api):
        """The scrap edge fires on the counted third failure and gives the minutes back.

        PRD 3.3: "When the recomputed tally reaches exactly 3, the trailer is
        scrapped, and the scrap runs as a three-hop cascade."

        Design: Corner/state_machines/state_third_frame_failure_scraps_the_unit_and_gives_the_jig_minutes_back
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_jig_reserved(plant, api, window=H.JIG_WINDOW_1)
        unit_id = staged["unit"]["id"]

        H.inspect_frame(api, unit_id, measured_length_mm=H.TA_NOMINAL_LENGTH_MM + 4)
        first = H.read_unit(api, unit_id)["build_status"]
        H.inspect_frame(api, unit_id, measured_length_mm=H.TA_NOMINAL_LENGTH_MM + 5)
        second = H.read_unit(api, unit_id)["build_status"]
        H.inspect_frame(api, unit_id, measured_length_mm=H.TA_NOMINAL_LENGTH_MM + 6)

        assert first == H.BuildStatus.FRAME_REWORK
        assert second == H.BuildStatus.FRAME_REWORK
        scrapped = H.read_unit(api, unit_id)
        assert scrapped["build_status"] == H.BuildStatus.SCRAPPED
        assert scrapped["frame_fail_count"] == H.FRAME_SCRAP_THRESHOLD
        reservations, _meta = validate_paginated(
            api.list_unit_jig_reservations(unit_id, headers=WELD_SUPERVISOR)
        )
        assert reservations[0]["status"] == H.ReservationStatus.RELEASED
        assert H.read_jig(api, plant["jig"]["id"])["reserved_minutes_total"] == 0
        assert H.read_model(api, plant["model"]["id"])["active_unit_count"] == 0
        inspections, _ins_meta = validate_paginated(
            api.list_frame_inspections(unit_id, headers=WELD_SUPERVISOR)
        )
        assert [row["inspection_seq"] for row in inspections] == [1, 2, 3]
        assert all(row["result"] == H.InspectionResult.FAIL for row in inspections)


class TestModelWithdrawalSparesWorkInProcess:
    def test_withdrawal_scraps_the_planned_trailer_and_leaves_the_welded_one(self, api):
        """The cascade is conditional on each trailer's own build state.

        PRD 3.1: "Every trailer built to this model whose `build_status` is
        `PLANNED` or `BUILD_HOLD` moves to `SCRAPPED`; every `RESERVED` jig
        reservation belonging to one of those trailers moves to `RELEASED`; and
        each affected jig has `reserved_minutes_total` decremented by the released
        `duration_minutes` with its `version` incremented."
        PRD 3.1: "Trailers already past `PLANNED` and `BUILD_HOLD`, meaning welded
        or later, are deliberately left exactly as they are."

        Design: Corner/state_machines/state_model_withdrawal_scraps_planned_units_and_spares_welded_work
        """
        plant = H.setup_plant(api)
        model_id = plant["model"]["id"]
        welded = H.unit_at_frame_welded(plant, api, "SN-000101", H.JIG_WINDOW_1)
        planned = H.open_unit(api, model_id, "SN-000102")
        H.submit_model(api, model_id)

        H.decide_model(api, model_id, decision="WITHDRAWN")

        model = H.read_model(api, model_id)
        assert model["certification_status"] == H.CertificationStatus.WITHDRAWN
        assert H.read_unit(api, planned["id"])["build_status"] == H.BuildStatus.SCRAPPED
        assert H.read_unit(api, welded["unit"]["id"])["build_status"] == H.BuildStatus.FRAME_WELDED
        assert H.read_jig(api, plant["jig"]["id"])["reserved_minutes_total"] == 120
        assert model["active_unit_count"] == 1
        assert model["certified_gvwr_lbs"] == H.TA_CERTIFIED_GVWR_LBS
        refused = api.submit_model(model_id, H.submission_payload(), headers=H.PLANT_ENGINEER)
        validate_error(refused, H.ERR_MODEL_STATE_INVALID)


class TestRoadTestPassVacatesTheLane:
    def test_a_passing_result_advances_the_trailer_and_frees_the_lane_window(self, api):
        """The verdict is derived from the measurements and the lane occupancy drops the row.

        PRD 3.6: "A `PASSED` result is the simple branch: the test moves
        `SCHEDULED` → `PASSED` and the trailer moves `ROAD_TEST_PENDING` →
        `ROAD_TEST_PASSED`, ready for labelling."
        PRD 3.6: "Tests whose `status` is `PASSED` or `FAILED` have vacated the
        lane and never count, however recently they were resulted."

        Design: Corner/state_machines/state_road_test_pass_advances_the_unit_and_vacates_the_lane
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_systems_installed(plant, api, window=H.JIG_WINDOW_1)
        road_test = H.book_road_test(
            api, staged["unit"]["id"], plant["lane"]["id"], window=H.LANE_WINDOW_1
        )

        response = api.record_road_test_result(
            road_test["id"], H.road_test_result_payload(), headers=QUALITY_INSPECTOR
        )

        resulted = validate_success(response)
        assert resulted["status"] == H.RoadTestStatus.PASSED
        H.assert_one_decimal(resulted["brake_stop_distance_ft"], 32.5)
        assert resulted["lighting_check_passed"] is True
        assert resulted["inspector_user_id"] == H.QUALITY_INSPECTOR_ID
        unit = H.read_unit(api, staged["unit"]["id"])
        H.assert_unit_dimensions(
            unit, H.BuildStatus.ROAD_TEST_PASSED, H.ComplianceStatus.FULLY_COMPLIANT
        )
        assert unit["rework_cycle_count"] == 0
        assert unit["vin"] is None
        still_scheduled, _meta = validate_paginated(
            api.list_lane_road_tests(
                plant["lane"]["id"],
                params={"status": H.RoadTestStatus.SCHEDULED},
                headers=QUALITY_INSPECTOR,
            )
        )
        assert still_scheduled == []


class TestPendingOptionHoldsTheTrailerOutOfStock:
    def test_the_release_waits_for_the_option_sign_off_and_stamps_that_instant(self, api):
        """Labelling alone leaves the trailer at LABELED with no stock instant.

        PRD 3.5: "A trailer sitting in `build_status` `LABELED` moves itself to
        `RELEASED_TO_STOCK` as soon as the count of its install lines whose
        `status` is `PENDING` reaches exactly zero, stamping `released_to_stock_at`
        with the logical clock's current instant."

        Design: Corner/state_machines/state_pending_option_holds_a_labeled_unit_out_of_stock_until_completion
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_road_test_passed(plant, api, window=H.JIG_WINDOW_1)
        unit_id = staged["unit"]["id"]
        option = H.charge_option(
            api,
            unit_id,
            option_code="SPECIALTY_FLOORING",
            quantity=1,
            unit_weight_lbs=150,
            unit_price_cents=17250,
            labor_hours=1.5,
        )

        label = H.issue_label(api, unit_id)
        after_label = H.read_unit(api, unit_id)
        H.set_clock(api, H.CLOCK_AUG_06)
        completed = H.complete_option(api, option["id"])

        assert after_label["build_status"] == H.BuildStatus.LABELED
        assert after_label["released_to_stock_at"] is None
        assert label["status"] == H.LabelStatus.ISSUED
        assert label["vin"] == H.VIN_FIRST
        assert after_label["vin"] == H.VIN_FIRST
        assert completed["status"] == H.OptionStatus.COMPLETED
        released = H.read_unit(api, unit_id)
        assert released["build_status"] == H.BuildStatus.RELEASED_TO_STOCK
        H.assert_instant(released["released_to_stock_at"], H.CLOCK_AUG_06)
        assert released["curb_weight_lbs"] == 2130
        assert released["payload_capacity_lbs"] == 4170


class TestPartialPartShipmentsCloseTheClaim:
    def test_the_receivable_is_credited_once_on_the_shipment_that_closes_the_claim(self, api):
        """PARTS_SHIPPED self-loops on a counter and the credit lands exactly once.

        PRD 3.9: "Once `shipped_line_count` equals `part_line_count`, the claim
        moves to `CLOSED` and the dealer's `warranty_receivable_cents` grows by
        `reimbursement_total_cents` — credited exactly once, no matter how many
        shipments it took — with the dealer's `version` incremented."

        Design: Corner/state_machines/state_partial_part_shipments_close_the_claim_on_the_last_line
        """
        plant = H.setup_plant(api)
        staged = H.claim_submitted(plant, api)
        dealer_id = plant["dealer"]["id"]
        approved = H.review_claim(api, staged["claim"]["id"], H.ClaimDecision.APPROVE)
        receivable_at_approval = H.read_dealer(api, dealer_id)["warranty_receivable_cents"]

        first = H.ship_claim_parts(api, staged["claim"]["id"], "TRK-0001", line_count=1)
        receivable_mid = H.read_dealer(api, dealer_id)["warranty_receivable_cents"]
        second = H.ship_claim_parts(api, staged["claim"]["id"], "TRK-0002", line_count=1)

        assert approved["status"] == H.ClaimStatus.APPROVED
        H.assert_money(approved["reimbursement_total_cents"], H.CLAIM_GROSS_CENTS)
        H.assert_money(receivable_at_approval, 0)
        assert first["status"] == H.ClaimStatus.PARTS_SHIPPED
        assert first["shipped_line_count"] == 1
        assert first["tracking_number"] == "TRK-0001"
        H.assert_money(receivable_mid, 0)
        assert second["status"] == H.ClaimStatus.CLOSED
        assert second["shipped_line_count"] == 2
        assert second["tracking_number"] == "TRK-0002"
        dealer = H.read_dealer(api, dealer_id)
        H.assert_money(dealer["warranty_receivable_cents"], H.CLAIM_GROSS_CENTS)
        H.assert_floor_plan_conserved(dealer, H.ORDER1_DRAW_CENTS)
