"""Breadth tests for the ``calculations`` design section.

The league's arithmetic lives in six places: the two academic evaluation
variants and their half-up rounding at the third decimal (PRD §3.2), the
derived participation cascade and the team roll-ups that follow it (PRD §3.5),
the three-way match-point award and the dispute deadline (PRD §3.7), the
integrity constant tables with their repeat multipliers and clean-conduct
credit (PRD §3.8), the seeding variants with their six ordered tiebreakers
(PRD §3.9), and the four pinned steps of the scholarship projection together
with the half-open recruiting window (PRD §3.9).  Each test below drives one of
those calculations from the API surface only.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    INTEGRITY_OFFICER_ID,
    INTEGRITY_OFFICER_ID_2,
    INTEGRITY_OFFICER_ID_3,
    integrity_officer_headers,
    league_admin_headers,
    make_coach_headers,
    recruiter_headers,
)


# ==========================================================================
# Instance: term_snapshot_standing_at_the_min_gpa_and_probation_floor_
#           boundaries
# ==========================================================================
def test_term_snapshot_walks_both_thresholds_a_thousandth_at_a_time(api):
    """2.000 is GOOD, 1.999 PROBATION, 1.750 PROBATION, 1.749 INELIGIBLE.

    PRD §3.2: "Under `TERM_SNAPSHOT`, `effective_gpa` is simply the latest
    term's GPA rounded half up to three decimals, and the prior term is ignored
    entirely."  And: "The resulting `effective_gpa` then selects a standing: at
    or above the district's `min_gpa` the student is `GOOD`; otherwise, at or
    above the district's `probation_gpa_floor` the student is `PROBATION`;
    otherwise the student is `INELIGIBLE`. All three comparisons use the
    rounded three-decimal figure."  PRD §3.1 pins the two defaults: "`min_gpa`,
    the grade-point average at or above which a student is in good standing,
    defaulting to 2.000, and `probation_gpa_floor`, the average at or above
    which a student below `min_gpa` is placed on probation rather than declared
    ineligible, defaulting to 1.750."

    Design: Corner/calculations/term_snapshot_standing_at_the_min_gpa_and_probation_floor_boundaries
    """
    district = fx.make_district(api)
    assert district["academic_standing_basis"] == "TERM_SNAPSHOT"
    A.assert_gpa(district["min_gpa"], 2.000)
    A.assert_gpa(district["probation_gpa_floor"], 1.750)

    school = fx.make_school(api, district["id"])
    student = fx.make_student(api, school["id"])
    assert student["academic_standing"] == "UNEVALUATED"
    assert student["effective_gpa"] is None

    good = fx.post_term(api, student, 2.000, 6.0, "2025-FALL")
    A.assert_gpa(good["effective_gpa"], 2.000)
    assert good["academic_standing"] == "GOOD"
    A.assert_version_advanced_by(student, good, 1)

    just_under = fx.post_term(api, good, 1.999, 6.0, "2026-WINTER")
    A.assert_gpa(just_under["effective_gpa"], 1.999)
    assert just_under["academic_standing"] == "PROBATION"
    A.assert_version_advanced_by(good, just_under, 1)

    on_the_floor = fx.post_term(api, just_under, 1.750, 6.0, "2026-SPRING")
    A.assert_gpa(on_the_floor["effective_gpa"], 1.750)
    assert on_the_floor["academic_standing"] == "PROBATION"
    A.assert_version_advanced_by(just_under, on_the_floor, 1)

    below_the_floor = fx.post_term(api, on_the_floor, 1.749, 6.0, "2026-SUMMER")
    A.assert_gpa(below_the_floor["effective_gpa"], 1.749)
    assert below_the_floor["academic_standing"] == "INELIGIBLE"
    A.assert_version_advanced_by(on_the_floor, below_the_floor, 1)

    A.assert_gpa(below_the_floor["latest_term_gpa"], 1.749)
    A.assert_gpa(below_the_floor["prior_term_gpa"], 1.750)
    assert below_the_floor["latest_term_label"] == "2026-SUMMER"
    assert below_the_floor["standing_basis_applied"] == "TERM_SNAPSHOT"


# ==========================================================================
# Instance: rolling_cumulative_reads_only_the_two_most_recent_postings
# ==========================================================================
def test_rolling_cumulative_forgets_the_term_displaced_out_of_the_register(api):
    """Depth two: the 3.000 term can never re-enter the weighted average.

    PRD §3.2: "Academic history is a **shift register of depth two**. ... On
    acceptance the term currently held in `latest_term_gpa` and
    `latest_term_credits` is displaced into `prior_term_gpa` and
    `prior_term_credits`; the posted values become the new `latest_term_gpa`
    and `latest_term_credits` ... A term displaced out of the prior slot is
    gone for good and can never re-enter any calculation."  And: "Under
    `ROLLING_CUMULATIVE`, the two terms are credit-weighted: multiply the
    latest term's GPA by the latest term's credits, add the prior term's GPA
    multiplied by the prior term's credits — treating a null prior GPA and a
    null prior credit count as zero — then divide that sum by the total of the
    latest term's credits plus the prior term's credits".

    Design: Corner/calculations/rolling_cumulative_reads_only_the_two_most_recent_postings
    """
    district = fx.make_district(api, academic_standing_basis="ROLLING_CUMULATIVE")
    assert district["academic_standing_basis"] == "ROLLING_CUMULATIVE"
    school = fx.make_school(api, district["id"])
    student = fx.make_student(api, school["id"])

    first = fx.post_term(api, student, 3.000, 6.0, "2025-FALL")
    A.assert_gpa(first["effective_gpa"], 3.000)
    assert first["academic_standing"] == "GOOD"
    assert first["prior_term_gpa"] is None
    assert first["prior_term_credits"] is None

    second = fx.post_term(api, first, 1.000, 6.0, "2026-WINTER")
    A.assert_gpa(second["effective_gpa"], 2.000)
    assert second["academic_standing"] == "GOOD"

    third = fx.post_term(api, second, 2.000, 6.0, "2026-SPRING")
    A.assert_gpa(third["effective_gpa"], 1.500)
    assert third["academic_standing"] == "INELIGIBLE"

    A.assert_gpa(third["latest_term_gpa"], 2.000)
    assert float(third["latest_term_credits"]) == 6.0
    A.assert_gpa(third["prior_term_gpa"], 1.000)
    assert float(third["prior_term_credits"]) == 6.0
    assert third["standing_basis_applied"] == "ROLLING_CUMULATIVE"


# ==========================================================================
# Instance: rolling_gpa_rounds_half_up_at_the_third_decimal
# ==========================================================================
def test_the_rolling_quotient_rounds_half_up_at_the_third_decimal(api):
    """16/11 is 1.454545..., and half up at three decimals is 1.455.

    PRD §3.2: "then divide that sum by the total of the latest term's credits
    plus the prior term's credits (again treating a null prior credit count as
    zero), and round the quotient half up to three decimals."  PRD §2.8:
    "Grade-point averages are carried to **three decimal places, rounded half
    up**. This applies to a district's `min_gpa` and `probation_gpa_floor`, to a
    posted term's GPA, to a student's `effective_gpa`, and to the snapshot
    `effective_gpa_at_verification` taken on a roster slot. Standing comparisons
    are performed on the *rounded* three-decimal value".

    Design: Corner/calculations/rolling_gpa_rounds_half_up_at_the_third_decimal
    """
    district = fx.make_district(api, academic_standing_basis="ROLLING_CUMULATIVE")
    school = fx.make_school(api, district["id"])
    student = fx.make_student(api, school["id"])

    prior = fx.post_term(api, student, 1.000, 6.0, "2026-WINTER")
    A.assert_gpa(prior["effective_gpa"], 1.000)

    latest = fx.post_term(api, prior, 2.000, 5.0, "2026-SPRING")
    A.assert_gpa(latest["effective_gpa"], 1.455)
    assert latest["academic_standing"] == "INELIGIBLE"

    assert float(latest["latest_term_credits"]) == 5.0
    assert float(latest["prior_term_credits"]) == 6.0
    A.assert_gpa(latest["latest_term_gpa"], 2.000)
    A.assert_gpa(latest["prior_term_gpa"], 1.000)
    assert latest["standing_basis_applied"] == "ROLLING_CUMULATIVE"


# ==========================================================================
# Instance: participation_ladder_lets_release_outrank_an_academic_block
# ==========================================================================
def _build_academically_blocked_starter(api):
    """One DRAFT team whose single enrollment-verified starter has just been
    knocked to INELIGIBLE by a failing academic posting."""
    world = fx.build_draft_team(api, term_gpa=3.500, term_credits=6.0)
    slot = fx.add_slot(
        api, world["team"]["id"], world["student"]["id"], world["coach"]["id"], "STARTER"
    )
    world["slot"] = fx.verify_slot_enrollment(api, slot["id"], "2010-05-01")
    world["student"] = fx.post_term(
        api, fx.get_student(api, world["student"]["id"]), 1.000, 6.0, "2026-SPRING"
    )
    return world


def test_release_outranks_an_academic_block_and_frees_the_seat(api):
    """A slot already INELIGIBLE for ACADEMIC reasons reports RELEASED.

    PRD §3.5: "The derivation is a strict cascade of four cases in this order.
    If `released_at` is not null the slot is `RELEASED`. Otherwise, if
    `ineligibility_reason` is not null the slot is `INELIGIBLE`. Otherwise, if
    `verification_status` is `ENROLLMENT_VERIFIED` and `academic_status` is
    `CLEARED`, the slot is `ACTIVE`. In every other case the slot is
    `PROSPECTIVE`."  And: "On success `released_at` is stamped from the logical
    clock, `participation_status` becomes `RELEASED`, the team's
    `starter_slots_used` is decremented and its `starter_slots_available`
    incremented so their sum still equals `max_starters`, `active_starter_count`
    is recomputed".  PRD §3.2: "every roster slot belonging to that student
    whose academics axis is still `PENDING` and whose team is still open for
    roster mutation ... moves its academics axis from `PENDING` to `BLOCKED`,
    takes `ineligibility_reason` `ACADEMIC`, has its participation reconciled to
    `INELIGIBLE`".

    Design: Corner/calculations/participation_ladder_lets_release_outrank_an_academic_block
    """
    world = _build_academically_blocked_starter(api)
    assert world["student"]["academic_standing"] == "INELIGIBLE"

    blocked = fx.get_slot(api, world["slot"]["id"])
    A.assert_slot_axes(
        blocked,
        verification_status="ENROLLMENT_VERIFIED",
        academic_status="BLOCKED",
        participation_status="INELIGIBLE",
    )
    assert blocked["ineligibility_reason"] == "ACADEMIC"
    assert blocked["released_at"] is None

    before = fx.get_team(api, world["team"]["id"])
    assert before["starter_slots_used"] == 1
    assert before["starter_slots_available"] == 2
    assert before["active_starter_count"] == 0
    A.assert_starter_capacity_conserved(before, 3)

    response = api.release_roster_slot(
        blocked["id"],
        {"release_note": "academically ineligible, slot freed"},
        make_coach_headers(world["coach"]["id"]),
    )
    validate_success(response)
    released = A.data_of(response)
    A.assert_slot_axes(
        released,
        verification_status="ENROLLMENT_VERIFIED",
        academic_status="BLOCKED",
        participation_status="RELEASED",
    )
    assert released["released_at"] == "2026-08-01T00:00:00.000Z"
    A.assert_version_advanced_by(blocked, released, 1)

    after = fx.get_team(api, world["team"]["id"])
    assert after["starter_slots_used"] == 0
    assert after["starter_slots_available"] == 3
    assert after["active_starter_count"] == 0
    A.assert_starter_capacity_conserved(after, 3)


# ==========================================================================
# Instance: two_agreeing_reports_confirm_a_draw_and_award_one_point_to_each_side
# ==========================================================================
def test_two_agreeing_reports_pay_one_point_to_each_side_of_a_draw(api):
    """The draw branch is the only one that credits both teams.

    PRD §3.7: "When the counts are equal, each side is credited 1 point and each
    side's `draws` rises by one. In all three of these non-forfeit cases the
    game tallies accumulate as well: the home team's `games_won` grows by the
    match's `home_games_won` and its `games_lost` by the match's
    `away_games_won`, while the away team's `games_won` grows by
    `away_games_won` and its `games_lost` by `home_games_won`."  And: "the
    agreed pair is pinned as `home_games_won` and `away_games_won`,
    `winner_team_id` is set to whichever side won more games and left null on an
    equal count, `play_status` moves `SERVER_READY → PLAYED`,
    `result_confirmed_at` is stamped from the logical clock, and the dispute
    deadline is computed."

    Design: Corner/calculations/two_agreeing_reports_confirm_a_draw_and_award_one_point_to_each_side
    """
    world = fx.build_two_team_season(api)
    match = fx.schedule_match(
        api,
        world["season"]["id"],
        world["team_a"]["id"],
        world["team_b"]["id"],
        "2026-09-25T18:00:00.000Z",
    )
    match = fx.configure_server(api, match["id"])
    A.assert_match_state(match, play_status="SERVER_READY")

    first = fx.report_result(api, match, world["team_a"], 1, 1)
    A.assert_match_state(
        first, play_status="SERVER_READY", result_status="PARTIALLY_REPORTED"
    )
    assert first["home_reported_home_games_won"] == 1
    assert first["home_reported_away_games_won"] == 1
    assert first["winner_team_id"] is None

    confirmed = fx.report_result(api, first, world["team_b"], 1, 1)
    A.assert_match_state(confirmed, play_status="PLAYED", result_status="CONFIRMED")
    assert confirmed["home_games_won"] == 1
    assert confirmed["away_games_won"] == 1
    assert confirmed["winner_team_id"] is None
    assert confirmed["home_points_awarded"] == 1
    assert confirmed["away_points_awarded"] == 1
    assert confirmed["result_confirmed_at"] == "2026-08-01T00:00:00.000Z"
    assert confirmed["dispute_deadline_at"] == "2026-08-03T00:00:00.000Z"
    A.assert_three_digit_millis(confirmed["dispute_deadline_at"])

    for team_key in ("team_a", "team_b"):
        team = fx.get_team(api, world[team_key]["id"])
        assert team["match_points"] == 1
        assert team["draws"] == 1
        assert team["wins"] == 0
        assert team["losses"] == 0
        assert team["games_won"] == 1
        assert team["games_lost"] == 1
        assert team["game_differential"] == 0
        assert team["forfeit_wins"] == 0
        assert team["forfeits_charged"] == 0

    season = fx.get_season(api, world["season"]["id"])
    A.assert_match_point_pool(season, 2)
    assert season["seeding_state"] == "UNSEEDED"

    finalized = fx.finalize_match(api, confirmed["id"])
    A.assert_match_state(finalized, play_status="FINALIZED", result_status="CONFIRMED")
    assert finalized["home_games_won"] == 1
    assert finalized["away_games_won"] == 1
    assert finalized["home_points_awarded"] == 1
    assert finalized["away_points_awarded"] == 1
    assert fx.get_team(api, world["team_a"]["id"])["match_points"] == 1
    A.assert_match_point_pool(fx.get_season(api, world["season"]["id"]), 2)


# ==========================================================================
# Instance: integrity_clean_credit_accrues_one_step_and_repeat_index_reflows_
#           on_overturn
# ==========================================================================
def _build_two_sustained_cases_then_appeal_the_first(api):
    """One DRAFT team carrying a MINOR and then a MAJOR ACCOUNT_SHARING case
    against the same student, the clock moved 31 clean days on, and the first
    case sitting in APPEALED."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    student = fx.make_student(api, school["id"])
    team = fx.make_team(api, season["id"], school["id"], title["id"], coach["id"])
    slot = fx.add_slot(api, team["id"], student["id"], coach["id"], "STARTER")

    first = fx.open_student_case(api, team["id"], student["id"], case_type="ACCOUNT_SHARING")
    fx.investigate_case(api, first["id"], officer_id=INTEGRITY_OFFICER_ID)
    first = fx.decide_case(
        api,
        first["id"],
        decision="SUSTAIN",
        severity="MINOR",
        officer_id=INTEGRITY_OFFICER_ID_2,
    )
    second = fx.open_student_case(
        api, team["id"], student["id"], case_type="ACCOUNT_SHARING"
    )
    fx.investigate_case(api, second["id"], officer_id=INTEGRITY_OFFICER_ID)
    second = fx.decide_case(
        api,
        second["id"],
        decision="SUSTAIN",
        severity="MAJOR",
        officer_id=INTEGRITY_OFFICER_ID_2,
    )

    fx.set_clock(api, "2026-09-01T00:00:00.000Z")
    first = fx.appeal_case(
        api, first, coach["id"], appeal_grounds="lab machine confirmed"
    )
    return {
        "team": team,
        "student": student,
        "slot": slot,
        "coach": coach,
        "first": first,
        "second": second,
    }


def test_overturning_the_first_case_reindexes_the_second_and_pays_the_credit(api):
    """The surviving case is restated from repeat 2 to repeat 1.

    PRD §3.8: "The repeat multiplier is 1.0 for the first case in the set, 1.5
    for the second, and 2.0 for the third and every case after it. Each case's
    `applied_penalty` is its `severity_weight` multiplied by its own multiplier,
    rounded half up to two decimals".  And: "The first link removes the case
    from the sustained set, which recomputes the team's `integrity_score` and
    shifts the `repeat_index` of every later sustained case on that team down by
    one — changing each of their `applied_penalty` figures accordingly — and
    sets the overturned case's own `sanction_type` back to `NONE`."  And on the
    credit: "Otherwise take the latest `decided_at` across the set, measure the
    whole days elapsed from that instant to the logical clock's present value by
    discarding any partial day, award 5 points for each complete block of 30
    such days, and cap the award at 10 points".

    Design: Corner/calculations/integrity_clean_credit_accrues_one_step_and_repeat_index_reflows_on_overturn
    """
    world = _build_two_sustained_cases_then_appeal_the_first(api)

    before_team = fx.get_team(api, world["team"]["id"])
    A.assert_integrity_score(before_team["integrity_score"], 60.00)
    first_before = fx.get_case(api, world["first"]["id"])
    assert first_before["status"] == "APPEALED"
    assert first_before["repeat_index"] == 1
    assert first_before["severity_weight"] == 10
    A.assert_integrity_score(first_before["applied_penalty"], 10.00)
    second_before = fx.get_case(api, world["second"]["id"])
    assert second_before["repeat_index"] == 2
    A.assert_integrity_score(second_before["applied_penalty"], 30.00)

    response = api.decide_appeal(
        world["first"]["id"],
        {"decision": "OVERTURN", "appeal_note": "lab machine confirmed"},
        integrity_officer_headers(INTEGRITY_OFFICER_ID_3),
    )
    validate_success(response)
    overturned = A.data_of(response)
    assert overturned["status"] == "OVERTURNED"
    assert overturned["appeal_decider_user_id"] == INTEGRITY_OFFICER_ID_3
    assert overturned["sanction_type"] == "NONE"

    second_after = fx.get_case(api, world["second"]["id"])
    assert second_after["status"] == "SUSTAINED"
    assert second_after["repeat_index"] == 1
    assert second_after["severity_weight"] == 20
    A.assert_integrity_score(second_after["applied_penalty"], 20.00)
    assert second_after["sanction_type"] == "STUDENT_SUSPENSION"

    after_team = fx.get_team(api, world["team"]["id"])
    A.assert_integrity_score(after_team["integrity_score"], 85.00)
    assert after_team["status"] == "DRAFT"
    assert after_team["suspension_reason"] is None

    assert fx.get_student(api, world["student"]["id"])["fair_play_status"] == "SANCTIONED"
    A.assert_slot_axes(
        fx.get_slot(api, world["slot"]["id"]), participation_status="PROSPECTIVE"
    )


# ==========================================================================
# Instance: seed_order_falls_through_five_tiebreakers_to_created_at_ascending
# ==========================================================================
def _build_two_untested_competing_teams_and_a_draft_one(api):
    """Two COMPETING teams created a day apart so their ``created_at`` order is
    unambiguous, plus a third team left in DRAFT, in a season whose
    ``playoff_slots`` is 1."""
    district = fx.make_district(api)
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"], playoff_slots=1)

    school_a = fx.make_school(api, district["id"])
    coach_a = fx.make_certified_coach(api, school_a["id"])
    student_a = fx.make_student_with_term(api, school_a["id"])
    school_b = fx.make_school(api, district["id"])
    coach_b = fx.make_certified_coach(api, school_b["id"])
    student_b = fx.make_student_with_term(api, school_b["id"])
    coach_c = fx.make_coach(api, school_a["id"], full_name="Coach Charlie")

    fx.approve_title_for_district(api, district["id"], title["id"], school_a["id"])
    season = fx.open_registration(api, season["id"])

    team_a = fx.make_team(
        api, season["id"], school_a["id"], title["id"], coach_a["id"], name="Alpha"
    )
    fx.set_clock(api, "2026-08-02T00:00:00.000Z")
    team_b = fx.make_team(
        api, season["id"], school_b["id"], title["id"], coach_b["id"], name="Bravo"
    )
    team_c = fx.make_team(
        api, season["id"], school_a["id"], title["id"], coach_c["id"], name="Charlie"
    )

    fx.make_active_starter(api, team_a["id"], coach_a["id"], student_a)
    fx.make_active_starter(api, team_b["id"], coach_b["id"], student_b)
    team_a = fx.lock_roster(api, fx.register_team(api, team_a))
    team_b = fx.lock_roster(api, fx.register_team(api, team_b))
    fx.advance_season(api, season["id"], "ROSTER_LOCKED")
    season = fx.advance_season(api, season["id"], "REGULAR_SEASON")

    return {
        "season": season,
        "team_a": fx.get_team(api, team_a["id"]),
        "team_b": fx.get_team(api, team_b["id"]),
        "team_c": fx.get_team(api, team_c["id"]),
    }


def test_two_untested_teams_are_separated_only_by_created_at(api):
    """All five ranked keys tie, so the last resort decides the bracket.

    PRD §3.9: "Six keys are applied in strict order, and a later key is
    consulted only when every earlier key ties. `seed_points` descending comes
    first. Then `head_to_head_points` descending ... Then `game_differential`
    descending ... Then `forfeits_charged` ascending ... Then `integrity_score`
    descending, compared at two decimals. Finally `created_at` ascending as the
    last resort; the record `id` is never consulted as a tiebreaker."  And:
    "Teams at a `seed_position` at or below the season's `playoff_slots` take
    status `PLAYOFF_SEEDED`; the rest take status `ELIMINATED`."  And: "Teams in
    `DRAFT`, `REGISTERED`, `ROSTER_LOCKED`, `WITHDRAWN` or `DISQUALIFIED` are
    excluded from the seed order entirely and keep a null `seed_position`."

    Design: Corner/calculations/seed_order_falls_through_five_tiebreakers_to_created_at_ascending
    """
    world = _build_two_untested_competing_teams_and_a_draft_one(api)
    assert world["team_a"]["created_at"] == "2026-08-01T00:00:00.000Z"
    assert world["team_b"]["created_at"] == "2026-08-02T00:00:00.000Z"
    assert world["team_a"]["status"] == "COMPETING"
    assert world["team_b"]["status"] == "COMPETING"
    assert world["season"]["playoff_slots"] == 1

    season = fx.run_seeding(api, world["season"]["id"])
    assert season["seeding_state"] == "SEEDED"
    assert season["seeding_basis_applied"] == "MATCH_POINT_BASIS"
    assert season["seed_order"] == [world["team_a"]["id"], world["team_b"]["id"]]
    A.assert_match_point_pool(season, 0)

    first = fx.get_team(api, world["team_a"]["id"])
    assert first["seed_position"] == 1
    assert first["status"] == "PLAYOFF_SEEDED"
    assert first["seed_stale"] is False
    A.assert_seed_points(first["seed_points"], 0.0000)
    A.assert_integrity_score(first["integrity_score"], 100.00)

    second = fx.get_team(api, world["team_b"]["id"])
    assert second["seed_position"] == 2
    assert second["status"] == "ELIMINATED"
    assert second["seed_stale"] is False
    A.assert_seed_points(second["seed_points"], 0.0000)
    A.assert_integrity_score(second["integrity_score"], 100.00)

    excluded = fx.get_team(api, world["team_c"]["id"])
    assert excluded["seed_position"] is None
    assert excluded["status"] == "DRAFT"


# ==========================================================================
# Instance: scholarship_multiplier_pays_half_on_probation_and_nothing_when_
#           unevaluated
# ==========================================================================
def _build_two_nominatable_students(api):
    """One PROBATION student on a SUB slot and one never-evaluated student on a
    STARTER slot, both on the same unseeded DRAFT team."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    team = fx.make_team(api, season["id"], school["id"], title["id"], coach["id"])

    probation = fx.post_term(
        api, fx.make_student(api, school["id"]), 1.900, 6.0, "2026-SPRING"
    )
    unevaluated = fx.make_student(api, school["id"])
    fx.add_slot(api, team["id"], probation["id"], coach["id"], "SUB")
    fx.add_slot(api, team["id"], unevaluated["id"], coach["id"], "STARTER")
    return {
        "team": team,
        "probation": probation,
        "unevaluated": unevaluated,
    }


def test_probation_pays_half_and_an_unevaluated_student_pays_nothing(api):
    """Two multiplier rows that are easy to omit, and a tier pinned once.

    PRD §3.9: "Take a base award of 150,000 cents and multiply it by the
    academic multiplier for the student's current `academic_standing` — 1.0 for
    `GOOD`, 0.5 for `PROBATION`, and 0.0 for both `UNEVALUATED` and
    `INELIGIBLE` — rounding that product half up to whole cents. Then add a seed
    bonus of 45,000 cents for every rank by which the nominating team's
    `seed_position` betters fifth place, where a null `seed_position` is treated
    as fifth place exactly".  And: "Step two chooses `award_tier` from that
    provisional total alone: at or above 350,000 cents it is `GOLD`, otherwise
    at or above 200,000 cents it is `SILVER`, otherwise it is `BRONZE`" while
    "Step three computes the performance bonus by multiplying the provisional
    total by the rate for the chosen tier — 5 percent for `BRONZE`, 12 percent
    for `SILVER`, 20 percent for `GOLD`".  And: "the student's `showcase_status`
    must currently be `NONE`, since a student may be nominated only once and a
    repeat is refused with `ERR_ALREADY_NOMINATED`".

    Design: Corner/calculations/scholarship_multiplier_pays_half_on_probation_and_nothing_when_unevaluated
    """
    world = _build_two_nominatable_students(api)
    assert world["probation"]["academic_standing"] == "PROBATION"
    assert world["unevaluated"]["academic_standing"] == "UNEVALUATED"
    assert world["probation"]["award_tier"] == "NONE"
    assert world["probation"]["scholarship_award_state"] == "NONE"

    half = api.nominate_showcase(
        world["probation"]["id"],
        {"nominating_team_id": world["team"]["id"]},
        league_admin_headers(),
    )
    validate_success(half)
    nominated = A.data_of(half)
    assert nominated["showcase_status"] == "NOMINATED"
    assert nominated["nominating_team_id"] == world["team"]["id"]
    assert nominated["academic_standing"] == "PROBATION"
    A.assert_cents(nominated["provisional_award_cents"], 75000)
    assert nominated["award_tier"] == "BRONZE"
    A.assert_cents(nominated["scholarship_award_cents"], 78750)
    assert nominated["scholarship_award_state"] == "CURRENT"

    nothing = api.nominate_showcase(
        world["unevaluated"]["id"],
        {"nominating_team_id": world["team"]["id"]},
        league_admin_headers(),
    )
    validate_success(nothing)
    blank = A.data_of(nothing)
    assert blank["academic_standing"] == "UNEVALUATED"
    A.assert_cents(blank["provisional_award_cents"], 0)
    assert blank["award_tier"] == "BRONZE"
    A.assert_cents(blank["scholarship_award_cents"], 0)
    assert blank["scholarship_award_state"] == "CURRENT"

    repeat = api.nominate_showcase(
        world["probation"]["id"],
        {"nominating_team_id": world["team"]["id"]},
        league_admin_headers(),
    )
    validate_error(repeat, ApiErrorId.ERR_ALREADY_NOMINATED.value, 409)

    unchanged = fx.get_student(api, world["probation"]["id"])
    A.assert_cents(unchanged["scholarship_award_cents"], 78750)
    assert unchanged["award_tier"] == "BRONZE"
    A.assert_version_is(unchanged, nominated["version"])


# ==========================================================================
# Instance: recruiting_window_is_half_open_so_a_contact_at_window_start_has_
#           aged_out
# ==========================================================================
def _build_nominated_student_with_two_logged_contacts(api):
    """A GOOD-standing nominated student whose district caps contacts at 2 per
    30-day window, carrying two contacts logged at the opening instant."""
    district = fx.make_district(
        api, recruiting_contact_cap_per_window=2, recruiting_window_days=30
    )
    school = fx.make_school(api, district["id"])
    coach = fx.make_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    team = fx.make_team(api, season["id"], school["id"], title["id"], coach["id"])
    student = fx.post_term(
        api, fx.make_student(api, school["id"]), 3.500, 6.0, "2026-SPRING"
    )
    fx.add_slot(api, team["id"], student["id"], coach["id"], "STARTER")
    student = A.data_of(
        api.nominate_showcase(
            student["id"], {"nominating_team_id": team["id"]}, league_admin_headers()
        )
    )
    for _ in range(2):
        student = A.data_of(
            api.log_recruiting_contact(
                student["id"],
                {"org_code": "TECH-T", "channel": "EMAIL", "purpose": "first look"},
                recruiter_headers(),
            )
        )
    return {"district": district, "team": team, "student": student}


def test_a_contact_sitting_exactly_on_the_window_start_has_aged_out(api):
    """One millisecond of clock reopens a quota that was full.

    PRD §3.9: "the rolling cap is applied: count the entries already in the
    student's `recruiting_contact_log` whose `contacted_at` is **strictly
    after** the instant `recruiting_window_days` before the clock's present
    value, and if that count has already reached the district's
    `recruiting_contact_cap_per_window`, refuse with
    `ERR_RECRUITING_CONTACT_CAP_EXCEEDED`. The window is half-open at its older
    end: a logged contact whose `contacted_at` falls exactly on the window's
    opening instant has aged out and is not counted."  And: "Refused attempts
    are never logged, so a rejected contact leaves the quota exactly where it
    was."

    Design: Corner/calculations/recruiting_window_is_half_open_so_a_contact_at_window_start_has_aged_out
    """
    world = _build_nominated_student_with_two_logged_contacts(api)
    student = world["student"]
    assert student["showcase_status"] == "NOMINATED"
    A.assert_cents(student["scholarship_award_cents"], 157500)
    assert len(student["recruiting_contact_log"]) == 2

    fx.set_clock(api, "2026-08-30T23:59:59.999Z")
    still_inside = api.log_recruiting_contact(
        student["id"],
        {"org_code": "TECH-T", "channel": "PHONE", "purpose": "official visit"},
        recruiter_headers(),
    )
    validate_error(
        still_inside, ApiErrorId.ERR_RECRUITING_CONTACT_CAP_EXCEEDED.value, 409
    )
    unlogged = fx.get_student(api, student["id"])
    assert len(unlogged["recruiting_contact_log"]) == 2
    A.assert_version_is(unlogged, student["version"])

    fx.set_clock(api, "2026-08-31T00:00:00.000Z")
    aged_out = api.log_recruiting_contact(
        student["id"],
        {"org_code": "TECH-T", "channel": "PHONE", "purpose": "official visit"},
        recruiter_headers(),
    )
    validate_success(aged_out)
    logged = A.data_of(aged_out)
    entries = logged["recruiting_contact_log"]
    assert len(entries) == 3
    assert entries[2]["contacted_at"] == "2026-08-31T00:00:00.000Z"
    assert entries[2]["org_code"] == "TECH-T"
    assert entries[2]["channel"] == "PHONE"
    assert entries[2]["purpose"] == "official visit"
    assert entries[0]["contacted_at"] == "2026-08-01T00:00:00.000Z"
    assert entries[1]["contacted_at"] == "2026-08-01T00:00:00.000Z"
    A.assert_version_advanced_by(unlogged, logged, 1)

    assert logged["showcase_status"] == "NOMINATED"
    A.assert_cents(logged["scholarship_award_cents"], 157500)


# ==========================================================================
# Instance: dispute_window_is_governed_by_the_home_teams_district_only
# ==========================================================================
def _build_forfeit_across_two_districts(api):
    """The home side sits in a 48-hour district and the away side in a 6-hour
    one; the away team is charged with a forfeit at the opening instant."""
    home_district = fx.make_district(api)
    away_district = fx.make_district(api, dispute_window_hours=6)
    home_school = fx.make_school(api, home_district["id"])
    away_school = fx.make_school(api, away_district["id"])
    home_coach = fx.make_coach(api, home_school["id"], full_name="Coach Home")
    away_coach = fx.make_coach(api, away_school["id"], full_name="Coach Away")
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    home_team = fx.make_team(
        api, season["id"], home_school["id"], title["id"], home_coach["id"], name="Home"
    )
    away_team = fx.make_team(
        api, season["id"], away_school["id"], title["id"], away_coach["id"], name="Away"
    )
    match = fx.schedule_match(
        api,
        season["id"],
        home_team["id"],
        away_team["id"],
        "2026-10-01T18:00:00.000Z",
    )
    match = fx.forfeit_match(
        api, match["id"], away_team["id"], reason_note="roster collapse"
    )
    return {
        "home_district": home_district,
        "away_district": away_district,
        "away_coach": away_coach,
        "home_team": home_team,
        "away_team": away_team,
        "match": match,
    }


def test_the_deadline_follows_the_home_district_and_the_away_coach_still_files(api):
    """The away side's own six-hour policy is never consulted.

    PRD §3.7: "The **dispute deadline** is derived from the home side's district
    only; the away side's policy never affects it. Walk from the match's
    `home_team_id` to that team's `school_id`, then to that school's
    `district_id`, and add that district's `dispute_window_hours` to the match's
    `result_confirmed_at`. The sum is stored as `dispute_deadline_at`, at
    millisecond precision with three fractional digits. This computation runs
    whenever `result_confirmed_at` is set — on confirmation, on an adjudication
    produced by a finalization override, and on a forfeit."  And: "the logical
    clock must be at or before `dispute_deadline_at`, with filing at the exact
    deadline millisecond still succeeding and anything later refused with
    `ERR_DISPUTE_WINDOW_CLOSED`".

    Design: Corner/calculations/dispute_window_is_governed_by_the_home_teams_district_only
    """
    world = _build_forfeit_across_two_districts(api)
    assert world["home_district"]["dispute_window_hours"] == 48
    assert world["away_district"]["dispute_window_hours"] == 6

    match = world["match"]
    A.assert_match_state(
        match, play_status="FORFEITED", result_status="ADJUDICATED", dispute_status="NONE"
    )
    assert match["result_confirmed_at"] == "2026-08-01T00:00:00.000Z"
    assert match["dispute_deadline_at"] == "2026-08-03T00:00:00.000Z"
    assert match["dispute_deadline_at"] != "2026-08-01T06:00:00.000Z"
    A.assert_three_digit_millis(match["dispute_deadline_at"])

    fx.set_clock(api, "2026-08-01T12:00:00.000Z")
    response = api.file_dispute(
        match["id"],
        {
            "filing_team_id": world["away_team"]["id"],
            "dispute_reason_code": "SERVER_FAULT",
            "dispute_note": "our client never connected",
        },
        make_coach_headers(world["away_coach"]["id"]),
    )
    validate_success(response)
    disputed = A.data_of(response)
    assert disputed["dispute_status"] == "OPEN"
    assert disputed["dispute_filed_by_team_id"] == world["away_team"]["id"]
    assert disputed["dispute_reason_code"] == "SERVER_FAULT"
    assert disputed["dispute_deadline_at"] == "2026-08-03T00:00:00.000Z"
    A.assert_version_advanced_by(match, disputed, 1)


# ==========================================================================
# Instance: server_pool_capacity_is_released_by_a_forfeited_match
# ==========================================================================
def _build_capacity_one_pool_holding_one_match(api):
    """A capacity-1 pool occupied by a single 18:00-19:00 match."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach_a = fx.make_coach(api, school["id"], full_name="Coach Alpha")
    coach_b = fx.make_coach(api, school["id"], full_name="Coach Bravo")
    title = fx.make_title(
        api,
        server_pool_id="POOL-A",
        server_pool_capacity=1,
        match_duration_minutes=60,
    )
    season = fx.make_season(api, title["id"])
    team_a = fx.make_team(
        api, season["id"], school["id"], title["id"], coach_a["id"], name="Alpha"
    )
    team_b = fx.make_team(
        api, season["id"], school["id"], title["id"], coach_b["id"], name="Bravo"
    )
    match = fx.schedule_match(
        api, season["id"], team_a["id"], team_b["id"], "2026-10-01T18:00:00.000Z"
    )
    return {
        "season": season,
        "team_a": team_a,
        "team_b": team_b,
        "match": match,
    }


def test_a_forfeited_peer_releases_the_capacity_it_was_holding(api):
    """The identical request is refused, then accepted once the peer forfeits.

    PRD §3.7: "The peers considered are every other match sharing the same
    `server_pool_id` whose `play_status` is `SCHEDULED`, `SERVER_READY` or
    `PLAYED`; matches that have reached `FINALIZED` or `FORFEITED` release their
    capacity and are ignored."  And: "If the occupancy at any probe instant
    exceeds the title's `server_pool_capacity`, the scheduling request is refused
    with `ERR_SERVER_POOL_CAPACITY_EXCEEDED`."  And on the forfeit itself:
    "Either way, `play_status` becomes `FORFEITED`, `result_status` becomes
    `ADJUDICATED`, `winner_team_id` becomes the other team".

    Design: Corner/calculations/server_pool_capacity_is_released_by_a_forfeited_match
    """
    world = _build_capacity_one_pool_holding_one_match(api)
    assert world["match"]["server_pool_id"] == "POOL-A"
    assert world["match"]["scheduled_end_at"] == "2026-10-01T19:00:00.000Z"
    A.assert_match_state(world["match"], play_status="SCHEDULED")

    overlapping = {
        "season_id": world["season"]["id"],
        "home_team_id": world["team_b"]["id"],
        "away_team_id": world["team_a"]["id"],
        "scheduled_start_at": "2026-10-01T18:30:00.000Z",
    }
    refused = api.create_match(overlapping, league_admin_headers())
    validate_error(refused, ApiErrorId.ERR_SERVER_POOL_CAPACITY_EXCEEDED.value, 409)

    forfeited = fx.forfeit_match(
        api, world["match"]["id"], world["team_b"]["id"], reason_note="roster collapse"
    )
    A.assert_match_state(
        forfeited, play_status="FORFEITED", result_status="ADJUDICATED"
    )
    assert forfeited["winner_team_id"] == world["team_a"]["id"]

    accepted = api.create_match(overlapping, league_admin_headers())
    validate_success(accepted, 201)
    second = A.data_of(accepted, 201)
    assert second["scheduled_start_at"] == "2026-10-01T18:30:00.000Z"
    assert second["scheduled_end_at"] == "2026-10-01T19:30:00.000Z"
    assert second["server_pool_id"] == "POOL-A"
    A.assert_match_state(second, play_status="SCHEDULED", result_status="AWAITING_REPORTS")

    _rows, meta = validate_paginated(
        api.list_matches({"season_id": world["season"]["id"]}, league_admin_headers())
    )
    assert meta["total_count"] == 2
