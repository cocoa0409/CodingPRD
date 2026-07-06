"""Warranty claims: the approve/deny branch fork off UNDER_REVIEW (with the
remediation estimate), and the cross-entity gate requiring a COMPLETED job.
"""
from test_helpers import (
    ApiErrorId,
    create_warranty_claim,
    create_warranty_claim_payload,
    setup_accepted_quote,
    setup_completed_job,
    setup_scheduled_job,
    transition_warranty_claim,
    validate_error,
    validate_success,
)


# ------------------------------------------------------ approve / deny branch
def test_warranty_approved_branch_records_actual_remediation(api):
    """PRD §3.8: "Moving from `SUBMITTED` to `UNDER_REVIEW` computes the claim's
    `estimated_remediation_cents`: a base amount chosen by issue type — 15,000
    cents for a `CLOG`, 30,000 cents for an `OVERFLOW`, and 60,000 cents for a
    `DETACHMENT` — plus the linear footage of the claim's job (the `linear_feet`
    on the job's quote) multiplied by 200 cents per foot and rounded half up to
    whole cents."
    PRD §3.8: "From `APPROVED`, moving to `RESOLVED` requires the supplied
    `actual_remediation_cents` to be present and at least 0, else `ERR_VALIDATION`;
    on success that actual cost is persisted on the claim and reconciled against
    the earlier estimate."

    Design: Difficulty/non_linear_state_machine/warranty_claim_approve_deny_branch
    """
    scenario = setup_completed_job(measured_linear_feet=210)
    claim = create_warranty_claim(scenario["job"]["id"], "CLOG")
    reviewed = transition_warranty_claim(claim["id"], "UNDER_REVIEW")
    assert reviewed["estimated_remediation_cents"] == 57000  # 15000 + round(210 * 200)
    transition_warranty_claim(claim["id"], "APPROVED")
    resolved = transition_warranty_claim(claim["id"], "RESOLVED", actual_remediation_cents=42000)
    assert resolved["status"] == "RESOLVED"
    assert resolved["actual_remediation_cents"] == 42000


def test_warranty_denied_branch_is_terminal(api, admin_headers):
    """PRD §3.8: "From `UNDER_REVIEW`, the agent may either move the claim to
    `APPROVED` or move it to `DENIED`; the denied branch is terminal and records
    no remediation cost, whereas the approved branch proceeds toward resolution."
    PRD §3.8: "`DENIED` and `RESOLVED` are the claim's terminal states."

    Design: Difficulty/non_linear_state_machine/warranty_claim_approve_deny_branch
    """
    scenario = setup_completed_job(measured_linear_feet=210)
    claim = create_warranty_claim(scenario["job"]["id"], "OVERFLOW")
    transition_warranty_claim(claim["id"], "UNDER_REVIEW")
    denied = transition_warranty_claim(claim["id"], "DENIED")
    assert denied["status"] == "DENIED"
    # Terminal: it cannot proceed to RESOLVED.
    resp = api.transition_warranty_claim(
        claim["id"], {"to_status": "RESOLVED", "actual_remediation_cents": 10000}, admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ------------------------------------------------- job-completed gate on filing
def test_warranty_claim_against_scheduled_job_rejected(api, admin_headers):
    """PRD §3.8: "The claim may be filed only against a job that has reached
    `COMPLETED`; a claim against any other job state is rejected with
    `ERR_JOB_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/warranty_requires_job_completed
    """
    scenario = setup_scheduled_job(measured_linear_feet=210, install_date="2026-06-10")
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(scenario["job"]["id"], "CLOG"), admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_COMPLETED)


def test_warranty_claim_against_pending_job_rejected(api, admin_headers):
    """PRD §3.8: "The claim may be filed only against a job that has reached
    `COMPLETED`; a claim against any other job state is rejected with
    `ERR_JOB_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/warranty_requires_job_completed
    """
    scenario = setup_accepted_quote(estimated_linear_feet=210, measured_linear_feet=210)
    assert scenario["job"]["status"] == "PENDING"
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(scenario["job"]["id"], "CLOG"), admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_COMPLETED)
