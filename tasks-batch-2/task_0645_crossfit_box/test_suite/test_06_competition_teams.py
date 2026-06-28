"""Competition teams: formation, invite/accept, roster bubble-up, lock/disband fork.

Queue A: team branching fork (lock vs disband).
Queue B: lock-already-locked invalid state, roster bubble-up on accept,
roster-full-on-accept.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_member_headers,
    register_member, setup_team_with_invite,
    create_team_payload, create_team_member_payload,
)
from test_helpers import api_client

BOX = TEST_USERS["box_manager_headers"]


# ==========================================================================
# Queue A — non_linear_state_machine / team_branching_fork_lock_vs_disband
# ==========================================================================

def test_team_lock_declines_outstanding_invites(api):
    """PRD §3.7: "it transitions the team from `FORMING` to `LOCKED`, finalizing the roster by cascading every still-`INVITED` team-member slot from `INVITED` to `DECLINED` (locking expires the outstanding invitations), and increments the team's `version`."

    Design: Difficulty/non_linear_state_machine/team_branching_fork_lock_vs_disband
    """
    s = setup_team_with_invite(max_roster_size=4)
    team = s["team"]
    cap = s["captain"]
    tm = s["team_member"]

    resp = api.lock_team(team["id"], {"expected_team_version": team["version"]},
                         make_member_headers(cap["id"]))
    data = validate_success(resp)
    assert data["status"] == "LOCKED"

    tm_after = validate_success(api.get_team_member(tm["id"], BOX))
    assert tm_after["status"] == "DECLINED"


def test_team_disband_removes_all_slots_and_zeroes_roster(api):
    """PRD §3.7: "it transitions the team from `FORMING` to `DISBANDED`, cascades every `ACCEPTED` or `INVITED` team-member slot to `REMOVED`, sets the team's `roster_size` to 0, and increments the team's `version`."

    Design: Difficulty/non_linear_state_machine/team_branching_fork_lock_vs_disband
    """
    s = setup_team_with_invite(max_roster_size=4)
    team = s["team"]
    cap = s["captain"]
    tm = s["team_member"]

    resp = api.disband_team(team["id"], {"expected_team_version": team["version"]},
                            make_member_headers(cap["id"]))
    data = validate_success(resp)
    assert data["status"] == "DISBANDED"
    assert data["roster_size"] == 0

    tm_after = validate_success(api.get_team_member(tm["id"], BOX))
    assert tm_after["status"] == "REMOVED"


# ==========================================================================
# Queue B — state_machines / lock_already_locked_team_returns_invalid_state
# ==========================================================================

def test_lock_already_locked_team_returns_invalid_state(api):
    """PRD §3.7: "A lock or disband from a non-`FORMING` team is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/lock_already_locked_team_returns_invalid_state
    """
    cap = register_member()
    team = validate_success(api.create_team(
        create_team_payload(cap["id"], name="Lockers", max_roster_size=3),
        make_member_headers(cap["id"]),
    ), expected_status=201)
    locked = validate_success(api.lock_team(
        team["id"], {"expected_team_version": team["version"]},
        make_member_headers(cap["id"]),
    ))
    resp = api.lock_team(team["id"], {"expected_team_version": locked["version"]},
                         make_member_headers(cap["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ==========================================================================
# Queue B — state_machines / bubble_up_roster_size_on_accept
# ==========================================================================

def test_accept_invite_bubbles_up_roster_size(api):
    """PRD §3.7: "Acceptance transitions the slot from `INVITED` to `ACCEPTED` and bubbles up an increment of one to the parent team's `roster_size`."

    Design: Corner/state_machines/bubble_up_roster_size_on_accept
    """
    s = setup_team_with_invite(max_roster_size=4)
    tm = s["team_member"]
    invitee = s["invitee"]
    team = s["team"]

    resp = api.accept_team_member(tm["id"], make_member_headers(invitee["id"]))
    data = validate_success(resp)
    assert data["status"] == "ACCEPTED"

    team_after = validate_success(api.get_team(team["id"], BOX))
    assert team_after["roster_size"] == 2


# ==========================================================================
# Queue B — validations / roster_full_accept_returns_error
# ==========================================================================

def test_accept_when_roster_full_returns_error(api):
    """PRD §3.7: "the team has room — its `roster_size` must be strictly below `max_roster_size`, otherwise the acceptance is rejected with `ERR_ROSTER_FULL`."

    Design: Corner/validations/roster_full_accept_returns_error
    """
    cap = register_member()
    invitee = register_member()
    team = validate_success(api.create_team(
        create_team_payload(cap["id"], name="FullTeam", max_roster_size=1),
        make_member_headers(cap["id"]),
    ), expected_status=201)
    tm = validate_success(api.create_team_member(
        create_team_member_payload(team["id"], invitee["id"]),
        make_member_headers(cap["id"]),
    ), expected_status=201)

    resp = api.accept_team_member(tm["id"], make_member_headers(invitee["id"]))
    validate_error(resp, ApiErrorId.ERR_ROSTER_FULL.value)
