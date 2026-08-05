"""Temporal windowing for shared resources: crew buffered overlap and viewing
room half-open adjacency."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_crew_with_scheduled_job, setup_two_bookings,
    transport_job_payload,
    COORD,
    api_client as api,
)


# ==========================================================================
# Crew: closed intervals padded by a 60-minute buffer on each side
# ==========================================================================
def test_crew_30min_gap_conflicts():
    """PRD §2.9: "The new job conflicts when its start is earlier than the other
    job's end plus 60 minutes, and simultaneously its end plus 60 minutes is later
    than the other job's start. Adjacency that falls inside the 60-minute buffer
    conflicts; a clear gap of exactly 60 minutes does not. A conflict is rejected
    with `ERR_CREW_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/crew_buffered_overlap
    """
    s = setup_crew_with_scheduled_job()
    # job2 11:30-12:30 leaves only a 30-minute gap after job1 ends 11:00 (< 60 buffer).
    resp = api.create_transport_job(
        transport_job_payload(s["a2"]["id"], s["crate2"]["id"], s["crew"]["id"],
                              scheduled_start="2026-06-01T11:30:00Z",
                              scheduled_end="2026-06-01T12:30:00Z",
                              requires_rigging=True, estimated_hours=1), COORD)
    validate_error(resp, ApiErrorId.ERR_CREW_UNAVAILABLE.value, 409)


def test_crew_exact_60min_gap_allowed():
    """PRD §2.9: "Adjacency that falls inside the 60-minute buffer conflicts; a
    clear gap of exactly 60 minutes does not. A conflict is rejected with
    `ERR_CREW_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/crew_buffered_overlap
    """
    s = setup_crew_with_scheduled_job()
    # job2 12:00-13:00 leaves a clear 60-minute gap after job1 ends 11:00 (allowed).
    data = validate_success(api.create_transport_job(
        transport_job_payload(s["a2"]["id"], s["crate2"]["id"], s["crew"]["id"],
                              scheduled_start="2026-06-01T12:00:00Z",
                              scheduled_end="2026-06-01T13:00:00Z",
                              requires_rigging=True, estimated_hours=1), COORD), 201)
    assert data["status"] == "SCHEDULED", data


# ==========================================================================
# Viewing room: half-open [start, end) intervals with no buffer
# ==========================================================================
def test_adjacent_booking_confirms():
    """PRD §2.9: "Because the intervals are half-open, a new booking whose start
    equals a prior booking's end does not conflict."

    Design: Difficulty/resource_temporal_overlap/room_halfopen_adjacency
    """
    s = setup_two_bookings("2026-05-02T15:00:00Z", "2026-05-02T16:00:00Z", damage_second=False)
    data = validate_success(api.transition_viewing_booking(s["b2"]["id"], {"to_status": "CONFIRMED"}, COORD))
    assert data["status"] == "CONFIRMED", data


def test_adjacent_bookings_coexist_confirmed():
    """PRD §2.9: "For **viewing rooms**, a booking being confirmed is checked
    against every other `CONFIRMED` booking on the same room using half-open
    intervals `[scheduled_start, scheduled_end)` with no buffer: the two conflict
    when the new booking's start is earlier than the existing booking's end and the
    existing booking's start is earlier than the new booking's end."

    Design: Difficulty/resource_temporal_overlap/room_halfopen_adjacency
    """
    s = setup_two_bookings("2026-05-02T15:00:00Z", "2026-05-02T16:00:00Z", damage_second=False)
    get_success_data(api.transition_viewing_booking(s["b2"]["id"], {"to_status": "CONFIRMED"}, COORD))
    b1 = validate_success(api.get_viewing_booking(s["b1"]["id"], COORD))
    b2 = validate_success(api.get_viewing_booking(s["b2"]["id"], COORD))
    assert b1["status"] == "CONFIRMED", b1
    assert b2["status"] == "CONFIRMED", b2
