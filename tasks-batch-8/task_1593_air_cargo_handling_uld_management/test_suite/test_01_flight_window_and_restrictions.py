"""Flight registration defaults and the booking-window state machine."""
from test_helpers import (
    ApiErrorId,
    assert_flight,
    close_flight,
    create_flight_payload,
    create_weight_restriction_payload,
    depart_flight,
    get_flight,
    impose_weight_restriction,
    make_accepted_booking,
    make_booking,
    make_flight,
    make_open_flight,
    make_uld_type_and_unit,
    create_build_up_plan,
    validate_error,
    validate_success,
)


class TestFlightCreation:
    def test_flight_created_with_zeroed_computed_fields(
        self, api, capacity_controller_headers
    ):
        """PRD §3.1: "A new flight starts in `SCHEDULED` status with its
        allocation counters at zero and no weight restriction."
        PRD §2.6: "All three counters start at zero when a flight is registered"
        PRD §2.6: "`weight_restriction_kg` records an active restricted payload
        imposed on the flight; it is `null` when no restriction is in force."

        Design: Corner/entities/flight_created_with_zeroed_computed_fields
        """
        res = api.create_flight(
            create_flight_payload(
                flight_number="CA301",
                origin="LAX",
                destination="HKG",
                max_payload_kg=5000,
                max_volume_m3=50,
                uld_position_count=4,
                dg_certified=False,
            ),
            capacity_controller_headers,
        )
        flight = validate_success(res, 201)
        assert_flight(flight)
        assert flight["status"] == "SCHEDULED", (
            f"Expected SCHEDULED, got {flight['status']}"
        )
        assert flight["allocated_weight_kg"] == 0
        assert flight["allocated_volume_m3"] == 0
        assert flight["reserved_positions"] == 0
        assert flight.get("weight_restriction_kg") is None
        assert isinstance(flight["version"], int)


class TestFlightWindowTransitions:
    def test_depart_from_open_flight_rejected(self, api, capacity_controller_headers):
        """PRD §3.8: "Departure is the flight's terminal act and belongs to the
        `CapacityController`; it requires the flight to be `CLOSED`, with any
        other state rejected as `ERR_FLIGHT_NOT_CLOSED`."

        Design: Corner/state_machines/depart_from_open_flight_rejected
        """
        flight = make_open_flight(flight_number="CA307")
        res = api.depart_flight(flight["id"], capacity_controller_headers)
        validate_error(res, ApiErrorId.ERR_FLIGHT_NOT_CLOSED)
        assert get_flight(flight["id"])["status"] == "OPEN_FOR_BOOKING", (
            "Failed departure must not mutate the flight"
        )

    def test_close_with_draft_plan_rejected(self, api, capacity_controller_headers):
        """PRD §3.1: "Closing the window requires the flight to be
        `OPEN_FOR_BOOKING` (again `ERR_FLIGHT_NOT_OPEN` otherwise) and
        additionally requires that no build-up plan on the flight remains in
        `DRAFT` — closing with an unfinished plan is rejected with
        `ERR_DRAFT_PLANS_EXIST`, since a plan must either be sealed or cancelled
        before the flight is frozen."

        Design: Corner/state_machines/close_with_draft_plan_rejected
        """
        flight = make_open_flight(flight_number="CA308")
        _uld_type, uld = make_uld_type_and_unit()
        create_build_up_plan(flight["id"], uld["id"])
        res = api.close_flight(flight["id"], capacity_controller_headers)
        validate_error(res, ApiErrorId.ERR_DRAFT_PLANS_EXIST)
        assert get_flight(flight["id"])["status"] == "OPEN_FOR_BOOKING"

    def test_weight_restriction_on_departed_flight_rejected(
        self, api, capacity_controller_headers
    ):
        """PRD §3.7: "a `CapacityController` can impose a restricted payload on
        a flight by supplying `restricted_payload_kg`, provided the flight is
        `OPEN_FOR_BOOKING` or `CLOSED` (any other state draws
        `ERR_FLIGHT_NOT_OPEN`)"

        Design: Corner/state_machines/weight_restriction_on_departed_flight_rejected
        """
        flight = make_open_flight(flight_number="CA314")
        close_flight(flight["id"])
        depart_flight(flight["id"])
        res = api.impose_weight_restriction(
            flight["id"],
            create_weight_restriction_payload(100),
            capacity_controller_headers,
        )
        validate_error(res, ApiErrorId.ERR_FLIGHT_NOT_OPEN)


class TestBookingAcceptanceWindow:
    def test_accept_on_scheduled_flight_rejected(self, api, capacity_controller_headers):
        """PRD §3.2: "The booking must be `REQUESTED` (any other state draws
        `ERR_BOOKING_INVALID_STATE`), and its flight must be `OPEN_FOR_BOOKING`
        (`ERR_FLIGHT_NOT_OPEN` otherwise)."

        Design: Corner/errors/accept_on_scheduled_flight_rejected
        """
        flight = make_flight(flight_number="CA339")  # never opened
        booking = make_booking(flight["id"], shipper_ref="SHP-SC")
        res = api.accept_booking(booking["id"], capacity_controller_headers)
        validate_error(res, ApiErrorId.ERR_FLIGHT_NOT_OPEN)
        assert get_flight(flight["id"])["allocated_weight_kg"] == 0, (
            "A failed acceptance must not debit the allocation pool"
        )


class TestWeightRestrictionWithoutOffload:
    def test_weight_restriction_above_allocation_offloads_nothing(
        self, api, capacity_controller_headers
    ):
        """PRD §3.7: "If that reduction is zero or negative, the flight already
        fits and no booking is offloaded — only the restriction itself is
        recorded."

        Design: Corner/cross_cutting_layers/weight_restriction_above_allocation_offloads_nothing
        """
        flight = make_open_flight(
            flight_number="CA342", max_payload_kg=1200, max_volume_m3=100
        )
        b1 = make_accepted_booking(
            flight["id"], shipper_ref="SHP-NO1", gross_weight_kg=300
        )
        b2 = make_accepted_booking(
            flight["id"], shipper_ref="SHP-NO2", gross_weight_kg=400
        )
        updated = impose_weight_restriction(flight["id"], 1200)
        assert updated["weight_restriction_kg"] == 1200, (
            f"Restriction must be recorded, got {updated['weight_restriction_kg']}"
        )
        assert get_booking_status(api, b1["id"], capacity_controller_headers) == "ACCEPTED"
        assert get_booking_status(api, b2["id"], capacity_controller_headers) == "ACCEPTED"


def get_booking_status(api, booking_id, headers):
    return validate_success(api.get_booking(booking_id, headers))["status"]
