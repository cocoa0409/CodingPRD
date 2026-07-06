"""Permit and HOA review branches, and the contract-signing gates."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS, make_client_headers,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["project_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
DESIGN = TEST_USERS["design_consultant_headers"]


def test_permit_deny_sets_correction_notes(api):
    """PRD §3.4: "The `PlatformAdmin`, acting as authority of record, then either approves it —
    advancing `SUBMITTED` to `APPROVED` and assigning a `permit_number` — or denies it, advancing
    `SUBMITTED` to `DENIED` and recording the supplied `correction_notes`."

    Design: Corner/state_machines/permit_deny_branch
    """
    ctx = fx.setup_permit_submitted(api)
    data = validate_success(api.deny_permit(ctx["permit_id"], {"correction_notes": "setback too small"}, ADMIN))
    assert data["status"] == "DENIED", f"expected DENIED, got {data['status']}"
    assert data["correction_notes"] == "setback too small", \
        f"expected correction_notes recorded, got {data.get('correction_notes')!r}"


def test_hoa_approve_branch(api):
    """PRD §3.4: "An `outcome` of `APPROVED` advances the submission to `APPROVED` and records
    `decision_notes`."

    Design: Corner/state_machines/hoa_approve_branch
    """
    ctx = fx.setup_hoa_submitted(api, email="oha@example.com")
    data = validate_success(api.decide_hoa(ctx["hoa_id"], {"outcome": "APPROVED", "decision_notes": "ok"}, ADMIN))
    assert data["status"] == "APPROVED", f"expected APPROVED, got {data['status']}"


def test_hoa_conditional_decision_sets_status(api):
    """PRD §3.4: "An `outcome` of `CONDITIONAL` advances it to `CONDITIONAL`, recording both
    `conditions` and `decision_notes`; a conditional decision does not satisfy the contract gate, so
    signing remains blocked until a later `APPROVED`."

    Design: Difficulty/non_linear_state_machine/hoa_submission_conditional_branch
    """
    ctx = fx.setup_hoa_submitted(api, email="ho@example.com")
    data = validate_success(api.decide_hoa(
        ctx["hoa_id"],
        {"outcome": "CONDITIONAL", "conditions": "earth-tone pavers only", "decision_notes": "board review"},
        ADMIN))
    assert data["status"] == "CONDITIONAL", f"expected CONDITIONAL, got {data['status']}"


def test_hoa_conditional_decision_records_conditions(api):
    """PRD §3.4: "An `outcome` of `CONDITIONAL` advances it to `CONDITIONAL`, recording both
    `conditions` and `decision_notes`; a conditional decision does not satisfy the contract gate, so
    signing remains blocked until a later `APPROVED`."

    Design: Difficulty/non_linear_state_machine/hoa_submission_conditional_branch
    """
    ctx = fx.setup_hoa_submitted(api, email="ho2@example.com")
    data = validate_success(api.decide_hoa(
        ctx["hoa_id"],
        {"outcome": "CONDITIONAL", "conditions": "earth-tone pavers only", "decision_notes": "board review"},
        ADMIN))
    assert data["conditions"] == "earth-tone pavers only", \
        f"expected conditions recorded, got {data.get('conditions')!r}"


def test_sign_contract_not_owner_forbidden(api):
    """PRD §3.5: "The homeowner then signs the contract, advancing `PENDING_APPROVALS` to
    `CONTRACTED`. Signing is a `Client`-only action, permitted only to the project's owner."
    PRD §2.5: "For the `Client`-only actions (approving or requesting a revision on a design,
    signing a contract, and filing a warranty claim), the caller must own the parent project, or
    `ERR_NOT_PROJECT_OWNER` (403)."

    Design: Corner/validations/sign_contract_not_owner_returns_forbidden
    """
    owner = fx.make_customer(api, email="oa@example.com", name="Owner A")
    other = fx.make_customer(api, email="ob@example.com", name="Owner B")
    project = fx.make_project(api, owner["id"], site_address="33 Yard Ln")
    resp = api.sign_contract(project["id"], make_client_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_PROJECT_OWNER)


def test_sign_contract_deposit_not_paid(api):
    """PRD §3.5: "Two gates apply: a deposit draw (`draw_type` `DEPOSIT`) must already be `PAID`, or
    the request is rejected with `ERR_DEPOSIT_NOT_PAID` (409); and if the project requires HOA
    review, its submission must be `APPROVED`, or the request is rejected with `ERR_HOA_NOT_APPROVED`
    (409)."

    Design: Corner/validations/sign_contract_deposit_not_paid_returns_error
    """
    ctx = fx.setup_pending_approvals_no_deposit(api)
    resp = api.sign_contract(ctx["project_id"], make_client_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_PAID)


def test_sign_contract_hoa_not_approved(api):
    """PRD §3.5: "Two gates apply: a deposit draw (`draw_type` `DEPOSIT`) must already be `PAID`, or
    the request is rejected with `ERR_DEPOSIT_NOT_PAID` (409); and if the project requires HOA
    review, its submission must be `APPROVED`, or the request is rejected with `ERR_HOA_NOT_APPROVED`
    (409)."

    Design: Corner/validations/sign_contract_hoa_not_approved_returns_error
    """
    ctx = fx.setup_pending_approvals_hoa_unapproved(api)
    resp = api.sign_contract(ctx["project_id"], make_client_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_HOA_NOT_APPROVED)
