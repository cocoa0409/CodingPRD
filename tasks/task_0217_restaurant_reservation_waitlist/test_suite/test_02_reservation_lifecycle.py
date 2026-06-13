"""Reservation lifecycle: the reschedule cycle, confirm preconditions, seating,
completion, no-show grace, and the strike-block boundary.

Covers Difficulty rules non_linear_state_machine (reschedule), boundary_precision
(strike threshold), cross_entity_state_dependency (confirm blocked), plus the
corner state-machine and validation instances on the Reservation entity.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, make_customer_headers, TEST_USERS, NON_EXISTENT_UUID,
    create_reschedule_payload,
    setup_floor, setup_confirmed_reservation, setup_seated_reservation,
    book_reservation, confirm, place_hold, set_clock, current_table_version,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]


# ─── non_linear_state_machine / reservation reschedule cycle ──────────────
def test_reschedule_returns_reservation_to_requested(api):
    """PRD §3.6: "On success the system recomputes `turn_window_end` and
    `release_at` for the new start and table, returns the reservation to
    `REQUESTED`, and increments the target table's `version`."

    Design: Difficulty/non_linear_state_machine/reservation_reschedule_cycle_confirmed_back_to_requested
    """
    ctx = setup_confirmed_reservation(
        party_size=2,
        restaurant_overrides={"late_cancel_cutoff_hours": 2,
                              "default_turn_time_minutes": 90,
                              "cleanup_buffer_minutes": 15},
        table_overrides={"max_party_size": 8})
    res_id = ctx["reservation"]["id"]
    cust = ctx["customer"]["id"]
    tbl = ctx["table"]["id"]
    tv = current_table_version(tbl)
    # 12:00 is outside the late window (12:00 < 19:00 - 2h = 17:00).
    updated = validate_success(api.reschedule_reservation(
        res_id,
        create_reschedule_payload(tbl, tv, "2026-06-15T19:00:00Z"),
        make_customer_headers(cust)), 200)
    assert updated["status"] == "REQUESTED", \
        f"reschedule returns CONFIRMED → REQUESTED, got {updated['status']}"


def test_reschedule_recomputes_turn_window_for_new_start(api):
    """PRD §3.6: "On success the system recomputes `turn_window_end` and
    `release_at` for the new start and table, returns the reservation to
    `REQUESTED`, and increments the target table's `version`."

    Design: Difficulty/non_linear_state_machine/reservation_reschedule_cycle_confirmed_back_to_requested
    """
    ctx = setup_confirmed_reservation(
        party_size=2,
        restaurant_overrides={"late_cancel_cutoff_hours": 2,
                              "default_turn_time_minutes": 90,
                              "cleanup_buffer_minutes": 15},
        table_overrides={"max_party_size": 8})
    res_id = ctx["reservation"]["id"]
    cust = ctx["customer"]["id"]
    tbl = ctx["table"]["id"]
    tv = current_table_version(tbl)
    updated = validate_success(api.reschedule_reservation(
        res_id,
        create_reschedule_payload(tbl, tv, "2026-06-15T19:00:00Z"),
        make_customer_headers(cust)), 200)
    # new start 19:00 + 90 turn → turn_window_end 20:30.
    assert updated["turn_window_end"] == "2026-06-15T20:30:00.000Z", \
        f"turn_window_end recomputed for 19:00 start, got {updated['turn_window_end']}"


# ─── cross_entity_state_dependency / confirm blocked by customer status ────
def test_confirm_blocked_when_customer_blocked_after_create(api):
    """PRD §3.2: "A `BLOCKED` guest cannot create or confirm a reservation or
    join the waitlist; such attempts are rejected with `ERR_CUSTOMER_BLOCKED`."

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_customer_blocked_status
    """
    floor = setup_floor(table_overrides={"max_party_size": 8})
    res = book_reservation(floor["restaurant"]["id"], floor["customer"]["id"],
                           floor["table"]["id"], party_size=2,
                           reservation_start="2026-06-15T18:00:00Z")
    # Advance the clock to the booking's start so the block cascade (§3.2 cancels
    # only reservations "with a start in the future") leaves this REQUESTED
    # reservation intact — the confirm must then trip the blocked-customer check.
    set_clock("2026-06-15T18:00:00Z")
    # Block the customer after the reservation is created.
    get_success_data(api.block_customer(floor["customer"]["id"], MANAGER))
    resp = api.confirm_reservation(res["id"], HOST)
    validate_error(resp, "ERR_CUSTOMER_BLOCKED")
    after = validate_success(api.get_reservation(res["id"], HOST), 200)
    assert after["status"] == "REQUESTED", "blocked confirm leaves reservation REQUESTED"


def test_confirm_requires_active_customer_unchanged_on_reject(api):
    """PRD §3.4: "**Confirmation** ... requires that the reservation is
    `REQUESTED`, that the referenced customer is `ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_customer_blocked_status
    """
    floor = setup_floor(table_overrides={"max_party_size": 8})
    res = book_reservation(floor["restaurant"]["id"], floor["customer"]["id"],
                           floor["table"]["id"], party_size=2,
                           reservation_start="2026-06-15T18:00:00Z")
    # Advance the clock to the booking's start so the §3.2 block cascade (which
    # cancels only future-start reservations) leaves this one REQUESTED, so the
    # confirm reaches the customer-status precondition (referenced customer must
    # be ACTIVE) and is rejected with ERR_CUSTOMER_BLOCKED.
    set_clock("2026-06-15T18:00:00Z")
    get_success_data(api.block_customer(floor["customer"]["id"], MANAGER))
    resp = api.confirm_reservation(res["id"], HOST)
    validate_error(resp, "ERR_CUSTOMER_BLOCKED")


# ─── boundary_precision_check / strike threshold blocks at exactly three ───
def _no_show_once(api, rid, cust, tbl, start, clock_after):
    res = book_reservation(rid, cust, tbl, party_size=2, reservation_start=start)
    confirm(res["id"])
    set_clock(clock_after)
    get_success_data(api.no_show_reservation(res["id"], HOST))


def test_customer_active_at_two_strikes(api):
    """PRD §3.5: "If the increment brings `no_show_strikes` to or above the
    restaurant's `no_show_strike_block_threshold`, the customer is set
    `BLOCKED`".

    Design: Difficulty/boundary_precision_check/noshow_strike_threshold_blocks_at_exactly_three
    """
    floor = setup_floor(restaurant_overrides={"per_seat_deposit_cents": 2500,
                                              "no_show_strike_block_threshold": 3},
                        table_overrides={"max_party_size": 8},
                        period_overrides={"pacing_max_covers_per_slot": 30})
    rid, cust, tbl = floor["restaurant"]["id"], floor["customer"]["id"], floor["table"]["id"]
    _no_show_once(api, rid, cust, tbl, "2026-06-15T18:00:00Z", "2026-06-15T18:20:00Z")
    _no_show_once(api, rid, cust, tbl, "2026-06-16T18:00:00Z", "2026-06-16T18:20:00Z")
    customer = validate_success(api.get_customer(cust, HOST), 200)
    assert customer["no_show_strikes"] == 2
    assert customer["status"] == "ACTIVE", "two strikes (< threshold 3) stays ACTIVE"


def test_customer_blocked_at_exactly_three_strikes(api):
    """PRD §3.5: "If the increment brings `no_show_strikes` to or above the
    restaurant's `no_show_strike_block_threshold`, the customer is set
    `BLOCKED`".

    Design: Difficulty/boundary_precision_check/noshow_strike_threshold_blocks_at_exactly_three
    """
    floor = setup_floor(restaurant_overrides={"per_seat_deposit_cents": 2500,
                                              "no_show_strike_block_threshold": 3},
                        table_overrides={"max_party_size": 8},
                        period_overrides={"pacing_max_covers_per_slot": 30})
    rid, cust, tbl = floor["restaurant"]["id"], floor["customer"]["id"], floor["table"]["id"]
    _no_show_once(api, rid, cust, tbl, "2026-06-15T18:00:00Z", "2026-06-15T18:20:00Z")
    _no_show_once(api, rid, cust, tbl, "2026-06-16T18:00:00Z", "2026-06-16T18:20:00Z")
    _no_show_once(api, rid, cust, tbl, "2026-06-17T18:00:00Z", "2026-06-17T18:20:00Z")
    customer = validate_success(api.get_customer(cust, HOST), 200)
    assert customer["no_show_strikes"] == 3
    assert customer["status"] == "BLOCKED", "third strike (== threshold) flips to BLOCKED"


# ─── corner state-machine instances on Reservation ────────────────────────
def test_seat_from_requested_invalid_state(api):
    """PRD §3.5: "**Seating** a confirmed party requires the reservation to be
    `CONFIRMED` and its table to be `AVAILABLE` or `DIRTY`".

    Design: Corner/state_machines/seat_reservation_from_requested_invalid_state
    """
    floor = setup_floor(table_overrides={"max_party_size": 8})
    res = book_reservation(floor["restaurant"]["id"], floor["customer"]["id"],
                           floor["table"]["id"], party_size=2)
    resp = api.seat_reservation(res["id"], HOST)
    validate_error(resp, "ERR_INVALID_STATE")
    after = validate_success(api.get_reservation(res["id"], HOST), 200)
    assert after["status"] == "REQUESTED", "rejected seat leaves status unchanged"


def test_cancel_completed_reservation_terminal_lockdown(api):
    """PRD §4: "reads and state-changing actions on existing resources return
    HTTP 200 with the affected resource". PRD §3.6: "A guest or host may
    **cancel** a reservation that is `REQUESTED` or `CONFIRMED`".

    Design: Corner/state_machines/cancel_completed_reservation_terminal_lockdown
    """
    ctx = setup_seated_reservation(party_size=2, table_overrides={"max_party_size": 8})
    completed = validate_success(api.complete_reservation(ctx["reservation"]["id"], HOST), 200)
    assert completed["status"] == "COMPLETED"
    resp = api.cancel_reservation(completed["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, "ERR_INVALID_STATE")
    after = validate_success(api.get_reservation(completed["id"], HOST), 200)
    assert after["status"] == "COMPLETED", "terminal COMPLETED is locked"


def test_new_reservation_starts_in_requested(api):
    """PRD §3.3: "A new reservation is born `REQUESTED`."

    Design: Corner/state_machines/initial_state_reservation_is_requested
    """
    floor = setup_floor(table_overrides={"max_party_size": 8})
    res = book_reservation(floor["restaurant"]["id"], floor["customer"]["id"],
                           floor["table"]["id"], party_size=2)
    assert res["status"] == "REQUESTED"


def test_complete_sets_table_dirty_and_increments_lifetime(api):
    """PRD §3.5: "**Completing** a `SEATED` reservation moves it to `COMPLETED`,
    increments the customer's `lifetime_reservations` and recomputes the
    customer's reliability, sets the table `DIRTY`".

    Design: Corner/state_machines/complete_sets_table_dirty_bubble_side_effect
    """
    ctx = setup_seated_reservation(party_size=2, table_overrides={"max_party_size": 8})
    completed = validate_success(api.complete_reservation(ctx["reservation"]["id"], HOST), 200)
    assert completed["status"] == "COMPLETED"
    table = validate_success(api.get_table(ctx["table"]["id"], HOST), 200)
    assert table["status"] == "DIRTY", "completed reservation leaves table DIRTY"
    customer = validate_success(api.get_customer(ctx["customer"]["id"], HOST), 200)
    assert customer["lifetime_reservations"] == 1


def test_no_show_before_grace_rejected(api):
    """PRD §3.5: "A host may mark a `CONFIRMED` reservation as a no-show only
    once the current time is at or after the booking's start plus a
    fifteen-minute grace; marking earlier is rejected with
    `ERR_NO_SHOW_TOO_EARLY`."

    Design: Corner/state_machines/noshow_before_grace_returns_too_early
    """
    ctx = setup_confirmed_reservation(party_size=2, table_overrides={"max_party_size": 8})
    # Clock exactly at reservation_start (0 min < 15 min grace).
    set_clock("2026-06-15T18:00:00Z")
    resp = api.no_show_reservation(ctx["reservation"]["id"], HOST)
    validate_error(resp, "ERR_NO_SHOW_TOO_EARLY")
    after = validate_success(api.get_reservation(ctx["reservation"]["id"], HOST), 200)
    assert after["status"] == "CONFIRMED", "rejected no-show leaves status CONFIRMED"


def test_reschedule_after_cutoff_rejected(api):
    """PRD §3.6: "the current time must be strictly before the booking's start
    minus the restaurant's `late_cancel_cutoff_hours`; an attempt at or after
    that cutoff is rejected with `ERR_RESCHEDULE_TOO_LATE`."

    Design: Corner/state_machines/reschedule_after_cutoff_returns_too_late
    """
    ctx = setup_confirmed_reservation(
        party_size=2,
        restaurant_overrides={"late_cancel_cutoff_hours": 24},
        table_overrides={"max_party_size": 8})
    # Clock 12:00 same day; start 18:00, cutoff 24h → late window started long ago.
    tbl = ctx["table"]["id"]
    tv = current_table_version(tbl)
    resp = api.reschedule_reservation(
        ctx["reservation"]["id"],
        create_reschedule_payload(tbl, tv, "2026-06-15T19:00:00Z"),
        make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, "ERR_RESCHEDULE_TOO_LATE")
    after = validate_success(api.get_reservation(ctx["reservation"]["id"], HOST), 200)
    assert after["status"] == "CONFIRMED", "rejected reschedule leaves status CONFIRMED"


def test_confirm_requested_reservation_emits_notification(api):
    """PRD §3.4: "A successful confirm sets the reservation `CONFIRMED` and emits
    a `Notification` with template `RESERVATION_CONFIRMED` to the customer's
    phone."

    Design: Corner/state_machines/confirm_reservation_from_requested_valid
    """
    floor = setup_floor(table_overrides={"max_party_size": 8})
    res = book_reservation(floor["restaurant"]["id"], floor["customer"]["id"],
                           floor["table"]["id"], party_size=2)
    confirmed = validate_success(api.confirm_reservation(res["id"], HOST), 200)
    assert confirmed["status"] == "CONFIRMED"
    data, _meta = validate_paginated(api.list_notifications(
        HOST, params={"subject_type": "RESERVATION", "subject_id": res["id"]}))
    templates = [n["template"] for n in data]
    assert "RESERVATION_CONFIRMED" in templates, \
        f"confirm emits a RESERVATION_CONFIRMED notification, got {templates}"
