"""Broadcast stream assignments: match-state gate and channel closed-interval overlap.

Queue A: stream_requires_match_scheduled_state, stream_overlap_touching_allowed.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_stream_assignment_payload, TEST_USERS,
)
from test_helpers import fixtures as F

REFEREE = TEST_USERS["referee_headers"]
PUBLIC = TEST_USERS["public_headers"]


def test_stream_on_pending_match_rejected(api):
    """PRD §3.7: "The target match must be in a broadcastable state — SCHEDULED,
    REPORTED, CONFIRMED, or DISPUTED — and never PENDING or VOIDED, otherwise the
    assignment is rejected with ERR_MATCH_NOT_SCHEDULABLE_STREAM (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/stream_requires_match_scheduled_state
    """
    ctx = F.build_two_player_single_elim()  # final is PENDING (not scheduled)
    channel = F.create_stream_channel(platform="TWITCH")
    resp = api.create_stream_assignment(create_stream_assignment_payload(
        ctx["m_id"], channel["id"], "2026-07-01T10:00:00Z", "2026-07-01T11:00:00Z"), REFEREE)
    validate_error(resp, ApiErrorId.ERR_MATCH_NOT_SCHEDULABLE_STREAM.value, 409)


def test_stream_on_pending_match_creates_nothing(api):
    """PRD §3.7: a stream assignment to a PENDING match is rejected with
    ERR_MATCH_NOT_SCHEDULABLE_STREAM (HTTP 409), so no assignment is created.

    Design: Difficulty/cross_entity_state_dependency/stream_requires_match_scheduled_state
    """
    ctx = F.build_two_player_single_elim()
    channel = F.create_stream_channel(platform="TWITCH")
    api.create_stream_assignment(create_stream_assignment_payload(
        ctx["m_id"], channel["id"], "2026-07-01T10:00:00Z", "2026-07-01T11:00:00Z"), REFEREE)
    existing = get_success_data(api.list_stream_assignments(
        PUBLIC, params={"match_id": ctx["m_id"], "limit": 100}))
    assert existing == [], existing
    assert F.get_match(ctx["m_id"])["status"] == "PENDING"


def test_stream_touching_endpoints_allowed(api):
    """PRD §3.7: "Because the comparisons are strict, touching endpoints are
    allowed: an assignment that ends at exactly the instant another begins does
    not conflict."

    Design: Difficulty/resource_temporal_overlap/stream_overlap_touching_allowed
    """
    ctx = F.build_round_robin_3p(tiebreak_method="SEED")
    F.schedule(ctx["m_ab"], ctx["st_id"], window="a")
    F.schedule(ctx["m_ac"], ctx["st_id"], window="b")
    channel = F.create_stream_channel(platform="YOUTUBE")
    a1 = validate_success(api.create_stream_assignment(create_stream_assignment_payload(
        ctx["m_ab"], channel["id"], "2026-07-01T10:00:00Z", "2026-07-01T11:00:00Z"), REFEREE), 201)
    a2 = validate_success(api.create_stream_assignment(create_stream_assignment_payload(
        ctx["m_ac"], channel["id"], "2026-07-01T11:00:00Z", "2026-07-01T12:00:00Z"), REFEREE), 201)
    assert a1["status"] == "SCHEDULED"
    assert a2["status"] == "SCHEDULED"  # touching at 11:00 accepted


def test_stream_interior_overlap_rejected(api):
    """PRD §3.7: "a conflict exists if there is any other SCHEDULED assignment on
    that channel ... such that the proposed start is strictly before that
    assignment's end and that assignment's start is strictly before the proposed
    end", otherwise ERR_CHANNEL_OVERLAP (HTTP 409).

    Design: Difficulty/resource_temporal_overlap/stream_overlap_touching_allowed
    """
    ctx = F.build_round_robin_3p(tiebreak_method="SEED")
    F.schedule(ctx["m_ab"], ctx["st_id"], window="a")
    F.schedule(ctx["m_ac"], ctx["st_id"], window="b")
    channel = F.create_stream_channel(platform="YOUTUBE")
    validate_success(api.create_stream_assignment(create_stream_assignment_payload(
        ctx["m_ab"], channel["id"], "2026-07-01T10:00:00Z", "2026-07-01T11:00:00Z"), REFEREE), 201)
    # 10:30-11:30 overlaps the interior of the 10:00-11:00 assignment
    resp = api.create_stream_assignment(create_stream_assignment_payload(
        ctx["m_ac"], channel["id"], "2026-07-01T10:30:00Z", "2026-07-01T11:30:00Z"), REFEREE)
    validate_error(resp, ApiErrorId.ERR_CHANNEL_OVERLAP.value, 409)
