"""Audit log emission and fraud-flag bookkeeping.

Pinned to PRD §2.5 (cascades, audit log), §3.8 (fraud flags / audit retrieval).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_fraud_flag_payload,
    setup_claim_under_review, setup_claim_paid, setup_claim_settled,
    add_fraud_flag, post_subrogation, list_audit_log,
    record_primary_decision, get_claim,
    bank_settle, bank_fail,
    TEST_USERS, has_audit_entry, find_audit_entry,
    assert_audit_log_entry, assert_fraud_flag,
    make_customer_headers, build_user_headers,
)


# ─── §2.5 STATUS_CHANGE recorded for every claim transition ───────
def test_status_change_audit_recorded_for_intake_to_under_investigation(api):
    """PRD §2.5: "Whenever a `Claim` changes status, the server records an
    `AuditLogEntry` whose `event_type` is `STATUS_CHANGE` and whose
    `from_state` and `to_state` capture the transition"

    Claim: opening an investigation records a STATUS_CHANGE
    INTAKE -> UNDER_INVESTIGATION.
    """
    from test_helpers import setup_basic_world, file_claim, open_investigation
    world = setup_basic_world()
    claim = file_claim(world)
    open_investigation(world, claim)
    entries, _ = list_audit_log(claim["id"])
    assert has_audit_entry(
        entries, event_type="STATUS_CHANGE",
        from_state="INTAKE", to_state="UNDER_INVESTIGATION",
    ), f"Missing STATUS_CHANGE INTAKE->UNDER_INVESTIGATION in {entries}"


def test_status_change_audit_recorded_under_review_to_approved(api):
    """PRD §2.5: "Whenever a `Claim` changes status, the server records an
    `AuditLogEntry` whose `event_type` is `STATUS_CHANGE` and whose
    `from_state` and `to_state` capture the transition"

    Claim: a manual APPROVE writes STATUS_CHANGE UNDER_REVIEW -> APPROVED.
    """
    state = setup_claim_under_review(claimed_amount_cents=5_000_000,
                                       assessed_loss_cents=5_000_000,
                                       coverage_limit_cents=100_000_000)
    state = record_primary_decision(state, outcome="APPROVE")
    entries, _ = list_audit_log(state["claim"]["id"])
    e = find_audit_entry(entries, event_type="STATUS_CHANGE",
                         from_state="UNDER_REVIEW", to_state="APPROVED")
    assert_audit_log_entry(e)


def test_review_decision_audit_event_recorded(api):
    """PRD §2.5: "Review decisions emit `event_type` `REVIEW_DECISION`"

    Claim: a primary review decision writes a REVIEW_DECISION audit entry.
    """
    state = setup_claim_under_review(claimed_amount_cents=5_000_000,
                                       assessed_loss_cents=5_000_000,
                                       coverage_limit_cents=100_000_000)
    state = record_primary_decision(state, outcome="DENY",
                                      rationale="Insufficient.")
    entries, _ = list_audit_log(state["claim"]["id"])
    assert has_audit_entry(entries, event_type="REVIEW_DECISION"), (
        f"Expected REVIEW_DECISION entry, got: "
        f"{[e.get('event_type') for e in entries]}"
    )


def test_payout_event_audit_recorded_for_payout_creation(api):
    """PRD §2.5: "payout creation, bank settlement, bank failure, and
    subrogation each emit `PAYOUT_EVENT`"

    Claim: creating a Payout records a PAYOUT_EVENT audit entry.
    """
    state = setup_claim_paid(salvage_value_cents=50_000)
    entries, _ = list_audit_log(state["claim"]["id"])
    assert has_audit_entry(entries, event_type="PAYOUT_EVENT"), (
        f"Expected PAYOUT_EVENT entry, got: "
        f"{[e.get('event_type') for e in entries]}"
    )


def test_payout_event_audit_recorded_for_subrogation(api):
    """PRD §2.5 / §3.6: "writes an audit `PAYOUT_EVENT`" for a subrogation post.

    Claim: subrogation records a PAYOUT_EVENT audit entry.
    """
    # Claim PAID (payout PENDING) — PRD §3.6 gates subrogation on Claim.status == PAID;
    # bank-settle would cascade Claim PAID -> CLOSED, blocking the subrogation.
    state = setup_claim_paid(salvage_value_cents=50_000)
    state = post_subrogation(state, amount_cents=10_000)
    entries, _ = list_audit_log(state["claim"]["id"])
    payout_events = [e for e in entries if e.get("event_type") == "PAYOUT_EVENT"]
    assert len(payout_events) >= 1, (
        f"Expected at least one PAYOUT_EVENT, got "
        f"{[e.get('event_type') for e in entries]}"
    )


def test_status_change_audit_paid_to_closed_after_settle(api):
    """PRD §2.5: "Whenever a `Claim` changes status, the server records an
    `AuditLogEntry` whose `event_type` is `STATUS_CHANGE` and whose
    `from_state` and `to_state` capture the transition"

    Claim: bank-settle writes STATUS_CHANGE PAID -> CLOSED.

    # difficulty: transitive_cascade/bank_settle_to_policy_event_sync_depth3
    """
    state = setup_claim_settled(salvage_value_cents=50_000)
    entries, _ = list_audit_log(state["claim"]["id"])
    e = find_audit_entry(entries, event_type="STATUS_CHANGE",
                         from_state="PAID", to_state="CLOSED")
    assert_audit_log_entry(e)


# ─── §2.5 system-actor for cascades ──────────────────────────────
def test_status_change_audit_actor_id_system_for_bank_settle_cascade(api):
    """PRD §2.5: "alongside `actor_id` (the `X-User-ID` of the caller, or
    the literal string `"system"` for clock-driven and event-driven
    cascades)"

    Claim: the STATUS_CHANGE PAID -> CLOSED entry (driven by the bank-settle
    cascade) carries actor_id == "system".
    """
    state = setup_claim_settled(salvage_value_cents=50_000)
    entries, _ = list_audit_log(state["claim"]["id"])
    e = find_audit_entry(entries, event_type="STATUS_CHANGE",
                         from_state="PAID", to_state="CLOSED")
    assert e["actor_id"] == "system", (
        f"Expected actor_id=='system' for cascade, got {e['actor_id']!r}"
    )


# ─── §3.8 fraud flag basics ───────────────────────────────────────
def test_fraud_flag_creation_emits_audit_event(api):
    """PRD §3.8: "Adding a flag emits an audit `FRAUD_FLAG_ADDED` event."

    Claim: POST /fraud-flags writes a FRAUD_FLAG_ADDED audit entry.
    """
    state = setup_claim_under_review(claimed_amount_cents=5_000_000,
                                       assessed_loss_cents=500_000,
                                       coverage_limit_cents=10_000_000)
    add_fraud_flag(state["claim"], signal="DUPLICATE_PATTERN", severity=0.5)
    entries, _ = list_audit_log(state["claim"]["id"])
    assert has_audit_entry(entries, event_type="FRAUD_FLAG_ADDED"), (
        f"Expected FRAUD_FLAG_ADDED entry, got "
        f"{[e.get('event_type') for e in entries]}"
    )


def test_fraud_flag_does_not_immediately_recompute_score(api):
    """PRD §3.8: "The flag itself does not immediately recompute
    `Claim.fraud_score` or decay the shop's `trust_score`; both happen at
    the next submit-for-review event for the affected claim, which is the
    point at which the canonical fraud-score and trust-decay calculations
    run."

    Claim: adding a fraud flag to a claim that is already past
    UNDER_INVESTIGATION does NOT mutate Claim.fraud_score (no new
    submit-for-review has run).
    """
    state = setup_claim_under_review(claimed_amount_cents=5_000_000,
                                       assessed_loss_cents=500_000,
                                       coverage_limit_cents=10_000_000)
    pre_score = state["claim"]["fraud_score"]
    add_fraud_flag(state["claim"], signal="DUPLICATE_PATTERN", severity=1.0)
    refreshed = get_claim(state["claim"]["id"])
    assert refreshed["fraud_score"] == pre_score, (
        f"fraud_score must not change before next submit-for-review: "
        f"pre={pre_score}, post={refreshed['fraud_score']}"
    )


def test_fraud_flag_rbac_admin_only(api, customer_headers):
    """PRD §4 endpoints table: POST /claims/{id}/fraud-flags is PlatformAdmin-only.

    Claim: Customer calling fraud-flags -> ERR_FORBIDDEN.
    """
    state = setup_claim_under_review(claimed_amount_cents=5_000_000,
                                       assessed_loss_cents=500_000,
                                       coverage_limit_cents=10_000_000)
    res = api.create_fraud_flag(
        state["claim"]["id"],
        create_fraud_flag_payload(signal="DUPLICATE_PATTERN", severity=0.5),
        customer_headers,
    )
    validate_error(res, "ERR_FORBIDDEN")


# ─── §3.8 audit retrieval ────────────────────────────────────────
def test_audit_log_ordered_by_created_at_ascending(api):
    """PRD §3.8: "The audit log for any claim is retrievable by `Reviewer`
    and `PlatformAdmin` callers and ordered by `created_at` ascending."

    Claim: GET /audit-log returns entries in non-decreasing created_at order.
    """
    state = setup_claim_paid(salvage_value_cents=50_000)
    entries, _ = list_audit_log(state["claim"]["id"])
    timestamps = [e["created_at"] for e in entries]
    assert timestamps == sorted(timestamps), (
        f"Audit log must be sorted ascending by created_at, got {timestamps}"
    )


def test_audit_log_filter_by_event_type(api):
    """PRD §3.8: "Filtering by `event_type` is supported"

    Claim: ?event_type=STATUS_CHANGE returns only STATUS_CHANGE entries.
    """
    state = setup_claim_paid(salvage_value_cents=50_000)
    entries, _ = list_audit_log(state["claim"]["id"], params={"event_type": "STATUS_CHANGE"})
    assert len(entries) > 0
    for e in entries:
        assert e["event_type"] == "STATUS_CHANGE", (
            f"Filter violated: got event_type={e['event_type']!r}"
        )


def test_audit_log_rbac_only_reviewer_or_admin(api, customer_headers):
    """PRD §4 endpoints table: GET /claims/{id}/audit-log is restricted to
    Reviewer and PlatformAdmin.

    Claim: Customer calling audit-log -> ERR_FORBIDDEN.
    """
    state = setup_claim_paid(salvage_value_cents=50_000)
    res = api.get_audit_log(state["claim"]["id"], customer_headers)
    validate_error(res, "ERR_FORBIDDEN")
