"""Calendar guards at session scheduling: organizer travel buffer and client
home whole-day exclusivity.
"""
from test_helpers import (
    validate_success, validate_error,
    create_session_payload,
    new_client, new_organizer, new_project, activate_project, new_session,
    make_organizer_headers,
)


# ── Difficulty: organizer travel-buffer overlap ───────────────────────────────

def test_organizer_sessions_within_travel_buffer_rejected(api):
    """PRD §3.3: "no other non-cancelled session for the same organizer_id may sit
    within a 30-minute travel buffer of the new one — that is, the gap between this
    session and any adjacent session of the same organizer must be at least 30
    minutes on either side. A violation is rejected with ERR_ORGANIZER_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/organizer_travel_buffer_overlap
    """
    ca, cb, organizer = new_client(), new_client(), new_organizer()
    pa = activate_project(new_project(ca["id"], organizer["id"], scope_rooms=["Room"])["id"])
    pb = activate_project(new_project(cb["id"], organizer["id"], scope_rooms=["Room"])["id"])
    new_session(pa["id"], organizer["id"], "2026-03-02T09:00:00Z", "2026-03-02T11:00:00Z")
    # New session starts 15 min after the first ends → gap < 30 min buffer.
    payload = create_session_payload(pb["id"], organizer["id"],
                                     "2026-03-02T11:15:00Z", "2026-03-02T12:15:00Z")
    res = api.create_session(payload, make_organizer_headers(organizer["id"]))
    validate_error(res, "ERR_ORGANIZER_DOUBLE_BOOKED")


def test_organizer_sessions_at_exactly_30_minute_gap_allowed(api):
    """PRD §3.3: "no other non-cancelled session for the same organizer_id may sit
    within a 30-minute travel buffer of the new one — that is, the gap between this
    session and any adjacent session of the same organizer must be at least 30
    minutes on either side. A violation is rejected with ERR_ORGANIZER_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/organizer_travel_buffer_overlap
    """
    ca, cb, organizer = new_client(), new_client(), new_organizer()
    pa = activate_project(new_project(ca["id"], organizer["id"], scope_rooms=["Room"])["id"])
    pb = activate_project(new_project(cb["id"], organizer["id"], scope_rooms=["Room"])["id"])
    new_session(pa["id"], organizer["id"], "2026-03-02T09:00:00Z", "2026-03-02T11:00:00Z")
    # Gap between 11:00 end and 11:30 start is exactly 30 minutes → allowed.
    payload = create_session_payload(pb["id"], organizer["id"],
                                     "2026-03-02T11:30:00Z", "2026-03-02T12:30:00Z")
    res = api.create_session(payload, make_organizer_headers(organizer["id"]))
    scheduled = validate_success(res, 201)
    assert scheduled["status"] == "SCHEDULED"


# ── Difficulty: client home whole-day exclusivity ─────────────────────────────

def test_client_two_sessions_same_calendar_date_rejected(api):
    """PRD §3.3: "no other non-cancelled session belonging to any project of the same
    client may fall on the same UTC calendar date as this session's scheduled_start;
    a violation is rejected with ERR_CLIENT_HOME_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/client_home_whole_day_overlap
    """
    client, o1, o2 = new_client(), new_organizer(), new_organizer()
    project = activate_project(new_project(client["id"], o1["id"], scope_rooms=["Room"])["id"])
    new_session(project["id"], o1["id"], "2026-03-02T09:00:00Z", "2026-03-02T10:00:00Z")
    # Same client, same date, 4 hours later, different organizer → whole-day collision.
    payload = create_session_payload(project["id"], o2["id"],
                                     "2026-03-02T14:00:00Z", "2026-03-02T15:00:00Z")
    res = api.create_session(payload, make_organizer_headers(o2["id"]))
    validate_error(res, "ERR_CLIENT_HOME_DOUBLE_BOOKED")


def test_client_sessions_on_different_dates_allowed(api):
    """PRD §3.3: "no other non-cancelled session belonging to any project of the same
    client may fall on the same UTC calendar date as this session's scheduled_start;
    a violation is rejected with ERR_CLIENT_HOME_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/client_home_whole_day_overlap
    """
    client, o1, o2 = new_client(), new_organizer(), new_organizer()
    project = activate_project(new_project(client["id"], o1["id"], scope_rooms=["Room"])["id"])
    new_session(project["id"], o1["id"], "2026-03-02T09:00:00Z", "2026-03-02T10:00:00Z")
    # Different UTC calendar date → no whole-day collision; different organizer → no buffer.
    payload = create_session_payload(project["id"], o2["id"],
                                     "2026-03-09T14:00:00Z", "2026-03-09T15:00:00Z")
    res = api.create_session(payload, make_organizer_headers(o2["id"]))
    scheduled = validate_success(res, 201)
    assert scheduled["status"] == "SCHEDULED"
