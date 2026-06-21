"""Validation-priority conflicts where two checks fail and the lower-priority
number wins.

PRD §2.10 states the full fixed priority order in prose AND that "A request that
fails an earlier check is rejected on that check and the later checks are not
consulted", so these orderings are explicitly named by the PRD contract.

Covers Difficulty rule priority_pair_validation_conflict.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, make_customer_headers,
    TEST_USERS,
    setup_floor, book_reservation, place_hold, confirm, set_clock,
    current_table_version, create_reservation_payload,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]


# ─── blocked customer (P6) beats party-size mismatch (P8) ─────────────────
def test_blocked_customer_beats_party_size_mismatch(api):
    """PRD §2.10: "then the blocked-customer safety check (`ERR_CUSTOMER_BLOCKED`),
    then the restaurant-open check (`ERR_RESTAURANT_CLOSED`), then party-size
    matching (`ERR_PARTY_SIZE_MISMATCH`)".

    Design: Difficulty/priority_pair_validation_conflict/blocked_customer_beats_party_size_mismatch
    """
    floor = setup_floor(table_overrides={"max_party_size": 8},
                        period_overrides={"pacing_max_covers_per_slot": 30})
    cust = floor["customer"]["id"]
    get_success_data(api.block_customer(cust, MANAGER))
    tv = current_table_version(floor["table"]["id"])
    # Party 9 on a max-8 table fails BOTH blocked (P6) and party-size (P8);
    # the lower priority number (P6) wins.
    resp = api.create_reservation(
        create_reservation_payload(floor["restaurant"]["id"], cust,
                                   floor["table"]["id"], tv, party_size=9,
                                   reservation_start="2026-06-15T18:00:00Z"),
        HOST)
    validate_error(resp, "ERR_CUSTOMER_BLOCKED")


def test_blocked_customer_create_rejected_party_within_band(api):
    """PRD §3.2: "A `BLOCKED` guest cannot create or confirm a reservation or
    join the waitlist; such attempts are rejected with `ERR_CUSTOMER_BLOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/blocked_customer_beats_party_size_mismatch
    """
    # Isolated single-failure control: a blocked customer with a valid party
    # size still fails with ERR_CUSTOMER_BLOCKED (the safety check alone).
    floor = setup_floor(table_overrides={"max_party_size": 8})
    cust = floor["customer"]["id"]
    get_success_data(api.block_customer(cust, MANAGER))
    tv = current_table_version(floor["table"]["id"])
    resp = api.create_reservation(
        create_reservation_payload(floor["restaurant"]["id"], cust,
                                   floor["table"]["id"], tv, party_size=2,
                                   reservation_start="2026-06-15T18:00:00Z"),
        HOST)
    validate_error(resp, "ERR_CUSTOMER_BLOCKED")


# ─── invalid state (P4) beats deposit required (P13) on confirm ───────────
def _setup_confirmed_then_released_hold(api):
    """A deposit_required (party-6) reservation CONFIRMED via a hold that is then
    released, leaving no HELD hold. Returns the reservation id."""
    floor = setup_floor(
        restaurant_overrides={"per_seat_deposit_cents": 2500,
                              "deposit_required_party_threshold": 6},
        table_overrides={"max_party_size": 8})
    rid, cust, tbl = floor["restaurant"]["id"], floor["customer"]["id"], floor["table"]["id"]
    res = book_reservation(rid, cust, tbl, party_size=6,
                           reservation_start="2026-06-15T18:00:00Z")
    hold = place_hold(res["id"], cust)
    confirm(res["id"])
    get_success_data(api.release_deposit_hold(hold["id"], MANAGER))
    return res["id"]


def test_invalid_state_beats_deposit_required_on_confirm(api):
    """PRD §2.10: "then — for transition endpoints — whether the target entity
    is in a state from which the transition is defined (`ERR_INVALID_STATE`)".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_deposit_required_on_confirm
    """
    res_id = _setup_confirmed_then_released_hold(api)
    # Reservation is already CONFIRMED (state check P4 fails) AND has no HELD hold
    # (deposit check P13 would fail); P4 wins.
    resp = api.confirm_reservation(res_id, HOST)
    validate_error(resp, "ERR_INVALID_STATE")


def test_second_confirm_on_confirmed_reservation_invalid_state(api):
    """PRD §2.10: "A request that fails an earlier check is rejected on that
    check and the later checks are not consulted." PRD §3.4: "**Confirmation** is
    a host action moving a reservation from `REQUESTED` to `CONFIRMED`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_deposit_required_on_confirm
    """
    res_id = _setup_confirmed_then_released_hold(api)
    resp = api.confirm_reservation(res_id, HOST)
    validate_error(resp, "ERR_INVALID_STATE")
    after = validate_success(api.get_reservation(res_id, HOST), 200)
    assert after["status"] == "CONFIRMED", "the reservation remains CONFIRMED"
