"""Waitlist promotion, notification, conversion, requeue cycle, and expiry.

Covers Difficulty rules non_linear_state_machine (waitlist requeue cycle) and
cross_entity_state_dependency (convert blocked by no matching table), plus the
corner state-machine and calculation instances on the WaitlistEntry entity.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, make_customer_headers,
    TEST_USERS,
    setup_floor_for_waitlist, setup_notified_waitlist_entry,
    make_restaurant, make_dining_area, make_table, make_customer,
    set_clock, join_waitlist, create_convert_payload,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]


# ─── non_linear_state_machine / waitlist requeue cycle NOTIFIED→WAITING ────
def test_requeue_returns_entry_to_waiting(api):
    """PRD §3.8: "requeue applies from `NOTIFIED` and increments `notify_count`
    (which penalizes the party's future ordering), clears `notify_expires_at`
    back to null, and returns the entry to `WAITING`."

    Design: Difficulty/non_linear_state_machine/waitlist_requeue_cycle_notified_back_to_waiting
    """
    ctx = setup_notified_waitlist_entry(party_size=2,
                                        table_overrides={"max_party_size": 6})
    requeued = validate_success(api.requeue_waitlist_entry(ctx["entry"]["id"], HOST), 200)
    assert requeued["status"] == "WAITING", "requeue returns NOTIFIED → WAITING"
    assert requeued["notify_expires_at"] is None, "requeue clears notify_expires_at"


def test_requeue_increments_notify_count(api):
    """PRD §3.8: "requeue applies from `NOTIFIED` and increments `notify_count`
    (which penalizes the party's future ordering), clears `notify_expires_at`
    back to null, and returns the entry to `WAITING`."

    Design: Difficulty/non_linear_state_machine/waitlist_requeue_cycle_notified_back_to_waiting
    """
    ctx = setup_notified_waitlist_entry(party_size=2,
                                        table_overrides={"max_party_size": 6})
    assert ctx["entry"]["notify_count"] == 0
    requeued = validate_success(api.requeue_waitlist_entry(ctx["entry"]["id"], HOST), 200)
    assert requeued["notify_count"] == 1, "requeue increments notify_count to 1"


# ─── cross_entity_state_dependency / convert blocked by no matching table ──
def test_convert_with_no_available_table_rejected(api):
    """PRD §3.8: "**Converting** the entry requires it to be `NOTIFIED`, the
    current time to be at or before `notify_expires_at` ... and an `AVAILABLE`
    table whose band contains the entry's `party_size` to exist (else
    `ERR_NO_MATCHING_TABLE`)."

    Design: Difficulty/cross_entity_state_dependency/convert_blocked_by_no_matching_table_status
    """
    ctx = setup_notified_waitlist_entry(party_size=2,
                                        table_overrides={"max_party_size": 4})
    # Take the only fitting table OUT_OF_SERVICE → no AVAILABLE table fits.
    get_success_data(api.table_out_of_service(ctx["table"]["id"], MANAGER))
    resp = api.convert_waitlist_entry(
        ctx["entry"]["id"], create_convert_payload(ctx["table"]["id"]), HOST)
    validate_error(resp, "ERR_NO_MATCHING_TABLE")


def test_convert_rejected_leaves_entry_notified(api):
    """PRD §3.8: "**Converting** the entry requires it to be `NOTIFIED` ... and
    an `AVAILABLE` table whose band contains the entry's `party_size` to exist
    (else `ERR_NO_MATCHING_TABLE`)."

    Design: Difficulty/cross_entity_state_dependency/convert_blocked_by_no_matching_table_status
    """
    ctx = setup_notified_waitlist_entry(party_size=2,
                                        table_overrides={"max_party_size": 4})
    get_success_data(api.table_out_of_service(ctx["table"]["id"], MANAGER))
    resp = api.convert_waitlist_entry(
        ctx["entry"]["id"], create_convert_payload(ctx["table"]["id"]), HOST)
    validate_error(resp, "ERR_NO_MATCHING_TABLE")
    after = validate_success(api.get_waitlist_entry(ctx["entry"]["id"], HOST), 200)
    assert after["status"] == "NOTIFIED", "rejected convert leaves entry NOTIFIED"


# ─── corner / convert after notify window expired ──────────────────────────
def test_convert_after_notify_window_expired_rejected(api):
    """PRD §3.8: "the current time to be at or before `notify_expires_at` (a
    conversion after the offer window is rejected with
    `ERR_NOTIFY_WINDOW_EXPIRED`)".

    Design: Corner/state_machines/notify_convert_after_window_expired
    """
    ctx = setup_notified_waitlist_entry(party_size=2,
                                        table_overrides={"max_party_size": 4})
    # Advance 11 min past notify (TTL is 10 min).
    set_clock("2026-06-15T18:11:00Z")
    resp = api.convert_waitlist_entry(
        ctx["entry"]["id"], create_convert_payload(ctx["table"]["id"]), HOST)
    validate_error(resp, "ERR_NOTIFY_WINDOW_EXPIRED")


# ─── corner / waitlist entry expires on clock advance ──────────────────────
def test_waitlist_entry_expires_after_120_minutes(api):
    """PRD §3.8: "an entry that has been `WAITING` too long expires: when the
    clock advances past the entry's `requested_start` plus 120 minutes with no
    table secured, the entry is set `EXPIRED`."

    Design: Corner/state_machines/waitlist_entry_expires_on_clock_advance
    """
    restaurant = make_restaurant()
    customer = make_customer()
    set_clock("2026-06-15T18:00:00Z")
    entry = join_waitlist(restaurant["id"], customer["id"], party_size=2,
                          requested_start="2026-06-15T18:30:00Z")
    assert entry["status"] == "WAITING"
    # requested_start 18:30 + 120 min = 20:30; advance to 21:00.
    set_clock("2026-06-15T21:00:00Z")
    after = validate_success(api.get_waitlist_entry(entry["id"], HOST), 200)
    assert after["status"] == "EXPIRED"


# ─── corner / promotion orders by notify_count then joined_at ──────────────
def test_promotion_winner_is_lowest_notify_count_then_joined_at(api):
    """PRD §3.8: "Among the candidates the winner is the one with the lowest
    `notify_count`, breaking ties by the earliest `joined_at`; the record `id`
    is never used as a tie-break."

    Design: Corner/calculations/waitlist_promotion_orders_by_notify_count_then_joined_at
    """
    restaurant = make_restaurant()
    area = make_dining_area(restaurant["id"])
    make_table(area["id"], label="T1", max_party_size=4)
    custA = make_customer()
    custB = make_customer()
    set_clock("2026-06-15T18:00:00Z")
    # A joins first, gets notified then requeued (notify_count 1).
    wlA = join_waitlist(restaurant["id"], custA["id"], party_size=2,
                        requested_start="2026-06-15T18:30:00Z")
    get_success_data(api.notify_waitlist_entry(wlA["id"], HOST))
    get_success_data(api.requeue_waitlist_entry(wlA["id"], HOST))
    # B joins later (notify_count 0).
    wlB = join_waitlist(restaurant["id"], custB["id"], party_size=2,
                        requested_start="2026-06-15T18:30:00Z")
    # Notifying the winner promotes B (notify_count 0 beats A's notify_count 1).
    notified = validate_success(api.notify_waitlist_entry(wlB["id"], HOST), 200)
    assert notified["status"] == "NOTIFIED"
    a_after = validate_success(api.get_waitlist_entry(wlA["id"], HOST), 200)
    assert a_after["status"] == "WAITING", "A (notify_count 1) loses to B (notify_count 0)"
