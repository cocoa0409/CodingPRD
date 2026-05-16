"""Difficulty-design coverage — one or more dedicated tests per
SCAFFOLD_DIFFICULTY_DESIGN.yaml instance.

Each test is tagged with `# difficulty: <rule_id>/<instance.name>` so
the coverage audit can confirm every instance has at least TWO tests
(some tests are in this file; some are in the topic-organised files
test_05..test_10/test_11). The aim of this file is to top up coverage
to two-per-instance and add the deadline/expiration boundary tests.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    DEFAULT_APPROVAL_VALIDITY_DAYS,
    DEFAULT_EXPEDITED_SLA_HOURS,
    DEFAULT_STANDARD_SLA_HOURS,
    EXPEDITED_PENDING_INFO_EXTENSION_HOURS,
    HOURS_PER_DAY,
    STANDARD_PENDING_INFO_EXTENSION_HOURS,
    TEST_DEFAULTS,
    TEST_USERS,
    advance_clock_to,
    attach_evidence,
    cancel_peer_to_peer,
    complete_peer_to_peer,
    create_authorization_request,
    cycle_pending_info,
    decide_appeal,
    decide_authorization,
    decide_authorization_payload,
    file_appeal,
    file_appeal_payload,
    iso_offset,
    iso_utc,
    make_provider_headers,
    occ_payload,
    parse_iso,
    re_get_appeal,
    re_get_authorization,
    re_get_peer_to_peer,
    request_info,
    resume_review,
    schedule_peer_to_peer,
    schedule_peer_to_peer_payload,
    setup_authorization_for_two_pending_info_cycles,
    setup_authorization_in_peer_review,
    setup_authorization_in_peer_review_with_partial_evidence,
    setup_authorization_with_two_p2p_calls_for_same_payer_reviewer,
    setup_completed_p2p_on_authorization,
    setup_denied_authorization,
    setup_denied_then_overturn_with_patched_catalog,
    setup_denied_with_pending_tier1_appeal,
    setup_denied_with_tier1_upheld,
    setup_reference_data,
    setup_resubmission_with_n_reused_evidence,
    setup_submitted_with_empty_required_categories,
    setup_two_drafts_for_dual_deadline,
    setup_under_review_authorization,
    setup_under_review_with_partial_score_05,
    submit_authorization,
    validate_error,
    validate_success,
    withdraw_appeal,
)


# ===========================================================================
# Rule 1: dual_variant_calc
# ===========================================================================
def test_standard_and_expedited_decision_deadlines_diverge(api):
    """PRD §3.6: "The base window depends on urgency: a STANDARD
    request uses the version-pinned standard_sla_hours (default 14
    days), and an EXPEDITED request uses the version-pinned
    expedited_sla_hours (default 3 days)."

    Claim: two authorizations submitted at the same clock anchor under
    the same catalog item, differing only in urgency, produce
    decision_deadline_at values that differ by exactly
    standard_sla_hours − expedited_sla_hours.

    difficulty: dual_variant_calc/standard_vs_expedited_decision_deadline
    """
    _, provider, _, draft_std, draft_exp = (
        setup_two_drafts_for_dual_deadline()
    )
    submit_authorization(provider=provider, authorization=draft_std)
    submit_authorization(provider=provider, authorization=draft_exp)
    auth_std = re_get_authorization(draft_std["id"])
    auth_exp = re_get_authorization(draft_exp["id"])
    submitted_std = parse_iso(auth_std["submitted_at"])
    submitted_exp = parse_iso(auth_exp["submitted_at"])
    dl_std = parse_iso(auth_std["decision_deadline_at"])
    dl_exp = parse_iso(auth_exp["decision_deadline_at"])
    # Standard: submitted + 336 hours.
    assert (dl_std - submitted_std).total_seconds() / 3600 == (
        DEFAULT_STANDARD_SLA_HOURS
    )
    # Expedited: submitted + 72 hours.
    assert (dl_exp - submitted_exp).total_seconds() / 3600 == (
        DEFAULT_EXPEDITED_SLA_HOURS
    )


def test_appeal_overturn_uses_pinned_validity_not_current(api):
    """PRD §3.10: "For an authorization that flips from DENIED to
    APPROVED through an overturned appeal, expires_at is recomputed at
    that moment using the same version-pinned approval_validity_days —
    the appeal does not re-pin the catalog version, so the validity
    window comes from the catalog snapshot captured at the original
    submitted_at, not from the current live catalog row."

    Claim: catalog patched from 90 → 30 days AFTER submission;
    appeal-overturn at decided_at=2026-05-20 produces expires_at =
    decided_at + 90 days (pinned), NOT decided_at + 30 days (current).

    difficulty: dual_variant_calc/initial_vs_appeal_overturn_approval_expiration
    """
    _, provider, _, auth = setup_denied_then_overturn_with_patched_catalog()
    # File tier-1 appeal and overturn it.
    appeal = file_appeal(provider=provider, authorization=auth)
    decide_appeal(
        appeal=appeal, outcome="OVERTURNED", approved_units=1,
        headers=TEST_USERS["initial_reviewer_headers"],
    )
    auth_after = re_get_authorization(auth["id"])
    assert auth_after["status"] == "APPROVED"
    decided_at = parse_iso(auth_after["decided_at"])
    expires_at = parse_iso(auth_after["expires_at"])
    # PRD §3.10: validity comes from PINNED 90-day value, not the
    # PATCHed 30-day current value.
    delta_h = (expires_at - decided_at).total_seconds() / 3600
    assert delta_h == 90 * HOURS_PER_DAY


# ===========================================================================
# Rule 2: combinatorial_formula
# ===========================================================================
def test_two_pending_info_cycles_extend_deadline_by_336_hours(api):
    """PRD §3.6: "A request that has experienced two such
    pending-information cycles thus has its deadline pushed out by 336
    hours (two weeks) for a STANDARD request or 48 hours for an
    EXPEDITED request."

    Claim: a STANDARD authorization that completes two PENDING_INFO
    cycles has decision_deadline_at == submitted_at + base + 2*168
    hours.

    difficulty: combinatorial_formula/decision_deadline_circular_extension_evaluation_order
    """
    provider, _, auth = (
        setup_authorization_for_two_pending_info_cycles()
    )
    # Two complete cycles. Evidence is already at 1.00 from the
    # fixture, so resume passes the 0.75 gate each time.
    auth = cycle_pending_info(provider=provider, authorization=auth)
    auth = cycle_pending_info(provider=provider, authorization=auth)
    submitted_at = parse_iso(auth["submitted_at"])
    deadline = parse_iso(auth["decision_deadline_at"])
    delta_h = (deadline - submitted_at).total_seconds() / 3600
    assert delta_h == (
        DEFAULT_STANDARD_SLA_HOURS
        + 2 * STANDARD_PENDING_INFO_EXTENSION_HOURS
    )


def test_expedited_pending_info_extension_is_24_hours(api):
    """PRD §3.6: "The extension per cycle is 168 hours (one week) for a
    STANDARD request and 24 hours (one day) for an EXPEDITED request."

    Claim: one PENDING_INFO cycle on an EXPEDITED authorization
    extends the deadline by exactly 24 hours.

    difficulty: combinatorial_formula/decision_deadline_circular_extension_evaluation_order
    """
    _, provider, _, auth, _ = setup_under_review_authorization(
        urgency="EXPEDITED",
    )
    auth = cycle_pending_info(provider=provider, authorization=auth)
    submitted_at = parse_iso(auth["submitted_at"])
    deadline = parse_iso(auth["decision_deadline_at"])
    delta_h = (deadline - submitted_at).total_seconds() / 3600
    assert delta_h == (
        DEFAULT_EXPEDITED_SLA_HOURS
        + EXPEDITED_PENDING_INFO_EXTENSION_HOURS
    )


def test_reuse_discount_with_two_reused_yields_010(api):
    """PRD §3.7: "computes the discount as 0.05 multiplied by the count
    of reused documents".

    Claim: 2 reused documents yields a discount of exactly 0.10.

    difficulty: combinatorial_formula/evidence_completeness_three_inputs_with_conditional
    """
    cats = list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"])
    _, provider, _, _, resub, _ = (
        setup_resubmission_with_n_reused_evidence(
            num_reused=2, required_categories=cats,
        )
    )
    submit_authorization(provider=provider, authorization=resub)
    resub = re_get_authorization(resub["id"])
    assert resub["evidence_reuse_discount"] == 0.10
    # Score: base 1.00 - 0.10 = 0.90 (no p2p bonus, no clamp).
    assert resub["evidence_completeness_score"] == 0.90


def test_reuse_discount_with_four_reused_yields_020(api):
    """PRD §3.7: "the discount is the smaller of 0.05 times the reused
    count and 0.20."

    Claim: 4 reused documents → discount = 0.05 * 4 = 0.20 (right at
    the cap).

    difficulty: combinatorial_formula/evidence_reuse_discount_cap_then_completeness_clamp_order
    """
    cats = list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"])
    _, provider, _, _, resub, _ = (
        setup_resubmission_with_n_reused_evidence(
            num_reused=4, required_categories=cats,
        )
    )
    submit_authorization(provider=provider, authorization=resub)
    resub = re_get_authorization(resub["id"])
    # 4 * 0.05 = 0.20, equal to cap.
    assert resub["evidence_reuse_discount"] == 0.20


# ===========================================================================
# Rule 3: non_linear_state_machine
# ===========================================================================
def test_authorization_request_cyclic_review_loop(api):
    """PRD §3.4: "The two cycles — SUBMITTED → UNDER_REVIEW,
    UNDER_REVIEW → PENDING_INFO → UNDER_REVIEW — can repeat any number
    of times for the same authorization."
    PRD §3.5: "Completing the review cascades back to the parent
    authorization, returning it from PEER_REVIEW to UNDER_REVIEW."
    PRD §3.11: "An overturned appeal records decided_at on the appeal,
    then cascades to the parent: the authorization transitions from
    DENIED to APPROVED".

    Claim: a single authorization can traverse UNDER_REVIEW ↔
    PENDING_INFO, UNDER_REVIEW ↔ PEER_REVIEW, and DENIED → APPROVED
    (via overturned appeal) in sequence.

    difficulty: non_linear_state_machine/authorization_request_cyclic_review_loop
    """
    _, provider, _, auth, _ = setup_under_review_authorization()
    # Cycle 1: UNDER_REVIEW → PENDING_INFO → UNDER_REVIEW.
    auth = cycle_pending_info(provider=provider, authorization=auth)
    assert auth["status"] == "UNDER_REVIEW"
    # Cycle 2: UNDER_REVIEW → PEER_REVIEW → UNDER_REVIEW (via complete
    # with outcome UPHELD).
    p2p = schedule_peer_to_peer(provider=provider, authorization=auth)
    auth = re_get_authorization(auth["id"])
    assert auth["status"] == "PEER_REVIEW"
    complete_peer_to_peer(p2p=p2p, outcome="UPHELD")
    auth = re_get_authorization(auth["id"])
    assert auth["status"] == "UNDER_REVIEW"
    # DENY -> file appeal -> overturn cascades back to APPROVED.
    decide_authorization(
        authorization=auth, outcome="DENIED",
        denial_reason_code="NOT_MEDICALLY_NECESSARY",
    )
    auth = re_get_authorization(auth["id"])
    assert auth["status"] == "DENIED"
    appeal = file_appeal(provider=provider, authorization=auth)
    decide_appeal(
        appeal=appeal, outcome="OVERTURNED", approved_units=1,
    )
    auth = re_get_authorization(auth["id"])
    assert auth["status"] == "APPROVED"


def test_appeal_branching_to_upheld_keeps_parent_denied(api):
    """PRD §3.11: "An upheld appeal records decided_at on the appeal
    but does not change the parent authorization's status — the
    authorization remains DENIED."

    Claim: tier-1 UPHELD branch leaves parent in DENIED.

    difficulty: non_linear_state_machine/appeal_branching_per_tier_with_role_branch
    """
    _, _, _, auth, appeal = setup_denied_with_pending_tier1_appeal()
    decide_appeal(appeal=appeal, outcome="UPHELD")
    appeal_after = re_get_appeal(appeal["id"])
    auth_after = re_get_authorization(auth["id"])
    assert appeal_after["outcome"] == "UPHELD"
    assert auth_after["status"] == "DENIED"


# ===========================================================================
# Rule 4: transitive_cascade
# ===========================================================================
def test_appeal_overturn_cascade_writes_expires_at(api):
    """PRD §3.11: "An overturned appeal records decided_at on the
    appeal, then cascades to the parent: the authorization transitions
    from DENIED to APPROVED, a new Decision is created with outcome
    APPROVED … The parent authorization's own decided_at is refreshed
    to the current server time, and its expires_at is recomputed per
    the rule in §3.10."

    Claim: after a tier-1 OVERTURNED appeal, the parent authorization
    has both decided_at and expires_at populated.

    difficulty: transitive_cascade/appeal_overturn_cascade_depth_three
    """
    _, _, _, auth, appeal = setup_denied_with_pending_tier1_appeal()
    decide_appeal(
        appeal=appeal, outcome="OVERTURNED", approved_units=1,
    )
    auth_after = re_get_authorization(auth["id"])
    assert auth_after["status"] == "APPROVED"
    assert auth_after.get("decided_at") is not None
    assert auth_after.get("expires_at") is not None


def test_p2p_overturn_recompute_unlocks_score(api):
    """PRD §3.5: "If the outcome is OVERTURNED, the parent
    authorization's evidence_completeness_score is recomputed using the
    post-peer-to-peer variant, which adds a bonus of 0.10 to the base
    score before clamping".

    Claim: starting from 0.75 base coverage and a completed OVERTURNED
    P2P, the parent's score becomes 0.85; the parent is back in
    UNDER_REVIEW.

    difficulty: transitive_cascade/p2p_overturn_recompute_unlocks_decision_chain_depth_two
    """
    _, _, _, auth, p2p = (
        setup_authorization_in_peer_review_with_partial_evidence()
    )
    assert auth["status"] == "PEER_REVIEW"
    complete_peer_to_peer(p2p=p2p, outcome="OVERTURNED")
    auth_after = re_get_authorization(auth["id"])
    assert auth_after["status"] == "UNDER_REVIEW"
    assert auth_after["evidence_completeness_score"] == 0.85


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
def test_state_wins_over_evidence_insufficient_on_draft(api):
    """PRD §2.8: "When two validations would both fail, the one with
    the lower number prevails."

    Claim: start-review on a DRAFT (state=DRAFT, evidence_score=0) ->
    ERR_INVALID_STATE wins over ERR_EVIDENCE_INSUFFICIENT because state
    is priority 5 and evidence is priority 10.

    difficulty: priority_pair_validation_conflict/state_vs_business_constraint_evidence_on_submitted
    """
    patient, provider, catalog_item = setup_reference_data()
    auth = create_authorization_request(
        patient=patient, provider=provider, catalog_item=catalog_item,
    )  # DRAFT, no evidence.
    res = api.start_review(
        auth["id"], occ_payload(version=auth["version"]),
        TEST_USERS["initial_reviewer_headers"],
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_catalog_retired_wins_over_expedited_justification(api):
    """PRD §2.8: "When two validations would both fail, the one with
    the lower number prevails. This is what guarantees, for example,
    that a caller whose version is stale on a DRAFT request that is
    not theirs sees the role-mismatch error first (priority 2) rather
    than the OCC error (priority 24)."

    Claim: a submit on a RETIRED catalog item with an EXPEDITED
    urgency and a 10-char justification returns ERR_CATALOG_RETIRED
    (priority 6) rather than ERR_EXPEDITED_JUSTIFICATION_REQUIRED
    (priority 9).

    difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_retired_catalog_on_expedited_submit
    """
    from test_helpers import (
        attach_categories, retire_service_catalog_item,
    )
    patient, provider, catalog_item = setup_reference_data()
    auth = create_authorization_request(
        patient=patient, provider=provider, catalog_item=catalog_item,
        urgency="EXPEDITED", clinical_justification="too short",
    )
    attach_categories(
        provider=provider, authorization=auth,
        categories=list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"]),
    )
    # Retire catalog AFTER attach (PATCH bumps catalog version but the
    # auth still points at the same catalog id).
    retire_service_catalog_item(catalog_item)
    res = api.submit_authorization_request(
        auth["id"], occ_payload(version=auth["version"]),
        make_provider_headers(provider["id"]),
    )
    validate_error(res, "ERR_CATALOG_RETIRED")


def test_active_catalog_with_short_expedited_justification_fails_with_justification_error(
    api,
):
    """PRD §2.8: "When two validations would both fail, the one with
    the lower number prevails."
    PRD §3.2: "if urgency is EXPEDITED — the clinical_justification
    must contain at least 50 non-whitespace characters (else
    ERR_EXPEDITED_JUSTIFICATION_REQUIRED)."

    Claim (negative-control for the priority pair): when the catalog
    is ACTIVE so ERR_CATALOG_RETIRED (priority 6) does NOT fire, the
    same short-justification submit returns
    ERR_EXPEDITED_JUSTIFICATION_REQUIRED (priority 9). This pins that
    the previous test's ERR_CATALOG_RETIRED outcome was caused by the
    priority-6 check pre-empting priority-9, not by a different
    behavior.

    difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_retired_catalog_on_expedited_submit
    """
    from test_helpers import attach_categories
    patient, provider, catalog_item = setup_reference_data()
    auth = create_authorization_request(
        patient=patient, provider=provider, catalog_item=catalog_item,
        urgency="EXPEDITED", clinical_justification="too short",
    )
    attach_categories(
        provider=provider, authorization=auth,
        categories=list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"]),
    )
    # Catalog remains ACTIVE.
    res = api.submit_authorization_request(
        auth["id"], occ_payload(version=auth["version"]),
        make_provider_headers(provider["id"]),
    )
    validate_error(res, "ERR_EXPEDITED_JUSTIFICATION_REQUIRED")


# ===========================================================================
# Rule 6: boundary_precision_check
# ===========================================================================
def test_score_at_exact_050_passes_start_review_gate(api):
    """PRD §3.4: "the request's evidence_completeness_score must be at
    least 0.50."

    Claim: a submitted authorization with score exactly 0.50 satisfies
    the >= 0.50 gate and start-review returns 200.

    difficulty: boundary_precision_check/evidence_completeness_at_exact_0_50_threshold
    """
    _, _, _, auth = setup_under_review_with_partial_score_05()
    # auth's status is SUBMITTED with score 0.50.
    assert auth["evidence_completeness_score"] == 0.50
    res = api.start_review(
        auth["id"], occ_payload(version=auth["version"]),
        TEST_USERS["initial_reviewer_headers"],
    )
    updated = validate_success(res, 200)
    assert updated["status"] == "UNDER_REVIEW"


def test_empty_required_categories_decide_succeeds_without_evidence(
    api,
):
    """PRD §3.7: "if the catalog item requires no categories, the base
    coverage is 1.00".
    PRD §3.4: "the request's evidence_completeness_score must be at
    least 0.50."

    Claim: with required_evidence_categories=[] and zero attached
    evidence, score=1.0; start-review and decide both succeed and the
    resulting authorization is APPROVED.

    difficulty: boundary_precision_check/empty_required_evidence_categories_yields_score_one
    """
    _, _, _, auth = setup_submitted_with_empty_required_categories()
    assert auth["evidence_completeness_score"] == 1.0
    sr = api.start_review(
        auth["id"], occ_payload(version=auth["version"]),
        TEST_USERS["initial_reviewer_headers"],
    )
    auth = validate_success(sr, 200)
    dr = api.decide_authorization_request(
        auth["id"],
        decide_authorization_payload(
            outcome="APPROVED", approved_units=1,
            version=auth["version"],
        ),
        TEST_USERS["initial_reviewer_headers"],
    )
    validate_success(dr, 201)
    auth = re_get_authorization(auth["id"])
    assert auth["status"] == "APPROVED"


# ===========================================================================
# Rule 7: cross_entity_state_dependency
# ===========================================================================
def test_appeal_filing_blocked_when_parent_expired(api):
    """PRD §3.10: "Once an authorization is EXPIRED, no new Appeal may
    be filed on it".
    PRD §2.8: "The target resource is in a state from which the
    requested transition is legal — failure yields ERR_INVALID_STATE."

    Claim: filing an appeal on an EXPIRED authorization returns
    ERR_INVALID_STATE.

    difficulty: cross_entity_state_dependency/appeal_filing_depends_on_authorization_request_state
    """
    from test_helpers import (
        expire_authorization_via_sweep,
        setup_approved_authorization,
    )
    _, provider, _, auth = setup_approved_authorization(
        approval_validity_days=1,
    )
    auth = expire_authorization_via_sweep(authorization=auth)
    assert auth["status"] == "EXPIRED"
    res = api.file_appeal(
        auth["id"], file_appeal_payload(),
        make_provider_headers(provider["id"]),
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_submit_blocked_when_catalog_retired(api):
    """PRD §3.2: "the catalog item must be ACTIVE (else
    ERR_CATALOG_RETIRED)".

    Claim: submitting against a RETIRED catalog item returns
    ERR_CATALOG_RETIRED.

    difficulty: cross_entity_state_dependency/authorization_request_submit_depends_on_service_catalog_item_status
    """
    from test_helpers import (
        retire_service_catalog_item, attach_categories,
    )
    patient, provider, catalog_item = setup_reference_data()
    auth = create_authorization_request(
        patient=patient, provider=provider, catalog_item=catalog_item,
    )
    attach_categories(
        provider=provider, authorization=auth,
        categories=list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"]),
    )
    retire_service_catalog_item(catalog_item)
    res = api.submit_authorization_request(
        auth["id"], occ_payload(version=auth["version"]),
        make_provider_headers(provider["id"]),
    )
    validate_error(res, "ERR_CATALOG_RETIRED")


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
def test_two_p2p_calls_for_different_reviewers_do_not_conflict(api):
    """PRD §3.5: "with any other SCHEDULED review whose
    payer_reviewer_id is the same; a conflict is rejected with
    ERR_PEER_REVIEW_TIME_CONFLICT."

    Claim: two overlapping P2P slots whose payer_reviewer_ids differ
    do NOT conflict (the rule is scoped to the same reviewer).

    difficulty: resource_temporal_overlap/peer_to_peer_half_open_interval_overlap
    """
    payer_a = "payer-A"
    payer_b = "payer-B"
    first_slot = "2026-05-21T10:00:00.000Z"
    (_, (_, prov2, _, auth2)) = (
        setup_authorization_with_two_p2p_calls_for_same_payer_reviewer(
            payer_reviewer_id=payer_a,
            first_slot_iso=first_slot,
            first_duration_minutes=30,
        )
    )
    # Same start as first slot, but payer B (different reviewer) →
    # should succeed.
    res = api.schedule_peer_to_peer(
        auth2["id"],
        schedule_peer_to_peer_payload(
            scheduled_at=first_slot,
            duration_minutes=30,
            payer_reviewer_id=payer_b,
            version=auth2["version"],
        ),
        make_provider_headers(prov2["id"]),
    )
    p2p_b = validate_success(res, 201)
    assert p2p_b["status"] == "SCHEDULED"


def test_per_authorization_capacity_one_via_completed_p2p(api):
    """PRD §3.5: "At most one peer-to-peer review per authorization may
    exist in SCHEDULED or COMPLETED status; an attempt to schedule a
    second is rejected with ERR_PEER_REVIEW_ALREADY_SCHEDULED."

    Claim: after the first P2P reaches COMPLETED and the parent has
    returned to UNDER_REVIEW, a second /peer-to-peer call is rejected.

    difficulty: resource_temporal_overlap/peer_to_peer_per_authorization_aggregate_capacity_one
    """
    _, provider, _, auth, _ = setup_completed_p2p_on_authorization()
    res = api.schedule_peer_to_peer(
        auth["id"],
        schedule_peer_to_peer_payload(
            scheduled_at=iso_offset(hours=72),
            duration_minutes=30,
            payer_reviewer_id="payer-Z",
            version=auth["version"],
        ),
        make_provider_headers(provider["id"]),
    )
    validate_error(res, "ERR_PEER_REVIEW_ALREADY_SCHEDULED")


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
def test_cancelled_p2p_does_not_consume_capacity(api):
    """PRD §3.5: "At most one peer-to-peer review per authorization may
    exist in SCHEDULED or COMPLETED status".

    Claim: a CANCELLED P2P is excluded from the capacity-1 set, so a
    second /peer-to-peer succeeds. (Conservation pair: status before
    forward action equals status after forward+compensate.)

    difficulty: compensating_invariant/peer_to_peer_cancel_preserves_under_review_state_and_evidence_score
    """
    _, provider, _, auth, p2p = setup_authorization_in_peer_review()
    cancel_peer_to_peer(p2p=p2p, actor_provider=provider)
    auth = re_get_authorization(auth["id"])
    assert auth["status"] == "UNDER_REVIEW"
    # A second P2P is now allowed because the prior one is CANCELLED,
    # not SCHEDULED/COMPLETED.
    res = api.schedule_peer_to_peer(
        auth["id"],
        schedule_peer_to_peer_payload(
            scheduled_at=iso_offset(hours=48),
            duration_minutes=30,
            payer_reviewer_id="payer-new",
            version=auth["version"],
        ),
        make_provider_headers(provider["id"]),
    )
    new_p2p = validate_success(res, 201)
    assert new_p2p["status"] == "SCHEDULED"


def test_two_withdrawn_appeals_leave_next_tier_at_one(api):
    """PRD §3.11: "A withdrawn appeal does not count as UPHELD for the
    purposes of computing the next tier".

    Claim: file tier-1, withdraw, file again, withdraw — the third
    file produces tier=1, demonstrating that the tier counter is
    governed purely by UPHELD appeals (zero here).

    difficulty: compensating_invariant/appeal_withdraw_preserves_tier_counter_invariant
    """
    _, provider, _, auth, appeal1 = (
        setup_denied_with_pending_tier1_appeal()
    )
    withdraw_appeal(provider=provider, appeal=appeal1)
    appeal2 = file_appeal(provider=provider, authorization=auth)
    assert appeal2["tier"] == 1
    withdraw_appeal(provider=provider, appeal=appeal2)
    res = api.file_appeal(
        auth["id"], file_appeal_payload(),
        make_provider_headers(provider["id"]),
    )
    appeal3 = validate_success(res, 201)
    assert appeal3["tier"] == 1
