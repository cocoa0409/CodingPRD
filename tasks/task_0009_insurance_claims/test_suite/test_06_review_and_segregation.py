"""Primary review (manual + auto path) and segregation of duties.

Pinned to PRD §3.4 (decisions), §2.7 (segregation of duties).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_decision_payload,
    setup_claim_under_review, setup_claim_approved, setup_claim_denied,
    record_primary_decision, get_claim,
    make_adjuster_headers, make_reviewer_headers, TEST_USERS,
)


# ─── §3.4 manual approve / deny ───────────────────────────────────
def test_primary_review_approve_transitions_to_approved(api):
    """PRD §3.4: "Approval moves the claim to `APPROVED`; ... Both outcomes
    write a `ReviewDecision` row, both refresh the claim's audit log, and
    both increment `Claim.version`."

    Claim: APPROVE outcome -> Claim.status == APPROVED, ReviewDecision row written.
    """
    state = setup_claim_under_review(
        claimed_amount_cents=5_000_000, assessed_loss_cents=5_000_000,
        coverage_limit_cents=100_000_000,
    )
    state = record_primary_decision(state, outcome="APPROVE")
    refreshed = get_claim(state["claim"]["id"])
    assert refreshed["status"] == "APPROVED"
    decision = state["primary_decision"]
    assert decision["review_level"] == "PRIMARY"
    assert decision["outcome"] == "APPROVE"
    assert decision["claim_id"] == state["claim"]["id"]


def test_primary_review_deny_transitions_to_denied_and_records_rationale(api):
    """PRD §3.4: "denial moves it to `DENIED` and copies the reviewer's
    `rationale` into the claim's `denial_reason`."

    Claim: DENY outcome -> Claim.status == DENIED, denial_reason populated.
    """
    state = setup_claim_under_review(
        claimed_amount_cents=5_000_000, assessed_loss_cents=5_000_000,
        coverage_limit_cents=100_000_000,
    )
    state = record_primary_decision(
        state, outcome="DENY",
        rationale="Damage predates the policy.",
    )
    refreshed = get_claim(state["claim"]["id"])
    assert refreshed["status"] == "DENIED"
    assert refreshed["denial_reason"] == "Damage predates the policy."


# ─── §2.7 segregation of duties (primary) ─────────────────────────
def test_primary_reviewer_cannot_be_adjuster(api):
    """PRD §2.7: "At primary-review time, the `X-User-ID` recording the
    decision must differ from the `Investigation.adjuster_id` of the
    claim's investigation; a violation is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Claim: a Reviewer whose X-User-ID equals the assigned adjuster id is
    rejected with ERR_SEGREGATION_OF_DUTIES.
    """
    state = setup_claim_under_review(
        claimed_amount_cents=5_000_000, assessed_loss_cents=5_000_000,
        coverage_limit_cents=100_000_000,
    )
    # Use the adjuster's id as the Reviewer X-User-ID.
    headers = {"X-User-ID": state["adjuster"]["id"], "X-User-Role": "Reviewer"}
    res = api.create_decision(
        state["claim"]["id"],
        create_decision_payload(outcome="APPROVE"),
        headers,
    )
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


# ─── §3.3 / §3.4 auto path (claimed_amount <= 200000 and fraud<0.30) ──
def test_auto_path_succeeds_without_manual_decision(api):
    """PRD §3.4: "When the path is `AUTO`, the server itself records a
    primary review decision through the same decision-recording capability
    used for manual reviews, but with the actor recorded as `system`: a
    `ReviewDecision` row is written with `review_level` set to `PRIMARY`
    and `outcome` set to `APPROVE`, the claim moves from `UNDER_REVIEW` to
    `APPROVED`, and the audit log captures both the `REVIEW_DECISION` event
    and the `STATUS_CHANGE`."

    Claim: a low-amount, low-fraud claim is auto-approved at
    submit-for-review without any reviewer call.
    """
    # claimed_amount=100000 <= 200000 and zero fraud -> AUTO path.
    state = setup_claim_under_review(
        claimed_amount_cents=100_000,
        assessed_loss_cents=100_000,
        deductible_cents=0,
        coinsurance_ratio=1.0,
        coverage_limit_cents=10_000_000,
    )
    refreshed = get_claim(state["claim"]["id"])
    # Either UNDER_REVIEW (auto-approval may be a separate step) or APPROVED
    # — PRD §3.4 says the server itself records the decision after submit.
    assert refreshed["review_path"] == "AUTO"
    assert refreshed["status"] == "APPROVED", (
        f"AUTO path must auto-approve at submit: status={refreshed['status']!r}"
    )


# ─── §3.4 RBAC + state preconditions ──────────────────────────────
def test_decision_rejected_when_claim_not_under_review(api):
    """PRD §1.2/§2.6 cascade: state check (priority 4) — the claim must
    be in `UNDER_REVIEW` for a decision to be filed.

    Claim: filing a decision against a claim still in INTAKE -> ERR_INVALID_STATE.
    """
    from test_helpers import setup_basic_world, file_claim
    world = setup_basic_world()
    claim = file_claim(world)  # INTAKE
    headers = make_reviewer_headers("rev-state-1")
    res = api.create_decision(
        claim["id"],
        create_decision_payload(outcome="APPROVE"),
        headers,
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_decision_rbac_only_reviewer(api, customer_headers):
    """PRD §4 endpoints table: POST /claims/{id}/decisions is Reviewer-only.

    Claim: Customer calling decisions -> ERR_FORBIDDEN.
    """
    state = setup_claim_under_review(
        claimed_amount_cents=5_000_000, assessed_loss_cents=5_000_000,
        coverage_limit_cents=100_000_000,
    )
    res = api.create_decision(
        state["claim"]["id"],
        create_decision_payload(outcome="APPROVE"),
        customer_headers,
    )
    validate_error(res, "ERR_FORBIDDEN")


# ─── §3.4 race outcome ───────────────────────────────────────────
def test_two_reviewers_decide_only_one_wins(api):
    """PRD §3.4: "If two reviewers race to decide the same claim, exactly
    one wins; the loser is rejected with `ERR_INVALID_STATE` because, by
    the time the loser's transaction observes the claim, it has already
    left `UNDER_REVIEW`."

    Claim: two parallel POST /decisions on the same UNDER_REVIEW claim ->
    exactly one succeeds; the other returns ERR_INVALID_STATE.
    """
    from test_helpers import run_race, assert_exactly_one_succeeds, validate_error_is_one_of
    state = setup_claim_under_review(
        claimed_amount_cents=5_000_000, assessed_loss_cents=5_000_000,
        coverage_limit_cents=100_000_000,
    )
    h1 = make_reviewer_headers("race-rev-1")
    h2 = make_reviewer_headers("race-rev-2")
    results = run_race(
        lambda: api.create_decision(state["claim"]["id"],
                                     create_decision_payload(outcome="APPROVE"), h1),
        lambda: api.create_decision(state["claim"]["id"],
                                     create_decision_payload(outcome="DENY"), h2),
    )
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    # The losing 4xx should be ERR_INVALID_STATE per PRD prose.
    loser = outcome["failures"][0]
    validate_error_is_one_of(loser, ["ERR_INVALID_STATE"])
