"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Renter calls are entity-backed by the Renter resource, so
every ownership-gated call uses make_renter_headers(renter["id"]) built from
the real entity id — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import orientation_items_for
from .factories import (
    cancel_booking_payload,
    checkout_payload,
    countersign_payload,
    create_booking_payload,
    create_certificate_payload,
    create_geo_zone_payload,
    create_maintenance_window_payload,
    create_renter_payload,
    create_season_rate_payload,
    create_vessel_payload,
    create_weather_advisory_payload,
    itinerary_payload,
    modify_booking_payload,
    report_incident_payload,
    resolve_incident_payload,
    return_payload,
    sign_item_payload,
    waypoint,
)
from .test_users import TEST_USERS, make_renter_headers

FM = TEST_USERS["fleet_manager_headers"]
DS = TEST_USERS["dock_staff_headers"]
MECH = TEST_USERS["mechanic_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation helpers
# ---------------------------------------------------------------------------

def create_vessel(name="Test Vessel", size_class="COMPACT_36", berth_count=6,
                  home_marina="Wahweap", fuel_tank_capacity_gallons=150):
    """Register a vessel (born AVAILABLE). Returns the vessel."""
    payload = create_vessel_payload(
        name=name, size_class=size_class, berth_count=berth_count,
        home_marina=home_marina, fuel_tank_capacity_gallons=fuel_tank_capacity_gallons,
    )
    return get_success_data(api_client.create_vessel(payload, FM))


def create_season_rate(size_class="COMPACT_36", season="PEAK",
                       start_date="2026-06-01", end_date="2026-08-31",
                       nightly_rate_cents=45000, weekly_discount_pct=10):
    """Create a closed-interval season rate window. Returns the rate."""
    payload = create_season_rate_payload(
        size_class=size_class, season=season, start_date=start_date,
        end_date=end_date, nightly_rate_cents=nightly_rate_cents,
        weekly_discount_pct=weekly_discount_pct,
    )
    return get_success_data(api_client.create_season_rate(payload, FM))


def create_geo_zone(zone_code="ZP-TEST", name="Test Zone", max_vessels_per_night=5,
                    allowed_size_classes=None):
    """Create a cruising zone. Returns the zone."""
    payload = create_geo_zone_payload(
        zone_code=zone_code, name=name,
        max_vessels_per_night=max_vessels_per_night,
        allowed_size_classes=list(allowed_size_classes)
        if allowed_size_classes is not None
        else ["COMPACT_36", "STANDARD_44", "LUXE_56"],
    )
    return get_success_data(api_client.create_geo_zone(payload, FM))


def create_maintenance_window(vessel_id, start_date, end_date, reason=None):
    """Schedule a maintenance window (closed interval). Returns the window."""
    payload = create_maintenance_window_payload(start_date=start_date,
                                                end_date=end_date)
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.create_maintenance_window(vessel_id, payload, FM))


def create_weather_advisory(severity, zone_ids, window_start, window_end):
    """Issue a weather advisory (born ACTIVE). Returns the advisory."""
    payload = create_weather_advisory_payload(
        severity=severity, zone_ids=list(zone_ids),
        window_start=window_start, window_end=window_end,
    )
    return get_success_data(api_client.create_weather_advisory(payload, FM))


def register_renter(full_name="Test Renter", email="renter@example.com",
                    date_of_birth="1990-01-01"):
    """Self-register a renter (born UNVERIFIED, risk scores 0, multiplier 1.0).

    Returns (renter, renter_headers) with the headers threaded to the real
    Renter id for all subsequent ownership-gated calls.
    """
    payload = create_renter_payload(full_name=full_name, email=email,
                                    date_of_birth=date_of_birth)
    renter = get_success_data(api_client.create_renter(payload, TEST_USERS["renter_headers"]))
    return renter, make_renter_headers(renter["id"])


def submit_certificate(renter, renter_headers, cert_number="CERT-0001",
                       issuing_authority="NASBLA", issued_on="2026-01-15",
                       expires_on="2027-06-30"):
    """Submit a boating-safety certificate (born SUBMITTED). Returns it."""
    payload = create_certificate_payload(
        cert_number=cert_number, issuing_authority=issuing_authority,
        issued_on=issued_on, expires_on=expires_on,
    )
    return get_success_data(
        api_client.submit_certificate(renter["id"], payload, renter_headers))


def verify_certificate(cert_id, headers=None):
    """DockStaff VERIFY decision on a SUBMITTED certificate. Returns it."""
    return get_success_data(
        api_client.decide_certificate(cert_id, {"decision": "VERIFY"}, headers or DS))


def create_qualified_renter(full_name="Test Renter", email="renter@example.com",
                            date_of_birth="1990-01-01", cert_number="CERT-0001",
                            issuing_authority="NASBLA", cert_issued_on="2026-01-15",
                            cert_expires_on="2027-06-30"):
    """Renter + certificate submitted and VERIFIED -> renter QUALIFIED.

    Returns (renter, renter_headers, certificate).
    """
    renter, headers = register_renter(full_name=full_name, email=email,
                                      date_of_birth=date_of_birth)
    cert = submit_certificate(renter, headers, cert_number=cert_number,
                              issuing_authority=issuing_authority,
                              issued_on=cert_issued_on, expires_on=cert_expires_on)
    cert = verify_certificate(cert["id"])
    return renter, headers, cert


def set_clock(to_iso8601):
    """Advance the logical clock and run the deterministic sweep."""
    return get_success_data(api_client.set_clock(to_iso8601, FM))


# ---------------------------------------------------------------------------
# Tier 1: booking lifecycle primitives
# ---------------------------------------------------------------------------

def create_booking(vessel_id, renter, renter_headers, start_date="2026-08-20",
                   end_date="2026-08-22", party_size=2, **extra):
    """Create a booking (born HELD with computed quote and deposit snapshot)."""
    payload = create_booking_payload(vessel_id, renter["id"],
                                     start_date=start_date, end_date=end_date,
                                     party_size=party_size, **extra)
    return get_success_data(api_client.create_booking(payload, renter_headers))


def confirm_booking(booking_id, renter_headers):
    """HELD -> CONFIRMED (pins quote, posts RENTAL, holds deposit, creates
    the orientation item set and the cleaning turn)."""
    return get_success_data(api_client.confirm_booking(booking_id, renter_headers))


def put_itinerary(booking_id, renter_headers, waypoints):
    """Submit/replace the itinerary (created APPROVED on full validity)."""
    return get_success_data(
        api_client.put_itinerary(booking_id, itinerary_payload(waypoints),
                                 renter_headers))


def sign_orientation_item(booking_id, renter_headers, item_code):
    return get_success_data(api_client.sign_orientation_item(
        booking_id, sign_item_payload(item_code), renter_headers))


def sign_all_orientation_items(booking_id, renter_headers, size_class):
    """Sign every item of the size-class set; the final sign moves the
    orientation IN_PROGRESS -> COMPLETED. Returns the updated booking."""
    booking = None
    for item_code in orientation_items_for(size_class):
        booking = sign_orientation_item(booking_id, renter_headers, item_code)
    return booking


def countersign_orientation(booking_id, approved=True, item_code=None):
    """DockStaff countersign (COMPLETED -> COUNTERSIGNED) or item rejection
    (COMPLETED -> IN_PROGRESS with the named item unsigned)."""
    return get_success_data(api_client.countersign_orientation(
        booking_id, countersign_payload(approved=approved, item_code=item_code), DS))


def checkout_booking(booking_id, fuel_gauge_percent=100, pump_out_done=True):
    """DockStaff checkout: CONFIRMED -> CHECKED_OUT, settlement -> PROVISIONAL."""
    return get_success_data(api_client.checkout_booking(
        booking_id, checkout_payload(fuel_gauge_percent, pump_out_done), DS))


def return_booking(booking_id, actual_return_at, fuel_gauge_percent=100,
                   pump_out_done=True):
    """DockStaff return: CHECKED_OUT/INTERRUPTED -> RETURNED; the booking's
    SCHEDULED cleaning turn starts (IN_PROGRESS)."""
    return get_success_data(api_client.return_booking(
        booking_id,
        return_payload(actual_return_at, fuel_gauge_percent, pump_out_done), DS))


def settle_booking(booking_id):
    """DockStaff settle: RETURNED -> CLOSED with the FINAL settlement and the
    deposit waterfall."""
    return get_success_data(api_client.settle_booking(booking_id, DS))


def list_cleaning_turns(booking_id):
    return get_success_data(api_client.list_cleaning_turns(booking_id, DS))


def get_single_turn(booking_id):
    turns = list_cleaning_turns(booking_id)
    assert len(turns) == 1, f"expected exactly one cleaning turn, got {turns!r}"
    return turns[0]


def inspect_turn(turn_id, passed):
    return get_success_data(
        api_client.inspect_cleaning_turn(turn_id, {"passed": passed}, DS))


def report_incident(booking_id, renter_headers, incident_type, occurred_at,
                    description=None):
    return get_success_data(api_client.report_incident(
        booking_id, report_incident_payload(incident_type, occurred_at, description),
        renter_headers))


def resolve_incident(incident_id, resolution, severity=None, downtime_days=None,
                     assessed_damage_cents=None):
    return get_success_data(api_client.resolve_incident(
        incident_id,
        resolve_incident_payload(resolution, severity=severity,
                                 downtime_days=downtime_days,
                                 assessed_damage_cents=assessed_damage_cents),
        MECH))


def get_booking(booking_id):
    return get_success_data(api_client.get_booking(booking_id, DS))


def get_renter(renter_id):
    return get_success_data(api_client.get_renter(renter_id, FM))


def get_vessel(vessel_id):
    return get_success_data(api_client.get_vessel(vessel_id, FM))


def list_charges(booking_id):
    return get_success_data(api_client.list_charges(booking_id, DS))


def list_itineraries(booking_id):
    return get_success_data(api_client.list_itineraries(booking_id, DS))


def list_maintenance_windows(vessel_id):
    return get_success_data(api_client.list_maintenance_windows(vessel_id, FM))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — fleet + qualified renter + booking
# ---------------------------------------------------------------------------

def setup_fleet_with_rate(size_class="COMPACT_36", tank=150, berth=6,
                          name="Test Vessel",
                          rate_start="2026-06-01", rate_end="2026-08-31",
                          nightly_rate_cents=None, weekly_discount_pct=10,
                          season="PEAK"):
    """One vessel plus one covering season-rate window. Returns the vessel.

    The nightly rate defaults per size class, mirroring the per-class default
    convention of setup_confirmed_booking.
    """
    if nightly_rate_cents is None:
        nightly_rate_cents = {
            "COMPACT_36": 45000,
            "STANDARD_44": 65000,
            "LUXE_56": 90000,
        }[size_class]
    vessel = create_vessel(name=name, size_class=size_class, berth_count=berth,
                           fuel_tank_capacity_gallons=tank)
    create_season_rate(size_class=size_class, season=season,
                       start_date=rate_start, end_date=rate_end,
                       nightly_rate_cents=nightly_rate_cents,
                       weekly_discount_pct=weekly_discount_pct)
    return vessel


def setup_confirmed_booking(size_class="COMPACT_36", tank=150, berth=6,
                            vessel_name="Test Vessel",
                            rates=None,
                            start_date="2026-08-20", end_date="2026-08-22",
                            party_size=2,
                            renter_name="Test Renter", renter_email="renter@example.com",
                            cert_expires_on="2027-06-30",
                            cert_issued_on="2026-01-15",
                            with_itinerary=False, zone_code="ZP-TEST",
                            zone_cap=5, zone_classes=None,
                            itinerary_night=None,
                            countersign=False):
    """Fleet + qualified renter + booking walked to CONFIRMED.

    `rates` is a list of (season, start, end, nightly_rate_cents, weekly_pct)
    tuples; defaults to one PEAK window 2026-06-01..2026-08-31 priced by the
    COMPACT default. Optionally adds a zone + APPROVED itinerary and/or the
    full orientation countersignature. Returns a context dict.
    """
    rate_rows = rates or [("PEAK", "2026-06-01", "2026-08-31",
                           {  # per-class default nightly price
                               "COMPACT_36": 45000,
                               "STANDARD_44": 65000,
                               "LUXE_56": 90000,
                           }[size_class], 10)]
    vessel = create_vessel(name=vessel_name, size_class=size_class,
                           berth_count=berth, fuel_tank_capacity_gallons=tank)
    for (season, rs, re_, price, pct) in rate_rows:
        create_season_rate(size_class=size_class, season=season, start_date=rs,
                           end_date=re_, nightly_rate_cents=price,
                           weekly_discount_pct=pct)
    renter, headers, cert = create_qualified_renter(
        full_name=renter_name, email=renter_email, cert_expires_on=cert_expires_on,
        cert_issued_on=cert_issued_on)
    booking = create_booking(vessel["id"], renter, headers,
                             start_date=start_date, end_date=end_date,
                             party_size=party_size)
    booking = confirm_booking(booking["id"], headers)

    zone = None
    itinerary = None
    if with_itinerary:
        zone = create_geo_zone(zone_code=zone_code, name=f"{zone_code} Bay",
                               max_vessels_per_night=zone_cap,
                               allowed_size_classes=zone_classes)
        itinerary = put_itinerary(
            booking["id"], headers,
            [waypoint(zone["id"], itinerary_night or start_date)])

    if countersign:
        booking = sign_all_orientation_items(booking["id"], headers, size_class)
        booking = countersign_orientation(booking["id"], approved=True)

    return {
        "vessel": vessel,
        "renter": renter,
        "renter_headers": headers,
        "cert": cert,
        "booking": booking,
        "zone": zone,
        "itinerary": itinerary,
        "size_class": size_class,
        "start_date": start_date,
        "end_date": end_date,
    }


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_checked_out_booking(checkout_clock=None, checkout_fuel=100,
                              checkout_pump=True, **kwargs):
    """CONFIRMED + itinerary + countersigned orientation, then checkout on the
    booking's start day: lifecycle CHECKED_OUT, settlement PROVISIONAL.

    Defaults the clock to start_dateT09:00:00Z (a legal checkout instant).
    Extra keyword arguments pass through to setup_confirmed_booking.
    """
    kwargs.setdefault("with_itinerary", True)
    kwargs.setdefault("countersign", True)
    ctx = setup_confirmed_booking(**kwargs)
    clock = checkout_clock or f"{ctx['start_date']}T09:00:00Z"
    set_clock(clock)
    ctx["booking"] = checkout_booking(ctx["booking"]["id"],
                                      fuel_gauge_percent=checkout_fuel,
                                      pump_out_done=checkout_pump)
    ctx["checkout_clock"] = clock
    return ctx


def setup_returned_booking(return_at=None, return_fuel=100, return_pump=True,
                           **kwargs):
    """Checked-out booking then returned: lifecycle RETURNED and the
    booking's cleaning turn IN_PROGRESS. Returns the context dict."""
    ctx = setup_checked_out_booking(**kwargs)
    actual = return_at or f"{ctx['end_date']}T09:00:00Z"
    ctx["booking"] = return_booking(ctx["booking"]["id"], actual,
                                    fuel_gauge_percent=return_fuel,
                                    pump_out_done=return_pump)
    ctx["return_at"] = actual
    ctx["turn"] = get_single_turn(ctx["booking"]["id"])
    return ctx


def inspect_turn_and_settle(ctx, passed=True):
    """Inspect the in-progress turn (default pass -> COMPLETED) and settle.
    Returns (settled_booking, charges)."""
    if passed:
        inspect_turn(ctx["turn"]["id"], True)
    settled = settle_booking(ctx["booking"]["id"])
    return settled, list_charges(ctx["booking"]["id"])


def cancel_booking(booking_id, renter_headers, reason=None):
    """OCC-guarded renter cancel using the booking's current version."""
    current = get_booking(booking_id)
    return get_success_data(api_client.cancel_booking(
        booking_id,
        cancel_booking_payload(current["version"], reason=reason),
        renter_headers))


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def _complete_charter_with_grounding(vessel_id, zone_id, renter, headers,
                                     size_class, start_date, end_date,
                                     checkout_clock, incident_at, report_clock,
                                     severity):
    """Drive one booking through confirm -> checkout -> GROUNDING incident
    resolved -> return -> turn pass -> settle. Returns the booking id."""
    booking = create_booking(vessel_id, renter, headers,
                             start_date=start_date, end_date=end_date,
                             party_size=2)
    booking = confirm_booking(booking["id"], headers)
    put_itinerary(booking["id"], headers, [waypoint(zone_id, start_date)])
    sign_all_orientation_items(booking["id"], headers, size_class)
    countersign_orientation(booking["id"], approved=True)
    set_clock(checkout_clock)
    checkout_booking(booking["id"], fuel_gauge_percent=100, pump_out_done=True)
    set_clock(report_clock)
    incident = report_incident(booking["id"], headers, "GROUNDING", incident_at)
    resolve_incident(incident["id"], "GROUNDING_CONFIRMED", severity=severity)
    return_booking(booking["id"], f"{end_date}T09:00:00Z",
                   fuel_gauge_percent=100, pump_out_done=True)
    turn = get_single_turn(booking["id"])
    inspect_turn(turn["id"], True)
    settle_booking(booking["id"])
    return booking["id"]


def setup_renter_with_two_resolved_groundings():
    """Build a renter with two resolved groundings on closed charters:

    - an old MAJOR grounding (occurred 2024-06-12, weight 25) that has aged out
      of the rolling 24-month window at the 2026-08-01 evaluation date, and
    - a recent MINOR grounding (occurred 2026-07-06, weight 10).

    Leaves the logical clock at 2026-08-01T00:00:00Z. Returns a context dict
    with the renter, threaded headers, and the vessel.
    """
    set_clock("2024-06-01T00:00:00Z")
    vessel = create_vessel(name="Compact Risk", size_class="COMPACT_36",
                           berth_count=6, fuel_tank_capacity_gallons=150)
    create_season_rate(size_class="COMPACT_36", season="PEAK",
                       start_date="2024-06-01", end_date="2024-08-31",
                       nightly_rate_cents=45000, weekly_discount_pct=10)
    create_season_rate(size_class="COMPACT_36", season="PEAK",
                       start_date="2026-06-01", end_date="2026-08-31",
                       nightly_rate_cents=45000, weekly_discount_pct=10)
    zone = create_geo_zone(zone_code="ZP-DANGLING", name="Dangling Rope",
                           max_vessels_per_night=5)
    renter, headers = register_renter(full_name="Rio Risk", email="rio@x.com",
                                      date_of_birth="1979-11-20")
    cert = submit_certificate(renter, headers, cert_number="C-200",
                              issuing_authority="USCG", issued_on="2024-01-10",
                              expires_on="2027-01-15")
    verify_certificate(cert["id"])

    _complete_charter_with_grounding(
        vessel["id"], zone["id"], renter, headers, "COMPACT_36",
        start_date="2024-06-10", end_date="2024-06-13",
        checkout_clock="2024-06-10T09:00:00Z",
        incident_at="2024-06-12T10:00:00Z",
        report_clock="2024-06-12T12:00:00Z",
        severity="MAJOR")

    set_clock("2026-07-01T00:00:00Z")
    _complete_charter_with_grounding(
        vessel["id"], zone["id"], renter, headers, "COMPACT_36",
        start_date="2026-07-05", end_date="2026-07-08",
        checkout_clock="2026-07-05T09:00:00Z",
        incident_at="2026-07-06T10:00:00Z",
        report_clock="2026-07-06T12:00:00Z",
        severity="MINOR")

    set_clock("2026-08-01T00:00:00Z")
    return {"renter": renter, "renter_headers": headers, "vessel": vessel,
            "zone": zone}
