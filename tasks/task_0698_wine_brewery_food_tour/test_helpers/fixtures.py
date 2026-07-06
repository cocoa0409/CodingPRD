"""Composite setup helpers.

Each test runs against a fresh, empty database (the harness restarts the server
before every test), so every fixture builds its preconditions from scratch using
only PRD-declared endpoints. Fixtures use get_success_data() (lenient) internally
so setup failures surface as clear "Setup failed" errors.

Identity threading: PartnerVenue and Guest are entity_backed roles. After a
fixture creates one, every ownership/identity-gated call uses
make_partner_venue_headers(venue["id"]) / make_guest_headers(guest["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_tour_product_payload, create_add_on_payload, create_vehicle_payload,
    create_partner_venue_payload, create_pickup_point_payload, create_guest_payload,
    create_departure_payload, create_stop_payload, create_venue_confirmation_payload,
    create_booking_payload,
)
from .test_users import (
    make_operator_headers, make_guide_headers,
    make_partner_venue_headers, make_guest_headers,
)

OP = make_operator_headers()
GUIDE = make_guide_headers()


# ---------------------------------------------------------------------------
# Atomic builders
# ---------------------------------------------------------------------------
def create_published_product(**overrides):
    """Create a product and publish it. Returns the published product dict."""
    prod = get_success_data(api_client.create_tour_product(
        create_tour_product_payload(**overrides), OP))
    get_success_data(api_client.publish_tour_product(prod["id"], OP))
    return get_success_data(api_client.get_tour_product(prod["id"], OP))


def create_vehicle(seat_capacity=12, **overrides):
    return get_success_data(api_client.create_vehicle(
        create_vehicle_payload(seat_capacity=seat_capacity, **overrides), OP))


def create_partner_venue(**overrides):
    return get_success_data(api_client.create_partner_venue(
        create_partner_venue_payload(**overrides), OP))


def create_pickup_point(**overrides):
    return get_success_data(api_client.create_pickup_point(
        create_pickup_point_payload(**overrides), OP))


def create_add_on(tour_product_id, **overrides):
    return get_success_data(api_client.create_add_on(
        create_add_on_payload(tour_product_id, **overrides), OP))


def create_guest(**overrides):
    """Register a guest (age unverified, waiver unsigned)."""
    return get_success_data(api_client.create_guest(create_guest_payload(**overrides), OP))


def create_cleared_guest(**overrides):
    """Register a guest, verify age, and sign the waiver. Returns guest dict
    with age_verified and waiver_signed both true."""
    guest = create_guest(**overrides)
    get_success_data(api_client.verify_age(guest["id"], OP))
    get_success_data(api_client.sign_waiver(guest["id"], make_guest_headers(guest["id"])))
    return get_success_data(api_client.get_guest(guest["id"], OP))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, OP))


# ---------------------------------------------------------------------------
# Tier 1/2: SCHEDULED departure setups
# ---------------------------------------------------------------------------
def setup_scheduled_departure(seat_capacity=12, is_private_charter=False,
                              product_overrides=None, departure_overrides=None):
    """PUBLISHED product + vehicle + pickup point + a SCHEDULED departure.
    Returns dict: product, vehicle, pickup, departure.
    """
    product = create_published_product(**(product_overrides or {}))
    vehicle = create_vehicle(seat_capacity=seat_capacity)
    pickup = create_pickup_point()
    dep_extra = dict(departure_overrides or {})
    if is_private_charter:
        dep_extra["is_private_charter"] = True
    departure = get_success_data(api_client.create_departure(
        create_departure_payload(product["id"], vehicle["id"], **dep_extra), OP))
    return {
        "product": product, "vehicle": vehicle, "pickup": pickup,
        "departure": departure,
    }


def setup_scheduled_departure_with_confirmed_stop(seat_capacity=12,
                                                  requested_headcount=6,
                                                  venue_overrides=None,
                                                  product_overrides=None):
    """SCHEDULED departure with one Stop whose VenueConfirmation is CONFIRMED.
    Returns dict: product, vehicle, pickup, venue, departure, stop, confirmation.
    """
    base = setup_scheduled_departure(seat_capacity=seat_capacity,
                                     product_overrides=product_overrides)
    venue = create_partner_venue(**(venue_overrides or {}))
    stop = get_success_data(api_client.create_stop(
        create_stop_payload(base["departure"]["id"], venue["id"]), OP))
    vc = get_success_data(api_client.create_venue_confirmation(
        create_venue_confirmation_payload(stop["id"],
                                          requested_headcount=requested_headcount), OP))
    get_success_data(api_client.confirm_venue_confirmation(
        vc["id"], make_partner_venue_headers(venue["id"])))
    base.update({
        "venue": venue, "stop": stop,
        "confirmation": get_success_data(
            api_client.get_venue_confirmation(vc["id"], OP)),
    })
    return base


def setup_requested_venue_confirmation(requested_headcount=8, venue_overrides=None):
    """SCHEDULED departure with one Stop and a REQUESTED VenueConfirmation
    (not yet confirmed). Returns dict: product, vehicle, venue, departure, stop,
    confirmation.
    """
    product = create_published_product()
    vehicle = create_vehicle()
    venue = create_partner_venue(**(venue_overrides or {}))
    departure = get_success_data(api_client.create_departure(
        create_departure_payload(product["id"], vehicle["id"]), OP))
    stop = get_success_data(api_client.create_stop(
        create_stop_payload(departure["id"], venue["id"]), OP))
    vc = get_success_data(api_client.create_venue_confirmation(
        create_venue_confirmation_payload(stop["id"],
                                          requested_headcount=requested_headcount), OP))
    return {
        "product": product, "vehicle": vehicle, "venue": venue,
        "departure": departure, "stop": stop, "confirmation": vc,
    }


# ---------------------------------------------------------------------------
# Tier 3: Booking lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_draft_booking(departure_id, pickup_id, party_size, lead_guest=None,
                         add_on_id=None, cleared=False, birth_date=None):
    """Create a guest (cleared or not) + a DRAFT booking. Returns (booking, guest)."""
    if lead_guest is None:
        guest_kwargs = {}
        if birth_date is not None:
            guest_kwargs["birth_date"] = birth_date
        lead_guest = create_cleared_guest(**guest_kwargs) if cleared \
            else create_guest(**guest_kwargs)
    booking = get_success_data(api_client.create_booking(
        create_booking_payload(departure_id, lead_guest["id"], pickup_id,
                               party_size, add_on_id=add_on_id),
        make_guest_headers(lead_guest["id"])))
    return booking, lead_guest


def reserve_booking(booking_id, departure_id, guest_id):
    """Reserve a DRAFT booking using the departure's CURRENT version. Returns
    the reserved booking dict."""
    dep = get_success_data(api_client.get_departure(departure_id, OP))
    return get_success_data(api_client.reserve_booking(
        booking_id, dep["version"], make_guest_headers(guest_id)))


def create_reserved_booking(departure_id, pickup_id, party_size, lead_guest=None,
                            add_on_id=None, cleared=False, birth_date=None):
    """Create + reserve a booking. Returns (booking, guest)."""
    booking, guest = create_draft_booking(
        departure_id, pickup_id, party_size, lead_guest=lead_guest,
        add_on_id=add_on_id, cleared=cleared, birth_date=birth_date)
    reserve_booking(booking["id"], departure_id, guest["id"])
    booking = get_success_data(api_client.get_booking(
        booking["id"], make_guest_headers(guest["id"])))
    return booking, guest


def create_paid_booking(departure_id, pickup_id, party_size, lead_guest=None,
                        add_on_id=None, birth_date=None):
    """Create a cleared guest + create + reserve + pay a booking. Returns
    (booking, guest). Guest is age-verified and waiver-signed."""
    booking, guest = create_reserved_booking(
        departure_id, pickup_id, party_size, lead_guest=lead_guest,
        add_on_id=add_on_id, cleared=True, birth_date=birth_date)
    get_success_data(api_client.pay_booking(booking["id"], make_guest_headers(guest["id"])))
    booking = get_success_data(api_client.get_booking(
        booking["id"], make_guest_headers(guest["id"])))
    return booking, guest


# ---------------------------------------------------------------------------
# Tier 4: Departure lifecycle shortcuts (confirm / depart / complete)
# ---------------------------------------------------------------------------
def setup_confirmed_departure(seat_capacity=12, party_size=4, add_on_id=None,
                              requested_headcount=None, venue_overrides=None,
                              product_overrides=None, paid=True):
    """Full chain to a CONFIRMED departure: product+van+pickup+venue, SCHEDULED
    departure with one CONFIRMED stop, one PAID (or RESERVED) booking, then
    confirm. Returns dict adding: booking, guest (plus all base setup keys).
    """
    rc = requested_headcount if requested_headcount is not None else party_size
    s = setup_scheduled_departure_with_confirmed_stop(
        seat_capacity=seat_capacity, requested_headcount=rc,
        venue_overrides=venue_overrides, product_overrides=product_overrides)
    if paid:
        booking, guest = create_paid_booking(
            s["departure"]["id"], s["pickup"]["id"], party_size, add_on_id=add_on_id)
    else:
        booking, guest = create_reserved_booking(
            s["departure"]["id"], s["pickup"]["id"], party_size,
            add_on_id=add_on_id, cleared=True)
    get_success_data(api_client.confirm_departure(s["departure"]["id"], OP))
    s["departure"] = get_success_data(api_client.get_departure(s["departure"]["id"], OP))
    s["booking"] = get_success_data(api_client.get_booking(
        booking["id"], make_guest_headers(guest["id"])))
    s["guest"] = guest
    return s


def setup_departed_departure(seat_capacity=12, party_size=4, add_on_id=None,
                             check_in=True):
    """CONFIRMED departure -> clock to depart_at -> DEPARTED (optionally the PAID
    booking is checked in). Returns dict with booking, guest, departure (DEPARTED).
    """
    s = setup_confirmed_departure(seat_capacity=seat_capacity, party_size=party_size,
                                  add_on_id=add_on_id, paid=True)
    set_clock(s["departure"]["depart_at"])
    get_success_data(api_client.depart_departure(s["departure"]["id"], GUIDE))
    if check_in:
        get_success_data(api_client.check_in_booking(s["booking"]["id"], GUIDE))
    s["departure"] = get_success_data(api_client.get_departure(s["departure"]["id"], OP))
    s["booking"] = get_success_data(api_client.get_booking(
        s["booking"]["id"], make_guest_headers(s["guest"]["id"])))
    return s


def setup_completed_departure(seat_capacity=12, party_size=4, add_on_id=None):
    """DEPARTED departure (booking CHECKED_IN) -> clock to return_at -> COMPLETED.
    Returns dict with booking (COMPLETED), guest, departure (COMPLETED), stop.
    """
    s = setup_departed_departure(seat_capacity=seat_capacity, party_size=party_size,
                                 add_on_id=add_on_id, check_in=True)
    set_clock(s["departure"]["return_at"])
    get_success_data(api_client.complete_departure(s["departure"]["id"], GUIDE))
    s["departure"] = get_success_data(api_client.get_departure(s["departure"]["id"], OP))
    s["booking"] = get_success_data(api_client.get_booking(
        s["booking"]["id"], make_guest_headers(s["guest"]["id"])))
    s["stop"] = get_success_data(api_client.get_stop(s["stop"]["id"], OP))
    return s


# ---------------------------------------------------------------------------
# Tier 5: Specialized targeting fixtures (mirrors specific design instances)
# ---------------------------------------------------------------------------
def setup_two_parallel_paid_departures(party_size=6, add_on_price=1500,
                                       requested_headcount=6):
    """Two parallel CONFIRMED departures (D_W, D_O), each with one CONFIRMED stop
    and one PAID booking party `party_size` with a cheese add-on. Shares one
    product + venue + pickup. Returns dict:
      product, addon, venue, pickup, dw, do, bw, bo (departures and bookings).
    Used for the dual-variant refund instance (weather full vs ops tiered).
    """
    product = create_published_product(gratuity_pct=0.18, charter_fee_cents=5000)
    addon = create_add_on(product["id"], name="Cheese", price_per_person_cents=add_on_price)
    venue = create_partner_venue(name="Oak", kind="WINERY",
                                 commission_pct=0.10, tasting_cost_per_guest_cents=1200)
    pickup = create_pickup_point()

    def build_confirmed(vehicle_label):
        vehicle = create_vehicle(seat_capacity=12, label=vehicle_label)
        departure = get_success_data(api_client.create_departure(
            create_departure_payload(product["id"], vehicle["id"]), OP))
        stop = get_success_data(api_client.create_stop(
            create_stop_payload(departure["id"], venue["id"]), OP))
        vc = get_success_data(api_client.create_venue_confirmation(
            create_venue_confirmation_payload(
                stop["id"], requested_headcount=requested_headcount), OP))
        get_success_data(api_client.confirm_venue_confirmation(
            vc["id"], make_partner_venue_headers(venue["id"])))
        booking, _ = create_paid_booking(departure["id"], pickup["id"], party_size,
                                         add_on_id=addon["id"])
        get_success_data(api_client.confirm_departure(departure["id"], OP))
        return departure, booking

    dw, bw = build_confirmed("VW")
    do, bo = build_confirmed("VO")
    return {
        "product": product, "addon": addon, "venue": venue, "pickup": pickup,
        "dw": get_success_data(api_client.get_departure(dw["id"], OP)),
        "do": get_success_data(api_client.get_departure(do["id"], OP)),
        "bw_id": bw["id"], "bo_id": bo["id"],
    }


def setup_venue_confirmation_at_revision(target_revisions=3):
    """Cycle a VenueConfirmation REQUESTED<->CHANGES_REQUESTED `target_revisions`
    times so revision_count == target_revisions and it ends in CHANGES_REQUESTED
    (after a final request-changes). Returns dict: venue, stop, confirmation.
    """
    s = setup_requested_venue_confirmation()
    vc_id = s["confirmation"]["id"]
    venue_headers = make_partner_venue_headers(s["venue"]["id"])
    for _ in range(target_revisions):
        get_success_data(api_client.request_changes_venue_confirmation(
            vc_id, "needs changes", venue_headers))
        get_success_data(api_client.resubmit_venue_confirmation(vc_id, 8, OP))
    # final request-changes to land back in CHANGES_REQUESTED at the limit
    get_success_data(api_client.request_changes_venue_confirmation(
        vc_id, "final", venue_headers))
    s["confirmation"] = get_success_data(api_client.get_venue_confirmation(vc_id, OP))
    return s
