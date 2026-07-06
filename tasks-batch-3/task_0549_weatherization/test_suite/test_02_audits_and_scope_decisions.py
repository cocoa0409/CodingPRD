"""Energy-audit lifecycle (including the reject/resubmit cycle) and scope-item
approval preconditions."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    new_dwelling,
    new_job,
    new_audit,
    new_scope,
    submit_audit,
    decide_audit,
    setup_proposed_scope_submitted_audit,
)


def _audit_submitted_then_rejected():
    """DRAFT audit with one scope item, submitted then rejected -> REJECTED."""
    dwelling = new_dwelling(address="5 Fir St")
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    audit = new_audit(job["id"])
    new_scope(
        job["id"], audit["id"], category="AIR_SEALING", area_sqft=800, target_r_value=0,
        estimated_cost_cents=60_000, estimated_savings_kwh=400,
    )
    submit_audit(audit["id"])
    decide_audit(audit["id"], "REJECT")
    return job, audit


def test_audit_reject_moves_submitted_to_rejected(api, program_admin_headers):
    """PRD 3.3: "a `decision` of `REJECT` moves a `SUBMITTED` audit to
    `REJECTED`. Deciding an audit that is not `SUBMITTED` fails with
    `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/energy_audit_reject_resubmit_cycle
    """
    _job, audit = _audit_submitted_then_rejected()
    current = validate_success(api.get_audit(audit["id"], program_admin_headers))
    assert current["status"] == "REJECTED"


def test_rejected_audit_resubmit_returns_to_submitted(api, auditor_headers):
    """PRD 3.3: "A `REJECTED` audit is re-submittable: submitting it again
    advances `REJECTED` back to `SUBMITTED` and recomputes its
    `estimated_annual_savings_kwh`, closing the `SUBMITTED → REJECTED →
    SUBMITTED` revision loop."

    Design: Difficulty/non_linear_state_machine/energy_audit_reject_resubmit_cycle
    """
    _job, audit = _audit_submitted_then_rejected()
    res = api.submit_audit(audit["id"], auditor_headers)
    updated = validate_success(res, 200)
    assert updated["status"] == "SUBMITTED"


def test_decide_draft_audit_rejected_invalid_state(api, program_admin_headers):
    """PRD 3.3: "Deciding an audit that is not `SUBMITTED` fails with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/audit_decide_on_draft_returns_invalid_state
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    audit = new_audit(job["id"])
    res = api.decide_audit(audit["id"], {"decision": "APPROVE"}, program_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert validate_success(api.get_audit(audit["id"], program_admin_headers))["status"] == "DRAFT"


def test_decide_approved_terminal_audit_rejected(api, auditor_headers, program_admin_headers):
    """PRD 3.3: "Deciding an audit that is not `SUBMITTED` fails with
    `ERR_INVALID_STATE`."
    PRD 3.3: "Only `APPROVED` is terminal."

    Design: Corner/state_machines/audit_decide_on_approved_terminal_returns_invalid_state
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    audit = new_audit(job["id"])
    submit_audit(audit["id"])
    decide_audit(audit["id"], "APPROVE")
    res = api.decide_audit(audit["id"], {"decision": "REJECT"}, program_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert validate_success(api.get_audit(audit["id"], program_admin_headers))["status"] == "APPROVED"


def test_submit_already_submitted_audit_rejected(api, auditor_headers):
    """PRD 3.3: "Submitting a `DRAFT` audit for review advances it from `DRAFT`
    to `SUBMITTED`; submitting an audit that is not in `DRAFT` fails with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/audit_submit_twice_idempotency_returns_invalid_state
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    audit = new_audit(job["id"])
    submit_audit(audit["id"])
    res = api.submit_audit(audit["id"], auditor_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert validate_success(api.get_audit(audit["id"], auditor_headers))["status"] == "SUBMITTED"


def test_approve_scope_with_submitted_audit_rejected(api, program_admin_headers):
    """PRD 3.4: "A `decision` of `APPROVE` moves a `PROPOSED` scope item to
    `APPROVED`, but only if the audit named by its `audit_id` is currently in
    `APPROVED` status; approving against an audit that is not `APPROVED` is
    rejected with `ERR_AUDIT_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/scope_approve_requires_audit_approved
    """
    ctx = setup_proposed_scope_submitted_audit()
    res = api.decide_scope_item(ctx["scope"]["id"], {"decision": "APPROVE"}, program_admin_headers)
    validate_error(res, ApiErrorId.ERR_AUDIT_NOT_APPROVED)


def test_scope_stays_proposed_when_audit_not_approved(api, program_admin_headers):
    """PRD 3.4: "A `decision` of `APPROVE` moves a `PROPOSED` scope item to
    `APPROVED`, but only if the audit named by its `audit_id` is currently in
    `APPROVED` status; approving against an audit that is not `APPROVED` is
    rejected with `ERR_AUDIT_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/scope_approve_requires_audit_approved
    """
    ctx = setup_proposed_scope_submitted_audit()
    api.decide_scope_item(ctx["scope"]["id"], {"decision": "APPROVE"}, program_admin_headers)
    scope = validate_success(api.get_scope_item(ctx["scope"]["id"], program_admin_headers))
    assert scope["status"] == "PROPOSED"


def test_auditor_cannot_decide_scope_forbidden(api, auditor_headers, program_admin_headers):
    """PRD 2.1: "A request whose role is recognized but is not permitted to
    perform the requested operation is rejected with `ERR_FORBIDDEN` (HTTP
    403)."

    Design: Corner/rbac/auditor_cannot_decide_scope_returns_forbidden
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    audit = new_audit(job["id"])
    scope = new_scope(
        job["id"], audit["id"], category="WALL_INSULATION", area_sqft=900, target_r_value=13,
        estimated_cost_cents=70_000, estimated_savings_kwh=250,
    )
    res = api.decide_scope_item(scope["id"], {"decision": "APPROVE"}, auditor_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    assert validate_success(api.get_scope_item(scope["id"], program_admin_headers))["status"] == "PROPOSED"
