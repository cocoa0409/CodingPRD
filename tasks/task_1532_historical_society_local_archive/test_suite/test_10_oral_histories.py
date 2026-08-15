"""Oral-history recordings: the studio turnaround buffer and the two-
dimensional release gate."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_collection,
    create_oral_history,
    create_zone,
    set_clock,
    walk_recording_to_review,
    validate_error,
    validate_success,
)

ARCH = {"X-User-ID": "arch-1", "X-User-Role": "Archivist", "Content-Type": "application/json"}


class TestStudioTurnaroundBuffer:

    def _collection(self):
        zone = create_zone()
        return create_collection(zone["id"])

    def test_gap_below_30_minutes_conflicts(self):
        """PRD §3.9: "A new session conflicts with an existing non-cancelled
        session in the same room unless at least the full turnaround separates
        them — precisely, unless the new session's end plus 30 minutes falls at
        or before the existing session's start, or the existing session's end
        plus 30 minutes falls at or before the new session's start. A gap of
        exactly 30 minutes is permitted; a 29-minute gap is a conflict, rejected
        with `ERR_RECORDING_ROOM_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/studio_turnaround_buffer_gap_semantics
        """
        collection = self._collection()
        first = create_oral_history(
            collection["id"], recording_room_id="STUDIO_A",
            session_start="2026-09-01T10:00:00Z",
            session_end="2026-09-01T12:00:00Z")
        assert first["status"] == "SCHEDULED"
        assert first["release_status"] == "PENDING"

        # Back-to-back (gap 0) conflicts: closed session bounds.
        resp1 = api_client.create_oral_history(
            {"collection_id": collection["id"], "narrator_name": "N. Two",
             "interviewer_name": "I. One", "recording_room_id": "STUDIO_A",
             "session_start": "2026-09-01T12:00:00Z",
             "session_end": "2026-09-01T13:00:00Z"}, ARCH)
        validate_error(resp1, ApiErrorId.ERR_RECORDING_ROOM_CONFLICT)

        # A 29-minute gap also conflicts.
        resp2 = api_client.create_oral_history(
            {"collection_id": collection["id"], "narrator_name": "N. Two",
             "interviewer_name": "I. One", "recording_room_id": "STUDIO_A",
             "session_start": "2026-09-01T12:29:00Z",
             "session_end": "2026-09-01T13:00:00Z"}, ARCH)
        validate_error(resp2, ApiErrorId.ERR_RECORDING_ROOM_CONFLICT)

    def test_exactly_30_minute_gap_admitted_and_other_room_unaffected(self):
        """PRD §3.9: "A new session conflicts with an existing non-cancelled
        session in the same room unless at least the full turnaround separates
        them — precisely, unless the new session's end plus 30 minutes falls at
        or before the existing session's start, or the existing session's end
        plus 30 minutes falls at or before the new session's start. A gap of
        exactly 30 minutes is permitted; a 29-minute gap is a conflict, rejected
        with `ERR_RECORDING_ROOM_CONFLICT`. Only sessions that have not been
        `CANCELLED` participate in the check."
        PRD §3.9: "Each studio is a single-resource pool guarded by a mandatory
        30-minute turnaround buffer, and its interval semantics deliberately
        differ from the reading room's."

        Design: Difficulty/resource_temporal_overlap/studio_turnaround_buffer_gap_semantics
        """
        collection = self._collection()
        create_oral_history(
            collection["id"], recording_room_id="STUDIO_A",
            session_start="2026-09-01T10:00:00Z",
            session_end="2026-09-01T12:00:00Z")

        # Exactly the 30-minute turnaround: admitted (the bound is inclusive).
        exact = validate_success(api_client.create_oral_history(
            {"collection_id": collection["id"], "narrator_name": "N. Two",
             "interviewer_name": "I. One", "recording_room_id": "STUDIO_A",
             "session_start": "2026-09-01T12:30:00Z",
             "session_end": "2026-09-01T13:30:00Z"}, ARCH),
            expected_status=201)
        assert exact["status"] == "SCHEDULED"

        # The parallel studio is a separate pool: overlapping times are fine.
        other_room = validate_success(api_client.create_oral_history(
            {"collection_id": collection["id"], "narrator_name": "N. Three",
             "interviewer_name": "I. One", "recording_room_id": "STUDIO_B",
             "session_start": "2026-09-01T11:00:00Z",
             "session_end": "2026-09-01T12:00:00Z"}, ARCH),
            expected_status=201)
        assert other_room["status"] == "SCHEDULED"


class TestReleaseGates:

    def test_oral_history_release_gates(self):
        """PRD §3.9: "Recording the narrator's signed release requires
        `release_status` to be `PENDING` and the body's
        `signed_by_narrator_name` to equal the recording's `narrator_name`
        exactly — any difference, however small, is `ERR_NARRATOR_MISMATCH`."
        PRD §3.9: "Publication (`IN_REVIEW → RELEASED`) joins the two
        dimensions: it requires the workflow state `IN_REVIEW`, a
        `release_status` of `SIGNED` (else `ERR_RELEASE_FORM_MISSING`), and any
        recorded `embargo_until` to have lapsed — an embargo lying strictly
        after the current logical time blocks publication with
        `ERR_ORAL_HISTORY_EMBARGOED`, while a null embargo or one exactly at the
        current time does not."

        Design: Corner/errors/oral_history_release_gates
        """
        zone = create_zone()
        collection = create_collection(zone["id"])
        recording = create_oral_history(
            collection["id"], narrator_name="N. One",
            session_start="2026-07-20T10:00:00Z",
            session_end="2026-07-20T11:00:00Z")
        walked = walk_recording_to_review(recording["id"])
        assert walked["status"] == "IN_REVIEW"
        assert walked["release_status"] == "PENDING"

        # Publish while the release is still PENDING.
        resp1 = api_client.publish_release(recording["id"], ARCH)
        validate_error(resp1, ApiErrorId.ERR_RELEASE_FORM_MISSING)

        # The signer must equal the narrator exactly.
        resp2 = api_client.sign_release(
            recording["id"], {"signed_by_narrator_name": "N. Other"}, ARCH)
        validate_error(resp2, ApiErrorId.ERR_NARRATOR_MISMATCH)
        mid = validate_success(api_client.get_oral_history(recording["id"], ARCH))
        assert mid["release_status"] == "PENDING"

        # Correct signer with a future embargo.
        signed = validate_success(api_client.sign_release(
            recording["id"],
            {"signed_by_narrator_name": "N. One",
             "embargo_until": "2026-12-01T00:00:00Z"}, ARCH))
        assert signed["release_status"] == "SIGNED"

        # Embargo lies strictly after the 2026-08-01 default clock.
        resp3 = api_client.publish_release(recording["id"], ARCH)
        validate_error(resp3, ApiErrorId.ERR_ORAL_HISTORY_EMBARGOED)

        # At exactly the embargo instant the gate opens.
        set_clock("2026-12-01T00:00:00Z")
        released = validate_success(
            api_client.publish_release(recording["id"], ARCH))
        assert released["status"] == "RELEASED"
