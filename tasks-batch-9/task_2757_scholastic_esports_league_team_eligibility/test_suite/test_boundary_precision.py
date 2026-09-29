"""Depth tests for the three boundary/precision instances.

Instance one probes a millisecond instant (roster lock, PRD §3.6), instance two
a rounded three-decimal ratio (rolling GPA, PRD §3.2) and instance three an
integer count of completed years (age at cutoff, PRD §3.5).
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ELIGIBILITY_OFFICER_ID,
    eligibility_officer_headers,
    league_admin_headers,
    make_coach_headers,
)


# ==========================================================================
# Instance: roster_lock_deadline_inclusive_at_the_exact_millisecond
# ==========================================================================
def _build_two_registered_teams_at_the_lock_deadline(api):
    """Two REGISTERED teams, then the clock parked on exactly the season's
    default ``roster_lock_at``."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    title = fx.make_title(api, server_pool_capacity=2)
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(api, title["id"])
    season = fx.open_registration(api, season["id"])

    teams = {}
    for label in ("Alpha", "Bravo"):
        coach = fx.make_certified_coach(api, school["id"])
        student = fx.make_student_with_term(
            api, school["id"], term_gpa=3.100, term_credits=6.0
        )
        team = fx.make_team(
            api, season["id"], school["id"], title["id"], coach["id"], name=label
        )
        fx.make_active_starter(api, team["id"], coach["id"], student, "STARTER")
        teams[label] = fx.register_team(api, team)

    fx.set_clock(api, "2026-09-20T00:00:00.000Z")
    return {"season": season, "teams": teams}


def test_roster_lock_succeeds_at_the_exact_deadline_millisecond(api):
    """The deadline comparison is inclusive.

    PRD §3.6: "the logical clock must be at or before the season's
    `roster_lock_at`, with locking at the exact deadline millisecond still
    succeeding and anything later refused with
    `ERR_ROSTER_LOCK_DEADLINE_PASSED` ... On success `roster_locked_at` is
    stamped from the clock and the team's `version` increments by one."

    Design: Difficulty/boundary_precision_check/roster_lock_deadline_inclusive_at_the_exact_millisecond
    """
    world = _build_two_registered_teams_at_the_lock_deadline(api)
    alpha = world["teams"]["Alpha"]

    response = api.lock_roster(alpha["id"], {}, make_coach_headers(alpha["coach_id"]))
    validate_success(response)
    locked = A.data_of(response)
    assert locked["status"] == "ROSTER_LOCKED"
    assert locked["roster_locked_at"] == "2026-09-20T00:00:00.000Z"
    A.assert_version_advanced_by(alpha, locked, 1)


def test_roster_lock_fails_one_millisecond_past_the_deadline(api):
    """One millisecond later the same call is refused, and the season's own
    two-locked-team advance is then unreachable.

    PRD §3.6: "anything later refused with
    `ERR_ROSTER_LOCK_DEADLINE_PASSED`".  PRD §3.4: "`REGISTRATION_OPEN →
    ROSTER_LOCKED` additionally requires a compound condition over the
    season's children: at least two of the season's teams must already have
    reached `ROSTER_LOCKED` themselves, and a season with fewer than two
    locked teams is refused with `ERR_INVALID_SEASON_STAGE`."

    Design: Difficulty/boundary_precision_check/roster_lock_deadline_inclusive_at_the_exact_millisecond
    """
    world = _build_two_registered_teams_at_the_lock_deadline(api)
    alpha = world["teams"]["Alpha"]
    bravo = world["teams"]["Bravo"]

    fx.lock_roster(api, alpha)
    fx.set_clock(api, "2026-09-20T00:00:00.001Z")

    late = api.lock_roster(bravo["id"], {}, make_coach_headers(bravo["coach_id"]))
    validate_error(late, ApiErrorId.ERR_ROSTER_LOCK_DEADLINE_PASSED.value, 409)

    unchanged = fx.get_team(api, bravo["id"])
    assert unchanged["status"] == "REGISTERED"
    assert unchanged["roster_locked_at"] is None

    blocked = api.advance_season(
        world["season"]["id"], {"to_status": "ROSTER_LOCKED"}, league_admin_headers()
    )
    validate_error(blocked, ApiErrorId.ERR_INVALID_SEASON_STAGE.value, 409)


# ==========================================================================
# Instance: rolling_gpa_at_three_decimals_lands_exactly_on_the_min_gpa_
#           threshold
# ==========================================================================
def _student_with_prior_nine_credit_term(api, min_gpa):
    """A ROLLING_CUMULATIVE district at the given ``min_gpa``, holding one
    student whose only posting so far is 2.400 over 9 credits."""
    district = fx.make_district(
        api,
        academic_standing_basis="ROLLING_CUMULATIVE",
        min_gpa=min_gpa,
        probation_gpa_floor=1.750,
    )
    school = fx.make_school(api, district["id"])
    student = fx.make_student(api, school["id"], birthdate="2009-05-10")
    student = fx.post_term(api, student, 2.400, 9, term_label="2025-FALL")
    return district, student


def test_rolling_gpa_landing_exactly_on_min_gpa_is_good_standing(api):
    """The ``>=`` comparison runs on the rounded three-decimal figure.

    PRD §3.2: "Under `ROLLING_CUMULATIVE`, the two terms are credit-weighted:
    multiply the latest term's GPA by the latest term's credits, add the prior
    term's GPA multiplied by the prior term's credits ... then divide that sum
    by the total of the latest term's credits plus the prior term's credits
    ... and round the quotient half up to three decimals."  And: "at or above
    the district's `min_gpa` the student is `GOOD` ... All three comparisons
    use the rounded three-decimal figure."

    Design: Difficulty/boundary_precision_check/rolling_gpa_at_three_decimals_lands_exactly_on_the_min_gpa_threshold
    """
    _district, student = _student_with_prior_nine_credit_term(api, 2.275)

    response = api.post_academic_term(
        student["id"],
        {
            "term_label": "2026-SPRING",
            "term_gpa": 1.9,
            "term_credits": 3,
            "expected_student_version": student["version"],
        },
        eligibility_officer_headers(ELIGIBILITY_OFFICER_ID),
    )
    validate_success(response)
    posted = A.data_of(response)

    A.assert_gpa(posted["effective_gpa"], 2.275)
    assert posted["academic_standing"] == "GOOD"
    assert posted["standing_basis_applied"] == "ROLLING_CUMULATIVE"
    A.assert_gpa(posted["latest_term_gpa"], 1.900)
    assert posted["latest_term_credits"] == 3
    A.assert_gpa(posted["prior_term_gpa"], 2.400)
    assert posted["prior_term_credits"] == 9


def test_rolling_gpa_one_thousandth_below_min_gpa_is_probation(api):
    """A ``min_gpa`` of 2.276 flips the identical transcript to PROBATION.

    PRD §3.2: "otherwise, at or above the district's `probation_gpa_floor` the
    student is `PROBATION`; otherwise the student is `INELIGIBLE`. All three
    comparisons use the rounded three-decimal figure."

    Design: Difficulty/boundary_precision_check/rolling_gpa_at_three_decimals_lands_exactly_on_the_min_gpa_threshold
    """
    _district, student = _student_with_prior_nine_credit_term(api, 2.276)

    posted = fx.post_term(api, student, 1.900, 3, term_label="2026-SPRING")

    A.assert_gpa(posted["effective_gpa"], 2.275)
    assert posted["academic_standing"] == "PROBATION"
    assert posted["standing_basis_applied"] == "ROLLING_CUMULATIVE"


# ==========================================================================
# Instance: age_at_cutoff_completed_years_boundary_on_enrollment_verification
# ==========================================================================
def _build_two_slots_astride_the_age_cutoff(api):
    """Two STARTER slots on one DRAFT team: one student turns 13 exactly on
    the season's default ``age_cutoff_date``, the other one day later."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"], name="North Middle")
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api, min_player_age=13)
    season = fx.make_season(api, title["id"])

    on_cutoff = fx.make_student(api, school["id"], birthdate="2013-09-01", grade_level=9)
    past_cutoff = fx.make_student(
        api, school["id"], birthdate="2013-09-02", grade_level=9
    )
    team = fx.make_team(api, season["id"], school["id"], title["id"], coach["id"])
    slot_on = fx.add_slot(api, team["id"], on_cutoff["id"], coach["id"], "STARTER")
    slot_past = fx.add_slot(api, team["id"], past_cutoff["id"], coach["id"], "STARTER")
    return {
        "team": team,
        "on_cutoff": on_cutoff,
        "past_cutoff": past_cutoff,
        "slot_on": slot_on,
        "slot_past": slot_past,
    }


def test_student_turning_thirteen_on_the_cutoff_date_clears_the_age_floor(api):
    """``age_at_cutoff`` counts completed years and the floor is inclusive.

    PRD §3.5: "the two age bounds are applied to `age_at_cutoff`, the number
    of completed years from the `verified_birthdate` to the season's
    `age_cutoff_date`: it must be at or above the title's `min_player_age`,
    otherwise `ERR_STUDENT_BELOW_TITLE_MIN_AGE` ... The publisher floor is
    inclusive".  On success "the slot's `verification_status` moves
    `UNVERIFIED → ENROLLMENT_VERIFIED`, `age_at_cutoff` is pinned to the
    computed figure, `enrollment_verified_by_user_id` is written from
    `X-User-ID`".

    Design: Difficulty/boundary_precision_check/age_at_cutoff_completed_years_boundary_on_enrollment_verification
    """
    world = _build_two_slots_astride_the_age_cutoff(api)

    response = api.verify_enrollment(
        world["slot_on"]["id"],
        {"enrollment_document_ref": "REG-ON", "verified_birthdate": "2013-09-01"},
        eligibility_officer_headers(ELIGIBILITY_OFFICER_ID),
    )
    validate_success(response)
    slot = A.data_of(response)
    A.assert_slot_axes(
        slot,
        verification_status="ENROLLMENT_VERIFIED",
        academic_status="PENDING",
        participation_status="PROSPECTIVE",
    )
    assert slot["age_at_cutoff"] == 13
    assert slot["enrollment_verified_by_user_id"] == ELIGIBILITY_OFFICER_ID


def test_student_turning_thirteen_one_day_after_the_cutoff_is_refused(api):
    """One day later the student is still twelve at the cutoff.

    PRD §3.5: "it must be at or above the title's `min_player_age`, otherwise
    `ERR_STUDENT_BELOW_TITLE_MIN_AGE`".  A refused verification leaves the
    slot's own axes alone, since only "On success" does the slot move.

    Design: Difficulty/boundary_precision_check/age_at_cutoff_completed_years_boundary_on_enrollment_verification
    """
    world = _build_two_slots_astride_the_age_cutoff(api)
    fx.verify_slot_enrollment(api, world["slot_on"]["id"], "2013-09-01")

    response = api.verify_enrollment(
        world["slot_past"]["id"],
        {"enrollment_document_ref": "REG-PAST", "verified_birthdate": "2013-09-02"},
        eligibility_officer_headers(ELIGIBILITY_OFFICER_ID),
    )
    validate_error(response, ApiErrorId.ERR_STUDENT_BELOW_TITLE_MIN_AGE.value, 422)

    slot_past = fx.get_slot(api, world["slot_past"]["id"])
    A.assert_slot_axes(
        slot_past,
        verification_status="UNVERIFIED",
        participation_status="PROSPECTIVE",
    )
    assert slot_past["age_at_cutoff"] is None

    team = fx.get_team(api, world["team"]["id"])
    assert team["starter_slots_used"] == 2
    assert team["starter_slots_available"] == 1
    assert team["active_starter_count"] == 0
