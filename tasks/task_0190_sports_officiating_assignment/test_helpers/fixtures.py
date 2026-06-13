"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: the Official role is entity-backed, so any ownership-gated
call uses make_official_headers(official_id) with the real Official.id — never the
shared TEST_USERS["official_headers"] fallback.

Geometry/clock conventions (mirroring the design recipes):
  - official home == game venue (40.0, -75.0) => great-circle distance 0,
    so mileage_cents is 0 and pay depends only on rank/fee/uplift math.
  - a wide AVAILABLE window [2026-01-01, 2027-01-01) covers every game interval.
  - the server clock is pinned via set_clock before time-gated steps.
  - every expected_game_version is re-read from a fresh GET /games/{id}
    immediately before each OCC call, because cascades silently bump version.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_league_payload, create_official_payload, create_availability_payload,
    create_game_payload, create_crew_slot_payload, offer_payload, accept_payload,
    game_version_payload, set_clock_payload, create_evaluation_payload,
)
from .test_users import TEST_USERS, make_official_headers

ADMIN = TEST_USERS["league_admin_headers"]
ASSIGNOR = TEST_USERS["assignor_headers"]
EVALUATOR = TEST_USERS["evaluator_headers"]


# ─── Low-level building blocks ───────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Pin the server's logical UTC clock."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def create_league(activate=True, **overrides) -> dict:
    """Create a league; activate it (SETUP -> OPEN) unless activate=False."""
    league = get_success_data(
        api_client.create_league(create_league_payload(**overrides), ADMIN))
    if activate:
        league = get_success_data(api_client.activate_league(league["id"], ADMIN))
    return league


def create_official(league_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_official(create_official_payload(league_id, **overrides), ADMIN))


def create_wide_availability(official_id, **overrides) -> dict:
    """Declare the official's wide AVAILABLE window, threading their identity."""
    return get_success_data(api_client.create_availability(
        create_availability_payload(official_id, **overrides),
        make_official_headers(official_id)))


def current_game_version(game_id) -> int:
    """Re-read the game's live version immediately before an OCC call."""
    return get_success_data(api_client.get_game(game_id, ASSIGNOR))["version"]


def make_postseason_eligible(league, official, score=5.0,
                             prior_game_start="2026-02-01T18:00:00Z",
                             prior_settle_clock="2026-02-01T20:30:00Z"):
    """Make an official genuinely postseason-eligible per PRD §3.12.

    PRD §3.12 requires that an eligible official's `mean_rating` be NOT null and
    at least `postseason_min_rating`, that `games_worked_count` be at least
    `postseason_min_games`, that `noshow_count` be at most `postseason_max_noshows`,
    and that `status` be ACTIVE. A freshly created official has `mean_rating` null
    (PRD §3.11: "When the official has no evaluations, `mean_rating` is null") and
    `games_worked_count` 0, so the postseason offer gate (PRD §3.4 rule 7) correctly
    rejects it with ERR_NOT_POSTSEASON_ELIGIBLE.

    This helper drives one full regular-season lifecycle for the official —
    offer → accept → lock → settle (so the assignment reaches COMPLETED, lifting
    `games_worked_count` to 1) followed by an evaluation (so `mean_rating` becomes
    non-null) — exactly as the PRD's eligibility recipe demands. It assumes the
    league has wide thresholds (min_games<=1, min_rating<=score, max_noshows>=0),
    which the calling tests configure. The prior game is at the official's home
    venue (distance 0) and uses an ASSISTANT slot (no rank gate), so it works for
    any rank. The server clock is restored to its pre-call value on return so
    time-gated assertions downstream are unaffected.

    Requires an ACTIVE wide-window availability covering the prior game interval;
    callers create that via create_wide_availability(official["id"]). Callers
    should invoke this BEFORE pinning the clock for their own scenario, since this
    helper moves the clock to the prior-game window; the caller's subsequent
    set_clock restores the scenario clock.
    """
    set_clock("2026-02-01T00:00:00Z")
    game = get_success_data(api_client.create_game(create_game_payload(
        league["id"], home_team="EligPrior", away_team="EligPriorAway",
        start_utc=prior_game_start), ASSIGNOR))
    slot = get_success_data(api_client.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR))
    game = get_success_data(api_client.open_game(game["id"], ASSIGNOR))
    asg = offer_slot(slot["id"], official["id"], game["id"])
    accept_assignment(asg["id"], official["id"], game["id"])
    lock_game(game["id"])
    set_clock(prior_settle_clock)
    settle_game(game["id"])
    get_success_data(api_client.create_evaluation(
        asg["id"], create_evaluation_payload(score), EVALUATOR))
    return get_success_data(api_client.get_official(official["id"], ADMIN))


# ─── Tier 1/2: League + Official + Game + provisioned, opened game ───────────

def setup_open_game_with_slot(position="ASSISTANT", official_overrides=None,
                              league_overrides=None, game_overrides=None,
                              slot_overrides=None, with_availability=True,
                              clock="2026-06-01T00:00:00Z"):
    """Active league + one official (+ wide availability) + an OPEN single-slot game.

    Returns dict with keys: league, official, game, slot, game_version
    (game_version is the live version captured right after open).
    """
    league = create_league(**(league_overrides or {}))
    official = create_official(league["id"], **(official_overrides or {}))
    if with_availability:
        create_wide_availability(official["id"])
    if clock:
        set_clock(clock)
    game = get_success_data(api_client.create_game(
        create_game_payload(league["id"], **(game_overrides or {})), ASSIGNOR))
    slot = get_success_data(api_client.create_crew_slot(
        game["id"], create_crew_slot_payload(position=position, **(slot_overrides or {})),
        ASSIGNOR))
    game = get_success_data(api_client.open_game(game["id"], ASSIGNOR))
    return {
        "league": league,
        "official": official,
        "game": game,
        "slot": slot,
        "game_version": game["version"],
    }


def offer_slot(slot_id, official_id, game_id) -> dict:
    """Offer a slot to an official using a freshly re-read game version."""
    gv = current_game_version(game_id)
    return get_success_data(api_client.offer_crew_slot(
        slot_id, offer_payload(official_id, gv), ASSIGNOR))


def accept_assignment(assignment_id, official_id, game_id) -> dict:
    """Official accepts using a freshly re-read game version."""
    gv = current_game_version(game_id)
    return get_success_data(api_client.accept_assignment(
        assignment_id, accept_payload(gv), make_official_headers(official_id)))


def decline_assignment(assignment_id, official_id) -> dict:
    return get_success_data(api_client.decline_assignment(
        assignment_id, make_official_headers(official_id)))


def lock_game(game_id) -> dict:
    gv = current_game_version(game_id)
    return get_success_data(api_client.lock_game(game_id, game_version_payload(gv), ASSIGNOR))


def settle_game(game_id) -> dict:
    gv = current_game_version(game_id)
    return get_success_data(api_client.settle_game(game_id, game_version_payload(gv), ASSIGNOR))


# ─── Tier 3: Lifecycle shortcuts ─────────────────────────────────────────────

def setup_offered_assignment(position="ASSISTANT", **kwargs):
    """OPEN game + slot offered to the official. Returns ctx with 'assignment'."""
    ctx = setup_open_game_with_slot(position=position, **kwargs)
    asg = offer_slot(ctx["slot"]["id"], ctx["official"]["id"], ctx["game"]["id"])
    ctx["assignment"] = asg
    return ctx


def setup_accepted_assignment(position="ASSISTANT", **kwargs):
    """OPEN game offered + accepted (game auto-STAFFED). Returns ctx with 'assignment'."""
    ctx = setup_offered_assignment(position=position, **kwargs)
    asg = accept_assignment(ctx["assignment"]["id"], ctx["official"]["id"], ctx["game"]["id"])
    ctx["assignment"] = asg
    ctx["game"] = get_success_data(api_client.get_game(ctx["game"]["id"], ASSIGNOR))
    return ctx


def setup_locked_game(position="REFEREE", official_overrides=None, **kwargs):
    """OPEN game offered + accepted + LOCKED (clock before start). Returns ctx."""
    if official_overrides is None:
        official_overrides = {"rank": "SENIOR"}  # REFEREE slots need SENIOR+
    ctx = setup_accepted_assignment(
        position=position, official_overrides=official_overrides, **kwargs)
    ctx["game"] = lock_game(ctx["game"]["id"])
    return ctx


def setup_completed_assignment(position="REFEREE", official_overrides=None,
                               settle_clock="2026-06-20T19:00:00Z", **kwargs):
    """Full lifecycle through settlement: assignment COMPLETED, game COMPLETED.

    Returns ctx with refreshed 'assignment' (COMPLETED) and 'game' (COMPLETED).
    """
    ctx = setup_locked_game(position=position, official_overrides=official_overrides, **kwargs)
    set_clock(settle_clock)
    ctx["game"] = settle_game(ctx["game"]["id"])
    ctx["assignment"] = get_success_data(
        api_client.get_assignment(ctx["assignment"]["id"], ASSIGNOR))
    return ctx


# ─── Tier 3: Decline -> appeal chains ────────────────────────────────────────

def setup_declined_with_appeal(decline_clock="2026-06-20T16:00:00Z",
                               game_start="2026-06-20T18:00:00Z",
                               reason="Appeal reason", **kwargs):
    """OPEN game offered, then declined (late-tier penalty 8), then appeal filed.

    Clock at decline is 2h before start => late tier => penalty 8 for a first,
    regular-game decline. Returns ctx with 'assignment' (DECLINED) and 'appeal'.
    """
    game_overrides = kwargs.pop("game_overrides", {})
    game_overrides.setdefault("start_utc", game_start)
    ctx = setup_open_game_with_slot(
        position="ASSISTANT", clock=decline_clock, game_overrides=game_overrides, **kwargs)
    asg = offer_slot(ctx["slot"]["id"], ctx["official"]["id"], ctx["game"]["id"])
    asg = decline_assignment(asg["id"], ctx["official"]["id"])
    ctx["assignment"] = asg
    appeal = get_success_data(api_client.create_appeal(
        asg["id"], {"reason": reason}, make_official_headers(ctx["official"]["id"])))
    ctx["appeal"] = appeal
    return ctx


# ─── Tier 4: Multi-slot games (OCC / crew-count scenarios) ───────────────────

def setup_two_slot_open_game(clock="2026-06-01T00:00:00Z"):
    """Active league + two officials (A, B) with wide availability + an OPEN
    2-slot game. Returns dict: league, official_a, official_b, game, slot1, slot2.
    """
    league = create_league()
    oa = create_official(league["id"], full_name="A", rank="ROOKIE")
    ob = create_official(league["id"], full_name="B", rank="ROOKIE")
    create_wide_availability(oa["id"])
    create_wide_availability(ob["id"])
    set_clock(clock)
    game = get_success_data(api_client.create_game(
        create_game_payload(league["id"], required_crew_size=2), ASSIGNOR))
    s1 = get_success_data(api_client.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR))
    s2 = get_success_data(api_client.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR))
    game = get_success_data(api_client.open_game(game["id"], ASSIGNOR))
    return {
        "league": league,
        "official_a": oa,
        "official_b": ob,
        "game": game,
        "slot1": s1,
        "slot2": s2,
    }


def get_season_ledger(league_id, official_id) -> dict:
    """Read the (league, official) SeasonLedger row via the official's ledger list."""
    rows, _meta = _paginated(api_client.list_official_ledger(official_id, ADMIN))
    for row in rows:
        if row.get("league_id") == league_id and row.get("official_id") == official_id:
            return row
    # Fall back to the league-scoped ledger listing.
    rows, _meta = _paginated(api_client.list_league_season_ledgers(league_id, ADMIN))
    for row in rows:
        if row.get("official_id") == official_id:
            return row
    raise AssertionError(
        f"Setup failed: no SeasonLedger for league={league_id} official={official_id}")


def _paginated(response):
    """Extract (data_list, meta) from a list response without depending on the
    framework's strict validator (used only inside setup helpers)."""
    body = response.json()
    return body["data"], body.get("meta", {})
