"""Depth tests for the three conserved quantities of PRD §2.9.

Instance one conserves money — the district subsidy pool against the grants
outstanding, reversed by withdrawal (PRD §3.6).  Instance two conserves an
integer seat count — ``starter_slots_used`` plus ``starter_slots_available``,
reversed by slot release (PRD §3.5).  Instance three conserves league points —
the season's ``match_point_pool``, reversed by an overturned appeal (PRD §3.8).
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    INTEGRITY_OFFICER_ID,
    INTEGRITY_OFFICER_ID_2,
    INTEGRITY_OFFICER_ID_3,
    integrity_officer_headers,
    make_athletic_director_headers,
    make_coach_headers,
)


# ==========================================================================
# Instance: district_subsidy_pool_restored_exactly_on_team_withdrawal
# ==========================================================================
def _build_registered_team_holding_one_grant(api):
    """One REGISTERED team drawing the odd per-line-rounded 3,962-cent grant
    against a 15,845-cent fee, out of the default 5,000,000-cent pool."""
    world = fx.build_draft_team(api, term_gpa=3.100, term_credits=6.0)
    world["slot"] = fx.make_active_starter(
        api, world["team"]["id"], world["coach"]["id"], world["student"], "STARTER"
    )
    world["team"] = fx.register_team(api, world["team"])
    return world


def test_withdrawal_credits_back_the_recorded_grant_not_a_recomputed_one(api):
    """The pool returns to exactly its immutable opening figure.

    PRD §3.6: "Withdrawal is the compensating counterpart of registration and
    unwinds it in full. The district's `subsidy_pool_cents` is increased by the
    team's `subsidy_granted_cents`, then the team's own `subsidy_granted_cents`
    and `net_fee_due_cents` are both set to 0, which restores the district's
    pool to exactly the figure the conservation invariant demands ... The team's
    status becomes the terminal `WITHDRAWN` and its `version` increments by
    one."  PRD §2.9: "the district's remaining `subsidy_pool_cents` plus the sum
    of `subsidy_granted_cents` across every team fielded by a school in that
    district always equals the district's `subsidy_pool_initial_cents`".

    Design: Difficulty/compensating_invariant/district_subsidy_pool_restored_exactly_on_team_withdrawal
    """
    world = _build_registered_team_holding_one_grant(api)
    registered = world["team"]
    A.assert_cents(registered["entry_fee_cents"], 15845)
    A.assert_cents(registered["subsidy_granted_cents"], 3962)
    A.assert_cents(registered["net_fee_due_cents"], 11883)

    before = fx.get_district(api, world["district"]["id"])
    A.assert_cents(before["subsidy_pool_cents"], 4996038)
    A.assert_subsidy_conserved(before, 3962)

    response = api.withdraw_team(
        registered["id"],
        {"withdrawal_note": "school folded the program"},
        make_athletic_director_headers(registered["school_id"]),
    )
    validate_success(response)
    withdrawn = A.data_of(response)
    assert withdrawn["status"] == "WITHDRAWN"
    A.assert_cents(withdrawn["subsidy_granted_cents"], 0)
    A.assert_cents(withdrawn["net_fee_due_cents"], 0)
    A.assert_cents(withdrawn["entry_fee_cents"], 15845)
    A.assert_version_advanced_by(registered, withdrawn, 1)

    after = fx.get_district(api, world["district"]["id"])
    A.assert_cents(after["subsidy_pool_cents"], 5000000)
    A.assert_cents(after["subsidy_pool_initial_cents"], 5000000)
    A.assert_subsidy_conserved(after, 0)


def test_withdrawal_also_frees_the_seat_and_empties_the_registered_count(api):
    """The same act keeps the seat invariant and the season roll-up honest.

    PRD §3.6: "Every roster slot on the team whose `participation_status` is not
    already `RELEASED` transitions to `RELEASED` ... The season's
    `registered_team_count` is recomputed, and if the season's `seeding_state`
    was `SEEDED` it becomes `STALE`."  PRD §3.5: "`starter_slots_used` is the
    count of the team's slots whose `slot_role` is `STARTER` and whose
    `participation_status` is `PROSPECTIVE`, `ACTIVE` or `INELIGIBLE` —
    released slots are excluded. `starter_slots_available` is the season's
    `max_starters` minus `starter_slots_used`."  PRD §3.4:
    "`registered_team_count` begins at 0 and counts the season's teams whose
    status is anything other than `DRAFT` or `WITHDRAWN`."

    Design: Difficulty/compensating_invariant/district_subsidy_pool_restored_exactly_on_team_withdrawal
    """
    world = _build_registered_team_holding_one_grant(api)
    fx.withdraw_team(api, world["team"], withdrawal_note="school folded the program")

    slot = fx.get_slot(api, world["slot"]["id"])
    A.assert_slot_axes(slot, participation_status="RELEASED")
    assert slot["released_at"] == "2026-08-01T00:00:00.000Z"

    team = fx.get_team(api, world["team"]["id"])
    assert team["starter_slots_used"] == 0
    assert team["starter_slots_available"] == 3
    A.assert_starter_capacity_conserved(team, 3)

    season = fx.get_season(api, world["season"]["id"])
    assert season["registered_team_count"] == 0
    assert season["seeding_state"] == "UNSEEDED"


# ==========================================================================
# Instance: starter_capacity_used_plus_available_is_invariant_across_add_and_
#           release
# ==========================================================================
def _build_team_with_three_starters_and_a_spare_student(api):
    """A DRAFT team filling all three default starter seats with unverified
    slots, plus a fourth student waiting for a seat."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    students = [
        fx.make_student(api, school["id"], birthdate=birthdate)
        for birthdate in ("2009-05-10", "2009-06-15", "2009-07-20", "2009-08-25")
    ]
    team = fx.make_team(api, season["id"], school["id"], title["id"], coach["id"])
    slots = [
        fx.add_slot(api, team["id"], student["id"], coach["id"], "STARTER")
        for student in students[:3]
    ]
    return {
        "coach": coach,
        "season": season,
        "team": team,
        "students": students,
        "slots": slots,
    }


def test_a_fourth_starter_is_refused_without_disturbing_the_seat_counters(api):
    """A refused insert must leave the identity exactly where it stood.

    PRD §3.5: "when the requested role is `STARTER`, the team must still have
    starter capacity — `starter_slots_used` strictly below the season's
    `max_starters`, equivalently at least one `starter_slots_available` —
    otherwise `ERR_STARTER_CAPACITY_EXCEEDED`."  PRD §2.9: "For every team,
    `starter_slots_used` plus `starter_slots_available` always equals the
    season's `max_starters`. This holds after every roster mutation".

    Design: Difficulty/compensating_invariant/starter_capacity_used_plus_available_is_invariant_across_add_and_release
    """
    world = _build_team_with_three_starters_and_a_spare_student(api)

    filled = fx.get_team(api, world["team"]["id"])
    assert filled["starter_slots_used"] == 3
    assert filled["starter_slots_available"] == 0
    assert filled["active_starter_count"] == 0
    A.assert_starter_capacity_conserved(filled, 3)

    response = api.create_roster_slot(
        {
            "team_id": world["team"]["id"],
            "student_id": world["students"][3]["id"],
            "slot_role": "STARTER",
        },
        make_coach_headers(world["coach"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STARTER_CAPACITY_EXCEEDED.value, 409)

    untouched = fx.get_team(api, world["team"]["id"])
    assert untouched["starter_slots_used"] == 3
    assert untouched["starter_slots_available"] == 0
    A.assert_starter_capacity_conserved(untouched, 3)


def test_releasing_a_seat_frees_it_for_a_replacement_student(api):
    """Release is the compensating half: the seat comes back and is reusable.

    PRD §3.5: "On success `released_at` is stamped from the logical clock,
    `participation_status` becomes `RELEASED`, the team's `starter_slots_used`
    is decremented and its `starter_slots_available` incremented so their sum
    still equals `max_starters`".  And: "If `released_at` is not null the slot
    is `RELEASED`."

    Design: Difficulty/compensating_invariant/starter_capacity_used_plus_available_is_invariant_across_add_and_release
    """
    world = _build_team_with_three_starters_and_a_spare_student(api)
    coach_headers = make_coach_headers(world["coach"]["id"])

    released_response = api.release_roster_slot(
        world["slots"][1]["id"],
        {"release_note": "moved out of district"},
        coach_headers,
    )
    validate_success(released_response)
    released = A.data_of(released_response)
    A.assert_slot_axes(released, participation_status="RELEASED")
    assert released["released_at"] == "2026-08-01T00:00:00.000Z"

    freed = fx.get_team(api, world["team"]["id"])
    assert freed["starter_slots_used"] == 2
    assert freed["starter_slots_available"] == 1
    A.assert_starter_capacity_conserved(freed, 3)

    replacement = api.create_roster_slot(
        {
            "team_id": world["team"]["id"],
            "student_id": world["students"][3]["id"],
            "slot_role": "STARTER",
        },
        coach_headers,
    )
    validate_success(replacement, 201)
    A.assert_slot_axes(A.data_of(replacement, 201), participation_status="PROSPECTIVE")

    refilled = fx.get_team(api, world["team"]["id"])
    assert refilled["starter_slots_used"] == 3
    assert refilled["starter_slots_available"] == 0
    A.assert_starter_capacity_conserved(refilled, 3)

    for kept in (world["slots"][0], world["slots"][2]):
        A.assert_slot_axes(
            fx.get_slot(api, kept["id"]), participation_status="PROSPECTIVE"
        )


# ==========================================================================
# Instance: season_match_point_pool_returns_to_zero_when_the_suspension_
#           forfeit_is_reversed
# ==========================================================================
def _build_forfeit_by_suspension_with_pending_appeal(api):
    """Alpha's only starter is sanctioned at MINOR, which starves the roster,
    suspends Alpha and forfeits its one SCHEDULED match to Bravo; Alpha's coach
    has already appealed."""
    world = fx.build_two_team_season(
        api, title_kwargs={"server_pool_capacity": 2}
    )
    world["match"] = fx.schedule_match(
        api,
        world["season"]["id"],
        world["team_a"]["id"],
        world["team_b"]["id"],
        "2026-09-25T18:00:00.000Z",
    )
    case = fx.open_student_case(
        api,
        world["team_a"]["id"],
        world["student_a"]["id"],
        case_type="ACCOUNT_SHARING",
    )
    fx.investigate_case(api, case["id"], officer_id=INTEGRITY_OFFICER_ID)
    case = fx.decide_case(
        api,
        case["id"],
        decision="SUSTAIN",
        severity="MINOR",
        officer_id=INTEGRITY_OFFICER_ID_2,
    )
    world["case"] = fx.appeal_case(
        api,
        case,
        world["coach_a"]["id"],
        appeal_grounds="the login came from the student's own home network",
    )
    return world


def _overturn(api, world):
    response = api.decide_appeal(
        world["case"]["id"],
        {"decision": "OVERTURN", "appeal_note": "evidence insufficient"},
        integrity_officer_headers(INTEGRITY_OFFICER_ID_3),
    )
    validate_success(response)
    return A.data_of(response)


def test_the_overturn_walks_the_three_points_back_out_of_the_season_pool(api):
    """The pool is reduced by reversal, not by recomputation.

    PRD §3.8: "The fifth link, caused by the fourth, restores every match that
    was forfeited **solely** because of that suspension: the 3 points credited
    to the opponent are removed, the winner's `forfeit_wins` and the forfeiting
    team's `forfeits_charged` are each decremented, the season's
    `match_point_pool` is reduced by 3 per restored match so it returns to
    exactly its pre-suspension value".  PRD §2.9 anchors the pool as "the
    running total of match points awarded in the season".

    Design: Difficulty/compensating_invariant/season_match_point_pool_returns_to_zero_when_the_suspension_forfeit_is_reversed
    """
    world = _build_forfeit_by_suspension_with_pending_appeal(api)

    A.assert_match_point_pool(fx.get_season(api, world["season"]["id"]), 3)
    charged = fx.get_team(api, world["team_a"]["id"])
    credited = fx.get_team(api, world["team_b"]["id"])
    assert charged["match_points"] == 0
    assert charged["forfeits_charged"] == 1
    assert credited["match_points"] == 3
    assert credited["forfeit_wins"] == 1

    case = _overturn(api, world)
    assert case["status"] == "OVERTURNED"

    A.assert_match_point_pool(fx.get_season(api, world["season"]["id"]), 0)
    charged = fx.get_team(api, world["team_a"]["id"])
    credited = fx.get_team(api, world["team_b"]["id"])
    assert charged["match_points"] == 0
    assert charged["forfeits_charged"] == 0
    assert credited["match_points"] == 0
    assert credited["forfeit_wins"] == 0

    assert charged["wins"] == 0
    assert charged["losses"] == 0
    assert charged["draws"] == 0
    assert charged["games_won"] == 0
    assert charged["games_lost"] == 0


def test_the_restored_match_returns_to_scheduled_with_no_result_fields_left(api):
    """An unconfigured match goes back to SCHEDULED, not to SERVER_READY.

    PRD §3.8: "`forfeiting_team_id` is cleared to null, `result_status` returns
    to `AWAITING_REPORTS`, and both `result_confirmed_at` and
    `dispute_deadline_at` return to null. Such a match's `play_status` is
    restored to `SERVER_READY` when its `region_code` had already been pinned
    and to `SCHEDULED` when it had not."  And the fourth link "returns the team
    `SUSPENDED → COMPETING` ... the team's `suspension_reason` is cleared back
    to null."

    Design: Difficulty/compensating_invariant/season_match_point_pool_returns_to_zero_when_the_suspension_forfeit_is_reversed
    """
    world = _build_forfeit_by_suspension_with_pending_appeal(api)

    forfeited = fx.get_match(api, world["match"]["id"])
    A.assert_match_state(
        forfeited, play_status="FORFEITED", result_status="ADJUDICATED"
    )
    assert forfeited["forfeiting_team_id"] == world["team_a"]["id"]
    assert forfeited["winner_team_id"] == world["team_b"]["id"]
    assert forfeited["away_points_awarded"] == 3

    _overturn(api, world)

    restored = fx.get_match(api, world["match"]["id"])
    A.assert_match_state(
        restored, play_status="SCHEDULED", result_status="AWAITING_REPORTS"
    )
    assert restored["forfeiting_team_id"] is None
    assert restored["winner_team_id"] is None
    assert restored["result_confirmed_at"] is None
    assert restored["dispute_deadline_at"] is None
    assert restored["home_points_awarded"] == 0
    assert restored["away_points_awarded"] == 0

    alpha = fx.get_team(api, world["team_a"]["id"])
    assert alpha["status"] == "COMPETING"
    assert alpha["suspension_reason"] is None
    A.assert_integrity_score(alpha["integrity_score"], 100.00)
    A.assert_slot_axes(
        fx.get_slot(api, world["slot_a"]["id"]), participation_status="ACTIVE"
    )
    assert fx.get_student(api, world["student_a"]["id"])["fair_play_status"] == "CLEAR"
