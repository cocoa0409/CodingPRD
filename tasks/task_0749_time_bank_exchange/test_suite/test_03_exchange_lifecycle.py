"""Exchange lifecycle: create, mark-delivered, settle, cancel, request bubble-up."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_member_headers, TEST_USERS,
    ApiErrorId,
    setup_scheduled_exchange, setup_delivered_exchange, setup_settled_exchange,
    set_clock,
)


def test_exchange_initial_state_is_scheduled(api):
    """PRD §3.3: "When all gates pass, the exchange is inserted with status at
    SCHEDULED, the linked request transitions from OPEN to MATCHED, and the
    requester's forward_looking_balance_minutes is recomputed to reflect the
    new pending debit."

    Design: Corner/state_machines/exchange_initial_state_is_scheduled
    """
    ctx = setup_scheduled_exchange()
    assert ctx["exchange"]["status"] == "SCHEDULED"


def test_cancel_from_settled_returns_invalid_state(api):
    """PRD §3.3: "Before the scheduled start arrives, either the provider or the
    requester may cancel a SCHEDULED exchange, transitioning SCHEDULED →
    CANCELLED."
    PRD §2.11: "then whether the target resource is in a state that permits the
    operation (per §3)"

    Design: Corner/state_machines/exchange_terminal_lockdown_no_transition_from_settled
    """
    ctx = setup_settled_exchange()
    resp = api.cancel_exchange(
        ctx["exchange"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_cancel_from_delivered_returns_invalid_state(api):
    """PRD §3.3: "Before the scheduled start arrives, either the provider or the
    requester may cancel a SCHEDULED exchange, transitioning SCHEDULED →
    CANCELLED. The cancel is only accepted while the clock is strictly earlier
    than scheduled_start_utc; a cancel arriving on or after the start is
    rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/exchange_cancelled_from_delivered_returns_invalid_state
    """
    ctx = setup_delivered_exchange()
    resp = api.cancel_exchange(
        ctx["exchange"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_cancel_exchange_reopens_matched_request(api):
    """PRD §3.3: "The cancel writes the exchange to CANCELLED and rolls the
    linked request back from MATCHED to OPEN, so a fresh exchange can be
    booked against it."

    Design: Corner/state_machines/exchange_cancel_bubble_up_to_skill_request_open
    """
    ctx = setup_scheduled_exchange()
    resp = api.cancel_exchange(
        ctx["exchange"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    ex = validate_success(resp)
    assert ex["status"] == "CANCELLED"
    r_resp = api.get_skill_request(
        ctx["request"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    r = validate_success(r_resp)
    assert r["status"] == "OPEN"


def test_settle_visible_immediately_credits_provider(api):
    """PRD §3.3: "an EARNED LedgerEntry is inserted for the provider with
    delta_minutes equal to the positive of committed_minutes; both members'
    chronological_balance_minutes and forward_looking_balance_minutes are
    recomputed"

    Design: Corner/consistency_model/immediate_consistency_settle_visible_in_response
    """
    ctx = setup_settled_exchange()
    resp = api.get_member(
        ctx["provider"]["id"],
        headers=make_member_headers(ctx["provider"]["id"]),
    )
    data = validate_success(resp)
    assert data["chronological_balance_minutes"] == 60


def test_provider_completed_exchange_count_recomputed_on_settle(api):
    """PRD §3.3: "the provider's completed_exchange_count is recomputed, which in
    turn may promote their trust_tier under the pinned ladder in §2.7"

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_completed_exchange_count
    """
    ctx = setup_settled_exchange()
    resp = api.get_member(
        ctx["provider"]["id"],
        headers=make_member_headers(ctx["provider"]["id"]),
    )
    data = validate_success(resp)
    assert data["completed_exchange_count"] == 1
    assert data["chronological_balance_minutes"] == 60
