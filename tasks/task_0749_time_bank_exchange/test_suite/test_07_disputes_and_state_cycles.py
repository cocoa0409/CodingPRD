"""Dispute lifecycle, exchange state cycles, cross-entity state dependency."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_member_headers,
    ApiErrorId,
    setup_delivered_exchange, setup_disputed_exchange, setup_settled_exchange,
    setup_two_members_and_offer,
)


# =============================================================================
# Rule 3 — non_linear_state_machine (Exchange DELIVERED->DISPUTED->DELIVERED)
# =============================================================================

def test_exchange_cycles_delivered_disputed_delivered_via_withdraw(api):
    """PRD §3.4: "The raiser may withdraw the dispute, taking it to WITHDRAWN;
    withdrawal returns the exchange from DISPUTED back to DELIVERED so the
    requester can drive normal settlement."

    Design: Difficulty/non_linear_state_machine/exchange_delivered_disputed_delivered_cycle
    """
    ctx = setup_disputed_exchange(claimed_delta_minutes=15,
                                  reason_code="INCOMPLETE_SERVICE")
    assert ctx["exchange"]["status"] == "DISPUTED"
    withdraw = get_success_data(api.withdraw_dispute(
        ctx["dispute"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    assert withdraw["status"] == "WITHDRAWN"
    resp = api.get_exchange(
        ctx["exchange"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    final = validate_success(resp)
    assert final["status"] == "DELIVERED"
    assert final.get("settled_at_utc") is None


def test_exchange_cycles_delivered_disputed_delivered_via_rejected_resolution(api):
    """PRD §3.4: "When the outcome is REJECTED, the dispute reaches
    RESOLVED_REJECTED and the exchange returns from DISPUTED to DELIVERED,
    resuming the normal settlement path with no ledger effect; admin_notes
    may be blank in this case."

    Design: Difficulty/non_linear_state_machine/exchange_delivered_disputed_delivered_cycle
    """
    ctx = setup_disputed_exchange(claimed_delta_minutes=15)
    get_success_data(api.resolve_dispute(
        ctx["dispute"]["id"], {"outcome": "REJECTED"},
        headers=TEST_USERS["admin_headers"],
    ))
    resp = api.get_exchange(
        ctx["exchange"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    final = validate_success(resp)
    assert final["status"] == "DELIVERED"
    assert final.get("settled_at_utc") is None


# =============================================================================
# Rule 7 — cross_entity_state_dependency
# =============================================================================

def test_settle_blocked_by_open_dispute_returns_invalid_state(api):
    """PRD §3.4: "While the dispute is OPEN, the requester cannot drive
    settlement — the no-open-dispute precondition on the settle transition
    fails with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/exchange_settle_blocked_by_open_dispute
    """
    ctx = setup_disputed_exchange(claimed_delta_minutes=15)
    resp = api.settle_exchange(
        ctx["exchange"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    # Confirm the exchange stays in DISPUTED
    resp2 = api.get_exchange(
        ctx["exchange"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    exch = validate_success(resp2)
    assert exch["status"] == "DISPUTED"


def test_exchange_create_blocked_by_offer_required_trust_tier(api):
    """PRD §3.3: "the requester's trust_tier must be at least the offer's
    required_trust_tier in the ordering UNVERIFIED < BASIC < TRUSTED <
    ANCHOR, or the request is rejected with ERR_TRUST_TIER_TOO_LOW."

    Design: Difficulty/cross_entity_state_dependency/exchange_create_blocked_by_offer_required_trust_tier
    """
    ctx = setup_two_members_and_offer(
        requester_seed=240,
        offer_minutes=60,
        required_trust_tier="TRUSTED",
    )
    r = get_success_data(api.create_skill_request(
        {"member_id": ctx["requester"]["id"], "skill_code": "GARDENING",
         "needed_minutes": 60,
         "earliest_start_utc": "2026-03-05T10:00:00Z",
         "latest_start_utc": "2026-03-05T18:00:00Z"},
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    resp = api.create_exchange(
        {"offer_id": ctx["offer"]["id"], "request_id": r["id"],
         "scheduled_start_utc": "2026-03-05T10:00:00Z",
         "committed_minutes": 60},
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TRUST_TIER_TOO_LOW)
    # SkillRequest stays OPEN (no exchange created).
    r_after = get_success_data(api.get_skill_request(
        r["id"], headers=make_member_headers(ctx["requester"]["id"]),
    ))
    assert r_after["status"] == "OPEN"


# =============================================================================
# Rule 9 — compensating_invariant
# =============================================================================

def test_cancel_scheduled_exchange_conserves_ledger_sum(api):
    """PRD §2.6: "The ledger is a strict append-only log"
    PRD §3.3: "Before the scheduled start arrives, either the provider or the
    requester may cancel a SCHEDULED exchange, transitioning SCHEDULED →
    CANCELLED. The cancel is only accepted while the clock is strictly earlier
    than scheduled_start_utc; a cancel arriving on or after the start is
    rejected with ERR_INVALID_STATE."

    Design: Difficulty/compensating_invariant/exchange_cancel_conserves_ledger_sum
    """
    from test_helpers import setup_scheduled_exchange, seed_balance
    # Additionally seed the provider so both are non-zero.
    ctx = setup_scheduled_exchange(requester_seed=240)
    seed_balance(ctx["provider"]["id"], 240, memo="seed prov")
    m1_pre = get_success_data(api.get_member(
        ctx["requester"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    m2_pre = get_success_data(api.get_member(
        ctx["provider"]["id"],
        headers=make_member_headers(ctx["provider"]["id"]),
    ))
    pre_sum = m1_pre["chronological_balance_minutes"] + m2_pre["chronological_balance_minutes"]
    # Cancel
    cancel = get_success_data(api.cancel_exchange(
        ctx["exchange"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    assert cancel["status"] == "CANCELLED"
    m1_post = get_success_data(api.get_member(
        ctx["requester"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    m2_post = get_success_data(api.get_member(
        ctx["provider"]["id"],
        headers=make_member_headers(ctx["provider"]["id"]),
    ))
    post_sum = m1_post["chronological_balance_minutes"] + m2_post["chronological_balance_minutes"]
    assert pre_sum == post_sum, \
        f"Ledger sum drifted on scheduled-exchange cancel: {pre_sum} -> {post_sum}"
    # And the requester's pending debit is released
    assert m1_post["forward_looking_balance_minutes"] == m1_post["chronological_balance_minutes"]
