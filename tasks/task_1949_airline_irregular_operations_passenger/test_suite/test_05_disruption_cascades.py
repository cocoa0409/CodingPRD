"""The flight cancel and misconnect cascades, completion rollup, and the
uncontrollable-event compensation filter."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, add_passenger, add_flight, add_event, add_booking,
    event_to_assessing, cancel_flight_under_event, delay_flight_to,
    fly_flight, get_booking, segments_for_booking, segments_for_flight,
    list_cases, comm_logs, get_event,
    setup_disrupted_booking, create_refund_election_payload,
)

AGENT = TEST_USERS["agent_headers"]
DUTY = TEST_USERS["duty_manager_headers"]


class TestFlightCancelCascadeDepth4:
    """Four links: flight CANCELLED -> segments CANCELLED -> bookings DISRUPTED
    -> cases QUEUED -> CANCELLATION comms + event counters recomputed."""

    def _setup(self):
        set_clock("2026-08-10T06:00:00Z")
        pa = add_passenger(full_name="Cas A", contact_email="casa@x.com")
        pb = add_passenger(full_name="Cas B", contact_email="casb@x.com")
        flight = add_flight(flight_number="OC2000",
                            sched_dep_utc="2026-08-10T10:00:00Z",
                            sched_arr_utc="2026-08-10T11:00:00Z")
        event = add_event(event_code="MECH-8", cost_cap_cents=1_000_000)
        event_to_assessing(event["id"])
        ba = add_booking(pa["id"], flight["id"], fare_cents=12000, party_size=1)
        bb = add_booking(pb["id"], flight["id"], fare_cents=24000, party_size=2)
        cancel_flight_under_event(flight["id"], event["id"],
                                  expected_version=flight["version"])
        return flight, event, ba, bb

    def test_cancel_cascade_mutates_segments_and_bookings(self, api):
        """PRD §3.3: "Link one: every `CONFIRMED` segment on the cancelled
        flight becomes `CANCELLED`; in contrast to a booking-level cancellation,
        these seats are retained in the cabin inventory's `seats_sold` for audit
        until the passengers are rebooked. Link two: each booking owning such a
        segment becomes `DISRUPTED` unless it already was."

        Design: Difficulty/transitive_cascade/flight_cancel_cascade_depth4
        """
        flight, event, ba, bb = self._setup()
        segments = segments_for_flight(flight["id"])
        assert len(segments) == 2
        for seg in segments:
            assert seg["segment_status"] == "CANCELLED", (
                f"link 1: segment {seg['id']} must be CANCELLED, got {seg['segment_status']}")
        for booking_id in (ba["id"], bb["id"]):
            booking = get_booking(booking_id)
            assert booking["booking_status"] == "DISRUPTED", (
                f"link 2: booking {booking_id} must be DISRUPTED")

    def test_cancel_cascade_creates_cases_comms_and_counters(self, api):
        """PRD §3.3: "Link three: each newly disrupted booking gets a
        reaccommodation case created under the same no-open-case rule, and —
        only when the linked event is controllable — its `compensation_status`
        advances from `NONE` to `ELIGIBLE_PENDING` with `eligible_at` stamped
        now, `compensation_amount_cents` initialized to the distance-tier base
        of §3.7, and `compensation_basis` set to `PROVISIONAL`."
        PRD §3.3: "Link four: each created case queues a `CANCELLATION`
        communication due immediately, and the event's affected counters are
        recomputed."
        PRD §3.2: "`affected_booking_count` counts the bookings currently in
        `booking_status` `DISRUPTED` that have at least one segment on a flight
        linked to this event, and `affected_passenger_count` sums `party_size`
        over exactly those bookings."

        Design: Difficulty/transitive_cascade/flight_cancel_cascade_depth4
        """
        flight, event, ba, bb = self._setup()
        cases = list_cases({"disruption_event_id": event["id"]})
        assert len(cases) == 2, f"link 3: one case per disrupted booking, got {len(cases)}"
        assert {c["booking_id"] for c in cases} == {ba["id"], bb["id"]}
        for case in cases:
            assert case["case_status"] == "QUEUED"

        logs = comm_logs({"disruption_event_id": event["id"]})
        cancellation_logs = [l for l in logs if l["template"] == "CANCELLATION"]
        assert len(cancellation_logs) == 2, (
            f"link 4: one CANCELLATION log per created case, got {len(cancellation_logs)}")
        for log in cancellation_logs:
            assert log["log_status"] == "QUEUED"

        event_after = get_event(event["id"])
        assert event_after["affected_booking_count"] == 2
        assert event_after["affected_passenger_count"] == 3, (
            "party_size 1 + party_size 2 = 3 affected passengers")


class TestFlightDelayMisconnectCascade:
    """Delay trigger: retimed inbound flight disrupts the onward segment whose
    connection fell below forty-five minutes."""

    def _setup(self):
        set_clock("2026-08-10T06:00:00Z")
        pax = add_passenger(full_name="Dee D", contact_email="dee@x.com")
        m1 = add_flight(flight_number="OC21", origin="AAA", destination="BBB",
                        sched_dep_utc="2026-08-10T08:00:00Z",
                        sched_arr_utc="2026-08-10T09:00:00Z",
                        distance_km=800, cabins=[{"cabin": "ECONOMY", "capacity": 50}])
        m2 = add_flight(flight_number="OC22", origin="BBB", destination="CCC",
                        sched_dep_utc="2026-08-10T10:00:00Z",
                        sched_arr_utc="2026-08-10T11:00:00Z",
                        distance_km=800, cabins=[{"cabin": "ECONOMY", "capacity": 50}])
        event = add_event(event_code="MECH-9", hub="AAA", cost_cap_cents=1_000_000)
        booking = add_booking(pax["id"], segments=[
            {"flight_id": m1["id"], "seq_no": 1},
            {"flight_id": m2["id"], "seq_no": 2},
        ], fare_cents=22000)
        # Retime M1 +30min: new connection 10:00 - 09:30 = 30 min < 45.
        delay_flight_to(m1["id"], "2026-08-10T08:30:00Z", "2026-08-10T09:30:00Z",
                        event_id=event["id"], expected_version=m1["version"])
        return m1, m2, event, booking

    def test_misconnect_disrupts_onward_segment_and_booking(self, api):
        """PRD §3.3: "The second pass is misconnect protection: for every
        `CONFIRMED` segment on the retimed flight, if the owning booking's next
        segment in sequence is still `CONFIRMED` on a flight departing less than
        forty-five minutes after the new arrival, that next segment becomes
        `DISRUPTED`. Each segment so disrupted pushes its booking's
        `booking_status` to `DISRUPTED`, each booking so disrupted spawns a
        reaccommodation case in `QUEUED` with its `priority_score` computed —
        but only when the booking does not already have a case in `QUEUED`,
        `OFFERED`, or `ESCALATED`".

        Design: Difficulty/transitive_cascade/flight_delay_misconnect_cascade
        """
        m1, m2, event, booking = self._setup()
        segments = {s["seq_no"]: s for s in segments_for_booking(booking["id"])}
        assert segments[1]["segment_status"] == "CONFIRMED", (
            "the retimed inbound segment itself is not disrupted")
        assert segments[2]["segment_status"] == "DISRUPTED", (
            "onward segment with a 30-minute connection (< 45) must be DISRUPTED")

        booking_after = get_booking(booking["id"])
        assert booking_after["booking_status"] == "DISRUPTED"

        cases = list_cases({"booking_id": booking["id"]})
        assert len(cases) == 1, f"exactly one case under the no-open-case rule, got {len(cases)}"
        assert cases[0]["case_status"] == "QUEUED"

    def test_misconnect_queues_detection_notice_without_compensation(self, api):
        """PRD §3.3: "each newly created case queues a `DISRUPTION_DETECTED`
        communication with `due_at` set to the current logical time."
        PRD §3.7: "Eligibility arises only from controllable events, through two
        doors. A cancellation under a controllable event grants eligibility at
        cascade time, as §3.3 describes, with the amount initialized to the
        distance-tier base and basis `PROVISIONAL`. Separately, when a flight
        linked to a controllable event arrives with an actual arrival delay of
        at least 180 minutes — measured as its `act_arr_utc` against its own
        `orig_sched_arr_utc` — the record-actuals sweep grants every booking
        that held a `CONFIRMED` segment on that flight `ELIGIBLE_PENDING` with
        `eligible_at` stamped now and the amount set to the distance-tier base
        with basis `FINAL`." A retime alone opens neither door.

        Design: Difficulty/transitive_cascade/flight_delay_misconnect_cascade
        """
        m1, m2, event, booking = self._setup()
        logs = comm_logs({"booking_id": booking["id"]})
        detected = [l for l in logs if l["template"] == "DISRUPTION_DETECTED"]
        assert len(detected) == 1, (
            f"exactly one DISRUPTION_DETECTED notice for the new case, got {len(detected)}")
        assert detected[0]["log_status"] == "QUEUED"

        booking_after = get_booking(booking["id"])
        assert booking_after["compensation_status"] == "NONE", (
            "a delay-only disruption grants no compensation eligibility")
        assert booking_after["compensation_amount_cents"] == 0


def test_booking_completes_when_its_flight_arrives(api):
    """PRD §3.1: "Arrival flows every `CONFIRMED` segment on the flight to
    `FLOWN`; each such segment triggers its booking's completion rollup and
    recomputes the booking's refund and credit amounts, because the set of flown
    legs has changed."
    PRD §3.4: "if every segment of the booking is in `FLOWN`, `CANCELLED`, or
    `REBOOKED`, with at least one segment `FLOWN` and none still `DISRUPTED` or
    `CONFIRMED`, the booking becomes `COMPLETED`, from either `ACTIVE` or
    `REBOOKED`."

    Design: Corner/state_machines/booking_completed_rollup
    """
    pax = add_passenger(full_name="Yan Y", contact_email="yan@x.com")
    flight = add_flight(flight_number="OC10",
                        sched_dep_utc="2026-08-10T08:00:00Z",
                        sched_arr_utc="2026-08-10T09:00:00Z",
                        cabins=[{"cabin": "ECONOMY", "capacity": 50}])
    booking = add_booking(pax["id"], flight["id"])
    fly_flight(flight["id"], "2026-08-10T08:05:00Z", "2026-08-10T09:05:00Z")

    segments = segments_for_booking(booking["id"])
    assert len(segments) == 1
    assert segments[0]["segment_status"] == "FLOWN"
    booking_after = get_booking(booking["id"])
    assert booking_after["booking_status"] == "COMPLETED", (
        "all segments terminal with one FLOWN -> completion rollup")


def test_uncontrollable_event_grants_no_compensation(api):
    """PRD §3.7: "Bookings disrupted under uncontrollable `WEATHER` or `ATC`
    events receive no compensation: the amount is zero and the money axis stays
    `NONE`."
    PRD §3.7: "The eligibility gate is evaluated before the deadline gate: the
    money axis must be `ELIGIBLE_PENDING` or the request fails with
    `ERR_COMPENSATION_NOT_ELIGIBLE` (HTTP 422)".
    PRD §3.2: "the event is controllable exactly when the classification is
    `MECHANICAL` or `CREW_SHORTAGE`, while `WEATHER` and `ATC` are
    uncontrollable."

    Design: Corner/calculations/compensation_uncontrollable_event_zero
    """
    ctx = setup_disrupted_booking(
        classification="WEATHER", event_code="WX-C9", cost_cap_cents=100000,
        flight_overrides={"flight_number": "OC33", "distance_km": 4000})
    booking = get_booking(ctx["booking"]["id"])
    assert booking["booking_status"] == "DISRUPTED", (
        "the cancellation cascade still runs for uncontrollable events")
    assert booking["compensation_status"] == "NONE"
    assert booking["compensation_amount_cents"] == 0

    res = api_client.create_refund_election(
        ctx["booking"]["id"], create_refund_election_payload("REFUND"), AGENT)
    validate_error(res, ApiErrorId.ERR_COMPENSATION_NOT_ELIGIBLE)
