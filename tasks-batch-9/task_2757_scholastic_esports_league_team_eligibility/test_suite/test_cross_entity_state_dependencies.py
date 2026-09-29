"""Depth tests for the two cross-entity state gates.

Instance one gates registration on a TitleApproval the Team never references by
foreign key (PRD §3.6).  Instance two gates a result report on the Season stage
above the Match (PRD §3.7).
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    league_admin_headers,
    make_coach_headers,
)


# ==========================================================================
# Instance: team_registration_blocked_by_revoked_district_title_approval
# ==========================================================================
def _build_registered_alpha_then_revoke_the_approval(api):
    """Alpha registers while the approval stands; Bravo is created without any
    roster slot, and the district then revokes the approval."""
    world = fx.build_draft_team(api, term_gpa=3.100, term_credits=6.0)
    world["slot"] = fx.make_active_starter(
        api, world["team"]["id"], world["coach"]["id"], world["student"], "STARTER"
    )
    world["team"] = fx.register_team(api, world["team"])

    coach_b = fx.make_certified_coach(api, world["school"]["id"])
    bravo = fx.make_team(
        api,
        world["season"]["id"],
        world["school"]["id"],
        world["title"]["id"],
        coach_b["id"],
        name="Bravo",
    )
    approval = fx.decide_title_approval(
        api,
        world["approval"],
        "REVOKE",
        decision_note="publisher rating changed",
    )
    world["coach_b"] = coach_b
    world["bravo"] = bravo
    world["approval"] = approval
    return world


def test_revoked_approval_blocks_registration_before_the_roster_minimum(api):
    """The approval guard is found by matching district and title, not by a key.

    PRD §3.6: "An approval must currently exist in `APPROVED` status linking
    the title the team plays to the district of the team's school — resolved
    through the team's `school_id` to that school's `district_id` — otherwise
    `ERR_TITLE_NOT_DISTRICT_APPROVED`; a `PENDING`, `DENIED` or `REVOKED`
    approval does not qualify. The team's `active_starter_count` must be at
    least the season's `min_starters`, otherwise
    `ERR_ROSTER_MINIMUM_NOT_MET`."  PRD §3.3: "An `action` of `REVOKE` moves
    an `APPROVED` approval to the terminal `REVOKED` state ... All three
    actions write `decided_by_user_id` from `X-User-ID`".

    Design: Difficulty/cross_entity_state_dependency/team_registration_blocked_by_revoked_district_title_approval
    """
    world = _build_registered_alpha_then_revoke_the_approval(api)

    assert world["approval"]["status"] == "REVOKED"
    assert world["approval"]["decided_by_user_id"] == world["district"]["id"]

    response = api.register_team(
        world["bravo"]["id"], {}, make_coach_headers(world["coach_b"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_TITLE_NOT_DISTRICT_APPROVED.value, 409)

    bravo = fx.get_team(api, world["bravo"]["id"])
    assert bravo["status"] == "DRAFT"
    A.assert_cents(bravo["entry_fee_cents"], 0)
    assert bravo["registered_at"] is None


def test_revocation_does_not_retroactively_unregister_the_earlier_team(api):
    """The guard is read at registration time only.

    PRD §3.6: "The entry fee is assembled from **line items** ... Take the
    default figures with a single starting slot: the two line items are 12,510
    and 3,335 cents, a quarter of each is 3,128 and 834 cents after rounding,
    and `subsidy_granted_cents` is therefore 3,962."  And: "the district's
    `subsidy_pool_cents` is reduced by exactly the `subsidy_granted_cents`
    just awarded".

    Design: Difficulty/cross_entity_state_dependency/team_registration_blocked_by_revoked_district_title_approval
    """
    world = _build_registered_alpha_then_revoke_the_approval(api)
    api.register_team(world["bravo"]["id"], {}, make_coach_headers(world["coach_b"]["id"]))

    alpha = fx.get_team(api, world["team"]["id"])
    assert alpha["status"] == "REGISTERED"
    A.assert_cents(alpha["subsidy_granted_cents"], 3962)

    season = fx.get_season(api, world["season"]["id"])
    assert season["registered_team_count"] == 1

    district = fx.get_district(api, world["district"]["id"])
    A.assert_cents(district["subsidy_pool_cents"], 4996038)
    A.assert_subsidy_conserved(district, 3962)


# ==========================================================================
# Instance: result_report_blocked_by_season_still_in_roster_locked_stage
# ==========================================================================
def _build_server_ready_match_in_roster_locked_season(api):
    """Both teams are locked and the season stops at ROSTER_LOCKED, which is
    legal for server configuration but not for reporting."""
    world = fx.build_two_team_season(
        api,
        title_kwargs={"server_pool_capacity": 2},
        advance_to_regular_season=False,
    )
    season = fx.advance_season(api, world["season"]["id"], "ROSTER_LOCKED")
    match = fx.schedule_match(
        api,
        season["id"],
        world["team_a"]["id"],
        world["team_b"]["id"],
        "2026-09-25T18:00:00.000Z",
    )
    world["season"] = season
    world["match"] = fx.configure_server(api, match["id"])
    return world


def _report_payload(world):
    return {
        "reporting_team_id": world["team_a"]["id"],
        "home_games_won": 2,
        "away_games_won": 1,
        "expected_match_version": world["match"]["version"],
    }


def test_result_report_is_refused_while_the_season_sits_at_roster_locked(api):
    """Two adjacent endpoints read the same Season field to opposite ends.

    PRD §3.7: "The match must be in `SCHEDULED`, otherwise
    `ERR_INVALID_MATCH_STATE`, and the season must be in `ROSTER_LOCKED`,
    `REGULAR_SEASON` or `PLAYOFFS`, otherwise `ERR_INVALID_SEASON_STAGE`" for
    server configuration, whereas for a report "the season must be in
    `REGULAR_SEASON` or `PLAYOFFS`, otherwise `ERR_INVALID_SEASON_STAGE`".

    Design: Difficulty/cross_entity_state_dependency/result_report_blocked_by_season_still_in_roster_locked_stage
    """
    world = _build_server_ready_match_in_roster_locked_season(api)
    assert fx.get_season(api, world["season"]["id"])["status"] == "ROSTER_LOCKED"
    assert world["match"]["play_status"] == "SERVER_READY"

    response = api.report_result(
        world["match"]["id"],
        _report_payload(world),
        make_coach_headers(world["team_a"]["coach_id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_SEASON_STAGE.value, 409)

    match = fx.get_match(api, world["match"]["id"])
    A.assert_match_state(
        match, play_status="SERVER_READY", result_status="AWAITING_REPORTS"
    )
    assert match["home_reported_home_games_won"] is None
    A.assert_version_is(match, world["match"]["version"])


def test_the_same_report_succeeds_once_the_season_reaches_regular_season(api):
    """The byte-identical call, version guard included, then lands.

    PRD §3.7: "The first of the two reports moves `result_status` from
    `AWAITING_REPORTS` to `PARTIALLY_REPORTED` and does nothing else beyond
    incrementing the match's `version`."  And: "A report from the home side is
    stored as `home_reported_home_games_won` and
    `home_reported_away_games_won`".  PRD §3.4: "`ROSTER_LOCKED →
    REGULAR_SEASON` cascades downward: every team in the season whose status is
    `ROSTER_LOCKED` automatically transitions to `COMPETING`".

    Design: Difficulty/cross_entity_state_dependency/result_report_blocked_by_season_still_in_roster_locked_stage
    """
    world = _build_server_ready_match_in_roster_locked_season(api)
    api.report_result(
        world["match"]["id"],
        _report_payload(world),
        make_coach_headers(world["team_a"]["coach_id"]),
    )

    advanced = api.advance_season(
        world["season"]["id"], {"to_status": "REGULAR_SEASON"}, league_admin_headers()
    )
    validate_success(advanced)
    assert A.data_of(advanced)["status"] == "REGULAR_SEASON"
    assert fx.get_team(api, world["team_a"]["id"])["status"] == "COMPETING"
    assert fx.get_team(api, world["team_b"]["id"])["status"] == "COMPETING"

    retried = api.report_result(
        world["match"]["id"],
        _report_payload(world),
        make_coach_headers(world["team_a"]["coach_id"]),
    )
    validate_success(retried)
    match = A.data_of(retried)
    assert match["result_status"] == "PARTIALLY_REPORTED"
    assert match["home_reported_home_games_won"] == 2
    assert match["home_reported_away_games_won"] == 1

    season = fx.get_season(api, world["season"]["id"])
    A.assert_match_point_pool(season, 0)
