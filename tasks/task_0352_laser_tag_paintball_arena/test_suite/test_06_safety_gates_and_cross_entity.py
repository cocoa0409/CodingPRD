"""Safety gates and cross-entity state dependencies: referee gate at check-in,
record-result requires a COMPLETED booking, state-vs-safety precedence, and the
minor-waiver guardian rule at sign time.

Queue A (Difficulty) — cross_entity_state_dependency,
priority_pair_validation_conflict.
Queue B (Corner) — state_machines (minor waiver sign).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_waiver_profile_payload, create_league_match_payload,
    TEST_USERS,
    create_arena, create_field, setup_arena_and_field, create_held_booking,
    create_confirmed_booking, create_league, open_league,
)

AM = TEST_USERS["arena_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
FM = TEST_USERS["field_marshal_headers"]
LD = TEST_USERS["league_director_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — cross_entity_state_dependency: check-in requires referee (two tests)
# ─────────────────────────────────────────────────────────────────────────────
def test_paintball_checkin_without_referee_returns_referee_required(api):
    """PRD §3.6: "The referee gate is also enforced at check-in: if the booking's
    `referee_required` is true, an `ASSIGNED` referee assignment must already exist for
    the booking, or the check-in is rejected with `ERR_REFEREE_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/booking_checkin_requires_referee_assignment_present
    """
    arena = create_arena(clock="2026-06-15T09:30:00Z")
    field = create_field(arena["id"], name="PB13", game_mode="PAINTBALL", capacity_max=6)
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:30:00Z", window_end="2026-06-15T11:00:00Z",
    )
    res = api.check_in_booking(booking["id"], {"checked_in_count": 4}, FM)
    validate_error(res, "ERR_REFEREE_REQUIRED", expected_status=422)


def test_paintball_booking_marks_referee_required_true(api):
    """PRD §3.6: "a booking requires a referee when its `party_size` is at least 12, or
    when minors are present, or when the field's `game_mode` is `PAINTBALL`. Any one of
    these three conditions is sufficient."

    Design: Difficulty/cross_entity_state_dependency/booking_checkin_requires_referee_assignment_present
    """
    arena = create_arena(clock="2026-06-15T09:30:00Z")
    field = create_field(arena["id"], name="PB13b", game_mode="PAINTBALL", capacity_max=6)
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:30:00Z", window_end="2026-06-15T11:00:00Z",
    )
    assert booking["referee_required"] is True, \
        "a PAINTBALL booking must have referee_required true"


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — cross_entity_state_dependency: record-result needs COMPLETED (two)
# ─────────────────────────────────────────────────────────────────────────────
def _setup_scheduled_match_on_confirmed_booking():
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    league = create_league(arena["id"], total_rounds=1, name="L14")
    open_league(league["id"])
    from test_helpers import api_client
    match = validate_success(
        api_client.create_league_match(
            create_league_match_payload(arena["id"], league["id"], booking["id"],
                                        home_team="Red", away_team="Blue"), LD), 201
    )
    return arena, field, booking, league, match


# NOTE: a test asserting record-result on a SCHEDULED match whose linked booking
# is not COMPLETED returns ERR_BOOKING_INVALID_STATE was removed. PRD §3.9 states
# the rule ("recording requires ... the linked booking to be `COMPLETED`") but
# never names the error_id for this branch: it names only ERR_MATCH_INVALID_STATE
# for "a match transition from a disallowed state". A PRD-faithful implementer can
# reasonably surface this match-recording precondition failure as
# ERR_MATCH_INVALID_STATE (the match operation's own state-class error), so the
# specific error_id is not uniquely derivable from PRD prose.

def test_scheduled_match_round_index_stamps_current_round(api):
    """PRD §3.9: "The match is created `SCHEDULED` and its `round_index` is stamped with
    the league's `current_round` at creation."

    Design: Difficulty/cross_entity_state_dependency/record_result_requires_booking_completed
    """
    arena, field, booking, league, match = _setup_scheduled_match_on_confirmed_booking()
    assert match["status"] == "SCHEDULED"
    assert match["round_index"] == 1, \
        f"match round_index must stamp current_round 1, got {match['round_index']}"


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — priority_pair_validation_conflict: state beats safety (two tests)
# ─────────────────────────────────────────────────────────────────────────────
def test_held_booking_checkin_returns_state_error_over_minor_waiver(api):
    """PRD §5: "then target-state legality for the requested transition (the
    `*_INVALID_STATE` family, 409); then the optimistic-concurrency version check
    (`ERR_STALE_FIELD_VERSION` / `ERR_STALE_LEAGUE_VERSION`, 412); then the business
    safety, referential, temporal, constraint, and fiscal rules."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_minor_waiver_on_checkin
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:30:00Z")
    # booking left HELD (never confirmed)
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:30:00Z", window_end="2026-06-15T11:00:00Z",
    )
    # a DRAFT minor waiver attached (would trip the minor-waiver safety gate if reached)
    validate_success(api.create_waiver_profile(create_waiver_profile_payload(
        arena["id"], booking["id"], participant_name="Kid",
        date_of_birth="2016-01-01T00:00:00Z", guardian_name="Parent"), FD), 201)
    res = api.check_in_booking(booking["id"], {"checked_in_count": 4}, FM)
    validate_error(res, "ERR_BOOKING_INVALID_STATE", expected_status=409)


def test_minor_waiver_gate_fires_when_state_is_valid(api):
    """PRD §3.6: "The minor-waiver safety gate is enforced at check-in: every waiver
    profile on the booking whose status is not `VOID` and whose `is_minor` is true must
    be `SIGNED` and carry a `guardian_name`. ... A check-in that violates this is
    rejected with `ERR_MINOR_WAIVER_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_minor_waiver_on_checkin
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:30:00Z")
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:30:00Z", window_end="2026-06-15T11:00:00Z",
    )
    # unsigned DRAFT minor waiver -> at a valid (CONFIRMED) state the safety gate fires
    validate_success(api.create_waiver_profile(create_waiver_profile_payload(
        arena["id"], booking["id"], participant_name="Kid",
        date_of_birth="2016-01-01T00:00:00Z", guardian_name="Parent"), FD), 201)
    res = api.check_in_booking(booking["id"], {"checked_in_count": 4}, FM)
    validate_error(res, "ERR_MINOR_WAIVER_REQUIRED", expected_status=422)


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — minor waiver sign without guardian
# ─────────────────────────────────────────────────────────────────────────────
def test_sign_minor_waiver_without_guardian_returns_minor_waiver_required(api):
    """PRD §3.6: "if the profile is for a minor, it must carry a `guardian_name`, and an
    attempt to sign a minor's waiver that has no guardian on file is rejected with
    `ERR_MINOR_WAIVER_REQUIRED`."

    Design: Corner/state_machines/sign_minor_waiver_without_guardian_returns_minor_waiver_required
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    waiver = validate_success(api.create_waiver_profile(create_waiver_profile_payload(
        arena["id"], booking["id"], participant_name="Minor",
        date_of_birth="2015-01-01T00:00:00Z"), FD), 201)  # no guardian_name
    res = api.sign_waiver(waiver["id"], FD)
    validate_error(res, "ERR_MINOR_WAIVER_REQUIRED", expected_status=422)
