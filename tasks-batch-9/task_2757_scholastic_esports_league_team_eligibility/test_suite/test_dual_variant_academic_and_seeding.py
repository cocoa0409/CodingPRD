"""Depth tests for the two dual-variant calculations.

Both instances of the ``dual_variant_calc`` rule are exercised here: the
academic standing basis of PRD §3.2 and the seeding basis of PRD §3.9.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ELIGIBILITY_OFFICER_ID,
    ELIGIBILITY_OFFICER_ID_2,
    eligibility_officer_headers,
)


# ==========================================================================
# Instance: academic_standing_term_snapshot_vs_rolling_cumulative_divergence
# ==========================================================================
BIRTHDATE = "2009-05-10"


def _build_two_term_student_on_starter_slot(api, academic_standing_basis):
    """One district on the given basis, with a student carrying exactly two
    postings — 2.400 over 6 credits then 1.900 over 6 credits — holding a
    STARTER slot whose enrollment axis is already verified."""
    district = fx.make_district(
        api,
        academic_standing_basis=academic_standing_basis,
        min_gpa=2.000,
        probation_gpa_floor=1.750,
    )
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    student = fx.make_student(api, school["id"], birthdate=BIRTHDATE)
    student = fx.post_term(api, student, 2.400, 6, term_label="2025-FALL")
    student = fx.post_term(api, student, 1.900, 6, term_label="2026-SPRING")
    team = fx.make_team(api, season["id"], school["id"], title["id"], coach["id"])
    slot = fx.add_slot(api, team["id"], student["id"], coach["id"], slot_role="STARTER")
    fx.verify_slot_enrollment(
        api, slot["id"], BIRTHDATE, officer_id=ELIGIBILITY_OFFICER_ID
    )
    return {
        "district": district,
        "school": school,
        "coach": coach,
        "title": title,
        "season": season,
        "student": student,
        "team": team,
        "slot": slot,
    }


def test_term_snapshot_basis_reads_the_latest_term_only_and_blocks_the_starter(api):
    """A TERM_SNAPSHOT district ignores the prior term entirely.

    PRD §3.2: "Under `TERM_SNAPSHOT`, `effective_gpa` is simply the latest
    term's GPA rounded half up to three decimals, and the prior term is
    ignored entirely." and "A `TERM_SNAPSHOT` district reads 1.900 and places
    the student on probation".  PRD §3.5 axis two: "If it yields `PROBATION`
    and the slot's `slot_role` is `STARTER`, the verification is refused with
    `ERR_PROBATION_STARTER_RESTRICTED`".

    Design: Difficulty/dual_variant_calc/academic_standing_term_snapshot_vs_rolling_cumulative_divergence
    """
    world = _build_two_term_student_on_starter_slot(api, "TERM_SNAPSHOT")

    response = api.verify_academics(
        world["slot"]["id"], {}, eligibility_officer_headers(ELIGIBILITY_OFFICER_ID_2)
    )
    validate_error(response, ApiErrorId.ERR_PROBATION_STARTER_RESTRICTED.value, 422)

    student = fx.get_student(api, world["student"]["id"])
    A.assert_gpa(student["effective_gpa"], 1.900)
    assert student["academic_standing"] == "PROBATION"
    assert student["standing_basis_applied"] == "TERM_SNAPSHOT"

    slot = fx.get_slot(api, world["slot"]["id"])
    A.assert_slot_axes(slot, academic_status="PENDING", participation_status="PROSPECTIVE")

    team = fx.get_team(api, world["team"]["id"])
    assert team["active_starter_count"] == 0


def test_rolling_cumulative_basis_credit_weights_both_terms_and_clears_the_starter(api):
    """A ROLLING_CUMULATIVE district credit-weights the two-deep register.

    PRD §3.2: "a `ROLLING_CUMULATIVE` district credit-weights the two terms to
    2.150 and places the same student in good standing."  PRD §3.5: on success
    "the slot snapshots `standing_at_verification` ... and
    `effective_gpa_at_verification` (three decimals)".

    Design: Difficulty/dual_variant_calc/academic_standing_term_snapshot_vs_rolling_cumulative_divergence
    """
    world = _build_two_term_student_on_starter_slot(api, "ROLLING_CUMULATIVE")

    response = api.verify_academics(
        world["slot"]["id"], {}, eligibility_officer_headers(ELIGIBILITY_OFFICER_ID_2)
    )
    validate_success(response)
    slot = A.data_of(response)
    A.assert_slot_axes(
        slot,
        verification_status="ENROLLMENT_VERIFIED",
        academic_status="CLEARED",
        participation_status="ACTIVE",
    )
    A.assert_gpa(slot["effective_gpa_at_verification"], 2.150)
    assert slot["standing_at_verification"] == "GOOD"

    student = fx.get_student(api, world["student"]["id"])
    A.assert_gpa(student["effective_gpa"], 2.150)
    assert student["academic_standing"] == "GOOD"
    assert student["standing_basis_applied"] == "ROLLING_CUMULATIVE"

    team = fx.get_team(api, world["team"]["id"])
    assert team["active_starter_count"] == 1


# ==========================================================================
# Instance: seed_points_match_point_basis_vs_win_percentage_basis_rank_inversion
# ==========================================================================
def _build_three_team_frozen_result_set(api):
    """Alpha is fed by two forfeit wins, Bravo holds one genuine win over
    Charlie, and the season's pool stands at 9 points."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    title = fx.make_title(api, server_pool_capacity=1, match_duration_minutes=60)
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(api, title["id"])
    season = fx.open_registration(api, season["id"])

    teams = {}
    for label in ("Alpha", "Bravo", "Charlie"):
        coach = fx.make_certified_coach(api, school["id"])
        student = fx.make_student_with_term(api, school["id"], term_gpa=3.100, term_credits=6)
        team = fx.make_team(
            api, season["id"], school["id"], title["id"], coach["id"], name=label
        )
        fx.make_active_starter(api, team["id"], coach["id"], student)
        team = fx.register_team(api, team)
        team = fx.lock_roster(api, team)
        teams[label] = team

    fx.advance_season(api, season["id"], "ROSTER_LOCKED")
    season = fx.advance_season(api, season["id"], "REGULAR_SEASON")

    alpha, bravo, charlie = teams["Alpha"], teams["Bravo"], teams["Charlie"]
    m1 = fx.schedule_match(
        api, season["id"], alpha["id"], charlie["id"], "2026-09-25T18:00:00.000Z"
    )
    m2 = fx.schedule_match(
        api, season["id"], alpha["id"], bravo["id"], "2026-09-25T19:00:00.000Z"
    )
    m3 = fx.schedule_match(
        api, season["id"], bravo["id"], charlie["id"], "2026-09-25T20:00:00.000Z"
    )
    fx.forfeit_match(api, m1["id"], charlie["id"], reason_note="no show")
    fx.forfeit_match(api, m2["id"], bravo["id"], reason_note="no show")
    m3 = fx.configure_server(api, m3["id"])
    fx.confirm_result(api, m3, bravo, charlie, 2, 1)

    return {
        "season": fx.get_season(api, season["id"]),
        "alpha": fx.get_team(api, alpha["id"]),
        "bravo": fx.get_team(api, bravo["id"]),
        "charlie": fx.get_team(api, charlie["id"]),
    }


def test_match_point_basis_seeds_the_forfeit_fed_team_first(api):
    """Under MATCH_POINT_BASIS forfeit wins count in full.

    PRD §3.9: "Under `MATCH_POINT_BASIS` a team's `seed_points` is simply its
    accumulated `match_points`" and "A team holding two forfeit wins and one
    genuine loss carries 6 match points and scores 6.0000 under
    `MATCH_POINT_BASIS`, comfortably ahead of a rival with a single genuine
    win at 3.0000".  "Teams at a `seed_position` at or below the season's
    `playoff_slots` take status `PLAYOFF_SEEDED`; the rest take status
    `ELIMINATED`."

    Design: Difficulty/dual_variant_calc/seed_points_match_point_basis_vs_win_percentage_basis_rank_inversion
    """
    world = _build_three_team_frozen_result_set(api)
    assert world["season"]["match_point_pool"] == 9

    season = fx.run_seeding(api, world["season"]["id"])
    assert season["seeding_basis_applied"] == "MATCH_POINT_BASIS"
    assert season["seeding_state"] == "SEEDED"

    alpha = fx.get_team(api, world["alpha"]["id"])
    bravo = fx.get_team(api, world["bravo"]["id"])
    charlie = fx.get_team(api, world["charlie"]["id"])

    A.assert_seed_points(alpha["seed_points"], 6.0000)
    assert alpha["seed_position"] == 1
    assert alpha["status"] == "PLAYOFF_SEEDED"
    A.assert_seed_points(bravo["seed_points"], 3.0000)
    assert bravo["seed_position"] == 2
    assert bravo["status"] == "PLAYOFF_SEEDED"
    A.assert_seed_points(charlie["seed_points"], 0.0000)
    assert charlie["seed_position"] == 3
    assert charlie["status"] == "ELIMINATED"

    assert season["seed_order"] == [alpha["id"], bravo["id"], charlie["id"]]
    A.assert_match_point_pool(season, 9)


def test_win_percentage_basis_override_inverts_the_top_two_seeds(api):
    """A WIN_PERCENTAGE_BASIS override discards the forfeits entirely.

    PRD §3.9: "Under `WIN_PERCENTAGE_BASIS` the denominator is the team's
    `wins` plus `losses` plus `draws` — a total that deliberately excludes
    forfeits ... when the denominator is zero the team scores 0.0000".  The
    tie between the two zero-scoring teams is broken by
    "`head_to_head_points` descending, which is the points a team earned in
    `FINALIZED` or `FORFEITED` matches whose *both* participants sit inside
    the currently tied group".  "When `basis_override` is supplied it takes
    effect ... Whichever value governed is echoed onto the season as
    `seeding_basis_applied`".

    Design: Difficulty/dual_variant_calc/seed_points_match_point_basis_vs_win_percentage_basis_rank_inversion
    """
    world = _build_three_team_frozen_result_set(api)
    fx.run_seeding(api, world["season"]["id"])

    season = fx.run_seeding(
        api, world["season"]["id"], basis_override="WIN_PERCENTAGE_BASIS"
    )
    assert season["seeding_basis_applied"] == "WIN_PERCENTAGE_BASIS"

    alpha = fx.get_team(api, world["alpha"]["id"])
    bravo = fx.get_team(api, world["bravo"]["id"])
    charlie = fx.get_team(api, world["charlie"]["id"])

    A.assert_seed_points(bravo["seed_points"], 1.0000)
    assert bravo["seed_position"] == 1
    A.assert_seed_points(alpha["seed_points"], 0.0000)
    assert alpha["seed_position"] == 2
    A.assert_seed_points(charlie["seed_points"], 0.0000)
    assert charlie["seed_position"] == 3

    assert season["seed_order"] == [bravo["id"], alpha["id"], charlie["id"]]
    A.assert_match_point_pool(season, 9)
    assert alpha["match_points"] == 6
    assert bravo["match_points"] == 3
    assert charlie["match_points"] == 0
