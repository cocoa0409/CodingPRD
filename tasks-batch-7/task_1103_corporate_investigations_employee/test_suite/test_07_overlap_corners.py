"""Corner tests for the two overlap geometries: half-open interviews and
closed-interval collection scopes."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case_in_fieldwork,
    create_interview_payload, create_collection_scope_payload,
    add_acknowledged_notice,
    make_investigator_headers, TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
GC = TEST_USERS["gc_headers"]


def test_room_buffer_overlap_rejected(api):
    """PRD §3.5: "Second, when `room_ref` is supplied, the same room may not
    have another interview in `SCHEDULED` or `UPJOHN_DELIVERED` whose window,
    expanded by fifteen minutes on both sides, intersects the requested
    window — back-to-back bookings with a gap of less than fifteen minutes
    are rejected (`ERR_ROOM_OVERLAP`)."

    Design: Corner/state_machines/room_buffer_overlap_rejected
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="RoomBuf", allegation_category="HARASSMENT", severity="MEDIUM",
        department="Ops",
    )
    case = bundle["case"]
    # First booking in room R1 [14:00, 15:00]
    get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-10T14:00:00Z",
            scheduled_end="2026-05-10T15:00:00Z",
            room_ref="R1",
        ),
        INV,
    ))
    # Gap of only 10 minutes — must reject
    resp = api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-2", interviewer_id="inv-8",
            scheduled_start="2026-05-10T15:10:00Z",
            scheduled_end="2026-05-10T15:40:00Z",
            room_ref="R1",
        ),
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_ROOM_OVERLAP, expected_status=409)
    # Gap of exactly 15 minutes — accepted
    ok = api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-3", interviewer_id="inv-8",
            scheduled_start="2026-05-10T15:15:00Z",
            scheduled_end="2026-05-10T16:00:00Z",
            room_ref="R1",
        ),
        INV,
    )
    second = validate_success(ok, expected_status=201)
    assert second["status"] == "SCHEDULED"
