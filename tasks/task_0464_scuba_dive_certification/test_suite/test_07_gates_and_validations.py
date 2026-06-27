"""Business-rule validations: cert/medical/waiver gates, o2 band, instructor
rating, duplicate and capacity checks, expired-waiver temporal gate.

Queue B (Corner): section validations.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_shop_admin_headers, make_instructor_headers,
    create_diver, create_course, create_instructor, create_boat, create_enrollment,
    create_session, sign_waiver, create_waiver_cleared_diver, set_clock,
    book_seat, certify_diver_open_water, setup_nitrox_certified_diver,
    setup_trip_with_certified_diver,
)
from test_helpers import factories as f
from test_helpers import ApiErrorId

ADMIN = make_shop_admin_headers()


class TestCertAndGasGates:
    def test_nitrox_fill_without_cert_rejected(self, api):
        """PRD 3.9: "A `NITROX` fill additionally requires the diver to be
        nitrox-certified, else `ERR_CERT_PREREQUISITE_NOT_MET` (HTTP 422)."

        Design: Corner/validations/nitrox_fill_without_cert_rejected
        """
        diver = create_diver(full_name="NoNitrox Ned")
        resp = api.create_fill_service(
            f.create_fill_service_payload(
                diver["id"], gas="NITROX", o2_pct=32, tank_capacity_liters=12
            ), ADMIN,
        )
        validate_error(
            resp, ApiErrorId.ERR_CERT_PREREQUISITE_NOT_MET.value, expected_status=422
        )

    def test_nitrox_o2_out_of_band_rejected(self, api):
        """PRD 3.9: "Oxygen percentage is constrained by gas: for `AIR` it must be
        exactly 21, and for `NITROX` it must be between 22 and 40 inclusive; a value
        outside the gas-appropriate range is malformed (`ERR_INVALID_REQUEST`, HTTP
        400)."

        Design: Corner/validations/nitrox_o2_out_of_band_rejected
        """
        diver = setup_nitrox_certified_diver()
        resp = api.create_fill_service(
            f.create_fill_service_payload(
                diver["id"], gas="NITROX", o2_pct=45, tank_capacity_liters=12
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestSchedulingAndBookingConstraints:
    def test_divemaster_cannot_lead_session(self, api):
        """PRD 3.4: "the named `primary_instructor_id` must reference an instructor
        rated `INSTRUCTOR`, and that instructor must not already lead another
        `SCHEDULED` session whose window overlaps the new one."
        PRD 3.4: "A non-`INSTRUCTOR` rating or a genuine window overlap is rejected
        with `ERR_INSTRUCTOR_CONFLICT` (HTTP 409)."

        Design: Corner/validations/instructor_rating_divemaster_cannot_lead_session
        """
        course = create_course()
        dm = create_instructor(full_name="Dm Dan", rating="DIVEMASTER")
        resp = api.create_session(
            f.create_session_payload(
                course["id"], dm["id"], session_type="OPEN_WATER",
                starts_at="2026-07-01T08:00:00Z", ends_at="2026-07-01T10:00:00Z",
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_CONFLICT.value)

    def test_duplicate_session_booking_rejected(self, api):
        """PRD 3.5: "And the booking must not duplicate an existing one: at most one
        non-terminal session booking may exist for a given enrollment-and-session
        pair, with a second rejected by `ERR_DUPLICATE_BOOKING` (HTTP 409)."

        Design: Corner/validations/duplicate_session_booking_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor(full_name="Dup Inst")
        diver = create_waiver_cleared_diver(full_name="Dup Deb")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-06-10T08:00:00Z", ends_at="2026-06-10T10:00:00Z",
        )
        enr = create_enrollment(diver["id"], course["id"])
        book_seat(session["id"], enr["id"], session["version"])
        sess_now = get_success_data(api.get_session(session["id"], ADMIN))
        resp = api.create_session_booking(
            f.create_session_booking_payload(
                session["id"], enr["id"], sess_now["version"]
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BOOKING.value)

    def test_trip_capacity_exceeded_at_boat_limit(self, api):
        """PRD 3.7: "the capacity check — the booking must not push
        `confirmed_divers` above the boat's `capacity`, else `ERR_CAPACITY_EXCEEDED`
        (HTTP 409)".

        Design: Corner/validations/trip_capacity_exceeded_at_boat_limit
        """
        # Boat capacity 1; first cert-cleared diver books, second is over capacity.
        boat, trip, diver1 = setup_trip_with_certified_diver(
            trip_overrides={"min_cert_level": "OPEN_WATER",
                            "base_fare_cents": 10000, "fill_addon_cents": 0},
            diver_full_name="First Fay",
        )
        # Shrink: boat capacity in the fixture is 10, so instead use a dedicated
        # capacity-1 boat with a fresh trip and certify two divers.
        small_boat = create_boat(name="Tiny", capacity=1)
        trip1 = get_success_data(
            api.create_dive_trip(
                f.create_dive_trip_payload(
                    small_boat["id"], starts_at="2026-06-25T08:00:00Z",
                    ends_at="2026-06-25T12:00:00Z", min_cert_level="OPEN_WATER",
                    base_fare_cents=10000, fill_addon_cents=0,
                ), ADMIN,
            )
        )
        diver2 = certify_diver_open_water(diver_full_name="Second Sue")[0]
        diver2 = get_success_data(api.get_diver(diver2["id"], ADMIN))
        # diver1 is already cert-cleared from the fixture.
        booking1 = validate_success(
            api.create_trip_booking(
                f.create_trip_booking_payload(
                    trip1["id"], diver1["id"], trip1["version"], tanks=0, party_size=1
                ), ADMIN,
            ), expected_status=201,
        )
        trip1_now = get_success_data(api.get_dive_trip(trip1["id"], ADMIN))
        resp = api.create_trip_booking(
            f.create_trip_booking_payload(
                trip1["id"], diver2["id"], trip1_now["version"], tanks=0, party_size=1
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)


class TestMedicalWaiverGate:
    def test_restricted_medical_blocks_session_booking(self, api):
        """PRD 2.8: "In each of these, the diver must have an active waiver and a
        `medical_status` that is not `RESTRICTED` (equivalently, `CLEAR`); if not,
        the operation is rejected with `ERR_WAIVER_REQUIRED` (HTTP 422)."
        PRD 3.1: "`RESTRICTED` when it is true."

        Design: Corner/validations/restricted_medical_blocks_session_booking
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor(full_name="Restr Inst")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-06-10T08:00:00Z", ends_at="2026-06-10T10:00:00Z",
        )
        diver = create_diver(full_name="Restr Rae")
        sign_waiver(diver["id"], medical_flagged=True)
        diver_after = get_success_data(api.get_diver(diver["id"], ADMIN))
        assert diver_after["medical_status"] == "RESTRICTED", diver_after
        enr = create_enrollment(diver["id"], course["id"])
        resp = api.create_session_booking(
            f.create_session_booking_payload(
                session["id"], enr["id"], session["version"]
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_REQUIRED.value, expected_status=422)

    def test_expired_waiver_blocks_session_booking(self, api):
        """PRD 2.8: "A waiver is **active** when the current logical clock is
        strictly before its `expires_at` and it is the diver's most recently signed
        waiver."
        PRD 2.8: "if not, the operation is rejected with `ERR_WAIVER_REQUIRED`
        (HTTP 422)."

        Design: Corner/validations/expired_waiver_blocks_session_booking
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course()
        instructor = create_instructor(full_name="Exp Inst")
        diver = create_diver(full_name="Exp Eve")
        sign_waiver(diver["id"], medical_flagged=False)  # expires 2027-06-01
        enr = create_enrollment(diver["id"], course["id"])
        set_clock("2027-07-01T00:00:00Z")  # waiver now expired
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2027-07-10T08:00:00Z", ends_at="2027-07-10T10:00:00Z",
        )
        resp = api.create_session_booking(
            f.create_session_booking_payload(
                session["id"], enr["id"], session["version"]
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_REQUIRED.value, expected_status=422)
