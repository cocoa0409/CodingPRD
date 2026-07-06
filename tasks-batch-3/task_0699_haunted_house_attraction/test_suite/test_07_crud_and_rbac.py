"""Entity creation, defaults, not-found, listing, and role/ownership access control."""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    validate_paginated,
    create_venue, create_attraction, create_guest, create_reservation, add_ticket,
    create_time_slot, create_attraction_payload, create_venue_payload,
    create_pass_product_payload, make_guest_headers,
    NON_EXISTENT_UUID, TEST_USERS,
)

OPS = TEST_USERS["ops_headers"]
BOX = TEST_USERS["box_office_headers"]
ACTOR = TEST_USERS["actor_headers"]


# ─── Entities ──────────────────────────────────────────────────────────────

def test_create_venue_returns_201_with_defaults(api):
    """PRD 3.1: "A fresh venue starts with operational_state of OPEN, weather_status
    of CLEAR, an open_attraction_count of zero, and version 1."

    POST /venues with name + timezone returns 201 and the documented defaults.

    Design: Corner/entities/create_venue_returns_201_with_defaults
    """
    res = api.create_venue(create_venue_payload(name="Fright Park"), OPS)
    venue = validate_success(res, 201)
    assert venue["weather_status"] == "CLEAR"
    assert venue["operational_state"] == "OPEN"
    assert venue["open_attraction_count"] == 0
    assert venue["version"] == 1


def test_create_attraction_missing_scare_level_rejected(api):
    """PRD 3.1: "the manager creates each Attraction by supplying the parent's
    identifier, a name, a min_age that must be zero or greater, a scare_level from 1
    through 5 expressing intensity, and a throughput_per_slot of at least 1". PRD 2.6:
    "A request whose body is malformed, omits a required field, or supplies an invalid
    enumeration value is rejected earlier still with ERR_INVALID_REQUEST."

    POST /attractions omitting the required scare_level is rejected ERR_INVALID_REQUEST.

    Design: Corner/entities/create_attraction_missing_scare_level_returns_invalid_request
    """
    venue = create_venue()
    payload = create_attraction_payload(venue["id"])
    del payload["scare_level"]
    res = api.create_attraction(payload, OPS)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_get_attraction_unknown_id_returns_not_found(api):
    """PRD 2.6: "the first identifier in the path that does not resolve to an existing
    resource causes immediate rejection with ERR_NOT_FOUND".

    GET /attractions/{id} with a non-existent UUID is rejected ERR_NOT_FOUND.

    Design: Corner/entities/get_attraction_unknown_id_returns_not_found
    """
    res = api.get_attraction(NON_EXISTENT_UUID, OPS)
    validate_error(res, "ERR_NOT_FOUND")


def test_new_attraction_status_open_and_raises_open_count(api):
    """PRD 3.1: "A new attraction begins life in status OPEN. Creating an open
    attraction raises the venue's open_attraction_count by one and recomputes the
    venue's operational_state."

    A newly created attraction has status OPEN and the parent venue's
    open_attraction_count becomes 1.

    Design: Corner/entities/attraction_status_initial_open
    """
    venue = create_venue()
    attraction = create_attraction(venue["id"])
    assert attraction["status"] == "OPEN"
    refreshed = validate_success(api.get_venue(venue["id"], OPS), 200)
    assert refreshed["open_attraction_count"] == 1


def test_pass_product_min_party_defaults_to_one(api):
    """PRD 3.4: "a min_party that for a GROUP product is the minimum party_size
    required before the discount applies (it is 1 for a SEASON product, and defaults
    to 1 when omitted)."

    Omitting min_party on POST /venues/{id}/pass-products applies the default 1.

    Design: Corner/entities/pass_product_min_party_default_is_one
    """
    venue = create_venue()
    res = api.create_pass_product(
        venue["id"],
        create_pass_product_payload(kind="SEASON", price_cents=5000,
                                    discount_pct=10, max_redemptions=5),
        OPS,
    )
    product = validate_success(res, 201)
    assert product["min_party"] == 1


def test_list_attractions_returns_array_pagination_envelope(api):
    """PRD 2.3: "The envelope's meta object for any list response includes the
    pagination fields limit, offset, total_count, and has_more."

    GET /attractions filtered by venue returns an array envelope with total_count 1
    and has_more false for a venue with one attraction.

    Design: Corner/entities/list_attractions_pagination_envelope
    """
    venue = create_venue()
    create_attraction(venue["id"])
    data, meta = validate_paginated(
        api.list_attractions(OPS, params={"venue_id": venue["id"]})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_list_tickets_by_reservation_returns_its_tickets(api):
    """PRD 2.3: "every list is returned ... The envelope's meta object for any list
    response includes the pagination fields limit, offset, total_count, and has_more."

    GET /tickets?reservation_id=... returns the array of tickets on that reservation;
    a reservation with two tickets yields total_count 2.

    Design: Corner/endpoints/tickets_reverse_reachability_by_reservation
    """
    venue = create_venue()
    attraction = create_attraction(venue["id"])
    slot = create_time_slot(attraction["id"])
    guest = create_guest()
    reservation = create_reservation(venue["id"], guest["id"])
    add_ticket(reservation["id"], slot["id"], tier="GA")
    add_ticket(reservation["id"], slot["id"], tier="FAST_PASS")

    data, meta = validate_paginated(
        api.list_tickets(BOX, params={"reservation_id": reservation["id"]})
    )
    assert meta["total_count"] == 2


# ─── RBAC / ownership ──────────────────────────────────────────────────────

def test_guest_cannot_create_venue(api):
    """PRD 2.1: "When a role attempts an operation it is not authorised for under the
    matrix in Section 4, the request is rejected with ERR_ROLE_FORBIDDEN."

    A Guest calling POST /venues (an OpsManager-only operation) is rejected
    ERR_ROLE_FORBIDDEN.

    Design: Corner/rbac/guest_cannot_create_venue
    """
    guest = create_guest()
    res = api.create_venue(create_venue_payload(name="Sneaky"), make_guest_headers(guest["id"]))
    validate_error(res, "ERR_ROLE_FORBIDDEN")


def test_actor_cannot_admit_reservation(api):
    """PRD 2.1: "When a role attempts an operation it is not authorised for under the
    matrix in Section 4, the request is rejected with ERR_ROLE_FORBIDDEN."

    An Actor calling POST /reservations/{id}/admit (a BoxOffice-only operation) is
    rejected ERR_ROLE_FORBIDDEN.

    Design: Corner/rbac/actor_cannot_admit_reservation
    """
    venue = create_venue()
    guest = create_guest()
    reservation = create_reservation(venue["id"], guest["id"])
    res = api.admit_reservation(reservation["id"], ACTOR)
    validate_error(res, "ERR_ROLE_FORBIDDEN")


def test_guest_cannot_cancel_other_guests_reservation(api):
    """PRD 2.1: "ownership checks on any guest-owned resource — a Guest record, a
    Reservation, a Waiver, or a Pass — compare the resource's owning guest_id ... to
    X-User-ID, and a mismatch is rejected with ERR_NOT_OWNER."

    Guest GB cancelling guest GA's reservation is rejected ERR_NOT_OWNER.

    Design: Corner/rbac/guest_cannot_cancel_other_guests_reservation_not_owner
    """
    venue = create_venue()
    ga = create_guest(full_name="GA", email="ga@x.com")
    gb = create_guest(full_name="GB", email="gb@x.com")
    # GA creates their own reservation.
    reservation = get_success_data(
        api.create_reservation({"venue_id": venue["id"], "guest_id": ga["id"]},
                               make_guest_headers(ga["id"]))
    )
    res = api.cancel_reservation(reservation["id"], make_guest_headers(gb["id"]))
    validate_error(res, "ERR_NOT_OWNER")


def test_missing_auth_headers_rejected(api):
    """PRD 2.1: "Every request must carry two mandatory headers: X-User-ID,
    identifying the acting user, and X-User-Role ... A request missing either header
    is rejected with ERR_MISSING_AUTH."

    A GET with no auth headers is rejected ERR_MISSING_AUTH.

    Design: Corner/rbac/missing_auth_header_returns_missing_auth
    """
    res = api.get_venue(NON_EXISTENT_UUID, {})
    validate_error(res, "ERR_MISSING_AUTH")
