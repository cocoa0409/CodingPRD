"""Booking creation guards (seats, connections), seat conservation, and the
immediately consistent commit read-back."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    add_passenger, add_flight, add_booking,
    cabin_inventory, setup_offered_case, commit_option,
    get_booking, segments_for_booking,
    create_booking_payload,
)

AGENT = TEST_USERS["agent_headers"]


class TestSeatConservationCreateCancelPair:
    def _flight(self):
        return add_flight(flight_number="OC99",
                          sched_dep_utc="2026-08-10T10:00:00Z",
                          sched_arr_utc="2026-08-10T11:00:00Z")

    def test_booking_create_consumes_cabin_seats(self, api):
        """PRD §3.4: "On success, each segment's cabin inventory `seats_sold`
        increases by `party_size`."

        Design: Difficulty/compensating_invariant/seat_conservation_create_cancel_pair
        """
        pax = add_passenger(full_name="Quinn Q", contact_email="quinn@x.com")
        flight = self._flight()
        assert cabin_inventory(flight["id"])["seats_sold"] == 0
        add_booking(pax["id"], flight["id"], party_size=2)
        assert cabin_inventory(flight["id"])["seats_sold"] == 2

    def test_booking_cancel_returns_seats_to_zero(self, api):
        """PRD §3.4: "Cancellation moves every non-`FLOWN` segment to
        `CANCELLED` and releases those seats, decreasing each affected cabin's
        `seats_sold` by `party_size`; any open case becomes `VOIDED` and its
        `PROPOSED` options become `EXPIRED`."

        Design: Difficulty/compensating_invariant/seat_conservation_create_cancel_pair
        """
        pax = add_passenger(full_name="Quinn Q", contact_email="quinn@x.com")
        flight = self._flight()
        booking = add_booking(pax["id"], flight["id"], party_size=2)
        assert cabin_inventory(flight["id"])["seats_sold"] == 2
        validate_success(api_client.cancel_booking(booking["id"], AGENT))
        assert cabin_inventory(flight["id"])["seats_sold"] == 0, (
            "create + cancel conserves the cabin seat total")


def test_seat_quota_exact_fit_then_one_short(api):
    """PRD §3.4: "every leg's cabin must have `seats_available` of at least
    `party_size`, otherwise `ERR_SEATS_INSUFFICIENT` (HTTP 422)".

    Design: Corner/validations/seats_exact_fit_boundary
    """
    p1 = add_passenger(full_name="Ivy I", contact_email="ivy@x.com")
    p2 = add_passenger(full_name="Jax J", contact_email="jax@x.com")
    flight = add_flight(flight_number="OC50",
                        sched_dep_utc="2026-08-10T10:00:00Z",
                        sched_arr_utc="2026-08-10T11:00:00Z",
                        cabins=[{"cabin": "ECONOMY", "capacity": 2}])
    res_ok = api_client.create_booking(
        create_booking_payload(p1["id"], flight["id"], party_size=2), AGENT)
    validate_success(res_ok, 201)  # party_size == seats_available (2 == 2)

    res_short = api_client.create_booking(
        create_booking_payload(p2["id"], flight["id"], party_size=1), AGENT)
    validate_error(res_short, ApiErrorId.ERR_SEATS_INSUFFICIENT)


def test_connection_minimum_is_forty_five_minutes_inclusive(api):
    """PRD §3.4: "each subsequent segment must depart at least forty-five
    minutes after the previous segment's scheduled arrival, otherwise
    `ERR_CONNECTION_WINDOW_VIOLATION` (HTTP 422)."

    Design: Corner/validations/connection_window_minimum_at_booking
    """
    p1 = add_passenger(full_name="Kai K", contact_email="kai@x.com")
    p2 = add_passenger(full_name="Liv L", contact_email="liv@x.com")
    s1 = add_flight(flight_number="OC51", origin="AAA", destination="BBB",
                    sched_dep_utc="2026-08-10T09:00:00Z",
                    sched_arr_utc="2026-08-10T10:00:00Z", distance_km=500,
                    cabins=[{"cabin": "ECONOMY", "capacity": 50}])
    s2 = add_flight(flight_number="OC52", origin="BBB", destination="CCC",
                    sched_dep_utc="2026-08-10T10:44:00Z",
                    sched_arr_utc="2026-08-10T11:44:00Z", distance_km=500,
                    cabins=[{"cabin": "ECONOMY", "capacity": 50}])
    s3 = add_flight(flight_number="OC53", origin="BBB", destination="CCC",
                    sched_dep_utc="2026-08-10T10:45:00Z",
                    sched_arr_utc="2026-08-10T11:45:00Z", distance_km=500,
                    cabins=[{"cabin": "ECONOMY", "capacity": 50}])

    res_44 = api_client.create_booking(create_booking_payload(
        p1["id"], segments=[{"flight_id": s1["id"], "seq_no": 1},
                            {"flight_id": s2["id"], "seq_no": 2}]), AGENT)
    validate_error(res_44, ApiErrorId.ERR_CONNECTION_WINDOW_VIOLATION)

    res_45 = api_client.create_booking(create_booking_payload(
        p2["id"], segments=[{"flight_id": s1["id"], "seq_no": 1},
                            {"flight_id": s3["id"], "seq_no": 2}]), AGENT)
    validate_success(res_45, 201)  # exactly 45 minutes is admissible


def test_commit_is_immediately_visible_across_reads(api):
    """PRD §1: the seven operator surfaces share "a shared, immediately
    consistent data model."
    PRD §3.5: "A successful commit moves the option to `ACCEPTED` and every
    sibling `PROPOSED` option to `REJECTED`, records the accepted option in
    `committed_option_id`, and increments the case's `version`. The booking
    moves from `DISRUPTED` to `REBOOKED`: its old `DISRUPTED` segments become
    `REBOOKED`, and new `CONFIRMED` segments are created from the option's legs
    with their `reaccommodation_case_id` pointing back at the case. Seats move
    with the passengers — each replaced segment decreases its old flight's
    `seats_sold` by `party_size`, each new own-metal leg increases its cabin's
    `seats_sold` by `party_size`".

    Design: Corner/consistency_model/immediate_consistency_after_commit
    """
    ctx = setup_offered_case(
        event_code="MECH-C24",
        flight_overrides={"flight_number": "OC89",
                          "sched_dep_utc": "2026-08-10T09:00:00Z",
                          "sched_arr_utc": "2026-08-10T10:00:00Z"},
        extra_flights=[{"flight_number": "OC90",
                        "sched_dep_utc": "2026-08-10T14:00:00Z",
                        "sched_arr_utc": "2026-08-10T15:00:00Z"}])
    recovery = ctx["extra_flights"][0]
    option = ctx["options"][0]
    pre_version = ctx["case"]["version"]

    committed = commit_option(ctx["case"]["id"], option["id"], pre_version)
    assert committed["case_status"] == "COMMITTED"
    assert committed["version"] == pre_version + 1
    assert committed["committed_option_id"] == option["id"]

    booking = get_booking(ctx["booking"]["id"])
    assert booking["booking_status"] == "REBOOKED", (
        "the very next read observes the rebooking — no lag")

    new_segments = validate_success(api_client.list_booking_segments(
        AGENT, params={"reaccommodation_case_id": ctx["case"]["id"]}))
    assert len(new_segments) == 1
    assert new_segments[0]["flight_id"] == recovery["id"]
    assert new_segments[0]["segment_status"] == "CONFIRMED"

    assert cabin_inventory(recovery["id"])["seats_sold"] == 1
    assert cabin_inventory(ctx["flight"]["id"])["seats_sold"] == 0, (
        "the seat retained at cancellation is released when the passenger is rebooked")
