"""Session scheduling: room conflicts, facilitator double-booking, and window bounds."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_onsite_cohort_for_sessions, add_session, create_facilitator,
    TEST_USERS,
)

COORD = TEST_USERS["scheduling_coordinator_headers"]


def test_session_out_of_cohort_range_rejected(api):
    """PRD §3.4: "A session must lie entirely within the cohort window — its interval must fall
    within the cohort's `starts_at` and `ends_at` — or it is rejected with
    `ERR_SESSION_OUT_OF_RANGE` (HTTP 422)."

    Design: Corner/validations/session_out_of_cohort_range_rejected
    """
    ctx = setup_onsite_cohort_for_sessions(
        starts_at="2026-07-17T09:00:00Z", ends_at="2026-07-17T17:00:00Z",
        enroll_deadline="2026-07-16T00:00:00Z",
    )
    resp = api.create_session(
        ctx["cohort"]["id"],
        {"title": "Late", "starts_at": "2026-07-17T18:00:00Z", "ends_at": "2026-07-17T19:00:00Z",
         "room_or_url": "ROOM-X"},
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_OUT_OF_RANGE.value)


def test_room_conflict_closed_interval_abutment_rejected(api):
    """PRD §3.4: "Two sessions of the same cohort that share a `room_or_url` must not overlap, and
    the interval is treated as closed: even adjacency at a shared boundary instant is rejected, so
    back-to-back sessions in the same room need a genuine gap between them. A violation yields
    `ERR_ROOM_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/room_conflict_closed_interval_abutment_rejected
    """
    ctx = setup_onsite_cohort_for_sessions(
        starts_at="2026-06-07T08:00:00Z", ends_at="2026-06-07T18:00:00Z",
        enroll_deadline="2026-06-06T00:00:00Z",
    )
    coh_id = ctx["cohort"]["id"]
    add_session(coh_id, "S1", "2026-06-07T09:00:00Z", "2026-06-07T10:00:00Z", "ROOM-A")
    # S2 starts at 10:00 exactly when S1 ends -> abutment rejected under closed-interval semantics.
    resp = api.create_session(
        coh_id,
        {"title": "S2", "starts_at": "2026-06-07T10:00:00Z", "ends_at": "2026-06-07T11:00:00Z",
         "room_or_url": "ROOM-A"},
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_ROOM_CONFLICT.value)


def test_room_conflict_genuine_overlap_rejected(api):
    """PRD §3.4: "Two sessions of the same cohort that share a `room_or_url` must not overlap, and
    the interval is treated as closed: even adjacency at a shared boundary instant is rejected, so
    back-to-back sessions in the same room need a genuine gap between them. A violation yields
    `ERR_ROOM_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/room_conflict_closed_interval_abutment_rejected
    """
    ctx = setup_onsite_cohort_for_sessions(
        starts_at="2026-06-07T08:00:00Z", ends_at="2026-06-07T18:00:00Z",
        enroll_deadline="2026-06-06T00:00:00Z",
    )
    coh_id = ctx["cohort"]["id"]
    add_session(coh_id, "S1", "2026-06-07T09:00:00Z", "2026-06-07T11:00:00Z", "ROOM-A")
    # S2 10:00-12:00 genuinely overlaps S1 09:00-11:00 in the same room.
    resp = api.create_session(
        coh_id,
        {"title": "S2", "starts_at": "2026-06-07T10:00:00Z", "ends_at": "2026-06-07T12:00:00Z",
         "room_or_url": "ROOM-A"},
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_ROOM_CONFLICT.value)


def test_facilitator_double_booked_half_open_overlap_rejected(api):
    """PRD §3.4: "A single facilitator's `ACTIVE` assignments may not overlap in time: overlap is
    judged on a half-open interval, so two assignments that merely touch at an endpoint are
    allowed but any genuine overlap is rejected with `ERR_FACILITATOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/facilitator_double_booked_half_open_overlap_rejected
    """
    ctx = setup_onsite_cohort_for_sessions(
        starts_at="2026-06-08T08:00:00Z", ends_at="2026-06-08T18:00:00Z",
        enroll_deadline="2026-06-07T00:00:00Z", lead_email="leadfac8@example.com",
    )
    coh_id = ctx["cohort"]["id"]
    cofac = create_facilitator(certified_categories=["TECHNICAL"], email="cofac8@example.com",
                               full_name="Co Fac")
    s1 = add_session(coh_id, "S1", "2026-06-08T09:00:00Z", "2026-06-08T10:00:00Z", "ROOM-1")
    s2 = add_session(coh_id, "S2", "2026-06-08T10:00:00Z", "2026-06-08T11:00:00Z", "ROOM-2")
    s3 = add_session(coh_id, "S3", "2026-06-08T09:30:00Z", "2026-06-08T10:30:00Z", "ROOM-3")
    # S1 then S2 (touching at 10:00) both succeed under half-open semantics.
    validate_success(
        api.create_session_assignment(s1["id"], {"facilitator_id": cofac["id"], "role": "ASSIST"}, COORD),
        expected_status=201,
    )
    validate_success(
        api.create_session_assignment(s2["id"], {"facilitator_id": cofac["id"], "role": "ASSIST"}, COORD),
        expected_status=201,
    )
    # S3 09:30-10:30 genuinely overlaps S1 09:00-10:00 -> rejected.
    resp = api.create_session_assignment(s3["id"], {"facilitator_id": cofac["id"], "role": "ASSIST"}, COORD)
    validate_error(resp, ApiErrorId.ERR_FACILITATOR_DOUBLE_BOOKED.value)


def test_facilitator_touching_assignments_allowed(api):
    """PRD §3.4: "overlap is judged on a half-open interval, so two assignments that merely touch
    at an endpoint are allowed but any genuine overlap is rejected with
    `ERR_FACILITATOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/facilitator_double_booked_half_open_overlap_rejected
    """
    ctx = setup_onsite_cohort_for_sessions(
        starts_at="2026-06-08T08:00:00Z", ends_at="2026-06-08T18:00:00Z",
        enroll_deadline="2026-06-07T00:00:00Z", lead_email="leadfac8b@example.com",
    )
    coh_id = ctx["cohort"]["id"]
    cofac = create_facilitator(certified_categories=["TECHNICAL"], email="cofac8b@example.com",
                               full_name="Co Fac B")
    s1 = add_session(coh_id, "S1", "2026-06-08T09:00:00Z", "2026-06-08T10:00:00Z", "ROOM-1")
    s2 = add_session(coh_id, "S2", "2026-06-08T10:00:00Z", "2026-06-08T11:00:00Z", "ROOM-2")
    # Two assignments touching at the 10:00 boundary are both permitted (half-open interval).
    validate_success(
        api.create_session_assignment(s1["id"], {"facilitator_id": cofac["id"]}, COORD),
        expected_status=201,
    )
    data = validate_success(
        api.create_session_assignment(s2["id"], {"facilitator_id": cofac["id"]}, COORD),
        expected_status=201,
    )
    assert data["status"] == "ACTIVE"
