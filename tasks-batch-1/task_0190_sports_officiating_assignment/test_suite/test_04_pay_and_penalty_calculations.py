"""Pay and penalty calculations: provisional vs finalized divergence, postseason
uplift ordering, mileage, reliability deduction, decline-penalty non-linearity,
and the round-per-item postseason-eligibility flip.

Each test translates exactly one design instance (Difficulty queue A or Corner queue B).
Literal expected values are copied verbatim from the design recipes.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_league_payload, create_official_payload, create_availability_payload,
    create_game_payload, create_crew_slot_payload, update_official_payload,
    create_evaluation_payload,
    TEST_USERS, make_official_headers,
    create_league, create_official, create_wide_availability,
    offer_slot, accept_assignment, current_game_version, set_clock, lock_game,
    setup_open_game_with_slot, make_postseason_eligible,
)

ADMIN = TEST_USERS["league_admin_headers"]
ASSIGNOR = TEST_USERS["assignor_headers"]
EVALUATOR = TEST_USERS["evaluator_headers"]


# ─── Dual-variant pay divergence (Difficulty) ────────────────────────────────

def test_provisional_vs_final_pay_diverge_on_rank_promotion(api):
    """PRD §3.5: "First, a rank multiplier is selected by the official's `rank`:
    `ROOKIE` maps to 1.0, `CERTIFIED` to 1.25, `SENIOR` to 1.5, and `MASTER` to
    2.0."
    PRD §3.5: "Because the rank multiplier here is read at offer time and frozen, an
    official who is promoted between the offer and settlement will see the
    provisional estimate diverge from the eventual settled figure; the provisional
    number deliberately reflects only what was known when the slot was offered."
    PRD §3.9: "The `final_pay_cents` is computed at settlement and, unlike the
    provisional estimate, reads the official's rank as of settlement time."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_pay_diverge_on_rank_promotion
    """
    league = create_league(sport="BASKETBALL", base_game_fee_cents=10000,
                           mileage_rate_cents_per_mile=50)
    official = create_official(league["id"], rank="CERTIFIED")
    create_wide_availability(official["id"])
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(
        league["id"], start_utc="2026-06-10T18:00:00Z"), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    asg = offer_slot(slot["id"], official["id"], game["id"])
    assert asg["provisional_pay_cents"] == 12500  # base 10000 * 1.25 CERTIFIED, dist 0
    accept_assignment(asg["id"], official["id"], game["id"])
    # Promote CERTIFIED -> SENIOR before lock/settle.
    ov1 = validate_success(api.get_official(official["id"], ADMIN), 200)["version"]
    validate_success(api.update_official(
        official["id"], update_official_payload(ov1, rank="SENIOR"), ADMIN), 200)
    lock_game(game["id"])
    set_clock("2026-06-10T20:30:00Z")
    gv = current_game_version(game["id"])
    validate_success(api.settle_game(game["id"], {"expected_game_version": gv}, ASSIGNOR), 200)
    settled = validate_success(api.get_assignment(asg["id"], ASSIGNOR), 200)
    assert settled["provisional_pay_cents"] == 12500
    assert settled["final_pay_cents"] == 15000  # base 10000 * 1.5 SENIOR at settle
    assert settled["final_pay_cents"] != settled["provisional_pay_cents"]


def test_eligibility_round_per_item_then_average_flip(api):
    """PRD §3.11: "first each individual evaluation `score` (over the official's
    completed-assignment evaluations) is rounded half-up to two decimal places,
    then the arithmetic mean of those rounded values is taken, and that mean is
    rounded half-up to two decimal places. This is round-per-item, then average,
    then round — not average-the-raw-scores-then-round."
    PRD §3.12: "their `mean_rating` is not null and is at least the league's
    `postseason_min_rating`".

    Design: Difficulty/dual_variant_calc/eligibility_round_first_vs_average_first_flip
    """
    league = create_league(sport="SOCCER", base_game_fee_cents=10000,
                           mileage_rate_cents_per_mile=0,
                           postseason_min_games=2, postseason_min_rating=3.35,
                           postseason_max_noshows=0)
    official = create_official(league["id"], rank="SENIOR")
    create_wide_availability(official["id"])

    def work_and_evaluate(home, away, start, settle_clock, score):
        set_clock("2026-06-01T00:00:00Z")
        game = validate_success(api.create_game(create_game_payload(
            league["id"], home_team=home, away_team=away, start_utc=start), ASSIGNOR), 201)
        slot = validate_success(api.create_crew_slot(
            game["id"], create_crew_slot_payload(position="REFEREE"), ASSIGNOR), 201)
        game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
        asg = offer_slot(slot["id"], official["id"], game["id"])
        accept_assignment(asg["id"], official["id"], game["id"])
        lock_game(game["id"])
        set_clock(settle_clock)
        gv = current_game_version(game["id"])
        validate_success(api.settle_game(game["id"], {"expected_game_version": gv}, ASSIGNOR), 200)
        validate_success(api.create_evaluation(
            asg["id"], create_evaluation_payload(score), EVALUATOR), 201)

    work_and_evaluate("H1", "A1", "2026-06-10T18:00:00Z", "2026-06-10T20:30:00Z", 3.335)
    work_and_evaluate("H2", "A2", "2026-06-12T18:00:00Z", "2026-06-12T20:30:00Z", 3.345)

    res = api.get_official_eligibility(official["id"], ADMIN)
    elig = validate_success(res, 200)
    # round-per-item: 3.335->3.34, 3.345->3.35; mean (3.34+3.35)/2=3.345 ->3.35.
    assert elig["mean_rating"] == 3.35
    assert elig["postseason_eligible"] is True


# ─── Combinatorial formula (Difficulty) ──────────────────────────────────────

def test_decline_penalty_late_postseason_nonlinear(api):
    """PRD §3.8: "A base penalty is chosen by lead time: if fewer than 24 hours
    remain, the base is 8 points (a late decline); otherwise if fewer than 72 hours
    remain, the base is 4 points; otherwise the base is 1 point."
    PRD §3.8: "An escalation is then added on top: it is the number of the
    official's prior penalised declines — that is, this official's terminal
    assignments carrying a positive `penalty_assessed_points` created before this
    one, ordered by `created_at` ascending — capped at 3, multiplied by 2 points
    each."
    PRD §3.8: "The base plus escalation is then multiplied by a postseason factor of
    2.0 if the game is postseason (otherwise by 1.0), and the result is rounded
    half-up to whole points."

    Design: Difficulty/combinatorial_formula/decline_penalty_nonlinear_leadtime_escalation_postseason
    """
    league = create_league(sport="HOCKEY", base_game_fee_cents=10000,
                           mileage_rate_cents_per_mile=0,
                           postseason_min_games=0, postseason_min_rating=0,
                           postseason_max_noshows=99)
    official = create_official(league["id"], rank="ROOKIE")
    create_wide_availability(official["id"])
    # PRD §3.4 rule 7 + §3.12: a postseason game's offer requires the candidate to
    # be postseason_eligible, which requires a non-null mean_rating; work one
    # regular-season game + evaluation to satisfy the gate before the postseason
    # offer. The completed game carries no penalty, so the decline escalation
    # (prior penalised declines) remains 0.
    make_postseason_eligible(league, official)
    set_clock("2026-06-10T16:00:00Z")  # 2h before start => late tier
    game = validate_success(api.create_game(create_game_payload(
        league["id"], start_utc="2026-06-10T18:00:00Z", is_postseason=True), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    asg = offer_slot(slot["id"], official["id"], game["id"])
    declined = validate_success(api.decline_assignment(
        asg["id"], make_official_headers(official["id"])), 200)
    # (base 8 + escalation 0) * postseason 2.0 = 16
    assert declined["penalty_assessed_points"] == 16
    assert declined["status"] == "DECLINED"


def test_provisional_postseason_uplift_before_mileage(api):
    """PRD §3.5: "The game pay is that base multiplied by the rank multiplier,
    rounded half-up to whole cents. If the game's `is_postseason` flag is set, this
    game pay is then multiplied by a postseason uplift factor of 1.20 and again
    rounded half-up to whole cents — the uplift is applied to the game pay before
    mileage is added."

    Design: Difficulty/combinatorial_formula/provisional_pay_postseason_uplift_before_mileage_order
    """
    league = create_league(sport="BASKETBALL", base_game_fee_cents=10000,
                           mileage_rate_cents_per_mile=0,
                           postseason_min_games=0, postseason_min_rating=0,
                           postseason_max_noshows=99)
    official = create_official(league["id"], rank="SENIOR")
    create_wide_availability(official["id"])
    # PRD §3.4 rule 7 + §3.12: postseason offer requires postseason_eligible, which
    # requires a non-null mean_rating; work one regular-season game + evaluation.
    make_postseason_eligible(league, official)
    set_clock("2026-06-01T00:00:00Z")
    game = validate_success(api.create_game(create_game_payload(
        league["id"], start_utc="2026-06-20T18:00:00Z", is_postseason=True), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="REFEREE"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    gv = current_game_version(game["id"])
    res = api.offer_crew_slot(
        slot["id"], {"official_id": official["id"], "expected_game_version": gv}, ASSIGNOR)
    asg = validate_success(res, 201)
    # SENIOR base 10000*1.5=15000, *1.20=18000, mileage 0 => 18000.
    assert asg["provisional_pay_cents"] == 18000


# ─── Calculation corner instances ────────────────────────────────────────────

def test_mileage_uses_rounded_distance_times_rate(api):
    """PRD §3.4: "The assignment's `mileage_cents` reimbursement is that distance
    rounded to the nearest whole mile (round-half-up) multiplied by the league's
    `mileage_rate_cents_per_mile`."
    PRD §3.5: "Finally, the mileage component (the rounded-to-whole-mile
    `distance_miles` multiplied by `mileage_rate_cents_per_mile`) is added to the
    game pay to yield `provisional_pay_cents`."

    Design: Corner/calculations/mileage_uses_rounded_distance_times_rate
    """
    league = create_league(sport="BASKETBALL", base_game_fee_cents=10000,
                           mileage_rate_cents_per_mile=100)
    official = create_official(league["id"], rank="ROOKIE", max_travel_miles=50)
    create_wide_availability(official["id"])
    set_clock("2026-06-01T00:00:00Z")
    # Venue (40.10, -75.0) ~6.9mi from home (40.0, -75.0); round(6.9)=7.
    game = validate_success(api.create_game(create_game_payload(
        league["id"], venue_lat=40.10, venue_lon=-75.0), ASSIGNOR), 201)
    slot = validate_success(api.create_crew_slot(
        game["id"], create_crew_slot_payload(position="ASSISTANT"), ASSIGNOR), 201)
    game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
    gv = current_game_version(game["id"])
    res = api.offer_crew_slot(
        slot["id"], {"official_id": official["id"], "expected_game_version": gv}, ASSIGNOR)
    asg = validate_success(res, 201)
    assert asg["mileage_cents"] == 700  # 7 miles * 100c/mi
    assert asg["provisional_pay_cents"] == 10700  # 10000 game pay + 700 mileage


def test_reliability_deduction_applied_at_settlement(api):
    """PRD §3.9: "Then a reliability deduction is applied that has no counterpart in
    the provisional estimate: if the official's `penalty_points` as of settlement is
    at least 10, the game pay is reduced to 90 percent of itself — that is,
    multiplied by the difference between one and a deduction fraction of 0.10 — and
    rounded half-up to whole cents."
    PRD §3.8: "if fewer than 24 hours remain, the base is 8 points (a late decline);
    otherwise if fewer than 72 hours remain, the base is 4 points; otherwise the
    base is 1 point."

    Design: Corner/calculations/reliability_deduction_applied_at_settlement_threshold
    """
    league = create_league(sport="BASKETBALL", base_game_fee_cents=10000,
                           mileage_rate_cents_per_mile=0)
    official = create_official(league["id"], rank="SENIOR")
    create_wide_availability(official["id"])

    def offer_and_decline(home, away, start, clock):
        set_clock(clock)
        game = validate_success(api.create_game(create_game_payload(
            league["id"], home_team=home, away_team=away, start_utc=start), ASSIGNOR), 201)
        slot = validate_success(api.create_crew_slot(
            game["id"], create_crew_slot_payload(position="REFEREE"), ASSIGNOR), 201)
        game = validate_success(api.open_game(game["id"], ASSIGNOR), 200)
        asg = offer_slot(slot["id"], official["id"], game["id"])
        validate_success(api.decline_assignment(
            asg["id"], make_official_headers(official["id"])), 200)

    # Decline 1: 96h out (standard tier) => 1pt.
    offer_and_decline("H1", "A1", "2026-06-20T14:00:00Z", "2026-06-16T14:00:00Z")
    # Decline 2: 2h out (late) prior=1 => 8 + min(1,3)*2 = 10pt. Total 11 >= 10.
    offer_and_decline("H2", "A2", "2026-06-21T18:00:00Z", "2026-06-21T16:00:00Z")

    # Working game 3 -> settle.
    set_clock("2026-06-01T00:00:00Z")
    g3 = validate_success(api.create_game(create_game_payload(
        league["id"], home_team="H3", away_team="A3",
        start_utc="2026-06-25T18:00:00Z"), ASSIGNOR), 201)
    s3 = validate_success(api.create_crew_slot(
        g3["id"], create_crew_slot_payload(position="REFEREE"), ASSIGNOR), 201)
    g3 = validate_success(api.open_game(g3["id"], ASSIGNOR), 200)
    a3 = offer_slot(s3["id"], official["id"], g3["id"])
    accept_assignment(a3["id"], official["id"], g3["id"])
    lock_game(g3["id"])
    set_clock("2026-06-25T19:00:00Z")
    gv = current_game_version(g3["id"])
    validate_success(api.settle_game(g3["id"], {"expected_game_version": gv}, ASSIGNOR), 200)

    official_after = validate_success(api.get_official(official["id"], ADMIN), 200)
    assert official_after["penalty_points"] == 11
    settled = validate_success(api.get_assignment(a3["id"], ASSIGNOR), 200)
    # SENIOR base 15000 * 0.90 = 13500 (mileage 0).
    assert settled["final_pay_cents"] == 13500
