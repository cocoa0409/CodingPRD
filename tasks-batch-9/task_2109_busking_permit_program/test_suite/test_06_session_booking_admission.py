"""Admitting a session booking: ordinance windows, pitch capacity and money."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_session_booking, assert_minute_ledger_invariant,
    create_session_booking_payload,
    set_clock, create_zone, create_pitch, create_performer,
    setup_active_permit, setup_district_pitch_and_active_permit,
    book_session, book_series, read_permit, permit_version, list_bookings,
    draft_and_activate_closure, read_pitch,
    make_officer_headers, make_performer_headers,
)
from test_helpers.api_client import api_client


OLD_TOWN = dict(name="Old Town", code="OT", base_noise_cap_db=72,
                evening_start_minute=1020, quiet_hours_start_minute=1260,
                quiet_hours_end_minute=480, weekend_noise_bonus_db=0,
                evening_penalty_db=8, max_concurrent_closures=2)


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict /
#          safety_quiet_hours_outranks_constraint_pitch_slot_overlap
# ---------------------------------------------------------------------------

def _old_town_with_evening_booking():
    ctx = setup_district_pitch_and_active_permit(
        zone_overrides=OLD_TOWN,
        pitch_overrides=dict(code="OT-01", tier="STANDARD", noise_cap_db=70,
                             amplification_allowed=False,
                             max_session_minutes=120, daily_session_cap=2))
    ctx["booking"] = book_session(
        ctx["permit"]["id"], ctx["pitch"]["id"],
        "2026-08-10T20:00:00Z", "2026-08-10T21:00:00Z", ctx["performer"]["id"])
    return ctx


def test_quiet_hours_violation_outranks_the_pitch_overlap_rule(api):
    """PRD §2.6: "A request is validated as an ordered sequence of checks, and
    the **first** check that fails decides the response; no later check may mask
    an earlier one, and no earlier check may be skipped because a later one
    would also fail."
    PRD §2.6: "21. The requested occupation window avoids the district's quiet
    window, otherwise `ERR_QUIET_HOURS_VIOLATION`. Applies to session booking and
    to draw creation."
    PRD §2.6: "33. The pitch occupation does not conflict with an existing
    occupation under the buffered interval test, otherwise
    `ERR_PITCH_SLOT_OVERLAP`. Applies to session booking and to draw creation."

    Design: Difficulty/priority_pair_validation_conflict/safety_quiet_hours_outranks_constraint_pitch_slot_overlap
    """
    ctx = _old_town_with_evening_booking()
    version_before = permit_version(ctx["permit"]["id"])

    resp = api.create_session_booking(
        create_session_booking_payload(
            ctx["permit"]["id"], ctx["pitch"]["id"],
            "2026-08-10T20:45:00Z", "2026-08-10T21:45:00Z", version_before),
        make_performer_headers(ctx["performer"]["id"]))
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_QUIET_HOURS_VIOLATION)

    permit = read_permit(ctx["permit"]["id"])
    assert permit["season_minutes_used"] == 60
    assert permit["version"] == version_before, \
        "a rejected booking must not advance the permit's version"


def test_control_request_violating_only_the_overlap_rule_reports_slot_overlap(api):
    """PRD §3.6: "A mandatory changeover buffer of 15 minutes is then applied on
    both sides of every comparison: the new occupation conflicts with an existing
    one when the new `start_at` is earlier than the existing end plus 15 minutes
    **and** the new `end_at` is later than the existing start minus 15 minutes."
    PRD §3.6: "No minute of the half-open occupation window may fall inside the
    district's quiet window, remembering that the window wraps midnight when its
    start minute is greater than its end minute, and that a district whose two
    quiet-hour minutes are equal has no quiet window at all; a violation is
    refused with `ERR_QUIET_HOURS_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/safety_quiet_hours_outranks_constraint_pitch_slot_overlap
    """
    ctx = _old_town_with_evening_booking()
    version_before = permit_version(ctx["permit"]["id"])

    resp = api.create_session_booking(
        create_session_booking_payload(
            ctx["permit"]["id"], ctx["pitch"]["id"],
            "2026-08-10T19:30:00Z", "2026-08-10T20:30:00Z", version_before),
        make_performer_headers(ctx["performer"]["id"]))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_PITCH_SLOT_OVERLAP)

    permit = read_permit(ctx["permit"]["id"])
    assert permit["season_minutes_used"] == 60
    assert permit["version"] == version_before
    assert ctx["booking"]["status"] == "RESERVED"


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap /
#          pitch_changeover_buffer_rejects_back_to_back_sessions
# ---------------------------------------------------------------------------

def _riverside_with_morning_booking():
    ctx = setup_district_pitch_and_active_permit(
        pitch_overrides=dict(code="RP-01", tier="STANDARD", noise_cap_db=82,
                             amplification_allowed=True,
                             max_session_minutes=120, daily_session_cap=3))
    ctx["booking"] = book_session(
        ctx["permit"]["id"], ctx["pitch"]["id"],
        "2026-08-25T10:00:00Z", "2026-08-25T11:00:00Z", ctx["performer"]["id"])
    return ctx


def test_session_starting_exactly_at_the_previous_end_is_refused(api):
    """PRD §3.6: "A mandatory changeover buffer of 15 minutes is then applied on
    both sides of every comparison: the new occupation conflicts with an existing
    one when the new `start_at` is earlier than the existing end plus 15 minutes
    **and** the new `end_at` is later than the existing start minus 15 minutes."
    PRD §3.6: "Two occupations that merely touch — one ending exactly when the
    other begins — therefore do conflict, because the buffer swallows the seam.
    Any conflict is refused with `ERR_PITCH_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/pitch_changeover_buffer_rejects_back_to_back_sessions
    """
    ctx = _riverside_with_morning_booking()
    version_before = permit_version(ctx["permit"]["id"])

    resp = api.create_session_booking(
        create_session_booking_payload(
            ctx["permit"]["id"], ctx["pitch"]["id"],
            "2026-08-25T11:00:00Z", "2026-08-25T12:00:00Z", version_before),
        make_performer_headers(ctx["performer"]["id"]))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_PITCH_SLOT_OVERLAP)
    assert read_permit(ctx["permit"]["id"])["season_minutes_used"] == 60


def test_session_starting_after_the_full_changeover_buffer_is_admitted(api):
    """PRD §3.6: "A mandatory changeover buffer of 15 minutes is then applied on
    both sides of every comparison: the new occupation conflicts with an existing
    one when the new `start_at` is earlier than the existing end plus 15 minutes
    **and** the new `end_at` is later than the existing start minus 15 minutes."
    PRD §3.6: "On admission the booking's `duration_minutes` is added to the
    permit's `season_minutes_used` and the permit's `version` is incremented."

    Design: Difficulty/resource_temporal_overlap/pitch_changeover_buffer_rejects_back_to_back_sessions
    """
    ctx = _riverside_with_morning_booking()
    resp = api.create_session_booking(
        create_session_booking_payload(
            ctx["permit"]["id"], ctx["pitch"]["id"],
            "2026-08-25T11:15:00Z", "2026-08-25T12:15:00Z",
            permit_version(ctx["permit"]["id"])),
        make_performer_headers(ctx["performer"]["id"]))
    booking = validate_success(resp, 201)
    assert_session_booking(booking)
    assert booking["status"] == "RESERVED"
    assert booking["duration_minutes"] == 60
    assert read_permit(ctx["permit"]["id"])["season_minutes_used"] == 120

    _, meta = validate_paginated(api.list_session_bookings(
        make_officer_headers(), params={"pitch_id": ctx["pitch"]["id"]}))
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Queue B: temporal admission rules
# ---------------------------------------------------------------------------

def test_booking_lead_time_and_horizon_are_both_enforced(api):
    """PRD §3.6: "The session must start at least one hour after the current
    program clock — a `start_at` closer than 60 minutes away is refused with
    `ERR_BOOKING_LEAD_TIME` — and no more than 30 days after it, refused beyond
    that with `ERR_BOOKING_HORIZON_EXCEEDED`."
    PRD §2.5: "The server holds a single logical UTC clock that starts at exactly
    `2026-08-01T00:00:00Z` when the process boots and stays there until it is
    moved explicitly; it must never fall back to the host's real time, not even
    before the first move."
    PRD §3.1: "when the two values are equal the district has no quiet window
    whatsoever and nothing is ever refused on quiet-hours grounds there."
    The district is registered without a quiet window on purpose: PRD §2.6 ranks
    the quiet-window check (21) ahead of the lead-time check (26), so a district
    that closes 23:00-06:00 would answer the sub-hour start with
    `ERR_QUIET_HOURS_VIOLATION` and the lead-time rule would never be reached.

    Design: Corner/validations/corner_booking_lead_time_and_horizon_enforced
    """
    ctx = setup_district_pitch_and_active_permit(
        zone_overrides=dict(name="Nightgate Wharf", code="NW",
                            base_noise_cap_db=78, evening_start_minute=1080,
                            quiet_hours_start_minute=0, quiet_hours_end_minute=0,
                            weekend_noise_bonus_db=0, evening_penalty_db=0,
                            max_concurrent_closures=1),
        pitch_overrides=dict(code="RP-01", tier="STANDARD", noise_cap_db=82,
                             amplification_allowed=True))
    permit_id, pitch_id = ctx["permit"]["id"], ctx["pitch"]["id"]
    performer_id = ctx["performer"]["id"]
    version = permit_version(permit_id)

    too_soon = api.create_session_booking(
        create_session_booking_payload(permit_id, pitch_id,
                                       "2026-08-01T00:30:00Z",
                                       "2026-08-01T01:30:00Z", version),
        make_performer_headers(performer_id))
    assert too_soon.status_code == 422, f"Expected 422, got {too_soon.status_code}"
    validate_error(too_soon, ApiErrorId.ERR_BOOKING_LEAD_TIME)

    too_far = api.create_session_booking(
        create_session_booking_payload(permit_id, pitch_id,
                                       "2026-09-05T10:00:00Z",
                                       "2026-09-05T11:00:00Z", version),
        make_performer_headers(performer_id))
    assert too_far.status_code == 422, f"Expected 422, got {too_far.status_code}"
    validate_error(too_far, ApiErrorId.ERR_BOOKING_HORIZON_EXCEEDED)

    inside = api.create_session_booking(
        create_session_booking_payload(permit_id, pitch_id,
                                       "2026-08-25T10:00:00Z",
                                       "2026-08-25T11:00:00Z", version),
        make_performer_headers(performer_id))
    booking = validate_success(inside, 201)
    assert booking["status"] == "RESERVED"
    assert read_permit(permit_id)["season_minutes_used"] == 60


def test_pitch_daily_session_cap_counts_one_utc_calendar_date(api):
    """PRD §3.6: "The second rule is a simple headcount: the number of sessions
    already on that pitch with `status` `RESERVED`, `RELOCATED` or `COMPLETED`
    whose `start_at` falls on the same UTC calendar date as the new one must be
    strictly below the pitch's `daily_session_cap`, otherwise
    `ERR_PITCH_DAILY_CAP_REACHED`."

    Design: Corner/validations/corner_pitch_daily_session_cap_enforced_per_utc_date
    """
    ctx = setup_district_pitch_and_active_permit(
        zone_overrides=OLD_TOWN,
        pitch_overrides=dict(code="OT-01", tier="STANDARD", noise_cap_db=70,
                             amplification_allowed=False,
                             max_session_minutes=120, daily_session_cap=2))
    permit_id, pitch_id = ctx["permit"]["id"], ctx["pitch"]["id"]
    performer_id = ctx["performer"]["id"]
    book_series(permit_id, pitch_id, performer_id, [
        ("2026-08-25T09:00:00Z", "2026-08-25T10:00:00Z"),
        ("2026-08-25T11:00:00Z", "2026-08-25T12:00:00Z"),
    ])

    third_same_day = api.create_session_booking(
        create_session_booking_payload(permit_id, pitch_id,
                                       "2026-08-25T14:00:00Z",
                                       "2026-08-25T15:00:00Z",
                                       permit_version(permit_id)),
        make_performer_headers(performer_id))
    assert third_same_day.status_code == 409, \
        f"Expected 409, got {third_same_day.status_code}"
    validate_error(third_same_day, ApiErrorId.ERR_PITCH_DAILY_CAP_REACHED)

    next_day = api.create_session_booking(
        create_session_booking_payload(permit_id, pitch_id,
                                       "2026-08-26T14:00:00Z",
                                       "2026-08-26T15:00:00Z",
                                       permit_version(permit_id)),
        make_performer_headers(performer_id))
    validate_success(next_day, 201)

    assert read_permit(permit_id)["season_minutes_used"] == 180
    _, meta = validate_paginated(api.list_session_bookings(
        make_officer_headers(), params={"pitch_id": pitch_id}))
    assert meta["total_count"] == 3


def test_session_longer_than_the_pitch_ceiling_is_refused(api):
    """PRD §3.6: "The `duration_minutes` must not exceed the pitch's
    `max_session_minutes`, otherwise `ERR_SESSION_TOO_LONG`."
    PRD §3.6: "From those two instants the server computes `duration_minutes`,
    the whole number of minutes between them."

    Design: Corner/errors/corner_error_session_too_long_for_the_pitch
    """
    ctx = setup_district_pitch_and_active_permit(
        pitch_overrides=dict(code="RP-03", tier="STANDARD", noise_cap_db=80,
                             amplification_allowed=False,
                             max_session_minutes=60, daily_session_cap=3))
    permit_id, pitch_id = ctx["permit"]["id"], ctx["pitch"]["id"]
    performer_id = ctx["performer"]["id"]
    version = permit_version(permit_id)

    too_long = api.create_session_booking(
        create_session_booking_payload(permit_id, pitch_id,
                                       "2026-08-25T10:00:00Z",
                                       "2026-08-25T12:00:00Z", version),
        make_performer_headers(performer_id))
    assert too_long.status_code == 422, f"Expected 422, got {too_long.status_code}"
    validate_error(too_long, ApiErrorId.ERR_SESSION_TOO_LONG)

    exact = api.create_session_booking(
        create_session_booking_payload(permit_id, pitch_id,
                                       "2026-08-25T10:00:00Z",
                                       "2026-08-25T11:00:00Z", version),
        make_performer_headers(performer_id))
    booking = validate_success(exact, 201)
    assert booking["duration_minutes"] == 60, \
        "a session landing exactly on max_session_minutes is admitted"
    assert read_permit(permit_id)["season_minutes_used"] == 60


def test_amplification_prohibited_on_the_pitch_outranks_session_too_long(api):
    """PRD §2.6: "19. Amplification is permitted on the pitch, otherwise
    `ERR_AMPLIFICATION_PROHIBITED`."
    PRD §2.6: "25. The occupation is no longer than the pitch's per-session
    ceiling, otherwise `ERR_SESSION_TOO_LONG`. Applies to session booking and to
    draw creation."
    PRD §3.6: "If `amplification_planned` is true, the pitch must have
    `amplification_allowed` true — a quiet pitch refuses amplified acts outright
    with `ERR_AMPLIFICATION_PROHIBITED` — and the permit must have
    `amplification_endorsed` true, since a permit issued without an endorsement
    may not amplify anywhere, refused with `ERR_AMPLIFICATION_NOT_ENDORSED`."

    Design: Corner/validations/corner_amplification_prohibited_outranks_session_too_long
    """
    ctx = setup_district_pitch_and_active_permit(
        zone_overrides=OLD_TOWN,
        pitch_overrides=dict(code="OT-01", tier="STANDARD", noise_cap_db=70,
                             amplification_allowed=False,
                             max_session_minutes=60, daily_session_cap=2))
    permit_id, pitch_id = ctx["permit"]["id"], ctx["pitch"]["id"]

    resp = api.create_session_booking(
        create_session_booking_payload(permit_id, pitch_id,
                                       "2026-08-25T10:00:00Z",
                                       "2026-08-25T12:00:00Z",
                                       permit_version(permit_id),
                                       amplification_planned=True),
        make_performer_headers(ctx["performer"]["id"]))
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_AMPLIFICATION_PROHIBITED)

    permit = read_permit(permit_id)
    assert permit["season_minutes_used"] == 0
    assert permit["amplification_endorsed"] is False


def test_amplified_session_on_a_permit_without_an_endorsement_is_refused(api):
    """PRD §3.6: "If `amplification_planned` is true, the pitch must have
    `amplification_allowed` true — a quiet pitch refuses amplified acts outright
    with `ERR_AMPLIFICATION_PROHIBITED` — and the permit must have
    `amplification_endorsed` true, since a permit issued without an endorsement
    may not amplify anywhere, refused with `ERR_AMPLIFICATION_NOT_ENDORSED`."
    PRD §3.6: "The pitch gate is evaluated before the permit gate."

    Design: Corner/errors/corner_error_amplification_not_endorsed_on_permit
    """
    ctx = setup_district_pitch_and_active_permit(
        pitch_overrides=dict(code="RP-01", tier="STANDARD", noise_cap_db=82,
                             amplification_allowed=True))
    permit_id, pitch_id = ctx["permit"]["id"], ctx["pitch"]["id"]
    assert ctx["pitch"]["amplification_allowed"] is True
    assert ctx["permit"]["amplification_endorsed"] is False

    resp = api.create_session_booking(
        create_session_booking_payload(permit_id, pitch_id,
                                       "2026-08-25T10:00:00Z",
                                       "2026-08-25T11:00:00Z",
                                       permit_version(permit_id),
                                       amplification_planned=True),
        make_performer_headers(ctx["performer"]["id"]))
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_AMPLIFICATION_NOT_ENDORSED)
    assert read_permit(permit_id)["season_minutes_used"] == 0


def test_booking_on_a_closed_pitch_is_refused(api):
    """PRD §3.6: "The pitch must have `availability_status` `OPEN`, otherwise
    `ERR_PITCH_CLOSED`."
    PRD §3.9: "That activation sets `availability_status` to `CLOSED` on every
    pitch in scope — the single named pitch when `pitch_id` was supplied,
    otherwise every pitch in the order's district."

    Design: Corner/errors/corner_error_pitch_closed_blocks_new_bookings
    """
    ctx = setup_district_pitch_and_active_permit(
        pitch_overrides=dict(code="RP-01", tier="STANDARD", noise_cap_db=82,
                             amplification_allowed=True))
    draft_and_activate_closure(ctx["zone"]["id"], "2026-08-05T08:00:00Z",
                               "2026-08-05T12:00:00Z", reason="EMERGENCY")
    assert read_pitch(ctx["pitch"]["id"])["availability_status"] == "CLOSED"

    resp = api.create_session_booking(
        create_session_booking_payload(ctx["permit"]["id"], ctx["pitch"]["id"],
                                       "2026-08-25T10:00:00Z",
                                       "2026-08-25T11:00:00Z",
                                       permit_version(ctx["permit"]["id"])),
        make_performer_headers(ctx["performer"]["id"]))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_PITCH_CLOSED)

    assert read_permit(ctx["permit"]["id"])["season_minutes_used"] == 0
    _, meta = validate_paginated(api.list_session_bookings(
        make_officer_headers(), params={"pitch_id": ctx["pitch"]["id"]}))
    assert meta["total_count"] == 0


def test_season_minute_cap_admits_exact_equality_and_refuses_one_more(api):
    """PRD §3.6: "Finally the season allowance is tested: a permit may consume
    1800 minutes — thirty hours — of pitch time per season, and the booking is
    admitted only when `season_minutes_used` plus the new `duration_minutes` is
    less than or equal to that cap. Landing exactly on the cap is admitted;
    exceeding it is refused with `ERR_SEASON_MINUTE_CAP_EXCEEDED`."

    Design: Corner/errors/corner_season_minute_cap_admits_exact_equality_and_rejects_one_more
    """
    ctx = setup_district_pitch_and_active_permit(
        zone_overrides=dict(name="Longhaul Quay", code="LQ",
                            base_noise_cap_db=78, evening_start_minute=1080,
                            quiet_hours_start_minute=0, quiet_hours_end_minute=0,
                            weekend_noise_bonus_db=0, evening_penalty_db=0,
                            max_concurrent_closures=1),
        pitch_overrides=dict(code="LQ-01", tier="STANDARD", noise_cap_db=82,
                             amplification_allowed=False,
                             max_session_minutes=240, daily_session_cap=12))
    permit_id, pitch_id = ctx["permit"]["id"], ctx["pitch"]["id"]
    performer_id = ctx["performer"]["id"]

    book_series(permit_id, pitch_id, performer_id,
                [(f"2026-08-0{day}T10:00:00Z", f"2026-08-0{day}T14:00:00Z")
                 for day in range(3, 10)])
    assert read_permit(permit_id)["season_minutes_used"] == 1680

    exact = api.create_session_booking(
        create_session_booking_payload(permit_id, pitch_id,
                                       "2026-08-10T10:00:00Z",
                                       "2026-08-10T12:00:00Z",
                                       permit_version(permit_id)),
        make_performer_headers(performer_id))
    booking = validate_success(exact, 201)
    assert booking["duration_minutes"] == 120
    assert read_permit(permit_id)["season_minutes_used"] == 1800, \
        "landing exactly on the 1800-minute cap is admitted"

    over = api.create_session_booking(
        create_session_booking_payload(permit_id, pitch_id,
                                       "2026-08-11T10:00:00Z",
                                       "2026-08-11T10:15:00Z",
                                       permit_version(permit_id)),
        make_performer_headers(performer_id))
    assert over.status_code == 409, f"Expected 409, got {over.status_code}"
    validate_error(over, ApiErrorId.ERR_SEASON_MINUTE_CAP_EXCEEDED)
    assert read_permit(permit_id)["season_minutes_used"] == 1800

    _, meta = validate_paginated(api.list_session_bookings(
        make_officer_headers(), params={"permit_id": permit_id}))
    assert meta["total_count"] == 8


def test_ownership_check_fires_before_the_body_is_checked_for_well_formedness(api):
    """PRD §2.6: "5. On any endpoint whose authorised roles include `Performer`,
    a caller acting as `Performer` owns the target resource, otherwise
    `ERR_NOT_RESOURCE_OWNER`."
    PRD §2.6: "6. The request body is well formed, otherwise
    `ERR_INVALID_REQUEST`. Applies to every POST endpoint."
    PRD §2.1: "A performer who targets a resource that resolves to a different
    performer is rejected with `ERR_NOT_RESOURCE_OWNER` and HTTP 403."

    Design: Corner/validations/corner_ownership_check_rejects_before_malformed_body
    """
    ctx = setup_district_pitch_and_active_permit(
        pitch_overrides=dict(code="RP-01", tier="STANDARD", noise_cap_db=82,
                             amplification_allowed=True))
    intruder = create_performer(legal_name="Eli Marsh", stage_name="Eli M",
                                email="eli@example.org",
                                act_type="ACOUSTIC_MUSIC")

    resp = api.create_session_booking(
        {"permit_id": ctx["permit"]["id"], "pitch_id": ctx["pitch"]["id"],
         "start_at": "2026-08-25T10:00:00Z",
         "expected_permit_version": permit_version(ctx["permit"]["id"])},
        make_performer_headers(intruder["id"]))
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert read_permit(ctx["permit"]["id"])["season_minutes_used"] == 0
