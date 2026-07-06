"""Post-test verification: pass (bubble-up + dual-variant savings), fail cascade,
job-cancel cascade, and the verify precedence pairs (SOD vs scope-incomplete)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_auditor_headers,
    create_diagnostic_test_payload,
    new_dwelling,
    new_job,
    setup_verify_ready,
    setup_verify_ready_no_scope,
    setup_job_cancel_cascade_ready,
)

BOB = make_auditor_headers("auditor-bob")
ALICE = make_auditor_headers("auditor-alice")


# ── energy_savings_estimated_vs_verified ──────────────────────────────────
def test_verify_pass_sets_verification_and_estimated_savings(api, program_admin_headers):
    """PRD 3.8: "Verification **passes** when this fraction is at least 0.20 (a
    20% reduction) and **fails** when it is below 0.20". PRD 3.4: "The job's
    `estimated_annual_savings_kwh` — distinct from the audit's field of the same
    name — is the audit-model projection: the sum of `estimated_savings_kwh`
    across the job's scope items in `APPROVED`, `INSTALLED`, or `VERIFIED`
    status, rounded half up to one decimal place."

    Design: Difficulty/dual_variant_calc/energy_savings_estimated_vs_verified
    """
    ctx = setup_verify_ready(estimated_savings=1200, baseline_cfm=3000, post_cfm=2400, achieved_r=38, actual_cost=300_000, estimated_cost=300_000)
    job = validate_success(api.verify_job(ctx["job"]["id"], {"post_test_id": ctx["post_test_id"]}, BOB), 200)
    assert job["verification_status"] == "PASSED"
    assert job["estimated_annual_savings_kwh"] == 1200


def test_verified_savings_differs_from_estimated(api, program_admin_headers):
    """PRD 3.8: "The job's `verified_annual_savings_kwh` is then computed
    top-down from the measurement: it is the CFM50 reduction (baseline CFM50
    minus post CFM50) multiplied by 1.5 kWh per unit of CFM50 reduction, rounded
    half up to one decimal place; this measurement-based figure typically
    differs from the audit-model `estimated_annual_savings_kwh`."

    Design: Difficulty/dual_variant_calc/energy_savings_estimated_vs_verified
    """
    ctx = setup_verify_ready(estimated_savings=1200, baseline_cfm=3000, post_cfm=2400, achieved_r=38, actual_cost=300_000, estimated_cost=300_000)
    job = validate_success(api.verify_job(ctx["job"]["id"], {"post_test_id": ctx["post_test_id"]}, BOB), 200)
    assert job["verified_annual_savings_kwh"] == 900
    assert job["estimated_annual_savings_kwh"] != job["verified_annual_savings_kwh"]


# ── verify_pass_completes_job_bubble_up (corner) ─────────────────────────
def test_verify_pass_completes_job_and_verifies_scope(api, program_admin_headers):
    """PRD 3.8: "Every scope item of the job in `INSTALLED` status is advanced
    to `VERIFIED`. Finally, because the install dimension is already `INSTALLED`
    and verification has now passed, the overall `job_status` auto-completes
    from `ACTIVE` to `COMPLETED`".

    Design: Corner/state_machines/verify_pass_completes_job_bubble_up
    """
    ctx = setup_verify_ready(estimated_savings=500, baseline_cfm=3000, post_cfm=2400, achieved_r=30, actual_cost=100_000, estimated_cost=100_000, cap=100_000)
    job = validate_success(api.verify_job(ctx["job"]["id"], {"post_test_id": ctx["post_test_id"]}, BOB), 200)
    assert job["verification_status"] == "PASSED"
    assert job["job_status"] == "COMPLETED"
    scope = validate_success(api.get_scope_item(ctx["scope"]["id"], program_admin_headers))
    assert scope["status"] == "VERIFIED"


# ── verify_fail_cascade_scope_rebate_budget_depth3 ────────────────────────
def test_verify_fail_sets_status_and_fails_scope(api, program_admin_headers):
    """PRD 3.8: "On a failure, the job's `verification_status` moves from
    `PENDING` to `FAILED`, and a three-link cascade unwinds the affected work.
    First (link 1), every scope item of the job in `INSTALLED` status is moved
    to `FAILED_VERIFICATION`."

    Design: Difficulty/transitive_cascade/verify_fail_cascade_scope_rebate_budget_depth3
    """
    ctx = setup_verify_ready(with_approved_rebate=True, estimated_savings=800, baseline_cfm=3000, post_cfm=2500, achieved_r=30, actual_cost=100_000, estimated_cost=100_000, cap=300_000)
    job = validate_success(api.verify_job(ctx["job"]["id"], {"post_test_id": ctx["post_test_id"]}, BOB), 200)
    assert job["verification_status"] == "FAILED"
    scope = validate_success(api.get_scope_item(ctx["scope"]["id"], program_admin_headers))
    assert scope["status"] == "FAILED_VERIFICATION"


def test_verify_fail_voids_rebate_and_returns_budget(api, program_admin_headers):
    """PRD 3.8: "Second (link 2), for each such scope item that had a rebate
    claim in `APPROVED` status, that claim is moved to `VOIDED`, caused by its
    measure failing verification. Third (link 3), each voided claim decrements
    the job's `approved_rebate_total_cents` by its `finalized_amount_cents`".

    Design: Difficulty/transitive_cascade/verify_fail_cascade_scope_rebate_budget_depth3
    """
    ctx = setup_verify_ready(with_approved_rebate=True, estimated_savings=800, baseline_cfm=3000, post_cfm=2500, achieved_r=30, actual_cost=100_000, estimated_cost=100_000, cap=300_000)
    api.verify_job(ctx["job"]["id"], {"post_test_id": ctx["post_test_id"]}, BOB)
    rebate = validate_success(api.get_rebate_claim(ctx["rebate"]["id"], program_admin_headers))
    assert rebate["status"] == "VOIDED"
    job = validate_success(api.get_job(ctx["job"]["id"], program_admin_headers))
    assert job["approved_rebate_total_cents"] == 0


# ── job_cancel_cascade_scope_rebate_depth2 ────────────────────────────────
def test_cancel_sets_job_cancelled_and_scope_cancelled(api, program_admin_headers):
    """PRD 3.2: "Cancelling moves `job_status` from `ACTIVE` to `CANCELLED` and
    unwinds the job's commitments through a compensating cascade. Every scope
    item still in `PROPOSED`, `APPROVED`, or `INSTALLED` is moved to
    `CANCELLED`".

    Design: Difficulty/transitive_cascade/job_cancel_cascade_scope_rebate_depth2
    """
    ctx = setup_job_cancel_cascade_ready()
    job = validate_success(api.cancel_job(ctx["job"]["id"], program_admin_headers), 200)
    assert job["job_status"] == "CANCELLED"
    scope = validate_success(api.get_scope_item(ctx["scope"]["id"], program_admin_headers))
    assert scope["status"] == "CANCELLED"


def test_cancel_voids_rebate_and_cancels_assignment(api, program_admin_headers):
    """PRD 3.2: "for each such scope item that had a rebate claim in `APPROVED`
    status, that claim is moved to `VOIDED`, which returns its
    `finalized_amount_cents` to the budget by decrementing the job's
    `approved_rebate_total_cents`. Separately, every crew assignment for the job
    still in `SCHEDULED` is moved to `CANCELLED`, releasing its reserved
    crew-days back to the crew".

    Design: Difficulty/transitive_cascade/job_cancel_cascade_scope_rebate_depth2
    """
    ctx = setup_job_cancel_cascade_ready()
    api.cancel_job(ctx["job"]["id"], program_admin_headers)
    rebate = validate_success(api.get_rebate_claim(ctx["rebate"]["id"], program_admin_headers))
    assert rebate["status"] == "VOIDED"
    assignment = validate_success(api.get_crew_assignment(ctx["assignment"]["id"], program_admin_headers))
    assert assignment["status"] == "CANCELLED"
    job = validate_success(api.get_job(ctx["job"]["id"], program_admin_headers))
    assert job["approved_rebate_total_cents"] == 0


# ── safety_beats_constraint_on_verify (priority 9 over 10) ────────────────
def test_verify_sod_and_scope_incomplete_returns_sod(api):
    """PRD 2.5: "Lower-numbered checks take priority over higher-numbered ones".
    PRD 2.5: "9. **Segregation of duties** — at verification, the acting
    auditor's `X-User-ID` must not equal the baseline blower-door test's
    `tester_user_id`, or `ERR_SOD_VIOLATION` (409)."
    PRD 2.5: "10. **Structural constraints** — the operation's structural
    preconditions must hold; the code varies: `ERR_SCOPE_INCOMPLETE`,
    `ERR_CREW_DOUBLE_BOOKED`, `ERR_DWELLING_WINDOW_CONFLICT`, or
    `ERR_CREW_CAPACITY_EXCEEDED`, each HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_verify
    """
    ctx = setup_verify_ready_no_scope(baseline_cfm=3000, post_cfm=2400, baseline_tester="auditor-alice", post_tester="auditor-bob")
    res = api.verify_job(ctx["job"]["id"], {"post_test_id": ctx["post_test_id"]}, ALICE)
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION)


def test_verify_sod_violation_leaves_verification_pending(api, program_admin_headers):
    """PRD 3.8: "the acting auditor's `X-User-ID` must not equal the
    `tester_user_id` recorded on the job's baseline blower-door test, or the
    request is rejected with `ERR_SOD_VIOLATION` — the person who recorded the
    baseline may not sign off on the outcome."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_verify
    """
    ctx = setup_verify_ready_no_scope(baseline_cfm=3000, post_cfm=2400, baseline_tester="auditor-alice", post_tester="auditor-bob")
    api.verify_job(ctx["job"]["id"], {"post_test_id": ctx["post_test_id"]}, ALICE)
    job = validate_success(api.get_job(ctx["job"]["id"], program_admin_headers))
    assert job["verification_status"] == "PENDING"


# ── verify_empty_installed_scope_set_rejected (SOD satisfied -> scope check) ─
def test_verify_no_installed_scope_returns_scope_incomplete(api):
    """PRD 3.8: "The job must also have at least one scope item in `INSTALLED`
    status; if none is installed, verification fails with `ERR_SCOPE_INCOMPLETE`."

    Design: Difficulty/boundary_precision_check/verify_empty_installed_scope_set_rejected
    """
    ctx = setup_verify_ready_no_scope(baseline_cfm=3000, post_cfm=2400, baseline_tester="auditor-alice", post_tester="auditor-bob")
    res = api.verify_job(ctx["job"]["id"], {"post_test_id": ctx["post_test_id"]}, BOB)
    validate_error(res, ApiErrorId.ERR_SCOPE_INCOMPLETE)


def test_verify_empty_scope_leaves_verification_pending(api, program_admin_headers):
    """PRD 3.8: "The job must also have at least one scope item in `INSTALLED`
    status; if none is installed, verification fails with `ERR_SCOPE_INCOMPLETE`."

    Design: Difficulty/boundary_precision_check/verify_empty_installed_scope_set_rejected
    """
    ctx = setup_verify_ready_no_scope(baseline_cfm=3000, post_cfm=2400, baseline_tester="auditor-alice", post_tester="auditor-bob")
    api.verify_job(ctx["job"]["id"], {"post_test_id": ctx["post_test_id"]}, BOB)
    job = validate_success(api.get_job(ctx["job"]["id"], program_admin_headers))
    assert job["verification_status"] == "PENDING"


# ── post_diagnostic_without_baseline_returns_baseline_required (corner) ────
def test_post_diagnostic_without_baseline_rejected(api, auditor_headers):
    """PRD 3.3: "When a test's `stage` is `POST`, it must carry a
    `baseline_test_id` that references a `BASELINE` test of the same job and the
    same `kind`; a POST-stage test that does not reference such a matching
    baseline is rejected with `ERR_BASELINE_TEST_REQUIRED`."

    Design: Corner/validations/post_diagnostic_without_baseline_returns_baseline_required
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    payload = create_diagnostic_test_payload(job["id"], kind="BLOWER_DOOR", stage="POST", cfm_measured=2400)
    res = api.create_diagnostic_test(payload, auditor_headers)
    validate_error(res, ApiErrorId.ERR_BASELINE_TEST_REQUIRED)
