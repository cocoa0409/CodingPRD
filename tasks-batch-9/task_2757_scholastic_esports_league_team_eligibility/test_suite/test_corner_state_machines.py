"""Breadth tests for the ``state_machines`` design section.

Six machines carry state in this domain — TitleApproval, Season, Team,
RosterSlot, FairPlayCase and the Match with its four independent axes — and this
module walks their initial states, their illegal from-states, their terminal
lockdowns, their declared happy paths, their guards and their cascades
(PRD §2.7 rungs 12 and 14 through 21, §3.3 through §3.8).
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ELIGIBILITY_OFFICER_ID,
    ELIGIBILITY_OFFICER_ID_2,
    INTEGRITY_OFFICER_ID,
    INTEGRITY_OFFICER_ID_2,
    eligibility_officer_headers,
    integrity_officer_headers,
    league_admin_headers,
    make_athletic_director_headers,
    make_coach_headers,
    make_district_admin_headers,
)


# ==========================================================================
# Instance: initial_states_are_pinned_for_every_entity_with_a_state_machine
# ==========================================================================
def _build_one_of_every_machine(api):
    """One live record for each of the six machines, all freshly created and
    none of them yet transitioned."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach_a = fx.make_coach(api, school["id"])
    coach_b = fx.make_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    approval = fx.request_title_approval(
        api, district["id"], title["id"], school["id"]
    )
    student = fx.make_student(api, school["id"])
    team_a = fx.make_team(
        api, season["id"], school["id"], title["id"], coach_a["id"], name="Alpha"
    )
    team_b = fx.make_team(
        api, season["id"], school["id"], title["id"], coach_b["id"], name="Bravo"
    )
    slot = fx.add_slot(api, team_a["id"], student["id"], coach_a["id"], "STARTER")
    match = fx.schedule_match(
        api, season["id"], team_a["id"], team_b["id"], "2026-10-01T18:00:00.000Z"
    )
    case = fx.open_student_case(api, team_a["id"], student["id"])
    return {
        "district": district,
        "school": school,
        "coach_a": coach_a,
        "coach_b": coach_b,
        "title": title,
        "season": season,
        "approval": approval,
        "student": student,
        "team_a": team_a,
        "team_b": team_b,
        "slot": slot,
        "match": match,
        "case": case,
    }


def test_approval_season_team_and_slot_open_at_their_declared_initial_states(api):
    """Four machines, four pinned initial states, nothing left null-by-default.

    PRD §3.3: "The request begins with `status` `PENDING`, with
    `decided_by_user_id`, `decided_at` and `decision_note` all null."
    PRD §3.4: "`status` begins at `DRAFT` and walks through
    `REGISTRATION_OPEN`, `ROSTER_LOCKED`, `REGULAR_SEASON`, `PLAYOFFS` and the
    terminal `COMPLETE`. `seeding_state` begins at `UNSEEDED` and thereafter
    alternates between `SEEDED` and `STALE` as results change."  PRD §3.5: "A
    new team's `status` is `DRAFT` ... Both
    `registered_at` and `roster_locked_at` are null at creation."  And: "A fresh
    slot begins with `verification_status` `UNVERIFIED`, `academic_status`
    `PENDING`, `participation_status` `PROSPECTIVE`, `released_at` and
    `ineligibility_reason` null, and both verifier identifiers null".

    Design: Corner/state_machines/initial_states_are_pinned_for_every_entity_with_a_state_machine
    """
    world = _build_one_of_every_machine(api)

    approval = fx.get_title_approval(api, world["approval"]["id"])
    assert approval["status"] == "PENDING"
    assert approval["decided_by_user_id"] is None
    assert approval["decided_at"] is None
    assert approval["decision_note"] is None

    season = fx.get_season(api, world["season"]["id"])
    assert season["status"] == "DRAFT"
    assert season["seeding_state"] == "UNSEEDED"

    team = fx.get_team(api, world["team_a"]["id"])
    assert team["status"] == "DRAFT"
    assert team["registered_at"] is None
    assert team["roster_locked_at"] is None

    slot = fx.get_slot(api, world["slot"]["id"])
    A.assert_slot_axes(
        slot,
        verification_status="UNVERIFIED",
        academic_status="PENDING",
        participation_status="PROSPECTIVE",
    )
    assert slot["released_at"] is None
    assert slot["ineligibility_reason"] is None
    assert slot["enrollment_verified_by_user_id"] is None
    assert slot["academics_verified_by_user_id"] is None


def test_a_new_match_pins_all_four_axes_and_a_new_case_carries_no_penalty(api):
    """The Match machine has four independent initial dimensions, and a
    REPORTED case has not yet touched the team it charges.

    PRD §3.7: "A newly scheduled match sits at `SCHEDULED`,
    `AWAITING_REPORTS`, `NONE` and `NONE` respectively."  And: "`region_code`
    and `patch_version` are null until the server is configured."  PRD §3.8: "A
    new case opens in `REPORTED` with `reported_by_user_id` taken from
    `X-User-ID`, `severity` null, `sanction_type` `NONE`, `severity_weight` 0,
    `applied_penalty` 0, `repeat_index` null, and `appeal_grounds`,
    `decided_at` and all three later decision identifiers null."  PRD §3.5:
    "`integrity_score` at 100.00".

    Design: Corner/state_machines/initial_states_are_pinned_for_every_entity_with_a_state_machine
    """
    world = _build_one_of_every_machine(api)

    match = fx.get_match(api, world["match"]["id"])
    A.assert_match_state(
        match,
        play_status="SCHEDULED",
        result_status="AWAITING_REPORTS",
        dispute_status="NONE",
        broadcast_status="NONE",
    )
    assert match["spectator_strikes"] == 0
    assert match["region_code"] is None
    assert match["patch_version"] is None

    case = fx.get_case(api, world["case"]["id"])
    assert case["status"] == "REPORTED"
    assert case["reported_by_user_id"] == INTEGRITY_OFFICER_ID
    assert case["severity"] is None
    assert case["sanction_type"] == "NONE"
    assert case["severity_weight"] == 0
    assert float(case["applied_penalty"]) == 0
    assert case["repeat_index"] is None
    assert case["appeal_grounds"] is None
    assert case["decided_at"] is None
    assert case["investigator_user_id"] is None
    assert case["decider_user_id"] is None
    assert case["appeal_decider_user_id"] is None

    A.assert_integrity_score(
        fx.get_team(api, world["team_a"]["id"])["integrity_score"], 100.00
    )


# ==========================================================================
# Instance: transitions_from_an_illegal_from_state_are_refused
# ==========================================================================
def test_four_machines_refuse_a_transition_from_an_illegal_from_state(api):
    """Four from-state rungs, four distinct conflict errors, no state moved.

    PRD §2.7 rung 12: "**Season stage.** The season is in a stage that permits
    the operation — otherwise `ERR_INVALID_SEASON_STAGE`. Registration requires
    `REGISTRATION_OPEN`; a stage advance requires the declared from-stage".
    Rung 17: "**Match play and result state,** otherwise
    `ERR_INVALID_MATCH_STATE`. ... finalization requires `play_status` `PLAYED`
    with `result_status` either `CONFIRMED`, `ADJUDICATED` or `CONTESTED`".
    Rung 18: "**Dispute from-state,** otherwise `ERR_INVALID_DISPUTE_STATE`.
    Filing requires `NONE`; `ACCEPT_REVIEW` requires `OPEN`".  Rung 21:
    "**Title-approval from-state,** otherwise `ERR_INVALID_APPROVAL_STATE`.
    `APPROVE` and `DENY` require `PENDING`; `REVOKE` requires `APPROVED`."

    Design: Corner/state_machines/transitions_from_an_illegal_from_state_are_refused
    """
    world = _build_one_of_every_machine(api)
    season_before = fx.get_season(api, world["season"]["id"])
    match_before = fx.get_match(api, world["match"]["id"])
    approval_before = fx.get_title_approval(api, world["approval"]["id"])

    skipped_stage = api.advance_season(
        world["season"]["id"], {"to_status": "REGULAR_SEASON"}, league_admin_headers()
    )
    validate_error(skipped_stage, ApiErrorId.ERR_INVALID_SEASON_STAGE.value, 409)
    season = fx.get_season(api, world["season"]["id"])
    assert season["status"] == "DRAFT"
    A.assert_version_is(season, season_before["version"])

    early_finalize = api.finalize_match(
        world["match"]["id"], {}, league_admin_headers()
    )
    validate_error(early_finalize, ApiErrorId.ERR_INVALID_MATCH_STATE.value, 409)

    early_review = api.dispute_action(
        world["match"]["id"], {"action": "ACCEPT_REVIEW"}, league_admin_headers()
    )
    validate_error(early_review, ApiErrorId.ERR_INVALID_DISPUTE_STATE.value, 409)
    match = fx.get_match(api, world["match"]["id"])
    A.assert_match_state(match, play_status="SCHEDULED", dispute_status="NONE")
    A.assert_version_is(match, match_before["version"])

    early_revoke = api.decide_title_approval(
        world["approval"]["id"],
        {"action": "REVOKE"},
        make_district_admin_headers(world["district"]["id"]),
    )
    validate_error(early_revoke, ApiErrorId.ERR_INVALID_APPROVAL_STATE.value, 409)
    approval = fx.get_title_approval(api, world["approval"]["id"])
    assert approval["status"] == "PENDING"
    assert approval["decided_at"] is None
    A.assert_version_is(approval, approval_before["version"])


# ==========================================================================
# Instance: repeating_a_completed_transition_returns_its_invalid_state_error
# ==========================================================================
def test_replaying_a_completed_transition_returns_the_machines_own_error(api):
    """These three transitions are single-shot, not idempotent.

    PRD §3.3: "Attempting to approve or deny something that is not `PENDING`,
    or to revoke something that is not `APPROVED`, is refused with
    `ERR_INVALID_APPROVAL_STATE`."  PRD §3.8: "An integrity officer takes the
    case ... which moves it `REPORTED → INVESTIGATING` and writes
    `investigator_user_id` from `X-User-ID`. Any other from-state is refused
    with `ERR_INVALID_CASE_STATE`."  PRD §3.5: "Releasing is refused with
    `ERR_ROSTER_LOCKED` once the team has locked, and with
    `ERR_ROSTER_SLOT_RELEASED` if the slot is already released — `RELEASED` is
    terminal and nothing further can be done to the slot."

    Design: Corner/state_machines/repeating_a_completed_transition_returns_its_invalid_state_error
    """
    world = _build_one_of_every_machine(api)
    approval = fx.decide_title_approval(
        api, world["approval"], "APPROVE", decision_note="board minutes 2026-07"
    )
    assert approval["status"] == "APPROVED"
    fx.investigate_case(api, world["case"]["id"], officer_id=INTEGRITY_OFFICER_ID)
    coach_headers = make_coach_headers(world["coach_a"]["id"])
    first_release = api.release_roster_slot(
        world["slot"]["id"], {"release_note": "left the school"}, coach_headers
    )
    validate_success(first_release)
    released = A.data_of(first_release)
    A.assert_slot_axes(released, participation_status="RELEASED")
    assert released["released_at"] == "2026-08-01T00:00:00.000Z"

    replay_approve = api.decide_title_approval(
        world["approval"]["id"],
        {"action": "APPROVE"},
        make_district_admin_headers(world["district"]["id"]),
    )
    validate_error(replay_approve, ApiErrorId.ERR_INVALID_APPROVAL_STATE.value, 409)
    assert (
        fx.get_title_approval(api, world["approval"]["id"])["decision_note"]
        == "board minutes 2026-07"
    )

    replay_investigate = api.investigate_case(
        world["case"]["id"],
        {"investigation_note": "second pass"},
        integrity_officer_headers(INTEGRITY_OFFICER_ID_2),
    )
    validate_error(replay_investigate, ApiErrorId.ERR_INVALID_CASE_STATE.value, 409)
    case = fx.get_case(api, world["case"]["id"])
    assert case["status"] == "INVESTIGATING"
    assert case["investigator_user_id"] == INTEGRITY_OFFICER_ID

    replay_release = api.release_roster_slot(
        world["slot"]["id"], {"release_note": "again"}, coach_headers
    )
    validate_error(replay_release, ApiErrorId.ERR_ROSTER_SLOT_RELEASED.value, 409)
    assert (
        fx.get_slot(api, world["slot"]["id"])["released_at"]
        == "2026-08-01T00:00:00.000Z"
    )

    team = fx.get_team(api, world["team_a"]["id"])
    assert team["starter_slots_used"] == 0
    assert team["starter_slots_available"] == 3
    A.assert_starter_capacity_conserved(team, 3)


# ==========================================================================
# Instance: terminal_states_reject_every_further_transition
# ==========================================================================
def test_a_denied_approval_and_a_dismissed_case_refuse_every_further_move(api):
    """Two terminal states on two machines, each refusing its own next step.

    PRD §3.3: "An `action` of `DENY` moves a `PENDING` approval to the terminal
    `DENIED` state and applies no rating test, since denial is always
    permissible."  And: "Attempting to approve or deny something that is not
    `PENDING`, or to revoke something that is not `APPROVED`, is refused with
    `ERR_INVALID_APPROVAL_STATE`."  PRD §3.8: "The charged team's coach may
    appeal a sustained case, supplying written `appeal_grounds`. The case must
    be in `SUSTAINED`, otherwise `ERR_INVALID_CASE_STATE`".

    Design: Corner/state_machines/terminal_states_reject_every_further_transition
    """
    world = _build_one_of_every_machine(api)
    denied = fx.decide_title_approval(
        api, world["approval"], "DENY", decision_note="not on the district list"
    )
    assert denied["status"] == "DENIED"
    fx.investigate_case(api, world["case"]["id"], officer_id=INTEGRITY_OFFICER_ID)
    dismissed = fx.decide_case(
        api,
        world["case"]["id"],
        decision="DISMISS",
        officer_id=INTEGRITY_OFFICER_ID_2,
    )
    assert dismissed["status"] == "DISMISSED"

    revoke_terminal = api.decide_title_approval(
        world["approval"]["id"],
        {"action": "REVOKE"},
        make_district_admin_headers(world["district"]["id"]),
    )
    validate_error(revoke_terminal, ApiErrorId.ERR_INVALID_APPROVAL_STATE.value, 409)
    assert fx.get_title_approval(api, world["approval"]["id"])["status"] == "DENIED"

    appeal_terminal = api.appeal_case(
        world["case"]["id"],
        {"appeal_grounds": "we dispute the dismissal reasoning"},
        make_coach_headers(world["coach_a"]["id"]),
    )
    validate_error(appeal_terminal, ApiErrorId.ERR_INVALID_CASE_STATE.value, 409)
    case = fx.get_case(api, world["case"]["id"])
    assert case["status"] == "DISMISSED"
    assert case["appeal_grounds"] is None


def _build_forfeited_match_in_a_running_season(api):
    """Bravo forfeits its only match to Alpha, which parks the match on the
    terminal ``FORFEITED`` value of the play axis."""
    world = fx.build_two_team_season(api)
    match = fx.schedule_match(
        api,
        world["season"]["id"],
        world["team_a"]["id"],
        world["team_b"]["id"],
        "2026-09-25T18:00:00.000Z",
    )
    world["match"] = fx.forfeit_match(
        api, match["id"], world["team_b"]["id"], reason_note="no show"
    )
    return world


def test_a_forfeited_match_refuses_a_second_forfeit_and_a_server_setup(api):
    """The forfeit endpoint's own from-state list looks permissive, and
    ``FORFEITED`` is in neither of its two entries.

    PRD §2.7 rung 17: "**Match play and result state,** otherwise
    `ERR_INVALID_MATCH_STATE`. Server configuration requires `play_status`
    `SCHEDULED`; ... a forfeit requires `SCHEDULED` or `SERVER_READY`".
    PRD §3.7: "the match must be in `SCHEDULED` or `SERVER_READY`, otherwise
    `ERR_INVALID_MATCH_STATE`".  And: "The non-forfeiting side is credited 3
    points and the forfeiting side 0; the winning side's `forfeit_wins` rises by
    one and the forfeiting side's `forfeits_charged` rises by one".

    Design: Corner/state_machines/terminal_states_reject_every_further_transition
    """
    world = _build_forfeited_match_in_a_running_season(api)
    A.assert_match_state(
        world["match"], play_status="FORFEITED", result_status="ADJUDICATED"
    )

    second_forfeit = api.forfeit_match(
        world["match"]["id"],
        {"forfeiting_team_id": world["team_a"]["id"]},
        league_admin_headers(),
    )
    validate_error(second_forfeit, ApiErrorId.ERR_INVALID_MATCH_STATE.value, 409)

    late_config = api.configure_server(
        world["match"]["id"],
        {"region_code": "US-WEST-2", "patch_version": "3.14.1"},
        league_admin_headers(),
    )
    validate_error(late_config, ApiErrorId.ERR_INVALID_MATCH_STATE.value, 409)

    match = fx.get_match(api, world["match"]["id"])
    A.assert_match_state(match, play_status="FORFEITED")
    assert match["forfeiting_team_id"] == world["team_b"]["id"]
    assert match["winner_team_id"] == world["team_a"]["id"]
    assert match["region_code"] is None
    assert match["patch_version"] is None

    winner = fx.get_team(api, world["team_a"]["id"])
    loser = fx.get_team(api, world["team_b"]["id"])
    assert winner["match_points"] == 3
    assert winner["forfeit_wins"] == 1
    assert loser["match_points"] == 0
    assert loser["forfeits_charged"] == 1
    A.assert_match_point_pool(fx.get_season(api, world["season"]["id"]), 3)


# ==========================================================================
# Instance: season_regular_season_advance_cascades_only_roster_locked_teams
# ==========================================================================
def _build_three_registered_teams_two_of_them_locked(api):
    """Alpha and Bravo reach ROSTER_LOCKED; Charlie registers and stops there.
    The season is then advanced to ROSTER_LOCKED itself."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    title = fx.make_title(api)
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(api, title["id"])
    season = fx.open_registration(api, season["id"])

    teams = {}
    for label in ("Alpha", "Bravo", "Charlie"):
        coach = fx.make_certified_coach(api, school["id"])
        student = fx.make_student_with_term(
            api, school["id"], term_gpa=3.100, term_credits=6.0
        )
        team = fx.make_team(
            api, season["id"], school["id"], title["id"], coach["id"], name=label
        )
        fx.make_active_starter(api, team["id"], coach["id"], student, "STARTER")
        teams[label] = fx.register_team(api, team)

    for label in ("Alpha", "Bravo"):
        teams[label] = fx.lock_roster(api, teams[label])
    season = fx.advance_season(api, season["id"], "ROSTER_LOCKED")
    return {"season": season, "teams": teams}


def test_regular_season_advance_cascades_only_the_roster_locked_teams(api):
    """The cascade is selective: the team that never locked stays REGISTERED.

    PRD §3.4: "`ROSTER_LOCKED → REGULAR_SEASON` cascades downward: every team in
    the season whose status is `ROSTER_LOCKED` automatically transitions to
    `COMPETING`, each such team advancing its own `version`."  And: "Teams still
    sitting in `REGISTERED` when this advance fires are deliberately left
    untouched — they missed the lock and will not compete."  And:
    "`registered_team_count` begins at 0 and counts the season's teams whose
    status is anything other than `DRAFT` or `WITHDRAWN`."

    Design: Corner/state_machines/season_regular_season_advance_cascades_only_roster_locked_teams
    """
    world = _build_three_registered_teams_two_of_them_locked(api)

    response = api.advance_season(
        world["season"]["id"], {"to_status": "REGULAR_SEASON"}, league_admin_headers()
    )
    validate_success(response)
    assert A.data_of(response)["status"] == "REGULAR_SEASON"

    for label in ("Alpha", "Bravo"):
        assert fx.get_team(api, world["teams"][label]["id"])["status"] == "COMPETING"

    charlie = fx.get_team(api, world["teams"]["Charlie"]["id"])
    assert charlie["status"] == "REGISTERED"
    assert charlie["roster_locked_at"] is None

    season = fx.get_season(api, world["season"]["id"])
    assert season["registered_team_count"] == 3

    alpha = fx.get_team(api, world["teams"]["Alpha"]["id"])
    assert alpha["match_points"] == 0
    assert alpha["seed_position"] is None
    assert alpha["seed_stale"] is False


# ==========================================================================
# Instance: team_withdrawal_cascades_down_to_slots_matches_and_season_counters
# ==========================================================================
def _build_registered_team_with_two_slots_and_two_matches(api):
    """Alpha holds one ACTIVE and one PROSPECTIVE starter slot and is booked
    against Bravo, while Charlie and Delta are booked against each other on a
    later day — a match the withdrawal must not touch."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    title = fx.make_title(api)
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(api, title["id"])
    season = fx.open_registration(api, season["id"])

    coach_a = fx.make_certified_coach(api, school["id"])
    student_one = fx.make_student_with_term(
        api, school["id"], term_gpa=3.100, term_credits=6.0
    )
    student_two = fx.make_student(api, school["id"], birthdate="2009-06-15")
    alpha = fx.make_team(
        api, season["id"], school["id"], title["id"], coach_a["id"], name="Alpha"
    )
    slot_one = fx.make_active_starter(
        api, alpha["id"], coach_a["id"], student_one, "STARTER"
    )
    slot_two = fx.add_slot(
        api, alpha["id"], student_two["id"], coach_a["id"], "STARTER"
    )
    alpha = fx.register_team(api, alpha)

    others = {}
    for label in ("Bravo", "Charlie", "Delta"):
        coach = fx.make_coach(api, school["id"])
        others[label] = fx.make_team(
            api, season["id"], school["id"], title["id"], coach["id"], name=label
        )

    own_match = fx.schedule_match(
        api, season["id"], alpha["id"], others["Bravo"]["id"], "2026-10-01T18:00:00.000Z"
    )
    other_match = fx.schedule_match(
        api,
        season["id"],
        others["Charlie"]["id"],
        others["Delta"]["id"],
        "2026-10-02T18:00:00.000Z",
    )
    return {
        "district": district,
        "season": season,
        "alpha": alpha,
        "others": others,
        "slot_one": slot_one,
        "slot_two": slot_two,
        "own_match": own_match,
        "other_match": other_match,
    }


def test_withdrawal_fans_out_to_slots_matches_and_season_counters(api):
    """One call reaches four entities, and stops at the team's own children.

    PRD §3.6: "Every roster slot on the team whose `participation_status` is not
    already `RELEASED` transitions to `RELEASED`. Every match of the team whose
    `play_status` is `SCHEDULED` or `SERVER_READY` transitions to `FORFEITED`
    with `forfeiting_team_id` set to the withdrawing team, carrying the full
    forfeit award described in §3.7. The season's `registered_team_count` is
    recomputed ... The team's status becomes the terminal `WITHDRAWN` and its
    `version` increments by one."  PRD §3.7: "`play_status` becomes
    `FORFEITED`, `result_status` becomes `ADJUDICATED`, `winner_team_id` becomes
    the other team".

    Design: Corner/state_machines/team_withdrawal_cascades_down_to_slots_matches_and_season_counters
    """
    world = _build_registered_team_with_two_slots_and_two_matches(api)

    response = api.withdraw_team(
        world["alpha"]["id"],
        {"withdrawal_note": "school pulled the program"},
        make_athletic_director_headers(world["alpha"]["school_id"]),
    )
    validate_success(response)
    withdrawn = A.data_of(response)
    assert withdrawn["status"] == "WITHDRAWN"
    A.assert_version_advanced_by(world["alpha"], withdrawn, 1)

    for slot in (world["slot_one"], world["slot_two"]):
        released = fx.get_slot(api, slot["id"])
        A.assert_slot_axes(released, participation_status="RELEASED")
        assert released["released_at"] == "2026-08-01T00:00:00.000Z"

    forfeited = fx.get_match(api, world["own_match"]["id"])
    A.assert_match_state(
        forfeited, play_status="FORFEITED", result_status="ADJUDICATED"
    )
    assert forfeited["forfeiting_team_id"] == world["alpha"]["id"]
    assert forfeited["winner_team_id"] == world["others"]["Bravo"]["id"]

    bravo = fx.get_team(api, world["others"]["Bravo"]["id"])
    assert bravo["match_points"] == 3
    assert bravo["forfeit_wins"] == 1
    assert withdrawn["forfeits_charged"] == 1

    untouched = fx.get_match(api, world["other_match"]["id"])
    A.assert_match_state(
        untouched, play_status="SCHEDULED", result_status="AWAITING_REPORTS"
    )
    assert untouched["forfeiting_team_id"] is None
    for label in ("Charlie", "Delta"):
        assert fx.get_team(api, world["others"][label]["id"])["match_points"] == 0

    season = fx.get_season(api, world["season"]["id"])
    A.assert_match_point_pool(season, 3)
    assert season["registered_team_count"] == 0

    alpha = fx.get_team(api, world["alpha"]["id"])
    assert alpha["starter_slots_used"] == 0
    assert alpha["active_starter_count"] == 0
    A.assert_starter_capacity_conserved(alpha, 3)


# ==========================================================================
# Instance: approval_pending_to_approved_to_revoked_walks_the_declared_path
# ==========================================================================
def test_approval_walks_pending_to_approved_to_revoked_stamping_each_hop(api):
    """Two consecutive legal hops, each stamping afresh and each worth exactly
    one version.

    PRD §3.3: "An `action` of `APPROVE` moves a `PENDING` approval to
    `APPROVED` ... An `action` of `REVOKE` moves an `APPROVED` approval to the
    terminal `REVOKED` state; it likewise applies no rating test. All three
    actions write `decided_by_user_id` from `X-User-ID` — an opaque operator
    identifier, never an entity identifier — stamp `decided_at` from the logical
    clock, and advance the approval's `version` by one."  PRD §2.5 on
    `created_at`: "It is taken from the logical clock and never changes
    afterwards."

    Design: Corner/state_machines/approval_pending_to_approved_to_revoked_walks_the_declared_path
    """
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    title = fx.make_title(api)
    pending = fx.request_title_approval(
        api, district["id"], title["id"], school["id"]
    )

    first = api.decide_title_approval(
        pending["id"],
        {"action": "APPROVE", "decision_note": "on the district list"},
        make_district_admin_headers(district["id"]),
    )
    validate_success(first)
    approved = A.data_of(first)
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_user_id"] == district["id"]
    assert approved["decided_at"] == "2026-08-01T00:00:00.000Z"
    assert approved["decision_note"] == "on the district list"
    A.assert_version_advanced_by(pending, approved, 1)

    fx.set_clock(api, "2026-08-05T09:00:00.000Z")

    second = api.decide_title_approval(
        pending["id"],
        {"action": "REVOKE", "decision_note": "publisher pulled the rating"},
        make_district_admin_headers(district["id"]),
    )
    validate_success(second)
    revoked = A.data_of(second)
    assert revoked["status"] == "REVOKED"
    assert revoked["decided_at"] == "2026-08-05T09:00:00.000Z"
    assert revoked["decision_note"] == "publisher pulled the rating"
    A.assert_version_advanced_by(approved, revoked, 1)

    assert revoked["district_id"] == district["id"]
    assert revoked["title_id"] == title["id"]
    assert revoked["requested_by_school_id"] == school["id"]
    assert revoked["created_at"] == pending["created_at"]


# ==========================================================================
# Instance: registration_precondition_counts_active_starters_not_created_slots
# ==========================================================================
def _build_draft_team_without_any_slot(api):
    """Everything registration needs except a roster: an APPROVED title, an
    open season, a certified coach and a student holding one posted term."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    title = fx.make_title(api)
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(api, title["id"])
    season = fx.open_registration(api, season["id"])
    coach = fx.make_certified_coach(api, school["id"])
    student = fx.make_student_with_term(
        api, school["id"], term_gpa=3.100, term_credits=6.0, birthdate="2009-05-10"
    )
    team = fx.make_team(
        api, season["id"], school["id"], title["id"], coach["id"], name="Alpha"
    )
    return {
        "district": district,
        "school": school,
        "season": season,
        "coach": coach,
        "student": student,
        "team": team,
    }


def test_registration_guard_counts_active_starters_not_created_slots(api):
    """Three refusals and one success from the same unchanged call, and the
    budget is never touched by a refusal.

    PRD §3.6: "The team's `active_starter_count` must be at least the season's
    `min_starters`, otherwise `ERR_ROSTER_MINIMUM_NOT_MET`. And the district's
    remaining `subsidy_pool_cents` must be at least as large as the subsidy this
    registration would grant, otherwise `ERR_SUBSIDY_POOL_EXHAUSTED` — the last
    rung on the whole ladder, so any state problem is always reported ahead of a
    budget problem."  PRD §3.5: "`starter_slots_used` is the count of the team's
    slots whose `slot_role` is `STARTER` and whose `participation_status` is
    `PROSPECTIVE`, `ACTIVE` or `INELIGIBLE` — released slots are excluded ...
    `active_starter_count` is the count of the team's slots whose `slot_role` is
    `STARTER` and whose `participation_status` is exactly `ACTIVE`."

    Design: Corner/state_machines/registration_precondition_counts_active_starters_not_created_slots
    """
    world = _build_draft_team_without_any_slot(api)
    coach_headers = make_coach_headers(world["coach"]["id"])
    team_id = world["team"]["id"]

    def _register():
        return api.register_team(team_id, {}, coach_headers)

    def _pool():
        return fx.get_district(api, world["district"]["id"])["subsidy_pool_cents"]

    validate_error(_register(), ApiErrorId.ERR_ROSTER_MINIMUM_NOT_MET.value, 422)
    A.assert_cents(_pool(), 5000000)

    slot = fx.add_slot(
        api, team_id, world["student"]["id"], world["coach"]["id"], "STARTER"
    )
    validate_error(_register(), ApiErrorId.ERR_ROSTER_MINIMUM_NOT_MET.value, 422)
    partial = fx.get_team(api, team_id)
    assert partial["starter_slots_used"] == 1
    assert partial["active_starter_count"] == 0
    A.assert_cents(_pool(), 5000000)

    fx.verify_slot_enrollment(api, slot["id"], world["student"]["birthdate"])
    validate_error(_register(), ApiErrorId.ERR_ROSTER_MINIMUM_NOT_MET.value, 422)
    half_cleared = fx.get_slot(api, slot["id"])
    A.assert_slot_axes(
        half_cleared,
        verification_status="ENROLLMENT_VERIFIED",
        academic_status="PENDING",
        participation_status="PROSPECTIVE",
    )
    A.assert_cents(_pool(), 5000000)

    fx.verify_slot_academics(api, slot["id"])
    accepted = _register()
    validate_success(accepted)
    registered = A.data_of(accepted)
    assert registered["status"] == "REGISTERED"
    assert registered["registered_at"] == "2026-08-01T00:00:00.000Z"
    assert registered["active_starter_count"] == 1
    A.assert_cents(registered["entry_fee_cents"], 15845)
    A.assert_cents(registered["subsidy_granted_cents"], 3962)
    A.assert_cents(registered["net_fee_due_cents"], 11883)
    A.assert_cents(_pool(), 4996038)


# ==========================================================================
# Instance: enrollment_verification_is_guarded_by_the_coaches_certification_
#           state
# ==========================================================================
def _build_slot_under_an_uncertified_coach(api):
    """A PROSPECTIVE starter slot on a team whose designated coach has never
    been certified."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    student = fx.make_student(api, school["id"], birthdate="2009-05-10")
    team = fx.make_team(
        api, season["id"], school["id"], title["id"], coach["id"], name="Alpha"
    )
    slot = fx.add_slot(api, team["id"], student["id"], coach["id"], "STARTER")
    return {"coach": coach, "student": student, "team": team, "slot": slot}


def test_enrollment_verification_is_gated_on_the_teams_coach_certification(api):
    """Three outcomes from one unchanged slot, decided entirely by the Coach.

    PRD §3.2: "team registration and enrollment verification both require the
    governing coach to be `CERTIFIED`, rejecting a `PENDING` or `SUSPENDED`
    coach with `ERR_COACH_NOT_CERTIFIED`, and both require
    `background_check_expires_on` to be on or after the logical clock's current
    date, rejecting an earlier expiry with
    `ERR_COACH_BACKGROUND_CHECK_EXPIRED`. The comparison is inclusive: an expiry
    falling on exactly today's date still clears."  And: "Certifying sets
    `certification_status` to `CERTIFIED`, writes the supplied
    `background_check_expires_on` date onto the coach, and stamps `certified_at`
    from the logical clock. The supplied expiry date is accepted as given —
    including a date already in the past".

    Design: Corner/state_machines/enrollment_verification_is_guarded_by_the_coaches_certification_state
    """
    world = _build_slot_under_an_uncertified_coach(api)
    slot_id = world["slot"]["id"]
    officer_headers = eligibility_officer_headers(ELIGIBILITY_OFFICER_ID)
    body = {"enrollment_document_ref": "REG-A", "verified_birthdate": "2009-05-10"}

    uncertified = api.verify_enrollment(slot_id, dict(body), officer_headers)
    validate_error(uncertified, ApiErrorId.ERR_COACH_NOT_CERTIFIED.value, 409)

    fx.certify_coach(api, world["coach"], background_check_expires_on="2026-07-31")
    lapsed = api.verify_enrollment(slot_id, dict(body), officer_headers)
    validate_error(
        lapsed, ApiErrorId.ERR_COACH_BACKGROUND_CHECK_EXPIRED.value, 409
    )

    untouched = fx.get_slot(api, slot_id)
    A.assert_slot_axes(
        untouched,
        verification_status="UNVERIFIED",
        participation_status="PROSPECTIVE",
    )
    assert untouched["age_at_cutoff"] is None
    assert untouched["enrollment_verified_by_user_id"] is None
    A.assert_version_is(untouched, world["slot"]["version"])

    fx.certify_coach(api, world["coach"], background_check_expires_on="2026-08-01")
    cleared = api.verify_enrollment(slot_id, dict(body), officer_headers)
    validate_success(cleared)
    verified = A.data_of(cleared)
    A.assert_slot_axes(verified, verification_status="ENROLLMENT_VERIFIED")
    assert verified["age_at_cutoff"] == 17
    assert verified["enrollment_verified_by_user_id"] == ELIGIBILITY_OFFICER_ID

    coach = fx.get_coach(api, world["coach"]["id"])
    assert coach["certification_status"] == "CERTIFIED"
    assert coach["background_check_expires_on"] == "2026-08-01"
    assert coach["certified_at"] == "2026-08-01T00:00:00.000Z"


# ==========================================================================
# Instance: dismiss_branch_executes_an_empty_side_effect_set
# ==========================================================================
def test_a_dismissed_case_moves_nothing_but_the_decider_stamp(api):
    """DISMISS is SUSTAIN's fork sibling with a deliberately empty effect set.

    PRD §3.8: "`DISMISS` moves the case `INVESTIGATING → DISMISSED`, writes
    `decider_user_id` from `X-User-ID`, stamps `decided_at` from the logical
    clock, leaves `sanction_type` at `NONE`, and changes **nothing else at all**
    — no student, roster, team, match or season figure moves, and the dismissed
    case never enters the penalty set."  And: "**Integrity scoring** works on the
    set of cases charged to a team whose status is `SUSTAINED` or
    `SUSTAINED_FINAL` ... Cases in `DISMISSED` or `OVERTURNED` are outside the
    set entirely."

    Design: Corner/state_machines/dismiss_branch_executes_an_empty_side_effect_set
    """
    world = fx.build_draft_team(api, term_gpa=3.100, term_credits=6.0)
    slot = fx.make_active_starter(
        api, world["team"]["id"], world["coach"]["id"], world["student"], "STARTER"
    )
    case = fx.open_student_case(
        api, world["team"]["id"], world["student"]["id"], case_type="ACCOUNT_SHARING"
    )
    fx.investigate_case(api, case["id"], officer_id=INTEGRITY_OFFICER_ID)

    response = api.decide_case(
        case["id"],
        {"decision": "DISMISS", "decision_note": "shared IP, not a shared account"},
        integrity_officer_headers(INTEGRITY_OFFICER_ID_2),
    )
    validate_success(response)
    dismissed = A.data_of(response)
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["decider_user_id"] == INTEGRITY_OFFICER_ID_2
    assert dismissed["decided_at"] == "2026-08-01T00:00:00.000Z"
    assert dismissed["severity"] is None
    assert dismissed["severity_weight"] == 0
    assert dismissed["repeat_index"] is None
    assert float(dismissed["applied_penalty"]) == 0
    assert dismissed["sanction_type"] == "NONE"

    assert fx.get_student(api, world["student"]["id"])["fair_play_status"] == "CLEAR"

    untouched_slot = fx.get_slot(api, slot["id"])
    A.assert_slot_axes(untouched_slot, participation_status="ACTIVE")
    assert untouched_slot["ineligibility_reason"] is None

    team = fx.get_team(api, world["team"]["id"])
    A.assert_integrity_score(team["integrity_score"], 100.00)
    assert team["status"] == "DRAFT"
    assert team["active_starter_count"] == 1

    season = fx.get_season(api, world["season"]["id"])
    A.assert_match_point_pool(season, 0)
    assert season["seeding_state"] == "UNSEEDED"


# ==========================================================================
# Instance: academic_posting_cascades_only_into_slots_whose_academic_axis_is_
#           still_pending
# ==========================================================================
def _build_one_student_holding_two_slots_one_already_cleared(api):
    """One student sits on two teams: slot A has cleared both axes on a 3.200
    term, slot B is still PENDING on its academics axis."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach_a = fx.make_certified_coach(api, school["id"])
    coach_b = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api)
    season = fx.make_season(api, title["id"])
    student = fx.make_student(api, school["id"], birthdate="2009-05-10")
    student = fx.post_term(api, student, 3.200, 6.0, term_label="2026-SUMMER")

    team_a = fx.make_team(
        api, season["id"], school["id"], title["id"], coach_a["id"], name="Alpha"
    )
    team_b = fx.make_team(
        api, season["id"], school["id"], title["id"], coach_b["id"], name="Bravo"
    )
    slot_a = fx.add_slot(api, team_a["id"], student["id"], coach_a["id"], "STARTER")
    slot_b = fx.add_slot(api, team_b["id"], student["id"], coach_b["id"], "STARTER")
    fx.verify_slot_enrollment(
        api, slot_a["id"], "2009-05-10", officer_id=ELIGIBILITY_OFFICER_ID
    )
    fx.verify_slot_academics(api, slot_a["id"], officer_id=ELIGIBILITY_OFFICER_ID_2)
    return {
        "student": fx.get_student(api, student["id"]),
        "team_a": team_a,
        "team_b": team_b,
        "slot_a": slot_a,
        "slot_b": slot_b,
    }


def test_academic_posting_blocks_only_the_slot_whose_academic_axis_is_pending(api):
    """The cleared slot keeps the snapshot taken at verification.

    PRD §3.2: "When the recomputed standing lands on `INELIGIBLE`, every roster
    slot belonging to that student whose academics axis is still `PENDING` and
    whose team is still open for roster mutation — that is, whose team is in
    `DRAFT` or `REGISTERED` — moves its academics axis from `PENDING` to
    `BLOCKED`, takes `ineligibility_reason` `ACADEMIC`, has its participation
    reconciled to `INELIGIBLE`, and forces a recomputation of that team's
    `active_starter_count`."  PRD §3.5: "the slot snapshots
    `standing_at_verification` (one of `GOOD`, `PROBATION` or `INELIGIBLE`) and
    `effective_gpa_at_verification` (three decimals) from the student's freshly
    computed figures".

    Design: Corner/state_machines/academic_posting_cascades_only_into_slots_whose_academic_axis_is_still_pending
    """
    world = _build_one_student_holding_two_slots_one_already_cleared(api)

    response = api.post_academic_term(
        world["student"]["id"],
        {
            "term_label": "2026-FALL",
            "term_gpa": 1.500,
            "term_credits": 6.0,
            "expected_student_version": world["student"]["version"],
        },
        eligibility_officer_headers(ELIGIBILITY_OFFICER_ID_2),
    )
    validate_success(response)
    posted = A.data_of(response)
    A.assert_gpa(posted["latest_term_gpa"], 1.500)
    A.assert_gpa(posted["effective_gpa"], 1.500)
    assert posted["academic_standing"] == "INELIGIBLE"
    assert posted["standing_basis_applied"] == "TERM_SNAPSHOT"

    blocked = fx.get_slot(api, world["slot_b"]["id"])
    A.assert_slot_axes(
        blocked, academic_status="BLOCKED", participation_status="INELIGIBLE"
    )
    assert blocked["ineligibility_reason"] == "ACADEMIC"

    kept = fx.get_slot(api, world["slot_a"]["id"])
    A.assert_slot_axes(
        kept, academic_status="CLEARED", participation_status="ACTIVE"
    )
    assert kept["standing_at_verification"] == "GOOD"
    A.assert_gpa(kept["effective_gpa_at_verification"], 3.200)

    team_a = fx.get_team(api, world["team_a"]["id"])
    team_b = fx.get_team(api, world["team_b"]["id"])
    assert team_a["active_starter_count"] == 1
    assert team_b["active_starter_count"] == 0
    assert team_b["starter_slots_used"] == 1
    assert team_b["starter_slots_available"] == 2
    A.assert_starter_capacity_conserved(team_b, 3)


# ==========================================================================
# Instance: dispute_and_broadcast_dimensions_advance_without_disturbing_play_
#           or_result
# ==========================================================================
def test_dispute_and_broadcast_axes_advance_without_touching_play_or_result(api):
    """The combined state (FORFEITED, ADJUDICATED, UNDER_REVIEW, SCHEDULED) must
    be reachable, which one flat status field cannot represent.

    PRD §3.7: "A match carries **four independent state dimensions**, and
    understanding that they advance separately is the key to the whole match
    workflow."  And: "`ACCEPT_REVIEW` moves `OPEN → UNDER_REVIEW`."  And: "On
    success `dispute_status` moves `NONE → OPEN` and `dispute_filed_by_team_id`
    and `dispute_reason_code` are stored."  PRD §3.7 on the deadline: "add that
    district's `dispute_window_hours` to the match's `result_confirmed_at`. The
    sum is stored as `dispute_deadline_at` ... This computation runs whenever
    `result_confirmed_at` is set — on confirmation, on an adjudication produced
    by a finalization override, and on a forfeit."

    Design: Corner/state_machines/dispute_and_broadcast_dimensions_advance_without_disturbing_play_or_result
    """
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach_a = fx.make_coach(api, school["id"])
    coach_b = fx.make_coach(api, school["id"])
    title = fx.make_title(api)
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
    match = fx.forfeit_match(api, match["id"], team_b["id"])
    assert match["result_confirmed_at"] == "2026-08-01T00:00:00.000Z"
    assert match["dispute_deadline_at"] == "2026-08-03T00:00:00.000Z"

    claimed = fx.register_broadcast(
        api,
        match["id"],
        coach_a["id"],
        school["id"],
        "2026-10-01T17:45:00.000Z",
        "2026-10-01T19:15:00.000Z",
    )
    A.assert_match_state(
        claimed,
        play_status="FORFEITED",
        result_status="ADJUDICATED",
        dispute_status="NONE",
        broadcast_status="SCHEDULED",
    )

    filed = fx.file_dispute(
        api, match["id"], team_b, dispute_reason_code="SCORE_MISMATCH",
        dispute_note="we were present",
    )
    assert filed["dispute_status"] == "OPEN"
    assert filed["dispute_filed_by_team_id"] == team_b["id"]
    assert filed["dispute_reason_code"] == "SCORE_MISMATCH"

    reviewed = fx.dispute_action(api, match["id"], "ACCEPT_REVIEW")
    A.assert_match_state(
        reviewed,
        play_status="FORFEITED",
        result_status="ADJUDICATED",
        dispute_status="UNDER_REVIEW",
        broadcast_status="SCHEDULED",
    )
    assert reviewed["spectator_strikes"] == 0
    assert reviewed["broadcast_school_id"] == school["id"]
    assert reviewed["forfeiting_team_id"] == team_b["id"]
    assert reviewed["winner_team_id"] == team_a["id"]
    assert reviewed["result_confirmed_at"] == "2026-08-01T00:00:00.000Z"
    assert reviewed["dispute_deadline_at"] == "2026-08-03T00:00:00.000Z"

    assert fx.get_team(api, team_a["id"])["match_points"] == 3
    A.assert_match_point_pool(fx.get_season(api, season["id"]), 3)
