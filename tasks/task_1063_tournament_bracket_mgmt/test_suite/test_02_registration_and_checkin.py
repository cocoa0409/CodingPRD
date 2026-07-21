"""Registration capacity/duplicates and the check-in gates.

Queue A: boundary_precision_check (registration capacity, check-in deadline),
priority_pair_validation_conflict (check-in state vs temporal).
Queue B: duplicate registration, idempotent check-in, insufficient participants.
"""
from datetime import datetime

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_registration_payload, TEST_USERS, make_player_headers,
)
from test_helpers import fixtures as F

DIRECTOR = TEST_USERS["director_headers"]
PUBLIC = TEST_USERS["public_headers"]


def _iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _open_tournament_with_registration(check_in_deadline="2026-08-01T00:00:00Z",
                                       max_participants=4):
    venue = F.create_venue()
    p1 = F.create_player()
    t = F.create_tournament(venue["id"], format="SINGLE_ELIM",
                            max_participants=max_participants, prize_pool_cents=0,
                            paid_places=1, check_in_deadline=check_in_deadline)
    F.open_registration(t["id"])
    r1 = F.register(t["id"], p1["id"])
    return t, p1, r1


# --------------------------------------------------------------------------
# Queue A — registration capacity boundary (max_participants)
# --------------------------------------------------------------------------
def test_registration_at_capacity_is_accepted(api):
    """PRD §3.2: "at most max_participants registrations may be in the
    REGISTERED/CHECKED_IN set, so the entry that would be the (max_participants +
    1)-th is rejected with ERR_TOURNAMENT_FULL (HTTP 409)".

    Design: Difficulty/boundary_precision_check/registration_capacity_boundary
    """
    venue = F.create_venue()
    p1 = F.create_player()
    p2 = F.create_player()
    t = F.create_tournament(venue["id"], format="SINGLE_ELIM", max_participants=2,
                            prize_pool_cents=0, paid_places=1)
    F.open_registration(t["id"])
    F.register(t["id"], p1["id"])
    resp = api.create_registration(create_registration_payload(t["id"], p2["id"]),
                                   make_player_headers(p2["id"]))
    validate_success(resp, 201)  # the 2nd (== max_participants) is accepted
    assert F.get_tournament(t["id"])["registered_count"] == 2


def test_registration_over_capacity_rejected(api):
    """PRD §3.2: "the entry that would be the (max_participants + 1)-th is
    rejected with ERR_TOURNAMENT_FULL (HTTP 409)".

    Design: Difficulty/boundary_precision_check/registration_capacity_boundary
    """
    venue = F.create_venue()
    p1 = F.create_player()
    p2 = F.create_player()
    p3 = F.create_player()
    t = F.create_tournament(venue["id"], format="SINGLE_ELIM", max_participants=2,
                            prize_pool_cents=0, paid_places=1)
    F.open_registration(t["id"])
    F.register(t["id"], p1["id"])
    F.register(t["id"], p2["id"])
    resp = api.create_registration(create_registration_payload(t["id"], p3["id"]),
                                   make_player_headers(p3["id"]))
    validate_error(resp, ApiErrorId.ERR_TOURNAMENT_FULL.value, 409)


# --------------------------------------------------------------------------
# Queue A — check-in deadline inclusive boundary
# --------------------------------------------------------------------------
def test_checkin_exactly_at_deadline_accepted(api):
    """PRD §3.3: "the logical now must be at or before the tournament's
    check_in_deadline — the boundary is inclusive, so now exactly equal to the
    deadline is accepted while now strictly after it is rejected with
    ERR_CHECKIN_CLOSED (HTTP 409)".

    Design: Difficulty/boundary_precision_check/checkin_deadline_inclusive_boundary
    """
    deadline = "2026-07-10T00:00:00Z"
    t, p1, r1 = _open_tournament_with_registration(check_in_deadline=deadline)
    F.close_registration(t["id"])
    get_success_data(api.set_clock({"to_iso8601": deadline}, DIRECTOR))
    resp = api.check_in(r1["id"], make_player_headers(p1["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "CHECKED_IN", data["status"]


def test_checkin_at_deadline_increments_count(api):
    """PRD §3.3: "On success the system sets checked_in_at to the logical now and
    increments checked_in_count."

    Design: Difficulty/boundary_precision_check/checkin_deadline_inclusive_boundary
    """
    deadline = "2026-07-10T00:00:00Z"
    t, p1, r1 = _open_tournament_with_registration(check_in_deadline=deadline)
    F.close_registration(t["id"])
    get_success_data(api.set_clock({"to_iso8601": deadline}, DIRECTOR))
    data = validate_success(api.check_in(r1["id"], make_player_headers(p1["id"])), 200)
    assert _iso(data["checked_in_at"]) == _iso(deadline), data["checked_in_at"]
    assert F.get_tournament(t["id"])["checked_in_count"] == 1


# --------------------------------------------------------------------------
# Queue A — priority pair: check-in state (5) beats temporal (6)
# --------------------------------------------------------------------------
def test_checkin_state_error_wins_over_temporal(api):
    """PRD §3.3: "the tournament must be in REGISTRATION_CLOSED, otherwise the
    check-in is rejected with ERR_TOURNAMENT_NOT_IN_CHECKIN (HTTP 409); the
    logical now must be at or before the tournament's check_in_deadline ...
    otherwise ... ERR_CHECKIN_CLOSED (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/checkin_state_beats_temporal
    """
    # Still REGISTRATION_OPEN (not CLOSED) AND clock past the deadline: both the
    # state gate and the temporal gate would fail; the earlier state gate wins.
    t, p1, r1 = _open_tournament_with_registration(check_in_deadline="2026-07-05T00:00:00Z")
    get_success_data(api.set_clock({"to_iso8601": "2026-07-06T00:00:00Z"}, DIRECTOR))
    resp = api.check_in(r1["id"], make_player_headers(p1["id"]))
    validate_error(resp, ApiErrorId.ERR_TOURNAMENT_NOT_IN_CHECKIN.value, 409)


def test_checkin_state_conflict_leaves_registration_unchanged(api):
    """PRD §3.3: "the tournament must be in REGISTRATION_CLOSED, otherwise the
    check-in is rejected with ERR_TOURNAMENT_NOT_IN_CHECKIN (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/checkin_state_beats_temporal
    """
    t, p1, r1 = _open_tournament_with_registration(check_in_deadline="2026-07-05T00:00:00Z")
    get_success_data(api.set_clock({"to_iso8601": "2026-07-06T00:00:00Z"}, DIRECTOR))
    api.check_in(r1["id"], make_player_headers(p1["id"]))
    assert F.get_registration(r1["id"])["status"] == "REGISTERED"


# --------------------------------------------------------------------------
# Queue B — duplicate registration, idempotent check-in, insufficient participants
# --------------------------------------------------------------------------
def test_duplicate_registration_rejected(api):
    """PRD §3.2: "a player may hold at most one non-terminal registration per
    tournament, so a second concurrent entry is rejected with
    ERR_DUPLICATE_REGISTRATION (HTTP 409)".

    Design: Corner/validations/duplicate_registration_rejected
    """
    venue = F.create_venue()
    p1 = F.create_player()
    t = F.create_tournament(venue["id"], format="SINGLE_ELIM", max_participants=8,
                            prize_pool_cents=0, paid_places=1)
    F.open_registration(t["id"])
    F.register(t["id"], p1["id"])
    resp = api.create_registration(create_registration_payload(t["id"], p1["id"]),
                                   make_player_headers(p1["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REGISTRATION.value, 409)


def test_second_checkin_rejected_invalid_state(api):
    """PRD §3.3: "the registration must currently be REGISTERED." PRD §2.11:
    "then the target's state precondition (ERR_INVALID_STATE and its more
    specific siblings)".

    Design: Corner/state_machines/checkin_already_checked_in_invalid_state
    """
    deadline = "2026-08-01T00:00:00Z"
    t, p1, r1 = _open_tournament_with_registration(check_in_deadline=deadline)
    F.close_registration(t["id"])
    F.check_in(r1["id"], p1["id"])
    resp = api.check_in(r1["id"], make_player_headers(p1["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert F.get_tournament(t["id"])["checked_in_count"] == 1


def test_generate_bracket_insufficient_participants(api):
    """PRD §3.3: "a generation attempt with fewer than two checked-in
    participants ... is rejected with ERR_INSUFFICIENT_PARTICIPANTS (HTTP 409)".

    Design: Corner/validations/generate_bracket_insufficient_participants
    """
    deadline = "2026-08-01T00:00:00Z"
    t, p1, r1 = _open_tournament_with_registration(check_in_deadline=deadline)
    F.close_registration(t["id"])
    F.check_in(r1["id"], p1["id"])
    resp = api.generate_bracket(t["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PARTICIPANTS.value, 409)
