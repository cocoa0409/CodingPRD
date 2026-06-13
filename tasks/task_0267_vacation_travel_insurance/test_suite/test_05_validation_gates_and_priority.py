"""Claim-approval eligibility gates, the delay threshold boundary, and cross-entity
state dependencies (§3.4, §3.6, §3.8).

Covers difficulty rules priority_pair_validation_conflict (named-storm cutoff vs fiscal),
boundary_precision_check (delay 12h inclusive / 11h rejected), cross_entity_state_dependency
(claim filing requires ACTIVE policy; payout creation requires APPROVED claim), and the
corner validation instances.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_active_policy, setup_claim_under_review, setup_paid_quoted_policy,
    approve_claim, set_clock,
    create_named_storm, file_claim, make_traveler_headers,
    create_claim_payload, create_payout_payload, TEST_USERS,
)

ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ─── priority_pair_validation_conflict: named-storm cutoff on approve ──────

def test_named_storm_cutoff_blocks_approval_when_issued_after_named(api):
    """PRD §3.6: "For a `CANCELLATION` claim whose `cancellation_reason` is `NAMED_STORM`, the
    policy's `issued_at` must be strictly earlier than the cited storm's `named_at` — coverage
    purchased on or after the storm was named does not cover that storm — else
    `ERR_NAMED_STORM_CUTOFF`."
    PRD §3.6: "the safety and eligibility gates run before any fiscal computation."

    Storm named 2026-06-02, policy issued 2026-06-03 (issued_at >= named_at): approving the
    storm-cancellation claim is rejected on the eligibility gate with ERR_NAMED_STORM_CUTOFF,
    before any reimbursement/aggregate computation.

    Design: Difficulty/priority_pair_validation_conflict/named_storm_cutoff_beats_aggregate_fiscal_on_approve
    """
    storm = create_named_storm(name="Hurricane Cutoff A", basin="ATLANTIC",
                               named_at="2026-06-02T00:00:00Z")
    bundle = setup_claim_under_review(
        plan_overrides={"base_rate_bps": 600, "cancellation_limit_pct": 100},
        policy_overrides={"initial_deposit_at": "2026-05-28T00:00:00Z"},
        peril="CANCELLATION", incident_at="2026-06-04T00:00:00Z",
        claim_overrides={"cancellation_reason": "NAMED_STORM", "named_storm_id": storm["id"]},
        expenses=[{"category": "PREPAID_TRIP", "description": "all",
                   "documented_amount_cents": 500000, "prepaid_nonrefundable_cents": 500000}],
        doc_type="RECEIPT", clock="2026-06-03T00:00:00Z",
    )
    res = api.approve_claim(bundle["claim"]["id"], ADJUSTER)
    validate_error(res, "ERR_NAMED_STORM_CUTOFF")


def test_named_storm_claim_approved_when_issued_before_named(api):
    """PRD §3.6: "the policy's `issued_at` must be strictly earlier than the cited storm's
    `named_at` — coverage purchased on or after the storm was named does not cover that storm —
    else `ERR_NAMED_STORM_CUTOFF`."

    The boundary companion: a policy issued 2026-06-01, strictly before the storm's named_at
    2026-06-05, covers the storm — approval succeeds.

    Design: Difficulty/priority_pair_validation_conflict/named_storm_cutoff_beats_aggregate_fiscal_on_approve
    """
    set_clock("2026-06-01T00:00:00Z")
    storm = create_named_storm(name="Hurricane Cutoff B", basin="ATLANTIC",
                               named_at="2026-06-05T00:00:00Z")
    bundle = setup_claim_under_review(
        plan_overrides={"base_rate_bps": 600, "cancellation_limit_pct": 100},
        policy_overrides={"initial_deposit_at": "2026-05-28T00:00:00Z"},
        peril="CANCELLATION", incident_at="2026-06-06T00:00:00Z",
        claim_overrides={"cancellation_reason": "NAMED_STORM", "named_storm_id": storm["id"]},
        expenses=[{"category": "PREPAID_TRIP", "description": "all",
                   "documented_amount_cents": 500000, "prepaid_nonrefundable_cents": 500000}],
        doc_type="RECEIPT", clock=None,
    )
    approved = validate_success(api.approve_claim(bundle["claim"]["id"], ADJUSTER), 200)
    assert approved["status"] == "APPROVED", \
        "storm claim must approve when issued_at is strictly earlier than named_at"


# ─── boundary_precision_check: delay 12h inclusive / 11h rejected ──────────

def test_delay_at_twelve_hours_covered(api):
    """PRD §3.6: "For a **delay** claim, the number of completed delay blocks is the floor of
    `delay_hours` divided by 12".
    PRD §3.6: "For a `DELAY` claim, `delay_hours` must be at least 12, else
    `ERR_DELAY_BELOW_THRESHOLD`."

    delay_hours == 12 is at the inclusive threshold: floor(12/12)=1 block * 20000 = 20000.

    Design: Difficulty/boundary_precision_check/delay_threshold_inclusive_12h_covered_11h_rejected
    """
    bundle = setup_claim_under_review(
        plan_overrides={"base_rate_bps": 600, "delay_block_cap_cents": 20000,
                        "delay_limit_cents": 100000},
        peril="DELAY", incident_at="2026-06-05T00:00:00Z",
        claim_overrides={"delay_hours": 12}, doc_type="CARRIER_DELAY_LETTER",
    )
    approved = validate_success(api.approve_claim(bundle["claim"]["id"], ADJUSTER), 200)
    assert approved["status"] == "APPROVED"
    assert approved["approved_amount_cents"] == 20000, \
        f"delay at 12h must approve 20000, got {approved['approved_amount_cents']}"


def test_delay_at_eleven_hours_rejected(api):
    """PRD §3.6: "For a `DELAY` claim, `delay_hours` must be at least 12, else
    `ERR_DELAY_BELOW_THRESHOLD`."

    delay_hours == 11 is below the inclusive 12-hour threshold and approval is rejected with
    ERR_DELAY_BELOW_THRESHOLD.

    Design: Difficulty/boundary_precision_check/delay_threshold_inclusive_12h_covered_11h_rejected
    """
    bundle = setup_claim_under_review(
        plan_overrides={"base_rate_bps": 600, "delay_block_cap_cents": 20000,
                        "delay_limit_cents": 100000},
        peril="DELAY", incident_at="2026-06-05T00:00:00Z",
        claim_overrides={"delay_hours": 11}, doc_type="CARRIER_DELAY_LETTER",
    )
    res = api.approve_claim(bundle["claim"]["id"], ADJUSTER)
    validate_error(res, "ERR_DELAY_BELOW_THRESHOLD")


# ─── cross_entity_state_dependency: filing & payout creation gates ─────────

def test_claim_filing_requires_active_policy(api):
    """PRD §3.4: "Only the owning `Traveler` files a claim, and only against a policy whose
    `coverage_status` is `ACTIVE` — a claim filed against a non-active policy is rejected with
    `ERR_POLICY_NOT_ACTIVE`."

    A policy still QUOTED (premium paid but not issued) rejects claim filing with
    ERR_POLICY_NOT_ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/claim_filing_requires_policy_coverage_active
    """
    bundle = setup_paid_quoted_policy(
        plan_overrides={"tier": "BASIC", "base_rate_bps": 400}, clock="2026-06-01T00:00:00Z")
    headers = make_traveler_headers(bundle["traveler_id"])
    res = api.create_claim(create_claim_payload(
        bundle["policy"]["id"], bundle["insured"]["id"], "MEDICAL", "2026-06-02T00:00:00Z"),
        headers)
    validate_error(res, "ERR_POLICY_NOT_ACTIVE")


def test_claim_filing_succeeds_against_active_policy(api):
    """PRD §3.4: "only against a policy whose `coverage_status` is `ACTIVE`".
    PRD §3.4: "A new claim is born `SUBMITTED`."

    The positive companion of the cross-entity dependency: filing against an ACTIVE policy is
    accepted and the claim is born SUBMITTED.

    Design: Difficulty/cross_entity_state_dependency/claim_filing_requires_policy_coverage_active
    """
    active = setup_active_policy(plan_overrides={"tier": "BASIC", "base_rate_bps": 400},
                                 clock="2026-06-01T00:00:00Z")
    claim = file_claim(active["policy"]["id"], active["insured"]["id"], active["traveler_id"],
                       "MEDICAL", "2026-06-02T00:00:00Z")
    assert claim["status"] == "SUBMITTED", \
        f"claim against an ACTIVE policy must be born SUBMITTED, got {claim['status']}"


def test_payout_creation_requires_approved_claim(api):
    """PRD §3.8: "A payout cannot be created against a claim that is not `APPROVED` — that is
    rejected with `ERR_CLAIM_NOT_APPROVED`."

    A claim merely UNDER_REVIEW (not yet approved) rejects payout creation with
    ERR_CLAIM_NOT_APPROVED.

    Design: Difficulty/cross_entity_state_dependency/payout_creation_requires_claim_approved
    """
    bundle = setup_claim_under_review(
        plan_overrides={"base_rate_bps": 600}, peril="MEDICAL",
        incident_at="2026-06-05T00:00:00Z", doc_type="MEDICAL_REPORT")
    res = api.create_payout(create_payout_payload(bundle["claim"]["id"]), ADJUSTER)
    validate_error(res, "ERR_CLAIM_NOT_APPROVED")


def test_payout_creation_succeeds_for_approved_claim(api):
    """PRD §3.8: "Once a claim is approved, a `ClaimsAdjuster` creates a **payout** for it by
    supplying the `claim_id`. The payout is born `PENDING`; the server copies the claim's policy
    onto the payout's `policy_id` for ledger reconciliation and sets the payout's `amount_cents`
    equal to the claim's `approved_amount_cents`."

    The positive companion: creating a payout against an APPROVED claim yields a PENDING payout
    whose amount_cents equals the claim's approved_amount_cents.

    Design: Difficulty/cross_entity_state_dependency/payout_creation_requires_claim_approved
    """
    bundle = setup_claim_under_review(
        plan_overrides={"base_rate_bps": 600, "medical_limit_cents": 500000}, peril="MEDICAL",
        incident_at="2026-06-05T00:00:00Z",
        expenses=[{"category": "MEDICAL_BILL", "description": "ER",
                   "documented_amount_cents": 100000}],
        doc_type="MEDICAL_REPORT")
    claim = approve_claim(bundle["claim"]["id"])
    payout = validate_success(
        api.create_payout(create_payout_payload(claim["id"]), ADJUSTER), 201)
    assert payout["status"] == "PENDING"
    assert payout["amount_cents"] == claim["approved_amount_cents"], \
        "payout amount_cents must equal the claim's approved_amount_cents"


# ─── Corner: validation gates ──────────────────────────────────────────────

def test_preexisting_medical_without_waiver_denied_on_approve(api):
    """PRD §3.6: "For a `MEDICAL` claim whose `involves_preexisting` is `true`, the policy's
    `preexisting_waiver_granted` must be `true`, else `ERR_PREEXISTING_NOT_WAIVED`."

    Plan waiver_window_days 3, issued 31 days after initial_deposit -> waiver NOT granted; a
    MEDICAL claim with involves_preexisting=true is rejected at approval.

    Design: Corner/validations/preexisting_medical_without_waiver_denied_on_approve
    """
    bundle = setup_claim_under_review(
        plan_overrides={"base_rate_bps": 600, "waiver_window_days": 3,
                        "medical_limit_cents": 500000},
        policy_overrides={"initial_deposit_at": "2026-05-01T00:00:00Z"},
        insured_overrides={"has_preexisting_condition": True},
        peril="MEDICAL", incident_at="2026-06-05T00:00:00Z",
        claim_overrides={"involves_preexisting": True},
        expenses=[{"category": "MEDICAL_BILL", "description": "ER",
                   "documented_amount_cents": 100000}],
        doc_type="MEDICAL_REPORT", clock="2026-06-01T00:00:00Z",
    )
    res = api.approve_claim(bundle["claim"]["id"], ADJUSTER)
    validate_error(res, "ERR_PREEXISTING_NOT_WAIVED")


def test_approve_without_documentation_returns_documentation_missing(api):
    """PRD §3.6: "And there must be at least one document on the claim, else
    `ERR_DOCUMENTATION_MISSING`."

    A MEDICAL claim under review with an expense but no document is rejected at approval.

    Design: Corner/validations/approve_without_documentation_returns_documentation_missing
    """
    bundle = setup_claim_under_review(
        plan_overrides={"base_rate_bps": 600, "medical_limit_cents": 500000},
        peril="MEDICAL", incident_at="2026-06-05T00:00:00Z",
        expenses=[{"category": "MEDICAL_BILL", "description": "ER",
                   "documented_amount_cents": 100000}],
        with_document=False,
    )
    res = api.approve_claim(bundle["claim"]["id"], ADJUSTER)
    validate_error(res, "ERR_DOCUMENTATION_MISSING")


def test_filing_window_closed_on_late_claim_submission(api):
    """PRD §3.4: "A claim is on time when the current clock is at or before `incident_at` plus
    the plan's `claim_filing_window_days`; a claim filed after that deadline is rejected with
    `ERR_FILING_WINDOW_CLOSED`."

    Clock 2026-06-01, claim_filing_window_days 90, incident_at 2026-01-01 (far past the window)
    on an ACTIVE policy -> ERR_FILING_WINDOW_CLOSED at submission.

    Design: Corner/validations/filing_window_closed_on_late_claim_submission
    """
    active = setup_active_policy(plan_overrides={"base_rate_bps": 600,
                                                 "claim_filing_window_days": 90},
                                 clock="2026-06-01T00:00:00Z")
    headers = make_traveler_headers(active["traveler_id"])
    res = api.create_claim(create_claim_payload(
        active["policy"]["id"], active["insured"]["id"], "MEDICAL", "2026-01-01T00:00:00Z"),
        headers)
    validate_error(res, "ERR_FILING_WINDOW_CLOSED")
