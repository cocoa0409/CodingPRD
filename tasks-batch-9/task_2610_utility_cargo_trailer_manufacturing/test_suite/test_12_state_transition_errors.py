"""Refusals that come from a row's state rather than from its shape.

The optimistic-concurrency field of PRD 2.8 comes first, then the build,
compliance, claim and label state machines of PRD 3.2 through 3.9. Every test
reads the guarded row back to prove the refusal left it exactly as it was.
"""

import test_helpers as H
from test_helpers import (
    ASSEMBLY_TECH,
    CERT_OFFICER_2,
    QUALITY_INSPECTOR,
    SALES_ADMIN,
    WELD_SUPERVISOR,
    validate_error,
    validate_paginated,
)


class TestStaleDealerVersion:
    def test_replaying_the_enrollment_version_on_a_second_order_is_stale(self, api):
        """The first allocation bumped the row the second invoice would be priced on.

        PRD 2.8: "Such a request is rejected with `ERR_STALE_DEALER_VERSION`
        (HTTP 412) so that the client can re-read and re-decide; the same
        allocation retried with the fresh `version` succeeds."

        Design: Corner/errors/error_stale_dealer_version_rejects_an_allocation_priced_on_a_superseded_dealer
        """
        plant = H.setup_plant(api)
        enrollment_version = plant["dealer"]["version"]
        H.unit_in_stock(plant, api, "SN-000101", H.JIG_WINDOW_1, H.LANE_WINDOW_1)
        second = H.unit_in_stock(plant, api, "SN-000102", H.JIG_WINDOW_2, H.LANE_WINDOW_2)
        first_order = H.place_order(
            api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10001"
        )
        second_order = H.place_order(
            api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10002"
        )
        H.allocate_order(api, first_order["id"], plant["dealer"]["id"])

        response = api.allocate_order(
            second_order["id"], H.allocation_payload(enrollment_version), headers=SALES_ADMIN
        )

        validate_error(response, H.ERR_STALE_DEALER_VERSION)
        pending = H.read_order(api, second_order["id"])
        assert pending["status"] == H.OrderStatus.PENDING
        assert pending["invoice_total_cents"] is None
        # PRD 3.8: "An order opens with `status` `PENDING`, `floor_plan_status`
        # `NONE` and `floor_plan_draw_cents` 0" — the refused allocation leaves
        # that opening value untouched.
        assert pending["floor_plan_draw_cents"] == 0
        assert pending["allocated_unit_id"] is None
        unit = H.read_unit(api, second["unit"]["id"])
        assert unit["build_status"] == H.BuildStatus.RELEASED_TO_STOCK
        assert unit["dealer_order_id"] is None
        dealer = H.read_dealer(api, plant["dealer"]["id"])
        H.assert_floor_plan_conserved(dealer, H.ORDER1_DRAW_CENTS)
        assert dealer["allocations_current_month_count"] == 1


class TestBuildAndComplianceStateGates:
    def test_a_welded_trailer_cannot_book_a_second_weld_window(self, api):
        """A reservation is admissible only from PLANNED, whatever the jig version says.

        PRD 3.2: "The trailer must be in `build_status` `PLANNED`; any other build
        state is refused with `ERR_UNIT_BUILD_STATE_INVALID`."

        Design: Corner/errors/error_jig_reservation_on_a_frame_welded_unit_is_rejected
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_frame_welded(plant, api)
        jig = H.read_jig(api, plant["jig"]["id"])
        assert jig["reserved_minutes_total"] == 120

        response = api.reserve_jig(
            jig["id"],
            H.reservation_payload(staged["unit"]["id"], jig["version"], window=H.JIG_WINDOW_2),
            headers=WELD_SUPERVISOR,
        )

        validate_error(response, H.ERR_UNIT_BUILD_STATE_INVALID)
        assert H.read_jig(api, jig["id"])["reserved_minutes_total"] == 120
        assert H.read_unit(api, staged["unit"]["id"])["build_status"] == (
            H.BuildStatus.FRAME_WELDED
        )
        reservations, _meta = validate_paginated(
            api.list_unit_jig_reservations(staged["unit"]["id"], headers=WELD_SUPERVISOR)
        )
        assert len(reservations) == 1
        assert reservations[0]["status"] == H.ReservationStatus.CONSUMED

    def test_the_brake_stage_before_the_lighting_stage_is_out_of_order(self, api):
        """The stages are ordered on the compliance dimension, not the build one.

        PRD 3.4: "A stage submitted against the wrong compliance state — brakes
        before lamps, or lamps again on an already-verified trailer — is refused
        with `ERR_COMPLIANCE_STAGE_OUT_OF_ORDER`."

        Design: Corner/errors/error_brake_stage_before_the_lighting_stage_is_rejected
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_frame_welded(plant, api)
        assert staged["unit"]["gvwr_lbs"] == H.TA_CERTIFIED_GVWR_LBS

        response = api.install_systems(
            staged["unit"]["id"], H.brake_payload(1, True), headers=ASSEMBLY_TECH
        )

        validate_error(response, H.ERR_COMPLIANCE_STAGE_OUT_OF_ORDER)
        unit = H.read_unit(api, staged["unit"]["id"])
        H.assert_unit_dimensions(
            unit, H.BuildStatus.FRAME_WELDED, H.ComplianceStatus.NOT_VERIFIED
        )
        assert unit["installed_braked_axle_count"] is None
        assert unit["breakaway_kit_installed"] is False


class TestTerminalDecisionsAreFinal:
    def test_an_approved_claim_cannot_be_re_adjudicated(self, api):
        """A late DENY must not unwind money the approval already computed.

        PRD 3.9: "A review is admissible only while `status` is `SUBMITTED`;
        anything else is refused with `ERR_CLAIM_STATE_INVALID`."

        Design: Corner/errors/error_second_review_of_an_approved_claim_is_rejected
        """
        plant = H.setup_plant(api)
        staged = H.claim_submitted(plant, api)
        approved = H.review_claim(api, staged["claim"]["id"], H.ClaimDecision.APPROVE)
        H.assert_money(approved["reimbursement_total_cents"], H.CLAIM_GROSS_CENTS)

        response = api.review_claim(
            staged["claim"]["id"],
            H.review_payload(H.ClaimDecision.DENY, review_note="second thoughts"),
            headers=SALES_ADMIN,
        )

        validate_error(response, H.ERR_CLAIM_STATE_INVALID)
        after = H.read_claim(api, staged["claim"]["id"])
        assert after["status"] == H.ClaimStatus.APPROVED
        H.assert_money(after["reimbursement_total_cents"], H.CLAIM_GROSS_CENTS)
        assert after["denial_reason"] is None
        assert after["shipped_line_count"] == 0

    def test_a_retested_trailer_that_still_holds_its_label_cannot_be_labelled_again(self, api):
        """A passed re-test returns the trailer to ROAD_TEST_PASSED with the label intact.

        PRD 3.7: "The trailer must carry no certification label whose `status` is
        `ISSUED`, and a second attempt is refused with `ERR_LABEL_ALREADY_ISSUED`."

        Design: Corner/errors/error_second_certification_label_on_a_retested_unit_is_rejected
        """
        plant = H.setup_plant(api)
        staged = H.unit_in_stock(plant, api)
        retest = H.book_road_test(
            api, staged["unit"]["id"], plant["lane"]["id"], window=H.RETEST_WINDOW
        )
        H.record_road_test_result(api, retest["id"])
        assert H.read_unit(api, staged["unit"]["id"])["build_status"] == (
            H.BuildStatus.ROAD_TEST_PASSED
        )

        response = api.issue_label(
            staged["unit"]["id"], H.label_payload(), headers=CERT_OFFICER_2
        )

        validate_error(response, H.ERR_LABEL_ALREADY_ISSUED)
        labels, _meta = validate_paginated(
            api.list_labels(staged["unit"]["id"], headers=SALES_ADMIN)
        )
        assert len(labels) == 1
        assert labels[0]["status"] == H.LabelStatus.ISSUED
        assert labels[0]["vin_sequence"] == 1
        assert labels[0]["vin"] == H.VIN_FIRST
        unit = H.read_unit(api, staged["unit"]["id"])
        assert unit["vin"] == H.VIN_FIRST
        assert unit["build_status"] == H.BuildStatus.ROAD_TEST_PASSED

    def test_a_passed_road_test_cannot_be_resulted_a_second_time(self, api):
        """A late failing result cannot reverse a test that already passed.

        PRD 3.6: "A result may only be recorded against a test whose `status` is
        `SCHEDULED` and whose trailer is in `build_status` `ROAD_TEST_PENDING`; a
        second attempt on an already-resulted test is refused with
        `ERR_ROAD_TEST_ALREADY_RESULTED`."

        Design: Corner/errors/error_second_result_on_the_same_road_test_is_rejected
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_road_test_passed(plant, api)

        response = api.record_road_test_result(
            staged["road_test"]["id"],
            H.road_test_result_payload(
                brake_stop_distance_ft=44.0,
                lighting_check_passed=False,
                result_notes="late failure report",
            ),
            headers=QUALITY_INSPECTOR,
        )

        validate_error(response, H.ERR_ROAD_TEST_ALREADY_RESULTED)
        road_test = H.read_road_test(api, staged["road_test"]["id"])
        assert road_test["status"] == H.RoadTestStatus.PASSED
        assert road_test["brake_stop_distance_ft"] == 32.5
        H.assert_unit_dimensions(
            H.read_unit(api, staged["unit"]["id"]),
            H.BuildStatus.ROAD_TEST_PASSED,
            H.ComplianceStatus.FULLY_COMPLIANT,
        )

    def test_a_signed_off_option_line_can_no_longer_be_removed(self, api):
        """Removal is a PENDING-only operation, so the weight aggregate cannot drop.

        PRD 3.5: "Only a `PENDING` line may be signed off or removed; a `COMPLETED`
        or already-`REMOVED` line is refused with `ERR_OPTION_NOT_REMOVABLE`."

        Design: Corner/errors/error_completed_option_install_cannot_be_removed
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_frame_welded(plant, api)
        option = H.charge_option(
            api,
            staged["unit"]["id"],
            option_code="E_TRACK_KIT",
            quantity=3,
            unit_weight_lbs=20,
            unit_price_cents=6650,
            labor_hours=1.0,
        )
        H.complete_option(api, option["id"])

        response = api.delete_option_install(
            option["id"],
            H.removal_payload(removal_reason="dealer changed the spec"),
            headers=ASSEMBLY_TECH,
        )

        validate_error(response, H.ERR_OPTION_NOT_REMOVABLE)
        assert H.read_option_install(api, option["id"])["status"] == H.OptionStatus.COMPLETED
        unit = H.read_unit(api, staged["unit"]["id"])
        assert unit["curb_weight_lbs"] == 2040
        assert unit["payload_capacity_lbs"] == 4260
        H.assert_weight_budget_balances(unit)

    def test_no_build_record_may_be_opened_against_a_withdrawn_model(self, api):
        """The withdrawn model keeps its certified rating yet accepts no new trailers.

        PRD 3.1: "A `WITHDRAWN` model accepts no further decisions and no new
        trailers: opening a build record against it is refused with
        `ERR_MODEL_NOT_BUILDABLE`, while `DRAFT`, `IN_ENGINEERING_REVIEW` and
        `CERTIFIED` models all accept new build records."

        Design: Corner/errors/error_unit_creation_against_a_withdrawn_model_is_rejected
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        H.submit_model(api, model["id"], engineering_note="revision package")
        withdrawn = H.decide_model(api, model["id"], H.CertificationDecision.WITHDRAWN)
        assert withdrawn["certification_status"] == H.CertificationStatus.WITHDRAWN

        response = api.create_unit(H.unit_payload(model["id"]), headers=WELD_SUPERVISOR)

        validate_error(response, H.ERR_MODEL_NOT_BUILDABLE)
        after = H.read_model(api, model["id"])
        assert after["active_unit_count"] == 0
        assert after["certified_gvwr_lbs"] == H.TA_CERTIFIED_GVWR_LBS

    def test_a_trailer_still_on_the_weld_floor_cannot_be_named_in_an_allocation(self, api):
        """The explicit override still has to satisfy the eligibility predicate.

        PRD 3.8: "Supplying a `unit_id` instead is the **explicit override**: no
        ranking runs, but the named trailer must itself satisfy the same
        eligibility predicate — `build_status` `RELEASED_TO_STOCK`,
        `dealer_order_id` null, and an `ISSUED` label — and a trailer that does not
        is refused with `ERR_UNIT_NOT_ALLOCATABLE`."

        Design: Corner/errors/error_explicit_allocation_of_a_unit_not_in_stock_is_rejected
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_frame_welded(plant, api)
        order = H.place_order(api, plant["dealer"]["id"], plant["model"]["id"])
        dealer_version = H.read_dealer(api, plant["dealer"]["id"])["version"]

        response = api.allocate_order(
            order["id"],
            H.allocation_payload(dealer_version, unit_id=staged["unit"]["id"]),
            headers=SALES_ADMIN,
        )

        validate_error(response, H.ERR_UNIT_NOT_ALLOCATABLE)
        pending = H.read_order(api, order["id"])
        assert pending["status"] == H.OrderStatus.PENDING
        assert pending["invoice_total_cents"] is None
        unit = H.read_unit(api, staged["unit"]["id"])
        assert unit["build_status"] == H.BuildStatus.FRAME_WELDED
        assert unit["dealer_order_id"] is None
        H.assert_floor_plan_conserved(H.read_dealer(api, plant["dealer"]["id"]), 0)

    def test_a_trailer_in_systems_rework_is_bookable_but_not_compliant(self, api):
        """The failure cascade leaves a state pair only the compliance gate refuses.

        PRD 3.6: "The trailer's `compliance_status` must be `FULLY_COMPLIANT`, and
        anything else is refused with `ERR_UNIT_NOT_COMPLIANT`."

        Design: Corner/errors/error_retest_booking_on_a_non_compliant_unit_is_rejected
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_systems_installed(plant, api)
        road_test = H.book_road_test(api, staged["unit"]["id"], plant["lane"]["id"])
        H.record_road_test_result(
            api, road_test["id"], brake_stop_distance_ft=44.0, lighting_check_passed=True
        )
        failed = H.read_unit(api, staged["unit"]["id"])
        H.assert_unit_dimensions(
            failed, H.BuildStatus.SYSTEMS_REWORK, H.ComplianceStatus.NON_COMPLIANT
        )

        response = api.book_road_test(
            staged["unit"]["id"],
            H.road_test_payload(plant["lane"]["id"], window=H.RETEST_WINDOW),
            headers=QUALITY_INSPECTOR,
        )

        validate_error(response, H.ERR_UNIT_NOT_COMPLIANT)
        tests, _meta = validate_paginated(
            api.list_unit_road_tests(staged["unit"]["id"], headers=QUALITY_INSPECTOR)
        )
        assert len(tests) == 1
        assert tests[0]["status"] == H.RoadTestStatus.FAILED
        after = H.read_unit(api, staged["unit"]["id"])
        H.assert_unit_dimensions(
            after, H.BuildStatus.SYSTEMS_REWORK, H.ComplianceStatus.NON_COMPLIANT
        )
        assert after["rework_cycle_count"] == 1
