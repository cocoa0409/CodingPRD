"""
Payment-event tests (PRD §3.9 / §2.4).

Idempotency, append-only schema (no updated_at, no version), no-auth.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    assert_payment_event,
    borrow_for,
    setup_borrow_environment,
    validate_error,
    validate_success,
)


def test_first_payment_event_persisted(api):
    """PRD §3.9: "The server persists the event record on first receipt."
    """
    env = setup_borrow_environment()
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    res = api.post_payment_event(
        {
            "idempotency_key": "k-first-1",
            "event_type": "PAYMENT_CONFIRMED",
            "rental_id": rental["id"],
            "amount": 1.50,
            "occurred_at": "2026-01-01T10:00:00Z",
        }
    )
    pe = validate_success(res, 200)
    assert_payment_event(pe)


def test_duplicate_idempotency_key_rejected(api):
    """PRD §3.9: "rejects any duplicate idempotency_key with
    ERR_DUPLICATE_PAYMENT_EVENT without further side effects."
    """
    env = setup_borrow_environment()
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    payload = {
        "idempotency_key": "k-dup-1",
        "event_type": "PAYMENT_CONFIRMED",
        "rental_id": rental["id"],
        "amount": 2.00,
        "occurred_at": "2026-01-01T10:00:00Z",
    }
    api.post_payment_event(payload)
    res2 = api.post_payment_event(payload)
    validate_error(res2, "ERR_DUPLICATE_PAYMENT_EVENT")


def test_payment_event_response_omits_updated_at_and_version(api):
    """PRD §2.4: PaymentEvent is the lone entity without common fields —
    "exposes id and created_at only, and has neither updated_at nor version."
    """
    env = setup_borrow_environment()
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    res = api.post_payment_event(
        {
            "idempotency_key": "k-omit-1",
            "event_type": "PAYMENT_CONFIRMED",
            "rental_id": rental["id"],
            "amount": 1.00,
            "occurred_at": "2026-01-01T10:00:00Z",
        }
    )
    pe = validate_success(res, 200)
    assert "updated_at" not in pe, (
        "PaymentEvent must not expose updated_at (PRD §2.4)"
    )
    assert "version" not in pe, (
        "PaymentEvent must not expose version (PRD §2.4)"
    )
