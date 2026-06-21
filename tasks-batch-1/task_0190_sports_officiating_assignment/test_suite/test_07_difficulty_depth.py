"""Second-coverage tests for every difficulty-design instance.

Each test below targets the SAME difficulty instance as a test in test_02–test_06
but from a distinct, complementary angle (the other side of a boundary, an
alternate branch, a multi-entity variant, or an intermediate conserved state) so
that every difficulty-design instance carries at least two tests. All assertions remain
uniquely derivable from verbatim PRD prose.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    create_league_payload, create_game_payload, create_crew_slot_payload,
    create_evaluation_payload, create_appeal_payload, update_official_payload,
    TEST_USERS, make_official_headers,
    create_league, create_official, create_wide_availability,
    offer_slot, accept_assignment, decline_assignment,
    current_game_version, set_clock, lock_game, settle_game, get_season_ledger,
    setup_open_game_with_slot, setup_offered_assignment, setup_accepted_assignment,
    setup_locked_game, setup_two_slot_open_game, make_postseason_eligible,
)

ADMIN = TEST_USERS["league_admin_headers"]
ASSIGNOR = TEST_USERS["assignor_headers"]
EVALUATOR = TEST_USERS["evaluator_headers"]


# ─── dual_variant_calc ───────────────────────────────────────────────────────

def test_provisional_vs_final_diverge_rookie_to_certified(api):
    """PRD §3.5: "First, a rank multiplier is selected by the official's `rank`:
    `ROOKIE` maps to 1.0, `CERTIFIED` to 1.25, `SENIOR` to 1.5, and `MASTER` to
    2.0."
    PRD §3.9: "The `final_pay_cents` is computed at settlement and, unlike the
    provisional estimate, reads the official's rank as of settlement time."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_pay_diverge_on_rank_promotion
    """
    league = create_league(sport="HOCKEY", base_game_fee_cents=10000,
                           mileage_rate_cents_per_mile=0)
    official = create_official(league["id"], rank="ROOKIE")
    create_wide_availability(official["id"])
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(league["id"]), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    asg = offer_slot(slot["id"], official["id"], game["id"])
    assert asg["provisional_pay_cents"] == 10000  # ROOKIE base 10000 * 1.0
    accept_assignment(asg["id"], official["id"], game["id"])
    ov1 = validate_success(api.get_official(official["id"], ADMIN), 200)["version"]
    validate_success(api.update_official(
        official["id"], update_official_payload(ov1, rank="CERTIFIED"), ADMIN), 200)
    lock_game(game["id"])
    set_clock("2026-06-20T19:00:00Z")
    settle_game(game["id"])
    settled = validate_success(api.get_assignment(asg["id"], ASSIGNOR), 200)
    assert settled["provisional_pay_cents"] == 10000
    assert settled["final_pay_cents"] == 12500  # CERTIFIED base 10000 * 1.25 at settle
    assert settled["final_pay_cents"] != settled["provisional_pay_cents"]


def test_eligibility_round_per_item_single_score(api):
    """PRD §3.11: "first each individual evaluation `score` (over the official's
    completed-assignment evaluations) is rounded half-up to two decimal places,
    then the arithmetic mean of those rounded values is taken, and that mean is
    rounded half-up to two decimal places."
    PRD §3.12: "their `mean_rating` is not null and is at least the league's
    `postseason_min_rating`".

    Design: Difficulty/dual_variant_calc/eligibility_round_first_vs_average_first_flip
    """
    league = create_league(sport="SOCCER", base_game_fee_cents=10000,
                           mileage_rate_cents_per_mile=0,
                           postseason_min_games=1, postseason_min_rating=3.35,
                           postseason_max_noshows=0)
    official = create_official(league["id"], rank="SENIOR")
    create_wide_availability(official["id"])
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(
        league["id"], start_utc="2026-06-10T18:00:00Z"), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="REFEREE"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    asg = offer_slot(slot["id"], official["id"], game["id"])
    accept_assignment(asg["id"], official["id"], game["id"])
    lock_game(game["id"])
    set_clock("2026-06-10T20:30:00Z")
    settle_game(game["id"])
    # Single score 3.345 -> rounded per item to 3.35; mean of one item -> 3.35.
    validate_success(api.create_evaluation(
        asg["id"], create_evaluation_payload(3.345), EVALUATOR), 201)
    elig = validate_success(api.get_official_eligibility(official["id"], ADMIN), 200)
    assert elig["mean_rating"] == 3.35
    assert elig["postseason_eligible"] is True


# ─── combinatorial_formula ───────────────────────────────────────────────────

def test_decline_penalty_standard_tier_regular_game(api):
    """PRD §3.8: "A base penalty is chosen by lead time: if fewer than 24 hours
    remain, the base is 8 points (a late decline); otherwise if fewer than 72 hours
    remain, the base is 4 points; otherwise the base is 1 point."
    PRD §3.8: "The base plus escalation is then multiplied by a postseason factor of
    2.0 if the game is postseason (otherwise by 1.0), and the result is rounded
    half-up to whole points."

    Design: Difficulty/combinatorial_formula/decline_penalty_nonlinear_leadtime_escalation_postseason
    """
    league = create_league(sport="HOCKEY")
    official = create_official(league["id"], rank="ROOKIE")
    create_wide_availability(official["id"])
    set_clock("2026-06-01T00:00:00Z")  # 19 days before start => standard tier (>=72h)
    game = validate_success(api.create_game(create_game_payload(
        league["id"], start_utc="2026-06-20T18:00:00Z"), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    asg = offer_slot(slot["id"], official["id"], game["id"])
    declined = validate_success(api.decline_assignment(
        asg["id"], make_official_headers(official["id"])), 200)
    # (base 1 + escalation 0) * 1.0 (regular) = 1.
    assert declined["penalty_assessed_points"] == 1


def test_provisional_uplift_before_mileage_with_mileage(api):
    """PRD §3.5: "If the game's `is_postseason` flag is set, this game pay is then
    multiplied by a postseason uplift factor of 1.20 and again rounded half-up to
    whole cents — the uplift is applied to the game pay before mileage is added.
    Finally, the mileage component (the rounded-to-whole-mile `distance_miles`
    multiplied by `mileage_rate_cents_per_mile`) is added to the game pay to yield
    `provisional_pay_cents`."

    Design: Difficulty/combinatorial_formula/provisional_pay_postseason_uplift_before_mileage_order
    """
    league = create_league(sport="BASKETBALL", base_game_fee_cents=10000,
                           mileage_rate_cents_per_mile=100,
                           postseason_min_games=0, postseason_min_rating=0,
                           postseason_max_noshows=99)
    official = create_official(league["id"], rank="SENIOR", max_travel_miles=50)
    create_wide_availability(official["id"])
    # PRD §3.4 rule 7 + §3.12: postseason offer requires postseason_eligible, which
    # requires a non-null mean_rating; work one regular-season home game (distance 0,
    # so no mileage side effect) + evaluation before the postseason offer.
    make_postseason_eligible(league, official)
    set_clock("2026-06-01T00:00:00Z")
    # Venue (40.10,-75.0) ~6.9mi from home; round(6.9)=7 miles * 100c = 700 mileage.
    game = validate_success(api.create_game(create_game_payload(
        league["id"], venue_lat=40.10, venue_lon=-75.0, is_postseason=True), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="REFEREE"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    gv = current_game_version(game["id"])
    asg = validate_success(api.offer_crew_slot(
        slot["id"], {"official_id": official["id"], "expected_game_version": gv}, ASSIGNOR), 201)
    # SENIOR 10000*1.5=15000, *1.20=18000 game pay, THEN + 700 mileage = 18700.
    assert asg["mileage_cents"] == 700
    assert asg["provisional_pay_cents"] == 18700


# ─── non_linear_state_machine ────────────────────────────────────────────────

def test_crewslot_returns_vacant_and_null_pointer_after_decline(api):
    """PRD §3.6: "The slot then returns from `OFFERED` to `VACANT`, its
    `current_assignment_id` is cleared, and it becomes offerable again — the cyclic
    re-offer loop that lets a slot be put back on the market."

    Design: Difficulty/non_linear_state_machine/crewslot_cyclic_reoffer_after_decline
    """
    ctx = setup_offered_assignment()
    decline_assignment(ctx["assignment"]["id"], ctx["official"]["id"])
    slot_after = validate_success(api.get_crew_slot(ctx["slot"]["id"], ASSIGNOR), 200)
    assert slot_after["status"] == "VACANT"
    assert slot_after["current_assignment_id"] is None


def test_game_open_bubbles_to_staffed_on_accept(api):
    """PRD §2.5: "if that count reaches the game's `required_crew_size` — the game
    automatically advances from `OPEN` to `STAFFED` without any explicit request on
    the game itself."

    Design: Difficulty/non_linear_state_machine/game_parallel_dimensions_staffed_bubbles_open_on_withdraw
    """
    ctx = setup_offered_assignment()
    before = validate_success(api.get_game(ctx["game"]["id"], ASSIGNOR), 200)
    assert before["status"] == "OPEN"
    accept_assignment(ctx["assignment"]["id"], ctx["official"]["id"], ctx["game"]["id"])
    after = validate_success(api.get_game(ctx["game"]["id"], ASSIGNOR), 200)
    assert after["status"] == "STAFFED"
    assert after["crew_filled_count"] == 1


# ─── transitive_cascade ──────────────────────────────────────────────────────

def test_noshow_on_locked_game_stays_locked_with_vacant_slot(api):
    """PRD §3.7: "The slot returns to `VACANT` and `crew_filled_count` is
    recomputed; if the game was `STAFFED` it may bubble back to `OPEN`, whereas a
    `LOCKED` game simply remains `LOCKED` carrying a now-vacant slot."

    Design: Difficulty/transitive_cascade/noshow_cascade_assignment_slot_game_depth3
    """
    ctx = setup_locked_game(position="ASSISTANT", official_overrides={})  # ROOKIE on ASSISTANT
    set_clock("2026-06-20T19:00:00Z")  # past start so no-show is permitted
    no_show = validate_success(api.no_show_assignment(ctx["assignment"]["id"], ASSIGNOR), 200)
    assert no_show["status"] == "NO_SHOW"
    slot_after = validate_success(api.get_crew_slot(ctx["slot"]["id"], ASSIGNOR), 200)
    assert slot_after["status"] == "VACANT"
    game_after = validate_success(api.get_game(ctx["game"]["id"], ASSIGNOR), 200)
    assert game_after["status"] == "LOCKED"
    assert game_after["crew_filled_count"] == 0


def test_game_cancel_cascade_releases_offered_slot(api):
    """PRD §3.10: "Cancellation drives the game to `CANCELLED`, moves every
    non-terminal assignment on the game to `CANCELLED` with no penalty assessed,
    releases every crew slot to `RELEASED`".

    Design: Difficulty/transitive_cascade/game_cancel_cascade_slot_and_assignment_depth2
    """
    ctx = setup_offered_assignment()  # slot OFFERED (not FILLED), live assignment OFFERED
    cancelled = validate_success(api.cancel_game(ctx["game"]["id"], ASSIGNOR), 200)
    assert cancelled["status"] == "CANCELLED"
    slot_after = validate_success(api.get_crew_slot(ctx["slot"]["id"], ASSIGNOR), 200)
    assert slot_after["status"] == "RELEASED"
    asg_after = validate_success(api.get_assignment(ctx["assignment"]["id"], ASSIGNOR), 200)
    assert asg_after["status"] == "CANCELLED"
    assert asg_after["penalty_assessed_points"] == 0


# ─── resource_temporal_overlap ───────────────────────────────────────────────

def test_double_book_touching_at_endpoint_allowed(api):
    """PRD §3.4 (step 5): "**Double-booking.** The game's interval must not overlap
    the interval of any other game on which this official already holds an `OFFERED`
    or `ACCEPTED` assignment; overlap is measured closed on the start and open on
    the end, so two games that merely touch at an endpoint do not conflict. A clash
    is rejected with `ERR_OFFICIAL_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/official_double_book_overlapping_games_strict_overlap
    """
    league = create_league(sport="SOCCER")
    official = create_official(league["id"], rank="ROOKIE")
    create_wide_availability(official["id"])
    set_clock("2026-06-01T00:00:00Z")
    # G1 [18:00,20:00) accepted; G2 [20:00,22:00) touches at the endpoint => allowed.
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
        start_utc="2026-06-20T20:00:00Z", duration_minutes=120), ASSIGNOR), 201)
    s2 = validate_success(api.create_crew_slot(
        g2["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    g2 = validate_success(api.open_game(g2["id"], ASSIGNOR), 200)
    gv = current_game_version(g2["id"])
    asg = validate_success(api.offer_crew_slot(
        s2["id"], {"official_id": official["id"], "expected_game_version": gv}, ASSIGNOR), 201)
    assert asg["status"] == "OFFERED"


def test_non_intersecting_blackout_allows_offer(api):
    """PRD §3.4 (step 4): "The game's occupied interval (from `start_utc` to
    `start_utc` plus `duration_minutes`, treated as half-open with the end excluded)
    must lie entirely inside at least one of the official's `ACTIVE` `AVAILABLE`
    windows and must not intersect any `ACTIVE` `BLACKOUT` window; otherwise the
    offer is rejected with `ERR_OUTSIDE_AVAILABILITY`."

    Design: Difficulty/resource_temporal_overlap/availability_blackout_intersection_semantics
    """
    league = create_league(sport="FOOTBALL")
    official = create_official(league["id"], rank="ROOKIE")
    # Wide AVAILABLE window; BLACKOUT [21:00,22:00) does NOT intersect game [18:00,20:00).
    validate_success(api.create_availability({
        "official_id": official["id"],
        "window_start_utc": "2026-06-20T00:00:00Z",
        "window_end_utc": "2026-06-21T00:00:00Z"},
        make_official_headers(official["id"])), 201)
    validate_success(api.create_availability({
        "official_id": official["id"],
        "window_start_utc": "2026-06-20T21:00:00Z",
        "window_end_utc": "2026-06-20T22:00:00Z",
        "kind": "BLACKOUT"},
        make_official_headers(official["id"])), 201)
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(
        league["id"], start_utc="2026-06-20T18:00:00Z", duration_minutes=120), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    gv = current_game_version(game["id"])
    asg = validate_success(api.offer_crew_slot(
        slot["id"], {"official_id": official["id"], "expected_game_version": gv}, ASSIGNOR), 201)
    assert asg["status"] == "OFFERED"


# ─── priority_pair_validation_conflict ───────────────────────────────────────

def test_travel_radius_fires_when_rank_passes(api):
    """PRD §3.4 (step 2): "**Rank eligibility.** If the slot's `position` is
    `REFEREE`, the official's `rank` must be `SENIOR` or `MASTER`; a lower rank is
    rejected with `ERR_RANK_INELIGIBLE`."
    PRD §3.4 (step 6): "**Travel radius.** The great-circle distance between the
    official's home location and the game's venue must be at most the official's
    `max_travel_miles`; a longer trip is rejected with `ERR_OUTSIDE_TRAVEL_RADIUS`."

    Design: Difficulty/priority_pair_validation_conflict/rank_ineligible_beats_travel_radius
    """
    league = create_league(sport="BASKETBALL")
    official = create_official(league["id"], rank="SENIOR", max_travel_miles=50)  # rank OK
    create_wide_availability(official["id"])
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(
        league["id"], venue_lat=41.0, venue_lon=-75.0), ASSIGNOR), 201)  # ~69mi > 50
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="REFEREE"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    gv = current_game_version(game["id"])
    res = api.offer_crew_slot(
        slot["id"], {"official_id": official["id"], "expected_game_version": gv}, ASSIGNOR)
    validate_error(res, "ERR_OUTSIDE_TRAVEL_RADIUS", expected_status=422)


def test_availability_fires_when_no_conflict(api):
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
    official = create_official(league["id"], rank="SENIOR")  # no conflict declared
    # No availability window => availability cover fails, COI passes.
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(league["id"]), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="REFEREE"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    gv = current_game_version(game["id"])
    res = api.offer_crew_slot(
        slot["id"], {"official_id": official["id"], "expected_game_version": gv}, ASSIGNOR)
    validate_error(res, "ERR_OUTSIDE_AVAILABILITY", expected_status=422)


# ─── boundary_precision_check (travel / availability / OCC / crew size) ───────

def test_travel_radius_beyond_max_rejected(api):
    """PRD §3.4 (step 6): "**Travel radius.** The great-circle distance between the
    official's home location and the game's venue must be at most the official's
    `max_travel_miles`; a longer trip is rejected with `ERR_OUTSIDE_TRAVEL_RADIUS`."

    Design: Difficulty/boundary_precision_check/travel_radius_dist_zero_inclusive_succeeds
    """
    league = create_league(sport="BASKETBALL")
    official = create_official(league["id"], rank="ROOKIE", max_travel_miles=50)
    create_wide_availability(official["id"])
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(
        league["id"], venue_lat=41.0, venue_lon=-75.0), ASSIGNOR), 201)  # ~69mi > 50
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    gv = current_game_version(game["id"])
    res = api.offer_crew_slot(
        slot["id"], {"official_id": official["id"], "expected_game_version": gv}, ASSIGNOR)
    validate_error(res, "ERR_OUTSIDE_TRAVEL_RADIUS", expected_status=422)


def test_availability_interval_strictly_inside_window_succeeds(api):
    """PRD §3.4 (step 4): "The game's occupied interval (from `start_utc` to
    `start_utc` plus `duration_minutes`, treated as half-open with the end excluded)
    must lie entirely inside at least one of the official's `ACTIVE` `AVAILABLE`
    windows and must not intersect any `ACTIVE` `BLACKOUT` window; otherwise the
    offer is rejected with `ERR_OUTSIDE_AVAILABILITY`."

    Design: Difficulty/boundary_precision_check/availability_end_exclusive_zero_gap_boundary
    """
    league = create_league(sport="HOCKEY")
    official = create_official(league["id"], rank="ROOKIE")
    # Window [18:00,20:00); game [18:00,19:00) duration 60 ends strictly before end.
    validate_success(api.create_availability({
        "official_id": official["id"],
        "window_start_utc": "2026-06-20T18:00:00Z",
        "window_end_utc": "2026-06-20T20:00:00Z"},
        make_official_headers(official["id"])), 201)
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(
        league["id"], start_utc="2026-06-20T18:00:00Z", duration_minutes=60), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    gv = current_game_version(game["id"])
    asg = validate_success(api.offer_crew_slot(
        slot["id"], {"official_id": official["id"], "expected_game_version": gv}, ASSIGNOR), 201)
    assert asg["status"] == "OFFERED"


def test_fresh_game_version_on_second_offer_succeeds(api):
    """PRD §2.6: "Two write operations participate in this protection, and both
    require the caller to submit an `expected_game_version` field carrying the game
    version the caller last observed."

    Design: Difficulty/boundary_precision_check/stale_game_version_on_offer_rejected_412
    """
    ctx = setup_two_slot_open_game()
    a1 = offer_slot(ctx["slot1"]["id"], ctx["official_a"]["id"], ctx["game"]["id"])
    accept_assignment(a1["id"], ctx["official_a"]["id"], ctx["game"]["id"])  # bumps version
    # Re-read the fresh version; second offer with the matched version succeeds.
    gv = current_game_version(ctx["game"]["id"])
    asg = validate_success(api.offer_crew_slot(
        ctx["slot2"]["id"],
        {"official_id": ctx["official_b"]["id"], "expected_game_version": gv}, ASSIGNOR), 201)
    assert asg["status"] == "OFFERED"


def test_minimum_required_crew_size_one_accepted(api):
    """PRD §3.3: "The crew size is given by `required_crew_size`, which must be at
    least 1."

    Design: Difficulty/boundary_precision_check/zero_required_crew_size_rejected_invalid_request
    """
    league = create_league(sport="BASKETBALL")
    game = validate_success(api.create_game(
        create_game_payload(league["id"], required_crew_size=1), ASSIGNOR), 201)
    assert game["required_crew_size"] == 1
    assert game["status"] == "DRAFT"


# ─── compensating_invariant ──────────────────────────────────────────────────

def test_decline_leaves_crew_count_zero_before_reoffer(api):
    """PRD §3.6: "The slot then returns from `OFFERED` to `VACANT`, its
    `current_assignment_id` is cleared, and it becomes offerable again — the cyclic
    re-offer loop that lets a slot be put back on the market."
    PRD §2.5: "When an official accepts an offer, the slot becomes filled, the owning
    game's `crew_filled_count` is recomputed, and — if that count reaches the game's
    `required_crew_size` — the game automatically advances from `OPEN` to `STAFFED`
    without any explicit request on the game itself."

    Design: Difficulty/compensating_invariant/decline_then_reoffer_accept_conserves_crew_count
    """
    ctx = setup_offered_assignment()
    decline_assignment(ctx["assignment"]["id"], ctx["official"]["id"])
    game_after = validate_success(api.get_game(ctx["game"]["id"], ASSIGNOR), 200)
    assert game_after["crew_filled_count"] == 0  # compensating leg leaves count at 0
    assert game_after["status"] == "OPEN"


def test_settle_conserves_pay_across_two_officials(api):
    """PRD §3.9: "each official's `SeasonLedger.total_pay_accrued_cents` increases by
    the sum of their settled `final_pay_cents`".
    PRD §3.9: "after settlement, `settlement_total_cents` is the sum of
    `final_pay_cents` over the game's completed assignments."

    Design: Difficulty/compensating_invariant/settle_conserves_pay_ledger_equals_sum_of_final_pay
    """
    ctx = setup_two_slot_open_game()  # two ROOKIE officials, 2-slot game
    league, game = ctx["league"], ctx["game"]
    oa, ob = ctx["official_a"], ctx["official_b"]
    a1 = offer_slot(ctx["slot1"]["id"], oa["id"], game["id"])
    accept_assignment(a1["id"], oa["id"], game["id"])
    a2 = offer_slot(ctx["slot2"]["id"], ob["id"], game["id"])
    accept_assignment(a2["id"], ob["id"], game["id"])  # game now STAFFED
    lock_game(game["id"])
    set_clock("2026-06-20T19:00:00Z")
    settled_game = settle_game(game["id"])
    a1s = validate_success(api.get_assignment(a1["id"], ASSIGNOR), 200)
    a2s = validate_success(api.get_assignment(a2["id"], ASSIGNOR), 200)
    assert a1s["final_pay_cents"] == 10000  # ROOKIE base 10000 * 1.0, mileage 0
    assert a2s["final_pay_cents"] == 10000
    assert settled_game["settlement_total_cents"] == 20000
    la = get_season_ledger(league["id"], oa["id"])
    lb = get_season_ledger(league["id"], ob["id"])
    assert la["total_pay_accrued_cents"] == 10000
    assert lb["total_pay_accrued_cents"] == 10000


def test_appeal_upheld_noshow_restores_noshow_count(api):
    """PRD §3.13: "Upholding sets `reversed_points` to the appealed assignment's
    `penalty_assessed_points`, subtracts that figure from the official's
    `SeasonLedger.penalty_points` (floored at 0)".
    PRD §3.13: "If the appealed assignment was a `NO_SHOW`, the official's
    `noshow_count` is also recomputed excluding that assignment, which can in turn
    change `postseason_eligible`".

    Design: Difficulty/compensating_invariant/appeal_upheld_conserves_penalty_points_ledger
    """
    ctx = setup_locked_game(position="ASSISTANT", official_overrides={})  # ROOKIE
    league, official, asg = ctx["league"], ctx["official"], ctx["assignment"]
    set_clock("2026-06-20T19:00:00Z")  # past start
    no_show = validate_success(api.no_show_assignment(asg["id"], ASSIGNOR), 200)
    assert no_show["penalty_assessed_points"] == 15  # base 15, regular game
    before = validate_success(api.get_official(official["id"], ADMIN), 200)
    assert before["noshow_count"] == 1
    appeal = validate_success(api.create_appeal(
        asg["id"], create_appeal_payload(reason="documented emergency"),
        make_official_headers(official["id"])), 201)
    upheld = validate_success(api.uphold_appeal(appeal["id"], ADMIN), 200)
    assert upheld["reversed_points"] == 15
    ledger = get_season_ledger(league["id"], official["id"])
    assert ledger["penalty_points"] == 0
    after = validate_success(api.get_official(official["id"], ADMIN), 200)
    assert after["noshow_count"] == 0  # recomputed excluding the appealed no-show
