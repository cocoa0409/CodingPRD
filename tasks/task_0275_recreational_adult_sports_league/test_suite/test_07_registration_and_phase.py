"""Team registration, confirmation gating, season-phase gating, and the capacity /
roster / fee cross-entity dependencies.

Covers cross_entity_state_dependency (score-submit requires IN_PLAY; confirm requires
capacity room), priority_pair_validation_conflict (season-phase beats capacity), and
the confirm/roster/fee corner validations.
"""
from test_helpers import (
    validate_success, validate_error,
    make_league_admin_headers, make_team_captain_headers, make_referee_headers,
    ApiErrorId,
)
import test_helpers.fixtures as fx
import test_helpers.factories as F

ADMIN = make_league_admin_headers()


def test_team_register_on_draft_season_rejected_by_phase(api):
    """PRD §2.8: "A team may be registered into a division only while its season's
    `registration_status` is `OPEN`."
    PRD §2.7: "then the season-phase gate (`ERR_SEASON_PHASE`); then the target
    resource's state validity ... then division capacity (`ERR_CAPACITY_EXCEEDED`)".

    The season is DRAFT (never opened), so the season-phase check fires before any
    capacity evaluation.

    Design: Difficulty/priority_pair_validation_conflict/season_phase_beats_capacity_on_team_register
    """
    season = fx.create_season()
    division = fx.create_division(season["id"], team_capacity=2, registration_fee_cents=0)
    cap = fx.create_player()
    dv = fx.get_division_version(division["id"])
    payload = F.create_team_payload(cap["id"], dv, name="Latecomers")
    resp = api.create_team(division["id"], payload, make_team_captain_headers(cap["id"]))
    validate_error(resp, ApiErrorId.ERR_SEASON_PHASE.value)


def test_team_register_on_closed_season_rejected_by_phase(api):
    """PRD §2.8: "A team may be registered into a division only while its season's
    `registration_status` is `OPEN`."

    A CLOSED season (already advanced past OPEN) likewise blocks registration with
    `ERR_SEASON_PHASE`, before any capacity evaluation.

    Design: Difficulty/priority_pair_validation_conflict/season_phase_beats_capacity_on_team_register
    """
    season = fx.create_season()
    division = fx.create_division(season["id"], team_capacity=2, registration_fee_cents=0)
    cap1 = fx.create_player()
    latecomer = fx.create_player()
    fx.set_clock("2026-08-15T00:00:00Z")
    fx.open_season(season["id"])
    t1 = fx.register_team(division["id"], cap1["id"])
    fx.confirm_team(t1["id"])
    fx.advance_to(season["id"], "CLOSED")  # season no longer OPEN
    dv = fx.get_division_version(division["id"])
    payload = F.create_team_payload(latecomer["id"], dv, name="TooLate")
    resp = api.create_team(division["id"], payload, make_team_captain_headers(latecomer["id"]))
    validate_error(resp, ApiErrorId.ERR_SEASON_PHASE.value)


def test_confirm_blocked_at_capacity_after_waitlist_settlement(api):
    """PRD §3.2: "A confirm attempt that would push past `team_capacity` is rejected
    with `ERR_CAPACITY_EXCEEDED`".

    A team WAITLISTED by the closing settlement cannot be confirmed while the division
    is already at `team_capacity`.

    Design: Difficulty/cross_entity_state_dependency/team_confirm_requires_division_capacity_room
    """
    season = fx.create_season()
    division = fx.create_division(season["id"], team_capacity=2, registration_fee_cents=0)
    cap1 = fx.create_player()
    cap2 = fx.create_player()
    cap3 = fx.create_player()
    fx.set_clock("2026-08-15T00:00:00Z")
    fx.open_season(season["id"])
    t1 = fx.register_team(division["id"], cap1["id"])
    t2 = fx.register_team(division["id"], cap2["id"])
    t3 = fx.register_team(division["id"], cap3["id"])
    fx.confirm_team(t1["id"])
    fx.confirm_team(t2["id"])
    fx.advance_to(season["id"], "CLOSED")  # t3 -> WAITLISTED; division full at capacity 2
    resp = api.confirm_team(t3["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)


def test_confirm_blocked_when_division_at_capacity(api):
    """PRD §3.2: "A confirm attempt that would push past `team_capacity` is rejected
    with `ERR_CAPACITY_EXCEEDED`".

    Design: Difficulty/cross_entity_state_dependency/team_confirm_requires_division_capacity_room
    """
    season = fx.create_season()
    division = fx.create_division(season["id"], team_capacity=2, registration_fee_cents=0)
    cap1 = fx.create_player()
    cap2 = fx.create_player()
    cap3 = fx.create_player()
    fx.set_clock("2026-08-15T00:00:00Z")
    fx.open_season(season["id"])
    t1 = fx.register_team(division["id"], cap1["id"])
    t2 = fx.register_team(division["id"], cap2["id"])
    t3 = fx.register_team(division["id"], cap3["id"])
    fx.confirm_team(t1["id"])
    fx.confirm_team(t2["id"])  # division now full (capacity 2)
    resp = api.confirm_team(t3["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)


def test_score_submit_succeeds_once_in_play(api):
    """PRD §3.7: "A successful submission records `home_score` and `away_score`,
    advances `score_status` from `PENDING` to `SUBMITTED`, and increments the game's
    `version` by one".

    Design: Difficulty/cross_entity_state_dependency/score_submit_requires_season_in_play_phase
    """
    s = fx.setup_in_play_game_pending()
    gv = validate_success(api.get_game(s["game"]["id"], ADMIN))["version"]
    submitted = validate_success(
        api.submit_score(s["game"]["id"], F.submit_score_payload(2, 1, gv),
                         make_referee_headers(s["referee"]["id"]))
    )
    assert submitted["score_status"] == "SUBMITTED"


def test_confirm_below_min_roster_rejected(api):
    """PRD §3.2: "a confirm attempt with a roster below `min_roster_size` (or one that
    introduced a duplicate active player) is rejected with `ERR_ROSTER_RULE`".

    Design: Corner/validations/confirm_below_min_roster_returns_roster_rule
    """
    base = fx.setup_open_division()
    division = fx.create_division(base["season"]["id"], min_roster_size=3, max_roster_size=8,
                                  team_capacity=4, registration_fee_cents=0)
    cap = fx.create_player()
    team = fx.register_team(division["id"], cap["id"])  # roster_size 1 (captain only)
    resp = api.confirm_team(team["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ROSTER_RULE.value)


def test_roster_add_over_max_rejected(api):
    """PRD §3.3: "an add that would carry the team's `ACTIVE` count beyond
    `max_roster_size` is rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Corner/validations/roster_add_over_max_returns_capacity_exceeded
    """
    base = fx.setup_open_division()
    division = fx.create_division(base["season"]["id"], min_roster_size=1, max_roster_size=1,
                                  team_capacity=4, registration_fee_cents=0)
    cap = fx.create_player()
    extra = fx.create_player()
    team = fx.register_team(division["id"], cap["id"])  # already at roster_size 1 = max
    resp = api.add_roster(team["id"], F.roster_add_payload(extra["id"]),
                          make_team_captain_headers(cap["id"]))
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)


def test_duplicate_roster_player_rejected(api):
    """PRD §3.3: "A player already holding an `ACTIVE` entry on the same team cannot be
    added a second time — the duplicate is rejected with `ERR_ROSTER_RULE`".

    Design: Corner/validations/duplicate_roster_player_returns_roster_rule
    """
    base = fx.setup_open_division()
    cap = fx.create_player()
    team = fx.register_team(base["division"]["id"], cap["id"])  # captain is ACTIVE on roster
    resp = api.add_roster(team["id"], F.roster_add_payload(cap["id"]),
                          make_team_captain_headers(cap["id"]))
    validate_error(resp, ApiErrorId.ERR_ROSTER_RULE.value)


def test_confirm_without_fee_in_fee_division_rejected(api):
    """PRD §3.2: "and a confirm of a fee-bearing division's team with no captured fee
    of the right amount is rejected with `ERR_FEE_REQUIRED`."

    Design: Corner/validations/confirm_without_fee_returns_fee_required
    """
    base = fx.setup_open_division()
    division = fx.create_division(base["season"]["id"], registration_fee_cents=4000)
    cap = fx.create_player()
    team = fx.register_team(division["id"], cap["id"])  # no fee captured
    resp = api.confirm_team(team["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_FEE_REQUIRED.value)


def test_schedule_with_underfilled_division_rejected(api):
    """PRD §3.1: "When the blocker is specifically a schedule that is not yet complete
    enough to advance — a division that lacks its teams or games, or games that still
    lack confirmed scores when moving toward `SCHEDULED` or `PLAYOFFS` — the request is
    rejected with `ERR_SCHEDULE_INCOMPLETE` instead."

    Design: Corner/validations/publish_schedule_with_underfilled_division_returns_schedule_incomplete
    """
    base = fx.setup_open_division()
    division = base["division"]
    cap = fx.create_player()
    team = fx.register_team(division["id"], cap["id"])
    fx.confirm_team(team["id"])  # only ONE confirmed team in the division
    fx.advance_to(base["season"]["id"], "CLOSED")
    v = fx.get_season_version(base["season"]["id"])
    resp = api.transition_season(base["season"]["id"], F.season_transition_payload("SCHEDULED", v), ADMIN)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_INCOMPLETE.value)
