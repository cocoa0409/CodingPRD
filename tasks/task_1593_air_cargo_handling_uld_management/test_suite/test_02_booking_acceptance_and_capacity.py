"""Booking intake, chargeable weight, capacity accounting, and monitoring."""
from test_helpers import (
    ApiErrorId,
    assert_booking,
    assert_money,
    create_booking_payload,
    get_booking,
    get_flight,
    make_accepted_booking,
    make_booking,
    make_flight,
    make_forwarder_headers,
    make_open_flight,
    record_temperature,
    validate_error,
    validate_success,
)


class TestChargeableWeight:
    def test_booking_chargeable_weight_volumetric_dominates(
        self, api, forwarder_agent_headers
    ):
        """PRD §3.2: "the volumetric weight is the booking's `volume_m3`
        multiplied by the standard volumetric factor of 167.0 kilograms per
        cubic metre, and the chargeable weight is the greater of the actual
        `gross_weight_kg` and that volumetric weight, rounded half-up to two
        decimal places."

        Design: Corner/entities/booking_chargeable_weight_volumetric_dominates
        """
        flight = make_flight(flight_number="CA302", max_payload_kg=5000)
        dense_volume = validate_success(
            api.create_booking(
                create_booking_payload(
                    flight["id"], shipper_ref="SHP-V1",
                    gross_weight_kg=10, volume_m3=0.5,
                ),
                forwarder_agent_headers,
            ),
            201,
        )
        assert_booking(dense_volume)
        assert_money(dense_volume["chargeable_weight_kg"], 83.5)  # max(10, 0.5*167.0)

        dense_mass = validate_success(
            api.create_booking(
                create_booking_payload(
                    flight["id"], shipper_ref="SHP-V2",
                    gross_weight_kg=100, volume_m3=0.1,
                ),
                forwarder_agent_headers,
            ),
            201,
        )
        assert_money(dense_mass["chargeable_weight_kg"], 100)  # max(100, 16.7)

    def test_booking_missing_required_gross_returns_invalid_request(
        self, api, forwarder_agent_headers
    ):
        """PRD §3.2: "a piece count `pieces` of at least 1, and the actual
        `gross_weight_kg` and `volume_m3`, each greater than 0"
        PRD §2.7: "Required fields must be present, types must be valid, and
        enum fields must be within their declared values ... Any violation
        yields `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/booking_missing_required_gross_returns_invalid_request
        """
        flight = make_flight(flight_number="CA303", max_payload_kg=5000)
        payload = create_booking_payload(flight["id"], shipper_ref="SHP-M1")
        del payload["gross_weight_kg"]
        res = api.create_booking(payload, forwarder_agent_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestFlightCapacityBoundaries:
    def test_accept_at_payload_equality_boundary_accepted(
        self, api, capacity_controller_headers
    ):
        """PRD §3.2: "acceptance requires the committed weight plus the
        candidate's `gross_weight_kg` to be less than or equal to
        `max_payload_kg`, with equality accepted and only a strictly-greater
        result rejected as `ERR_FLIGHT_PAYLOAD_EXCEEDED`"

        Design: Difficulty/boundary_precision_check/flight_payload_equality_accepted
        """
        flight = make_open_flight(
            flight_number="CA213", max_payload_kg=1000, max_volume_m3=100
        )
        make_accepted_booking(
            flight["id"], shipper_ref="SHP-B1", gross_weight_kg=600, volume_m3=1
        )
        candidate = make_booking(
            flight["id"], shipper_ref="SHP-B2", gross_weight_kg=400, volume_m3=1
        )
        accepted = validate_success(
            api.accept_booking(candidate["id"], capacity_controller_headers)
        )
        assert accepted["status"] == "ACCEPTED", (
            "600 + 400 == 1000 == max_payload: equality must be accepted"
        )
        assert_money(get_flight(flight["id"])["allocated_weight_kg"], 1000)

    def test_accept_strictly_above_payload_boundary_rejected(
        self, api, capacity_controller_headers
    ):
        """PRD §3.2: "acceptance requires the committed weight plus the
        candidate's `gross_weight_kg` to be less than or equal to
        `max_payload_kg`, with equality accepted and only a strictly-greater
        result rejected as `ERR_FLIGHT_PAYLOAD_EXCEEDED`"

        Design: Difficulty/boundary_precision_check/flight_payload_equality_accepted
        """
        flight = make_open_flight(
            flight_number="CA213", max_payload_kg=1000, max_volume_m3=100
        )
        make_accepted_booking(
            flight["id"], shipper_ref="SHP-B1", gross_weight_kg=600, volume_m3=1
        )
        make_accepted_booking(
            flight["id"], shipper_ref="SHP-B2", gross_weight_kg=400, volume_m3=1
        )
        over = make_booking(
            flight["id"], shipper_ref="SHP-B3", gross_weight_kg=0.1, volume_m3=0.1
        )
        res = api.accept_booking(over["id"], capacity_controller_headers)
        validate_error(res, ApiErrorId.ERR_FLIGHT_PAYLOAD_EXCEEDED)
        assert get_booking(over["id"])["status"] == "REQUESTED", (
            "A rejected acceptance must leave the booking REQUESTED"
        )

    def test_accept_volume_boundary_exceeded(self, api, capacity_controller_headers):
        """PRD §3.2: "the committed volume plus the candidate's `volume_m3` to
        be less than or equal to `max_volume_m3`, likewise equality-accepted,
        with a strictly-greater overflow rejected as
        `ERR_FLIGHT_VOLUME_EXCEEDED`."

        Design: Corner/validations/accept_volume_boundary_exceeded
        """
        flight = make_open_flight(
            flight_number="CA318", max_payload_kg=1000, max_volume_m3=10
        )
        make_accepted_booking(
            flight["id"], shipper_ref="SHP-V3", gross_weight_kg=1, volume_m3=10
        )
        candidate = make_booking(
            flight["id"], shipper_ref="SHP-V4", gross_weight_kg=1, volume_m3=0.1
        )
        res = api.accept_booking(candidate["id"], capacity_controller_headers)
        validate_error(res, ApiErrorId.ERR_FLIGHT_VOLUME_EXCEEDED)

    def test_capacity_excludes_terminal_and_requested_bookings(
        self, api, capacity_controller_headers
    ):
        """PRD §2.6: "`allocated_weight_kg` is the sum of `gross_weight_kg` over
        the flight's bookings whose status is `ACCEPTED` or `BUILT_UP`, and
        nothing else — bookings in `REQUESTED`, `OFFLOADED`, `REJECTED`,
        `CANCELLED`, or `LOADED` status are excluded from the sum."

        Design: Corner/calculations/capacity_excludes_terminal_and_requested_bookings
        """
        flight = make_open_flight(
            flight_number="CA315", max_payload_kg=1000, max_volume_m3=100
        )
        make_accepted_booking(
            flight["id"], shipper_ref="SHP-F3", gross_weight_kg=800, volume_m3=1
        )
        rejected = make_booking(
            flight["id"], shipper_ref="SHP-F4", gross_weight_kg=500, volume_m3=1
        )
        validate_success(
            api.reject_booking(
                rejected["id"], {"reason": "documentation incomplete"},
                capacity_controller_headers,
            )
        )
        candidate = make_booking(
            flight["id"], shipper_ref="SHP-F5", gross_weight_kg=200, volume_m3=1
        )
        accepted = validate_success(
            api.accept_booking(candidate["id"], capacity_controller_headers)
        )
        assert accepted["status"] == "ACCEPTED", (
            "800 + 200 == 1000 <= cap: the REJECTED 500kg booking must be excluded"
        )
        assert_money(get_flight(flight["id"])["allocated_weight_kg"], 1000)


class TestDangerousGoodsEmbargoPriority:
    def test_accept_dg_embargo_masks_payload_capacity(
        self, api, capacity_controller_headers
    ):
        """PRD §3.2: "The dangerous-goods embargo of §3.3 applies next, and
        then the two capacity rungs in order — payload first, then volume."
        PRD §3.3: "it may be accepted or rebooked only onto a flight whose
        `dg_certified` flag is true; any attempt against an uncertified flight
        is rejected with `ERR_FLIGHT_NOT_DG_CERTIFIED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/accept_dg_safety_beats_capacity_fiscal
        """
        flight = make_open_flight(
            flight_number="CA212", max_payload_kg=100, max_volume_m3=100,
            dg_certified=False,
        )
        make_accepted_booking(
            flight["id"], shipper_ref="SHP-P2", gross_weight_kg=100, volume_m3=1
        )
        dg_booking = make_booking(
            flight["id"], shipper_ref="SHP-P3", commodity_code="DG",
            gross_weight_kg=50, volume_m3=1, is_dangerous_goods=True,
        )
        res = api.accept_booking(dg_booking["id"], capacity_controller_headers)
        validate_error(res, ApiErrorId.ERR_FLIGHT_NOT_DG_CERTIFIED)
        assert get_booking(dg_booking["id"])["status"] == "REQUESTED", (
            "A failed acceptance must not mutate the booking"
        )

    def test_accept_dg_embargo_masks_volume_capacity(
        self, api, capacity_controller_headers
    ):
        """PRD §3.2: "The dangerous-goods embargo of §3.3 applies next, and
        then the two capacity rungs in order — payload first, then volume."
        PRD §3.3: "it may be accepted or rebooked only onto a flight whose
        `dg_certified` flag is true; any attempt against an uncertified flight
        is rejected with `ERR_FLIGHT_NOT_DG_CERTIFIED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/accept_dg_safety_beats_capacity_fiscal
        """
        flight = make_open_flight(
            flight_number="CA212", max_payload_kg=1000, max_volume_m3=10,
            dg_certified=False,
        )
        make_accepted_booking(
            flight["id"], shipper_ref="SHP-P2", gross_weight_kg=1, volume_m3=10
        )
        dg_booking = make_booking(
            flight["id"], shipper_ref="SHP-P3", commodity_code="DG",
            gross_weight_kg=50, volume_m3=0.1, is_dangerous_goods=True,
        )
        res = api.accept_booking(dg_booking["id"], capacity_controller_headers)
        validate_error(res, ApiErrorId.ERR_FLIGHT_NOT_DG_CERTIFIED)
        assert get_booking(dg_booking["id"])["status"] == "REQUESTED"


class TestAllocationConservation:
    def test_accept_debits_flight_allocation(self, api, capacity_controller_headers):
        """PRD §3.2: "On success the booking moves to `ACCEPTED`, its weight
        and volume are debited into `allocated_weight_kg` and
        `allocated_volume_m3`, and that mutation increments the flight's
        `version`"

        Design: Difficulty/compensating_invariant/flight_weight_accept_cancel_conservation
        """
        flight = make_open_flight(
            flight_number="CA219", max_payload_kg=1000, max_volume_m3=100
        )
        make_accepted_booking(
            flight["id"], shipper_ref="SHP-I1", gross_weight_kg=400, volume_m3=1
        )
        assert_money(get_flight(flight["id"])["allocated_weight_kg"], 400)
        candidate = make_booking(
            flight["id"], shipper_ref="SHP-I2", gross_weight_kg=200, volume_m3=1
        )
        validate_success(api.accept_booking(candidate["id"], capacity_controller_headers))
        assert_money(get_flight(flight["id"])["allocated_weight_kg"], 600)

    def test_cancel_accepted_booking_restores_allocation(self, api):
        """PRD §3.2: "cancelling from `ACCEPTED` compensates the acceptance
        debit, subtracting the booking's weight and volume from the flight's
        allocation counters."

        Design: Difficulty/compensating_invariant/flight_weight_accept_cancel_conservation
        """
        flight = make_open_flight(
            flight_number="CA219", max_payload_kg=1000, max_volume_m3=100
        )
        make_accepted_booking(
            flight["id"], shipper_ref="SHP-I1", gross_weight_kg=400, volume_m3=1
        )
        candidate = make_accepted_booking(
            flight["id"], shipper_ref="SHP-I2", gross_weight_kg=200, volume_m3=1
        )
        assert_money(get_flight(flight["id"])["allocated_weight_kg"], 600)
        cancelled = validate_success(
            api.cancel_booking(candidate["id"], make_forwarder_headers("fwd-1"))
        )
        assert cancelled["status"] == "CANCELLED"
        assert_money(get_flight(flight["id"])["allocated_weight_kg"], 400)


class TestImmediateConsistency:
    def test_effects_visible_immediately_in_same_response(
        self, api, capacity_controller_headers
    ):
        """PRD §2.6: "each subsequent debit or release is applied immediately,
        within the same request that caused it — there is no eventual
        consistency window."
        PRD §3.2: "On success the booking moves to `ACCEPTED`, its weight and
        volume are debited into `allocated_weight_kg` and
        `allocated_volume_m3`"

        Design: Corner/consistency_model/effects_visible_immediately_in_same_response
        """
        flight = make_open_flight(
            flight_number="CA343", max_payload_kg=1000, max_volume_m3=100
        )
        booking = make_booking(
            flight["id"], shipper_ref="SHP-IM", gross_weight_kg=250, volume_m3=1
        )
        accepted = validate_success(
            api.accept_booking(booking["id"], capacity_controller_headers)
        )
        assert accepted["status"] == "ACCEPTED", (
            "The mutation must be visible in the accept response itself"
        )
        observed = get_flight(flight["id"])
        assert_money(observed["allocated_weight_kg"], 250)
        assert_money(observed["allocated_volume_m3"], 1)


class TestTemperatureMonitoring:
    def test_temperature_excursion_inclusive_bounds_and_stickiness(
        self, api, ramp_operator_headers
    ):
        """PRD §3.5: "a reading is in range when `temperature_c` is greater
        than or equal to `temp_min_c` and less than or equal to `temp_max_c`,
        both bounds inclusive."
        PRD §3.5: "the booking's `temp_excursion_count` — defined as the count
        of its readings with `in_range` false — increments by one, and its
        `temp_status` moves to `EXCURSION`, which is sticky: no later in-range
        reading ever returns the booking to `IN_RANGE`."

        Design: Corner/calculations/temperature_excursion_inclusive_bounds_and_stickiness
        """
        flight = make_open_flight(flight_number="CA316", max_payload_kg=5000)
        booking = make_accepted_booking(
            flight["id"], shipper_ref="SHP-T2", commodity_code="PER",
            gross_weight_kg=100, volume_m3=1, temp_min_c=2.0, temp_max_c=8.0,
        )
        r1 = record_temperature(booking["id"], "2026-08-09T10:00:00Z", 2.0)
        r2 = record_temperature(booking["id"], "2026-08-09T11:00:00Z", 8.0)
        r3 = record_temperature(booking["id"], "2026-08-09T12:00:00Z", 8.1)
        r4 = record_temperature(booking["id"], "2026-08-09T13:00:00Z", 5.0)
        assert r1["in_range"] is True and r2["in_range"] is True, (
            "Bounds are inclusive: 2.0 and 8.0 must be in range"
        )
        assert r3["in_range"] is False, "8.1 exceeds the inclusive upper bound"
        assert r4["in_range"] is True
        observed = get_booking(booking["id"], ramp_operator_headers)
        assert observed["temp_excursion_count"] == 1
        assert observed["temp_status"] == "EXCURSION", (
            "EXCURSION is sticky: the later in-range reading must not clear it"
        )

    def test_temp_log_without_range_not_defined(self, api, ramp_operator_headers):
        """PRD §3.5: "the booking must actually define a range — a reading
        against an unmonitored booking is rejected with
        `ERR_TEMP_RANGE_NOT_DEFINED` (HTTP 422)."

        Design: Corner/validations/temp_log_without_range_not_defined
        """
        flight = make_open_flight(flight_number="CA320", max_payload_kg=5000)
        booking = make_accepted_booking(
            flight["id"], shipper_ref="SHP-N2", gross_weight_kg=50, volume_m3=1
        )
        res = api.create_temperature_log(
            booking["id"],
            {"recorded_at": "2026-08-09T10:00:00Z", "temperature_c": 5.0},
            ramp_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_TEMP_RANGE_NOT_DEFINED)
