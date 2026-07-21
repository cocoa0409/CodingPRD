"""Composite setup helpers.

Every test runs against a freshly restarted server (empty DB), so each fixture
builds its full precondition chain from scratch using only PRD-declared
endpoints. Setup calls use the lenient get_success_data() so setup failures
surface as clear "Setup failed" errors rather than confusing assertions.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_venue_payload,
    create_station_payload,
    create_stream_channel_payload,
    create_player_payload,
    create_tournament_payload,
    create_registration_payload,
    schedule_match_payload,
    report_match_payload,
    confirm_match_payload,
    create_dispute_payload,
)
from .test_users import TEST_USERS, make_referee_headers, make_player_headers

DIRECTOR = TEST_USERS["director_headers"]
PUBLIC = TEST_USERS["public_headers"]

# Default non-overlapping station windows within a wide-open venue.
WIN = {
    "a": ("2026-07-01T10:00:00Z", "2026-07-01T11:00:00Z"),
    "b": ("2026-07-01T11:30:00Z", "2026-07-01T12:30:00Z"),
    "c": ("2026-07-01T13:00:00Z", "2026-07-01T14:00:00Z"),
}


# --------------------------------------------------------------------------
# Primitive creators
# --------------------------------------------------------------------------
def create_venue(open_minute=0, close_minute=1440, name="Arena", address="1 Main St"):
    return get_success_data(api_client.create_venue(
        create_venue_payload(name=name, address=address,
                             open_minute=open_minute, close_minute=close_minute), DIRECTOR))


def create_station(venue_id, label="Table 1"):
    return get_success_data(api_client.create_station(
        venue_id, create_station_payload(label=label), DIRECTOR))


def create_stream_channel(platform="TWITCH", name="Main Channel"):
    return get_success_data(api_client.create_stream_channel(
        create_stream_channel_payload(name=name, platform=platform), DIRECTOR))


def create_player(rating=1000, tax_id_provided=False, display_name="Player", email=None):
    return get_success_data(api_client.create_player(
        create_player_payload(display_name=display_name, email=email,
                             rating=rating, tax_id_provided=tax_id_provided), PUBLIC))


def create_tournament(venue_id, **overrides):
    return get_success_data(api_client.create_tournament(
        create_tournament_payload(venue_id, **overrides), DIRECTOR))


def open_registration(tournament_id):
    return get_success_data(api_client.open_registration(tournament_id, {}, DIRECTOR))


def register(tournament_id, player_id, seed_input=None):
    payload = create_registration_payload(tournament_id, player_id)
    if seed_input is not None:
        payload["seed_input"] = seed_input
    return get_success_data(api_client.create_registration(payload, make_player_headers(player_id)))


def close_registration(tournament_id):
    return get_success_data(api_client.close_registration(tournament_id, DIRECTOR))


def check_in(registration_id, player_id):
    return get_success_data(api_client.check_in(registration_id, make_player_headers(player_id)))


def generate_bracket(tournament_id):
    return get_success_data(api_client.generate_bracket(tournament_id, DIRECTOR))


def start_tournament(tournament_id):
    return get_success_data(api_client.start_tournament(tournament_id, DIRECTOR))


def get_tournament(tournament_id):
    return get_success_data(api_client.get_tournament(tournament_id, PUBLIC))


def get_match(match_id):
    return get_success_data(api_client.get_match(match_id, PUBLIC))


def get_registration(registration_id):
    return get_success_data(api_client.get_registration(registration_id, PUBLIC))


def list_tournament_matches(tournament_id):
    return get_success_data(api_client.list_tournament_matches(tournament_id, PUBLIC))


def list_payouts(tournament_id, variant=None, status=None):
    params = {"tournament_id": tournament_id, "limit": 100}
    if variant:
        params["variant"] = variant
    if status:
        params["status"] = status
    return get_success_data(api_client.list_payouts(PUBLIC, params=params))


# --------------------------------------------------------------------------
# Match-play helpers (winner-slot aware to survive home/away seeding freedom)
# --------------------------------------------------------------------------
def schedule(match_id, station_id, window="a", start=None, end=None, headers=None):
    if start is None:
        start, end = WIN[window]
    return get_success_data(api_client.schedule_match(
        match_id, schedule_match_payload(station_id, start, end),
        headers or TEST_USERS["referee_headers"]))


def report_scores(match_id, home_score, away_score, headers):
    return get_success_data(api_client.report_match(
        match_id, report_match_payload(home_score, away_score), headers))


def report_winner(match_id, winner_registration_id, headers, winner_score=2, loser_score=0):
    """Report so that winner_registration_id wins, regardless of which slot it
    occupies. Returns the reported match data (with bumped version)."""
    m = get_match(match_id)
    if m["home_registration_id"] == winner_registration_id:
        home, away = winner_score, loser_score
    elif m["away_registration_id"] == winner_registration_id:
        home, away = loser_score, winner_score
    else:
        raise AssertionError(
            f"{winner_registration_id} is not a competitor of match {match_id}")
    return report_scores(match_id, home, away, headers)


def confirm(match_id, expected_version, headers):
    return get_success_data(api_client.confirm_match(
        match_id, confirm_match_payload(expected_version), headers))


# --------------------------------------------------------------------------
# Two-player SINGLE_ELIM builders
# --------------------------------------------------------------------------
def build_two_player_single_elim(
    prize_pool_cents=0,
    paid_places=1,
    p1_rating=1500,
    p2_rating=1200,
    p1_tax=False,
    p2_tax=False,
    seeding_method="RATING",
    tiebreak_method="SEED",
    max_participants=4,
    open_minute=0,
    close_minute=1440,
    check_in_deadline="2026-08-01T00:00:00Z",
    name="Cup",
):
    """Build a 2-player SINGLE_ELIM tournament through START (IN_PROGRESS).

    Returns ctx with keys: v_id, st_id, p1, p2, r1, r2, t_id, m_id.
    P1 is the higher-rated player (seed 1 under RATING). m_id is the final.
    """
    venue = create_venue(open_minute, close_minute)
    station = create_station(venue["id"])
    p1 = create_player(rating=p1_rating, tax_id_provided=p1_tax, display_name="P1")
    p2 = create_player(rating=p2_rating, tax_id_provided=p2_tax, display_name="P2")
    t = create_tournament(
        venue["id"], name=name, format="SINGLE_ELIM", max_participants=max_participants,
        prize_pool_cents=prize_pool_cents, paid_places=paid_places,
        seeding_method=seeding_method, tiebreak_method=tiebreak_method,
        check_in_deadline=check_in_deadline)
    open_registration(t["id"])
    r1 = register(t["id"], p1["id"])
    r2 = register(t["id"], p2["id"])
    close_registration(t["id"])
    check_in(r1["id"], p1["id"])
    check_in(r2["id"], p2["id"])
    generate_bracket(t["id"])
    start_tournament(t["id"])
    matches = list_tournament_matches(t["id"])
    m_id = matches[0]["id"]
    return {
        "v_id": venue["id"], "st_id": station["id"],
        "p1": p1["id"], "p2": p2["id"], "r1": r1["id"], "r2": r2["id"],
        "t_id": t["id"], "m_id": m_id,
    }


def play_final_scheduled(ctx):
    """Schedule the 2-player final on the venue's station. Returns match data."""
    return schedule(ctx["m_id"], ctx["st_id"], window="a")


def play_final_reported(ctx, winner_registration_id, reporter_headers=None):
    """Schedule + report the final so winner_registration_id wins. Returns match."""
    schedule(ctx["m_id"], ctx["st_id"], window="a")
    reporter = reporter_headers or make_referee_headers("ref-reporter")
    return report_winner(ctx["m_id"], winner_registration_id, reporter)


def play_final_confirmed(ctx, winner_registration_id,
                         reporter_headers=None, confirmer_user_id="ref-confirmer"):
    """Schedule + report + confirm the final so winner_registration_id wins.
    Returns the CONFIRMED match data."""
    reported = play_final_reported(ctx, winner_registration_id, reporter_headers)
    return confirm(ctx["m_id"], reported["version"], make_referee_headers(confirmer_user_id))


def raise_dispute(match_id, raised_by_registration_id, raiser_player_id, reason="challenge"):
    return get_success_data(api_client.create_dispute(
        create_dispute_payload(match_id, raised_by_registration_id, reason),
        make_player_headers(raiser_player_id)))


# --------------------------------------------------------------------------
# Three-player ROUND_ROBIN builder
# --------------------------------------------------------------------------
def build_round_robin_3p(tiebreak_method="GAME_DIFF", ratings=(1500, 1200, 1000)):
    """Build a 3-player ROUND_ROBIN through START (IN_PROGRESS).

    Under RATING seeding: A=seed1 (highest rating), B=seed2, C=seed3.
    Round-robin pins the lower seed as home, so match m_ab has home=ra, away=rb.
    Returns ctx: t_id, v_id, st_id, pa/pb/pc, ra/rb/rc, m_ab/m_ac/m_bc.
    """
    venue = create_venue()
    station = create_station(venue["id"])
    pa = create_player(rating=ratings[0], display_name="A")
    pb = create_player(rating=ratings[1], display_name="B")
    pc = create_player(rating=ratings[2], display_name="C")
    t = create_tournament(
        venue["id"], name="RR", format="ROUND_ROBIN", max_participants=8,
        prize_pool_cents=0, paid_places=1, seeding_method="RATING",
        tiebreak_method=tiebreak_method)
    open_registration(t["id"])
    ra = register(t["id"], pa["id"])
    rb = register(t["id"], pb["id"])
    rc = register(t["id"], pc["id"])
    close_registration(t["id"])
    check_in(ra["id"], pa["id"])
    check_in(rb["id"], pb["id"])
    check_in(rc["id"], pc["id"])
    generate_bracket(t["id"])
    start_tournament(t["id"])

    def find_match(home_id, away_id):
        data = get_success_data(api_client.list_matches(PUBLIC, params={
            "tournament_id": t["id"], "home_registration_id": home_id,
            "away_registration_id": away_id, "limit": 100}))
        assert data, f"no match with home={home_id} away={away_id}"
        return data[0]["id"]

    return {
        "t_id": t["id"], "v_id": venue["id"], "st_id": station["id"],
        "pa": pa["id"], "pb": pb["id"], "pc": pc["id"],
        "ra": ra["id"], "rb": rb["id"], "rc": rc["id"],
        "m_ab": find_match(ra["id"], rb["id"]),
        "m_ac": find_match(ra["id"], rc["id"]),
        "m_bc": find_match(rb["id"], rc["id"]),
    }


def setup_round_robin_confirmed(tiebreak_method, results, ratings=(1500, 1200, 1000)):
    """Full 3-player round robin with all 3 matches CONFIRMED.

    `results` maps 'ab'/'ac'/'bc' -> (home_score, away_score) (home = lower seed).
    All matches are scheduled BEFORE any confirm so that per-match elimination of
    a loser cannot block scheduling a still-CHECKED_IN competitor's later match.
    """
    ctx = build_round_robin_3p(tiebreak_method, ratings)
    reporter = make_referee_headers("ref-reporter")
    confirmer = make_referee_headers("ref-confirmer")
    match_ids = {"ab": ctx["m_ab"], "ac": ctx["m_ac"], "bc": ctx["m_bc"]}
    # schedule all three on distinct non-overlapping windows
    schedule(ctx["m_ab"], ctx["st_id"], window="a")
    schedule(ctx["m_ac"], ctx["st_id"], window="b")
    schedule(ctx["m_bc"], ctx["st_id"], window="c")
    # report + confirm each
    for key, (home_score, away_score) in results.items():
        m_id = match_ids[key]
        reported = report_scores(m_id, home_score, away_score, reporter)
        confirm(m_id, reported["version"], confirmer)
    return ctx


def standings_rows(data):
    """Extract the ranked rows list from the standings response payload."""
    if isinstance(data, dict):
        return data.get("rows", [])
    if isinstance(data, list):
        return data
    return []
