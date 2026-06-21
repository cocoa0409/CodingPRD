"""League lifecycle, seeding, validation precedence, RBAC and CRUD basics.

Covers: dual_variant_calc (win_pct seeding), priority_pair_validation_conflict
(state beats age, forbidden beats field-slot), corner entities (defaults, not
found, required field, fk scope, pagination), corner state_machines (terminal
lockdown, evaluation precondition), corner rbac (forbidden, unauthenticated),
cross_cutting (version increment).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_league_admin_headers,
    make_parent_guardian_headers,
)
from test_helpers import fixtures as fx


ADMIN = make_league_admin_headers("admin-1")


# ─────────────────────────────────────────────────────────────────────────────
# dual_variant_calc / seeding_variant_diverges...on_team_domain  (A)
# ─────────────────────────────────────────────────────────────────────────────

def _three_team_season(draft_snake):
    s = fx.setup_league_in_season(num_teams=3, num_fields=1,
                                  draft_snake=draft_snake, max_games_per_day=10)
    return s


def _play(s, home, away, hr, ar, day):
    game = fx.schedule_game(
        s["league"]["id"], s["division"]["id"], home, away, s["field"]["id"],
        f"2026-05-0{day}T17:00:00Z", f"2026-05-0{day}T19:00:00Z")
    a = fx.propose_assignment(game["id"], s["referee"]["id"])
    fx.confirm_assignment(a["id"], s["referee"]["user_id"])
    fx.start_game(game["id"])
    fx.finalize_game(game["id"], hr, ar)


def test_win_pct_seeding_assigns_seeds(api):
    """PRD §3.8: "When `draft_snake` is true (the default competitive bracket),
    teams are ranked primarily by win percentage descending; ties are then broken
    by `run_differential` descending, and any remaining ties by `created_at`
    ascending (never by `id`). ... Seeds run 1 upward within each division."

    X (1-0, 1.000), Y (3-1, .750), Z (0-3) -> seeds X=1, Y=2, Z=3.

    Design: Difficulty/dual_variant_calc/seeding_variant_diverges_from_draft_picks_on_team_domain
    """
    s = _three_team_season(draft_snake=True)
    tx, ty, tz = s["teams"][0], s["teams"][1], s["teams"][2]
    # X 5-2 Y  -> X 1-0, Y 0-1
    _play(s, tx["id"], ty["id"], 5, 2, 1)
    # Y 7-1 Z  -> Y 1-1, Z 0-1
    _play(s, ty["id"], tz["id"], 7, 1, 2)
    # Y 6-3 Z  -> Y 2-1, Z 0-2
    _play(s, ty["id"], tz["id"], 6, 3, 3)
    # Y 8-0 Z  -> Y 3-1, Z 0-3
    _play(s, ty["id"], tz["id"], 8, 0, 4)

    fx.advance(s["league"]["id"], "PLAYOFFS")
    sx = validate_success(api.get_team(tx["id"], ADMIN))
    sy = validate_success(api.get_team(ty["id"], ADMIN))
    sz = validate_success(api.get_team(tz["id"], ADMIN))
    assert sx["wins"] == 1 and sx["losses"] == 0, sx
    assert sy["wins"] == 3 and sy["losses"] == 1, sy
    assert sz["wins"] == 0 and sz["losses"] == 3, sz
    assert sx["seed"] == 1, sx["seed"]
    assert sy["seed"] == 2, sy["seed"]
    assert sz["seed"] == 3, sz["seed"]


def test_seeding_standings_and_run_differential(api):
    """PRD §2.5: "a team's `wins`, `losses`, and `run_differential` (derived from
    that team's `FINAL` games)." §3.5: "each team's `run_differential` absorbs its
    own runs minus its opponent's runs."

    X run_diff +3, Y +14, Z -17 from the played games.

    Design: Difficulty/dual_variant_calc/seeding_variant_diverges_from_draft_picks_on_team_domain
    """
    s = _three_team_season(draft_snake=True)
    tx, ty, tz = s["teams"][0], s["teams"][1], s["teams"][2]
    _play(s, tx["id"], ty["id"], 5, 2, 1)
    _play(s, ty["id"], tz["id"], 7, 1, 2)
    _play(s, ty["id"], tz["id"], 6, 3, 3)
    _play(s, ty["id"], tz["id"], 8, 0, 4)
    fx.advance(s["league"]["id"], "PLAYOFFS")

    sx = validate_success(api.get_team(tx["id"], ADMIN))
    sy = validate_success(api.get_team(ty["id"], ADMIN))
    sz = validate_success(api.get_team(tz["id"], ADMIN))
    assert sx["run_differential"] == 3, sx["run_differential"]
    assert sy["run_differential"] == 14, sy["run_differential"]
    assert sz["run_differential"] == -17, sz["run_differential"]


# ─────────────────────────────────────────────────────────────────────────────
# priority_pair_validation_conflict / state_beats_age_out_of_range...  (A)
# ─────────────────────────────────────────────────────────────────────────────

def test_verify_age_on_already_verified_player_invalid_state(api):
    """PRD §2.7: "State legality is fifth: if the target resource or its owning
    league is not in a state that permits the operation, the request yields
    `ERR_INVALID_STATE` (HTTP 409)." §3.3: "a `LeagueAdmin` verifies their age,
    moving a `REGISTERED` player to `AGE_VERIFIED`."

    Verifying a player that is already AGE_VERIFIED (wrong from-state) yields
    ERR_INVALID_STATE — the state gate (priority 5) is reached before the
    age-eligibility check (priority 7).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_age_out_of_range_on_verify_age
    """
    league = fx.create_league(draft_snake=True)
    fx.set_clock("2026-06-01T00:00:00Z")
    division = fx.create_division(league["id"])
    family = fx.create_family(league["id"], volunteer_deposit_cents=0)
    fx.advance(league["id"], "REGISTRATION")
    p = fx.register_player(league["id"], family["id"], division["id"],
                          full_name="P1", birth_date="2015-01-15",
                          birth_certificate_ref="bc1")
    fx.verify_age(p["id"])  # now AGE_VERIFIED

    resp = api.verify_age(p["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_reverify_rejected_leaves_player_age_verified(api):
    """PRD §2.7: "State legality is fifth: if the target resource or its owning
    league is not in a state that permits the operation, the request yields
    `ERR_INVALID_STATE` (HTTP 409)." §3.3: "a `LeagueAdmin` verifies their age,
    moving a `REGISTERED` player to `AGE_VERIFIED`."

    A rejected re-verify (player already AGE_VERIFIED) leaves the player's status
    AGE_VERIFIED — the state gate fires and no further transition occurs.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_age_out_of_range_on_verify_age
    """
    league = fx.create_league(draft_snake=True)
    fx.set_clock("2026-06-01T00:00:00Z")
    division = fx.create_division(league["id"])
    family = fx.create_family(league["id"], volunteer_deposit_cents=0)
    fx.advance(league["id"], "REGISTRATION")
    p = fx.register_player(league["id"], family["id"], division["id"],
                          full_name="P1", birth_date="2015-01-15",
                          birth_certificate_ref="bc1")
    fx.verify_age(p["id"])

    resp = api.verify_age(p["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    player = validate_success(api.get_player(p["id"], ADMIN))
    assert player["status"] == "AGE_VERIFIED", player["status"]


# ─────────────────────────────────────────────────────────────────────────────
# priority_pair_validation_conflict / forbidden_beats_field_slot_conflict...  (A)
# ─────────────────────────────────────────────────────────────────────────────

def test_forbidden_beats_field_slot_conflict(api):
    """PRD §2.7: "Authorization is second: a role not permitted for the operation
    (or acting outside its ownership) yields `ERR_FORBIDDEN`." §2.7: "the
    field-slot check (`ERR_FIELD_SLOT_CONFLICT`)" comes among the later domain
    checks.

    A Coach (not permitted to create games) submitting a game that ALSO overlaps
    an existing field slot receives ERR_FORBIDDEN, because auth precedes the
    temporal check.

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_field_slot_conflict_on_game_create
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=1)
    fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")

    coach_headers = fx.make_coach_headers("cx")
    resp = api.create_game({
        "league_id": s["league"]["id"], "division_id": s["division"]["id"],
        "home_team_id": s["teams"][0]["id"], "away_team_id": s["teams"][1]["id"],
        "field_id": s["field"]["id"],
        "start_iso": "2026-05-01T18:00:00Z", "end_iso": "2026-05-01T20:00:00Z",
    }, coach_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_forbidden_coach_game_create_makes_no_game(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation ... the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    A Coach's forbidden game-create (which also overlaps a field slot) is rejected
    and creates no second game: only the original game remains on the field.

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_field_slot_conflict_on_game_create
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=1)
    fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")

    coach_headers = fx.make_coach_headers("cx")
    resp = api.create_game({
        "league_id": s["league"]["id"], "division_id": s["division"]["id"],
        "home_team_id": s["teams"][0]["id"], "away_team_id": s["teams"][1]["id"],
        "field_id": s["field"]["id"],
        "start_iso": "2026-05-01T18:00:00Z", "end_iso": "2026-05-01T20:00:00Z",
    }, coach_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    games = validate_success(
        api.list_games(ADMIN, params={"field_id": s["field"]["id"]}))
    assert len(games) == 1, games


# ─────────────────────────────────────────────────────────────────────────────
# corner: entities / create_league_returns_defaults  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_create_league_returns_defaults(api):
    """PRD §3.1: "A freshly created league is in `SETUP`, has `version` 1, a
    `total_registered_players` of 0, and a `draft_round_index` of 0."

    Design: Corner/entities/create_league_returns_defaults
    """
    data = validate_success(api.create_league({
        "name": "Spring", "season_year": 2026, "age_cutoff_date": "2026-08-31",
        "registration_open_iso": "2026-01-01T00:00:00Z",
        "registration_close_iso": "2026-12-31T00:00:00Z",
    }, ADMIN), 201)
    assert data["status"] == "SETUP", data["status"]
    assert data["version"] == 1, data["version"]
    assert data["total_registered_players"] == 0, data["total_registered_players"]
    assert data["draft_round_index"] == 0, data["draft_round_index"]


# ─────────────────────────────────────────────────────────────────────────────
# corner: entities / get_player_not_found  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_get_player_not_found(api):
    """PRD §2.6: "the system validates existence left to right and rejects the
    first identifier that does not resolve to an existing in-scope resource with
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_player_not_found
    """
    fx.create_league()
    resp = api.get_player(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ─────────────────────────────────────────────────────────────────────────────
# corner: entities / create_player_missing_required_field  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_create_player_missing_birth_date(api):
    """PRD §2.7: "The structural request-body check (`ERR_INVALID_REQUEST`, HTTP
    400) covers malformed bodies, missing required fields, bad enum members, and
    numeric values outside their allowed ranges." §3.2: "A `Player` is created
    with its `league_id`, the registering `family_id`, the requested
    `division_id`, a `full_name`, a `birth_date` as `'YYYY-MM-DD'`".

    Omitting the required birth_date -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_player_missing_required_field
    """
    league = fx.create_league()
    fx.set_clock("2026-06-01T00:00:00Z")
    division = fx.create_division(league["id"])
    family = fx.create_family(league["id"], volunteer_deposit_cents=0)
    fx.advance(league["id"], "REGISTRATION")

    resp = api.create_player({
        "league_id": league["id"], "family_id": family["id"],
        "division_id": division["id"], "full_name": "NoDOB",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─────────────────────────────────────────────────────────────────────────────
# corner: entities / create_player_bad_division_scope  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_create_player_division_in_other_league_fk_mismatch(api):
    """PRD §2.6: "a player's requested division must belong to the same league as
    the player ... A foreign key that points at an entity in the wrong league or
    division is rejected with `ERR_FK_SCOPE_MISMATCH` (HTTP 422)."

    Design: Corner/entities/create_player_bad_division_scope
    """
    l1 = fx.create_league(name="L1")
    fx.set_clock("2026-06-01T00:00:00Z")
    l2 = fx.create_league(name="L2")
    d2 = fx.create_division(l2["id"])
    fx.create_division(l1["id"])
    f1 = fx.create_family(l1["id"], volunteer_deposit_cents=0)
    fx.advance(l1["id"], "REGISTRATION")

    resp = api.create_player({
        "league_id": l1["id"], "family_id": f1["id"], "division_id": d2["id"],
        "full_name": "Kid", "birth_date": "2015-01-15",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FK_SCOPE_MISMATCH.value)


# ─────────────────────────────────────────────────────────────────────────────
# corner: entities / list_divisions_pagination_envelope  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_list_divisions_pagination_envelope(api):
    """PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`." §2.2: "The `response_type` is either "object"
    for a single resource or "array" for a list of resources."

    Design: Corner/entities/list_divisions_pagination_envelope
    """
    league = fx.create_league()
    fx.create_division(league["id"], name="Majors")
    fx.create_division(league["id"], name="Minors", min_league_age=7,
                       max_league_age=9)

    resp = api.list_divisions(ADMIN, params={"league_id": league["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is False, meta


# ─────────────────────────────────────────────────────────────────────────────
# corner: validations / duplicate_family_email_rejected  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_duplicate_family_email_rejected(api):
    """PRD §3.2: "The `guardian_email` must be unique within the league; a second
    family attempting to reuse an email already present in that league is rejected
    with `ERR_DUPLICATE_FAMILY_EMAIL`."

    Design: Corner/validations/duplicate_family_email_rejected
    """
    league = fx.create_league()
    fx.create_family(league["id"], guardian_email="fam@x.com",
                     guardian_name="Fam", volunteer_deposit_cents=0)
    resp = api.create_family({
        "league_id": league["id"], "guardian_email": "fam@x.com",
        "guardian_name": "Dup", "volunteer_deposit_cents": 0,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_FAMILY_EMAIL.value)


# ─────────────────────────────────────────────────────────────────────────────
# corner: validations / registration_window_closed_blocks_player_create  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_registration_window_closed_blocks_player_create(api):
    """PRD §3.2: "Player registration ... is only legal while the league is in
    `REGISTRATION` and the current clock instant falls within the half-open window
    from `registration_open_iso` up to but not including `registration_close_iso`.
    A registration mutation attempted outside that window is rejected with
    `ERR_REGISTRATION_WINDOW_CLOSED`."

    Design: Corner/validations/registration_window_closed_blocks_player_create
    """
    league = fx.create_league()
    division = fx.create_division(league["id"])
    family = fx.create_family(league["id"], volunteer_deposit_cents=0)
    fx.advance(league["id"], "REGISTRATION")
    fx.set_clock("2027-01-01T00:00:00Z")  # after close 2026-12-31

    resp = api.create_player({
        "league_id": league["id"], "family_id": family["id"],
        "division_id": division["id"], "full_name": "Late",
        "birth_date": "2015-01-15",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_WINDOW_CLOSED.value)


# ─────────────────────────────────────────────────────────────────────────────
# corner: state_machines / terminal_withdrawn_player_cannot_verify  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_withdrawn_player_cannot_verify_age(api):
    """PRD §3.2: "A player who is no longer participating may be withdrawn by a
    `LeagueAdmin`, moving them to the terminal `WITHDRAWN` status". §2.7: "State
    legality is fifth: if the target resource ... is not in a state that permits
    the operation, the request yields `ERR_INVALID_STATE`".

    Design: Corner/state_machines/terminal_withdrawn_player_cannot_verify
    """
    league = fx.create_league()
    fx.set_clock("2026-06-01T00:00:00Z")
    division = fx.create_division(league["id"])
    family = fx.create_family(league["id"], volunteer_deposit_cents=0)
    fx.advance(league["id"], "REGISTRATION")
    p = fx.register_player(league["id"], family["id"], division["id"],
                          full_name="P1", birth_date="2015-01-15",
                          birth_certificate_ref="bc1")
    validate_success(api.withdraw_player(p["id"], ADMIN))

    resp = api.verify_age(p["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─────────────────────────────────────────────────────────────────────────────
# corner: rbac / parent_guardian_cannot_create_division  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_parent_guardian_cannot_create_division(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation ... the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)." §4: division creation is LeagueAdmin-only.

    Design: Corner/rbac/parent_guardian_cannot_create_division
    """
    league = fx.create_league()
    family = fx.create_family(league["id"], volunteer_deposit_cents=0)

    resp = api.create_division({
        "league_id": league["id"], "name": "Majors", "min_league_age": 9,
        "max_league_age": 12, "roster_cap": 12,
    }, make_parent_guardian_headers(family["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ─────────────────────────────────────────────────────────────────────────────
# corner: rbac / unauthenticated_missing_headers  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_unauthenticated_missing_headers(api):
    """PRD §2.1: "A request missing either header is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unauthenticated_missing_headers
    """
    league = fx.create_league()
    resp = api.raw_get(f"/leagues/{league['id']}", {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─────────────────────────────────────────────────────────────────────────────
# corner: cross_cutting / version_increments_on_every_mutation  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_league_version_increments_on_advance(api):
    """PRD §2.4: "The `version` starts at 1 when the resource is created and
    increases by exactly 1 on every mutation". §3.1: "Each advance increments the
    league's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
    """
    league = fx.create_league()
    assert league["version"] == 1, league["version"]
    fx.create_division(league["id"])
    out = validate_success(api.advance_league(
        league["id"], {"target": "REGISTRATION"}, ADMIN))
    assert out["version"] == 2, out["version"]
