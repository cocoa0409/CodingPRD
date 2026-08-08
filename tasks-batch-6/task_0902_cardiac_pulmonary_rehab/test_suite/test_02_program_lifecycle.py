"""Program activation dependencies, cross-entity state guards, discharge & maintenance.

Queue A (Difficulty): cross_entity_state_dependency, boundary_precision_check
(discharge empty-set). Queue B (Corner): terminal lockdown, discharge side effects,
maintenance tiering.
"""
import pytest

from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId
from test_helpers import fixtures as X


# ---------------------------------------------------------------------------
# Difficulty: session scheduling requires an ACTIVE parent program
# ---------------------------------------------------------------------------
def test_schedule_session_on_draft_program_rejected(api):
    """PRD §3.4: "A session may only be scheduled while its parent program is
    `ACTIVE`; scheduling against a program in any other status is rejected with
    `ERR_PROGRAM_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/session_schedule_requires_program_active
    """
    ctx = X.setup_draft_program(api)  # authorization + finalized baseline, but NOT activated
    resp = X.schedule_session(ctx, phase="PHASE_I", return_response=True)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE, expected_status=409)


def test_schedule_session_on_held_program_rejected(api):
    """PRD §3.4: "A session may only be scheduled while its parent program is
    `ACTIVE`; scheduling against a program in any other status is rejected with
    `ERR_PROGRAM_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/session_schedule_requires_program_active
    """
    ctx = X.setup_active_program(api)
    validate_success(api.hold_program(ctx["program_id"], ctx["coord"], {"reason": "chest pain"}))
    resp = X.schedule_session(ctx, return_response=True)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE, expected_status=409)


# ---------------------------------------------------------------------------
# Difficulty: activation requires an APPROVED authorization
# ---------------------------------------------------------------------------
def test_activate_with_pending_authorization_rejected(api):
    """PRD §3.3: "Activating a `DRAFT` program moves it to `ACTIVE`, but only when
    three conditions all hold: the program is in `DRAFT` (else `ERR_PROGRAM_NOT_DRAFT`),
    at least one `APPROVED` insurance authorization exists for the program (else
    `ERR_NO_APPROVED_AUTHORIZATION`), and at least one `FINALIZED` `BASELINE` outcome
    assessment exists for the program (else `ERR_BASELINE_OUTCOME_REQUIRED`)."

    Design: Difficulty/cross_entity_state_dependency/program_activate_requires_approved_authorization
    """
    ctx = X.setup_draft_program(api, approve_authorization=False)  # PENDING auth, finalized baseline
    resp = api.activate_program(ctx["program_id"], ctx["coord"])
    validate_error(resp, ApiErrorId.ERR_NO_APPROVED_AUTHORIZATION, expected_status=409)
    prog = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert prog["status"] == "DRAFT"


def test_activate_with_no_authorization_rejected(api):
    """PRD §3.3: "Activating a `DRAFT` program moves it to `ACTIVE`, but only when
    three conditions all hold: the program is in `DRAFT` (else `ERR_PROGRAM_NOT_DRAFT`),
    at least one `APPROVED` insurance authorization exists for the program (else
    `ERR_NO_APPROVED_AUTHORIZATION`), and at least one `FINALIZED` `BASELINE` outcome
    assessment exists for the program (else `ERR_BASELINE_OUTCOME_REQUIRED`)."

    Design: Difficulty/cross_entity_state_dependency/program_activate_requires_approved_authorization
    """
    ctx = X.setup_draft_program(api, with_authorization=False)  # no auth, finalized baseline present
    resp = api.activate_program(ctx["program_id"], ctx["coord"])
    validate_error(resp, ApiErrorId.ERR_NO_APPROVED_AUTHORIZATION, expected_status=409)


# ---------------------------------------------------------------------------
# Difficulty: discharge requires a non-empty set of FINALIZED DISCHARGE outcomes
# ---------------------------------------------------------------------------
def test_discharge_without_discharge_outcome_rejected(api):
    """PRD §3.8: "Discharge concludes the episode, moving an `ACTIVE` program to
    `DISCHARGED`. It requires that the program be `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`),
    that no session remain in `SCHEDULED` status (else `ERR_ACTIVE_SESSIONS_EXIST`),
    and that at least one `FINALIZED` `DISCHARGE` outcome assessment exist for the
    program (else `ERR_NO_FINALIZED_DISCHARGE_OUTCOME`)."

    Design: Difficulty/boundary_precision_check/discharge_requires_nonempty_finalized_discharge_outcome
    """
    ctx = X.setup_active_program(api)  # finalized BASELINE only, no DISCHARGE, no scheduled sessions
    resp = api.discharge_program(ctx["program_id"], ctx["coord"])
    validate_error(resp, ApiErrorId.ERR_NO_FINALIZED_DISCHARGE_OUTCOME, expected_status=409)
    prog = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert prog["status"] == "ACTIVE"


def test_discharge_with_only_draft_discharge_outcome_rejected(api):
    """PRD §3.8: "It requires that the program be `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`),
    that no session remain in `SCHEDULED` status (else `ERR_ACTIVE_SESSIONS_EXIST`),
    and that at least one `FINALIZED` `DISCHARGE` outcome assessment exist for the
    program (else `ERR_NO_FINALIZED_DISCHARGE_OUTCOME`)."

    Design: Difficulty/boundary_precision_check/discharge_requires_nonempty_finalized_discharge_outcome
    """
    ctx = X.setup_active_program(api)
    # A DISCHARGE outcome exists but stays DRAFT (never finalized).
    from test_helpers import factories as F
    validate_success(
        api.create_outcome(F.create_outcome_payload(ctx["program_id"], "DISCHARGE", 360), ctx["clin_headers"]),
        expected_status=201,
    )
    resp = api.discharge_program(ctx["program_id"], ctx["coord"])
    validate_error(resp, ApiErrorId.ERR_NO_FINALIZED_DISCHARGE_OUTCOME, expected_status=409)


# ---------------------------------------------------------------------------
# Corner: terminal-state lockdown, discharge side effects, maintenance tiering
# ---------------------------------------------------------------------------
def test_withdraw_terminal_program_returns_already_terminal(api):
    """PRD §3.8: "Withdrawal is permitted from `DRAFT`, `ACTIVE`, or `ON_HOLD` (an
    already-terminal program is rejected with `ERR_PROGRAM_ALREADY_TERMINAL`), carries
    an optional `reason`, moves the program to `WITHDRAWN`, and cancels every remaining
    `SCHEDULED` session per §2.9."

    Design: Corner/state_machines/withdraw_terminal_program_returns_already_terminal
    """
    ctx = X.setup_draft_program(api, with_authorization=False, with_baseline=False)
    validate_success(api.withdraw_program(ctx["program_id"], ctx["coord"], {"reason": "patient declined"}))
    resp = api.withdraw_program(ctx["program_id"], ctx["coord"])
    validate_error(resp, ApiErrorId.ERR_PROGRAM_ALREADY_TERMINAL, expected_status=409)


def test_discharge_creates_maintenance_and_fails_open_goals(api):
    """PRD §3.8: "Discharge has two side effects: any still-`OPEN` `GOAL` care plan
    items are transitioned to `NOT_ACHIEVED`, and a new `MaintenanceProgram` is created
    in `ACTIVE` status."

    Design: Corner/state_machines/discharge_creates_maintenance_and_fails_open_goals
    """
    from test_helpers import factories as F
    ctx = X.setup_active_program(api)
    goal = validate_success(
        api.create_care_plan_item(
            F.create_care_plan_item_payload(ctx["program_id"], item_type="GOAL", title="Walk 400m"),
            ctx["clin_headers"],
        ),
        expected_status=201,
    )
    X.add_finalized_discharge_outcome(ctx, distance_meters=380)

    prog = validate_success(api.discharge_program(ctx["program_id"], ctx["coord"]))
    assert prog["status"] == "DISCHARGED"

    maint, meta = validate_paginated(api.list_maintenance_programs(ctx["coord"], params={"program_id": ctx["program_id"]}))
    assert len(maint) == 1
    assert maint[0]["status"] == "ACTIVE"

    resolved_goal = validate_success(api.get_care_plan_item(goal["id"], ctx["coord"]))
    assert resolved_goal["status"] == "NOT_ACHIEVED"


def test_maintenance_tier_intensive_below_threshold(api):
    """PRD §3.8: "Its `tier` is `INTENSIVE` when the finalized discharge assessment's
    `improvement_pct` is strictly less than 10.0 percent, reflecting a low functional
    gain that warrants closer maintenance; otherwise the tier is `STANDARD`. The
    `monthly_visit_allowance` follows from the tier: 4 monthly visits for a `STANDARD`
    tier and 8 for an `INTENSIVE` tier."

    Design: Corner/calculations/maintenance_tier_intensive_below_threshold
    """
    ctx = X.setup_active_program(api, baseline_distance=300)
    disch = X.add_finalized_discharge_outcome(ctx, distance_meters=320)  # +20m over 300 = 6.7%
    assert disch["improvement_pct"] == pytest.approx(6.7, abs=0.001)

    validate_success(api.discharge_program(ctx["program_id"], ctx["coord"]))
    maint, _ = validate_paginated(api.list_maintenance_programs(ctx["coord"], params={"program_id": ctx["program_id"]}))
    assert len(maint) == 1
    assert maint[0]["tier"] == "INTENSIVE"
    assert maint[0]["monthly_visit_allowance"] == 8
