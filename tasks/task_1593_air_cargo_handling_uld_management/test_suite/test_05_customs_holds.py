"""Customs holds: singleton guard, release lifecycle, and the build-up gate."""
from test_helpers import (
    ApiErrorId,
    create_build_up_plan,
    get_booking,
    make_accepted_booking,
    make_booking,
    make_open_flight,
    make_uld_type_and_unit,
    place_customs_hold,
    release_customs_hold,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestHoldSingletonGuard:
    def test_second_customs_hold_rejected_while_active(
        self, api, customs_officer_headers
    ):
        """PRD §3.6: "a booking carries at most one `ACTIVE` hold: placing a
        second while one is outstanding is refused with
        `ERR_HOLD_ALREADY_ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/customs_hold_containment_overlap
        """
        flight = make_open_flight(flight_number="CA218", max_payload_kg=5000)
        booking = make_booking(
            flight["id"], shipper_ref="SHP-H1", gross_weight_kg=100, volume_m3=1
        )
        place_customs_hold(booking["id"], reason_code="DOC_CHECK")
        res = api.create_customs_hold(
            booking["id"], {"reason_code": "INSPECTION"}, customs_officer_headers
        )
        validate_error(res, ApiErrorId.ERR_HOLD_ALREADY_ACTIVE)

    def test_customs_hold_accepted_after_prior_release(
        self, api, customs_officer_headers
    ):
        """PRD §3.6: "the release stamps `released_at` from the logical clock,
        stores the note, and moves the hold to `RELEASED`, its terminal state."
        PRD §3.6: "a booking carries at most one `ACTIVE` hold: placing a
        second while one is outstanding is refused with
        `ERR_HOLD_ALREADY_ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/customs_hold_containment_overlap
        """
        flight = make_open_flight(flight_number="CA218", max_payload_kg=5000)
        booking = make_booking(
            flight["id"], shipper_ref="SHP-H1", gross_weight_kg=100, volume_m3=1
        )
        first = place_customs_hold(booking["id"], reason_code="DOC_CHECK")
        released = release_customs_hold(first["id"], release_note="cleared")
        assert released["status"] == "RELEASED"
        second = validate_success(
            api.create_customs_hold(
                booking["id"], {"reason_code": "INSPECTION"}, customs_officer_headers
            ),
            201,
        )
        assert second["status"] == "ACTIVE", (
            "Once the prior hold is RELEASED a new hold may be placed"
        )


class TestHoldReleaseLifecycle:
    def test_released_hold_cannot_release_again(self, api, customs_officer_headers):
        """PRD §3.6: "only an `ACTIVE` hold can be released, anything else
        drawing `ERR_HOLD_NOT_ACTIVE`"

        Design: Corner/state_machines/released_hold_cannot_release_again
        """
        flight = make_open_flight(flight_number="CA311", max_payload_kg=5000)
        booking = make_booking(
            flight["id"], shipper_ref="SHP-H2", gross_weight_kg=100, volume_m3=1
        )
        hold = place_customs_hold(booking["id"], reason_code="DOC_CHECK")
        release_customs_hold(hold["id"], release_note="cleared")
        res = api.release_customs_hold(
            hold["id"], {"release_note": "again"}, customs_officer_headers
        )
        validate_error(res, ApiErrorId.ERR_HOLD_NOT_ACTIVE)


class TestCustomsGateAtAssignment:
    def test_assign_blocked_while_customs_hold_active(self, api, ramp_operator_headers):
        """PRD §3.6: "any booking with an `ACTIVE` hold is refused at
        assignment with `ERR_CUSTOMS_HOLD_ACTIVE` (HTTP 409), keeping detained
        cargo off aircraft regardless of how otherwise ready it is."

        Design: Difficulty/cross_entity_state_dependency/assign_blocked_by_active_customs_hold
        """
        flight = make_open_flight(flight_number="CA215", max_payload_kg=5000)
        _uld_type, uld = make_uld_type_and_unit(uld_code="AKE00011CA")
        booking = make_accepted_booking(
            flight["id"], shipper_ref="SHP-X1", gross_weight_kg=100, volume_m3=1
        )
        place_customs_hold(booking["id"], reason_code="INSPECTION")
        plan = create_build_up_plan(flight["id"], uld["id"])
        res = api.assign_booking_to_plan(
            plan["id"],
            {
                "booking_id": booking["id"],
                "expected_build_up_plan_version": plan["version"],
            },
            ramp_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_CUSTOMS_HOLD_ACTIVE)
        assert get_booking(booking["id"], ramp_operator_headers)["status"] == "ACCEPTED"

    def test_assign_succeeds_after_customs_hold_released(
        self, api, ramp_operator_headers
    ):
        """PRD §3.6: "With the hold no longer `ACTIVE`, the booking's path into
        a build-up plan reopens."
        PRD §3.4: "A successful assignment moves the booking `ACCEPTED →
        BUILT_UP`, sets its `build_up_plan_id` to the plan, adds its
        `gross_weight_kg` into the plan's `total_weight_kg`, and increments the
        plan's `version`."

        Design: Difficulty/cross_entity_state_dependency/assign_blocked_by_active_customs_hold
        """
        flight = make_open_flight(flight_number="CA215", max_payload_kg=5000)
        _uld_type, uld = make_uld_type_and_unit(uld_code="AKE00011CA")
        booking = make_accepted_booking(
            flight["id"], shipper_ref="SHP-X1", gross_weight_kg=100, volume_m3=1
        )
        hold = place_customs_hold(booking["id"], reason_code="INSPECTION")
        plan = create_build_up_plan(flight["id"], uld["id"])
        release_customs_hold(hold["id"], release_note="docs verified")
        updated = validate_success(
            api.assign_booking_to_plan(
                plan["id"],
                {
                    "booking_id": booking["id"],
                    "expected_build_up_plan_version": plan["version"],
                },
                ramp_operator_headers,
            )
        )
        assert updated["total_weight_kg"] == 100
        observed = get_booking(booking["id"], ramp_operator_headers)
        assert observed["status"] == "BUILT_UP"
        assert observed.get("build_up_plan_id") == plan["id"]


class TestStateErrorMasksCustomsGate:
    def test_assign_state_error_masks_active_hold(self, api, ramp_operator_headers):
        """PRD §3.4: "Its checks fire in ladder order: state first — the plan
        must be `DRAFT` (`ERR_PLAN_NOT_DRAFT`), the booking must be `ACCEPTED`
        (`ERR_BOOKING_NOT_ACCEPTED`), and the plan's version must match the
        supplied expectation (`ERR_STALE_PLAN_VERSION`); then the safety gates
        — no `ACTIVE` customs hold on the booking (`ERR_CUSTOMS_HOLD_ACTIVE`)"
        PRD §2.7: "A failure at any rung stops evaluation immediately and
        produces that rung's error, so an earlier failure always masks later
        ones."

        Design: Difficulty/priority_pair_validation_conflict/assign_state_beats_customs_safety
        """
        flight = make_open_flight(flight_number="CA211", max_payload_kg=5000)
        _uld_type, uld = make_uld_type_and_unit(uld_code="AKE00008CA")
        booking = make_booking(  # stays REQUESTED — never accepted
            flight["id"], shipper_ref="SHP-P1", gross_weight_kg=100, volume_m3=1
        )
        place_customs_hold(booking["id"], reason_code="DOC_CHECK")
        plan = create_build_up_plan(flight["id"], uld["id"])
        res = api.assign_booking_to_plan(
            plan["id"],
            {
                "booking_id": booking["id"],
                "expected_build_up_plan_version": plan["version"],
            },
            ramp_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_BOOKING_NOT_ACCEPTED)

    def test_assign_state_error_masks_active_hold_after_reject(
        self, api, capacity_controller_headers, ramp_operator_headers
    ):
        """PRD §3.4: "Its checks fire in ladder order: state first — the plan
        must be `DRAFT` (`ERR_PLAN_NOT_DRAFT`), the booking must be `ACCEPTED`
        (`ERR_BOOKING_NOT_ACCEPTED`), and the plan's version must match the
        supplied expectation (`ERR_STALE_PLAN_VERSION`); then the safety gates
        — no `ACTIVE` customs hold on the booking (`ERR_CUSTOMS_HOLD_ACTIVE`)"
        PRD §2.7: "A failure at any rung stops evaluation immediately and
        produces that rung's error, so an earlier failure always masks later
        ones."

        Design: Difficulty/priority_pair_validation_conflict/assign_state_beats_customs_safety
        """
        flight = make_open_flight(flight_number="CA211", max_payload_kg=5000)
        _uld_type, uld = make_uld_type_and_unit(uld_code="AKE00008CA")
        booking = make_booking(
            flight["id"], shipper_ref="SHP-P1", gross_weight_kg=100, volume_m3=1
        )
        hold = place_customs_hold(booking["id"], reason_code="DOC_CHECK")
        validate_success(
            api.reject_booking(
                booking["id"], {"reason": "no capacity"}, capacity_controller_headers
            )
        )
        plan = create_build_up_plan(flight["id"], uld["id"])
        res = api.assign_booking_to_plan(
            plan["id"],
            {
                "booking_id": booking["id"],
                "expected_build_up_plan_version": plan["version"],
            },
            ramp_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_BOOKING_NOT_ACCEPTED)
        holds, _meta = validate_paginated(
            api.list_customs_holds(booking["id"], ramp_operator_headers)
        )
        assert holds[0]["status"] == "ACTIVE", (
            "The state-rung failure must leave the outstanding hold untouched"
        )
