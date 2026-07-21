"""Scheduling a match onto a station/window: ordering, cross-entity state, overlap.

Queue A: schedule_referential_beats_temporal, schedule_requires_both_checked_in,
station_overlap_within_buffer.
Queue B: schedule_outside_venue_hours.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    schedule_match_payload, TEST_USERS, make_player_headers,
)
from test_helpers import fixtures as F

DIRECTOR = TEST_USERS["director_headers"]
REFEREE = TEST_USERS["referee_headers"]
PUBLIC = TEST_USERS["public_headers"]


def _two_player_bracket_ready(open_minute=0, close_minute=1440):
    """2-player SINGLE_ELIM stopped at BRACKET_READY (before start)."""
    venue = F.create_venue(open_minute, close_minute)
    station = F.create_station(venue["id"])
    p1 = F.create_player(rating=1500, display_name="P1")
    p2 = F.create_player(rating=1200, display_name="P2")
    t = F.create_tournament(venue["id"], format="SINGLE_ELIM", max_participants=4,
                            prize_pool_cents=0, paid_places=1)
    F.open_registration(t["id"])
    r1 = F.register(t["id"], p1["id"])
    r2 = F.register(t["id"], p2["id"])
    F.close_registration(t["id"])
    F.check_in(r1["id"], p1["id"])
    F.check_in(r2["id"], p2["id"])
    F.generate_bracket(t["id"])
    return {"v_id": venue["id"], "st_id": station["id"], "t_id": t["id"],
            "p1": p1["id"], "p2": p2["id"], "r1": r1["id"], "r2": r2["id"]}


# --------------------------------------------------------------------------
# Queue A — referential (station wrong venue) beats temporal (outside hours)
# --------------------------------------------------------------------------
def test_schedule_station_wrong_venue_error_wins(api):
    """PRD §3.4: "the station's venue_id must equal the tournament's venue_id,
    otherwise ERR_STATION_WRONG_VENUE (HTTP 409); the window must lie within the
    venue's operating hours ... otherwise ERR_OUTSIDE_VENUE_HOURS (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/schedule_referential_beats_temporal
    """
    ctx = F.build_two_player_single_elim(open_minute=600, close_minute=1200)
    v2 = F.create_venue(0, 1440, name="V2")
    st2 = F.create_station(v2["id"], label="T-V2")
    # station from V2 (wrong venue) AND window 09:00 before V1 opens at 10:00
    resp = api.schedule_match(ctx["m_id"], schedule_match_payload(
        st2["id"], "2026-07-01T09:00:00Z", "2026-07-01T09:30:00Z"), REFEREE)
    validate_error(resp, ApiErrorId.ERR_STATION_WRONG_VENUE.value, 409)


def test_schedule_wrong_venue_leaves_match_pending(api):
    """PRD §3.4: "the station's venue_id must equal the tournament's venue_id,
    otherwise ERR_STATION_WRONG_VENUE (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/schedule_referential_beats_temporal
    """
    ctx = F.build_two_player_single_elim(open_minute=600, close_minute=1200)
    v2 = F.create_venue(0, 1440, name="V2")
    st2 = F.create_station(v2["id"], label="T-V2")
    api.schedule_match(ctx["m_id"], schedule_match_payload(
        st2["id"], "2026-07-01T09:00:00Z", "2026-07-01T09:30:00Z"), REFEREE)
    assert F.get_match(ctx["m_id"])["status"] == "PENDING"


# --------------------------------------------------------------------------
# Queue A — schedule requires both competitors CHECKED_IN
# --------------------------------------------------------------------------
def test_schedule_rejected_when_competitor_withdrew(api):
    """PRD §3.4: "both competitors must currently be CHECKED_IN, otherwise the
    schedule is rejected with ERR_COMPETITOR_NOT_CHECKED_IN (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_both_checked_in
    """
    ctx = _two_player_bracket_ready()
    # withdrawal is allowed while not yet IN_PROGRESS
    F.get_success_data(api.withdraw(ctx["r2"], make_player_headers(ctx["p2"])))
    F.start_tournament(ctx["t_id"])
    m_id = F.list_tournament_matches(ctx["t_id"])[0]["id"]
    resp = api.schedule_match(m_id, schedule_match_payload(
        ctx["st_id"], "2026-07-01T10:00:00Z", "2026-07-01T11:00:00Z"), REFEREE)
    validate_error(resp, ApiErrorId.ERR_COMPETITOR_NOT_CHECKED_IN.value, 409)


def test_withdrawn_competitor_state_after_failed_schedule(api):
    """PRD §3.2: "withdrawal moves the registration to WITHDRAWN". PRD §3.4: the
    schedule is rejected with ERR_COMPETITOR_NOT_CHECKED_IN so the match is
    unchanged.

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_both_checked_in
    """
    ctx = _two_player_bracket_ready()
    F.get_success_data(api.withdraw(ctx["r2"], make_player_headers(ctx["p2"])))
    F.start_tournament(ctx["t_id"])
    m_id = F.list_tournament_matches(ctx["t_id"])[0]["id"]
    api.schedule_match(m_id, schedule_match_payload(
        ctx["st_id"], "2026-07-01T10:00:00Z", "2026-07-01T11:00:00Z"), REFEREE)
    assert F.get_match(m_id)["status"] == "PENDING"
    assert F.get_registration(ctx["r2"])["status"] == "WITHDRAWN"


# --------------------------------------------------------------------------
# Queue A — station overlap within the 15-minute turnover buffer
# --------------------------------------------------------------------------
def test_station_overlap_within_buffer_rejected(api):
    """PRD §3.4: "The buffer means the gap between two matches must be at least 15
    minutes; two matches exactly 15 minutes apart do not conflict, while
    back-to-back matches touching at a shared instant do conflict".

    Design: Difficulty/resource_temporal_overlap/station_overlap_within_buffer
    """
    ctx = F.build_round_robin_3p(tiebreak_method="SEED")
    F.schedule(ctx["m_ab"], ctx["st_id"], start="2026-07-01T10:00:00Z",
               end="2026-07-01T11:00:00Z")
    # m_ac starts 11:10 — only a 10-minute gap after m_ab ends (< 15 min buffer)
    resp = api.schedule_match(ctx["m_ac"], schedule_match_payload(
        ctx["st_id"], "2026-07-01T11:10:00Z", "2026-07-01T12:10:00Z"), REFEREE)
    validate_error(resp, ApiErrorId.ERR_STATION_OVERLAP.value, 409)


def test_station_overlap_leaves_first_scheduled_second_pending(api):
    """PRD §3.4: "a conflict exists if there is any other match on that station in
    SCHEDULED, REPORTED, CONFIRMED, or DISPUTED status ... whose interval, once
    expanded by the buffer, still overlaps the proposal".

    Design: Difficulty/resource_temporal_overlap/station_overlap_within_buffer
    """
    ctx = F.build_round_robin_3p(tiebreak_method="SEED")
    F.schedule(ctx["m_ab"], ctx["st_id"], start="2026-07-01T10:00:00Z",
               end="2026-07-01T11:00:00Z")
    api.schedule_match(ctx["m_ac"], schedule_match_payload(
        ctx["st_id"], "2026-07-01T11:10:00Z", "2026-07-01T12:10:00Z"), REFEREE)
    m_ab = F.get_match(ctx["m_ab"])
    assert m_ab["status"] == "SCHEDULED"
    assert F.get_match(ctx["m_ac"])["status"] == "PENDING"


# --------------------------------------------------------------------------
# Queue B — schedule outside venue operating hours
# --------------------------------------------------------------------------
def test_schedule_outside_venue_hours_rejected(api):
    """PRD §3.4: "the window must lie within the venue's operating hours with
    scheduled_end strictly after scheduled_start, otherwise ERR_OUTSIDE_VENUE_HOURS
    (HTTP 422)".

    Design: Corner/errors/schedule_outside_venue_hours
    """
    ctx = F.build_two_player_single_elim(open_minute=600, close_minute=1200)
    # correct-venue station, but 09:00 window is before the venue opens (10:00)
    resp = api.schedule_match(ctx["m_id"], schedule_match_payload(
        ctx["st_id"], "2026-07-01T09:00:00Z", "2026-07-01T09:30:00Z"), REFEREE)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_VENUE_HOURS.value, 422)
    assert F.get_match(ctx["m_id"])["status"] == "PENDING"
