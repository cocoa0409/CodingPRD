"""Depth tests for the two genuine state-machine cycles.

Instance one cycles ``Team.status`` COMPETING → SUSPENDED → COMPETING through a
sustain and an overturned appeal (PRD §3.8).  Instance two cycles
``Match.dispute_status`` UNDER_REVIEW ↔ NEEDS_INFO twice before rejecting
(PRD §3.7).
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
    league_admin_headers,
)


# ==========================================================================
# Instance: team_competing_suspended_competing_cycle_via_sustain_then_appeal_
#           overturn
# ==========================================================================
def _build_suspended_alpha_with_pending_appeal(api):
    """Two COMPETING teams; Alpha's only starter is sanctioned, which starves
    the roster and drives Alpha into SUSPENDED, and Alpha's coach has already
    lodged the appeal."""
    world = fx.build_two_team_season(api)
    alpha = world["team_a"]
    case = fx.open_student_case(
        api, alpha["id"], world["student_a"]["id"], case_type="ACCOUNT_SHARING"
    )
    fx.investigate_case(api, case["id"], officer_id=INTEGRITY_OFFICER_ID)
    case = fx.decide_case(
        api,
        case["id"],
        decision="SUSTAIN",
        severity="MINOR",
        officer_id=INTEGRITY_OFFICER_ID_2,
    )
    case = fx.appeal_case(
        api,
        case,
        world["coach_a"]["id"],
        appeal_grounds="device was shared by a sibling, not an account transfer",
    )
    world["case"] = case
    return world


def test_sustain_starves_the_roster_and_the_appeal_holds_the_sanction_in_force(api):
    """Entering the cycle: COMPETING → SUSPENDED, and APPEALED does not undo it.

    PRD §3.8: "The fourth link, caused by the third, moves the charged team
    `COMPETING → SUSPENDED` when any of three things is true: the team's
    `active_starter_count` has fallen below the season's `min_starters` ... The
    team's `suspension_reason` records which of those it was —
    `ROSTER_MINIMUM_BREACH`".  And: "The case moves `SUSTAINED → APPEALED` and
    **all sanctions remain in force** while the appeal is pending — the case
    stays in the penalty set and nothing is restored yet."

    Design: Difficulty/non_linear_state_machine/team_competing_suspended_competing_cycle_via_sustain_then_appeal_overturn
    """
    world = _build_suspended_alpha_with_pending_appeal(api)

    assert world["case"]["status"] == "APPEALED"

    alpha = fx.get_team(api, world["team_a"]["id"])
    assert alpha["status"] == "SUSPENDED"
    assert alpha["suspension_reason"] == "ROSTER_MINIMUM_BREACH"
    assert alpha["active_starter_count"] == 0
    A.assert_integrity_score(alpha["integrity_score"], 90.00)

    slot = fx.get_slot(api, world["slot_a"]["id"])
    A.assert_slot_axes(slot, participation_status="INELIGIBLE")
    assert slot["ineligibility_reason"] == "FAIR_PLAY"

    bravo = fx.get_team(api, world["team_b"]["id"])
    assert bravo["status"] == "COMPETING"
    A.assert_integrity_score(bravo["integrity_score"], 100.00)


def test_overturned_appeal_returns_the_team_to_the_state_it_previously_held(api):
    """Exiting the cycle: SUSPENDED → COMPETING, the same state as before.

    PRD §3.8: "`OVERTURN` moves the case `APPEALED → OVERTURNED` and runs a
    five-link compensation that is the exact inverse of the sustain cascade."
    "The second link ... returns that student's `fair_play_status` to
    `CLEAR`".  "The third link ... returns every roster slot of that student
    whose `participation_status` is `INELIGIBLE` with `ineligibility_reason`
    `FAIR_PLAY` back to `ACTIVE`, clearing `ineligibility_reason` — provided
    the slot's own two axes still stand at `ENROLLMENT_VERIFIED` and
    `CLEARED`".  "The fourth link ... returns the team `SUSPENDED →
    COMPETING` once its `active_starter_count` is again at least the season's
    `min_starters` and no other case against it remains sustained with a
    `TEAM_SUSPENSION` or `DISQUALIFICATION` sanction; the team's
    `suspension_reason` is cleared back to null."

    Design: Difficulty/non_linear_state_machine/team_competing_suspended_competing_cycle_via_sustain_then_appeal_overturn
    """
    world = _build_suspended_alpha_with_pending_appeal(api)

    response = api.decide_appeal(
        world["case"]["id"],
        {"decision": "OVERTURN", "appeal_note": "grounds accepted"},
        integrity_officer_headers(INTEGRITY_OFFICER_ID_3),
    )
    validate_success(response)
    case = A.data_of(response)
    assert case["status"] == "OVERTURNED"
    assert case["appeal_decider_user_id"] == INTEGRITY_OFFICER_ID_3
    assert case["sanction_type"] == "NONE"

    student = fx.get_student(api, world["student_a"]["id"])
    assert student["fair_play_status"] == "CLEAR"

    slot = fx.get_slot(api, world["slot_a"]["id"])
    A.assert_slot_axes(
        slot,
        verification_status="ENROLLMENT_VERIFIED",
        academic_status="CLEARED",
        participation_status="ACTIVE",
    )
    assert slot["ineligibility_reason"] is None

    alpha = fx.get_team(api, world["team_a"]["id"])
    assert alpha["status"] == "COMPETING"
    assert alpha["suspension_reason"] is None
    assert alpha["active_starter_count"] == 1
    A.assert_integrity_score(alpha["integrity_score"], 100.00)


# ==========================================================================
# Instance: dispute_under_review_needs_info_cycled_twice_then_rejected
# ==========================================================================
def _build_dispute_in_needs_info(api):
    """A forfeited match whose dispute has already been accepted for review,
    pushed to NEEDS_INFO, resumed, and pushed to NEEDS_INFO a second time."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])

    coach_a = fx.make_coach(api, school["id"])
    coach_b = fx.make_coach(api, school["id"])
    alpha = fx.make_team(api, season["id"], school["id"], title["id"], coach_a["id"], name="Alpha")
    bravo = fx.make_team(api, season["id"], school["id"], title["id"], coach_b["id"], name="Bravo")

    match = fx.schedule_match(
        api, season["id"], alpha["id"], bravo["id"], "2026-09-25T18:00:00.000Z"
    )
    fx.forfeit_match(api, match["id"], bravo["id"], reason_note="no show")
    fx.file_dispute(
        api,
        match["id"],
        alpha,
        dispute_reason_code="SERVER_FAULT",
        dispute_note="opponent claims a server outage",
    )
    fx.dispute_action(api, match["id"], "ACCEPT_REVIEW")
    fx.dispute_action(
        api, match["id"], "REQUEST_INFO", info_request_note="send the server log"
    )
    fx.dispute_action(api, match["id"], "RESUME_REVIEW")
    fx.dispute_action(
        api, match["id"], "REQUEST_INFO", info_request_note="log is unreadable, resend"
    )
    return {
        "district": district,
        "school": school,
        "season": season,
        "alpha": alpha,
        "bravo": bravo,
        "match": fx.get_match(api, match["id"]),
    }


def test_reject_is_illegal_from_needs_info_and_legal_after_resuming_review(api):
    """The cycle has no iteration cap, and NEEDS_INFO is not a decision state.

    PRD §3.7: "`REQUEST_INFO` moves `UNDER_REVIEW → NEEDS_INFO` and may carry
    an `info_request_note`. `RESUME_REVIEW` moves `NEEDS_INFO → UNDER_REVIEW`.
    That pair forms a **cycle** which may repeat any number of times before a
    decision is reached. Any action attempted from a state other than its
    declared from-state is refused with `ERR_INVALID_DISPUTE_STATE`."  And:
    "`REJECT` moves `UNDER_REVIEW → REJECTED`".

    Design: Difficulty/non_linear_state_machine/dispute_under_review_needs_info_cycled_twice_then_rejected
    """
    world = _build_dispute_in_needs_info(api)
    match_id = world["match"]["id"]

    rejected_early = api.dispute_action(
        match_id, {"action": "REJECT"}, league_admin_headers()
    )
    validate_error(rejected_early, ApiErrorId.ERR_INVALID_DISPUTE_STATE.value, 409)
    assert fx.get_match(api, match_id)["dispute_status"] == "NEEDS_INFO"

    resumed = api.dispute_action(
        match_id, {"action": "RESUME_REVIEW"}, league_admin_headers()
    )
    validate_success(resumed)
    assert A.data_of(resumed)["dispute_status"] == "UNDER_REVIEW"

    rejected = api.dispute_action(
        match_id, {"action": "REJECT"}, league_admin_headers()
    )
    validate_success(rejected)
    assert A.data_of(rejected)["dispute_status"] == "REJECTED"


def test_rejecting_the_cycled_dispute_moves_no_result_and_no_points(api):
    """A REJECT terminates the cycle without restating anything.

    PRD §3.7: "`REJECT` moves `UNDER_REVIEW → REJECTED` and must carry neither
    corrected count, otherwise `ERR_INVALID_REQUEST`. Nothing but
    `dispute_status` changes: the result stands, the points stand, and no
    team, season or student figure moves."  The forfeit award is that "The
    non-forfeiting side is credited 3 points and the forfeiting side 0; the
    winning side's `forfeit_wins` rises by one and the forfeiting side's
    `forfeits_charged` rises by one".

    Design: Difficulty/non_linear_state_machine/dispute_under_review_needs_info_cycled_twice_then_rejected
    """
    world = _build_dispute_in_needs_info(api)
    match_id = world["match"]["id"]
    fx.dispute_action(api, match_id, "RESUME_REVIEW")
    fx.dispute_action(api, match_id, "REJECT")

    match = fx.get_match(api, match_id)
    A.assert_match_state(
        match,
        play_status="FORFEITED",
        result_status="ADJUDICATED",
        dispute_status="REJECTED",
    )
    assert match["winner_team_id"] == world["alpha"]["id"]
    assert match["home_points_awarded"] == 3
    assert match["away_points_awarded"] == 0
    assert match["dispute_filed_by_team_id"] == world["alpha"]["id"]
    assert match["dispute_deadline_at"] == "2026-08-03T00:00:00.000Z"

    alpha = fx.get_team(api, world["alpha"]["id"])
    assert alpha["match_points"] == 3
    assert alpha["forfeit_wins"] == 1
    bravo = fx.get_team(api, world["bravo"]["id"])
    assert bravo["match_points"] == 0
    assert bravo["forfeits_charged"] == 1

    season = fx.get_season(api, world["season"]["id"])
    A.assert_match_point_pool(season, 3)
