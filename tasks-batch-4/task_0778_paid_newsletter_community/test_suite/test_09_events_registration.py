"""Events, registration, seat conservation, and cascades.

Difficulty (queue A): subscription-cancel cascade with waitlist promotion;
zero-slot waitlisting; overlapping-event double-booking; registration-closed
beats event-full; register/cancel seat invariant. Corner (queue B): double
register; full event without waitlist.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    make_member_headers,
    new_publication, new_tier, new_event, new_paid_subscriber,
    setup_two_pro_members_for_event, register, find_event,
    reset_clock, set_clock,
)

CREATOR = TEST_USERS["creator_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty A7 — subscription cancel cascades seat release + waitlist promote
# ---------------------------------------------------------------------------

def _cascade_scenario(api):
    s = setup_two_pro_members_for_event(
        api, event_overrides={"capacity": 1, "allow_waitlist": True}
    )
    reg_a = register(api, s["event"]["id"], s["member_a"]["id"])       # REGISTERED
    reg_b = register(api, s["event"]["id"], s["member_b"]["id"])       # WAITLISTED
    api.cancel_subscription(s["sub_a"]["id"], {}, make_member_headers(s["member_a"]["id"]))
    return s, reg_a, reg_b


def test_subscription_cancel_promotes_waitlisted_registration(api):
    """PRD §3.5: "Cancellation carries a cascade: every one of that member's
    event registrations that is still `REGISTERED` for an event whose
    `starts_at` is in the future is moved to `CANCELED`; each such cancellation
    decrements that event's `registered_count` and increments its
    `available_slots`; and each freed seat promotes the earliest-created
    still-`WAITLISTED` registration on that same event to `REGISTERED`."

    Design: Difficulty/transitive_cascade/subscription_cancel_cascades_seat_release_and_waitlist_promote
    """
    s, reg_a, reg_b = _cascade_scenario(api)
    a_after = validate_success(api.get_registration(reg_a["id"], ADMIN), expected_status=200)
    b_after = validate_success(api.get_registration(reg_b["id"], ADMIN), expected_status=200)
    assert a_after["status"] == "CANCELED"
    assert b_after["status"] == "REGISTERED"


def test_subscription_cancel_conserves_event_seat_counters(api):
    """PRD §3.8: "for each event, the sum of `registered_count` and
    `available_slots` always equals `capacity`, `registered_count` equals the
    count of registrations in `REGISTERED`, and `waitlist_count` equals the count
    in `WAITLISTED`."

    Design: Difficulty/transitive_cascade/subscription_cancel_cascades_seat_release_and_waitlist_promote
    """
    s, _, _ = _cascade_scenario(api)
    ev = find_event(api, s["pub_id"], s["event"]["id"])
    assert ev["registered_count"] == 1
    assert ev["waitlist_count"] == 0
    assert ev["available_slots"] == 0


# ---------------------------------------------------------------------------
# Difficulty A12 — zero available slots waitlists the next registration
# ---------------------------------------------------------------------------

def _full_event_then_register_b(api):
    s = setup_two_pro_members_for_event(
        api, event_overrides={"capacity": 1, "allow_waitlist": True}
    )
    register(api, s["event"]["id"], s["member_a"]["id"])  # fills the single seat
    resp = api.create_registration(s["event"]["id"], {}, make_member_headers(s["member_b"]["id"]))
    return s, resp


def test_registration_waitlisted_when_no_slots(api):
    """PRD §3.8: "When these checks pass, the registration is created
    `REGISTERED` if a seat is available; otherwise it is created `WAITLISTED`
    when waitlisting is allowed, or rejected with `ERR_EVENT_FULL` when
    `allow_waitlist` is false."

    Design: Difficulty/boundary_precision_check/event_zero_available_slots_waitlists_next_registration
    """
    _, resp = _full_event_then_register_b(api)
    reg_b = validate_success(resp, expected_status=201)
    assert reg_b["status"] == "WAITLISTED"


def test_waitlisting_updates_event_counters(api):
    """PRD §3.8: "The event records its `publication_id` and exposes computed
    counters `registered_count`, `waitlist_count`, and `available_slots`, where
    `available_slots` is the `capacity` minus `registered_count` and never falls
    below zero."

    Design: Difficulty/boundary_precision_check/event_zero_available_slots_waitlists_next_registration
    """
    s, _ = _full_event_then_register_b(api)
    ev = find_event(api, s["pub_id"], s["event"]["id"])
    assert ev["registered_count"] == 1
    assert ev["waitlist_count"] == 1
    assert ev["available_slots"] == 0


# ---------------------------------------------------------------------------
# Difficulty A15 — overlapping events reject the second registration
# ---------------------------------------------------------------------------

def _overlap_scenario(api):
    reset_clock(api)
    pub = new_publication(api)
    pro = new_tier(api, pub["id"], tier_rank=2, monthly_price_cents=2500, name="Pro")
    ev1 = new_event(api, pub["id"], title="E1",
                    starts_at="2026-04-01T10:00:00Z", ends_at="2026-04-01T12:00:00Z",
                    capacity=5, allow_waitlist=True)
    ev2 = new_event(api, pub["id"], title="E2",
                    starts_at="2026-04-01T11:00:00Z", ends_at="2026-04-01T13:00:00Z",
                    capacity=5, allow_waitlist=True)
    mb = new_paid_subscriber(api, pub["id"], pro["id"])
    member = mb["member"]
    register(api, ev1["id"], member["id"])
    return pub, ev2, member


def test_overlapping_event_registration_rejected(api):
    """PRD §3.8: "A member already holding a `REGISTERED` spot on another event
    whose interval from `starts_at` to `ends_at` overlaps this event's interval
    is refused with `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/member_double_booking_overlapping_events_rejected
    """
    _, ev2, member = _overlap_scenario(api)
    resp = api.create_registration(ev2["id"], {}, make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value)


def test_overlapping_event_registration_creates_no_second_registration(api):
    """PRD §3.8: "A `Member` registers themselves for an event; the registration
    records the `event_id`, the acting `member_id`, a `registered_at`, and a
    `status`." — but an overlapping-event attempt is refused with
    `ERR_SCHEDULE_CONFLICT`, leaving the member with only their first registration.

    Design: Difficulty/resource_temporal_overlap/member_double_booking_overlapping_events_rejected
    """
    _, ev2, member = _overlap_scenario(api)
    api.create_registration(ev2["id"], {}, make_member_headers(member["id"]))
    regs, _meta = validate_paginated(
        api.list_registrations(ADMIN, params={"member_id": member["id"]})
    )
    assert len(regs) == 1, "the rejected registration must not be persisted"


# ---------------------------------------------------------------------------
# Difficulty A10 — registration-closed (temporal) beats event-full (capacity)
# ---------------------------------------------------------------------------

def _closed_and_full_scenario(api):
    s = setup_two_pro_members_for_event(
        api,
        event_overrides={
            "capacity": 1,
            "allow_waitlist": False,
            "registration_closes_at": "2026-03-05T00:00:00Z",
        },
    )
    register(api, s["event"]["id"], s["member_a"]["id"])  # fills capacity, window open
    set_clock(api, "2026-03-10T00:00:00Z")                # now past the close time
    return s


def test_registration_closed_beats_event_full(api):
    """PRD §3.8: "Registration ... is refused with `ERR_REGISTRATION_CLOSED` once
    the clock has passed `registration_closes_at`."

    Design: Difficulty/priority_pair_validation_conflict/registration_closed_temporal_beats_event_full_constraint
    """
    s = _closed_and_full_scenario(api)
    resp = api.create_registration(s["event"]["id"], {}, make_member_headers(s["member_b"]["id"]))
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_CLOSED.value)


def test_registration_closed_precedence_over_event_full(api):
    """PRD §2.5: "This ordering is normative because a later, more specific error
    must never mask an earlier, more fundamental one."
    PRD §2.5: "**Capacity** — a full event with waitlisting disabled rejects with
    `ERR_EVENT_FULL` (409)."

    Design: Difficulty/priority_pair_validation_conflict/registration_closed_temporal_beats_event_full_constraint
    """
    s = _closed_and_full_scenario(api)
    resp = api.create_registration(s["event"]["id"], {}, make_member_headers(s["member_b"]["id"]))
    err = validate_error(resp, ApiErrorId.ERR_REGISTRATION_CLOSED.value)
    assert err["error_id"] != ApiErrorId.ERR_EVENT_FULL.value


# ---------------------------------------------------------------------------
# Difficulty A18 — register then cancel conserves capacity (seat invariant)
# ---------------------------------------------------------------------------

def _register_then_cancel(api):
    reset_clock(api)
    pub = new_publication(api)
    pro = new_tier(api, pub["id"], tier_rank=2, monthly_price_cents=2500, name="Pro")
    ev = new_event(api, pub["id"], capacity=3, allow_waitlist=True)
    mb = new_paid_subscriber(api, pub["id"], pro["id"])
    member = mb["member"]
    reg = register(api, ev["id"], member["id"])
    api.cancel_registration(reg["id"], make_member_headers(member["id"]))
    return pub, ev, reg, member


def test_register_then_cancel_returns_to_zero_registered(api):
    """PRD §3.8: "When a `REGISTERED` registration is cancelled — by the member
    directly, or by the subscription-cancel cascade of §3.5 — the event's
    `registered_count` drops by one and `available_slots` rises by one ..."

    Design: Difficulty/compensating_invariant/seat_invariant_register_then_cancel_conserves_capacity
    """
    pub, ev, reg, _ = _register_then_cancel(api)
    reg_after = validate_success(api.get_registration(reg["id"], ADMIN), expected_status=200)
    assert reg_after["status"] == "CANCELED"
    ev_after = find_event(api, pub["id"], ev["id"])
    assert ev_after["registered_count"] == 0


def test_register_then_cancel_conserves_capacity(api):
    """PRD §3.8: "Seats are conserved on every transition: for each event, the
    sum of `registered_count` and `available_slots` always equals `capacity` ..."

    Design: Difficulty/compensating_invariant/seat_invariant_register_then_cancel_conserves_capacity
    """
    pub, ev, _, _ = _register_then_cancel(api)
    ev_after = find_event(api, pub["id"], ev["id"])
    assert ev_after["available_slots"] == 3
    assert ev_after["registered_count"] + ev_after["available_slots"] == 3


# ---------------------------------------------------------------------------
# Corner — double registration
# ---------------------------------------------------------------------------

def test_register_twice_same_event_rejected(api):
    """PRD §3.8: "A member may not double-register: an existing `REGISTERED` or
    `WAITLISTED` registration for the same event yields `ERR_ALREADY_REGISTERED`."

    Design: Corner/validations/register_twice_same_event_returns_409
    """
    s = setup_two_pro_members_for_event(
        api, event_overrides={"capacity": 5, "allow_waitlist": True}
    )
    register(api, s["event"]["id"], s["member_a"]["id"])
    resp = api.create_registration(s["event"]["id"], {}, make_member_headers(s["member_a"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ALREADY_REGISTERED.value)


# ---------------------------------------------------------------------------
# Corner — full event with waitlisting disabled
# ---------------------------------------------------------------------------

def test_register_full_no_waitlist_rejected(api):
    """PRD §3.8: "otherwise it is created `WAITLISTED` when waitlisting is
    allowed, or rejected with `ERR_EVENT_FULL` when `allow_waitlist` is false."

    Design: Corner/validations/register_full_no_waitlist_returns_409
    """
    s = setup_two_pro_members_for_event(
        api, event_overrides={"capacity": 1, "allow_waitlist": False}
    )
    register(api, s["event"]["id"], s["member_a"]["id"])  # fills the only seat
    resp = api.create_registration(s["event"]["id"], {}, make_member_headers(s["member_b"]["id"]))
    validate_error(resp, ApiErrorId.ERR_EVENT_FULL.value)
