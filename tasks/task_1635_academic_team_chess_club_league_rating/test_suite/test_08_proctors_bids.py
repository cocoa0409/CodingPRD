"""Proctor staffing and postseason qualification-bid claims (PRD §2.5, §3.8, §3.9)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_club,
    create_coach,
    create_meet,
    create_player,
    create_proctor_assignment_payload,
    create_tournament,
    create_waived_membership,
    farm_checkin_points,
    farm_meet_wins,
    finalize_season,
    finalize_standings,
    generate_bids,
    list_bids,
    make_club_coach_headers,
    make_proctor_headers,
    parse_iso_instant,
    setup_one_club,
    setup_two_club_league,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["federation_admin_headers"]

# ─── Proctor overlap (queue A) ──

def _setup_proctor_overlap(api):
    ctx = setup_two_club_league()
    tournament = create_tournament(ctx["season"]["id"], name="State Qualifier",
                                   start_date="2026-09-10", end_date="2026-09-12",
                                   entry_fee_cents=0)
    validate_success(api.create_proctor_assignment(
        create_proctor_assignment_payload(ctx["coach_a"]["id"], "TOURNAMENT",
                                          tournament_id=tournament["id"]),
        ADMIN), 201)
    meet13 = create_meet(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_b"]["id"],
                         "2026-09-13")
    meet14 = create_meet(ctx["season"]["id"], ctx["club_b"]["id"], ctx["club_a"]["id"],
                         "2026-09-14")
    return ctx, tournament, meet13, meet14

def test_proctor_buffer_day_rejected(api):
    """PRD §3.8: "Double-booking is prevented with a rest buffer: if the coach already
    holds an assignment in `ASSIGNED` or `CONFIRMED` whose event interval — a meet
    occupies its single `scheduled_date`, a tournament the span from its `start_date`
    through its `end_date` — expanded by one rest day on each side intersects the new
    event's interval, the assignment is rejected with `ERR_PROCTOR_DOUBLE_BOOKED`."
    Tournament [09-10, 09-12] expands to [09-09, 09-13]; a meet on 09-13 intersects.

    Design: Difficulty/resource_temporal_overlap/proctor_buffered_interval_overlap
    """
    ctx, tournament, meet13, _ = _setup_proctor_overlap(api)
    res = api.create_proctor_assignment(
        create_proctor_assignment_payload(ctx["coach_a"]["id"], "MEET", meet_id=meet13["id"]),
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_PROCTOR_DOUBLE_BOOKED)

def test_proctor_two_days_after_accepted(api):
    """PRD §3.8: "expanded by one rest day on each side intersects the new event's
    interval, the assignment is rejected with `ERR_PROCTOR_DOUBLE_BOOKED`". Tournament
    [09-10, 09-12] expands to [09-09, 09-13]; a meet on 09-14 lies outside.

    Design: Difficulty/resource_temporal_overlap/proctor_buffered_interval_overlap
    """
    ctx, tournament, _, meet14 = _setup_proctor_overlap(api)
    created = validate_success(
        api.create_proctor_assignment(
            create_proctor_assignment_payload(ctx["coach_a"]["id"], "MEET", meet_id=meet14["id"]),
            ADMIN,
        ),
        201,
    )
    assert created["status"] == "ASSIGNED"
    assert created["coach_id"] == ctx["coach_a"]["id"]

def test_no_show_on_assigned_rejected(api, federation_admin_headers):
    """PRD §3.8: "When a confirmed proctor fails to appear, the administrator marks the
    assignment `NO_SHOW`, a transition permitted only from `CONFIRMED`."
    PRD §2.10 rung 8 lists `ERR_ASSIGNMENT_INVALID_STATE` among the per-entity state
    errors (HTTP 409).

    Design: Corner/errors/no_show_on_assigned_rejected
    """
    ctx = setup_two_club_league()
    meet = create_meet(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_b"]["id"],
                       "2026-09-05")
    assignment = validate_success(
        api.create_proctor_assignment(
            create_proctor_assignment_payload(ctx["coach_a"]["id"], "MEET", meet_id=meet["id"]),
            ADMIN,
        ),
        201,
    )
    assert assignment["status"] == "ASSIGNED"
    res = api.mark_no_show(assignment["id"], federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE)

def test_rbac_proctor_confirm_others_assignment_forbidden(api):
    """PRD §3.8: "The assigned coach confirms their own duty: acting with the `Proctor`
    role, their `X-User-ID` must equal the assignment's `coach_id` (otherwise
    `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`) and the assignment must be `ASSIGNED` (state
    checked first, `ERR_ASSIGNMENT_INVALID_STATE`); confirmation moves it to
    `CONFIRMED`."

    Design: Corner/rbac/rbac_proctor_confirm_others_assignment_forbidden
    """
    ctx = setup_two_club_league()
    meet = create_meet(ctx["season"]["id"], ctx["club_a"]["id"], ctx["club_b"]["id"],
                       "2026-09-05")
    assignment = validate_success(
        api.create_proctor_assignment(
            create_proctor_assignment_payload(ctx["coach_a"]["id"], "MEET", meet_id=meet["id"]),
            ADMIN,
        ),
        201,
    )
    # A different coach (club B) tries to confirm coach A's assignment.
    res = api.confirm_proctor_assignment(
        assignment["id"], make_proctor_headers(ctx["coach_b"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_RESOURCE_OWNERSHIP)

# ─── Bid generation helpers ──

def _farm_and_finalize(ctx, plan):
    """Award check-in points per plan, then move the season to FINALIZING."""
    farm_checkin_points(ctx["season"]["id"], plan)
    finalize_season(ctx["season"]["id"])

def test_bid_accept_requires_season_active_or_finalizing(api, federation_admin_headers):
    """PRD §3.9: "Acceptance requires the bid to be `OFFERED` (state checked first,
    `ERR_BID_INVALID_STATE`), the bid's season to be `ACTIVE` or `FINALIZING`
    (`ERR_SEASON_INVALID_STATE`), and the coach to belong to the bid's club
    (`ERR_FORBIDDEN_RESOURCE_OWNERSHIP`); the bid becomes `ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/bid_accept_requires_season_active_or_finalizing
    """
    ctx = setup_one_club(season_overrides={"state_bid_slots_per_region": 1},
                         num_players=1)
    player = ctx["players"][0]
    _farm_and_finalize(ctx, [(player["id"], ctx["coach"]["id"], 3)])  # 6 points
    finalize_standings(ctx["season"]["id"])
    generate_bids(ctx["season"]["id"])
    bid = list_bids({"season_id": ctx["season"]["id"], "player_id": player["id"]})[0]
    assert bid["status"] == "OFFERED"

    validate_success(api.complete_season(ctx["season"]["id"], federation_admin_headers))
    res = api.accept_bid(bid["id"], make_club_coach_headers(ctx["coach"]["id"]))
    validate_error(res, ApiErrorId.ERR_SEASON_INVALID_STATE)

def test_bid_accept_rejection_keeps_bid_offered(api, federation_admin_headers):
    """PRD §3.9: "Acceptance requires the bid to be `OFFERED` (state checked first,
    `ERR_BID_INVALID_STATE`), the bid's season to be `ACTIVE` or `FINALIZING`
    (`ERR_SEASON_INVALID_STATE`)". A rejected accept mutates nothing.

    Design: Difficulty/cross_entity_state_dependency/bid_accept_requires_season_active_or_finalizing
    """
    ctx = setup_one_club(season_overrides={"state_bid_slots_per_region": 1},
                         num_players=1)
    player = ctx["players"][0]
    _farm_and_finalize(ctx, [(player["id"], ctx["coach"]["id"], 3)])
    finalize_standings(ctx["season"]["id"])
    generate_bids(ctx["season"]["id"])
    bid = list_bids({"season_id": ctx["season"]["id"], "player_id": player["id"]})[0]

    validate_success(api.complete_season(ctx["season"]["id"], federation_admin_headers))
    validate_error(
        api.accept_bid(bid["id"], make_club_coach_headers(ctx["coach"]["id"])),
        ApiErrorId.ERR_SEASON_INVALID_STATE,
    )
    after = validate_success(api.get_bid(bid["id"], federation_admin_headers))
    assert after["status"] == "OFFERED"

# ─── Clock-sweep promotion cascade (queue A) ──

def _expiry_cascade_ctx():
    """Region NE, slots 1: P1 (club A) 9 points via a 3-round sweep, P2 (club B) 6
    points via three check-ins, P3 (club B) 0. Season FINALIZING with bids generated
    at the default clock (deadline 2026-08-08)."""
    ctx = setup_two_club_league(
        season_overrides={"state_bid_slots_per_region": 1},
        players_a=[{"grade_level": 11}],
        players_b=[{"grade_level": 10}, {"grade_level": 9}],
    )
    p1, p2, p3 = ctx["players_a"][0], ctx["players_b"][0], ctx["players_b"][1]
    farm_meet_wins(ctx["season"]["id"], ctx["club_a"], ctx["coach_a"],
                   ctx["club_b"], ctx["coach_b"], p1["id"], p3["id"], 3)
    farm_checkin_points(ctx["season"]["id"], [(p2["id"], ctx["coach_b"]["id"], 3)])
    finalize_season(ctx["season"]["id"])
    bids = generate_bids(ctx["season"]["id"])
    return ctx, p1, p2, p3, bids

def test_bid_expiry_sweeps_and_promotes(api, federation_admin_headers):
    """PRD §2.5: "Advancing the clock runs a housekeeping sweep: every qualification
    bid still in `OFFERED` whose `offer_deadline` is strictly earlier than the new
    clock reading becomes `EXPIRED`, and each expired individual bid triggers the
    promotion cascade described in §3.9."
    PRD §3.9: "the system promotes the single highest-ranked player in the same region
    who satisfies the full eligibility filter and has no `INDIVIDUAL_STATE` bid for the
    season in any status — `OFFERED`, `ACCEPTED`, `DECLINED`, and `EXPIRED` all exclude
    — creating them a fresh `OFFERED` bid, or creating nothing when the pool is empty."
    PRD §3.9: "Every generated bid begins `OFFERED` with an `offer_deadline` exactly
    seven days after the logical clock".

    Design: Difficulty/transitive_cascade/bid_expiry_promotion_cascade
    """
    ctx, p1, p2, p3, _ = _expiry_cascade_ctx()
    validate_success(
        api.set_clock({"to_iso8601": "2026-08-09T00:00:00Z"}, federation_admin_headers)
    )

    p1_bids = list_bids({"season_id": ctx["season"]["id"], "player_id": p1["id"]})
    assert p1_bids[0]["status"] == "EXPIRED", "deadline 2026-08-08 < new clock 2026-08-09"

    p2_bids = list_bids({"season_id": ctx["season"]["id"], "player_id": p2["id"]})
    assert len(p2_bids) == 1, "promotion offers the next-ranked eligible player"
    assert p2_bids[0]["status"] == "OFFERED"
    assert p2_bids[0]["bid_type"] == "INDIVIDUAL_STATE"
    assert parse_iso_instant(p2_bids[0]["offer_deadline"]) == datetime(
        2026, 8, 16, tzinfo=timezone.utc
    ), "fresh deadline is the new clock plus seven days"

def test_bid_expiry_team_bid_not_promoted_and_ineligible_skipped(api):
    """PRD §2.5: "each expired individual bid triggers the promotion cascade described
    in §3.9" — only individual bids promote. PRD §3.9: eligibility requires
    "their `performance_points` have reached at least 6".

    Design: Difficulty/transitive_cascade/bid_expiry_promotion_cascade
    """
    ctx, p1, p2, p3, _ = _expiry_cascade_ctx()
    validate_success(api.set_clock({"to_iso8601": "2026-08-09T00:00:00Z"}, ADMIN))

    team_bids = list_bids({"season_id": ctx["season"]["id"], "bid_type": "TEAM_STATE"})
    assert len(team_bids) == 1, "no promotion bid spawns for a team bid"
    assert team_bids[0]["status"] == "EXPIRED"
    assert team_bids[0]["club_id"] == ctx["club_a"]["id"]

    p3_bids = list_bids({"season_id": ctx["season"]["id"], "player_id": p3["id"]})
    assert p3_bids == [], "0 points is below the eligibility floor of 6"

# ─── Queue B bid claims ──

def test_bid_decline_after_accept_rejected(api, federation_admin_headers):
    """PRD §3.9: "Declining requires the same `OFFERED` state and ownership checks and
    moves the bid to `DECLINED`" — an already-ACCEPTED bid is not OFFERED, so the
    decline fails with `ERR_BID_INVALID_STATE`.

    Design: Corner/errors/bid_decline_after_accept_rejected
    """
    ctx = setup_one_club(season_overrides={"state_bid_slots_per_region": 1},
                         num_players=1)
    player = ctx["players"][0]
    _farm_and_finalize(ctx, [(player["id"], ctx["coach"]["id"], 3)])
    generate_bids(ctx["season"]["id"])
    bid = list_bids({"season_id": ctx["season"]["id"], "player_id": player["id"]})[0]

    accepted = validate_success(
        api.accept_bid(bid["id"], make_club_coach_headers(ctx["coach"]["id"]))
    )
    assert accepted["status"] == "ACCEPTED"
    res = api.decline_bid(bid["id"], make_club_coach_headers(ctx["coach"]["id"]))
    validate_error(res, ApiErrorId.ERR_BID_INVALID_STATE)
    after = validate_success(api.get_bid(bid["id"], federation_admin_headers))
    assert after["status"] == "ACCEPTED"

def test_bid_points_threshold_boundary(api):
    """PRD §3.9: "a player is eligible when they are `ACTIVE`, their club is not
    `SUSPENDED`, their membership for the season is `PAID` or `WAIVED`, their
    `performance_points` have reached at least 6, and they hold no existing bid for the
    season in `OFFERED` or `ACCEPTED`."

    Design: Corner/calculations/bid_points_threshold_boundary
    """
    ctx = setup_two_club_league(
        season_overrides={"state_bid_slots_per_region": 2},
        players_a=[{"grade_level": 11}, {"grade_level": 10}],
        players_b=[{"grade_level": 9}],
    )
    p5, p6, px = ctx["players_a"][0], ctx["players_a"][1], ctx["players_b"][0]
    # P5: one confirmed win (3 points) + one check-in (2) = 5 — one short.
    farm_meet_wins(ctx["season"]["id"], ctx["club_a"], ctx["coach_a"],
                   ctx["club_b"], ctx["coach_b"], p5["id"], px["id"], 1, complete=False)
    farm_checkin_points(ctx["season"]["id"],
                        [(p5["id"], ctx["coach_a"]["id"], 1),
                         (p6["id"], ctx["coach_a"]["id"], 3)])
    finalize_season(ctx["season"]["id"])
    generate_bids(ctx["season"]["id"])

    p6_bids = list_bids({"season_id": ctx["season"]["id"], "player_id": p6["id"]})
    assert len(p6_bids) == 1 and p6_bids[0]["status"] == "OFFERED", "6 points qualifies"
    assert p6_bids[0]["bid_type"] == "INDIVIDUAL_STATE"

    p5_bids = list_bids({"season_id": ctx["season"]["id"], "player_id": p5["id"]})
    assert p5_bids == [], "5 points earns no bid even with a free slot"

    team_bids = list_bids({"season_id": ctx["season"]["id"], "bid_type": "TEAM_STATE"})
    assert len(team_bids) == 1
    assert team_bids[0]["club_id"] == ctx["club_a"]["id"], (
        "all standings metrics tie at zero; the final created_at tiebreak picks the "
        "earlier-registered club"
    )

def test_bid_selector_tiebreak_by_rating(api):
    """PRD §3.9: "The eligible pool is grouped by the club's `region_code`, ranked by a
    pinned order — `performance_points` descending, then `rating` descending, then
    `rated_games_played` descending, then the player's `created_at` ascending, with ids
    never used — and generation offers bids to the top `state_bid_slots_per_region`
    players of each region."

    Design: Corner/cross_cutting_layers/bid_selector_tiebreak_by_rating
    """
    season_ctx = setup_one_club(season_overrides={"state_bid_slots_per_region": 1},
                                num_players=0)
    season_id = season_ctx["season"]["id"]
    club = season_ctx["club"]
    coach = season_ctx["coach"]
    # P2 created FIRST so creation order cannot be the decider.
    p2 = create_player(club["id"], full_name="P2", grade_level=10,
                       initial_rating=1400, initial_rated_games=25)
    p1 = create_player(club["id"], full_name="P1", grade_level=11,
                       initial_rating=1500, initial_rated_games=25)
    create_waived_membership(p1["id"], season_id)
    create_waived_membership(p2["id"], season_id)
    farm_checkin_points(season_id, [(p1["id"], coach["id"], 3),
                                    (p2["id"], coach["id"], 3)])
    finalize_season(season_id)
    generate_bids(season_id)

    individual = list_bids({"season_id": season_id, "bid_type": "INDIVIDUAL_STATE"})
    assert len(individual) == 1, "one slot only"
    assert individual[0]["player_id"] == p1["id"], "points tie 6=6 broken by rating 1500 > 1400"
    assert individual[0]["status"] == "OFFERED"
    assert parse_iso_instant(individual[0]["offer_deadline"]) == datetime(
        2026, 8, 8, tzinfo=timezone.utc
    ), "deadline is the default clock 2026-08-01 plus seven days"

def test_bid_promotion_empty_pool(api):
    """PRD §3.9: "when a declined bid is `INDIVIDUAL_STATE`, the system promotes the
    single highest-ranked player in the same region who satisfies the full eligibility
    filter and has no `INDIVIDUAL_STATE` bid for the season in any status — `OFFERED`,
    `ACCEPTED`, `DECLINED`, and `EXPIRED` all exclude — creating them a fresh `OFFERED`
    bid, or creating nothing when the pool is empty."

    Design: Corner/cross_cutting_layers/bid_promotion_empty_pool
    """
    ctx = setup_one_club(season_overrides={"state_bid_slots_per_region": 1},
                         num_players=1)
    player = ctx["players"][0]
    _farm_and_finalize(ctx, [(player["id"], ctx["coach"]["id"], 3)])
    generate_bids(ctx["season"]["id"])
    bid = list_bids({"season_id": ctx["season"]["id"], "player_id": player["id"]})[0]

    declined = validate_success(
        api.decline_bid(bid["id"], make_club_coach_headers(ctx["coach"]["id"]))
    )
    assert declined["status"] == "DECLINED"

    open_bids = list_bids({"season_id": ctx["season"]["id"],
                           "bid_type": "INDIVIDUAL_STATE", "status": "OFFERED"})
    assert open_bids == [], "the DECLINED bid excludes P1; the empty pool yields no promotion"

def test_bids_generate_bulk_count(api):
    """PRD §3.9: "generation offers bids to the top `state_bid_slots_per_region`
    players of each region. For `TEAM_STATE` bids, generation offers one bid per region
    to the club ranked first by the standings cascade among that region's clubs. Every
    generated bid begins `OFFERED` with an `offer_deadline` exactly seven days after
    the logical clock; team and national bids carry no `player_id`."
    PRD §3.9: eligibility requires "they hold no existing bid for the season in
    `OFFERED` or `ACCEPTED`" — a repeated generate offers nothing new to already-
    offered players.

    Design: Corner/endpoints/bids_generate_bulk_count
    """
    ctx = setup_one_club(season_overrides={"state_bid_slots_per_region": 2},
                         num_players=0)
    season_id = ctx["season"]["id"]
    club, coach = ctx["club"], ctx["coach"]
    p1 = create_player(club["id"], full_name="P1", grade_level=11,
                       initial_rating=1500, initial_rated_games=25)
    p2 = create_player(club["id"], full_name="P2", grade_level=10,
                       initial_rating=1400, initial_rated_games=25)
    create_waived_membership(p1["id"], season_id)
    create_waived_membership(p2["id"], season_id)
    farm_checkin_points(season_id, [(p1["id"], coach["id"], 3),
                                    (p2["id"], coach["id"], 3)])
    finalize_season(season_id)

    first = generate_bids(season_id)
    assert len(first) == 3, "2 INDIVIDUAL_STATE + 1 TEAM_STATE in one call"
    individual = [b for b in first if b["bid_type"] == "INDIVIDUAL_STATE"]
    team = [b for b in first if b["bid_type"] == "TEAM_STATE"]
    assert len(individual) == 2
    assert {b["player_id"] for b in individual} == {p1["id"], p2["id"]}
    assert len(team) == 1 and team[0]["club_id"] == club["id"]
    assert team[0].get("player_id") is None, "team bids carry no player_id"
    for bid in first:
        assert bid["status"] == "OFFERED"
        assert parse_iso_instant(bid["offer_deadline"]) == datetime(
            2026, 8, 8, tzinfo=timezone.utc
        )

    second = generate_bids(season_id)
    assert [b for b in second if b["bid_type"] == "INDIVIDUAL_STATE"] == [], (
        "already-OFFERED players are skipped on regeneration"
    )
    assert len(list_bids({"season_id": season_id, "bid_type": "INDIVIDUAL_STATE"})) == 2
