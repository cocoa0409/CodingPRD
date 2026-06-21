"""Project / walkthrough / color-selection state machines: preconditions,
cyclic loops, cancel cascade, and the parallel workflow x payment axes.

Covers finalize/schedule/walkthrough preconditions, the walkthrough fail->reopen
revert loop, the color-selection terminal lockdown, the cancellation cascade, and
the independence of the workflow and payment axes.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_product, create_project, add_surface,
    setup_estimated_project, setup_scheduled_project, setup_in_progress_project,
    setup_walkthrough_pending_project,
    propose_color, propose_and_approve_color, create_crew, schedule_crew, pay_deposit,
    TEST_DEFAULTS, TEST_USERS,
)

EST = TEST_USERS["estimator_headers"]
PM = TEST_USERS["project_manager_headers"]
CUST = TEST_USERS["customer_headers"]
CREW = TEST_USERS["crew_member_headers"]

S1_DEPOSIT = TEST_DEFAULTS["S1_DEPOSIT_30PCT_CENTS"]  # 2674


# ─── difficulty: parallel workflow x payment axes independent ─────────────

def test_deposit_advances_payment_axis_only(api):
    """PRD §2.1 (Introduction): "a project advances along a workflow axis and an
    independent payment axis at the same time, so that a homeowner can pay a deposit
    before any crew is scheduled..."
    PRD §3.8: "A **deposit** payment carries `kind` `DEPOSIT` and drives the axis from
    `UNPAID` to `DEPOSIT_PAID`."

    Design: Difficulty/non_linear_state_machine/project_parallel_workflow_and_payment_axes_independent
    """
    _, project, _ = setup_estimated_project(project_overrides={"deposit_pct": 30})
    assert project["deposit_due_cents"] == S1_DEPOSIT
    pay_deposit(project["id"], S1_DEPOSIT)
    after = validate_success(api.get_project(project["id"], PM), 200)
    assert after["payment_status"] == "DEPOSIT_PAID"
    assert after["workflow_status"] == "ESTIMATED"


def test_workflow_axis_unmoved_by_deposit(api):
    """PRD §3.8: "The payment axis evolves independently of the workflow axis, subject only
    to the guards stated here."
    PRD §3.5: "A project manager moves a project from `ESTIMATED` to `SCHEDULED`..."

    Design: Difficulty/non_linear_state_machine/project_parallel_workflow_and_payment_axes_independent
    """
    _, project, _ = setup_estimated_project(project_overrides={"deposit_pct": 30})
    pay_deposit(project["id"], S1_DEPOSIT)
    after = validate_success(api.get_project(project["id"], PM), 200)
    # Paying the deposit must NOT auto-advance workflow_status to SCHEDULED.
    assert after["workflow_status"] == "ESTIMATED"
    assert after["deposit_due_cents"] == S1_DEPOSIT


# ─── corner: finalize-estimate invalid transition (already ESTIMATED) ─────

def test_finalize_estimate_twice_returns_not_draft(api):
    """PRD §3.3: "This transition is permitted only when the project's `workflow_status`
    is `DRAFT`; otherwise it is rejected with `ERR_PROJECT_NOT_DRAFT`."

    Design: Corner/state_machines/finalize_estimate_from_estimated_returns_not_draft
    """
    _, project, _ = setup_estimated_project()
    res = api.finalize_estimate(project["id"], EST)
    validate_error(res, "ERR_PROJECT_NOT_DRAFT", expected_status=409)


# ─── corner: finalize with no surfaces ────────────────────────────────────

def test_finalize_estimate_no_surfaces_returns_no_surfaces(api):
    """PRD §3.3: "The project must also have at least one surface in `PLANNED` status,
    failing which the transition is rejected with `ERR_NO_SURFACES`."

    Design: Corner/state_machines/finalize_estimate_with_no_surfaces_returns_no_surfaces
    """
    project = create_project()
    res = api.finalize_estimate(project["id"], EST)
    validate_error(res, "ERR_NO_SURFACES", expected_status=409)


# ─── corner: schedule without deposit ─────────────────────────────────────

def test_schedule_without_deposit_returns_deposit_not_paid(api):
    """PRD §3.5: "The payment axis must already show `DEPOSIT_PAID` or `PAID_IN_FULL`
    (otherwise `ERR_DEPOSIT_NOT_PAID`)."

    Design: Corner/state_machines/schedule_without_deposit_returns_deposit_not_paid
    """
    product, project, surfaces = setup_estimated_project(project_overrides={"deposit_pct": 30})
    propose_and_approve_color(surfaces[0]["id"])
    crew = create_crew()
    schedule_crew(project["id"], crew["id"], "2026-03-02", "2026-03-03")
    # No deposit paid.
    res = api.schedule_project(project["id"], PM)
    validate_error(res, "ERR_DEPOSIT_NOT_PAID", expected_status=409)


# ─── corner: schedule without approved color ──────────────────────────────

def test_schedule_without_approved_color_returns_color_not_approved(api):
    """PRD §3.5: "Every `PLANNED` surface must have an `APPROVED` color selection
    (otherwise `ERR_COLOR_NOT_APPROVED`)."

    Design: Corner/state_machines/schedule_without_approved_color_returns_color_not_approved
    """
    product, project, surfaces = setup_estimated_project(project_overrides={"deposit_pct": 30})
    crew = create_crew()
    schedule_crew(project["id"], crew["id"], "2026-03-02", "2026-03-03")
    pay_deposit(project["id"], S1_DEPOSIT)
    # Color never approved.
    res = api.schedule_project(project["id"], PM)
    validate_error(res, "ERR_COLOR_NOT_APPROVED", expected_status=409)


# ─── corner: request-walkthrough with active crew ─────────────────────────

def test_request_walkthrough_with_active_crew_returns_crew_not_done(api):
    """PRD §3.6: "This requires the project to be `IN_PROGRESS` (otherwise
    `ERR_PROJECT_NOT_IN_PROGRESS`) and every crew assignment to be `DONE` or `CANCELLED`
    (otherwise `ERR_CREW_NOT_DONE`)."

    Design: Corner/state_machines/request_walkthrough_with_active_crew_returns_crew_not_done
    """
    bundle = setup_in_progress_project(S1_DEPOSIT)
    # Begin (not complete) the crew assignment -> it is IN_PROGRESS.
    validate_success(api.begin_crew_assignment(bundle["assignment"]["id"], CREW), 200)
    res = api.request_walkthrough(bundle["project"]["id"], PM)
    validate_error(res, "ERR_CREW_NOT_DONE", expected_status=409)


# ─── corner: walkthrough pass with open punch list ────────────────────────

def test_walkthrough_pass_open_punch_list_returns_punch_list_open(api):
    """PRD §3.7: "Passing it requires the walkthrough to be `PENDING` (otherwise
    `ERR_WALKTHROUGH_NOT_PENDING`), the `punch_list_count` to be exactly 0 (otherwise
    `ERR_PUNCH_LIST_OPEN`, since open defects block a pass)..."

    Design: Corner/state_machines/walkthrough_pass_with_open_punch_list_returns_punch_list_open
    """
    bundle = setup_walkthrough_pending_project(S1_DEPOSIT)
    wt_id = bundle["walkthrough"]["id"]
    validate_success(api.fail_walkthrough(wt_id, CUST), 200)
    validate_success(api.reopen_walkthrough(wt_id, {"punch_list_count": 2}, PM), 200)
    res = api.pass_walkthrough(wt_id, CUST)
    validate_error(res, "ERR_PUNCH_LIST_OPEN", expected_status=409)


# ─── corner: walkthrough fail -> reopen revert cycle ──────────────────────

def test_walkthrough_fail_then_reopen_cycle(api):
    """PRD §3.7: "Failing a walkthrough requires it to be `PENDING` (otherwise
    `ERR_WALKTHROUGH_NOT_PENDING`) and moves it to `FAILED`."
    PRD §3.7: "the project manager may reopen it, which requires the walkthrough to be
    `FAILED` (otherwise `ERR_WALKTHROUGH_NOT_FAILED`), resets `punch_list_count` to the
    value supplied in the reopen payload (defaulting to 0 when none is supplied), and
    returns the walkthrough to `PENDING` for another inspection."

    Design: Corner/state_machines/walkthrough_failed_then_pending_reopen_cycle
    """
    bundle = setup_walkthrough_pending_project(S1_DEPOSIT)
    wt_id = bundle["walkthrough"]["id"]
    failed = validate_success(api.fail_walkthrough(wt_id, CUST), 200)
    assert failed["status"] == "FAILED"
    reopened = validate_success(api.reopen_walkthrough(wt_id, {}, PM), 200)
    assert reopened["status"] == "PENDING"
    assert reopened["punch_list_count"] == 0


# ─── corner: color selection terminal REJECTED lockdown ───────────────────

def test_approve_rejected_color_returns_not_proposed(api):
    """PRD §3.4: "Rejecting a proposed color likewise requires `PROPOSED` status
    (`ERR_COLOR_NOT_PROPOSED`) and moves the selection to `REJECTED`, the terminal state
    of this short machine."
    PRD §3.4: "Approving a proposed color is allowed only when the selection is in
    `PROPOSED` status (otherwise `ERR_COLOR_NOT_PROPOSED`)..."

    Design: Corner/state_machines/color_approve_terminal_reject_lockdown
    """
    product = create_product()
    project = create_project()
    surface = add_surface(project["id"], product["id"])
    cs = propose_color(surface["id"])
    validate_success(api.reject_color_selection(cs["id"], CUST), 200)
    res = api.approve_color_selection(cs["id"], CUST)
    validate_error(res, "ERR_COLOR_NOT_PROPOSED", expected_status=409)


# ─── corner: cancel cascade releases crew + refunds payments ──────────────

def test_cancel_scheduled_project_cascades(api):
    """PRD §3.10: "Cancellation runs a compensating cascade: every crew assignment that
    is `SCHEDULED` or `IN_PROGRESS` moves to `CANCELLED`, releasing the corresponding crew
    `scheduled_day_count` and equipment `units_reserved`; every `CAPTURED` payment moves to
    `REFUNDED` and the project's `amount_paid_cents` is recomputed to 0; and the project's
    `workflow_status` becomes `CANCELLED`."

    Design: Corner/state_machines/cancel_releases_crew_and_refunds_payments_cascade
    """
    bundle = setup_scheduled_project(S1_DEPOSIT)
    project_id = bundle["project"]["id"]
    crew_id = bundle["crew"]["id"]
    asg_id = bundle["assignment"]["id"]

    validate_success(api.cancel_project(project_id, PM), 200)

    crew_after = validate_success(api.get_crew_member(crew_id, PM), 200)
    assert crew_after["scheduled_day_count"] == 0

    asg_after = validate_success(api.get_crew_assignment(asg_id, PM), 200)
    assert asg_after["status"] == "CANCELLED"

    project_after = validate_success(api.get_project(project_id, PM), 200)
    assert project_after["workflow_status"] == "CANCELLED"
    assert project_after["amount_paid_cents"] == 0
