"""Segregation-of-duties four-eyes, RBAC role denial, and validation-precedence pairs."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    setup_active_subaward,
    setup_active_subaward_with_drawdown,
    setup_draft_subaward,
    submit_drawdown,
    get_subaward,
    create_nonprofit,
    create_nofo,
    create_drawdown_payload,
    make_subrecipient_headers,
    make_grants_manager_headers,
    make_program_officer_headers,
)


def test_sod_conflict_when_risk_assessor_approves_drawdown(api):
    """PRD §2.10: "a GrantsManager who authored any RiskAssessment on a subaward may not later
    approve a drawdown against that same subaward; when the approving manager's X-User-ID
    matches the assessed_by_user_id of any risk assessment on the subaward, the approval is
    rejected with ERR_SOD_CONFLICT (HTTP 403)."

    Design: Corner/validations/sod_conflict_on_drawdown_approve_by_risk_assessor
    """
    ctx = setup_active_subaward_with_drawdown(drawdown_amount=5_000_000)
    validate_success(
        api.create_risk_assessment(ctx["sub_id"], make_grants_manager_headers("gm-1")), 201
    )
    res = api.approve_drawdown(ctx["dd_id"], {}, make_grants_manager_headers("gm-1"))
    validate_error(res, "ERR_SOD_CONFLICT")


def test_sod_ok_when_different_manager_approves(api):
    """PRD §2.10: "Approval by a different manager who never assessed that subaward proceeds
    normally."

    Design: Corner/validations/sod_ok_when_different_manager_approves
    """
    ctx = setup_active_subaward_with_drawdown(drawdown_amount=5_000_000)
    validate_success(
        api.create_risk_assessment(ctx["sub_id"], make_grants_manager_headers("gm-1")), 201
    )
    approved = validate_success(
        api.approve_drawdown(ctx["dd_id"], {}, make_grants_manager_headers("gm-2")), 200
    )
    assert approved["status"] == "APPROVED"


def test_subrecipient_cannot_approve_drawdown(api):
    """PRD §2.1: "When a role is authenticated but not permitted to invoke the requested
    operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/subrecipient_cannot_approve_drawdown_returns_unauthorized
    """
    ctx = setup_active_subaward_with_drawdown(drawdown_amount=5_000_000)
    res = api.approve_drawdown(ctx["dd_id"], {}, make_subrecipient_headers(ctx["np_id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header is rejected with ERR_UNAUTHENTICATED
    (HTTP 401) before any other processing."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    nofo = create_nofo()
    res = api.get_nofo(nofo["id"], headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_state_precedes_fiscal_on_suspended_over_budget_drawdown(api):
    """PRD §2.11: "then whether the target resource is in a legal state for the requested
    transition (the ERR_INVALID_*_STATE family together with ERR_SUBAWARD_NOT_ACTIVE,
    ERR_INTAKE_CLOSED, and ERR_APPLICATION_NOT_SCORED). Only after those structural checks do
    the business-specific rules apply ... then drawdown sufficiency (ERR_INSUFFICIENT_BUDGET)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_suspended_over_budget_drawdown
    """
    ctx = setup_active_subaward()
    suspended = validate_success(
        api.suspend_subaward(ctx["sub_id"], {"reason": "risk"}, make_grants_manager_headers("gm-1")),
        200,
    )
    payload = create_drawdown_payload(999_000_000, suspended["version"])
    res = api.create_drawdown(ctx["sub_id"], payload, make_subrecipient_headers(ctx["np_id"]))
    validate_error(res, "ERR_SUBAWARD_NOT_ACTIVE")


def test_suspended_over_budget_drawdown_leaves_ledger_untouched(api):
    """PRD §2.11: "Only after those structural checks do the business-specific rules apply."

    Because the state check pre-empts the fiscal check, the rejected create leaves the
    subaward's obligation ledger unchanged.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_suspended_over_budget_drawdown
    """
    ctx = setup_active_subaward()
    suspended = validate_success(
        api.suspend_subaward(ctx["sub_id"], {"reason": "risk"}, make_grants_manager_headers("gm-1")),
        200,
    )
    payload = create_drawdown_payload(999_000_000, suspended["version"])
    validate_error(
        api.create_drawdown(ctx["sub_id"], payload, make_subrecipient_headers(ctx["np_id"])),
        "ERR_SUBAWARD_NOT_ACTIVE",
    )
    assert get_subaward(ctx["sub_id"])["obligated_cents"] == 0


def test_ownership_precedes_state_on_foreign_draft_drawdown(api):
    """PRD §2.11: "then left-to-right existence of path resources (the ERR_*_NOT_FOUND family),
    then subrecipient ownership (ERR_NOT_RESOURCE_OWNER), then whether the target resource is
    in a legal state for the requested transition."

    A non-owner drawing on a DRAFT subaward is rejected on ownership, not state.

    Design: Difficulty/priority_pair_validation_conflict/owner_beats_state_on_foreign_draft_drawdown
    """
    ctx = setup_draft_subaward()
    other = create_nonprofit(legal_name="Other Org")
    version = get_subaward(ctx["sub_id"])["version"]
    payload = create_drawdown_payload(100_000, version)
    res = api.create_drawdown(ctx["sub_id"], payload, make_subrecipient_headers(other["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_foreign_draft_drawdown_creates_nothing(api):
    """PRD §2.1: "A Subrecipient acting on an application, subaward, drawdown, performance
    report, single audit, or finding whose governing nonprofit_id differs from its X-User-ID is
    rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/owner_beats_state_on_foreign_draft_drawdown
    """
    ctx = setup_draft_subaward()
    other = create_nonprofit(legal_name="Other Org")
    version = get_subaward(ctx["sub_id"])["version"]
    payload = create_drawdown_payload(100_000, version)
    validate_error(
        api.create_drawdown(ctx["sub_id"], payload, make_subrecipient_headers(other["id"])),
        "ERR_NOT_RESOURCE_OWNER",
    )
    data, meta = validate_paginated(
        api.list_drawdowns(ctx["sub_id"], make_program_officer_headers())
    )
    assert meta["total_count"] == 0
