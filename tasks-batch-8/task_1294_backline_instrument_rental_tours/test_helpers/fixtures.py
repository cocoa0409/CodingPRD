"""Composite setup helpers: multi-step flows so tests focus on assertions.

Every helper builds preconditions from scratch against a fresh server (the
runner restarts it before each test) using only PRD-declared endpoints, and
uses get_success_data() so setup failures surface as clear "Setup failed"
errors rather than confusing assertion failures.
"""
from datetime import date, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_artist_payload, create_tour_payload, create_tour_stop_payload,
    create_rider_line_payload, create_gear_model_payload, create_gear_unit_payload,
    create_source_payload, create_shipment_payload, create_shipment_line_payload,
    create_flight_case_payload, create_partner_vendor_payload,
)
from .test_users import TEST_USERS, make_vendor_rep_headers

OPS = TEST_USERS["ops_manager_headers"]
OPS_B = TEST_USERS["ops_manager_b_headers"]
TM = TEST_USERS["tour_manager_headers"]
LC = TEST_USERS["logistics_headers"]
WT = TEST_USERS["warehouse_tech_headers"]


# ---------------------------------------------------------------------------
# Single-entity helpers
# ---------------------------------------------------------------------------

def create_artist(headers=OPS, topup_cents=None, **overrides):
    """Register an artist, optionally posting a deposit top-up."""
    artist = get_success_data(api_client.create_artist(create_artist_payload(**overrides), headers))
    if topup_cents:
        get_success_data(api_client.create_deposit_topup(artist["id"], {"amount_cents": topup_cents}, OPS))
    return artist


def get_artist(artist_id, headers=OPS):
    return get_success_data(api_client.get_artist(artist_id, headers))


def create_gear_model(headers=OPS, **overrides):
    return get_success_data(api_client.create_gear_model(create_gear_model_payload(**overrides), headers))


def create_gear_unit(model_id, headers=OPS, **overrides):
    return get_success_data(api_client.create_gear_unit(create_gear_unit_payload(model_id, **overrides), headers))


def create_tour(artist_id, headers=TM, **overrides):
    return get_success_data(api_client.create_tour(create_tour_payload(artist_id, **overrides), headers))


def add_stop(tour_id, headers=TM, **overrides):
    return get_success_data(api_client.create_tour_stop(tour_id, create_tour_stop_payload(**overrides), headers))


def add_rider_line(stop_id, model_id, headers=TM, **overrides):
    return get_success_data(api_client.create_rider_line(stop_id, create_rider_line_payload(model_id, **overrides), headers))


def activate_tour(tour_id, headers=TM):
    """Activate with a fresh OCC version read."""
    tour = get_success_data(api_client.get_tour(tour_id, headers))
    return get_success_data(api_client.activate_tour(tour_id, {"expected_tour_version": tour["version"]}, headers))


def source_line(line_id, headers=LC, **overrides):
    """Source a rider line. Returns the created ReservationLine."""
    return get_success_data(api_client.source_rider_line(line_id, create_source_payload(**overrides), headers))


def get_reservation(reservation_id, headers=TM):
    return get_success_data(api_client.get_reservation_line(reservation_id, headers))


def get_unit(unit_id, headers=OPS):
    return get_success_data(api_client.get_gear_unit(unit_id, headers))


def get_stop(stop_id, headers=TM):
    return get_success_data(api_client.get_tour_stop(stop_id, headers))


def get_tour(tour_id, headers=TM):
    return get_success_data(api_client.get_tour(tour_id, headers))


def get_line(line_id, headers=TM):
    return get_success_data(api_client.get_rider_line(line_id, headers))


def find_claim_for_reservation(reservation_id, headers=OPS):
    claims = get_success_data(api_client.list_damage_claims(
        headers, params={"reservation_line_id": reservation_id}))
    return claims[0]


def find_cross_request_for_reservation(reservation_id, headers=LC):
    reqs = get_success_data(api_client.list_cross_rental_requests(
        headers, params={"reservation_line_id": reservation_id}))
    return reqs[0]


def find_ticket_for_unit(unit_id, headers=WT):
    tickets = get_success_data(api_client.list_maintenance_tickets(
        headers, params={"gear_unit_id": unit_id}))
    return tickets[0]


# ---------------------------------------------------------------------------
# Hierarchy + lifecycle composites
# ---------------------------------------------------------------------------

def setup_tour_with_sourced_line(artist=None, model=None, unit=None,
                                 city="LAX", stop_city=None,
                                 start_date="2026-08-09T00:00:00Z",
                                 end_date="2026-08-11T00:00:00Z",
                                 venue_date="2026-08-10T00:00:00Z",
                                 activate=True, artist_overrides=None,
                                 model_overrides=None, topup_cents=None,
                                 insurance_policy_id="POL-FIXTURE",
                                 tour_overrides=None):
    """Artist + model + unit + tour + stop + rider line, then source it.

    Returns dict(artist, model, unit, tour, stop, line, reservation).
    Sourcing happens while the tour is DRAFT (PRD §3.3 requires only that the
    stop be PLANNED). Activation, when requested, happens after sourcing.
    """
    stop_city = stop_city or city
    artist = artist or create_artist(topup_cents=topup_cents, **(artist_overrides or {}))
    model = model or create_gear_model(**(model_overrides or {}))
    unit = unit or create_gear_unit(model["id"], home_city_code=city)
    tour_kwargs = dict(tour_overrides or {})
    if insurance_policy_id is not None:
        tour_kwargs["insurance_policy_id"] = insurance_policy_id
    tour = create_tour(artist["id"], **tour_kwargs)
    stop = add_stop(tour["id"], city_code=stop_city, venue_date=venue_date,
                    load_in_ts=venue_date.replace("T00:00:00Z", "T10:00:00Z"))
    line = add_rider_line(stop["id"], model["id"])
    reservation = source_line(line["id"], origin_city_code=city, dest_city_code=stop_city,
                              start_date=start_date, end_date=end_date)
    if activate:
        tour = activate_tour(tour["id"])
    return dict(artist=get_artist(artist["id"]), model=model, unit=get_unit(unit["id"]),
                tour=tour, stop=stop, line=line, reservation=reservation)


def create_shipment_with_line(tour_id, unit_id, from_city="LAX", to_city="LAX",
                              ship_date="2026-08-09T00:00:00Z", capacity_kg=1000,
                              weight_kg=10, labor_minutes=10, **line_overrides):
    """Create a cartage leg plus one booked line. Returns (shipment, line)."""
    shipment = get_success_data(api_client.create_shipment(
        create_shipment_payload(tour_id, from_city_code=from_city, to_city_code=to_city,
                                ship_date=ship_date, capacity_kg=capacity_kg), LC))
    line = get_success_data(api_client.create_shipment_line(
        shipment["id"], create_shipment_line_payload(unit_id, weight_kg=weight_kg,
                                                     labor_minutes=labor_minutes, **line_overrides), LC))
    return shipment, line


def drive_reservation_to_delivered(reservation, unit_id=None, tour_id=None,
                                   ship_city_pair=("LAX", "LAX"), ship_date="2026-08-05T00:00:00Z"):
    """DISPATCHED -> DELIVERED. Creates the covering shipment the dispatch
    precondition requires when tour_id is supplied."""
    if tour_id is not None and unit_id is not None:
        create_shipment_with_line(tour_id, unit_id, from_city=ship_city_pair[0],
                                  to_city=ship_city_pair[1], ship_date=ship_date)
    get_success_data(api_client.dispatch_reservation(reservation["id"], LC))
    return get_success_data(api_client.mark_reservation_delivered(reservation["id"], LC))


def drive_reservation_to_returned(reservation, checked_in_at="2026-08-07T09:00:00Z",
                                  **delivered_kwargs):
    """DISPATCHED -> DELIVERED -> RETURNED."""
    delivered = drive_reservation_to_delivered(reservation, **delivered_kwargs)
    return get_success_data(api_client.check_in_reservation(
        delivered["id"], {"checked_in_at": checked_in_at}, WT))


def drive_reservation_to_inspected(reservation, damage_present=False,
                                   assessed_severity=None, repair_estimate_cents=None,
                                   checked_in_at="2026-08-07T09:00:00Z",
                                   inspector_headers=WT, **delivered_kwargs):
    """DISPATCHED -> DELIVERED -> RETURNED -> INSPECTED, optionally filing a
    damage claim atomically. Returns (inspected_reservation, claim_or_None)."""
    returned = drive_reservation_to_returned(reservation, checked_in_at=checked_in_at,
                                             **delivered_kwargs)
    payload = {"damage_present": damage_present}
    if damage_present:
        payload["assessed_severity"] = assessed_severity
        payload["repair_estimate_cents"] = repair_estimate_cents if repair_estimate_cents is not None else 0
    inspected = get_success_data(api_client.inspect_reservation(returned["id"], payload, inspector_headers))
    claim = None
    if damage_present:
        claim = find_claim_for_reservation(returned["id"])
    return inspected, claim


def settle_reservation(reservation_id, headers=TM):
    """Settle with a fresh OCC version read."""
    reservation = get_reservation(reservation_id, headers)
    return get_success_data(api_client.settle_reservation(
        reservation_id, {"expected_reservation_version": reservation["version"]}, headers))


def create_approved_vendor(city_codes=None, **overrides):
    vendor = get_success_data(api_client.create_partner_vendor(
        create_partner_vendor_payload(city_codes=city_codes or ["LAX"], **overrides), OPS))
    get_success_data(api_client.approve_partner_vendor(vendor["id"], OPS))
    return get_success_data(api_client.get_partner_vendor(vendor["id"], OPS))


def open_cross_rental_via_source(line_id, vendor, stop_city="LAX",
                                 start_date="2026-08-11T00:00:00Z",
                                 end_date="2026-08-13T00:00:00Z",
                                 vendor_rate_cents_per_day=70_000):
    """Source a rider line through the cross-rental path (no in-house unit
    needed). Returns (reservation, cross_rental_request)."""
    reservation = get_success_data(api_client.source_rider_line(
        line_id,
        create_source_payload(origin_city_code=stop_city, dest_city_code=stop_city,
                              start_date=start_date, end_date=end_date,
                              use_cross_rental=True, partner_vendor_id=vendor["id"],
                              vendor_rate_cents_per_day=vendor_rate_cents_per_day),
        LC))
    request = find_cross_request_for_reservation(reservation["id"])
    return reservation, request


def setup_maintenance_ticket_via_gate(city="NASH", days=30):
    """Force a unit into MAINTENANCE via the day-count gate and return the
    auto-opened ticket. A `days`-long rental returns at projected days >= 30."""
    start = date(2026, 8, 1)
    end = start + timedelta(days=days)
    ctx = setup_tour_with_sourced_line(
        city=city, start_date=f"{start.isoformat()}T00:00:00Z",
        end_date=f"{end.isoformat()}T00:00:00Z",
        venue_date="2026-08-15T00:00:00Z",
        artist_overrides={"tier": "PLATINUM", "deposit_waived": True},
        model_overrides={"daily_rate_cents": 20_000, "replacement_value_cents": 100_000,
                         "weight_class": "STANDARD"},
        insurance_policy_id=None)
    drive_reservation_to_returned(
        ctx["reservation"], checked_in_at=f"{end.isoformat()}T09:00:00Z",
        unit_id=ctx["unit"]["id"], tour_id=ctx["tour"]["id"],
        ship_city_pair=(city, city), ship_date=f"{start.isoformat()}T00:00:00Z")
    ctx["ticket"] = find_ticket_for_unit(ctx["unit"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Scenario fixtures keyed to specific test recipes
# ---------------------------------------------------------------------------

def setup_quote_settlement_divergence():
    """Artist risk 0 at quote, driven to 60 by an intervening TOTAL_LOSS
    assessment on an earlier rental; the reservation under test returns 36h
    late. Returns ctx with the reservation INSPECTED, ready to settle.

    Numbers: 5-day window at 100000/day, same city -> quoted 500000.
    Settle: + insurance 40000 (risk 60) + 2 late blocks at 150000 = 840000.
    """
    artist = create_artist(legal_name="The Variants", tier="STANDARD", topup_cents=110_000)
    model = create_gear_model(sku="DV-AMP-1", category="AMP", daily_rate_cents=100_000,
                              replacement_value_cents=300_000, weight_class="HAND_CARRY")
    u1 = create_gear_unit(model["id"], serial_number="DV-U1", home_city_code="LAX")
    u2 = create_gear_unit(model["id"], serial_number="DV-U2", home_city_code="LAX")
    tour = create_tour(artist["id"], name="Variant Tour", insurance_policy_id="POL-1")
    s_early = add_stop(tour["id"], city_code="LAX", venue_date="2026-08-04T00:00:00Z",
                       load_in_ts="2026-08-04T10:00:00Z")
    rl2 = add_rider_line(s_early["id"], model["id"])
    r2 = source_line(rl2["id"], origin_city_code="LAX", dest_city_code="LAX",
                     start_date="2026-08-03T00:00:00Z", end_date="2026-08-05T00:00:00Z")
    # Reservation under test is sourced while the artist's risk is still 0, so
    # its quote carries no insurance surcharge (PRD §3.3 quote-time risk).
    s1 = add_stop(tour["id"], city_code="LAX", venue_date="2026-08-10T00:00:00Z",
                  load_in_ts="2026-08-10T10:00:00Z")
    rl1 = add_rider_line(s1["id"], model["id"])
    r1 = source_line(rl1["id"], origin_city_code="LAX", dest_city_code="LAX",
                     start_date="2026-08-10T00:00:00Z", end_date="2026-08-15T00:00:00Z")
    tour = activate_tour(tour["id"])
    # Damaging rental: TOTAL_LOSS claim assessed -> artist risk 60.
    drive_reservation_to_inspected(r2, damage_present=True, assessed_severity="TOTAL_LOSS",
                                   repair_estimate_cents=0, checked_in_at="2026-08-05T09:00:00Z",
                                   unit_id=u2["id"], tour_id=tour["id"],
                                   ship_city_pair=("LAX", "LAX"), ship_date="2026-08-03T00:00:00Z")
    dc2 = find_claim_for_reservation(r2["id"])
    get_success_data(api_client.assess_damage_claim(dc2["id"], OPS))
    create_shipment_with_line(tour["id"], u1["id"], from_city="LAX", to_city="LAX",
                              ship_date="2026-08-10T00:00:00Z")
    inspected, _ = drive_reservation_to_inspected(
        r1, damage_present=False, checked_in_at="2026-08-16T12:00:00Z")
    return dict(artist=get_artist(artist["id"]), model=model, tour=tour,
                reservation=inspected, quoted_at_source=r1["quoted_fee_cents"])


def setup_rounding_contrast():
    """Artist pre-seeded to risk 60 by a TOTAL_LOSS assessment; a 5-day
    cross-region rental at an odd daily rate (33333) then exposes the two
    pinned rounding orders. Returns ctx with the reservation SOURCED."""
    artist = create_artist(legal_name="Round Act", tier="STANDARD", topup_cents=67_500)
    m1 = create_gear_model(sku="RD-KB-1", category="KEYS", daily_rate_cents=33_333,
                           replacement_value_cents=250_000, weight_class="STANDARD")
    m2 = create_gear_model(sku="RD-KB-2", category="KEYS", daily_rate_cents=10_000,
                           replacement_value_cents=100_000, weight_class="HAND_CARRY")
    create_gear_unit(m1["id"], serial_number="RD-U1", home_city_code="LAX")
    u2 = create_gear_unit(m2["id"], serial_number="RD-U2", home_city_code="LAX")
    tour = create_tour(artist["id"], name="Round Tour", insurance_policy_id="POL-R")
    s_early = add_stop(tour["id"], city_code="LAX", venue_date="2026-08-04T00:00:00Z",
                       load_in_ts="2026-08-04T10:00:00Z")
    rl2 = add_rider_line(s_early["id"], m2["id"])
    r2 = source_line(rl2["id"], origin_city_code="LAX", dest_city_code="LAX",
                     start_date="2026-08-03T00:00:00Z", end_date="2026-08-05T00:00:00Z")
    tour = activate_tour(tour["id"])
    drive_reservation_to_inspected(r2, damage_present=True, assessed_severity="TOTAL_LOSS",
                                   repair_estimate_cents=0, checked_in_at="2026-08-05T09:00:00Z",
                                   unit_id=u2["id"], tour_id=tour["id"],
                                   ship_city_pair=("LAX", "LAX"), ship_date="2026-08-03T00:00:00Z")
    dc = find_claim_for_reservation(r2["id"])
    get_success_data(api_client.assess_damage_claim(dc["id"], OPS))
    s2 = add_stop(tour["id"], city_code="NYC", venue_date="2026-08-12T00:00:00Z",
                  load_in_ts="2026-08-12T10:00:00Z")
    rl1 = add_rider_line(s2["id"], m1["id"])
    r1 = source_line(rl1["id"], origin_city_code="LAX", dest_city_code="NYC",
                     start_date="2026-08-10T00:00:00Z", end_date="2026-08-15T00:00:00Z")
    return dict(artist=get_artist(artist["id"]), reservation=r1)


def setup_deposit_hold_pair():
    """STANDARD artist topped up 75000; two sourced reservations hold 55000
    (replacement 300000) and 20000 (replacement 100000). Returns ctx."""
    artist = create_artist(legal_name="Risk Act", tier="STANDARD", topup_cents=75_000)
    m_hi = create_gear_model(sku="RS-GTR-1", category="GUITAR", daily_rate_cents=50_000,
                             replacement_value_cents=300_000, weight_class="HAND_CARRY")
    m_lo = create_gear_model(sku="RS-GTR-2", category="GUITAR", daily_rate_cents=10_000,
                             replacement_value_cents=100_000, weight_class="HAND_CARRY")
    create_gear_unit(m_hi["id"], serial_number="RS-U1", home_city_code="NYC")
    create_gear_unit(m_lo["id"], serial_number="RS-U2", home_city_code="NYC")
    tour = create_tour(artist["id"], name="Risk Tour", insurance_policy_id="POL-2")
    stop = add_stop(tour["id"], city_code="NYC", venue_date="2026-08-06T00:00:00Z",
                    load_in_ts="2026-08-06T10:00:00Z")
    rl_hi = add_rider_line(stop["id"], m_hi["id"])
    r_hi = source_line(rl_hi["id"], origin_city_code="NYC", dest_city_code="NYC",
                       start_date="2026-08-05T00:00:00Z", end_date="2026-08-07T00:00:00Z")
    rl_lo = add_rider_line(stop["id"], m_lo["id"])
    r_lo = source_line(rl_lo["id"], origin_city_code="NYC", dest_city_code="NYC",
                       start_date="2026-08-05T00:00:00Z", end_date="2026-08-07T00:00:00Z")
    return dict(artist=artist, tour=tour, stop=stop,
                r_hi=r_hi, r_lo=r_lo, m_hi=m_hi, m_lo=m_lo)


def setup_substitution_cycle():
    """SOURCED line on a model that lists a substitute; runs propose -> reject
    -> propose so only the OCC-guarded approval remains. Returns ctx with the
    captured rider revisions and both units."""
    artist = create_artist(legal_name="Cycle Act", tier="STANDARD", topup_cents=40_000)
    m2 = create_gear_model(sku="CY-GTR-B", category="GUITAR", daily_rate_cents=35_000,
                           replacement_value_cents=180_000, weight_class="HAND_CARRY")
    m1 = create_gear_model(sku="CY-GTR-A", category="GUITAR", daily_rate_cents=40_000,
                           replacement_value_cents=200_000, weight_class="HAND_CARRY",
                           substitute_model_ids=[m2["id"]])
    u1 = create_gear_unit(m1["id"], serial_number="CY-U1", home_city_code="NYC")
    u2 = create_gear_unit(m2["id"], serial_number="CY-U2", home_city_code="NYC")
    tour = create_tour(artist["id"], name="Cycle Tour", insurance_policy_id="POL-C")
    stop = add_stop(tour["id"], city_code="NYC", venue_date="2026-08-10T00:00:00Z",
                    load_in_ts="2026-08-10T10:00:00Z")
    line = add_rider_line(stop["id"], m1["id"])
    reservation = source_line(line["id"], origin_city_code="NYC", dest_city_code="NYC",
                              start_date="2026-08-09T00:00:00Z", end_date="2026-08-11T00:00:00Z")
    rev0 = get_stop(stop["id"])["rider_revision"]
    get_success_data(api_client.propose_substitution(
        line["id"], {"substitute_gear_model_id": m2["id"], "substitution_reason": "artist preference"}, LC))
    rev_after_propose1 = get_stop(stop["id"])["rider_revision"]
    get_success_data(api_client.reject_substitution(line["id"], TM))
    rev_after_reject = get_stop(stop["id"])["rider_revision"]
    get_success_data(api_client.propose_substitution(
        line["id"], {"substitute_gear_model_id": m2["id"], "substitution_reason": "second attempt"}, LC))
    rev_after_propose2 = get_stop(stop["id"])["rider_revision"]
    return dict(artist=artist, tour=tour, stop=stop, line=line, reservation=reservation,
                m1=m1, m2=m2, u1=u1, u2=u2, rev0=rev0,
                rev_after_propose1=rev_after_propose1,
                rev_after_reject=rev_after_reject,
                rev_after_propose2=rev_after_propose2)


def setup_loadout_cascade():
    """Unit pre-accumulated to 25 rental days by a clean first rental, then a
    second 5-day rental reaches a SHOW_READY stop. Load-out trips the gate at
    projected 25 + 5 = 30. Returns ctx ready for the load-out trigger."""
    artist = create_artist(legal_name="Cascade Act", tier="PLATINUM", deposit_waived=True)
    model = create_gear_model(sku="KC-BASS-1", category="BASS", daily_rate_cents=30_000,
                              replacement_value_cents=150_000, weight_class="HAND_CARRY")
    unit = create_gear_unit(model["id"], serial_number="KC-U1", home_city_code="NYC")
    tour = create_tour(artist["id"], name="Cascade Tour",
                       start_date="2026-07-01T00:00:00Z", end_date="2026-09-30T00:00:00Z")
    s0 = add_stop(tour["id"], city_code="NYC", venue_date="2026-07-26T00:00:00Z",
                  load_in_ts="2026-07-26T10:00:00Z")
    rl0 = add_rider_line(s0["id"], model["id"])
    r0 = source_line(rl0["id"], origin_city_code="NYC", dest_city_code="NYC",
                     start_date="2026-07-01T00:00:00Z", end_date="2026-07-26T00:00:00Z")
    tour = activate_tour(tour["id"])
    drive_reservation_to_returned(r0, checked_in_at="2026-07-26T09:00:00Z",
                                  unit_id=unit["id"], tour_id=tour["id"],
                                  ship_city_pair=("NYC", "NYC"), ship_date="2026-07-01T00:00:00Z")
    days_after_first = get_unit(unit["id"])["rental_days_since_service"]
    # Second rental: 5 days, driven to DELIVERED with the stop SHOW_READY.
    s1 = add_stop(tour["id"], city_code="NYC", venue_date="2026-08-10T00:00:00Z",
                  load_in_ts="2026-08-10T10:00:00Z")
    rl1 = add_rider_line(s1["id"], model["id"])
    r1 = source_line(rl1["id"], origin_city_code="NYC", dest_city_code="NYC",
                     start_date="2026-08-09T00:00:00Z", end_date="2026-08-14T00:00:00Z")
    shipment, sline = create_shipment_with_line(tour["id"], unit["id"], from_city="NYC",
                                                to_city="NYC", ship_date="2026-08-09T00:00:00Z",
                                                capacity_kg=500, weight_kg=15, labor_minutes=20)
    get_success_data(api_client.dispatch_reservation(r1["id"], LC))
    get_success_data(api_client.begin_loading_shipment(shipment["id"], LC))
    get_success_data(api_client.load_shipment_line(sline["id"], WT))
    get_success_data(api_client.depart_shipment(shipment["id"], LC))
    get_success_data(api_client.mark_shipment_delivered(shipment["id"], LC))
    get_success_data(api_client.mark_reservation_delivered(r1["id"], LC))
    get_success_data(api_client.mark_rider_line_fulfilled(rl1["id"], WT))
    get_success_data(api_client.stage_tour_stop(s1["id"], LC))
    get_success_data(api_client.show_ready_tour_stop(s1["id"], WT))
    return dict(artist=artist, model=model, unit=unit, tour=tour, stop=s1,
                line=rl1, reservation=r1, days_after_first=days_after_first)


def setup_vendor_suspend_pair():
    """APPROVED vendor covering LAX with two cross-rental requests: one
    ACCEPTED, one still REQUESTED. Returns ctx ready for the suspend trigger."""
    artist = create_artist(legal_name="Vendor Act", tier="STANDARD", topup_cents=190_000)
    model = create_gear_model(sku="VN-PA-1", category="PA", daily_rate_cents=80_000,
                              replacement_value_cents=600_000, weight_class="HEAVY")
    vendor = create_approved_vendor(name="SoCal Backline Co", city_codes=["LAX"],
                                    commission_bps=1200)
    tour = create_tour(artist["id"], name="Vendor Tour", insurance_policy_id="POL-V")
    s1 = add_stop(tour["id"], city_code="LAX", venue_date="2026-08-12T00:00:00Z",
                  load_in_ts="2026-08-12T10:00:00Z")
    rl1 = add_rider_line(s1["id"], model["id"])
    r1, crr1 = open_cross_rental_via_source(rl1["id"], vendor, stop_city="LAX",
                                            start_date="2026-08-11T00:00:00Z",
                                            end_date="2026-08-13T00:00:00Z")
    s2 = add_stop(tour["id"], city_code="LAX", venue_date="2026-08-20T00:00:00Z",
                  load_in_ts="2026-08-20T10:00:00Z")
    rl2 = add_rider_line(s2["id"], model["id"])
    r2, crr2 = open_cross_rental_via_source(rl2["id"], vendor, stop_city="LAX",
                                            start_date="2026-08-19T00:00:00Z",
                                            end_date="2026-08-21T00:00:00Z")
    get_success_data(api_client.accept_cross_rental_request(
        crr1["id"], make_vendor_rep_headers(vendor["id"])))
    return dict(artist=artist, model=model, vendor=vendor, tour=tour,
                r1=r1, crr1=crr1, r2=r2, crr2=crr2)


def setup_stage_guard():
    """DRAFT tour (waived artist), one SOURCED rider line, and a cartage leg
    already DELIVERED to the stop's city. Returns ctx ready to attempt staging."""
    ctx = setup_tour_with_sourced_line(
        city="LAX", activate=False, insurance_policy_id=None,
        artist_overrides={"tier": "PLATINUM", "deposit_waived": True},
        model_overrides={"sku": "GD-AMP-1", "daily_rate_cents": 10_000,
                         "replacement_value_cents": 100_000})
    shipment, sline = create_shipment_with_line(ctx["tour"]["id"], ctx["unit"]["id"],
                                                from_city="LAX", to_city="LAX",
                                                ship_date="2026-08-09T00:00:00Z",
                                                capacity_kg=100, weight_kg=5, labor_minutes=5)
    get_success_data(api_client.begin_loading_shipment(shipment["id"], LC))
    get_success_data(api_client.load_shipment_line(sline["id"], WT))
    get_success_data(api_client.depart_shipment(shipment["id"], LC))
    get_success_data(api_client.mark_shipment_delivered(shipment["id"], LC))
    return ctx


def setup_cross_rental_fulfilled():
    """Cross-rental path driven to FULFILLED: reservation SOURCED with
    is_cross_rental true. Window 2 days at vendor rate 80000, vendor 1500 bps,
    so the eventual commission is 24000. Returns ctx."""
    artist = create_artist(legal_name="XR Act", tier="PLATINUM", deposit_waived=True)
    model = create_gear_model(sku="XR-PA-1", category="PA", daily_rate_cents=90_000,
                              replacement_value_cents=700_000, weight_class="HEAVY")
    vendor = create_approved_vendor(name="XR Vendor", city_codes=["SEA"], commission_bps=1500)
    tour = create_tour(artist["id"], name="XR Tour")
    stop = add_stop(tour["id"], city_code="SEA", venue_date="2026-08-11T00:00:00Z",
                    load_in_ts="2026-08-11T10:00:00Z")
    line = add_rider_line(stop["id"], model["id"])
    reservation, crr = open_cross_rental_via_source(
        line["id"], vendor, stop_city="SEA",
        start_date="2026-08-10T00:00:00Z", end_date="2026-08-12T00:00:00Z",
        vendor_rate_cents_per_day=80_000)
    rep = make_vendor_rep_headers(vendor["id"])
    get_success_data(api_client.accept_cross_rental_request(crr["id"], rep))
    get_success_data(api_client.fulfill_cross_rental_request(crr["id"], rep))
    return dict(artist=artist, model=model, vendor=vendor, tour=tour, stop=stop,
                line=line, reservation=reservation, crr=crr)


def setup_overlap_unit():
    """One unit, one SOURCED reservation [2026-08-10, 2026-08-15) at an LAX
    stop. Returns ctx with the tour available for adding further stops."""
    ctx = setup_tour_with_sourced_line(
        city="LAX", activate=False, insurance_policy_id=None,
        start_date="2026-08-10T00:00:00Z", end_date="2026-08-15T00:00:00Z",
        venue_date="2026-08-12T00:00:00Z",
        artist_overrides={"tier": "PLATINUM", "deposit_waived": True},
        model_overrides={"sku": "OL-GTR-1", "category": "GUITAR", "daily_rate_cents": 20_000,
                         "replacement_value_cents": 100_000})
    return ctx


def setup_transit_buffer_scene():
    """Unit home LAX with a SOURCED reservation [2026-08-10, 2026-08-15);
    a second stop exists in NYC. Returns ctx."""
    ctx = setup_tour_with_sourced_line(
        city="LAX", activate=False, insurance_policy_id=None,
        start_date="2026-08-10T00:00:00Z", end_date="2026-08-15T00:00:00Z",
        venue_date="2026-08-12T00:00:00Z",
        artist_overrides={"tier": "PLATINUM", "deposit_waived": True},
        model_overrides={"sku": "BF-DRM-1", "category": "DRUMS", "daily_rate_cents": 25_000,
                         "replacement_value_cents": 120_000, "weight_class": "STANDARD"})
    stop_nyc = add_stop(ctx["tour"]["id"], city_code="NYC", venue_date="2026-08-16T00:00:00Z",
                        load_in_ts="2026-08-16T10:00:00Z")
    ctx["stop_nyc"] = stop_nyc
    return ctx


def setup_deposit_invariant_scene():
    """STANDARD artist topped up exactly 55000; one sourced reservation holds
    55000 (replacement 300000). Returns ctx with the SOURCED reservation."""
    ctx = setup_tour_with_sourced_line(
        city="LAX", activate=False, insurance_policy_id="POL-I", topup_cents=55_000,
        artist_overrides={"legal_name": "Invariant Act", "tier": "STANDARD"},
        model_overrides={"sku": "IV-AMP-1", "daily_rate_cents": 10_000,
                         "replacement_value_cents": 300_000})
    return ctx


def setup_weight_scene():
    """Shipment of capacity 100kg with two BOOKED lines of 30kg and 40kg."""
    artist = create_artist(legal_name="Weight Act", tier="PLATINUM", deposit_waived=True)
    model = create_gear_model(sku="WT-AMP-1", category="AMP", daily_rate_cents=10_000,
                              replacement_value_cents=100_000, weight_class="STANDARD")
    u1 = create_gear_unit(model["id"], serial_number="WT-U1", home_city_code="LAX")
    u2 = create_gear_unit(model["id"], serial_number="WT-U2", home_city_code="LAX")
    tour = create_tour(artist["id"], name="Weight Tour")
    shipment = get_success_data(api_client.create_shipment(
        create_shipment_payload(tour["id"], from_city_code="LAX", to_city_code="NYC",
                                ship_date="2026-08-09T00:00:00Z", capacity_kg=100), LC))
    sl1 = get_success_data(api_client.create_shipment_line(
        shipment["id"], create_shipment_line_payload(u1["id"], weight_kg=30, labor_minutes=10), LC))
    sl2 = get_success_data(api_client.create_shipment_line(
        shipment["id"], create_shipment_line_payload(u2["id"], weight_kg=40, labor_minutes=10), LC))
    return dict(artist=artist, model=model, tour=tour, shipment=shipment,
                sl1=sl1, sl2=sl2, u1=u1, u2=u2)


def setup_state_fiscal_scene(cancel_line):
    """STANDARD artist with balance 0 and one rider line; when cancel_line is
    true the line is CANCELLED before any source attempt. Returns ctx."""
    artist = create_artist(legal_name="Conflict Act", tier="STANDARD")
    model = create_gear_model(sku="XC-AMP-1", category="AMP", daily_rate_cents=10_000,
                              replacement_value_cents=300_000, weight_class="HAND_CARRY")
    unit = create_gear_unit(model["id"], serial_number="XC-U1", home_city_code="LAX")
    tour = create_tour(artist["id"], name="Conflict Tour", insurance_policy_id="POL-X")
    stop = add_stop(tour["id"], city_code="LAX", venue_date="2026-08-10T00:00:00Z",
                    load_in_ts="2026-08-10T10:00:00Z")
    line = add_rider_line(stop["id"], model["id"])
    if cancel_line:
        get_success_data(api_client.cancel_rider_line(line["id"], TM))
    return dict(artist=artist, model=model, unit=unit, tour=tour, stop=stop, line=line)


def setup_sod_scene():
    """Claim FILED by the default WarehouseTech user on an inspected rental; a
    once-approved vendor is suspended afterwards. Returns ctx incl. filer id."""
    artist = create_artist(legal_name="SoD Act", tier="PLATINUM", deposit_waived=True)
    model = create_gear_model(sku="SD-GTR-1", category="GUITAR", daily_rate_cents=10_000,
                              replacement_value_cents=100_000, weight_class="HAND_CARRY")
    unit = create_gear_unit(model["id"], serial_number="SD-U1", home_city_code="LAX")
    vendor = create_approved_vendor(name="SuspendMe", city_codes=["LAX"], commission_bps=1000)
    ctx = setup_tour_with_sourced_line(
        artist=artist, model=model, unit=unit, city="LAX", insurance_policy_id=None,
        start_date="2026-08-05T00:00:00Z", end_date="2026-08-07T00:00:00Z",
        venue_date="2026-08-06T00:00:00Z")
    _, claim = drive_reservation_to_inspected(
        ctx["reservation"], damage_present=True, assessed_severity="MINOR",
        repair_estimate_cents=5000, checked_in_at="2026-08-07T09:00:00Z",
        unit_id=unit["id"], tour_id=ctx["tour"]["id"],
        ship_city_pair=("LAX", "LAX"), ship_date="2026-08-05T00:00:00Z")
    get_success_data(api_client.suspend_partner_vendor(vendor["id"], OPS))
    ctx["claim"] = claim
    ctx["vendor"] = vendor
    ctx["filer_id"] = claim["filed_by_user_id"]
    return ctx


def setup_maintenance_gate_boundary_pair():
    """Two units of one model, sourced on the same stop for 29- and 30-day
    windows, both DISPATCHED and DELIVERED. Returns ctx ready for check-ins."""
    artist = create_artist(legal_name="Boundary Act", tier="PLATINUM", deposit_waived=True)
    model = create_gear_model(sku="BD-AMP-1", category="AMP", daily_rate_cents=10_000,
                              replacement_value_cents=100_000, weight_class="HAND_CARRY")
    u29 = create_gear_unit(model["id"], serial_number="BD-U29", home_city_code="LAX")
    u30 = create_gear_unit(model["id"], serial_number="BD-U30", home_city_code="LAX")
    tour = create_tour(artist["id"], name="Boundary Tour", end_date="2026-09-30T00:00:00Z")
    stop = add_stop(tour["id"], city_code="LAX", venue_date="2026-08-15T00:00:00Z",
                    load_in_ts="2026-08-15T10:00:00Z")
    rl29 = add_rider_line(stop["id"], model["id"])
    r29 = source_line(rl29["id"], origin_city_code="LAX", dest_city_code="LAX",
                      start_date="2026-08-01T00:00:00Z", end_date="2026-08-30T00:00:00Z")
    rl30 = add_rider_line(stop["id"], model["id"])
    r30 = source_line(rl30["id"], origin_city_code="LAX", dest_city_code="LAX",
                      start_date="2026-08-01T00:00:00Z", end_date="2026-08-31T00:00:00Z")
    tour = activate_tour(tour["id"])
    shipment = get_success_data(api_client.create_shipment(
        create_shipment_payload(tour["id"], from_city_code="LAX", to_city_code="LAX",
                                ship_date="2026-08-01T00:00:00Z", capacity_kg=500), LC))
    get_success_data(api_client.create_shipment_line(
        shipment["id"], create_shipment_line_payload(r29["gear_unit_id"], weight_kg=10, labor_minutes=10), LC))
    get_success_data(api_client.create_shipment_line(
        shipment["id"], create_shipment_line_payload(r30["gear_unit_id"], weight_kg=10, labor_minutes=10), LC))
    get_success_data(api_client.dispatch_reservation(r29["id"], LC))
    get_success_data(api_client.mark_reservation_delivered(r29["id"], LC))
    get_success_data(api_client.dispatch_reservation(r30["id"], LC))
    get_success_data(api_client.mark_reservation_delivered(r30["id"], LC))
    return dict(artist=artist, model=model, tour=tour, stop=stop,
                r29=r29, r30=r30, u29=r29["gear_unit_id"], u30=r30["gear_unit_id"])


def setup_overage_pair():
    """Two reservations (replacement value 300000 -> hold 55000 each), both
    INSPECTED with MINOR claims of exactly 55000 and 55001, both ASSESSED.
    Returns ctx ready for the charge triggers."""
    artist = create_artist(legal_name="Overage Act", tier="STANDARD", topup_cents=220_000)
    model = create_gear_model(sku="OV-KB-1", category="KEYS", daily_rate_cents=10_000,
                              replacement_value_cents=300_000, weight_class="STANDARD")
    u1 = create_gear_unit(model["id"], serial_number="OV-U1", home_city_code="LAX")
    u2 = create_gear_unit(model["id"], serial_number="OV-U2", home_city_code="LAX")
    tour = create_tour(artist["id"], name="Overage Tour", insurance_policy_id="POL-O")
    stop = add_stop(tour["id"], city_code="LAX", venue_date="2026-08-06T00:00:00Z",
                    load_in_ts="2026-08-06T10:00:00Z")
    rl1 = add_rider_line(stop["id"], model["id"])
    r1 = source_line(rl1["id"], origin_city_code="LAX", dest_city_code="LAX",
                     start_date="2026-08-05T00:00:00Z", end_date="2026-08-07T00:00:00Z")
    rl2 = add_rider_line(stop["id"], model["id"])
    r2 = source_line(rl2["id"], origin_city_code="LAX", dest_city_code="LAX",
                     start_date="2026-08-05T00:00:00Z", end_date="2026-08-07T00:00:00Z")
    tour = activate_tour(tour["id"])
    shipment = get_success_data(api_client.create_shipment(
        create_shipment_payload(tour["id"], from_city_code="LAX", to_city_code="LAX",
                                ship_date="2026-08-05T00:00:00Z", capacity_kg=500), LC))
    get_success_data(api_client.create_shipment_line(
        shipment["id"], create_shipment_line_payload(r1["gear_unit_id"], weight_kg=10, labor_minutes=10), LC))
    get_success_data(api_client.create_shipment_line(
        shipment["id"], create_shipment_line_payload(r2["gear_unit_id"], weight_kg=10, labor_minutes=10), LC))
    _, dc1 = drive_reservation_to_inspected(
        r1, damage_present=True, assessed_severity="MINOR", repair_estimate_cents=55_000,
        checked_in_at="2026-08-07T09:00:00Z")
    _, dc2 = drive_reservation_to_inspected(
        r2, damage_present=True, assessed_severity="MINOR", repair_estimate_cents=55_001,
        checked_in_at="2026-08-07T09:00:00Z")
    get_success_data(api_client.assess_damage_claim(dc1["id"], OPS))
    get_success_data(api_client.assess_damage_claim(dc2["id"], OPS))
    return dict(artist=artist, model=model, tour=tour, stop=stop,
                r1=r1, r2=r2, dc1=dc1, dc2=dc2, u1=u1, u2=u2)


def setup_complete_blocked_scene():
    """ACTIVE tour whose only reservation is INSPECTED with a COSMETIC claim
    still ASSESSED. Returns ctx ready to attempt tour completion."""
    ctx = setup_tour_with_sourced_line(
        city="LAX", insurance_policy_id=None,
        start_date="2026-08-05T00:00:00Z", end_date="2026-08-07T00:00:00Z",
        venue_date="2026-08-06T00:00:00Z",
        artist_overrides={"legal_name": "Block Act", "tier": "PLATINUM", "deposit_waived": True},
        model_overrides={"sku": "BK-AMP-1", "daily_rate_cents": 10_000,
                         "replacement_value_cents": 100_000})
    _, claim = drive_reservation_to_inspected(
        ctx["reservation"], damage_present=True, assessed_severity="COSMETIC",
        repair_estimate_cents=1000, checked_in_at="2026-08-07T09:00:00Z",
        unit_id=ctx["unit"]["id"], tour_id=ctx["tour"]["id"],
        ship_city_pair=("LAX", "LAX"), ship_date="2026-08-05T00:00:00Z")
    get_success_data(api_client.assess_damage_claim(claim["id"], OPS))
    ctx["claim"] = claim
    return ctx


def setup_inspected_reservation_scene():
    """Reservation INSPECTED with no damage; returns ctx including the version
    captured right after dispatch (stale by the time of settle)."""
    ctx = setup_tour_with_sourced_line(
        city="LAX", insurance_policy_id=None,
        start_date="2026-08-05T00:00:00Z", end_date="2026-08-07T00:00:00Z",
        venue_date="2026-08-06T00:00:00Z",
        artist_overrides={"legal_name": "OCC2 Act", "tier": "PLATINUM", "deposit_waived": True},
        model_overrides={"sku": "O2-AMP-1", "daily_rate_cents": 10_000,
                         "replacement_value_cents": 100_000})
    create_shipment_with_line(ctx["tour"]["id"], ctx["unit"]["id"], from_city="LAX",
                              to_city="LAX", ship_date="2026-08-05T00:00:00Z",
                              capacity_kg=100, weight_kg=5, labor_minutes=5)
    get_success_data(api_client.dispatch_reservation(ctx["reservation"]["id"], LC))
    stale_version = get_reservation(ctx["reservation"]["id"])["version"]
    get_success_data(api_client.mark_reservation_delivered(ctx["reservation"]["id"], LC))
    get_success_data(api_client.check_in_reservation(
        ctx["reservation"]["id"], {"checked_in_at": "2026-08-07T09:00:00Z"}, WT))
    get_success_data(api_client.inspect_reservation(
        ctx["reservation"]["id"], {"damage_present": False}, WT))
    ctx["stale_version"] = stale_version
    return ctx


def setup_risk_filtering_scene():
    """Artist with one MAJOR claim ASSESSED (risk 24 under the 90-day recency
    doubling). Returns ctx ready to waive the claim."""
    ctx = setup_tour_with_sourced_line(
        city="LAX", insurance_policy_id=None,
        start_date="2026-08-05T00:00:00Z", end_date="2026-08-07T00:00:00Z",
        venue_date="2026-08-06T00:00:00Z",
        artist_overrides={"legal_name": "Filter Act", "tier": "PLATINUM", "deposit_waived": True},
        model_overrides={"sku": "FL-AMP-1", "daily_rate_cents": 10_000,
                         "replacement_value_cents": 100_000})
    _, claim = drive_reservation_to_inspected(
        ctx["reservation"], damage_present=True, assessed_severity="MAJOR",
        repair_estimate_cents=20_000, checked_in_at="2026-08-07T09:00:00Z",
        unit_id=ctx["unit"]["id"], tour_id=ctx["tour"]["id"],
        ship_city_pair=("LAX", "LAX"), ship_date="2026-08-05T00:00:00Z")
    get_success_data(api_client.assess_damage_claim(claim["id"], OPS))
    ctx["claim"] = claim
    return ctx
