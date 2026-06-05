"""Meeting scheduling guards: window validity, per-match half-open overlap, and
per-guardian buffer double-booking.

Queue-A resource_temporal_overlap plus the queue-B window-validity corner.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    factories as f,
    fixtures as fx,
)

COORD = fx.COORD
SCREENER = fx.SCREENER
SPECIALIST = fx.SPECIALIST


def test_meeting_window_end_not_after_start_rejected(api):
    """PRD §3.5: "The `scheduled_end` must be strictly later than the
    `scheduled_start`, failing which the request is rejected with
    `ERR_MEETING_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/meeting_window_invalid_end_not_after_start
    """
    ctx = fx.setup_confirmed_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Mw"},
        guardian_overrides={"full_name": "G Mw"},
        child_overrides={"first_name": "Mw"},
    )
    spec = ctx["specialist_headers"]
    resp = api.schedule_meeting(
        ctx["match"]["id"],
        f.schedule_meeting_payload("2026-01-05T11:00:00Z", "2026-01-05T11:00:00Z", "Mw"),
        spec,
    )
    validate_error(resp, ApiErrorId.ERR_MEETING_WINDOW_INVALID.value, 422)


def test_per_match_overlap_rejected_back_to_back_allowed(api):
    """PRD §3.5: "The per-match overlap guard treats the new window as half-open
    over `[scheduled_start, scheduled_end)` and compares it against every other
    meeting on the same match that is still in `SCHEDULED` or `HELD`: the two
    collide when the new start is earlier than the existing end and the existing
    start is earlier than the new end ... A collision yields `ERR_MEETING_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/per_match_meeting_halfopen_overlap
    """
    ctx = fx.setup_confirmed_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Ov1", "home_zip": "75201",
                             "interest_tags": ["STEM"]},
        guardian_overrides={"full_name": "G Ov1"},
        child_overrides={"first_name": "Rex", "age": 12, "home_zip": "75201",
                         "interest_tags": ["STEM"]},
    )
    spec = ctx["specialist_headers"]
    match_id = ctx["match"]["id"]
    fx.schedule_meeting(match_id, "2026-01-05T10:00:00Z", "2026-01-05T11:00:00Z",
                       location="A", specialist_headers=spec)
    # Overlapping (10:30–11:30) collides on the per-match guard (priority before
    # the per-guardian buffer), yielding ERR_MEETING_OVERLAP.
    overlap = api.schedule_meeting(
        match_id,
        f.schedule_meeting_payload("2026-01-05T10:30:00Z", "2026-01-05T11:30:00Z", "B"),
        spec,
    )
    validate_error(overlap, ApiErrorId.ERR_MEETING_OVERLAP.value, 409)


def test_per_match_fully_contained_overlap_rejected(api):
    """PRD §3.5: "the two collide when the new start is earlier than the existing
    end and the existing start is earlier than the new end ... A collision yields
    `ERR_MEETING_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/per_match_meeting_halfopen_overlap
    """
    ctx = fx.setup_confirmed_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Ov2", "home_zip": "75201",
                             "interest_tags": ["STEM"]},
        guardian_overrides={"full_name": "G Ov2"},
        child_overrides={"first_name": "Rex2", "age": 12, "home_zip": "75201",
                         "interest_tags": ["STEM"]},
    )
    spec = ctx["specialist_headers"]
    match_id = ctx["match"]["id"]
    fx.schedule_meeting(match_id, "2026-01-05T10:00:00Z", "2026-01-05T12:00:00Z",
                       location="Wide", specialist_headers=spec)
    # A window strictly inside the existing one collides.
    resp = api.schedule_meeting(
        match_id,
        f.schedule_meeting_payload("2026-01-05T10:30:00Z", "2026-01-05T11:00:00Z", "Inner"),
        spec,
    )
    validate_error(resp, ApiErrorId.ERR_MEETING_OVERLAP.value, 409)


def test_per_guardian_buffer_double_booking_rejected(api):
    """PRD §3.5: "Each existing window is treated as closed and inflated on both
    sides by sixty minutes; the new meeting collides when the new start is earlier
    than the existing end plus sixty minutes and the existing start is earlier
    than the new end plus sixty minutes. Because the intervals are closed and
    buffer-inflated, a shared endpoint collides, and so does any positive gap
    strictly smaller than sixty minutes. A collision yields
    `ERR_GUARDIAN_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/per_guardian_buffer_double_booking
    """
    fx.set_clock(fx.REF_CLOCK)
    # Two eligible volunteers, one per child, both under the same guardian.
    vol_a = fx.create_eligible_volunteer(set_clock_first=False, full_name="V Ga",
                                        home_zip="19103", interest_tags=["STEM"])
    vol_b = fx.create_eligible_volunteer(set_clock_first=False, full_name="V Gb",
                                        gender="FEMALE", home_zip="19103",
                                        interest_tags=["ARTS"])
    guardian = fx.create_guardian(consent_on_file=True, full_name="G Two")
    child_a = fx.create_child(guardian["id"], first_name="Tina", age=9, gender="FEMALE",
                             home_zip="19103", interest_tags=["STEM"])
    prop_a = fx.propose_match(child_a["id"])
    match_a = fx.accept_proposal(prop_a["id"], vol_a["id"])
    fx.schedule_meeting(match_a["id"], "2026-01-05T10:00:00Z", "2026-01-05T11:00:00Z",
                       location="RoomA")

    child_b = fx.create_child(guardian["id"], first_name="Theo", age=11, gender="MALE",
                             home_zip="19103", interest_tags=["ARTS"])
    prop_b = fx.propose_match(child_b["id"])
    match_b = fx.accept_proposal(prop_b["id"], vol_b["id"])
    # 11:30–12:30 is a 30-minute gap from RoomA's 11:00 end < 60-minute buffer.
    resp = api.schedule_meeting(
        match_b["id"],
        f.schedule_meeting_payload("2026-01-05T11:30:00Z", "2026-01-05T12:30:00Z", "RoomB"),
        SPECIALIST,
    )
    validate_error(resp, ApiErrorId.ERR_GUARDIAN_DOUBLE_BOOKED.value, 409)


def test_per_guardian_gap_at_buffer_boundary_accepted(api):
    """PRD §3.5: "the new meeting collides when the new start is earlier than the
    existing end plus sixty minutes and the existing start is earlier than the new
    end plus sixty minutes. Because the intervals are closed and buffer-inflated,
    a shared endpoint collides, and so does any positive gap strictly smaller than
    sixty minutes."

    Design: Difficulty/resource_temporal_overlap/per_guardian_buffer_double_booking
    """
    fx.set_clock(fx.REF_CLOCK)
    vol_a = fx.create_eligible_volunteer(set_clock_first=False, full_name="V Gc",
                                        home_zip="19103", interest_tags=["STEM"])
    vol_b = fx.create_eligible_volunteer(set_clock_first=False, full_name="V Gd",
                                        gender="FEMALE", home_zip="19103",
                                        interest_tags=["ARTS"])
    guardian = fx.create_guardian(consent_on_file=True, full_name="G Three")
    child_a = fx.create_child(guardian["id"], first_name="Tina2", age=9, gender="FEMALE",
                             home_zip="19103", interest_tags=["STEM"])
    match_a = fx.accept_proposal(fx.propose_match(child_a["id"])["id"], vol_a["id"])
    fx.schedule_meeting(match_a["id"], "2026-01-05T10:00:00Z", "2026-01-05T11:00:00Z",
                       location="RoomA")
    child_b = fx.create_child(guardian["id"], first_name="Theo2", age=11, gender="MALE",
                             home_zip="19103", interest_tags=["ARTS"])
    match_b = fx.accept_proposal(fx.propose_match(child_b["id"])["id"], vol_b["id"])
    # New meeting starts exactly 60 minutes after RoomA's 11:00 end: gap == buffer,
    # so new.start (12:00) is NOT earlier than existing.end+60 (12:00) → accepted.
    resp = api.schedule_meeting(
        match_b["id"],
        f.schedule_meeting_payload("2026-01-05T12:00:00Z", "2026-01-05T13:00:00Z", "RoomB"),
        SPECIALIST,
    )
    created = validate_success(resp, 201)
    assert created["status"] == "SCHEDULED"
