"""Provider/room interval overlap, optimistic concurrency, and the queue-call
priority conflict (PRD §2.7, §3.2, §3.11).

Covers the provider half-open + buffer overlap, the room closed-interval
adjacency rule, the OCC stale-version guards on copay authorize and room
booking, and the state-vs-referential priority conflict on queue call.
"""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    fixtures,
)

FRONT = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def test_provider_overlap_with_buffer_rejected(api):
    """PRD §3.2: "Each existing appointment for that provider whose `status` is not `CANCELLED` occupies the half-open interval that runs from its `start_utc` up to, but not including, its `end_utc` plus the provider's `cleanup_buffer_minutes`."
    PRD §3.2: "A genuine overlap is rejected with `ERR_PROVIDER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/provider_halfopen_buffer_overlap
    """
    clinic = fixtures.create_clinic(name="C15")
    provider = fixtures.create_provider(clinic["id"], cleanup_buffer_minutes=10)
    patient = fixtures.create_patient(clinic["id"])
    fixtures.create_appointment(
        clinic["id"], provider["id"], patient["id"],
        start_utc="2026-06-24T10:00:00.000Z", end_utc="2026-06-24T10:30:00.000Z",
    )
    # Existing occupies [10:00, 10:40); new 10:35-11:05 strictly overlaps.
    resp = api.create_appointment(
        {"clinic_id": clinic["id"], "provider_id": provider["id"], "patient_id": patient["id"],
         "start_utc": "2026-06-24T10:35:00.000Z", "end_utc": "2026-06-24T11:05:00.000Z"},
        FRONT,
    )
    validate_error(resp, "ERR_PROVIDER_DOUBLE_BOOKED")


def test_provider_overlap_adjacency_at_buffer_end_allowed(api):
    """PRD §3.2: "Because the intervals are half-open, mere touching at a single
    instant does not collide: if an existing appointment's end plus buffer equals
    the new appointment's start, that is allowed."

    Design: Difficulty/resource_temporal_overlap/provider_halfopen_buffer_overlap
    """
    clinic = fixtures.create_clinic(name="C15b")
    provider = fixtures.create_provider(clinic["id"], cleanup_buffer_minutes=10)
    patient = fixtures.create_patient(clinic["id"])
    fixtures.create_appointment(
        clinic["id"], provider["id"], patient["id"],
        start_utc="2026-06-24T10:00:00.000Z", end_utc="2026-06-24T10:30:00.000Z",
    )
    # New starts exactly at 10:40 (buffer end) -> adjacency allowed.
    data = validate_success(api.create_appointment(
        {"clinic_id": clinic["id"], "provider_id": provider["id"], "patient_id": patient["id"],
         "start_utc": "2026-06-24T10:40:00.000Z", "end_utc": "2026-06-24T11:10:00.000Z"},
        FRONT,
    ), expected_status=201)
    assert data["status"] == "SCHEDULED"


def test_room_booking_closed_interval_adjacency_allowed(api):
    """PRD §3.11: "Adjacency is allowed — when an existing booking's end equals the new booking's start the gap is zero and that is permitted — but any strictly-interior overlap is rejected with `ERR_ROOM_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/room_closed_interval_adjacency_allowed
    """
    clinic, provider, patient, appt, session, card, qentry, room = fixtures.setup_session_ready(
        clinic_name="C16", with_exam_room=True
    )
    fixtures.book_room(
        room["id"], qentry["id"], "2026-06-25T09:00:00.000Z", "2026-06-25T09:30:00.000Z"
    )
    room_v2 = fixtures.get_room_version(room["id"])
    # New booking 09:30-10:00 shares only the endpoint 09:30 -> allowed.
    data = validate_success(api.create_room_booking(
        {"exam_room_id": room["id"], "queue_entry_id": qentry["id"],
         "start_utc": "2026-06-25T09:30:00.000Z", "end_utc": "2026-06-25T10:00:00.000Z",
         "expected_exam_room_version": room_v2},
        FRONT,
    ), expected_status=201)
    assert data["start_utc"] == "2026-06-25T09:30:00.000Z"


def test_room_booking_strict_overlap_rejected(api):
    """PRD §3.11: "any strictly-interior overlap is rejected with `ERR_ROOM_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/room_closed_interval_adjacency_allowed
    """
    clinic, provider, patient, appt, session, card, qentry, room = fixtures.setup_session_ready(
        clinic_name="C16b", with_exam_room=True
    )
    fixtures.book_room(
        room["id"], qentry["id"], "2026-06-25T09:00:00.000Z", "2026-06-25T09:30:00.000Z"
    )
    room_v2 = fixtures.get_room_version(room["id"])
    # 09:15-09:45 strictly overlaps the existing 09:00-09:30 -> rejected.
    resp = api.create_room_booking(
        {"exam_room_id": room["id"], "queue_entry_id": qentry["id"],
         "start_utc": "2026-06-25T09:15:00.000Z", "end_utc": "2026-06-25T09:45:00.000Z",
         "expected_exam_room_version": room_v2},
        FRONT,
    )
    validate_error(resp, "ERR_ROOM_DOUBLE_BOOKED")


def test_queue_call_state_error_precedes_referential(api):
    """PRD §3.11: "Calling requires the entry to be `WAITING` (otherwise
    `ERR_QUEUE_ENTRY_NOT_WAITING`), requires the parent session's `workflow_status`
    to be `READY_FOR_VISIT` or `CHECKED_IN` (otherwise `ERR_SESSION_NOT_READY`),
    and requires the referenced exam room to belong to the same clinic as the
    session (otherwise `ERR_ROOM_CLINIC_MISMATCH`)."

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_queue_call
    """
    clinic, provider, patient, appt, session, card, qentry, room = fixtures.setup_session_ready(
        clinic_name="C10", with_exam_room=True
    )
    # A second clinic with its own room (different clinic than the session).
    other_clinic = fixtures.create_clinic(name="C10b", facility_fee_cents=0)
    other_room = fixtures.create_exam_room(other_clinic["id"], label="Other")

    # Move the entry to CALLED first so it is no longer WAITING.
    validate_success(api.call_queue_entry(qentry["id"], {"exam_room_id": room["id"]}, FRONT))

    # Re-call with a foreign-clinic room: state failure (not WAITING) AND
    # referential failure (room clinic mismatch) both apply. State priority 6
    # precedes referential priority 8.
    resp = api.call_queue_entry(qentry["id"], {"exam_room_id": other_room["id"]}, FRONT)
    validate_error(resp, "ERR_QUEUE_ENTRY_NOT_WAITING")


def test_queue_call_not_waiting_wins_over_room_mismatch(api):
    """PRD §3.11: "Calling requires the entry to be `WAITING` (otherwise `ERR_QUEUE_ENTRY_NOT_WAITING`)"

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_queue_call
    """
    clinic, provider, patient, appt, session, card, qentry, room = fixtures.setup_session_ready(
        clinic_name="C10c", with_exam_room=True
    )
    other_clinic = fixtures.create_clinic(name="C10d", facility_fee_cents=0)
    other_room = fixtures.create_exam_room(other_clinic["id"], label="Other2")
    fixtures.api_client.call_queue_entry(qentry["id"], {"exam_room_id": room["id"]}, FRONT)
    fixtures.api_client.room_in_queue_entry(qentry["id"], FRONT)  # now IN_ROOM, not WAITING
    resp = api.call_queue_entry(qentry["id"], {"exam_room_id": other_room["id"]}, FRONT)
    validate_error(resp, "ERR_QUEUE_ENTRY_NOT_WAITING")


def test_occ_stale_session_version_on_copay_authorize(api):
    """PRD §2.7: "the authorization is rejected with `ERR_STALE_SESSION_VERSION`
    (HTTP 412)."
    PRD §2.7: "This stale-version check runs before any business validation on the
    copay-authorize operation."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_session_version_on_copay_authorize
    """
    clinic, provider, patient, appt, session, card = fixtures.setup_session_copay_due(
        clinic_name="CE19"
    )
    current = fixtures.session_version(session["id"])
    resp = api.create_copay_payment(
        {"intake_session_id": session["id"], "amount_cents": 9100,
         "expected_intake_session_version": current - 1},
        BILLING,
    )
    validate_error(resp, "ERR_STALE_SESSION_VERSION")


def test_occ_stale_room_version_on_booking(api):
    """PRD §2.7: "If that value does not equal the room's current `version` — for example because another booking has just been written against the room, advancing its version — the booking is rejected with `ERR_STALE_ROOM_VERSION` (HTTP 412). A successful room booking advances the room's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_room_version_on_booking
    """
    clinic, provider, patient, appt, session, card, qentry, room = fixtures.setup_session_ready(
        clinic_name="CE20", with_exam_room=True
    )
    room_v0 = room["version"]
    # First booking advances the room version.
    fixtures.book_room(
        room["id"], qentry["id"], "2026-07-18T08:00:00.000Z", "2026-07-18T08:30:00.000Z",
        expected_version=room_v0,
    )
    # Re-use the now-stale v0.
    resp = api.create_room_booking(
        {"exam_room_id": room["id"], "queue_entry_id": qentry["id"],
         "start_utc": "2026-07-18T09:00:00.000Z", "end_utc": "2026-07-18T09:30:00.000Z",
         "expected_exam_room_version": room_v0},
        FRONT,
    )
    validate_error(resp, "ERR_STALE_ROOM_VERSION")
