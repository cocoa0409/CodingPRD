"""Authentication, authorisation and ownership (PRD 2.1 and 2.11 priorities 1-3)."""

import functools

from flask import g, request

from constants import ROLES
from db import db
from errors import fail


def authenticate():
    """Priority 1: both headers present and the role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if not role or not role.strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a recognised role." % role)
    g.user_id = user_id
    g.role = role


def current_user_id():
    return getattr(g, "user_id", None)


def current_role():
    return getattr(g, "role", None)


def roles(*allowed):
    """Priority 2: the acting role must appear in the endpoint's role list."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            if current_role() not in allowed:
                fail(
                    "ERR_UNAUTHORIZED",
                    "Role '%s' may not call this endpoint." % current_role(),
                )
            return view(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------- ownership ---
#
# Priority 3.  A Subscriber caller must own the target resource.  The check runs
# on every endpoint whose role list includes Subscriber and on no other endpoint.
# When the target cannot be resolved the check is skipped so the 404 at priority
# 5 (or the body-reference 404 at priority 6) reports the missing record.

def _acting_subscriber():
    return current_role() == "Subscriber"


def _deny():
    fail("ERR_NOT_RESOURCE_OWNER", "The acting subscriber does not own this resource.")


def own_subscriber(subscriber_id):
    if not _acting_subscriber() or subscriber_id is None:
        return
    if subscriber_id != current_user_id():
        _deny()


def own_subscriber_record(subscriber_id):
    """Ownership of a Subscriber account read: the account's own id."""
    if not _acting_subscriber():
        return
    if subscriber_id in db.subscribers and subscriber_id != current_user_id():
        _deny()


def own_order(order_id):
    if not _acting_subscriber():
        return
    order = db.orders.get(order_id)
    if order is not None:
        own_subscriber(order["subscriber_id"])


def own_terminal(terminal_id):
    if not _acting_subscriber():
        return
    terminal = db.terminals.get(terminal_id)
    if terminal is not None:
        own_subscriber(terminal["subscriber_id"])


def own_subscription(subscription_id):
    if not _acting_subscriber():
        return
    subscription = db.subscriptions.get(subscription_id)
    if subscription is not None:
        own_subscriber(subscription["subscriber_id"])


def own_roaming(roaming_id):
    if not _acting_subscriber():
        return
    roaming = db.roaming.get(roaming_id)
    if roaming is not None:
        own_subscription(roaming["subscription_id"])


def own_credit(credit_id):
    if not _acting_subscriber():
        return
    credit = db.outage_credits.get(credit_id)
    if credit is not None:
        own_subscription(credit["subscription_id"])
