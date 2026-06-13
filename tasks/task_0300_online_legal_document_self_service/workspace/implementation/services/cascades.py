"""Multi-hop cascades (PRD §2.5, §3.1, §3.8).

Storage-lock cascade (origin: Subscription -> CANCELLED):
  hop B: each eligible DocumentProject -> STORAGE_LOCKED
  hop C: each STORAGE_LOCKED project cancels in-flight AttorneyReviews
         (REQUESTED/ASSIGNED/IN_REVIEW) -> CANCELLED, and cancels its
         SCHEDULED UpdateReminders -> CANCELLED
  hop D: each cancelled review refunds surcharge to the project's Order

Every hop is a real mutation: updated_at refreshed, version incremented.
"""

from common import touch
from db import store
from services.pricing import order_for_project, recompute_net

# Project statuses eligible to be storage-locked when a subscription cancels.
LOCKABLE_PROJECT_STATES = {
    "DRAFT", "IN_PROGRESS", "ASSEMBLED", "IN_REVIEW", "CHANGES_REQUESTED", "FINALIZED",
}
# Review statuses considered "in flight" and cancelled when their project locks.
IN_FLIGHT_REVIEW_STATES = {"REQUESTED", "ASSIGNED", "IN_REVIEW"}


def cancel_review_via_cascade(review):
    """Hop D: refund surcharge, recompute net, release window."""
    review["status"] = "CANCELLED"
    touch(review)
    order = order_for_project(review["document_project_id"])
    if order is not None:
        order["amount_refunded_cents"] += review["surcharge_cents"]
        recompute_net(order)
        touch(order)
    # Attorney window is "released" implicitly: CANCELLED reviews are excluded
    # from overlap checks (see attorney_reviews.window_conflicts).


def storage_lock_project(project):
    """Hop B + C: lock the project, cancel in-flight reviews and scheduled
    reminders. Assumes the project is in a lockable state."""
    project["status"] = "STORAGE_LOCKED"
    touch(project)

    # Hop C: cancel in-flight reviews for this project (deterministic order).
    reviews = [
        r for r in store.attorney_reviews.values()
        if r["document_project_id"] == project["id"]
        and r["status"] in IN_FLIGHT_REVIEW_STATES
    ]
    reviews.sort(key=lambda r: r["_seq"])
    for review in reviews:
        cancel_review_via_cascade(review)

    # Cancel SCHEDULED reminders for this project so they never fire.
    reminders = [
        rm for rm in store.update_reminders.values()
        if rm["document_project_id"] == project["id"]
        and rm["status"] == "SCHEDULED"
    ]
    reminders.sort(key=lambda rm: rm["_seq"])
    for rem in reminders:
        rem["status"] = "CANCELLED"
        touch(rem)


def cascade_subscription_cancelled(subscription):
    """Hop A origin: lock all eligible projects of this subscription."""
    projects = [
        p for p in store.document_projects.values()
        if p["subscription_id"] == subscription["id"]
        and p["status"] in LOCKABLE_PROJECT_STATES
    ]
    projects.sort(key=lambda p: p["_seq"])
    for project in projects:
        storage_lock_project(project)
