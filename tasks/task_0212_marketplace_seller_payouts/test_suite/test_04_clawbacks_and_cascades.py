"""Transitive cascades and temporal-window boundaries.

Translates queue A (Difficulty) transitive_cascade and resource_temporal_overlap.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_fee_schedule, create_seller, create_order,
    seller_with_scheduled_payout, current_seller_version,
    create_requested_refund,
    set_clock, advance_clock, create_chargeback,
    make_seller_headers, make_finance_headers,
)
from test_helpers import api_client


# ─────────────────────────────────────────────────────────────────────────────
# transitive_cascade / payout_release_cascade_order_paid_then_ledger_then_balance
# ─────────────────────────────────────────────────────────────────────────────

def test_payout_release_cascade_order_paid_and_balance_zeroed(api, finance_headers):
    """PRD §3.9: "On a successful release, the platform ... posts a negative `PAYOUT`
    ledger entry for the disbursed amount ... flips every swept order's
    `settlement_status` from `AVAILABLE` to `PAID`, increments the seller's `version`
    by 1, reconciles the seller's balances".
    PRD §2.6: "The `available_balance_cents` is the sum of that seller's ledger-entry
    amounts whose `hold_state` is `AVAILABLE`, less the seller's current
    `reserve_held_cents`".

    Design: Difficulty/transitive_cascade/payout_release_cascade_order_paid_then_ledger_then_balance_depth3
    """
    # STANDARD seller (reserve 0), one matured order +8130 AVAILABLE, payout scheduled.
    seller, order, payout, _pm = seller_with_scheduled_payout(gross_amount_cents=10000)
    version = current_seller_version(seller["id"])
    released = validate_success(
        api.release_payout(payout["id"], {"expected_seller_version": version},
                           make_finance_headers("finance-2")),
        200,
    )
    assert released["payout_amount_cents"] == 8130
    refetched_order = validate_success(api.get_order(order["id"], finance_headers), 200)
    assert refetched_order["settlement_status"] == "PAID"
    refetched_seller = validate_success(api.get_seller(seller["id"], finance_headers), 200)
    assert refetched_seller["available_balance_cents"] == 0


def test_payout_release_increments_seller_version(api, finance_headers):
    """PRD §3.9: "increments the seller's `version` by 1".

    Design: Difficulty/transitive_cascade/payout_release_cascade_order_paid_then_ledger_then_balance_depth3
    """
    seller, order, payout, _pm = seller_with_scheduled_payout(gross_amount_cents=10000)
    version = current_seller_version(seller["id"])
    validate_success(
        api.release_payout(payout["id"], {"expected_seller_version": version},
                           make_finance_headers("finance-2")),
        200,
    )
    refetched_seller = validate_success(api.get_seller(seller["id"], finance_headers), 200)
    assert refetched_seller["version"] == version + 1


# ─────────────────────────────────────────────────────────────────────────────
# transitive_cascade / refund_apply_cascade_clawback_then_ledger_then_balance
# ─────────────────────────────────────────────────────────────────────────────

def test_refund_apply_cascade_clawback_ledger_and_pending_balance(api, finance_headers):
    """PRD §3.6: "A `REFUND_CLAWBACK` ledger entry is posted for the negative of the
    clawback amount ... The order's `clawback_status` moves from `NONE` to
    `REFUND_CLAWED` ... and the seller's balances and risk score are reconciled."
    PRD §3.6: "then the `clawback_cents` as the refund amount minus that returned
    commission."

    Design: Difficulty/transitive_cascade/refund_apply_cascade_clawback_then_ledger_then_balance_depth2
    """
    set_clock("2026-02-01T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    # Provisional proceeds 8130 in PENDING. Refund 4000 → clawback 3400.
    refund = create_requested_refund(order["id"], refund_amount_cents=4000)
    applied = validate_success(api.apply_refund(refund["id"], finance_headers), 200)
    assert applied["clawback_cents"] == 3400
    refetched_order = validate_success(api.get_order(order["id"], finance_headers), 200)
    assert refetched_order["clawback_status"] == "REFUND_CLAWED"
    refetched_seller = validate_success(api.get_seller(seller["id"], finance_headers), 200)
    # pending proceeds 8130 less the 3400 clawback debit (both PENDING) = 4730.
    assert refetched_seller["pending_balance_cents"] == 4730


def test_refund_clawback_ledger_entry_is_negative(api, finance_headers):
    """PRD §3.6: "A `REFUND_CLAWBACK` ledger entry is posted for the negative of the
    clawback amount".

    Design: Difficulty/transitive_cascade/refund_apply_cascade_clawback_then_ledger_then_balance_depth2
    """
    set_clock("2026-02-01T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    refund = create_requested_refund(order["id"], refund_amount_cents=4000)
    validate_success(api.apply_refund(refund["id"], finance_headers), 200)
    res = api.list_seller_ledger_entries(
        seller["id"], finance_headers, params={"source_type": "REFUND_CLAWBACK"}
    )
    data, _meta = validate_paginated(res)
    clawbacks = [e for e in data if e["source_type"] == "REFUND_CLAWBACK"]
    assert len(clawbacks) == 1
    assert clawbacks[0]["amount_cents"] == -3400


# ─────────────────────────────────────────────────────────────────────────────
# resource_temporal_overlap / order_maturation_window_half_open_lower_bound
# ─────────────────────────────────────────────────────────────────────────────

def test_order_matures_exactly_at_lower_bound_inclusive(api, finance_headers):
    """PRD §3.5: "An order matures — its `settlement_status` flips from `PENDING` to
    `AVAILABLE` — only when its settlement is still `PENDING`, the current UTC time
    is at or after the order's `settled_at` plus the active schedule's
    `maturation_days`".

    Design: Difficulty/resource_temporal_overlap/order_maturation_window_half_open_lower_bound_inclusive
    """
    set_clock("2026-01-01T00:00:00Z")
    create_fee_schedule()  # maturation_days 7
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    # Advance to exactly settled_at + 7 days → inclusive lower bound matures it.
    advance_clock("2026-01-08T00:00:00Z")
    matured = validate_success(api.get_order(order["id"], finance_headers), 200)
    assert matured["settlement_status"] == "AVAILABLE"
    # matured_at is stamped with the current clock time (PRD §3.5).
    assert matured["matured_at"] is not None
    assert matured["matured_at"].startswith("2026-01-08T00:00:00")


def test_order_does_not_mature_one_second_before_lower_bound(api, finance_headers):
    """PRD §3.5: "the current UTC time is at or after the order's `settled_at` plus
    the active schedule's `maturation_days`".

    Design: Difficulty/resource_temporal_overlap/order_maturation_window_half_open_lower_bound_inclusive
    """
    set_clock("2026-01-01T00:00:00Z")
    create_fee_schedule()  # maturation_days 7
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    # One second before settled_at + 7d → still PENDING.
    advance_clock("2026-01-07T23:59:59Z")
    refetched = validate_success(api.get_order(order["id"], finance_headers), 200)
    assert refetched["settlement_status"] == "PENDING"


# ─────────────────────────────────────────────────────────────────────────────
# resource_temporal_overlap / chargeback_representment_window_closed_upper_bound
# ─────────────────────────────────────────────────────────────────────────────

def test_representment_after_window_closed_rejected(api, finance_headers):
    """PRD §3.7: "The seller may contest by submitting representment evidence, which
    moves `chargeback_status` from `RECEIVED` to `REPRESENTED` — but only if the
    current time is at or before `representment_due_at`. Representment submitted
    after that deadline is rejected with `ERR_REPRESENTMENT_WINDOW_CLOSED`
    (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/chargeback_representment_window_closed_upper_bound_inclusive
    """
    set_clock("2026-02-01T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    cb = create_chargeback(order["id"])
    # Advance well past representment_due_at (receipt + 7 days).
    set_clock("2026-02-20T00:00:00Z")
    res = api.represent_chargeback(cb["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_REPRESENTMENT_WINDOW_CLOSED", expected_status=422)
    refetched = validate_success(api.get_chargeback(cb["id"], finance_headers), 200)
    assert refetched["chargeback_status"] == "RECEIVED"


def test_representment_within_window_succeeds(api, finance_headers):
    """PRD §3.7: "The seller may contest by submitting representment evidence, which
    moves `chargeback_status` from `RECEIVED` to `REPRESENTED` — but only if the
    current time is at or before `representment_due_at`."

    Design: Difficulty/resource_temporal_overlap/chargeback_representment_window_closed_upper_bound_inclusive
    """
    set_clock("2026-02-01T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    cb = create_chargeback(order["id"])
    # Still within the window (immediately after receipt).
    represented = validate_success(
        api.represent_chargeback(cb["id"], make_seller_headers(seller["id"])), 200
    )
    assert represented["chargeback_status"] == "REPRESENTED"
