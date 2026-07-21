"""Club subscriptions and the training-group waitlist.

Queue A (Difficulty): transitive_cascade (waitlist promotion),
cross_entity_state_dependency (booking requires active subscription).
Queue B (Corner): state_machines (full session -> waitlist, reactivate invalid).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    fixtures as fx,
)


def _two_subscribed_members():
    m1 = fx.create_member()
    m2 = fx.create_member()
    fx.create_subscription(m1["id"], "BASIC")
    fx.create_subscription(m2["id"], "BASIC")
    return m1, m2


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / booking_cancel_waitlist_promotion_cascade
# ---------------------------------------------------------------------------
def test_booking_cancel_promotes_waitlist(api, sm):
    """PRD 3.9: "When a `BOOKED` booking is cancelled a slot frees, firing the
    waitlist cascade: the session's `booked_count` is reduced by one, and the
    earliest `WAITLISTED` booking on that session — the one with the smallest
    `created_at` — is promoted from `WAITLISTED` to `BOOKED`, which raises
    `booked_count` back by one and clears that booking's `waitlist_position`."

    Design: Difficulty/transitive_cascade/booking_cancel_waitlist_promotion_cascade
    """
    m1, m2 = _two_subscribed_members()
    session = fx.create_training_session(
        "2026-08-10T13:00:00Z", "2026-08-10T14:00:00Z", capacity=1, title="Dawn 5k"
    )
    b1 = fx.book_training(session["id"], m1["id"])
    b2 = fx.book_training(session["id"], m2["id"])
    assert b2["status"] == "WAITLISTED"
    get_success_data(api.cancel_booking(b1["id"], sm))
    assert fx.get_success_data(api.get_training_booking(b1["id"], sm))["status"] == "CANCELLED"
    assert fx.get_success_data(api.get_training_booking(b2["id"], sm))["status"] == "BOOKED"


def test_booking_cancel_updates_booked_count(api, sm):
    """PRD 3.9: "the earliest `WAITLISTED` booking on that session — the one with
    the smallest `created_at` — is promoted from `WAITLISTED` to `BOOKED`, which
    raises `booked_count` back by one and clears that booking's
    `waitlist_position`."

    Design: Difficulty/transitive_cascade/booking_cancel_waitlist_promotion_cascade
    """
    m1, m2 = _two_subscribed_members()
    session = fx.create_training_session(
        "2026-08-10T13:00:00Z", "2026-08-10T14:00:00Z", capacity=1, title="Dawn 5k"
    )
    b1 = fx.book_training(session["id"], m1["id"])
    fx.book_training(session["id"], m2["id"])
    get_success_data(api.cancel_booking(b1["id"], sm))
    session_after = fx.get_success_data(api.get_training_session(session["id"], sm))
    assert session_after["booked_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / booking_requires_active_subscription
# ---------------------------------------------------------------------------
def test_booking_requires_active_subscription_none(api, sm):
    """PRD 3.9: "the member must hold an `ACTIVE` subscription, or the request
    fails with `ERR_SUBSCRIPTION_REQUIRED`"

    Design: Difficulty/cross_entity_state_dependency/booking_requires_active_subscription
    """
    member = fx.create_member()  # no subscription
    session = fx.create_training_session(
        "2026-08-11T13:00:00Z", "2026-08-11T14:00:00Z", capacity=5, title="No-sub run"
    )
    resp = api.create_training_booking(
        {"session_id": session["id"], "member_id": member["id"]}, sm
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_REQUIRED.value, 409)


def test_booking_requires_active_subscription_cancelled(api, sm):
    """PRD 3.9: "the member must hold an `ACTIVE` subscription, or the request
    fails with `ERR_SUBSCRIPTION_REQUIRED`"

    Design: Difficulty/cross_entity_state_dependency/booking_requires_active_subscription
    """
    member = fx.create_member()
    sub = fx.create_subscription(member["id"], "BASIC")
    get_success_data(api.cancel_subscription(sub["id"], sm))  # no longer ACTIVE
    session = fx.create_training_session(
        "2026-08-12T13:00:00Z", "2026-08-12T14:00:00Z", capacity=5, title="Cancelled-sub run"
    )
    resp = api.create_training_booking(
        {"session_id": session["id"], "member_id": member["id"]}, sm
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_REQUIRED.value, 409)


# ---------------------------------------------------------------------------
# Corner: state_machines
# ---------------------------------------------------------------------------
def test_booking_full_routes_to_waitlist(api, sm):
    """PRD 3.9: "A full session is **not** an error — when `available_slots` is
    greater than zero the booking is created `BOOKED` and the session's
    `booked_count` rises, but when the session is full the booking is instead
    created `WAITLISTED`."

    Design: Corner/state_machines/c_booking_full_routes_to_waitlist
    """
    m1, m2 = _two_subscribed_members()
    session = fx.create_training_session(
        "2026-08-21T13:00:00Z", "2026-08-21T14:00:00Z", capacity=1, title="Full 10k"
    )
    fx.book_training(session["id"], m1["id"])
    resp = api.create_training_booking(
        {"session_id": session["id"], "member_id": m2["id"]}, sm
    )
    data = validate_success(resp, 201)
    assert data["status"] == "WAITLISTED"


def test_subscription_reactivate_from_active_invalid(api, sm):
    """PRD 3.7: "Requesting a transition from a state that does not allow it —
    reactivating an active subscription, for instance — yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/c_subscription_reactivate_invalid_from_active
    """
    member = fx.create_member()
    sub = fx.create_subscription(member["id"], "BASIC")  # ACTIVE
    resp = api.reactivate_subscription(sub["id"], sm)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
