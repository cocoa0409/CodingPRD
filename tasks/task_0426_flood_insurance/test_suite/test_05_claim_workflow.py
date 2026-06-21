"""Claim workflow: the SUBMITTED -> UNDER_REVIEW -> {APPROVED,DENIED} machine,
the proof-of-loss revision loop, cross-entity state preconditions, the inclusive
60-day proof-of-loss deadline, and the coverage-window check.

Covers difficulty queue A (non_linear_state_machine claim cycle,
cross_entity_state_dependency, boundary_precision_check proof-of-loss,
resource_temporal_overlap) and corner queue B (state_machines, validations,
endpoints, errors sections for claims/proofs).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    set_clock,
    setup_active_policy,
    setup_bound_policy,
    setup_claim_under_review,
    file_claim,
    open_review,
    file_proof_of_loss,
    accept_proof_of_loss,
    deny_claim,
    assert_claim,
    ApiErrorId,
    TEST_USERS,
)


# --- Revision loop (cyclic state machine) ----------------------------------

def test_proof_reject_bounces_claim_back_to_submitted(api):
    """PRD §3.9: "Rejection of a pending proof-of-loss moves its `review_status`
    to `REJECTED` and, when the rejected proof supports a claim that is
    `UNDER_REVIEW`, bounces that claim back to `SUBMITTED`, advancing the claim's
    `version` as well."

    Design: Difficulty/non_linear_state_machine/claim_review_revision_cycle_under_review_to_submitted
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="holder-5", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
    )
    proof = file_proof_of_loss(claim["id"], "holder-5", documented_building_loss=9999)
    rejected = validate_success(
        api.reject_proof_of_loss(proof["id"], TEST_USERS["adjuster_headers"])
    )
    assert rejected["review_status"] == "REJECTED", rejected["review_status"]

    fetched = validate_success(
        api.get_claim(claim["id"], TEST_USERS["adjuster_headers"])
    )
    assert fetched["status"] == "SUBMITTED", fetched["status"]


def test_proof_reject_leaves_claims_paid_ledger_at_zero(api):
    """PRD §3.10: "a denial moves the claim to the terminal `DENIED` status,
    leaves `settlement_total` at 0, and has no ledger impact."
    PRD §3.9: "bounces that claim back to `SUBMITTED`, advancing the claim's
    `version` as well."

    Design: Difficulty/compensating_invariant/review_bounce_claims_paid_ledger_conservation
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="holder-20", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
    )
    proof = file_proof_of_loss(claim["id"], "holder-20", documented_building_loss=5000)
    api.reject_proof_of_loss(proof["id"], TEST_USERS["adjuster_headers"])

    fetched_claim = validate_success(
        api.get_claim(claim["id"], TEST_USERS["adjuster_headers"])
    )
    assert fetched_claim["status"] == "SUBMITTED", fetched_claim["status"]
    assert fetched_claim["settlement_total"] == 0, fetched_claim["settlement_total"]

    fetched_policy = validate_success(
        api.get_policy(policy["id"], TEST_USERS["underwriter_headers"])
    )
    assert fetched_policy["total_claims_paid"] == 0, fetched_policy["total_claims_paid"]


# --- Cross-entity state dependencies ---------------------------------------

def test_open_review_requires_policy_active(api):
    """PRD §3.8: "the claim's policy must currently be `ACTIVE`, failing which the
    request is rejected with `ERR_POLICY_NOT_ACTIVE` (HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/claim_open_review_requires_policy_active
    """
    community, prop, bound = setup_bound_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="holder-15",
        flood_zone="X", base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
        crs_class=10, is_lender_required=True,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    claim = file_claim(bound["id"], "holder-15", "2026-04-10T00:00:00Z", building_loss=5000)
    resp = api.open_review(claim["id"], TEST_USERS["adjuster_headers"])
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE, expected_status=409)


def test_proof_accept_requires_claim_under_review(api):
    """PRD §3.9: "Acceptance is permitted only when the proof is `PENDING` and the
    claim it supports is `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`, HTTP
    409)."

    Design: Difficulty/cross_entity_state_dependency/proof_accept_requires_claim_under_review
    """
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="holder-16",
        flood_zone="X", base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
        crs_class=10, is_lender_required=True,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    # Claim filed but never opened for review (stays SUBMITTED).
    claim = file_claim(active["id"], "holder-16", "2026-04-10T00:00:00Z", building_loss=5000)
    proof = file_proof_of_loss(claim["id"], "holder-16", documented_building_loss=5000)
    resp = api.accept_proof_of_loss(proof["id"], TEST_USERS["adjuster_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# --- Deadline boundary and coverage window ---------------------------------

def test_proof_of_loss_accepts_at_day_60(api):
    """PRD §3.9: "the sixty-day deadline is inclusive, so `days_after_loss` must
    be at most 60 — exactly day 60 is on time and day 61 is late — and a late
    filing is rejected with `ERR_PROOF_OF_LOSS_LATE` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/proof_of_loss_day60_accepts_day61_rejects
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="holder-13", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
        date_of_loss="2026-04-10T00:00:00Z",
    )
    set_clock("2026-06-09T00:00:00Z")  # exactly day 60 after 2026-04-10
    proof = file_proof_of_loss(claim["id"], "holder-13", documented_building_loss=5000)
    assert proof["days_after_loss"] == 60, proof["days_after_loss"]
    accepted = validate_success(
        api.accept_proof_of_loss(proof["id"], TEST_USERS["adjuster_headers"])
    )
    assert accepted["review_status"] == "ACCEPTED", accepted["review_status"]


def test_proof_of_loss_rejects_at_day_61(api):
    """PRD §3.9: "the sixty-day deadline is inclusive, so `days_after_loss` must
    be at most 60 — exactly day 60 is on time and day 61 is late — and a late
    filing is rejected with `ERR_PROOF_OF_LOSS_LATE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/proof_of_loss_inclusive_60day_window_collision
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="holder-18", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
        date_of_loss="2026-04-10T00:00:00Z",
    )
    set_clock("2026-06-10T00:00:00Z")  # day 61 after 2026-04-10
    proof = file_proof_of_loss(claim["id"], "holder-18", documented_building_loss=5000)
    assert proof["days_after_loss"] == 61, proof["days_after_loss"]
    resp = api.accept_proof_of_loss(proof["id"], TEST_USERS["adjuster_headers"])
    validate_error(resp, ApiErrorId.ERR_PROOF_OF_LOSS_LATE, expected_status=409)


def test_loss_inside_waiting_period_outside_coverage(api):
    """PRD §3.8: "the `date_of_loss` must fall within the coverage window — at or
    after the policy's `effective_date` and strictly before its `expiration_date`
    — so that a loss during the waiting period or on/after expiration is rejected
    with `ERR_LOSS_OUTSIDE_COVERAGE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/loss_inside_waiting_period_outside_coverage_halfopen
    """
    # Standard 30-day policy: bound 2026-03-01 -> effective 2026-03-31.
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", activate_clock="2026-03-31T00:00:00Z",
        owner_id="holder-17", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10, is_lender_required=False,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    # Loss 2026-03-15 falls inside the waiting period, before effective_date.
    claim = file_claim(active["id"], "holder-17", "2026-03-15T00:00:00Z", building_loss=5000)
    resp = api.open_review(claim["id"], TEST_USERS["adjuster_headers"])
    validate_error(resp, ApiErrorId.ERR_LOSS_OUTSIDE_COVERAGE, expected_status=409)


# --- Corner: claim/proof state-machine breadth -----------------------------

def test_claim_starts_in_submitted_state(api):
    """PRD §3.8: "A newly filed claim enters the `SUBMITTED` status."

    Design: Corner/state_machines/claim_initial_state_submitted
    """
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="h-in",
        flood_zone="X", base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
        crs_class=10, is_lender_required=True,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    claim = file_claim(active["id"], "h-in", "2026-04-10T00:00:00Z", building_loss=5000)
    assert_claim(claim)
    assert claim["status"] == "SUBMITTED", claim["status"]
    assert claim["settlement_total"] == 0, claim["settlement_total"]


def test_open_review_twice_rejected(api):
    """PRD §3.8: "The transition is permitted only from `SUBMITTED` (otherwise
    `ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/open_review_twice_idempotency_invalid_state
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="h-id", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
    )
    resp = api.open_review(claim["id"], TEST_USERS["adjuster_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_approve_on_denied_claim_rejected(api):
    """PRD §3.10: "the claim must be `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`,
    HTTP 409)"

    Design: Corner/state_machines/approve_claim_from_terminal_denied_returns_invalid_state
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="h-dn", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
    )
    denied = deny_claim(claim["id"], claim["version"])
    assert denied["status"] == "DENIED", denied["status"]
    resp = api.approve_claim(
        claim["id"], {"expected_claim_version": denied["version"]},
        TEST_USERS["adjuster_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# --- Corner: approval gating validations -----------------------------------

def test_approve_without_accepted_proof_rejected(api):
    """PRD §3.10: "an accepted proof-of-loss must exist for it — a proof whose
    `review_status` is `ACCEPTED` — failing which the approval is rejected with
    `ERR_PROOF_OF_LOSS_MISSING` (HTTP 409)"

    Design: Corner/validations/approve_without_accepted_proof_returns_pol_missing
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="h-pm", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
    )
    resp = api.approve_claim(
        claim["id"], {"expected_claim_version": claim["version"]},
        TEST_USERS["adjuster_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PROOF_OF_LOSS_MISSING, expected_status=409)


def test_proof_figure_mismatch_rejected(api):
    """PRD §3.9: "the sum of `documented_building_loss` and
    `documented_contents_loss` must equal the sum of the claim's `building_loss`
    and `contents_loss`, and a mismatch is rejected with
    `ERR_PROOF_OF_LOSS_MISMATCH` (HTTP 422)."

    Design: Corner/validations/proof_of_loss_figure_mismatch_rejected
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="h-mm", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
        date_of_loss="2026-04-10T00:00:00Z",
    )
    set_clock("2026-04-20T00:00:00Z")  # in-window, so timeliness passes
    proof = file_proof_of_loss(claim["id"], "h-mm", documented_building_loss=9999)
    resp = api.accept_proof_of_loss(proof["id"], TEST_USERS["adjuster_headers"])
    validate_error(resp, ApiErrorId.ERR_PROOF_OF_LOSS_MISMATCH, expected_status=422)


def test_icc_on_non_substantial_claim_not_eligible(api):
    """PRD §3.10: "an ICC cost supplied on a non-substantial claim is the
    condition behind `ERR_ICC_NOT_ELIGIBLE` (HTTP 422)."

    Design: Corner/validations/icc_on_non_substantial_claim_not_eligible
    """
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="h-ie",
        flood_zone="X", base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
        crs_class=10, is_lender_required=True,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    claim = file_claim(
        active["id"], "h-ie", "2026-04-10T00:00:00Z",
        building_loss=0, contents_loss=0, substantial_damage=False, icc_eligible_cost=18000,
    )
    claim = open_review(claim["id"])
    proof = file_proof_of_loss(
        claim["id"], "h-ie", documented_building_loss=0, documented_contents_loss=0
    )
    accept_proof_of_loss(proof["id"])
    resp = api.approve_claim(
        claim["id"], {"expected_claim_version": claim["version"]},
        TEST_USERS["adjuster_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ICC_NOT_ELIGIBLE, expected_status=422)


# --- Corner: claim listing -------------------------------------------------

def test_list_claims_by_policy_filter(api):
    """PRD §2.5: "claims by `policy_id`"

    Design: Corner/endpoints/list_claims_by_policy_filter_reverse_reachability
    """
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="h-fl",
        flood_zone="X", base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
        crs_class=10, is_lender_required=True,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    claim = file_claim(active["id"], "h-fl", "2026-04-10T00:00:00Z", building_loss=5000)
    resp = api.list_claims(TEST_USERS["adjuster_headers"], params={"policy_id": active["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, data
    assert data[0]["id"] == claim["id"], data[0]["id"]
