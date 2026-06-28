"""Role-based access control, ownership gating, authentication, optimistic
concurrency, and seat-ledger reconciliation on walk-in cancel.

Corner queue (B): rbac + cross_cutting_complexity_layers sections.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_customer_headers, TEST_USERS, ApiErrorId,
    create_studio, create_artist, create_customer,
    setup_open_event_with_customer, book_reservation, event_current_version,
    set_clock,
)

MANAGER = TEST_USERS["manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


# ─── rbac ───────────────────────────────────────────────────────────────────

def test_front_desk_cannot_create_event(api):
    """PRD §2.1: "When an authenticated caller attempts an operation their role is not
    permitted to perform, the request is rejected with ERR_FORBIDDEN (HTTP 403)."
    PRD §4: the POST /studio-ops/events row lists authorized roles "StudioManager,
    PlatformAdmin" (FrontDesk is not among them).

    Design: Corner/rbac/frontdesk_cannot_create_event
    """
    studio = create_studio(room_capacity_seats=10, name="RB1")
    resp = api.create_event({
        "studio_id": studio["id"], "title": "Nope", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T10:00:00Z", "end_utc": "2026-04-05T12:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_customer_cannot_cancel_others_reservation(api):
    """PRD §2.1: "A Customer may act only on reservations they own — paying,
    confirming, or cancelling another customer's reservation, or booking with a
    customer_id other than their own, is rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/customer_cannot_cancel_others_reservation
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer_a = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500, clock=None)
    customer_b = create_customer(email="rbb@x.com", full_name="RB B")
    res = book_reservation(event["id"], customer_a["id"], seats=1)

    # Customer B (own valid X-User-ID) tries to cancel A's reservation.
    resp = api.cancel_reservation(res["id"], make_customer_headers(customer_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_unauthenticated_missing_headers(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the
    known roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/unauthenticated_missing_headers
    """
    resp = api.list_studios({})  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ─── cross_cutting_complexity_layers (OCC + reconciliation) ─────────────────

def test_occ_correct_version_succeeds_and_bumps(api):
    """PRD §2.9: "If expected_event_version does not equal the event's current version
    at the moment the create is processed, the request is rejected with
    ERR_STALE_EVENT_VERSION."
    PRD §3.4: "The event's version is incremented by one as part of the create."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500, clock=None)
    ver = event_current_version(event["id"])
    resp = api.create_reservation({
        "event_id": event["id"], "customer_id": customer["id"],
        "booking_mode": "PUBLIC", "seats": 1, "expected_event_version": ver},
        make_customer_headers(customer["id"]))
    validate_success(resp, expected_status=201)
    after = get_success_data(api.get_event(event["id"], MANAGER))
    assert after["version"] == ver + 1, (
        f"create must bump event version {ver} -> {ver + 1}, got {after['version']}")


def test_occ_stale_version_rejected(api):
    """PRD §2.9: "A reservation-create request must carry expected_event_version ...
    If expected_event_version does not equal the event's current version at the moment
    the create is processed, the request is rejected with ERR_STALE_EVENT_VERSION
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500, clock=None)
    stale_ver = event_current_version(event["id"])
    ch = make_customer_headers(customer["id"])
    # First create succeeds and advances the event's version.
    validate_success(api.create_reservation({
        "event_id": event["id"], "customer_id": customer["id"],
        "booking_mode": "PUBLIC", "seats": 1, "expected_event_version": stale_ver}, ch),
        expected_status=201)
    # Second create still carrying the now-stale version is rejected.
    resp = api.create_reservation({
        "event_id": event["id"], "customer_id": customer["id"],
        "booking_mode": "PUBLIC", "seats": 1, "expected_event_version": stale_ver}, ch)
    validate_error(resp, ApiErrorId.ERR_STALE_EVENT_VERSION)


def test_walk_in_cancel_reconciles_seat_ledger(api):
    """PRD §3.7: "A walk-in begins REGISTERED and consumes seats immediately: the
    event's seat ledger is recomputed and, if the registration drives seats_available
    to 0, the event flips OPEN → FULL ... A walk-in may be cancelled, transitioning to
    CANCELLED, which releases its seats; the ledger is recomputed and the event flips
    FULL → OPEN if seats free up."

    Design: Corner/cross_cutting_complexity_layers/walkin_cancel_releases_seats_reconciliation
    """
    set_clock("2026-04-01T00:00:00Z")
    event, _customer = setup_open_event_with_customer(
        room_capacity_seats=4, seats_capacity=4, price_cents_per_seat=4500, clock=None)
    walk = get_success_data(api.create_walk_in(
        {"event_id": event["id"], "party_name": "Walkers", "party_size": 4}, FRONT_DESK))

    full = get_success_data(api.get_event(event["id"], MANAGER))
    assert full["walk_in_seats"] == 4
    assert full["seats_available"] == 0
    assert full["status"] == "FULL"

    get_success_data(api.cancel_walk_in(walk["id"], FRONT_DESK))
    after = get_success_data(api.get_event(event["id"], MANAGER))
    assert after["walk_in_seats"] == 0, "cancel releases walk-in seats"
    assert after["seats_available"] == 4
    assert after["status"] == "OPEN"
