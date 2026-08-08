"""Suspension/reinstatement cycle, closeout denial cascade, and the open-findings gate."""
from test_helpers import (
    validate_success,
    validate_error,
    setup_active_subaward,
    setup_active_subaward_with_drawdown,
    setup_active_subaward_with_scheduled_visit,
    conduct_visit_with_finding,
    get_subaward,
    make_grants_manager_headers,
    make_program_officer_headers,
)


def test_suspend_moves_active_subaward_to_suspended(api):
    """PRD §3.9: "Beyond the cascade path, a `GrantsManager` may directly suspend an `ACTIVE`
    subaward, optionally recording a `reason`, moving it from `ACTIVE` to `SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/subaward_suspend_reinstate_cycle
    """
    ctx = setup_active_subaward()
    suspended = validate_success(
        api.suspend_subaward(ctx["sub_id"], {"reason": "risk"}, make_grants_manager_headers("gm-1")),
        200,
    )
    assert suspended["status"] == "SUSPENDED"


def test_reinstate_returns_suspended_subaward_to_active(api):
    """PRD §3.9: "A suspended subaward can be reinstated by a GrantsManager, moving it from
    SUSPENDED back to ACTIVE."

    Design: Difficulty/non_linear_state_machine/subaward_suspend_reinstate_cycle
    """
    ctx = setup_active_subaward()
    validate_success(
        api.suspend_subaward(ctx["sub_id"], {"reason": "risk"}, make_grants_manager_headers("gm-1")),
        200,
    )
    reinstated = validate_success(
        api.reinstate_subaward(ctx["sub_id"], make_grants_manager_headers("gm-1")), 200
    )
    assert reinstated["status"] == "ACTIVE"


def test_close_denies_pending_drawdown(api):
    """PRD §3.9: "Closing it from CLOSEOUT_PENDING to CLOSED requires that every Finding on the
    subaward be RESOLVED, or the close is rejected with ERR_OPEN_FINDINGS; on a successful
    close, each drawdown still in SUBMITTED or RETURNED transitions to DENIED, crediting the
    subaward's obligated_cents back for any amount still provisionally obligated."

    Design: Difficulty/transitive_cascade/closeout_denies_pending_drawdown_releases_obligation
    """
    ctx = setup_active_subaward_with_drawdown(drawdown_amount=5_000_000)
    validate_success(api.initiate_closeout(ctx["sub_id"], make_program_officer_headers()), 200)
    closed = validate_success(api.close_subaward(ctx["sub_id"], make_program_officer_headers()), 200)
    assert closed["status"] == "CLOSED"
    dd = validate_success(api.get_drawdown(ctx["dd_id"], make_program_officer_headers()), 200)
    assert dd["status"] == "DENIED"


def test_close_releases_obligation_of_denied_drawdown(api):
    """PRD §3.9: "on a successful close, each drawdown still in SUBMITTED or RETURNED transitions
    to DENIED, crediting the subaward's obligated_cents back for any amount still provisionally
    obligated."

    Design: Difficulty/transitive_cascade/closeout_denies_pending_drawdown_releases_obligation
    """
    ctx = setup_active_subaward_with_drawdown(drawdown_amount=5_000_000)
    validate_success(api.initiate_closeout(ctx["sub_id"], make_program_officer_headers()), 200)
    validate_success(api.close_subaward(ctx["sub_id"], make_program_officer_headers()), 200)
    assert get_subaward(ctx["sub_id"])["obligated_cents"] == 0


def test_close_with_open_finding_rejected(api):
    """PRD §3.9: "Closing it from `CLOSEOUT_PENDING` to `CLOSED` requires that every `Finding` on
    the subaward be `RESOLVED`, or the close is rejected with `ERR_OPEN_FINDINGS`."

    Design: Difficulty/cross_entity_state_dependency/closeout_requires_all_findings_resolved
    """
    ctx = setup_active_subaward_with_scheduled_visit()
    conduct_visit_with_finding(ctx["sub_id"], ctx["visit_id"], "HIGH")
    validate_success(api.initiate_closeout(ctx["sub_id"], make_program_officer_headers()), 200)
    res = api.close_subaward(ctx["sub_id"], make_program_officer_headers())
    validate_error(res, "ERR_OPEN_FINDINGS")


def test_close_with_open_finding_leaves_subaward_closeout_pending(api):
    """PRD §3.9: "Closing it from `CLOSEOUT_PENDING` to `CLOSED` requires that every `Finding` on
    the subaward be `RESOLVED`, or the close is rejected with `ERR_OPEN_FINDINGS`."

    A rejected close must not advance the subaward out of CLOSEOUT_PENDING.

    Design: Difficulty/cross_entity_state_dependency/closeout_requires_all_findings_resolved
    """
    ctx = setup_active_subaward_with_scheduled_visit()
    conduct_visit_with_finding(ctx["sub_id"], ctx["visit_id"], "HIGH")
    validate_success(api.initiate_closeout(ctx["sub_id"], make_program_officer_headers()), 200)
    validate_error(
        api.close_subaward(ctx["sub_id"], make_program_officer_headers()), "ERR_OPEN_FINDINGS"
    )
    assert get_subaward(ctx["sub_id"])["status"] == "CLOSEOUT_PENDING"
