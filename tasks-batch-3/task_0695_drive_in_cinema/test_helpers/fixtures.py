"""Composite setup helpers.

Each test runs against a fresh, empty database (the runner restarts the server before
every test), so every fixture builds its preconditions from scratch using only
PRD-declared endpoints. Fixtures use get_success_data() so setup failures surface clearly.

Role conventions (all roles opaque): operator/admin/gate X-User-IDs are arbitrary;
Patron X-User-ID must equal the patron_id stored on the owned resource for ownership-gated
calls — make_patron_headers(patron_id) enforces this.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_patron_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["venue_operator_headers"]
GATE = TEST_USERS["gate_attendant_headers"]


# -------------------------------------------------------------------------
# Clock control
# -------------------------------------------------------------------------
def set_clock(to_iso8601):
    """Set the server's logical clock."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# -------------------------------------------------------------------------
# Tier 1: Atomic catalog creators
# -------------------------------------------------------------------------
def create_venue(name="Test Drive-In", fm_channel_pool=None, **overrides):
    if fm_channel_pool is None:
        fm_channel_pool = ["87.9", "88.1", "88.3"]
    payload = {"name": name, "fm_channel_pool": fm_channel_pool}
    payload.update(overrides)
    return get_success_data(api_client.create_venue(payload, ADMIN))


def create_lot(venue_id, name="L", stall_count=10, person_capacity=100, **overrides):
    payload = {
        "venue_id": venue_id,
        "name": name,
        "stall_count": stall_count,
        "person_capacity": person_capacity,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_lot(payload, OPERATOR))


def create_film(title="F", runtime_minutes=100, rating="G"):
    payload = {"title": title, "runtime_minutes": runtime_minutes, "rating": rating}
    return get_success_data(api_client.create_film(payload, OPERATOR))


def create_concession_item(venue_id, name="Item", unit_price_cents=350, tax_rate=0.0, available=True):
    payload = {
        "venue_id": venue_id,
        "name": name,
        "unit_price_cents": unit_price_cents,
        "tax_rate": tax_rate,
        "available": available,
    }
    return get_success_data(api_client.create_concession_item(payload, OPERATOR))


def create_showtime(venue_id, lot_id, primary_film_id, start_utc, **overrides):
    payload = {
        "venue_id": venue_id,
        "lot_id": lot_id,
        "primary_film_id": primary_film_id,
        "is_double_feature": False,
        "start_utc": start_utc,
        "pricing_mode": "PER_CAR",
        "base_price_cents": 2000,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_showtime(payload, OPERATOR))


def create_season_pass(patron_id, valid_from_utc, valid_to_utc, tier="GOLD", max_redemptions=3):
    payload = {
        "patron_id": patron_id,
        "tier": tier,
        "max_redemptions": max_redemptions,
        "valid_from_utc": valid_from_utc,
        "valid_to_utc": valid_to_utc,
    }
    return get_success_data(api_client.create_season_pass(payload, OPERATOR))


def create_private_rental(venue_id, lot_id, organizer_id, start_utc, end_utc,
                          flat_venue_fee_cents=100000, per_hour_cents=10000):
    payload = {
        "venue_id": venue_id,
        "lot_id": lot_id,
        "organizer_id": organizer_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "flat_venue_fee_cents": flat_venue_fee_cents,
        "per_hour_cents": per_hour_cents,
    }
    return get_success_data(api_client.create_private_rental(payload, OPERATOR))


# -------------------------------------------------------------------------
# Tier 2: Venue + lot + film base scenarios
# -------------------------------------------------------------------------
def setup_venue_lot_film(clock="2026-06-01T00:00:00Z", fm_channel_pool=None,
                         stall_count=10, person_capacity=100, runtime_minutes=100,
                         venue_overrides=None):
    """Base scenario: one venue, one lot, one film, clock set.
    Returns (venue, lot, film)."""
    venue_kw = venue_overrides or {}
    venue = create_venue(fm_channel_pool=fm_channel_pool, **venue_kw)
    lot = create_lot(venue["id"], stall_count=stall_count, person_capacity=person_capacity)
    film = create_film(runtime_minutes=runtime_minutes)
    if clock is not None:
        set_clock(clock)
    return venue, lot, film


def setup_scheduled_showtime(clock="2026-06-01T00:00:00Z", start_utc="2026-07-20T02:00:00Z",
                             fm_channel_pool=None, stall_count=10, person_capacity=100,
                             runtime_minutes=100, venue_overrides=None, showtime_overrides=None):
    """Venue + lot + film + a SCHEDULED PER_CAR showtime.
    Returns (venue, lot, film, showtime)."""
    venue, lot, film = setup_venue_lot_film(
        clock=clock, fm_channel_pool=fm_channel_pool, stall_count=stall_count,
        person_capacity=person_capacity, runtime_minutes=runtime_minutes,
        venue_overrides=venue_overrides,
    )
    st_kw = showtime_overrides or {}
    showtime = create_showtime(venue["id"], lot["id"], film["id"], start_utc, **st_kw)
    return venue, lot, film, showtime


def setup_double_feature_showtime(clock="2026-06-01T00:00:00Z", start_utc="2026-07-20T02:00:00Z",
                                  pricing_mode="PER_CAR", base_price_cents=2000,
                                  included_occupants=2, per_extra_person_cents=600,
                                  double_feature_surcharge_cents=1500,
                                  stall_count=10, person_capacity=200, runtime_minutes=90):
    """Venue + lot + two films + a SCHEDULED double-feature showtime.
    Returns (venue, lot, film1, film2, showtime)."""
    venue = create_venue()
    lot = create_lot(venue["id"], stall_count=stall_count, person_capacity=person_capacity)
    film1 = create_film(title="F1", runtime_minutes=runtime_minutes, rating="PG")
    film2 = create_film(title="F2", runtime_minutes=runtime_minutes, rating="PG")
    if clock is not None:
        set_clock(clock)
    overrides = {
        "secondary_film_id": film2["id"],
        "is_double_feature": True,
        "pricing_mode": pricing_mode,
        "base_price_cents": base_price_cents,
        "double_feature_surcharge_cents": double_feature_surcharge_cents,
    }
    if pricing_mode == "PER_CAR":
        overrides["included_occupants"] = included_occupants
        overrides["per_extra_person_cents"] = per_extra_person_cents
    showtime = create_showtime(venue["id"], lot["id"], film1["id"], start_utc, **overrides)
    return venue, lot, film1, film2, showtime


# -------------------------------------------------------------------------
# Tier 3: Reservation lifecycle shortcuts
# -------------------------------------------------------------------------
def make_reservation(showtime, patron_id, occupant_count=2, **overrides):
    """Create a CONFIRMED/UNPAID reservation against a showtime, OCC-checking the
    showtime's current version. Returns the reservation data."""
    payload = {
        "showtime_id": showtime["id"],
        "patron_id": patron_id,
        "occupant_count": occupant_count,
        "expected_showtime_version": showtime["version"],
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_reservation(payload, make_patron_headers(patron_id))
    )


def create_paid_reservation(showtime, patron_id, occupant_count=2, **overrides):
    """Create + pay a reservation. Returns the reservation after payment (PAID)."""
    resv = make_reservation(showtime, patron_id, occupant_count=occupant_count, **overrides)
    paid = get_success_data(
        api_client.pay_reservation(resv["id"], make_patron_headers(patron_id))
    )
    return paid


def create_checked_in_reservation(showtime, patron_id, occupant_count=2, **overrides):
    """Create + pay + check-in a reservation. Caller must have set the clock into the
    check-in window. Returns the reservation after check-in (CHECKED_IN)."""
    paid = create_paid_reservation(showtime, patron_id, occupant_count=occupant_count, **overrides)
    checked_in = get_success_data(api_client.check_in_reservation(paid["id"], GATE))
    return checked_in


def create_scanned_reservation(showtime, patron_id, occupant_count=2, **overrides):
    """Create + pay + check-in + scan a reservation. Returns the reservation after scan
    (SCANNED). Caller must have set the clock into the check-in window."""
    resv = make_reservation(showtime, patron_id, occupant_count=occupant_count, **overrides)
    gate_code = resv["gate_code"]
    get_success_data(api_client.pay_reservation(resv["id"], make_patron_headers(patron_id)))
    get_success_data(api_client.check_in_reservation(resv["id"], GATE))
    scanned = get_success_data(api_client.scan_reservation(resv["id"], gate_code, GATE))
    return scanned


# -------------------------------------------------------------------------
# Tier 4: Concession order shortcuts
# -------------------------------------------------------------------------
def create_concession_order(reservation_id, patron_id, lines):
    """Create a concession pre-order on a reservation. Returns the order data."""
    return get_success_data(
        api_client.create_concession_order(
            reservation_id, {"lines": lines}, make_patron_headers(patron_id)
        )
    )


def create_paid_concession_order(reservation_id, patron_id, lines):
    """Create + pay a concession order. Returns the order after payment (PAID)."""
    order = create_concession_order(reservation_id, patron_id, lines)
    paid = get_success_data(
        api_client.pay_concession_order(order["id"], make_patron_headers(patron_id))
    )
    return paid


def standard_concession_lines(venue_id):
    """Three concession items (Popcorn 350@7.25%, Combo 1250@7.25%, Water 199@0%) and a
    3-line order (qty 3/1/2) totalling 3000c. Returns (lines, item_ids)."""
    pop = create_concession_item(venue_id, name="Popcorn", unit_price_cents=350, tax_rate=0.0725)
    combo = create_concession_item(venue_id, name="Combo", unit_price_cents=1250, tax_rate=0.0725)
    water = create_concession_item(venue_id, name="Water", unit_price_cents=199, tax_rate=0.0)
    lines = [
        {"concession_item_id": pop["id"], "qty": 3},
        {"concession_item_id": combo["id"], "qty": 1},
        {"concession_item_id": water["id"], "qty": 2},
    ]
    return lines, {"pop": pop["id"], "combo": combo["id"], "water": water["id"]}


# -------------------------------------------------------------------------
# Tier 5: Private rental shortcuts
# -------------------------------------------------------------------------
def create_approved_rental(venue_id, lot_id, organizer_id, start_utc, end_utc, **overrides):
    """Create + approve a private rental on an otherwise-free lot. Returns the approved
    rental data."""
    rental = create_private_rental(venue_id, lot_id, organizer_id, start_utc, end_utc, **overrides)
    approved = get_success_data(
        api_client.approve_private_rental(rental["id"], rental["version"], OPERATOR)
    )
    return approved


# -------------------------------------------------------------------------
# Helpers for refund-record lookup
# -------------------------------------------------------------------------
def list_refunds_for_reservation(reservation_id, headers=None):
    """Return the list of refund records attributed to a reservation."""
    h = headers or OPERATOR
    resp = api_client.list_refund_records(h, params={"reservation_id": reservation_id})
    body = resp.json()
    return body["data"]


def list_refunds_for_order(order_id, headers=None):
    """Return the list of refund records attributed to a concession order."""
    h = headers or OPERATOR
    resp = api_client.list_refund_records(h, params={"concession_order_id": order_id})
    body = resp.json()
    return body["data"]
