"""Snake draft: order, roster cap, pick void cascades and revert cycle.

Covers: non_linear_state_machine (player drafted->void revert), transitive_cascade
(void depth-3), compensating_invariant (void conserves roster occupancy), corner
calculations (snake round-2 reversal, not-your-pick), corner validations
(roster full), corner errors (not-last-pick), consistency_model (immediate),
corner endpoints (filtered players by team).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_league_admin_headers,
)
from test_helpers import fixtures as fx


ADMIN = make_league_admin_headers("admin-1")


# ─────────────────────────────────────────────────────────────────────────────
# non_linear_state_machine / player_drafted_then_void_revert_cycle  (A)
# ─────────────────────────────────────────────────────────────────────────────

def test_pick_then_void_reverts_player_to_evaluated(api):
    """PRD §3.4: "Voiding moves the `DraftPick` to the terminal `VOIDED` status
    and reverts the player from `DRAFTED` back to `EVALUATED`: the player's
    `team_id` is cleared to null and the team's `roster_count` falls by 1, with
    the player's `version` incrementing on the revert."

    Design: Difficulty/non_linear_state_machine/player_drafted_then_void_revert_cycle
    """
    d = fx.setup_league_in_draft(num_teams=2, num_players=2)
    tx = d["teams"][0]
    p1 = d["players"][0]
    pick = fx.draft_pick(d["league"]["id"], tx["id"], p1["id"],
                         d["league_version"])

    voided = validate_success(api.void_draft_pick(pick["id"], ADMIN))
    assert voided["status"] == "VOIDED", voided["status"]

    player = validate_success(api.get_player(p1["id"], ADMIN))
    assert player["status"] == "EVALUATED", player["status"]
    assert player["team_id"] is None, player["team_id"]
    team = validate_success(api.get_team(tx["id"], ADMIN))
    assert team["roster_count"] == 0, team["roster_count"]


def test_void_pick_is_terminal_voided(api):
    """PRD §3.4: "Voiding moves the `DraftPick` to the terminal `VOIDED` status
    and reverts the player from `DRAFTED` back to `EVALUATED`."

    Design: Difficulty/non_linear_state_machine/player_drafted_then_void_revert_cycle
    """
    d = fx.setup_league_in_draft(num_teams=2, num_players=2)
    pick = fx.draft_pick(d["league"]["id"], d["teams"][0]["id"],
                         d["players"][0]["id"], d["league_version"])
    voided = validate_success(api.void_draft_pick(pick["id"], ADMIN))
    assert voided["status"] == "VOIDED", voided["status"]
    fetched = validate_success(api.get_draft_pick(pick["id"], ADMIN))
    assert fetched["status"] == "VOIDED", fetched["status"]


# ─────────────────────────────────────────────────────────────────────────────
# transitive_cascade / void_pick_cascades_pick_to_player_to_team_depth3  (A)
# ─────────────────────────────────────────────────────────────────────────────

def test_void_cascades_pick_player_team_depth3(api):
    """PRD §3.4: "Voiding moves the `DraftPick` to the terminal `VOIDED` status
    and reverts the player from `DRAFTED` back to `EVALUATED`: the player's
    `team_id` is cleared to null and the team's `roster_count` falls by 1, with
    the player's `version` incrementing on the revert."

    Link 1 (pick VOIDED) -> link 2 (player EVALUATED, team_id null) -> link 3
    (team.roster_count -1).

    Design: Difficulty/transitive_cascade/void_pick_cascades_pick_to_player_to_team_depth3
    """
    d = fx.setup_league_in_draft(num_teams=2, num_players=2)
    tx = d["teams"][0]
    p1 = d["players"][0]
    pick = fx.draft_pick(d["league"]["id"], tx["id"], p1["id"],
                         d["league_version"])
    team_after_pick = validate_success(api.get_team(tx["id"], ADMIN))
    assert team_after_pick["roster_count"] == 1, team_after_pick["roster_count"]

    voided = validate_success(api.void_draft_pick(pick["id"], ADMIN))
    assert voided["status"] == "VOIDED", voided["status"]               # link 1
    player = validate_success(api.get_player(p1["id"], ADMIN))
    assert player["status"] == "EVALUATED", player["status"]            # link 2
    assert player["team_id"] is None, player["team_id"]                 # link 2
    team = validate_success(api.get_team(tx["id"], ADMIN))
    assert team["roster_count"] == 0, team["roster_count"]              # link 3


def test_void_decrements_team_roster_count(api):
    """PRD §3.4: "the player's `team_id` is cleared to null and the team's
    `roster_count` falls by 1".

    Design: Difficulty/transitive_cascade/void_pick_cascades_pick_to_player_to_team_depth3
    """
    d = fx.setup_league_in_draft(num_teams=2, num_players=2)
    tx = d["teams"][0]
    pick = fx.draft_pick(d["league"]["id"], tx["id"], d["players"][0]["id"],
                         d["league_version"])
    validate_success(api.void_draft_pick(pick["id"], ADMIN))
    team = validate_success(api.get_team(tx["id"], ADMIN))
    assert team["roster_count"] == 0, team["roster_count"]


# ─────────────────────────────────────────────────────────────────────────────
# compensating_invariant / draft_void_conserves_roster_occupancy  (A)
# ─────────────────────────────────────────────────────────────────────────────

def test_void_conserves_roster_occupancy(api):
    """PRD §3.4: "the team's `roster_count` rises by 1" (on pick); §3.4:
    "the team's `roster_count` falls by 1" (on void). A pick (+1) paired with its
    void (-1) returns the per-division roster occupancy to its pre-pick value.

    Design: Difficulty/compensating_invariant/draft_void_conserves_roster_occupancy
    """
    d = fx.setup_league_in_draft(num_teams=2, num_players=2)
    tx, ty = d["teams"][0], d["teams"][1]
    pick = fx.draft_pick(d["league"]["id"], tx["id"], d["players"][0]["id"],
                         d["league_version"])
    validate_success(api.void_draft_pick(pick["id"], ADMIN))

    team_x = validate_success(api.get_team(tx["id"], ADMIN))
    team_y = validate_success(api.get_team(ty["id"], ADMIN))
    assert team_x["roster_count"] == 0, team_x["roster_count"]
    assert team_y["roster_count"] == 0, team_y["roster_count"]
    assert team_x["roster_count"] + team_y["roster_count"] == 0


def test_void_conserves_occupancy_matches_player_count(api):
    """PRD §2.5: "a team's `roster_count` (players assigned to that team in
    status `DRAFTED` or `ROSTERED`)". After a pick and its void, no player has a
    team_id and the summed roster_count is 0 — the conserved quantity is intact.

    Design: Difficulty/compensating_invariant/draft_void_conserves_roster_occupancy
    """
    d = fx.setup_league_in_draft(num_teams=2, num_players=2)
    tx = d["teams"][0]
    pick = fx.draft_pick(d["league"]["id"], tx["id"], d["players"][0]["id"],
                         d["league_version"])
    validate_success(api.void_draft_pick(pick["id"], ADMIN))

    resp = api.list_players(ADMIN, params={"division_id": d["division"]["id"]})
    data = validate_success(resp)
    drafted = [p for p in data if p.get("team_id")]
    assert drafted == [], drafted


# ─────────────────────────────────────────────────────────────────────────────
# corner: calculations / snake_draft_round2_reverses_order  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_snake_round2_reverses_order(api):
    """PRD §3.4: "When `draft_snake` is true and the round number is even, the
    expected `draft_slot` is the team count minus the zero-based position (the
    round runs in reverse); otherwise the expected `draft_slot` is the zero-based
    position plus 1 (the round runs forward)."
    PRD §3.4: "The `overall_number` assigned to the pick is the prior pick count
    plus 1, and `round_number` is the round computed above."

    Two teams, snake on: picks 1,2 are round 1 (slot1, slot2); pick 3 is round 2
    and must be team Y (slot 2) again.

    Design: Corner/calculations/snake_draft_round2_reverses_order
    """
    d = fx.setup_league_in_draft(num_teams=2, num_players=3)
    tx, ty = d["teams"][0], d["teams"][1]
    p1, p2, p3 = d["players"]

    fx.draft_pick(d["league"]["id"], tx["id"], p1["id"],
                  d["league_version"])
    v1 = fx.league_version(d["league"]["id"])
    fx.draft_pick(d["league"]["id"], ty["id"], p2["id"], v1)
    v2 = fx.league_version(d["league"]["id"])

    pick3 = fx.draft_pick(d["league"]["id"], ty["id"], p3["id"], v2)
    assert pick3["round_number"] == 2, pick3["round_number"]
    assert pick3["overall_number"] == 3, pick3["overall_number"]
    assert pick3["team_id"] == ty["id"], pick3["team_id"]


def test_snake_round2_wrong_slot_rejected(api):
    """PRD §3.4: "The submitting team's `draft_slot` must equal that expected
    slot; if it does not, the pick is rejected with `ERR_NOT_YOUR_PICK`."

    In round 2 (reversed) the on-the-clock team is slot 2 (Y); team X (slot 1)
    submitting pick 3 is rejected.

    Design: Corner/calculations/snake_draft_round2_reverses_order
    """
    d = fx.setup_league_in_draft(num_teams=2, num_players=3)
    tx, ty = d["teams"][0], d["teams"][1]
    p1, p2, p3 = d["players"]
    fx.draft_pick(d["league"]["id"], tx["id"], p1["id"], d["league_version"])
    v1 = fx.league_version(d["league"]["id"])
    fx.draft_pick(d["league"]["id"], ty["id"], p2["id"], v1)
    v2 = fx.league_version(d["league"]["id"])

    resp = api.create_draft_pick({
        "league_id": d["league"]["id"], "team_id": tx["id"],
        "player_id": p3["id"], "expected_league_version": v2,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_YOUR_PICK.value)


# ─────────────────────────────────────────────────────────────────────────────
# corner: calculations / not_your_pick_when_wrong_slot  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_first_pick_wrong_slot_rejected(api):
    """PRD §3.4: "The submitting team's `draft_slot` must equal that expected
    slot; if it does not, the pick is rejected with `ERR_NOT_YOUR_PICK`."

    The first overall pick belongs to slot 1; team Y (slot 2) submitting it is
    rejected.

    Design: Corner/calculations/not_your_pick_when_wrong_slot
    """
    d = fx.setup_league_in_draft(num_teams=2, num_players=1)
    ty = d["teams"][1]
    resp = api.create_draft_pick({
        "league_id": d["league"]["id"], "team_id": ty["id"],
        "player_id": d["players"][0]["id"],
        "expected_league_version": d["league_version"],
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_YOUR_PICK.value)


# ─────────────────────────────────────────────────────────────────────────────
# corner: validations / roster_full_rejected_on_draft  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_roster_full_rejected_on_second_pick(api):
    """PRD §3.4: "The draft may not push a team past its division's `roster_cap`;
    a pick that would make `roster_count` reach or exceed the cap is rejected with
    `ERR_ROSTER_FULL`."

    roster_cap=1, one team alone: it drafts P1 (roster_count 1) then attempting
    P2 is rejected.

    Design: Corner/validations/roster_full_rejected_on_draft
    """
    d = fx.setup_league_in_draft(num_teams=1, roster_cap=1, num_players=2)
    tx = d["teams"][0]
    p1, p2 = d["players"]
    fx.draft_pick(d["league"]["id"], tx["id"], p1["id"], d["league_version"])
    v1 = fx.league_version(d["league"]["id"])

    resp = api.create_draft_pick({
        "league_id": d["league"]["id"], "team_id": tx["id"],
        "player_id": p2["id"], "expected_league_version": v1,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ROSTER_FULL.value)


# ─────────────────────────────────────────────────────────────────────────────
# corner: errors / not_last_pick_void_rejected  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_void_not_last_pick_rejected(api):
    """PRD §3.4: "Only the most recent `ACTIVE` pick — the one with the highest
    `overall_number` — may be voided; an attempt to void any earlier pick is
    rejected with `ERR_NOT_LAST_PICK`."

    Design: Corner/errors/not_last_pick_void_rejected
    """
    d = fx.setup_league_in_draft(num_teams=2, num_players=2)
    tx, ty = d["teams"][0], d["teams"][1]
    p1, p2 = d["players"]
    pick1 = fx.draft_pick(d["league"]["id"], tx["id"], p1["id"],
                          d["league_version"])
    v1 = fx.league_version(d["league"]["id"])
    fx.draft_pick(d["league"]["id"], ty["id"], p2["id"], v1)

    resp = api.void_draft_pick(pick1["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_LAST_PICK.value)


# ─────────────────────────────────────────────────────────────────────────────
# corner: consistency_model / draft_pick_immediate_consistency  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_draft_pick_side_effects_immediately_visible(api):
    """PRD §3.4: "Recording a pick drives the selected player from `EVALUATED` to
    `DRAFTED`: the player's `team_id` is set to the drafting team, the team's
    `roster_count` rises by 1, and the player's `version` increments."

    Design: Corner/consistency_model/draft_pick_immediate_consistency
    """
    d = fx.setup_league_in_draft(num_teams=2, num_players=1)
    tx = d["teams"][0]
    p1 = d["players"][0]
    fx.draft_pick(d["league"]["id"], tx["id"], p1["id"], d["league_version"])

    player = validate_success(api.get_player(p1["id"], ADMIN))
    assert player["status"] == "DRAFTED", player["status"]
    assert player["team_id"] == tx["id"], player["team_id"]


# ─────────────────────────────────────────────────────────────────────────────
# corner: endpoints / filtered_players_by_team  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_filtered_players_by_team(api):
    """PRD §3.4: "the player's `team_id` is set to the drafting team".
    PRD §4: "GET `/players` List players (filterable)". Filtering by team_id
    returns only players drafted onto that team.

    Design: Corner/endpoints/filtered_players_by_team
    """
    d = fx.setup_league_in_draft(num_teams=2, num_players=2)
    tx = d["teams"][0]
    p1 = d["players"][0]
    fx.draft_pick(d["league"]["id"], tx["id"], p1["id"], d["league_version"])

    resp = api.list_players(ADMIN, params={"team_id": tx["id"]})
    data = validate_success(resp)
    assert len(data) == 1, data
    assert data[0]["id"] == p1["id"], data[0]
    assert data[0]["team_id"] == tx["id"], data[0]
