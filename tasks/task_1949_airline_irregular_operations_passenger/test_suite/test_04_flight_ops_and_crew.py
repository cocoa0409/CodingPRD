"""Flight operations, crew duty windows, legality rechecks, and flight OCC."""
from datetime import datetime, timezone

from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    add_flight, add_event, add_crew_assignment,
    event_to_assessing, fly_flight, get_flight,
    create_crew_assignment_payload, delay_flight_payload, cancel_flight_payload,
)

OPS = TEST_USERS["ops_controller_headers"]
CREW = TEST_USERS["crew_scheduler_headers"]


def _instant(s: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp to an instant. PRD pins timestamp values
    (which instant), not the byte-format of client-supplied schedule fields —
    compare instants, not strings."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class TestCrewDutyOverlapHalfOpen:
    def _flight(self):
        return add_flight(flight_number="OC95",
                          sched_dep_utc="2026-08-10T08:00:00Z",
                          sched_arr_utc="2026-08-10T10:00:00Z",
                          cabins=[{"cabin": "ECONOMY", "capacity": 50}])

    def test_adjacent_duty_windows_are_not_an_overlap(self, api):
        """PRD §3.1: "A crew member may not hold two assignments in `ASSIGNED`
        status whose duty windows overlap as half-open intervals — one window
        ending exactly when another begins is not an overlap — and such a
        conflict is rejected with `ERR_CREW_DUTY_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/crew_duty_overlap_half_open
        """
        flight = self._flight()
        first = validate_success(api_client.create_crew_assignment(
            flight["id"], create_crew_assignment_payload(
                crew_member_ref="CM1", crew_role="CAPTAIN",
                duty_start_utc="2026-08-10T06:00:00Z",
                duty_end_utc="2026-08-10T14:00:00Z"), CREW), 201)
        assert first["assignment_status"] == "ASSIGNED"

        second = api_client.create_crew_assignment(
            flight["id"], create_crew_assignment_payload(
                crew_member_ref="CM1", crew_role="FIRST_OFFICER",
                duty_start_utc="2026-08-10T14:00:00Z",
                duty_end_utc="2026-08-10T22:00:00Z"), CREW)
        data = validate_success(second, 201)
        assert data["assignment_status"] == "ASSIGNED", (
            "start 14:00 == prior end 14:00 touches but does not overlap (half-open)")

    def test_one_minute_earlier_start_overlaps_and_is_rejected(self, api):
        """PRD §3.1: "A crew member may not hold two assignments in `ASSIGNED`
        status whose duty windows overlap as half-open intervals — one window
        ending exactly when another begins is not an overlap — and such a
        conflict is rejected with `ERR_CREW_DUTY_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/crew_duty_overlap_half_open
        """
        flight = self._flight()
        validate_success(api_client.create_crew_assignment(
            flight["id"], create_crew_assignment_payload(
                crew_member_ref="CM1", crew_role="CAPTAIN",
                duty_start_utc="2026-08-10T06:00:00Z",
                duty_end_utc="2026-08-10T14:00:00Z"), CREW), 201)
        res = api_client.create_crew_assignment(
            flight["id"], create_crew_assignment_payload(
                crew_member_ref="CM1", crew_role="FLIGHT_ATTENDANT",
                duty_start_utc="2026-08-10T13:59:00Z",
                duty_end_utc="2026-08-10T21:00:00Z"), CREW)
        validate_error(res, ApiErrorId.ERR_CREW_DUTY_OVERLAP)


def test_post_flight_buffer_inclusive_boundary(api):
    """PRD §3.1: "an assignment legally covers its flight when duty starts at
    or before the scheduled departure and the scheduled arrival plus a
    thirty-minute post-flight buffer falls at or before duty end; an assignment
    failing that coverage test is marked `FLAGGED_ILLEGAL` instead of `LEGAL`."
    PRD §3.3: "The first pass is the crew legality recheck: every crew
    assignment on the flight is re-evaluated against the retimed schedule, and
    any assignment whose duty window no longer covers the new departure through
    the new arrival plus the thirty-minute buffer becomes `FLAGGED_ILLEGAL`,
    after which the flight's `crew_coverage_status` is recomputed."

    Design: Corner/calculations/crew_post_flight_buffer_boundary
    """
    w1 = add_flight(flight_number="OC39")
    w2 = add_flight(flight_number="OC40")
    event = add_event(event_code="MECH-C13", cost_cap_cents=100000)
    a1 = add_crew_assignment(w1["id"], crew_member_ref="CM9", crew_role="CAPTAIN")
    add_crew_assignment(w1["id"], crew_member_ref="CM11", crew_role="FIRST_OFFICER")
    a2 = add_crew_assignment(w2["id"], crew_member_ref="CM10", crew_role="CAPTAIN")
    add_crew_assignment(w2["id"], crew_member_ref="CM12", crew_role="FIRST_OFFICER")

    # Retime W1 to arrive 13:30: 13:30 + 30min = 14:00 <= duty_end 14:00 (inclusive).
    w1v = get_flight(w1["id"])["version"]
    validate_success(api_client.delay_flight(
        w1["id"], delay_flight_payload("2026-08-10T12:00:00Z",
                                       "2026-08-10T13:30:00Z", w1v,
                                       disruption_event_id=event["id"]), OPS))
    # Retime W2 to arrive 13:31: 13:31 + 30min = 14:01 > 14:00.
    w2v = get_flight(w2["id"])["version"]
    validate_success(api_client.delay_flight(
        w2["id"], delay_flight_payload("2026-08-10T12:00:00Z",
                                       "2026-08-10T13:31:00Z", w2v,
                                       disruption_event_id=event["id"]), OPS))

    a1_after = validate_success(api_client.get_crew_assignment(a1["id"], CREW))
    assert a1_after["legality_status"] == "LEGAL", (
        "arrival 13:30 + 30min buffer == duty end 14:00 falls at the inclusive boundary")
    w1_after = get_flight(w1["id"])
    assert w1_after["crew_coverage_status"] == "CREW_OK"

    a2_after = validate_success(api_client.get_crew_assignment(a2["id"], CREW))
    assert a2_after["legality_status"] == "FLAGGED_ILLEGAL", (
        "arrival 13:31 + 30min buffer == 14:01 exceeds duty end 14:00")
    w2_after = get_flight(w2["id"])
    assert w2_after["crew_coverage_status"] == "CREW_SHORT", (
        "no LEGAL non-RELEASED CAPTAIN -> CREW_SHORT")


def test_arrived_flight_rejects_cancel_and_delay(api):
    """PRD §3.3: "Cancelling requires the flight to be in `SCHEDULED` or
    `DELAYED` — cancelling an `IN_FLIGHT`, `ARRIVED`, or already `CANCELLED`
    flight is rejected with `ERR_FLIGHT_NOT_CANCELLABLE` (HTTP 409)".
    PRD §3.3: "Attempting either from any other state is rejected with
    `ERR_FLIGHT_NOT_DELAYABLE`."

    Design: Corner/state_machines/flight_terminal_lockdown
    """
    flight = add_flight(flight_number="OC5",
                        sched_dep_utc="2026-08-10T08:00:00Z",
                        sched_arr_utc="2026-08-10T09:00:00Z",
                        cabins=[{"cabin": "ECONOMY", "capacity": 50}])
    event = add_event(event_code="WX-C2", classification="WEATHER",
                      cost_cap_cents=1000)
    # Keep the event in a cancel-admissible state so only the flight-state
    # guard can fail (isolated single-failure scenario).
    event_to_assessing(event["id"])
    arrived = fly_flight(flight["id"], "2026-08-10T08:05:00Z", "2026-08-10T09:05:00Z")
    assert arrived["flight_status"] == "ARRIVED"

    res_cancel = api_client.cancel_flight(
        flight["id"], cancel_flight_payload(event["id"], arrived["version"]), OPS)
    validate_error(res_cancel, ApiErrorId.ERR_FLIGHT_NOT_CANCELLABLE)

    res_delay = api_client.delay_flight(
        flight["id"], delay_flight_payload("2026-08-10T12:00:00Z",
                                           "2026-08-10T13:00:00Z",
                                           arrived["version"]), OPS)
    validate_error(res_delay, ApiErrorId.ERR_FLIGHT_NOT_DELAYABLE)


def test_release_of_released_assignment_rejected(api):
    """PRD §3.1: "Releasing an assignment — permitted only while it is
    `ASSIGNED`, otherwise `ERR_INVALID_CREW_STATE` (HTTP 409) — moves it to
    `RELEASED` and again recomputes the flight's coverage."

    Design: Corner/errors/crew_release_twice_rejected
    """
    flight = add_flight(flight_number="OC59",
                        sched_dep_utc="2026-08-10T08:00:00Z",
                        sched_arr_utc="2026-08-10T10:00:00Z",
                        cabins=[{"cabin": "ECONOMY", "capacity": 50}])
    assignment = add_crew_assignment(flight["id"], crew_member_ref="CM20",
                                     crew_role="CAPTAIN")
    validate_success(api_client.release_crew_assignment(assignment["id"], CREW))
    res = api_client.release_crew_assignment(assignment["id"], CREW)
    validate_error(res, ApiErrorId.ERR_INVALID_CREW_STATE)


def test_delay_missing_body_fields_rejected_before_existence(api):
    """PRD §2.8: "Consequently, a request that is both malformed and addressed
    to a nonexistent resource surfaces `ERR_INVALID_REQUEST`, and a
    stale-version rejection always precedes any state-machine rejection."

    Design: Corner/validations/delay_missing_required_fields_returns_400_before_existence
    """
    res = api_client.delay_flight(NON_EXISTENT_UUID, {}, OPS)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_delay_with_stale_flight_version_rejected_412(api):
    """PRD §2.7: "In each case, if the supplied value does not equal the
    resource's current `version` — for example because options were regenerated
    on the case, or because a crew assignment changed the flight's coverage and
    bumped its version — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412), and the client must re-read the resource and resubmit with the
    current version."
    PRD §3.1: "Creating an assignment recomputes the flight's
    `crew_coverage_status` and increments the flight's `version`."

    Design: Corner/cross_cutting_layers/occ_delay_stale_version_returns_412
    """
    flight = add_flight(flight_number="OC82",
                        sched_dep_utc="2026-08-10T08:00:00Z",
                        sched_arr_utc="2026-08-10T10:00:00Z",
                        cabins=[{"cabin": "ECONOMY", "capacity": 50}])
    stale_version = flight["version"]
    add_crew_assignment(flight["id"], crew_member_ref="CM30", crew_role="CAPTAIN")

    res = api_client.delay_flight(
        flight["id"], delay_flight_payload("2026-08-10T09:00:00Z",
                                           "2026-08-10T11:00:00Z",
                                           stale_version), OPS)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    after = get_flight(flight["id"])
    assert _instant(after["sched_dep_utc"]) == _instant("2026-08-10T08:00:00Z"), (
        "rejected retime must not mutate the schedule")


def test_delay_with_current_version_increments_by_one(api):
    """PRD §2.4: "`version` (integer): starts at creation and increments by one
    on every mutation of the resource, including mutations caused by cascade
    side effects."
    PRD §3.3: "Every successful delay or retiming writes the new schedule,
    increments the flight's `version`, and then runs two protection passes."

    Design: Corner/cross_cutting_layers/occ_success_increments_version
    """
    flight = add_flight(flight_number="OC83",
                        sched_dep_utc="2026-08-10T08:00:00Z",
                        sched_arr_utc="2026-08-10T10:00:00Z",
                        cabins=[{"cabin": "ECONOMY", "capacity": 50}])
    event = add_event(event_code="MECH-C21", cost_cap_cents=100000)
    delayed = validate_success(api_client.delay_flight(
        flight["id"], delay_flight_payload("2026-08-10T09:00:00Z",
                                           "2026-08-10T11:00:00Z",
                                           flight["version"],
                                           disruption_event_id=event["id"]), OPS))
    assert delayed["version"] == flight["version"] + 1, (
        f"exactly one increment: {flight['version']} -> {delayed['version']}")
    assert delayed["flight_status"] == "DELAYED"
    assert _instant(delayed["sched_dep_utc"]) == _instant("2026-08-10T09:00:00Z")
