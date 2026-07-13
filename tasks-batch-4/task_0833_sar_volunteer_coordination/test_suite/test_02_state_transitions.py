"""State-machine legality: invalid transitions, terminal lockdown, valid branches,
and the two cyclic revision loops (task suspend/resume, claim return/resubmit)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_member_headers,
    create_active_incident, create_task, create_assigned_task,
    create_team_and_member, create_clue, create_dismissed_clue,
    create_acknowledged_callout, create_claim, create_submitted_claim,
    setup_task_in_progress_with_member,
)

COORD = TEST_USERS["coordinator_headers"]
IC = TEST_USERS["incident_commander_headers"]
FIN = TEST_USERS["finance_officer_headers"]


# --- Corner: invalid / terminal / valid transitions ---

def test_resume_assigned_task_is_invalid_state(api):
    """PRD §3.3: "A running task can enter a weather-hold loop: suspending it moves
    it from `IN_PROGRESS` to `SUSPENDED`, and resuming moves it back from
    `SUSPENDED` to `IN_PROGRESS`."
    PRD §2.5: "The target resource must be in a state from which the requested
    transition is defined, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/resume_task_from_assigned_returns_invalid_state
    """
    inc = create_active_incident(api, name="Inv Inc", ics_incident_number="OR-2026-1002")
    task = create_assigned_task(api, inc["id"])
    resp = api.resume_task(task["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_promote_dismissed_clue_is_invalid_state(api):
    """PRD §3.7: "The terminal clue states are `DISMISSED` and `RESOLVED`."
    PRD §2.5: "The target resource must be in a state from which the requested
    transition is defined, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/clue_promote_from_dismissed_terminal_returns_invalid_state
    """
    inc = create_active_incident(api, name="Clue Inc", ics_incident_number="OR-2026-1003")
    clue = create_dismissed_clue(api, inc["id"])
    resp = api.promote_clue(clue["id"], IC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_dismiss_logged_clue_reaches_dismissed(api):
    """PRD §3.7: "the commander can promote a logged clue, moving it from `LOGGED`
    to `ACTIONABLE`, or dismiss it, moving it from `LOGGED` to `DISMISSED`."

    Design: Corner/state_machines/clue_dismiss_from_logged_valid_branch
    """
    inc = create_active_incident(api, name="Clue Inc2", ics_incident_number="OR-2026-1004")
    clue = create_clue(api, inc["id"], clue_priority="ROUTINE", description="candy wrapper")
    resp = api.dismiss_clue(clue["id"], IC)
    data = validate_success(resp)
    assert data["status"] == "DISMISSED"


def test_acknowledge_callout_twice_is_invalid_state(api):
    """PRD §3.4: "The paged `Member`, acting on their own callout, can acknowledge
    it, moving it from `REQUESTED` to `ACKNOWLEDGED`, or decline it, moving it from
    either `REQUESTED` or `ACKNOWLEDGED` to `DECLINED`."
    PRD §2.5: "The target resource must be in a state from which the requested
    transition is defined, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/acknowledge_callout_twice_returns_invalid_state
    """
    inc = create_active_incident(api, name="Ack Inc", ics_incident_number="OR-2026-1005")
    team, member = create_team_and_member(api)
    task = create_task(api, inc["id"])
    co = create_acknowledged_callout(api, task["id"], member["id"])
    resp = api.acknowledge_callout(co["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# --- Difficulty: non_linear_state_machine / task_suspend_resume_cycle ---

def test_task_suspend_then_resume_reenters_in_progress(api):
    """PRD §3.3: "A running task can enter a weather-hold loop: suspending it moves
    it from `IN_PROGRESS` to `SUSPENDED`, and resuming moves it back from
    `SUSPENDED` to `IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/task_suspend_resume_cycle
    """
    inc, team, member, task, co = setup_task_in_progress_with_member(
        api, incident_overrides={"name": "Loop Search", "ics_incident_number": "OR-2026-0005"},
        task_overrides={"segment_area_sqkm": 5.0, "planned_searcher_hours": 4})
    susp = validate_success(api.suspend_task(task["id"], COORD))
    assert susp["status"] == "SUSPENDED"
    resumed = validate_success(api.resume_task(task["id"], COORD))
    assert resumed["status"] == "IN_PROGRESS"


def test_task_suspended_state_is_reachable_from_in_progress(api):
    """PRD §3.3: "A running task can enter a weather-hold loop: suspending it moves
    it from `IN_PROGRESS` to `SUSPENDED`, and resuming moves it back from
    `SUSPENDED` to `IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/task_suspend_resume_cycle
    """
    inc, team, member, task, co = setup_task_in_progress_with_member(
        api, incident_overrides={"name": "Loop2 Search", "ics_incident_number": "OR-2026-0005b"})
    susp = validate_success(api.suspend_task(task["id"], COORD))
    assert susp["status"] == "SUSPENDED"
    # Confirm the persisted read agrees (non-terminal re-entry, not a dead end).
    reread = validate_success(api.get_task(task["id"], COORD))
    assert reread["status"] == "SUSPENDED"


# --- Difficulty: non_linear_state_machine / claim_return_resubmit_cycle ---

def test_claim_return_then_resubmit_reenters_submitted(api):
    """PRD §3.8: "A `FinanceOfficer` may return a submitted claim for revision,
    moving it from `SUBMITTED` to `RETURNED`, from which the member may submit again
    — the `SUBMITTED` and `RETURNED` states form a revision loop, and each
    resubmission recomputes `estimated_amount_cents`."

    Design: Difficulty/non_linear_state_machine/claim_return_resubmit_cycle
    """
    inc = create_active_incident(api, name="Cycle Search", incident_type="URBAN",
                                 ics_incident_number="OR-2026-0006")
    team, member = create_team_and_member(api)
    claim = create_submitted_claim(api, member["id"], inc["id"],
                                   declared_mileage_miles=20, meal_count=1, lodging_nights=0)
    returned = validate_success(api.return_claim(claim["id"], FIN))
    assert returned["status"] == "RETURNED"
    resubmitted = validate_success(api.submit_claim(claim["id"], make_member_headers(member["id"])))
    assert resubmitted["status"] == "SUBMITTED"


def test_claim_returned_state_reachable_from_submitted(api):
    """PRD §3.8: "A `FinanceOfficer` may return a submitted claim for revision,
    moving it from `SUBMITTED` to `RETURNED`, from which the member may submit again
    — the `SUBMITTED` and `RETURNED` states form a revision loop, and each
    resubmission recomputes `estimated_amount_cents`."

    Design: Difficulty/non_linear_state_machine/claim_return_resubmit_cycle
    """
    inc = create_active_incident(api, name="Cycle2 Search", incident_type="URBAN",
                                 ics_incident_number="OR-2026-0006b")
    team, member = create_team_and_member(api)
    claim = create_submitted_claim(api, member["id"], inc["id"], declared_mileage_miles=20)
    returned = validate_success(api.return_claim(claim["id"], FIN))
    assert returned["status"] == "RETURNED"
    reread = validate_success(api.get_claim(claim["id"], COORD))
    assert reread["status"] == "RETURNED"
