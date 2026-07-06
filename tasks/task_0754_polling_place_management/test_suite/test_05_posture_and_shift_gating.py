"""Posture cycling and posture-dependent child operations.

Queue A: non_linear_state_machine (cyclic), cross_entity_state_dependency (check-in blocked).
Queue B: provisional cast requires OPEN.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_election, create_place,
    setup_open_place, setup_shift_scheduled,
    create_provisional_ballot_payload,
)

ADMIN = TEST_USERS["election_admin_headers"]
CAPTAIN = TEST_USERS["precinct_captain_headers"]


# ---- non_linear_state_machine / polling_place_cyclic_open_suspend_open ----

def test_suspend_open_place_sets_suspended(api):
    """PRD §3.2: "A `PrecinctCaptain` may suspend an open place, taking it
    `OPEN → SUSPENDED`, optionally supplying a `reason`; suspend is defined only from
    `OPEN`."

    Design: Difficulty/non_linear_state_machine/polling_place_cyclic_open_suspend_open
    """
    ctx = setup_open_place(api)
    data = validate_success(api.suspend_place(ctx["place"]["id"], CAPTAIN, {"reason": "power flicker"}))
    assert data["readiness_posture"] == "SUSPENDED"


def test_resume_suspended_place_returns_to_open(api):
    """PRD §3.2: "Resuming takes a place `SUSPENDED → OPEN` and re-checks the same physical
    guarantees: every equipment unit at the place must be `OPERATIONAL` and no kit for the
    place may be `COMPROMISED`".

    Design: Difficulty/non_linear_state_machine/polling_place_cyclic_open_suspend_open
    """
    ctx = setup_open_place(api)
    pp_id = ctx["place"]["id"]
    get_success_data(api.suspend_place(pp_id, CAPTAIN, {"reason": "power flicker"}))
    data = validate_success(api.resume_place(pp_id, CAPTAIN))
    assert data["readiness_posture"] == "OPEN", (
        f"place should cycle back to OPEN after resume, got {data['readiness_posture']}"
    )


# ---- cross_entity_state_dependency / checkin_blocked_when_place_suspended ----

def test_checkin_rejected_when_place_suspended(api):
    """PRD §3.5: "Check-in requires that the shift be `SCHEDULED`, that the worker's
    `training_status` be `CERTIFIED` (otherwise `ERR_WORKER_NOT_CERTIFIED`, 422), that the
    parent assignment be `ACTIVE`, and that the owning place's `readiness_posture` be `OPEN`
    — the latter two being conditions on the surrounding state, rejected as
    `ERR_INVALID_STATE` when unmet."

    Design: Difficulty/cross_entity_state_dependency/checkin_blocked_when_place_suspended
    """
    ctx = setup_shift_scheduled(api, scheduled_start="2026-11-03T06:00:00Z",
                                scheduled_end="2026-11-03T12:00:00Z")
    pp_id = ctx["place"]["id"]
    get_success_data(api.suspend_place(pp_id, CAPTAIN, {"reason": "outage"}))
    resp = api.check_in(ctx["shift"]["id"], CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_checkin_blocked_leaves_shift_scheduled(api):
    """PRD §3.5: "Check-in requires that the shift be `SCHEDULED` ... and that the owning
    place's `readiness_posture` be `OPEN` — the latter two being conditions on the
    surrounding state, rejected as `ERR_INVALID_STATE` when unmet."

    Design: Difficulty/cross_entity_state_dependency/checkin_blocked_when_place_suspended
    """
    ctx = setup_shift_scheduled(api, scheduled_start="2026-11-03T06:00:00Z",
                                scheduled_end="2026-11-03T12:00:00Z")
    pp_id, sid = ctx["place"]["id"], ctx["shift"]["id"]
    get_success_data(api.suspend_place(pp_id, CAPTAIN, {"reason": "outage"}))
    validate_error(api.check_in(sid, CAPTAIN), ApiErrorId.ERR_INVALID_STATE)
    shift = get_success_data(api.get_shift(sid, ADMIN))
    place = get_success_data(api.get_polling_place(pp_id, ADMIN))
    assert shift["status"] == "SCHEDULED"
    assert place["readiness_posture"] == "SUSPENDED"


# ---- validations / error_provisional_cast_when_place_not_open ----

def test_cast_provisional_at_setup_place_is_voting_not_open(api):
    """PRD §3.7: "Casting requires the place's posture to be `OPEN`; casting at a place that
    is not open is rejected with `ERR_VOTING_NOT_OPEN` (409)."

    Design: Corner/validations/error_provisional_cast_when_place_not_open
    """
    el = create_election(api, open_voting=True)
    pp = create_place(api, election_id=el["id"])  # SETUP, never opened
    resp = api.create_provisional_ballot(create_provisional_ballot_payload(pp["id"]), CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_VOTING_NOT_OPEN)
