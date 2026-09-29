"""Subscriber account-state transitions (PRD 3.9).

`PROSPECT` on creation, `WAITLISTED` while an order waits, `ACTIVE` once a
subscription exists, `SUSPENDED` when every non-terminal subscription is
suspended, `CLOSED` when none remain non-terminal.
"""

from constants import SLOT_OCCUPYING_STATES
from db import db, touch


def subscriptions_of(subscriber_id):
    return [s for s in db.subscriptions.values() if s["subscriber_id"] == subscriber_id]


def _set_state(subscriber, state):
    if subscriber is not None and subscriber["account_state"] != state:
        subscriber["account_state"] = state
        touch(subscriber)


def mark_active(subscriber):
    _set_state(subscriber, "ACTIVE")


def settle_after_suspension(subscriber):
    """SUSPENDED once every non-terminal subscription on the account is suspended."""
    if subscriber is None:
        return
    live = [
        s
        for s in subscriptions_of(subscriber["id"])
        if s["service_state"] != "TERMINATED"
    ]
    if live and all(s["service_state"] == "SUSPENDED" for s in live):
        _set_state(subscriber, "SUSPENDED")


def settle_after_resumption(subscriber):
    if subscriber is None:
        return
    if subscriber["account_state"] == "SUSPENDED":
        _set_state(subscriber, "ACTIVE")


def settle_after_termination(subscriber):
    """CLOSED once no subscription on the account occupies a slot any more."""
    if subscriber is None:
        return
    remaining = [
        s
        for s in subscriptions_of(subscriber["id"])
        if s["service_state"] in SLOT_OCCUPYING_STATES
    ]
    if not remaining:
        _set_state(subscriber, "CLOSED")
