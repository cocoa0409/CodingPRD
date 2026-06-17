"""Cascade tests: window expiry, ride breakdown, redistribution, party disband.

Covers the transitive cascades from the difficulty index plus the corner-index
side-effect-execution instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_park, set_clock, create_ride, create_window, create_guest,
    book_vq, confirm, setup_park_ride_window, setup_party_with_member,
    setup_active_lightning_lane,
    make_park_admin_headers, make_ride_operator_headers, make_guest_headers,
    api_client,
)

ADMIN = make_park_admin_headers()
OPERATOR = make_ride_operator_headers()


def test_window_expiry_forfeits_reservation_and_recomputes_wait(api):
    """PRD §3.4: "for each window in `OPEN` or `EXHAUSTED` status whose
    `window_end_utc` is at or before the park's `current_utc`, the window moves to
    `EXPIRED`. Expiring a window cascades to its reservations: each reservation on
    that window still in `HELD` or `BOOKED` is forfeited — moved to `FORFEITED` —
    and for `VIRTUAL_QUEUE` reservations the freed slot is credited back by
    decrementing the window's `reserved_count` and the ride's `booked_slot_count`
    each by one."

    After forfeit, booked_slot_count 1->0, so posted_wait recomputes to
    ceil((0+20)/100*60) = 12.

    Design: Difficulty/transitive_cascade/window_expiry_forfeits_reservation_then_recomputes_wait
    """
    park = create_park()
    set_clock(park["id"], "2026-06-15T10:30:00.000Z")
    ride = create_ride(park["id"], hourly_throughput=100)
    window = create_window(ride["id"], "2026-06-15T10:00:00.000Z", "2026-06-15T11:00:00.000Z")
    guest = create_guest(park["id"], full_name="G1")
    res = book_vq(ride["id"], guest["id"], window["id"], window["version"])
    confirm(res["id"], guest["id"])
    set_clock(park["id"], "2026-06-15T11:05:00.000Z")

    validate_success(api.advance_windows(park["id"], ADMIN))

    win = validate_success(api.get_return_window(window["id"], ADMIN))
    assert win["window_status"] == "EXPIRED", f"window must be EXPIRED, got {win['window_status']}"
    reservation = validate_success(api.get_reservation(res["id"], ADMIN))
    assert reservation["reservation_status"] == "FORFEITED", \
        f"reservation must be FORFEITED, got {reservation['reservation_status']}"
    ride_data = validate_success(api.get_ride(ride["id"], ADMIN))
    assert ride_data["booked_slot_count"] == 0, \
        f"booked_slot_count must drop to 0, got {ride_data['booked_slot_count']}"
    assert ride_data["posted_wait_minutes"] == 12, \
        f"posted_wait must recompute to 12, got {ride_data['posted_wait_minutes']}"


def test_party_disband_removes_memberships_and_clears_guest_party_id(api):
    """PRD §3.5: "A party that is still `FORMING` may be disbanded by the leader:
    disbanding moves the party `FORMING → DISBANDED`, sets every `LINKED` membership
    to `REMOVED`, and clears the `party_id` of each affected guest back to null."

    Design: Difficulty/transitive_cascade/party_disband_removes_memberships_then_clears_guest_party_id
    """
    park, ride, window, leader, member, party = setup_party_with_member(with_window=False)
    membership_id = party["_member_membership_id"]

    data = validate_success(api.disband(party["id"], make_guest_headers(leader["id"])))
    assert data["party_status"] == "DISBANDED"

    mem = validate_success(api.get_membership(membership_id, ADMIN))
    assert mem["membership_status"] == "REMOVED", \
        f"membership must be REMOVED, got {mem['membership_status']}"
    member_data = validate_success(api.get_guest(member["id"], ADMIN))
    assert member_data["party_id"] is None, \
        f"member party_id must clear to null, got {member_data['party_id']}"
    leader_data = validate_success(api.get_guest(leader["id"], ADMIN))
    assert leader_data["party_id"] is None, \
        f"leader party_id must clear to null, got {leader_data['party_id']}"


def test_ride_down_refunds_active_lightning_lane_hold(api):
    """PRD §3.7: "Every Lightning Lane purchase on the ride in `ACTIVE` status is
    refunded as compensation: it moves `ACTIVE → REFUNDED`, and its `charged_cents`
    is credited back."

    Design: Corner/state_machines/ride_down_refunds_active_lightning_lane_hold
    """
    park, ride, guest, plan, purchase = setup_active_lightning_lane()
    data = validate_success(api.declare_down(ride["id"], OPERATOR))
    assert data["operational_status"] == "DOWN"

    ll = validate_success(api.get_lightning_lane_purchase(purchase["id"], ADMIN))
    assert ll["hold_status"] == "REFUNDED", \
        f"active LL hold must become REFUNDED, got {ll['hold_status']}"


def test_ride_down_redistribution_cascade(api):
    """PRD §3.7: "Every reservation on the ride in `BOOKED` status is redistributed:
    it moves `BOOKED → REDISTRIBUTED`, its `redistributed_from_window_id` is set to
    the window it currently occupies, and that old window's `reserved_count` and the
    ride's `booked_slot_count` are each decremented by one."
    PRD §3.7: "Every child window currently `OPEN` or `EXHAUSTED` is suspended,
    moving to `SUSPENDED`."

    Design: Corner/cross_cutting_complexity_layers/ride_down_redistribution_cascade_end_to_end
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=5)
    guest = create_guest(park["id"], full_name="G1")
    res = book_vq(ride["id"], guest["id"], window["id"], window["version"])
    confirm(res["id"], guest["id"])

    validate_success(api.declare_down(ride["id"], OPERATOR))

    reservation = validate_success(api.get_reservation(res["id"], ADMIN))
    assert reservation["reservation_status"] == "REDISTRIBUTED", \
        f"booked reservation must become REDISTRIBUTED, got {reservation['reservation_status']}"
    assert reservation["redistributed_from_window_id"] == window["id"], \
        f"redistributed_from_window_id must record original window, got {reservation['redistributed_from_window_id']}"
    win = validate_success(api.get_return_window(window["id"], ADMIN))
    assert win["reserved_count"] == 0, f"old window reserved_count must decrement to 0, got {win['reserved_count']}"
    assert win["window_status"] == "SUSPENDED", f"window must be SUSPENDED, got {win['window_status']}"
    ride_data = validate_success(api.get_ride(ride["id"], ADMIN))
    assert ride_data["booked_slot_count"] == 0, \
        f"booked_slot_count must drop to 0, got {ride_data['booked_slot_count']}"


def test_party_book_fans_out_held_reservations(api):
    """PRD §3.5: "it moves the party `FORMING → LOCKED` ... For each `LINKED` member
    that passes the height and accessibility checks, the system creates one `HELD`
    `VIRTUAL_QUEUE` reservation against the chosen window, debiting the window's
    `reserved_count` and the ride's `booked_slot_count` per created reservation".

    Leader GL + member GM, ride R5 60-min window capacity 2 -> two HELD reservations,
    reserved_count 2.

    Design: Corner/state_machines/party_book_creates_held_reservations_for_linked_members
    """
    park, ride, window, leader, member, party = setup_party_with_member(hourly_throughput=5, with_window=True)
    resp = api.party_book(
        party["id"],
        {"ride_id": ride["id"], "return_window_id": window["id"],
         "expected_party_version": party["_v1"]},
        make_guest_headers(leader["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert len(data["created_reservation_ids"]) == 2, \
        f"expected 2 created reservations, got {len(data['created_reservation_ids'])}"

    party_data = validate_success(api.get_party(party["id"], ADMIN))
    assert party_data["party_status"] == "LOCKED", \
        f"party must be LOCKED, got {party_data['party_status']}"
    win = validate_success(api.get_return_window(window["id"], ADMIN))
    assert win["reserved_count"] == 2, f"window reserved_count must be 2, got {win['reserved_count']}"
