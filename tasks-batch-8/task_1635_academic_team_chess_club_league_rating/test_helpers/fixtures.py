"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so each test
starts against an empty database). Setup calls use get_success_data() so a
failed precondition raises a clear "Setup step failed" error.

Identity threading (PRD §2.1): ClubCoach / Proctor calls that are
ownership-gated always go through make_club_coach_headers(coach["id"]) /
make_proctor_headers(coach["id"]) with the real Coach.id — never the shared
TEST_USERS fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_club_payload,
    create_coach_payload,
    create_dispute_payload,
    create_ledger_adjustment_payload,
    create_meet_payload,
    create_membership_payload,
    create_pairing_payload,
    create_player_payload,
    create_proctor_assignment_payload,
    create_season_payload,
    create_section_payload,
    create_tournament_payload,
)
from .test_users import TEST_USERS, make_club_coach_headers, make_proctor_headers

ADMIN = TEST_USERS["federation_admin_headers"]
TREASURER = TEST_USERS["treasurer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ─── Tier 1: Single-entity creation / state progression ──

def create_season(**overrides) -> dict:
    """Create a season (lands in REGISTRATION)."""
    res = api_client.create_season(create_season_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_active_season(**overrides) -> dict:
    """Create a season and activate it (REGISTRATION -> ACTIVE)."""
    season = create_season(**overrides)
    return get_success_data(api_client.activate_season(season["id"], ADMIN))


def create_club(season_id, **overrides) -> dict:
    return get_success_data(api_client.create_club(create_club_payload(season_id, **overrides), ADMIN))


def create_coach(club_id, **overrides) -> dict:
    return get_success_data(api_client.create_coach(create_coach_payload(club_id, **overrides), ADMIN))


def create_player(club_id, **overrides) -> dict:
    """Create a player as the administrator (no ownership scoping)."""
    return get_success_data(api_client.create_player(create_player_payload(club_id, **overrides), ADMIN))


def create_membership(player_id, season_id) -> dict:
    """Create a membership (lands INVOICED; fee computed from the logical clock)."""
    return get_success_data(
        api_client.create_membership(create_membership_payload(player_id, season_id), ADMIN)
    )


def waive_membership(membership_id) -> dict:
    return get_success_data(api_client.waive_membership(membership_id, ADMIN))


def create_waived_membership(player_id, season_id) -> dict:
    """Membership created and waived (WAIVED satisfies the paid-or-waived gate)."""
    membership = create_membership(player_id, season_id)
    return waive_membership(membership["id"])


def pay_membership(membership_id, headers=None) -> dict:
    return get_success_data(api_client.pay_membership(membership_id, headers or TREASURER))


def fund_club(club_id, amount_cents, poster_user_id="treasurer-1", memo="funding") -> dict:
    """Post a manual ADJUSTMENT to a club's ledger (re-reads the club version for OCC)."""
    club = get_success_data(api_client.get_club(club_id, ADMIN))
    headers = dict(TREASURER)
    headers["X-User-ID"] = poster_user_id
    res = api_client.post_ledger_entry(
        club_id,
        create_ledger_adjustment_payload(amount_cents, club["version"], memo=memo),
        headers,
    )
    return get_success_data(res)


def get_club(club_id) -> dict:
    return get_success_data(api_client.get_club(club_id, ADMIN))


def club_balance(club_id) -> int:
    return get_club(club_id)["account_balance_cents"]


# ─── Tier 2: League skeleton (season + clubs + coaches + players) ──

def setup_one_club(season_overrides=None, fund=None, with_coach=True, num_players=0,
                   player_overrides=None, waive=True) -> dict:
    """ACTIVE season + one club (+ its coach, players with memberships, funding).

    Returns {"season", "club", "coach", "players": [...]}.
    """
    season = create_active_season(**(season_overrides or {}))
    club = create_club(season["id"], name="Alpha", school_name="Alpha HS")
    coach = create_coach(club["id"], full_name="Coach A", email="coach.a@example.com") if with_coach else None
    if fund is not None:
        fund_club(club["id"], fund)
        club = get_club(club["id"])
    players = []
    specs = player_overrides or [{} for _ in range(num_players)]
    for i, spec in enumerate(specs):
        player = create_player(club["id"], full_name=f"P{i + 1}", **spec)
        if waive:
            create_waived_membership(player["id"], season["id"])
        players.append(player)
    return {"season": season, "club": club, "coach": coach, "players": players}


def setup_two_club_league(season_overrides=None, players_a=None, players_b=None,
                          waive=True) -> dict:
    """ACTIVE season + clubs A and B + one coach each + players with memberships.

    players_a / players_b: lists of per-player factory overrides.
    Returns {"season", "club_a", "club_b", "coach_a", "coach_b",
             "players_a": [...], "players_b": [...]}.
    """
    season = create_active_season(**(season_overrides or {}))
    club_a = create_club(season["id"], name="Alpha", school_name="Alpha HS")
    club_b = create_club(season["id"], name="Beta", school_name="Beta HS")
    coach_a = create_coach(club_a["id"], full_name="Coach A", email="coach.a@example.com")
    coach_b = create_coach(club_b["id"], full_name="Coach B", email="coach.b@example.com")
    out = {
        "season": season, "club_a": club_a, "club_b": club_b,
        "coach_a": coach_a, "coach_b": coach_b, "players_a": [], "players_b": [],
    }
    for key, club, specs in (("players_a", club_a, players_a), ("players_b", club_b, players_b)):
        for i, spec in enumerate(specs or []):
            player = create_player(club["id"], full_name=f"{key}{i + 1}", **spec)
            if waive:
                create_waived_membership(player["id"], season["id"])
            out[key].append(player)
    return out


# ─── Tier 3: Meet lifecycle shortcuts ──

def create_meet(season_id, host_club_id, away_club_id, scheduled_date=None,
                rounds_count=1, boards_count=1) -> dict:
    """Create a meet (lands DRAFT)."""
    payload = create_meet_payload(
        season_id, host_club_id, away_club_id,
        scheduled_date=scheduled_date or TEST_DEFAULTS["MEET_DATE"],
        rounds_count=rounds_count, boards_count=boards_count,
    )
    return get_success_data(api_client.create_meet(payload, ADMIN))


def schedule_meet(meet_id) -> dict:
    return get_success_data(api_client.schedule_meet(meet_id, ADMIN))


def create_pairing(meet_id, round_number, board_number, white_player_id, black_player_id) -> dict:
    """Create a pairing, reading the meet's current version for the OCC field."""
    meet = get_success_data(api_client.get_meet(meet_id, ADMIN))
    payload = create_pairing_payload(
        round_number, board_number, white_player_id, black_player_id, meet["version"]
    )
    return get_success_data(api_client.create_pairing(meet_id, payload, ADMIN))


def publish_pairings(meet_id) -> dict:
    return get_success_data(api_client.publish_pairings(meet_id, ADMIN))


def create_meet_proctor(coach_id, meet_id, confirm=True) -> dict:
    """Assign a coach as meet proctor; optionally confirm (as that coach)."""
    assignment = get_success_data(api_client.create_proctor_assignment(
        create_proctor_assignment_payload(coach_id, "MEET", meet_id=meet_id), ADMIN))
    if confirm:
        assignment = get_success_data(api_client.confirm_proctor_assignment(
            assignment["id"], make_proctor_headers(coach_id)))
    return assignment


def create_tournament_proctor(coach_id, tournament_id, confirm=True) -> dict:
    assignment = get_success_data(api_client.create_proctor_assignment(
        create_proctor_assignment_payload(coach_id, "TOURNAMENT", tournament_id=tournament_id), ADMIN))
    if confirm:
        assignment = get_success_data(api_client.confirm_proctor_assignment(
            assignment["id"], make_proctor_headers(coach_id)))
    return assignment


def start_meet(meet_id) -> dict:
    return get_success_data(api_client.start_meet(meet_id, ADMIN))


def report_result(pairing_id, result, reporter_coach_id) -> dict:
    return get_success_data(api_client.report_result(
        pairing_id, {"result": result}, make_club_coach_headers(reporter_coach_id)))


def confirm_pairing(pairing_id, confirmer_coach_id) -> dict:
    return get_success_data(api_client.confirm_pairing(
        pairing_id, make_club_coach_headers(confirmer_coach_id)))


def report_and_confirm(pairing_id, result, reporter_coach_id, confirmer_coach_id) -> dict:
    """Two-party handshake: one club's coach reports, the other club's confirms."""
    report_result(pairing_id, result, reporter_coach_id)
    return confirm_pairing(pairing_id, confirmer_coach_id)


def run_meet(season_id, host_club, away_club, host_coach, away_coach, games,
             scheduled_date=None, results=None, complete=False) -> dict:
    """Full meet pipeline: create -> schedule -> pairings -> publish -> proctor -> start.

    games: list of (round_number, board_number, white_player_id, black_player_id)
           covering the full round x board grid.
    results: optional list aligned with games; each pairing is reported by the
             host club's coach and confirmed by the away club's coach.
    complete: when True (and results given), completes the meet.
    Returns {"meet": ..., "pairings": [...]} with the meet re-read at the end.
    """
    rounds_count = max(g[0] for g in games)
    boards_count = max(g[1] for g in games)
    meet = create_meet(season_id, host_club["id"], away_club["id"],
                       scheduled_date=scheduled_date,
                       rounds_count=rounds_count, boards_count=boards_count)
    schedule_meet(meet["id"])
    pairings = [
        create_pairing(meet["id"], rnd, board, white, black)
        for (rnd, board, white, black) in games
    ]
    publish_pairings(meet["id"])
    create_meet_proctor(host_coach["id"], meet["id"], confirm=True)
    start_meet(meet["id"])
    if results is not None:
        for pairing, result in zip(pairings, results):
            report_and_confirm(pairing["id"], result, host_coach["id"], away_coach["id"])
    if complete:
        get_success_data(api_client.complete_meet(meet["id"], ADMIN))
    return {
        "meet": get_success_data(api_client.get_meet(meet["id"], ADMIN)),
        "pairings": pairings,
    }


def farm_meet_wins(season_id, winner_club, winner_coach, loser_club, loser_coach,
                   winner_player_id, loser_player_id, n_wins,
                   scheduled_date="2026-09-05", complete=True) -> dict:
    """One meet of n rounds on one board; the host-side player wins every round.

    Each confirmed win is worth 3 performance points (PRD §3.5).
    Returns the run_meet result.
    """
    games = [(r, 1, winner_player_id, loser_player_id) for r in range(1, n_wins + 1)]
    return run_meet(
        season_id, winner_club, loser_club, winner_coach, loser_coach, games,
        scheduled_date=scheduled_date, results=["WHITE_WIN"] * n_wins, complete=complete,
    )


# ─── Tier 3: Tournament lifecycle shortcuts ──

def create_tournament(season_id, **overrides) -> dict:
    """Create a tournament (lands DRAFT)."""
    return get_success_data(api_client.create_tournament(
        create_tournament_payload(season_id, **overrides), ADMIN))


def create_section(tournament_id, **overrides) -> dict:
    return get_success_data(api_client.create_section(
        tournament_id, create_section_payload(**overrides), ADMIN))


def open_tournament(tournament_id) -> dict:
    return get_success_data(api_client.open_registration(tournament_id, ADMIN))


def setup_open_tournament_with_section(season_id, tournament_overrides=None,
                                       section_overrides=None) -> tuple:
    """Tournament created, one section created, registration opened.

    Returns (tournament, section).
    """
    tournament = create_tournament(season_id, **(tournament_overrides or {}))
    section = create_section(tournament["id"], **(section_overrides or {}))
    open_tournament(tournament["id"])
    return tournament, section


def create_entry(section_id, player_id, coach_id) -> dict:
    """Register a player into a section as the club's own coach."""
    return get_success_data(api_client.create_entry(
        section_id, {"player_id": player_id}, make_club_coach_headers(coach_id)))


def start_tournament_with_proctor(tournament_id, proctor_coach_id) -> dict:
    """close-registration (unless already CLOSED) -> confirmed proctor -> start."""
    tournament = get_success_data(api_client.get_tournament(tournament_id, ADMIN))
    if tournament["status"] == "REGISTRATION_OPEN":
        get_success_data(api_client.close_registration(tournament_id, ADMIN))
    create_tournament_proctor(proctor_coach_id, tournament_id, confirm=True)
    return get_success_data(api_client.start_tournament(tournament_id, ADMIN))


def farm_checkin_points(season_id, plan, name="Farm", proctor_coach_id=None) -> dict:
    """Award tournament check-in points (+2 each, PRD §3.5) to players.

    plan: list of (player_id, coach_id, n_checkins). One entry per section per
    player (uniqueness is per section-and-player), all entries checked in.
    Uses a fee-0 tournament so no club funding is needed.
    Returns {"tournament": ..., "entries": [...]}.
    """
    max_checkins = max(n for (_, _, n) in plan)
    tournament = create_tournament(season_id, name=name, entry_fee_cents=0,
                                   capacity=max(64, sum(n for (_, _, n) in plan)))
    sections = [
        create_section(tournament["id"], name=f"S-{i + 1}")
        for i in range(max_checkins)
    ]
    open_tournament(tournament["id"])
    entries = []
    for player_id, coach_id, n_checkins in plan:
        for i in range(n_checkins):
            entries.append(create_entry(sections[i]["id"], player_id, coach_id))
    proctor = proctor_coach_id or plan[0][1]
    start_tournament_with_proctor(tournament["id"], proctor)
    for entry in entries:
        get_success_data(api_client.check_in_entry(entry["id"], ADMIN))
    return {"tournament": tournament, "entries": entries}


# ─── Tier 5: Postseason (standings, bids) ──

def finalize_season(season_id) -> dict:
    return get_success_data(api_client.finalize_season(season_id, ADMIN))


def finalize_standings(season_id) -> list:
    """Snapshot standings with a fresh expected_season_version (OCC)."""
    season = get_success_data(api_client.get_season(season_id, ADMIN))
    return get_success_data(api_client.finalize_standings(
        season_id, {"expected_season_version": season["version"]}, ADMIN))


def generate_bids(season_id) -> list:
    return get_success_data(api_client.generate_bids(season_id, ADMIN))


def list_bids(params) -> list:
    """Filtered bid listing as the administrator. Returns the data array."""
    data, _meta = validate_paginated(api_client.list_bids(ADMIN, params=params))
    return data


def get_player(player_id) -> dict:
    return get_success_data(api_client.get_player(player_id, ADMIN))


def raise_dispute(pairing_id, coach_id, reason="result contested by club") -> dict:
    """ClubCoach of a participating club disputes a pairing (lands OPEN)."""
    return get_success_data(api_client.dispute_pairing(
        pairing_id, create_dispute_payload(reason), make_club_coach_headers(coach_id)))


def open_review(dispute_id) -> dict:
    return get_success_data(api_client.open_dispute_review(dispute_id, ADMIN))


def resolve_dispute(dispute_id, outcome, resolved_result=None, notes="adjudicated") -> dict:
    payload = {"outcome": outcome, "resolution_notes": notes}
    if resolved_result is not None:
        payload["resolved_result"] = resolved_result
    return get_success_data(api_client.resolve_dispute(dispute_id, payload, ADMIN))
