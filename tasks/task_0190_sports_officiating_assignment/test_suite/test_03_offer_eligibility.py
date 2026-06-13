"""Offer-time eligibility gauntlet (§3.4): suspension, rank, conflict-of-interest,
availability cover, double-booking, travel radius, postseason gate — plus the two
priority-pair conflicts and the availability/travel boundary-precision instances.

Each test translates exactly one design instance (Difficulty queue A or Corner queue B).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_league_payload, create_official_payload, create_availability_payload,
    create_conflict_declaration_payload, create_game_payload, create_crew_slot_payload,
    update_official_payload,
    TEST_USERS, make_official_headers,
    setup_open_game_with_slot,
    offer_slot, accept_assignment, current_game_version, set_clock,
    create_league, create_official, create_wide_availability,
)

ADMIN = TEST_USERS["league_admin_headers"]
ASSIGNOR = TEST_USERS["assignor_headers"]


# ─── Priority-pair validation conflicts (Difficulty) ─────────────────────────

def test_rank_ineligible_beats_travel_radius(api):
    """PRD §3.4 (offer eligibility order): step 2 "**Rank eligibility.** If the
    slot's `position` is `REFEREE`, the official's `rank` must be `SENIOR` or
    `MASTER`; a lower rank is rejected with `ERR_RANK_INELIGIBLE`." (checked before)
    step 6 "**Travel radius.** The great-circle distance between the official's home
    location and the game's venue must be at most the official's `max_travel_miles`;
    a longer trip is rejected with `ERR_OUTSIDE_TRAVEL_RADIUS`."

    Design: Difficulty/priority_pair_validation_conflict/rank_ineligible_beats_travel_radius
    """
    league = create_league(sport="BASKETBALL")
    official = create_official(league["id"], rank="ROOKIE", max_travel_miles=50)
    create_wide_availability(official["id"])
    set_clock("2026-06-01T00:00:00Z")
    # Venue far (lat 41 vs home 40 => ~69mi > 50) AND ROOKIE on a REFEREE slot.
    game = validate_success(api.create_game(create_game_payload(
        league["id"], venue_lat=41.0, venue_lon=-75.0), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="REFEREE"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    gv = current_game_version(game["id"])
    res = api.offer_crew_slot(
        slot["id"], {"official_id": official["id"], "expected_game_version": gv}, ASSIGNOR)
    validate_error(res, "ERR_RANK_INELIGIBLE", expected_status=422)


def test_conflict_of_interest_beats_outside_availability(api):
    """PRD §3.4 (eligibility step 3, checked before step 4): "**Conflict of
    interest.** The official must have no `TEAM`-scoped conflict naming this game's
    `home_team` or `away_team`, and no `OFFICIAL`-scoped conflict with any official
    already `FILLED` on the same game; a violation of either is rejected with
    `ERR_CONFLICT_OF_INTEREST`."
    PRD §3.4 (eligibility step 4): "**Availability cover.** The game's occupied
    interval (from `start_utc` to `start_utc` plus `duration_minutes`, treated as
    half-open with the end excluded) must lie entirely inside at least one of the
    official's `ACTIVE` `AVAILABLE` windows and must not intersect any `ACTIVE`
    `BLACKOUT` window; otherwise the offer is rejected with
    `ERR_OUTSIDE_AVAILABILITY`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_of_interest_beats_outside_availability
    """
    league = create_league(sport="SOCCER")
    official = create_official(league["id"], rank="SENIOR")
    # TEAM conflict against 'Hawks' AND no availability window declared at all.
    validate_success(api.create_conflict_declaration(
        create_conflict_declaration_payload(official["id"], scope="TEAM", team_name="Hawks"),
        ADMIN), 201)
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(
        league["id"], home_team="Hawks"), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="REFEREE"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    gv = current_game_version(game["id"])
    res = api.offer_crew_slot(
        slot["id"], {"official_id": official["id"], "expected_game_version": gv}, ASSIGNOR)
    validate_error(res, "ERR_CONFLICT_OF_INTEREST", expected_status=422)


# ─── Boundary precision: travel radius inclusive, availability end-exclusive ──

def test_travel_radius_distance_zero_inclusive_succeeds(api):
    """PRD §3.4 (step 6): "The great-circle distance between the official's home
    location and the game's venue must be at most the official's `max_travel_miles`;
    a longer trip is rejected with `ERR_OUTSIDE_TRAVEL_RADIUS`."
    PRD §3.4: "The frozen `distance_miles` is the great-circle distance in miles
    between the official's home (`home_lat`, `home_lon`) and the venue (`venue_lat`,
    `venue_lon`), carried to two decimal places."

    Design: Difficulty/boundary_precision_check/travel_radius_dist_zero_inclusive_succeeds
    """
    ctx = setup_open_game_with_slot(
        position="ASSISTANT", official_overrides={"rank": "ROOKIE", "max_travel_miles": 50})
    gv = current_game_version(ctx["game"]["id"])
    res = api.offer_crew_slot(
        ctx["slot"]["id"],
        {"official_id": ctx["official"]["id"], "expected_game_version": gv}, ASSIGNOR)
    asg = validate_success(res, 201)
    assert asg["distance_miles"] == 0.0
    assert asg["status"] == "OFFERED"


# ─── Resource temporal overlap (Difficulty) ──────────────────────────────────

def test_official_double_booked_strict_overlap(api):
    """PRD §3.4 (step 5): "**Double-booking.** The game's interval must not overlap
    the interval of any other game on which this official already holds an
    `OFFERED` or `ACCEPTED` assignment; overlap is measured closed on the start and
    open on the end, so two games that merely touch at an endpoint do not conflict.
    A clash is rejected with `ERR_OFFICIAL_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/official_double_book_overlapping_games_strict_overlap
    """
    league = create_league(sport="SOCCER")
    official = create_official(league["id"], rank="ROOKIE")
    create_wide_availability(official["id"])
    set_clock("2026-06-01T00:00:00Z")
    # G1 [18:00, 20:00) accepted; G2 [19:00, 21:00) overlaps by 1h.
    g1 = validate_success(api.create_game(create_game_payload(
        league["id"], home_team="H1", away_team="A1",
        start_utc="2026-06-20T18:00:00Z", duration_minutes=120), ASSIGNOR), 201)
    s1 = validate_success(api.create_crew_slot(
        g1["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    g1 = validate_success(api.open_game(g1["id"], ASSIGNOR), 200)
    a1 = offer_slot(s1["id"], official["id"], g1["id"])
    accept_assignment(a1["id"], official["id"], g1["id"])

    g2 = validate_success(api.create_game(create_game_payload(
        league["id"], home_team="H2", away_team="A2",
        start_utc="2026-06-20T19:00:00Z", duration_minutes=120), ASSIGNOR), 201)
    s2 = validate_success(api.create_crew_slot(
        g2["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    g2 = validate_success(api.open_game(g2["id"], ASSIGNOR), 200)
    gv = current_game_version(g2["id"])
    res = api.offer_crew_slot(
        s2["id"], {"official_id": official["id"], "expected_game_version": gv}, ASSIGNOR)
    validate_error(res, "ERR_OFFICIAL_DOUBLE_BOOKED", expected_status=409)


def test_blackout_intersection_defeats_availability(api):
    """PRD §3.4 (eligibility step 4): "**Availability cover.** The game's occupied
    interval (from `start_utc` to `start_utc` plus `duration_minutes`, treated as
    half-open with the end excluded) must lie entirely inside at least one of the
    official's `ACTIVE` `AVAILABLE` windows and must not intersect any `ACTIVE`
    `BLACKOUT` window; otherwise the offer is rejected with
    `ERR_OUTSIDE_AVAILABILITY`."

    Design: Difficulty/resource_temporal_overlap/availability_blackout_intersection_semantics
    """
    league = create_league(sport="FOOTBALL")
    official = create_official(league["id"], rank="ROOKIE")
    # Wide AVAILABLE window for the whole day, plus a BLACKOUT [19:30, 19:45) that
    # intersects the game interval [18:00, 20:00).
    validate_success(api.create_availability(create_availability_payload(
        official["id"],
        window_start_utc="2026-06-20T00:00:00Z",
        window_end_utc="2026-06-21T00:00:00Z"),
        make_official_headers(official["id"])), 201)
    validate_success(api.create_availability(create_availability_payload(
        official["id"],
        window_start_utc="2026-06-20T19:30:00Z",
        window_end_utc="2026-06-20T19:45:00Z",
        kind="BLACKOUT"),
        make_official_headers(official["id"])), 201)
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(
        league["id"], start_utc="2026-06-20T18:00:00Z", duration_minutes=120), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    gv = current_game_version(game["id"])
    res = api.offer_crew_slot(
        slot["id"], {"official_id": official["id"], "expected_game_version": gv}, ASSIGNOR)
    validate_error(res, "ERR_OUTSIDE_AVAILABILITY", expected_status=422)


# ─── Single-violation validation claims (Corner) ─────────────────────────────

def test_offer_to_suspended_official_returns_official_suspended(api):
    """PRD §3.4 (step 1): "**Suspension.** The candidate official's `status` must be
    `ACTIVE`; a `SUSPENDED` official cannot receive a new offer and the request is
    rejected with `ERR_OFFICIAL_SUSPENDED`."

    Design: Corner/validations/offer_to_suspended_official_returns_official_suspended
    """
    league = create_league(sport="SOCCER")
    official = create_official(league["id"])
    create_wide_availability(official["id"])
    ov1 = validate_success(api.get_official(official["id"], ADMIN), 200)["version"]
    validate_success(api.update_official(
        official["id"], update_official_payload(ov1, status="SUSPENDED"), ADMIN), 200)
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(league["id"]), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    gv = current_game_version(game["id"])
    res = api.offer_crew_slot(
        slot["id"], {"official_id": official["id"], "expected_game_version": gv}, ASSIGNOR)
    validate_error(res, "ERR_OFFICIAL_SUSPENDED", expected_status=409)


def test_offer_postseason_game_to_ineligible_official(api):
    """PRD §3.4 (step 7): "**Postseason gate.** If the game's `is_postseason` flag is
    set, the candidate must currently be `postseason_eligible`; an ineligible
    official is rejected with `ERR_NOT_POSTSEASON_ELIGIBLE`."
    PRD §3.12: "their `games_worked_count` is at least the league's
    `postseason_min_games`".

    Design: Corner/validations/offer_postseason_game_to_ineligible_official_returns_not_postseason_eligible
    """
    league = create_league(sport="BASKETBALL")  # default postseason gates (min 8)
    official = create_official(league["id"], rank="SENIOR")  # 0 games worked < 8
    create_wide_availability(official["id"])
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(
        league["id"], is_postseason=True), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="REFEREE"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    gv = current_game_version(game["id"])
    res = api.offer_crew_slot(
        slot["id"], {"official_id": official["id"], "expected_game_version": gv}, ASSIGNOR)
    validate_error(res, "ERR_NOT_POSTSEASON_ELIGIBLE", expected_status=422)
