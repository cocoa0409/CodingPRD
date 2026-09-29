"""Depth tests for the three named precedence pairs.

Each instance drives one call that violates two rules at once and pins which
rung of the PRD §2.7 ladder must answer.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    RECRUITER_ID,
    league_admin_headers,
    make_coach_headers,
    recruiter_headers,
)


# ==========================================================================
# Instance: register_state_error_wins_over_exhausted_subsidy_pool
# ==========================================================================
def _build_registered_team_on_a_drained_pool(api):
    """A district whose pool held exactly the 3,962 cents one starter draws,
    spent in full by the team's first registration."""
    world = fx.build_draft_team(
        api,
        district_kwargs={"subsidy_pool_cents": 3962},
        term_gpa=3.100,
        term_credits=6.0,
    )
    world["slot"] = fx.make_active_starter(
        api, world["team"]["id"], world["coach"]["id"], world["student"], "STARTER"
    )
    world["team"] = fx.register_team(api, world["team"])
    return world


def test_already_registered_team_hears_the_state_error_not_the_fiscal_one(api):
    """The team from-state rung sits far above the fiscal rung.

    PRD §2.7: "A registration attempt on a team that is already registered
    *and* whose district pool is exhausted reports `ERR_INVALID_TEAM_STATE`,
    because the team from-state rung sits far above the fiscal rung."  PRD
    §3.6: "The team must be in `DRAFT`, otherwise `ERR_INVALID_TEAM_STATE`"
    and "the district's remaining `subsidy_pool_cents` must be at least as
    large as the subsidy this registration would grant, otherwise
    `ERR_SUBSIDY_POOL_EXHAUSTED` — the last rung on the whole ladder".

    Design: Difficulty/priority_pair_validation_conflict/register_state_error_wins_over_exhausted_subsidy_pool
    """
    world = _build_registered_team_on_a_drained_pool(api)
    assert world["team"]["status"] == "REGISTERED"
    A.assert_cents(world["team"]["subsidy_granted_cents"], 3962)
    A.assert_cents(fx.get_district(api, world["district"]["id"])["subsidy_pool_cents"], 0)

    response = api.register_team(
        world["team"]["id"], {}, make_coach_headers(world["coach"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_TEAM_STATE.value, 409)


def test_rejected_second_registration_leaves_no_second_debit(api):
    """The refused call moves no fiscal figure at all.

    PRD §3.6: "the district's `subsidy_pool_cents` is reduced by exactly the
    `subsidy_granted_cents` just awarded, keeping the subsidy conservation
    invariant in balance against the district's `subsidy_pool_initial_cents`"
    and "the season's `registered_team_count` is recomputed".

    Design: Difficulty/priority_pair_validation_conflict/register_state_error_wins_over_exhausted_subsidy_pool
    """
    world = _build_registered_team_on_a_drained_pool(api)
    api.register_team(world["team"]["id"], {}, make_coach_headers(world["coach"]["id"]))

    district = fx.get_district(api, world["district"]["id"])
    A.assert_cents(district["subsidy_pool_cents"], 0)
    A.assert_cents(district["subsidy_pool_initial_cents"], 3962)
    A.assert_subsidy_conserved(district, 3962)

    team = fx.get_team(api, world["team"]["id"])
    A.assert_cents(team["subsidy_granted_cents"], 3962)
    assert team["status"] == "REGISTERED"

    season = fx.get_season(api, world["season"]["id"])
    assert season["registered_team_count"] == 1


# ==========================================================================
# Instance: dispute_non_participant_error_wins_over_closed_dispute_window
# ==========================================================================
def _build_forfeited_match_past_the_deadline(api):
    """A forfeited match whose 48-hour dispute window closed yesterday, plus a
    third team that never played in it."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])

    teams = {}
    for label in ("Alpha", "Bravo", "Charlie"):
        coach = fx.make_coach(api, school["id"])
        teams[label] = fx.make_team(
            api, season["id"], school["id"], title["id"], coach["id"], name=label
        )

    match = fx.schedule_match(
        api,
        season["id"],
        teams["Alpha"]["id"],
        teams["Bravo"]["id"],
        "2026-09-25T18:00:00.000Z",
    )
    match = fx.forfeit_match(api, match["id"], teams["Bravo"]["id"], reason_note="no show")
    fx.set_clock(api, "2026-08-04T00:00:00.000Z")
    return {"season": season, "teams": teams, "match": match}


def test_non_participant_filing_team_outranks_the_closed_window(api):
    """Referential agreement precedes temporal windows.

    PRD §2.7: "A dispute filed after the window has closed by a team that is
    not even a participant reports `ERR_TEAM_NOT_MATCH_PARTICIPANT`, because
    referential agreement precedes temporal windows."  PRD §3.7: "the filing
    team must be a participant, otherwise `ERR_TEAM_NOT_MATCH_PARTICIPANT`;
    and the logical clock must be at or before `dispute_deadline_at` ...
    anything later refused with `ERR_DISPUTE_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/dispute_non_participant_error_wins_over_closed_dispute_window
    """
    world = _build_forfeited_match_past_the_deadline(api)
    alpha_coach_headers = make_coach_headers(world["teams"]["Alpha"]["coach_id"])

    response = api.file_dispute(
        world["match"]["id"],
        {
            "filing_team_id": world["teams"]["Charlie"]["id"],
            "dispute_reason_code": "SCORE_MISMATCH",
            "dispute_note": "filed on behalf of another club",
        },
        alpha_coach_headers,
    )
    validate_error(response, ApiErrorId.ERR_TEAM_NOT_MATCH_PARTICIPANT.value, 422)

    match = fx.get_match(api, world["match"]["id"])
    assert match["dispute_status"] == "NONE"
    assert match["dispute_filed_by_team_id"] is None
    assert match["dispute_deadline_at"] == "2026-08-03T00:00:00.000Z"


def test_the_closed_window_rule_was_live_all_along(api):
    """Naming a genuine participant exposes the lower-priority rung.

    PRD §3.7: "the logical clock must be at or before `dispute_deadline_at`,
    with filing at the exact deadline millisecond still succeeding and
    anything later refused with `ERR_DISPUTE_WINDOW_CLOSED`. Recall from §2.7
    that a non-participant filing late hears about the participation problem,
    not the window."

    Design: Difficulty/priority_pair_validation_conflict/dispute_non_participant_error_wins_over_closed_dispute_window
    """
    world = _build_forfeited_match_past_the_deadline(api)
    alpha_coach_headers = make_coach_headers(world["teams"]["Alpha"]["coach_id"])

    response = api.file_dispute(
        world["match"]["id"],
        {
            "filing_team_id": world["teams"]["Alpha"]["id"],
            "dispute_reason_code": "SCORE_MISMATCH",
        },
        alpha_coach_headers,
    )
    validate_error(response, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED.value, 409)
    assert fx.get_match(api, world["match"]["id"])["dispute_status"] == "NONE"


# ==========================================================================
# Instance: recruiting_dead_period_error_wins_over_contact_cap
# ==========================================================================
def _build_nominated_student_at_the_cap_inside_the_dead_period(api):
    """A district capped at one contact per 30 days with a 2026-08-10..20
    blackout; one contact is already logged and the clock sits at 08-15."""
    district = fx.make_district(
        api,
        recruiting_contact_cap_per_window=1,
        recruiting_window_days=30,
        recruiting_dead_period_start="2026-08-10T00:00:00.000Z",
        recruiting_dead_period_end="2026-08-20T00:00:00.000Z",
    )
    school = fx.make_school(api, district["id"])
    coach = fx.make_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    student = fx.make_student_with_term(
        api, school["id"], term_gpa=3.100, term_credits=6.0
    )
    team = fx.make_team(api, season["id"], school["id"], title["id"], coach["id"])
    fx.add_slot(api, team["id"], student["id"], coach["id"], slot_role="STARTER")

    student = fx.data_of(
        api.nominate_showcase(
            student["id"], {"nominating_team_id": team["id"]}, league_admin_headers()
        )
    )
    fx.data_of(
        api.log_recruiting_contact(
            student["id"],
            {"org_code": "STATE-U", "channel": "EMAIL", "purpose": "camp invitation"},
            recruiter_headers(RECRUITER_ID),
        )
    )
    fx.set_clock(api, "2026-08-15T00:00:00.000Z")
    return {"district": district, "student": student, "team": team}


def test_dead_period_outranks_the_rolling_contact_cap(api):
    """The temporal dead-period rung precedes the quota rung.

    PRD §2.7: "a recruiting contact attempted inside the dead period by a
    recruiter who has also exhausted the rolling cap reports
    `ERR_RECRUITING_DEAD_PERIOD`, because the temporal dead-period rung
    precedes the quota rung."  PRD §3.9: "Two district rules follow ... and
    they are evaluated in this order. First, if the district has both a
    `recruiting_dead_period_start` and a `recruiting_dead_period_end`
    configured and the logical clock falls inside that interval — with both
    ends inclusive — the contact is refused with
    `ERR_RECRUITING_DEAD_PERIOD`."  And: "Refused attempts are never logged,
    so a rejected contact leaves the quota exactly where it was."

    Design: Difficulty/priority_pair_validation_conflict/recruiting_dead_period_error_wins_over_contact_cap
    """
    world = _build_nominated_student_at_the_cap_inside_the_dead_period(api)
    assert world["student"]["showcase_status"] == "NOMINATED"
    assert world["student"]["award_tier"] == "BRONZE"
    A.assert_cents(world["student"]["provisional_award_cents"], 150000)
    A.assert_cents(world["student"]["scholarship_award_cents"], 157500)

    response = api.log_recruiting_contact(
        world["student"]["id"],
        {"org_code": "STATE-U", "channel": "PHONE", "purpose": "follow up"},
        recruiter_headers(RECRUITER_ID),
    )
    validate_error(response, ApiErrorId.ERR_RECRUITING_DEAD_PERIOD.value, 409)

    student = fx.get_student(api, world["student"]["id"])
    assert len(student["recruiting_contact_log"]) == 1
    assert student["recruiting_contact_log"][0]["contacted_at"] == (
        "2026-08-01T00:00:00.000Z"
    )


def test_after_the_dead_period_the_rolling_cap_answers_instead(api):
    """The quota rung was live all along, just outranked.

    PRD §3.9: "Second, the rolling cap is applied: count the entries already
    in the student's `recruiting_contact_log` whose `contacted_at` is
    **strictly after** the instant `recruiting_window_days` before the clock's
    present value, and if that count has already reached the district's
    `recruiting_contact_cap_per_window`, refuse with
    `ERR_RECRUITING_CONTACT_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/recruiting_dead_period_error_wins_over_contact_cap
    """
    world = _build_nominated_student_at_the_cap_inside_the_dead_period(api)
    blocked = api.log_recruiting_contact(
        world["student"]["id"],
        {"org_code": "STATE-U", "channel": "PHONE", "purpose": "follow up"},
        recruiter_headers(RECRUITER_ID),
    )
    validate_error(blocked, ApiErrorId.ERR_RECRUITING_DEAD_PERIOD.value, 409)

    fx.set_clock(api, "2026-08-21T00:00:00.000Z")
    capped = api.log_recruiting_contact(
        world["student"]["id"],
        {"org_code": "STATE-U", "channel": "PHONE", "purpose": "follow up"},
        recruiter_headers(RECRUITER_ID),
    )
    validate_error(capped, ApiErrorId.ERR_RECRUITING_CONTACT_CAP_EXCEEDED.value, 409)

    student = fx.get_student(api, world["student"]["id"])
    assert len(student["recruiting_contact_log"]) == 1
