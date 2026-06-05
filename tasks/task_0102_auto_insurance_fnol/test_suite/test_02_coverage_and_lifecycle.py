"""Coverage verification, the claim state machine, and OCC on the claim.

Covers: verify-coverage denial reasons, the reopen->reverify cycle, invalid-state
transitions, terminal-state lockdown, and the assign-adjuster optimistic
concurrency rule (stale rejected, correct succeeds + bumps version).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_policy, add_collision_coverage, create_adjuster, file_claim,
    verify_claim, assign_claim,
    setup_claim_under_review, setup_repair_approved_claim,
    make_claims_adjuster_headers,
    TEST_USERS,
)

SUP = TEST_USERS["supervisor_headers"]


def test_coverage_denied_when_loss_outside_policy_window(api):
    """PRD §3.2: "the loss instant must fall within the coverage window, meaning
    `loss_datetime` is at or after the policy's `effective_date` and strictly before
    its `expiration_date`". PRD §3.2: "the claim instead moves `FNOL_SUBMITTED →
    COVERAGE_DENIED` and the recorded `CoverageVerification` has `outcome` `DENIED`, a
    null `matched_coverage_type`, and a `denial_reason` of `POLICY_INACTIVE`,
    `OUTSIDE_COVERAGE_WINDOW`, or `NO_MATCHING_COVERAGE` according to which condition
    failed."

    Design: Corner/state_machines/coverage_denied_when_loss_outside_policy_window
    """
    policy = create_policy(comparative_fault_rule="PURE",
                           effective_date="2026-06-01T00:00:00.000Z",
                           expiration_date="2026-12-31T00:00:00.000Z")
    add_collision_coverage(policy["id"])
    adjuster = create_adjuster(license_tier="STANDARD")
    claim = file_claim(policy["id"], adjuster["id"],
                       loss_datetime="2026-05-01T00:00:00.000Z",
                       loss_type="COLLISION", vehicle_acv_cents=800_000)
    headers = make_claims_adjuster_headers(adjuster["id"])
    verified = validate_success(api.verify_coverage(claim["id"], headers), 200)
    assert verified["status"] == "COVERAGE_DENIED"

    cvs, _meta = _list(api.list_coverage_verifications(claim["id"], headers))
    assert len(cvs) >= 1
    cv = cvs[0]
    assert cv["outcome"] == "DENIED"
    assert cv["denial_reason"] == "OUTSIDE_COVERAGE_WINDOW"


def test_reopen_denied_claim_allows_reverification_cycle(api):
    """PRD §3.2: "a `ClaimsSupervisor` may reopen such a claim, moving it
    `COVERAGE_DENIED → REOPENED`, which clears the prior coverage-verification
    linkage". PRD §3.2: "From `REOPENED`, the same verification action runs again
    against the same three conditions and, on success, advances the claim `REOPENED →
    COVERAGE_VERIFIED`".

    Design: Corner/state_machines/reopen_denied_claim_allows_reverification_cycle
    """
    # No matching coverage at first -> DENIED.
    policy = create_policy(comparative_fault_rule="PURE")
    adjuster = create_adjuster(license_tier="STANDARD")
    claim = file_claim(policy["id"], adjuster["id"], loss_type="COLLISION", vehicle_acv_cents=800_000)
    headers = make_claims_adjuster_headers(adjuster["id"])
    denied = validate_success(api.verify_coverage(claim["id"], headers), 200)
    assert denied["status"] == "COVERAGE_DENIED"
    # Correct the policy by adding the matching coverage, then reopen.
    add_collision_coverage(policy["id"])
    reopened = validate_success(api.reopen_claim(claim["id"], SUP), 200)
    assert reopened["status"] == "REOPENED"
    # Re-verify now succeeds.
    reverified = validate_success(api.verify_coverage(claim["id"], headers), 200)
    assert reverified["status"] == "COVERAGE_VERIFIED"


def test_verify_coverage_from_already_verified_returns_invalid_state(api):
    """PRD §3.6: "it confirm[s] the target resource is in a state from which the
    requested transition is defined, rejecting an out-of-state request with
    `ERR_INVALID_STATE`; this state guard governs every transition endpoint in the
    system." Verify is only defined from FNOL_SUBMITTED or REOPENED.

    Design: Corner/state_machines/verify_coverage_from_already_verified_returns_invalid_state
    """
    policy = create_policy(comparative_fault_rule="PURE")
    add_collision_coverage(policy["id"])
    adjuster = create_adjuster(license_tier="STANDARD")
    claim = file_claim(policy["id"], adjuster["id"], loss_type="COLLISION", vehicle_acv_cents=800_000)
    headers = make_claims_adjuster_headers(adjuster["id"])
    validate_success(api.verify_coverage(claim["id"], headers), 200)  # -> COVERAGE_VERIFIED
    res = api.verify_coverage(claim["id"], headers)  # no verify transition from COVERAGE_VERIFIED
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_settle_from_under_review_returns_invalid_state(api):
    """PRD §3.9: "A claim may be settled from either disposition outcome —
    `REPAIR_APPROVED → SETTLED` or `TOTAL_LOSS → SETTLED`". PRD §3.6: "Only then does it
    confirm the target resource is in a state from which the requested transition is
    defined, rejecting an out-of-state request with `ERR_INVALID_STATE`; this state
    guard governs every transition endpoint in the system." Settle is not defined from
    UNDER_REVIEW.

    Design: Corner/state_machines/settle_from_under_review_returns_invalid_state
    """
    ctx = setup_claim_under_review()  # claim is UNDER_REVIEW (assigned, no disposition)
    res = api.settle_claim(ctx["claim"]["id"], {"expected_claim_version": ctx["version"]}, SUP)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_terminal_closed_claim_rejects_further_transition(api):
    """PRD §3.9: "A settled claim is closed by a `ClaimsSupervisor`, moving it
    `SETTLED → CLOSED`, which is the claim's only terminal state." PRD §3.2:
    "Reopening is permitted only while the claim is in `COVERAGE_DENIED`." Reopen from
    terminal CLOSED is out of state.

    Design: Corner/state_machines/terminal_closed_claim_rejects_further_transition
    """
    ctx = setup_repair_approved_claim(repair_total_cents=600_000)  # REPAIR_APPROVED, settlement 550000
    claim_id = ctx["claim"]["id"]
    validate_success(api.settle_claim(claim_id, {"expected_claim_version": ctx["version"]}, SUP), 200)
    validate_success(api.close_claim(claim_id, SUP), 200)  # -> CLOSED
    res = api.reopen_claim(claim_id, SUP)  # reopen only from COVERAGE_DENIED
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Assign-adjuster OCC (cross_cutting_complexity_layers) ───

def test_occ_assign_adjuster_correct_version_succeeds_and_bumps(api):
    """PRD §3.3: "Once coverage is verified, a `ClaimsSupervisor` assigns a handling
    adjuster, moving the claim `COVERAGE_VERIFIED → UNDER_REVIEW`". PRD §3.3: "On
    success the claim's `assigned_adjuster_id` is set to the target adjuster and the
    claim's `version` is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/occ_assign_adjuster_correct_version_succeeds_and_bumps
    """
    policy = create_policy(comparative_fault_rule="PURE")
    add_collision_coverage(policy["id"])
    adjuster = create_adjuster(license_tier="STANDARD")
    claim = file_claim(policy["id"], adjuster["id"], loss_type="COLLISION", vehicle_acv_cents=800_000)
    verified = verify_claim(claim["id"], adjuster["id"])
    v1 = verified["version"]
    res = api.assign_adjuster(
        claim["id"],
        {"adjuster_id": adjuster["id"], "expected_claim_version": v1},
        SUP,
    )
    updated = validate_success(res, 200)
    assert updated["status"] == "UNDER_REVIEW"
    assert updated["version"] == v1 + 1


def _list(response):
    """Unwrap a list response into (data, meta) using the standard envelope."""
    body = response.json()
    return body["data"], body["meta"]
