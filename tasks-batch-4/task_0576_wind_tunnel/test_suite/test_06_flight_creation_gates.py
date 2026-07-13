"""Flight creation gates: seat capacity, staffing, and fiscal sufficiency, plus
their validation precedence (PRD §3.5, §2.10)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_session_instructor,
    create_flight_payload,
    make_booking,
    make_flight,
    make_instructor,
    make_member,
    make_package,
    make_session,
    make_tunnel,
    validate_error,
    validate_success,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]


class TestSessionCapacityBoundary:
    """A capacity-1 session accepts one flight and rejects the second."""

    def _setup(self, api):
        tunnel = make_tunnel(api)
        instructor = make_instructor(api)
        pkg = make_package(api, included_minutes=2, base_price_cents=6000)
        m1 = make_member(api, name="M1", weight_kg=80)
        m2 = make_member(api, name="M2", weight_kg=80)
        b1 = make_booking(api, m1["id"], pkg["id"], party_size=1)
        b2 = make_booking(api, m2["id"], pkg["id"], party_size=1)
        session = make_session(api, tunnel["id"], capacity=1)
        assign_session_instructor(api, session["id"], instructor["id"], session["version"])
        make_flight(api, b1["id"], session["id"], m1["id"], 2)
        return session, b2, m2

    def test_session_full_rejects_second_flight(self, api):
        """PRD §3.5: "Creation requires the session to be `STAFFED` (else
        `ERR_SESSION_NOT_STAFFED`) and to have at least one open seat (else
        `ERR_SESSION_FULL`), and requires the booking to hold enough minutes".

        Design: Difficulty/boundary_precision_check/session_capacity_full_count_boundary
        """
        session, b2, m2 = self._setup(api)
        resp = api.create_flight(create_flight_payload(b2["id"], session["id"], m2["id"], 2), FRONTDESK)
        validate_error(resp, ApiErrorId.ERR_SESSION_FULL.value)

    def test_seats_unchanged_after_full_rejection(self, api):
        """PRD §3.5: "the session's `seats_taken` is the count of its flights in
        `SCHEDULED`, `CHECKED_IN`, or `FLOWN`, and `seats_available` is `capacity` minus
        `seats_taken`, never negative."

        Design: Difficulty/boundary_precision_check/session_capacity_full_count_boundary
        """
        session, b2, m2 = self._setup(api)
        api.create_flight(create_flight_payload(b2["id"], session["id"], m2["id"], 2), FRONTDESK)
        reread = validate_success(api.get_session(session["id"], FRONTDESK), 200)
        assert reread["seats_taken"] == 1, reread["seats_taken"]
        assert reread["seats_available"] == 0, reread["seats_available"]


class TestFlightCreateRequiresStaffedSession:
    """Flight creation depends on the session's staffing_status."""

    def _setup_unstaffed(self, api):
        tunnel = make_tunnel(api)
        pkg = make_package(api, included_minutes=2, base_price_cents=6000)
        member = make_member(api, weight_kg=80)
        booking = make_booking(api, member["id"], pkg["id"], party_size=1)
        session = make_session(api, tunnel["id"])  # never assigned -> UNSTAFFED
        return session, booking, member

    def test_flight_create_requires_staffed_session(self, api):
        """PRD §3.5: "Creation requires the session to be `STAFFED` (else
        `ERR_SESSION_NOT_STAFFED`) and to have at least one open seat".

        Design: Difficulty/cross_entity_state_dependency/flight_create_requires_staffed_session
        """
        session, booking, member = self._setup_unstaffed(api)
        resp = api.create_flight(
            create_flight_payload(booking["id"], session["id"], member["id"], 2), FRONTDESK
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_STAFFED.value)

    def test_no_seat_taken_on_unstaffed_rejection(self, api):
        """PRD §3.5: "Consuming minutes and taking a seat are the two immediate effects
        of creation."

        Design: Difficulty/cross_entity_state_dependency/flight_create_requires_staffed_session
        """
        session, booking, member = self._setup_unstaffed(api)
        api.create_flight(create_flight_payload(booking["id"], session["id"], member["id"], 2), FRONTDESK)
        reread = validate_success(api.get_session(session["id"], FRONTDESK), 200)
        assert reread["seats_taken"] == 0, reread["seats_taken"]


class TestReferentialBeatsFiscal:
    """business_referential (priority 5) fires before business_fiscal (priority 9)."""

    def _setup(self, api):
        tunnel = make_tunnel(api)
        pkg = make_package(api, included_minutes=2, base_price_cents=6000)
        member = make_member(api, weight_kg=80)
        booking = make_booking(api, member["id"], pkg["id"], party_size=1)  # only 2 minutes
        session = make_session(api, tunnel["id"])  # UNSTAFFED
        return session, booking, member

    def test_unstaffed_beats_insufficient_minutes(self, api):
        """PRD §2.10: "Lower-priority checks are never reached once a higher-priority
        check fails."
        PRD §2.10: "a flight create or session start demands a staffed session
        (`ERR_SESSION_NOT_STAFFED`), all at 409."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_flight_create
        """
        session, booking, member = self._setup(api)
        resp = api.create_flight(
            create_flight_payload(booking["id"], session["id"], member["id"], 5), FRONTDESK
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_STAFFED.value)

    def test_booking_minutes_unchanged_on_rejection(self, api):
        """PRD §2.10: "Lower-priority checks are never reached once a higher-priority
        check fails."
        PRD §3.5: "Consuming minutes and taking a seat are the two immediate effects of
        creation."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_flight_create
        """
        session, booking, member = self._setup(api)
        api.create_flight(create_flight_payload(booking["id"], session["id"], member["id"], 5), FRONTDESK)
        reread = validate_success(api.get_booking(booking["id"], FRONTDESK), 200)
        assert reread["minutes_remaining"] == 2, reread["minutes_remaining"]


def test_insufficient_minutes_on_staffed_session(api):
    """PRD §3.5: "requires the booking to hold enough minutes — its `minutes_remaining`
    must be at least the requested `scheduled_minutes`, else `ERR_INSUFFICIENT_MINUTES`."

    Design: Corner/validations/flight_insufficient_minutes_on_staffed_session_returns_error
    """
    tunnel = make_tunnel(api)
    instructor = make_instructor(api)
    pkg = make_package(api, included_minutes=2, base_price_cents=6000)
    member = make_member(api, weight_kg=80)
    booking = make_booking(api, member["id"], pkg["id"], party_size=1)  # 2 minutes
    session = make_session(api, tunnel["id"])
    assign_session_instructor(api, session["id"], instructor["id"], session["version"])
    resp = api.create_flight(create_flight_payload(booking["id"], session["id"], member["id"], 5), FRONTDESK)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MINUTES.value)
