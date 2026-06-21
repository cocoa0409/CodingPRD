"""Private-dining lifecycle and optimistic-concurrency on shared inventory.

Covers the corner cross_cutting_complexity_layers OCC instances (stale table
version on create; stale area version on buyout confirm; table version
increments on every mutation) and the private-dining state-machine / error
corner instances. The buyout-cascade corner instance is asserted in
test_03_cascades.py.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, make_customer_headers,
    TEST_USERS,
    setup_private_area,
    make_restaurant, make_dining_area, make_table, make_service_period,
    make_customer, set_clock, book_reservation, current_table_version,
    make_private_event, propose_private_event,
    create_reservation_payload, create_confirm_buyout_payload,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]


# ─── corner / OCC stale table version on reservation create ────────────────
def test_create_with_stale_table_version_rejected(api):
    """PRD §2.9: "If that value does not equal the table's current `version` ...
    the create is rejected with `ERR_STALE_TABLE_VERSION` (HTTP 412), preventing
    the client from booking over a slot it never actually saw as free."

    Design: Corner/cross_cutting_complexity_layers/occ_reservation_create_stale_table_version
    """
    restaurant = make_restaurant(default_turn_time_minutes=90, cleanup_buffer_minutes=15)
    area = make_dining_area(restaurant["id"])
    table = make_table(area["id"], max_party_size=8)
    make_service_period(restaurant["id"], pacing_max_covers_per_slot=30)
    customer = make_customer()
    set_clock("2026-06-15T12:00:00Z")
    stale_version = table["version"]  # version 1
    # First create advances table.version 1 → 2. Window: 20:00 → 21:45 (90 turn
    # + 15 cleanup).
    book_reservation(restaurant["id"], customer["id"], table["id"],
                     expected_table_version=stale_version, party_size=2,
                     reservation_start="2026-06-15T20:00:00Z")
    # Second create at 22:00 (grid-aligned, window 22:00 → 23:45) does NOT
    # overlap the first reservation's 20:00–21:45 window, so the table-overlap
    # check (ERR_TABLE_DOUBLE_BOOKED, which precedes the OCC token in §2.10) is
    # not tripped — isolating the stale-version rejection. The request still
    # carries expected_table_version 1 while the table is now at version 2.
    resp = api.create_reservation(
        create_reservation_payload(restaurant["id"], customer["id"], table["id"],
                                   stale_version, party_size=2,
                                   reservation_start="2026-06-15T22:00:00Z"),
        make_customer_headers(customer["id"]))
    validate_error(resp, "ERR_STALE_TABLE_VERSION")


# ─── corner / OCC stale area version on buyout confirm ─────────────────────
def test_buyout_confirm_with_stale_area_version_rejected(api):
    """PRD §2.9: "If that value does not equal the area's current `version` ...
    the confirm is rejected with `ERR_STALE_AREA_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_private_dining_confirm_stale_area_version
    """
    restaurant = make_restaurant()
    area = make_dining_area(restaurant["id"], name="PRIVATE_ROOM", kind="PRIVATE")
    stale_area_version = area["version"]  # version 1, the client's last observed
    customer = make_customer()
    # A prior buyout (e1) legitimately confirms and occupies the area window,
    # advancing the area's version 1 → 2; cancelling that CONFIRMED event returns
    # the area to AVAILABLE and advances its version 2 → 3 (PRD §3.4). The area is
    # now AVAILABLE again at version 3 with no CONFIRMED buyout left on it, so the
    # confirm preconditions (event PROPOSED, area AVAILABLE, no overlapping
    # confirmed buyout) all pass and the optimistic-concurrency token is the
    # check that fires.
    e1 = make_private_event(restaurant["id"], area["id"], customer["id"],
                            party_size=12, food_minimum_cents=200000,
                            event_start="2026-07-01T18:00:00Z",
                            event_end="2026-07-01T22:00:00Z")
    propose_private_event(e1["id"])
    get_success_data(api.confirm_private_dining_event(
        e1["id"], create_confirm_buyout_payload(stale_area_version), MANAGER))
    get_success_data(api.cancel_private_dining_event(e1["id"], MANAGER))
    # e2 is PROPOSED on the now-AVAILABLE area (live version 3); the confirm still
    # carries expected_dining_area_version 1, which is stale.
    e2 = make_private_event(restaurant["id"], area["id"], customer["id"],
                            party_size=10, food_minimum_cents=150000,
                            event_start="2026-07-02T18:00:00Z",
                            event_end="2026-07-02T22:00:00Z")
    propose_private_event(e2["id"])
    resp = api.confirm_private_dining_event(
        e2["id"], create_confirm_buyout_payload(stale_area_version), MANAGER)
    validate_error(resp, "ERR_STALE_AREA_VERSION")


# ─── corner / table version increments on every mutation ───────────────────
def test_table_version_increments_on_each_mutation(api):
    """PRD §3.1: "A table is born `AVAILABLE` (and at `version` 1) ... Taking a
    table out of service, returning it to service, and bussing a dirty table
    each set the table's status accordingly and increment the table's `version`".

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_table_mutation
    """
    restaurant = make_restaurant()
    area = make_dining_area(restaurant["id"])
    table = make_table(area["id"], max_party_size=8)
    assert table["version"] == 1, "table is born at version 1"
    get_success_data(api.table_out_of_service(table["id"], MANAGER))  # → 2
    returned = validate_success(api.table_return_to_service(table["id"], MANAGER), 200)  # → 3
    assert returned["version"] == 3
    assert returned["status"] == "AVAILABLE"


# ─── corner / private-dining revise cycle PROPOSED→INQUIRY ─────────────────
def test_private_dining_revise_returns_to_inquiry(api):
    """PRD §3.4: "From `PROPOSED` a manager may **revise** the event back to
    `INQUIRY` to re-price it (a loop that may repeat)".

    Design: Corner/state_machines/private_dining_revise_cycle_back_to_inquiry
    """
    restaurant = make_restaurant()
    area = make_dining_area(restaurant["id"], name="PRIVATE_ROOM", kind="PRIVATE")
    customer = make_customer()
    event = make_private_event(restaurant["id"], area["id"], customer["id"],
                               party_size=12, food_minimum_cents=200000,
                               event_start="2026-07-01T18:00:00Z",
                               event_end="2026-07-01T22:00:00Z")
    propose_private_event(event["id"])
    revised = validate_success(api.revise_private_dining_event(event["id"], MANAGER), 200)
    assert revised["status"] == "INQUIRY"


# ─── corner / propose on non-private area rejected ─────────────────────────
def test_propose_on_non_private_area_rejected(api):
    """PRD §3.4: "A manager **proposes** the event, which is allowed only from
    `INQUIRY` and only when the referenced area's `kind` is `PRIVATE` —
    proposing on a non-private area is rejected with `ERR_AREA_NOT_PRIVATE`."

    Design: Corner/errors/propose_private_dining_on_non_private_area_rejected
    """
    restaurant = make_restaurant()
    area = make_dining_area(restaurant["id"], name="MAIN", kind="STANDARD")
    customer = make_customer()
    event = make_private_event(restaurant["id"], area["id"], customer["id"],
                               party_size=12, food_minimum_cents=200000,
                               event_start="2026-07-01T18:00:00Z",
                               event_end="2026-07-01T22:00:00Z")
    resp = api.propose_private_dining_event(event["id"], MANAGER)
    validate_error(resp, "ERR_AREA_NOT_PRIVATE")
