"""Depth tests for the two multi-link causal cascades.

Instance one is the five-link enforcement chain of PRD §3.8 (case → student →
slot → team → match).  Instance two is the four-link adjudication chain of
PRD §3.7 (result → ledger → seeding → scholarship).
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    INTEGRITY_OFFICER_ID,
    INTEGRITY_OFFICER_ID_2,
    league_admin_headers,
)


# ==========================================================================
# Instance: sustained_severe_case_cascades_five_links_case_student_slot_team_
#           match
# ==========================================================================
def _build_five_link_world(api):
    """Alpha carries two ACTIVE starters (seated before roster lock), one
    SCHEDULED match, and an INVESTIGATING SMURFING case on student A1."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    title = fx.make_title(api, server_pool_capacity=2)
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(api, title["id"])
    season = fx.open_registration(api, season["id"])

    coach_a = fx.make_certified_coach(api, school["id"])
    coach_b = fx.make_certified_coach(api, school["id"])
    student_a1 = fx.make_student_with_term(
        api, school["id"], term_gpa=3.100, term_credits=6.0, birthdate="2009-05-10"
    )
    student_a2 = fx.make_student_with_term(
        api, school["id"], term_gpa=3.100, term_credits=6.0, birthdate="2009-05-11"
    )
    student_b1 = fx.make_student_with_term(
        api, school["id"], term_gpa=3.100, term_credits=6.0, birthdate="2009-06-15"
    )

    alpha = fx.make_team(api, season["id"], school["id"], title["id"], coach_a["id"], name="Alpha")
    bravo = fx.make_team(api, season["id"], school["id"], title["id"], coach_b["id"], name="Bravo")
    slot_a1 = fx.make_active_starter(api, alpha["id"], coach_a["id"], student_a1, "STARTER")
    slot_a2 = fx.make_active_starter(api, alpha["id"], coach_a["id"], student_a2, "STARTER")
    slot_b1 = fx.make_active_starter(api, bravo["id"], coach_b["id"], student_b1, "STARTER")

    alpha = fx.lock_roster(api, fx.register_team(api, alpha))
    bravo = fx.lock_roster(api, fx.register_team(api, bravo))
    fx.advance_season(api, season["id"], "ROSTER_LOCKED")
    season = fx.advance_season(api, season["id"], "REGULAR_SEASON")

    match = fx.schedule_match(
        api, season["id"], alpha["id"], bravo["id"], "2026-09-25T18:00:00.000Z"
    )
    case = fx.open_student_case(api, alpha["id"], student_a1["id"], case_type="SMURFING")
    fx.investigate_case(api, case["id"], officer_id=INTEGRITY_OFFICER_ID)

    return {
        "district": district,
        "school": school,
        "season": season,
        "alpha": alpha,
        "bravo": bravo,
        "student_a1": student_a1,
        "student_a2": student_a2,
        "slot_a1": slot_a1,
        "slot_a2": slot_a2,
        "slot_b1": slot_b1,
        "match": match,
        "case": case,
    }


def _sustain_severe(api, world):
    return fx.decide_case(
        api,
        world["case"]["id"],
        decision="SUSTAIN",
        severity="SEVERE",
        officer_id=INTEGRITY_OFFICER_ID_2,
    )


def test_severe_sustain_walks_links_one_through_four_to_a_sanction_suspension(api):
    """Links 1–4: the suspension comes from the sanction, not from starvation.

    PRD §3.8: "The second link, caused by the first and only when
    `subject_type` is `STUDENT`, moves that student's `fair_play_status` from
    `CLEAR` to `SANCTIONED`. The third link, caused by the second, moves every
    roster slot of that student whose `participation_status` is `ACTIVE` to
    `INELIGIBLE` with `ineligibility_reason` `FAIR_PLAY` ... The fourth link,
    caused by the third, moves the charged team `COMPETING → SUSPENDED` when
    any of three things is true: ... the selected `sanction_type` is
    `TEAM_SUSPENSION` or `DISQUALIFICATION` ... The team's `suspension_reason`
    records which of those it was — `ROSTER_MINIMUM_BREACH`,
    `FAIR_PLAY_SANCTION` or `INTEGRITY_FLOOR_BREACH` respectively."  And: "A
    `SEVERE` severity selects `TEAM_SUSPENSION`."

    Design: Difficulty/transitive_cascade/sustained_severe_case_cascades_five_links_case_student_slot_team_match
    """
    world = _build_five_link_world(api)
    case = _sustain_severe(api, world)

    assert case["status"] == "SUSTAINED"
    assert case["repeat_index"] == 1
    assert case["severity_weight"] == 50
    A.assert_integrity_score(case["applied_penalty"], 50.00)
    assert case["sanction_type"] == "TEAM_SUSPENSION"

    assert fx.get_student(api, world["student_a1"]["id"])["fair_play_status"] == "SANCTIONED"
    assert fx.get_student(api, world["student_a2"]["id"])["fair_play_status"] == "CLEAR"

    slot_a1 = fx.get_slot(api, world["slot_a1"]["id"])
    A.assert_slot_axes(slot_a1, participation_status="INELIGIBLE")
    assert slot_a1["ineligibility_reason"] == "FAIR_PLAY"
    A.assert_slot_axes(
        fx.get_slot(api, world["slot_a2"]["id"]), participation_status="ACTIVE"
    )

    alpha = fx.get_team(api, world["alpha"]["id"])
    A.assert_integrity_score(alpha["integrity_score"], 50.00)
    assert alpha["status"] == "SUSPENDED"
    assert alpha["suspension_reason"] == "FAIR_PLAY_SANCTION"
    assert alpha["active_starter_count"] == 1
    assert alpha["starter_slots_used"] == 2
    assert alpha["starter_slots_available"] == 1


def test_severe_sustain_reaches_link_five_and_forfeits_the_scheduled_match(api):
    """Link 5 is two entities away from the endpoint's own aggregate.

    PRD §3.8: "The fifth link, caused by the fourth, forfeits every match of
    that suspended team whose `play_status` is `SCHEDULED` or `SERVER_READY`,
    crediting the opponent 3 points, growing the season's `match_point_pool`
    by 3 per forfeited match, and setting the season's `seeding_state` to
    `STALE`."  PRD §3.7: "`play_status` becomes `FORFEITED`, `result_status`
    becomes `ADJUDICATED`, `winner_team_id` becomes the other team,
    `forfeiting_team_id` is stored, `result_confirmed_at` is stamped,
    `dispute_deadline_at` is computed".

    Design: Difficulty/transitive_cascade/sustained_severe_case_cascades_five_links_case_student_slot_team_match
    """
    world = _build_five_link_world(api)
    _sustain_severe(api, world)

    match = fx.get_match(api, world["match"]["id"])
    A.assert_match_state(
        match, play_status="FORFEITED", result_status="ADJUDICATED"
    )
    assert match["forfeiting_team_id"] == world["alpha"]["id"]
    assert match["winner_team_id"] == world["bravo"]["id"]
    assert match["home_points_awarded"] == 0
    assert match["away_points_awarded"] == 3
    assert match["result_confirmed_at"] == "2026-08-01T00:00:00.000Z"
    assert match["dispute_deadline_at"] == "2026-08-03T00:00:00.000Z"

    alpha = fx.get_team(api, world["alpha"]["id"])
    bravo = fx.get_team(api, world["bravo"]["id"])
    assert alpha["match_points"] == 0
    assert alpha["forfeits_charged"] == 1
    assert bravo["match_points"] == 3
    assert bravo["forfeit_wins"] == 1

    season = fx.get_season(api, world["season"]["id"])
    A.assert_match_point_pool(season, 3)
    assert season["seeding_state"] == "UNSEEDED"
    assert alpha["seed_position"] is None


# ==========================================================================
# Instance: dispute_upheld_cascades_four_links_result_ledger_seeding_
#           scholarship
# ==========================================================================
def _build_seeded_nominated_dispute_under_review(api):
    """Alpha wins 2-1, the season is seeded with Alpha first, Alpha's student
    is nominated at a CURRENT 369,600-cent projection, and Bravo's dispute has
    been accepted for review."""
    world = fx.build_confirmed_match(api, home_games_won=2, away_games_won=1)
    season = fx.run_seeding(api, world["season"]["id"])
    student = fx.data_of(
        api.nominate_showcase(
            world["student_a"]["id"],
            {"nominating_team_id": world["team_a"]["id"]},
            league_admin_headers(),
        )
    )
    fx.file_dispute(
        api,
        world["match"]["id"],
        world["team_b"],
        dispute_reason_code="SCORE_MISMATCH",
        dispute_note="game 3 was awarded to the wrong side",
    )
    fx.dispute_action(api, world["match"]["id"], "ACCEPT_REVIEW")

    world["season"] = season
    world["student_a"] = student
    return world


def _uphold_with_correction(api, world):
    return fx.dispute_action(
        api,
        world["match"]["id"],
        "UPHOLD",
        corrected_home_games_won=1,
        corrected_away_games_won=2,
    )


def test_upheld_dispute_restates_the_result_and_the_whole_point_ledger(api):
    """Links 1–2: revert-then-apply leaves the season pool unchanged.

    PRD §3.7: "First, the match's `result_status` becomes `ADJUDICATED`,
    `home_games_won` and `away_games_won` are replaced by the corrected pair,
    and `winner_team_id` is recomputed. Second, caused by the first, the point
    award is re-run in revert-then-apply order on both teams, so
    `match_points`, `wins`, `losses`, `draws`, `games_won`, `games_lost`,
    `forfeit_wins` and `forfeits_charged` are all restated from the corrected
    result, and the season's `match_point_pool` is adjusted by the resulting
    delta so that the conservation formula of §2.9 still holds exactly."  And:
    "A team's `game_differential` is always its `games_won` less its
    `games_lost`."

    Design: Difficulty/transitive_cascade/dispute_upheld_cascades_four_links_result_ledger_seeding_scholarship
    """
    world = _build_seeded_nominated_dispute_under_review(api)
    assert world["season"]["seeding_state"] == "SEEDED"
    A.assert_cents(world["student_a"]["scholarship_award_cents"], 369600)

    match = _uphold_with_correction(api, world)
    A.assert_match_state(
        match, result_status="ADJUDICATED", dispute_status="UPHELD"
    )
    assert match["home_games_won"] == 1
    assert match["away_games_won"] == 2
    assert match["winner_team_id"] == world["team_b"]["id"]
    assert match["home_points_awarded"] == 0
    assert match["away_points_awarded"] == 3

    alpha = fx.get_team(api, world["team_a"]["id"])
    assert alpha["match_points"] == 0
    assert alpha["wins"] == 0
    assert alpha["losses"] == 1
    assert alpha["games_won"] == 1
    assert alpha["games_lost"] == 2
    assert alpha["game_differential"] == -1

    bravo = fx.get_team(api, world["team_b"]["id"])
    assert bravo["match_points"] == 3
    assert bravo["wins"] == 1
    assert bravo["losses"] == 0
    assert bravo["games_won"] == 2
    assert bravo["games_lost"] == 1
    assert bravo["game_differential"] == 1

    season = fx.get_season(api, world["season"]["id"])
    A.assert_match_point_pool(season, 3)


def test_upheld_dispute_reaches_links_three_and_four_seeding_and_scholarship(api):
    """Links 3–4: a stale order flags the award and bars the bracket.

    PRD §3.7: "Third, caused by the second, the season's `seeding_state` moves
    `SEEDED → STALE` and every team in that season that already holds a
    non-null `seed_position` gets `seed_stale` set to true. Fourth, caused by
    the third, every student whose `showcase_status` is `NOMINATED` and whose
    `nominating_team_id` belongs to this season moves
    `scholarship_award_state` from `CURRENT` to `RECALC_REQUIRED`".  PRD §3.4:
    "`REGULAR_SEASON → PLAYOFFS` requires the season's `seeding_state` to be
    exactly `SEEDED`; an `UNSEEDED` or `STALE` order may not open a bracket,
    and the attempt is refused with `ERR_SEASON_SEEDING_NOT_CURRENT`."

    Design: Difficulty/transitive_cascade/dispute_upheld_cascades_four_links_result_ledger_seeding_scholarship
    """
    world = _build_seeded_nominated_dispute_under_review(api)
    _uphold_with_correction(api, world)

    season = fx.get_season(api, world["season"]["id"])
    assert season["seeding_state"] == "STALE"

    alpha = fx.get_team(api, world["team_a"]["id"])
    bravo = fx.get_team(api, world["team_b"]["id"])
    assert alpha["seed_stale"] is True
    assert bravo["seed_stale"] is True
    assert alpha["seed_position"] == 1
    assert bravo["seed_position"] == 2

    nominated = fx.get_student(api, world["student_a"]["id"])
    assert nominated["scholarship_award_state"] == "RECALC_REQUIRED"
    assert nominated["award_tier"] == "SILVER"
    A.assert_cents(nominated["scholarship_award_cents"], 369600)

    sibling = fx.get_student(api, world["student_b"]["id"])
    assert sibling["showcase_status"] == "NONE"
    assert sibling["scholarship_award_state"] == "NONE"

    blocked = api.advance_season(
        world["season"]["id"], {"to_status": "PLAYOFFS"}, league_admin_headers()
    )
    validate_error(blocked, ApiErrorId.ERR_SEASON_SEEDING_NOT_CURRENT.value, 409)
