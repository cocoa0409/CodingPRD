"""Optimistic concurrency on the departure seat pool: stale-version rejection
and per-mutation version increment.

Queue B: cross_cutting_complexity_layers section.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_operator_headers, make_guest_headers,
    get_success_data,
    create_guest_payload, create_booking_payload,
    setup_scheduled_departure,
)
from test_helpers import api_client

OP = make_operator_headers()


def test_occ_stale_departure_version_on_reserve_returns_412(api):
    """PRD §2.7: "The server compares `expected_departure_version` against the
    departure's current `version`. If another writer has reserved or released
    seats since the client read the departure — thereby advancing the
    departure's `version` — the client's view of remaining capacity is stale,
    and the reservation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_departure_version_on_reserve_returns_412
    """
    s = setup_scheduled_departure(seat_capacity=12)
    dep_id = s["departure"]["id"]
    v0 = s["departure"]["version"]
    g1 = get_success_data(api.create_guest(create_guest_payload(full_name="G1"), OP))
    g2 = get_success_data(api.create_guest(create_guest_payload(full_name="G2"), OP))
    b1 = get_success_data(api.create_booking(
        create_booking_payload(dep_id, g1["id"], s["pickup"]["id"], 3),
        make_guest_headers(g1["id"])))
    b2 = get_success_data(api.create_booking(
        create_booking_payload(dep_id, g2["id"], s["pickup"]["id"], 3),
        make_guest_headers(g2["id"])))
    # Reserve b1 at v0 -> advances departure version.
    get_success_data(api.reserve_booking(b1["id"], v0, make_guest_headers(g1["id"])))
    # Reserve b2 still carrying the now-stale v0 -> rejected 412.
    resp = api.reserve_booking(b2["id"], v0, make_guest_headers(g2["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


def test_version_increments_on_every_departure_mutation(api):
    """PRD §2.4: "The `version` field is an integer that starts at its initial
    value on creation and increments by one on every mutation of the resource"
    PRD §3.6: "When all preconditions hold, the reservation adds `party_size` to
    the departure's `seats_taken` ..., increments the departure's `version`, and
    increments the booking's `version`."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_departure_mutation
    """
    s = setup_scheduled_departure(seat_capacity=12)
    assert s["departure"]["version"] == 1, \
        f"departure version must start at 1, got {s['departure']['version']}"
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 3),
        make_guest_headers(guest["id"])))
    get_success_data(api.reserve_booking(
        booking["id"], s["departure"]["version"], make_guest_headers(guest["id"])))
    dep_after = validate_success(api.get_departure(s["departure"]["id"], OP))
    assert dep_after["version"] == 2, \
        f"departure version must be 2 after one reserve, got {dep_after['version']}"
