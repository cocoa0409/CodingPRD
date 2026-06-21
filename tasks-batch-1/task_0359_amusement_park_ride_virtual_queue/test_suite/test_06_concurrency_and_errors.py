"""Optimistic concurrency, error, and RBAC tests."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_park, set_clock, create_ride, create_window, create_guest,
    book_vq, setup_park_ride_window, setup_party_with_member,
    make_park_admin_headers, make_ride_operator_headers, make_guest_headers,
    api_client,
)

ADMIN = make_park_admin_headers()
OPERATOR = make_ride_operator_headers()


# ----------------------------------------------------------------------
# Optimistic concurrency control
# ----------------------------------------------------------------------

def test_stale_window_version_on_reservation_rejected(api):
    """PRD §2.7: "If the window's `version` has advanced since then — because
    another writer claimed a slot and bumped it — the new reservation's view of
    `reserved_count` against `slot_capacity` is no longer current, so the create is
    rejected with `ERR_STALE_VERSION` (HTTP 412) before it can oversell the window."

    First booking bumps window.version; a second booking reusing the pre-advance
    version is stale.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_window_version_on_reservation
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=100)
    ga = create_guest(park["id"], full_name="GA")
    gb = create_guest(park["id"], full_name="GB")
    book_vq(ride["id"], ga["id"], window["id"], window["version"])
    resp = api.create_reservation(
        {"ride_id": ride["id"], "guest_id": gb["id"], "return_window_id": window["id"],
         "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": window["version"]},
        make_guest_headers(gb["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_window_version_increments_allows_fresh_booking(api):
    """PRD §3.3: "When a `VIRTUAL_QUEUE` reservation is created and passes every
    gate, the system increments the target window's `reserved_count` by one and the
    ride's `booked_slot_count` by one, advances `ReturnWindow.version`".

    The second booking passing the freshly-read version succeeds; reserved_count
    reaches capacity 2 and the window bubbles to EXHAUSTED.

    Design: Corner/cross_cutting_complexity_layers/occ_window_version_increments_on_each_booking
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=5)
    ga = create_guest(park["id"], full_name="GA")
    gb = create_guest(park["id"], full_name="GB")
    res_a = book_vq(ride["id"], ga["id"], window["id"], window["version"])
    res_b = validate_success(
        api.create_reservation(
            {"ride_id": ride["id"], "guest_id": gb["id"], "return_window_id": window["id"],
             "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": res_a["version"]},
            make_guest_headers(gb["id"]),
        ),
        expected_status=201,
    )
    assert res_b["reservation_status"] == "HELD"
    win = validate_success(api.get_return_window(window["id"], ADMIN))
    assert win["reserved_count"] == 2, f"expected reserved_count 2, got {win['reserved_count']}"
    assert win["window_status"] == "EXHAUSTED", f"window must be EXHAUSTED, got {win['window_status']}"


def test_stale_party_version_on_party_book_rejected(api):
    """PRD §2.7: "Membership link and unlink operations, as well as a prior
    party-booking, all advance `Party.version`; if it has moved since the client's
    last read, the booking would fan out reservations over a member set the client
    no longer knows accurately, so it is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    party-book echoes the pre-member-link version (party_v0), which is now stale.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_party_version_on_party_book
    """
    park, ride, window, leader, member, party = setup_party_with_member(hourly_throughput=5, with_window=True)
    resp = api.party_book(
        party["id"],
        {"ride_id": ride["id"], "return_window_id": window["id"],
         "expected_party_version": party["_v0"]},
        make_guest_headers(leader["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# ----------------------------------------------------------------------
# Error catalogue
# ----------------------------------------------------------------------

def test_leader_removal_forbidden(api):
    """PRD §3.5: "The leader may not be unlinked from its own party — an attempt to
    do so is rejected with `ERR_LEADER_REMOVAL_FORBIDDEN`."

    Design: Corner/errors/leader_removal_forbidden_error
    """
    park = create_park()
    leader = create_guest(park["id"], full_name="GL")
    party = validate_success(
        api.create_party(park["id"], {"leader_guest_id": leader["id"]}, make_guest_headers(leader["id"])),
        expected_status=201,
    )
    resp = api.remove_member(party["id"], leader["id"], make_guest_headers(leader["id"]))
    validate_error(resp, ApiErrorId.ERR_LEADER_REMOVAL_FORBIDDEN)


def test_guest_park_mismatch_on_cross_park_reservation(api):
    """PRD §2.10: "Separately, when a referenced `Guest`, `Ride`, or `ReturnWindow`
    belongs to a different `Park` than the operation's park scope, the request is
    rejected with `ERR_GUEST_PARK_MISMATCH`."

    Guest registered under park A books a ride/window in park B.

    Design: Corner/errors/guest_park_mismatch_on_cross_park_reservation
    """
    park_a = create_park(name="PA")
    park_b = create_park(name="PB")
    set_clock(park_b["id"], "2026-06-15T09:00:00.000Z")
    ride = create_ride(park_b["id"], hourly_throughput=100, name="RB")
    window = create_window(ride["id"])
    guest = create_guest(park_a["id"], full_name="GA")
    resp = api.create_reservation(
        {"ride_id": ride["id"], "guest_id": guest["id"], "return_window_id": window["id"],
         "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": window["version"]},
        make_guest_headers(guest["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_GUEST_PARK_MISMATCH)


# ----------------------------------------------------------------------
# RBAC
# ----------------------------------------------------------------------

def test_guest_cannot_declare_ride_down(api):
    """PRD §2.1: "When a recognized role attempts an operation that its permissions
    do not cover, the request is rejected with `ERR_UNAUTHORIZED`."

    declare-down is RideOperator-only; a GuestApp caller is unauthorized.

    Design: Corner/rbac/guest_cannot_declare_ride_down
    """
    park = create_park()
    ride = create_ride(park["id"], hourly_throughput=100)
    guest = create_guest(park["id"], full_name="G1")
    resp = api.declare_down(ride["id"], make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_guest_cannot_cancel_other_guests_reservation(api):
    """PRD §2.1: "a `GuestApp` request that targets a reservation, party, or
    purchase belonging to another guest — that is, whose `X-User-ID` is neither the
    owning `guest_id` nor the `leader_guest_id` of the target party — is rejected
    with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/guest_cannot_act_on_other_guests_reservation
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=100)
    g1 = create_guest(park["id"], full_name="G1")
    g2 = create_guest(park["id"], full_name="G2")
    res = book_vq(ride["id"], g1["id"], window["id"], window["version"])
    resp = api.cancel_reservation(res["id"], make_guest_headers(g2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "Every request to the API must be authenticated through two
    mandatory HTTP headers. `X-User-ID` identifies the acting principal, and
    `X-User-Role` declares the operational capacity under which it acts. If either
    header is missing, or `X-User-Role` does not name a role the system recognizes,
    the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    park = create_park()
    resp = api.get_park(park["id"], {})  # no auth headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
