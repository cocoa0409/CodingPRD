"""Quote pricing, rate-lock lifecycle, and lock-time preconditions.

Covers the quote_fee / recipient_amount calculations, the half-open rate-lock
overlap rule, corridor-active gating, TTL auto-expiry, and payout-method support.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_quote_payload, advance_clock_payload,
    setup_corridor, setup_sender, setup_recipient, create_locked_quote,
    assert_quote, assert_quote_disclosure,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["remittance_agent_headers"]


# ─── quote_fee tiered selection (combinatorial mode a) ──────────────────────

def test_quote_fee_at_tier_threshold_selects_tier2_rate(api):
    """PRD §3.3: "if `send_principal_minor` is at or above the corridor's
    `fee_tier_threshold_minor`, the discounted `fee_pct_tier2_bps` applies;
    otherwise the standard `fee_pct_bps` applies."
    PRD §3.3: "The total `fee_minor` is the floored percentage component plus the
    flat component — each floored on its own, then added, never the sum floored."

    Design: Difficulty/combinatorial_formula/quote_fee_tiered_selection_mode_a
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    res = api.create_quote(
        create_quote_payload(corridor["id"], sender["id"],
                             send_principal_minor=100000, payout_method="BANK"), AGENT)
    quote = validate_success(res, 201)
    locked = validate_success(api.lock_quote(quote["id"], AGENT), 200)
    assert_quote_disclosure(locked)
    # P=100000 == threshold -> tier2 (70 bps): floor(100000*70/10000)=700 + flat 199 = 899.
    assert locked["fee_minor"] == 899, f"expected 899, got {locked['fee_minor']}"
    assert locked["total_pay_minor"] == 100899, locked["total_pay_minor"]
    assert locked["recipient_amount_minor"] == 5556156, locked["recipient_amount_minor"]


def test_quote_fee_below_tier_threshold_uses_standard_rate(api):
    """PRD §3.3: "if `send_principal_minor` is at or above the corridor's
    `fee_tier_threshold_minor`, the discounted `fee_pct_tier2_bps` applies;
    otherwise the standard `fee_pct_bps` applies."
    PRD §3.3: "The percentage component is `send_principal_minor` multiplied by the
    chosen basis-point rate, divided by ten thousand, floored to a whole minor unit."

    Design: Difficulty/combinatorial_formula/quote_fee_tiered_selection_mode_a
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    # P=99999 < threshold 100000 -> standard 120 bps: floor(99999*120/10000)=1199 + 199 = 1398.
    locked = create_locked_quote(corridor["id"], sender["id"], send_principal_minor=99999)
    assert locked["fee_minor"] == 1398, f"expected 1398, got {locked['fee_minor']}"


# ─── recipient_amount margin-first rounding (combinatorial mode b) ──────────

def test_locked_rate_applies_margin_first_then_floors(api):
    """PRD §3.3: "`locked_rate_micro` is the snapshotted `mid_rate_micro` multiplied
    by the quantity ten-thousand-minus-`fx_margin_bps`, divided by ten thousand, with
    any fractional micro-unit floored away."

    Design: Difficulty/combinatorial_formula/recipient_amount_rounding_order_mode_b
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    locked = create_locked_quote(corridor["id"], sender["id"], send_principal_minor=50000)
    # mid=56333333, margin=137bps: floor(56333333*(10000-137)/10000) = 55561566.
    assert locked["locked_rate_micro"] == 55561566, locked["locked_rate_micro"]


def test_recipient_amount_converts_principal_after_margin(api):
    """PRD §3.3: "`recipient_amount_minor` is `send_principal_minor` multiplied by
    `locked_rate_micro`, divided by one million, floored to a whole receive-currency
    minor unit — the margin is applied to the rate first and only then is the
    principal converted, never the reverse."

    Design: Difficulty/combinatorial_formula/recipient_amount_rounding_order_mode_b
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    locked = create_locked_quote(corridor["id"], sender["id"], send_principal_minor=50000)
    # floor(50000*55561566/1000000) = 2778078 (margin-first; convert-then-margin would give 2778077).
    assert locked["recipient_amount_minor"] == 2778078, locked["recipient_amount_minor"]
    assert locked["fee_minor"] == 799, locked["fee_minor"]


# ─── rate-lock half-open overlap (resource temporal overlap) ────────────────

def test_overlapping_rate_lock_same_sender_corridor_rejected(api):
    """PRD §3.3: "only when no other quote for the same sender-and-corridor pair is
    currently `LOCKED` with an expiry still in the future; an overlapping live lock is
    rejected with `ERR_RATE_LOCK_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rate_lock_overlap_same_sender_corridor_half_open
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    create_locked_quote(corridor["id"], sender["id"], send_principal_minor=50000)
    second = validate_success(api.create_quote(
        create_quote_payload(corridor["id"], sender["id"],
                             send_principal_minor=60000, payout_method="BANK"), AGENT), 201)
    res = api.lock_quote(second["id"], AGENT)
    validate_error(res, "ERR_RATE_LOCK_OVERLAP")
    after = validate_success(api.get_quote(second["id"], AGENT), 200)
    assert after["status"] == "DRAFT", after["status"]


def test_second_lock_distinct_sender_not_overlapping(api):
    """PRD §3.3: "only when no other quote for the same sender-and-corridor pair is
    currently `LOCKED` with an expiry still in the future; an overlapping live lock is
    rejected with `ERR_RATE_LOCK_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rate_lock_overlap_same_sender_corridor_half_open
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender_a = setup_sender(full_name="Sender Alpha")
    sender_b = setup_sender(full_name="Sender Beta")
    create_locked_quote(corridor["id"], sender_a["id"], send_principal_minor=50000)
    # A different sender on the same corridor is not an overlap; the lock succeeds.
    locked_b = create_locked_quote(corridor["id"], sender_b["id"], send_principal_minor=50000)
    assert locked_b["status"] == "LOCKED", locked_b["status"]


# ─── corridor-active gating on lock (cross-entity state dependency) ─────────

def test_lock_on_suspended_corridor_rejected(api):
    """PRD §3.3: "An agent locks a `DRAFT` quote, which is permitted only while the
    corridor is `ACTIVE` — a suspended corridor yields `ERR_CORRIDOR_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/quote_lock_requires_corridor_active
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    quote = validate_success(api.create_quote(
        create_quote_payload(corridor["id"], sender["id"],
                             send_principal_minor=50000, payout_method="BANK"), AGENT), 201)
    api.suspend_corridor(corridor["id"], ADMIN)
    res = api.lock_quote(quote["id"], AGENT)
    validate_error(res, "ERR_CORRIDOR_SUSPENDED")
    after = validate_success(api.get_quote(quote["id"], AGENT), 200)
    assert after["status"] == "DRAFT", after["status"]


def test_lock_on_active_corridor_succeeds(api):
    """PRD §3.3: "An agent locks a `DRAFT` quote, which is permitted only while the
    corridor is `ACTIVE`."
    PRD §3.3: "The lock advances the quote from `DRAFT` to `LOCKED` and increments
    its `version`."

    Design: Difficulty/cross_entity_state_dependency/quote_lock_requires_corridor_active
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    quote = validate_success(api.create_quote(
        create_quote_payload(corridor["id"], sender["id"],
                             send_principal_minor=50000, payout_method="BANK"), AGENT), 201)
    assert corridor["status"] == "ACTIVE"
    locked = validate_success(api.lock_quote(quote["id"], AGENT), 200)
    assert locked["status"] == "LOCKED", locked["status"]
    assert locked["version"] == quote["version"] + 1, locked["version"]


# ─── payout-method support (corner: validations) ────────────────────────────

def test_quote_payout_method_not_in_corridor_rejected(api):
    """PRD §3.3: "the `payout_method` to be used — which must be one of the
    corridor's `enabled_payout_methods`, or the request is rejected with
    `ERR_PAYOUT_METHOD_NOT_SUPPORTED`."

    Design: Corner/validations/payout_method_not_in_corridor_returns_unsupported
    """
    corridor = setup_corridor(enabled_payout_methods=["BANK"], with_fx=False,
                              rolling_window_cap_minor=4000000)
    sender = setup_sender()
    res = api.create_quote(
        create_quote_payload(corridor["id"], sender["id"],
                             send_principal_minor=50000, payout_method="WALLET"), AGENT)
    validate_error(res, "ERR_PAYOUT_METHOD_NOT_SUPPORTED")


# ─── locking an already-LOCKED quote (corner: state_machines) ───────────────

def test_lock_already_locked_quote_rejected(api):
    """PRD §3.9: "then that the target resource is in a state from which the
    requested transition is allowed (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/lock_already_locked_quote_returns_invalid_state
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    locked = create_locked_quote(corridor["id"], sender["id"], send_principal_minor=50000)
    assert locked["status"] == "LOCKED"
    res = api.lock_quote(locked["id"], AGENT)
    validate_error(res, "ERR_INVALID_STATE")


# ─── quote auto-expiry blocks consume (corner: state_machines) ──────────────

def test_quote_auto_expires_after_ttl_blocks_transfer_create(api):
    """PRD §3.3: "The system auto-expires a `LOCKED` quote the moment the clock
    reaches or passes its `expires_at`: when the clock is advanced or set, any locked
    quote at or past expiry transitions to `EXPIRED` before any later read observes it."
    PRD §3.4: "Consuming a quote requires that its `expires_at` is strictly after the
    current clock; a quote whose window has elapsed is rejected with `ERR_QUOTE_EXPIRED`."

    Design: Corner/state_machines/quote_auto_expires_after_ttl_blocks_consume
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    recipient = setup_recipient(sender["id"], full_name="Exp Recipient")
    locked = create_locked_quote(corridor["id"], sender["id"], send_principal_minor=50000)
    # TTL is 1800s; advancing 1801s drives expires_at past, so the quote is EXPIRED.
    api.advance_clock(advance_clock_payload(seconds=1801), ADMIN)
    res = api.create_transfer({
        "quote_id": locked["id"],
        "recipient_id": recipient["id"],
        "expected_quote_version": locked["version"],
    }, AGENT)
    validate_error(res, "ERR_QUOTE_EXPIRED")
    after = validate_success(api.get_quote(locked["id"], AGENT), 200)
    assert after["status"] == "EXPIRED", after["status"]
