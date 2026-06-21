"""Composite setup helpers.

These encapsulate the multi-step API sequences that the test cases need to reach
specific system states. They use get_success_data() (lenient) internally so that
a setup failure surfaces as a clear "Setup failed" rather than a confusing
assertion error.

The harness restarts the server (empty DB) before every test, so each helper
builds its entire world from scratch using only PRD-declared endpoints.

Identity threading: every leg action is ownership-gated on the trip's assigned
driver, so leg calls use make_driver_headers(driver_id) with the real Driver id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_driver_headers
from . import factories


COORD = TEST_USERS["coordinator_headers"]
BROKER = TEST_USERS["broker_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def set_clock(now_utc):
    return get_success_data(api_client.set_clock(now_utc, COORD))


def seed_distance(county_a, county_b, miles):
    return get_success_data(api_client.seed_county_distance(county_a, county_b, miles, COORD))


def create_member(**overrides):
    return get_success_data(api_client.create_member(factories.create_member_payload(**overrides), COORD))


def create_span(member_id, **overrides):
    return get_success_data(
        api_client.create_eligibility_span(factories.create_eligibility_span_payload(member_id, **overrides), COORD)
    )


def create_broker(**overrides):
    # Broker creation is a Coordinator operation (PRD 3.2).
    return get_success_data(api_client.create_broker(factories.create_broker_payload(**overrides), COORD))


def create_driver(broker_id, **overrides):
    return get_success_data(api_client.create_driver(factories.create_driver_payload(broker_id, **overrides), BROKER))


def create_rate(**overrides):
    return get_success_data(api_client.create_rate_schedule(factories.create_rate_schedule_payload(**overrides), COORD))


def create_trip(member_id, **overrides):
    return get_success_data(api_client.create_trip(factories.create_trip_payload(member_id, **overrides), COORD))


def recompute(member_id):
    return get_success_data(api_client.recompute_eligibility(member_id, COORD))


def list_legs(trip_id):
    """Return the legs list (OUTBOUND first, then RETURN) for a trip."""
    resp = api_client.list_trip_legs(trip_id, COORD)
    get_success_data(resp)
    return resp.json()["data"]


def get_trip(trip_id):
    return get_success_data(api_client.get_trip(trip_id, COORD))


def get_driver(driver_id):
    return get_success_data(api_client.get_driver(driver_id, COORD))


def get_member(member_id):
    return get_success_data(api_client.get_member(member_id, COORD))


# ---------------------------------------------------------------------------
# Tier 2: base world (member + span + broker + driver + rate + geo)
# ---------------------------------------------------------------------------

def setup_world(
    *,
    modality="AMBULATORY",
    member_mobility=None,
    span_los="ROUTINE",
    broker_max_modality=None,
    driver_modality=None,
    home_county="C1",
    base_county="C2",
    deadhead_miles=12,
    free_deadhead_miles=5,
    deadhead_rate_cents_per_mile=80,
    covered_counties=None,
    rate_overrides=None,
    span_start="2026-01-01T00:00:00Z",
    span_end="2027-01-01T00:00:00Z",
    clock="2026-03-01T08:00:00Z",
    medicaid_id="M-W1",
    create_rate_row=True,
):
    """Build an eligible member with covering span plus an active broker and an
    available driver that can serve `modality`, seeding the dead-head distance.

    Returns dict with member, broker, driver, and (if created) rate.
    """
    member_mobility = member_mobility or modality
    broker_max_modality = broker_max_modality or modality
    driver_modality = driver_modality or modality
    covered_counties = covered_counties or [home_county]

    set_clock(clock)
    rate = None
    if create_rate_row:
        rate_payload = dict(modality=modality)
        if rate_overrides:
            rate_payload.update(rate_overrides)
        rate = create_rate(**rate_payload)

    member = create_member(
        medicaid_id=medicaid_id, mobility_level=member_mobility, home_county=home_county,
    )
    create_span(member["id"], level_of_service=span_los, coverage_start=span_start, coverage_end=span_end)
    broker = create_broker(
        name="Broker-" + medicaid_id, covered_counties=covered_counties,
        max_modality=broker_max_modality, free_deadhead_miles=free_deadhead_miles,
        deadhead_rate_cents_per_mile=deadhead_rate_cents_per_mile,
    )
    if base_county != home_county:
        seed_distance(base_county, home_county, deadhead_miles)
    driver = create_driver(broker["id"], vehicle_modality=driver_modality, base_county=base_county)
    return {"member": member, "broker": broker, "driver": driver, "rate": rate}


# ---------------------------------------------------------------------------
# Tier 1 / 3: trip state progression shortcuts
# ---------------------------------------------------------------------------

def create_scheduled_trip(world, *, modality="AMBULATORY", los="ROUTINE",
                          scheduled_loaded_miles=8, is_round_trip=False,
                          return_is_will_call=False, appointment_at="2026-03-02T09:00:00Z"):
    """Create a trip on world's member and schedule it. Returns (trip, legs)."""
    trip = create_trip(
        world["member"]["id"], modality=modality, requested_level_of_service=los,
        appointment_at=appointment_at, scheduled_loaded_miles=scheduled_loaded_miles,
        is_round_trip=is_round_trip, return_is_will_call=return_is_will_call,
    )
    scheduled = get_success_data(api_client.schedule_trip(trip["id"], COORD))
    legs = list_legs(trip["id"])
    return scheduled, legs


def assign_trip(world, trip, *, expected_version=None):
    """Assign world's broker+driver to a SCHEDULED trip. Returns the assigned trip."""
    if expected_version is None:
        expected_version = trip["version"]
    payload = {"expected_trip_version": expected_version, "preferred_broker_id": world["broker"]["id"]}
    return get_success_data(api_client.assign_trip(trip["id"], payload, BROKER))


def create_assigned_trip(world, **trip_kwargs):
    """Create + schedule + assign a trip. Returns (trip_after_assign, legs)."""
    scheduled, legs = create_scheduled_trip(world, **trip_kwargs)
    assigned = assign_trip(world, scheduled)
    return assigned, legs


def _drive_leg_to_dropoff(leg_id, driver_id, odometer):
    """Walk a leg PENDING -> EN_ROUTE -> ARRIVED -> PICKED_UP -> DROPPED_OFF."""
    dh = make_driver_headers(driver_id)
    get_success_data(api_client.leg_depart(leg_id, dh))
    get_success_data(api_client.leg_arrive(leg_id, dh))
    get_success_data(api_client.leg_pickup(leg_id, dh))
    get_success_data(api_client.leg_dropoff(leg_id, odometer, dh))


def complete_oneway_trip(world, *, modality="AMBULATORY", los="ROUTINE",
                         scheduled_loaded_miles=8, odometer=8.0,
                         appointment_at="2026-03-02T09:00:00Z"):
    """Create -> schedule -> assign -> drive the single OUTBOUND leg to DROPPED_OFF,
    which bubbles the trip to COMPLETED. Returns (trip, legs, driver_id)."""
    assigned, legs = create_assigned_trip(
        world, modality=modality, los=los, scheduled_loaded_miles=scheduled_loaded_miles,
        is_round_trip=False, appointment_at=appointment_at,
    )
    driver_id = world["driver"]["id"]
    ob = legs[0]
    _drive_leg_to_dropoff(ob["id"], driver_id, odometer)
    return assigned, legs, driver_id


def complete_roundtrip_non_will_call(world, *, modality="WHEELCHAIR", los="ROUTINE",
                                     scheduled_loaded_miles=10, ob_odometer=10.0,
                                     rt_odometer=10.0, appointment_at="2026-03-02T09:00:00Z"):
    """Create -> schedule -> assign -> drive both legs (non-will-call) to DROPPED_OFF,
    bubbling the trip to COMPLETED. Returns (trip, legs, driver_id)."""
    assigned, legs = create_assigned_trip(
        world, modality=modality, los=los, scheduled_loaded_miles=scheduled_loaded_miles,
        is_round_trip=True, return_is_will_call=False, appointment_at=appointment_at,
    )
    driver_id = world["driver"]["id"]
    ob, rt = legs[0], legs[1]
    _drive_leg_to_dropoff(ob["id"], driver_id, ob_odometer)
    _drive_leg_to_dropoff(rt["id"], driver_id, rt_odometer)
    return assigned, legs, driver_id


def complete_will_call_roundtrip(world, *, modality="WHEELCHAIR", los="ROUTINE",
                                 scheduled_loaded_miles=10, ob_odometer=10.4,
                                 rt_odometer=9.8, ready_at="2026-03-02T09:00:00Z",
                                 pickup_at="2026-03-02T09:25:00Z",
                                 appointment_at="2026-03-02T09:00:00Z"):
    """Full will-call round trip through COMPLETED.

    OUTBOUND driven to DROPPED_OFF; the RETURN will-call leg is readied (clock at
    `ready_at`), departed, arrived, then picked up at `pickup_at` and dropped off.
    Returns (trip, legs, driver_id).
    """
    assigned, legs = create_assigned_trip(
        world, modality=modality, los=los, scheduled_loaded_miles=scheduled_loaded_miles,
        is_round_trip=True, return_is_will_call=True, appointment_at=appointment_at,
    )
    driver_id = world["driver"]["id"]
    dh = make_driver_headers(driver_id)
    ob, rt = legs[0], legs[1]
    _drive_leg_to_dropoff(ob["id"], driver_id, ob_odometer)
    set_clock(ready_at)
    get_success_data(api_client.leg_ready(rt["id"], COORD))
    get_success_data(api_client.leg_depart(rt["id"], dh))
    get_success_data(api_client.leg_arrive(rt["id"], dh))
    set_clock(pickup_at)
    get_success_data(api_client.leg_pickup(rt["id"], dh))
    get_success_data(api_client.leg_dropoff(rt["id"], rt_odometer, dh))
    return assigned, legs, driver_id


# ---------------------------------------------------------------------------
# Tier 5: billing-axis progression (claim / encounter / reconcile)
# ---------------------------------------------------------------------------

def submit_claim(trip_id):
    return get_success_data(api_client.create_claim(factories.create_claim_payload(trip_id), BROKER))


def capture_encounter(trip_id):
    return get_success_data(api_client.create_encounter(factories.create_encounter_payload(trip_id), AUDITOR))


def reconcile(trip_id):
    return get_success_data(api_client.reconcile_trip(trip_id, AUDITOR))


def claim_and_encounter(trip_id):
    """Submit the claim then capture the encounter. Returns (claim, encounter)."""
    claim = submit_claim(trip_id)
    encounter = capture_encounter(trip_id)
    return claim, encounter


# ---------------------------------------------------------------------------
# Tier 4: accumulation — no-show strikes
# ---------------------------------------------------------------------------

def accrue_noshow_strikes(world, count, *, modality="AMBULATORY",
                          scheduled_loaded_miles=8, start_day=2):
    """Drive `count` separate trips to an OUTBOUND no-show, accruing that many
    strikes on world's member. Returns the list of no-showed trips."""
    driver_id = world["driver"]["id"]
    dh = make_driver_headers(driver_id)
    trips = []
    for i in range(count):
        appt = f"2026-03-{start_day + i:02d}T09:00:00Z"
        assigned, legs = create_assigned_trip(
            world, modality=modality, scheduled_loaded_miles=scheduled_loaded_miles,
            is_round_trip=False, appointment_at=appt,
        )
        ob = legs[0]
        get_success_data(api_client.leg_depart(ob["id"], dh))
        get_success_data(api_client.leg_arrive(ob["id"], dh))
        get_success_data(api_client.leg_no_show(ob["id"], dh))
        trips.append(assigned)
    return trips


def setup_arrived_outbound_for_noshow(world, *, appointment_at="2026-03-09T09:00:00Z",
                                      modality="AMBULATORY", scheduled_loaded_miles=8):
    """Create -> schedule -> assign -> depart -> arrive the OUTBOUND leg, leaving it
    in ARRIVED ready for a no-show trigger. Returns (trip, outbound_leg, driver_id)."""
    assigned, legs = create_assigned_trip(
        world, modality=modality, scheduled_loaded_miles=scheduled_loaded_miles,
        is_round_trip=False, appointment_at=appointment_at,
    )
    driver_id = world["driver"]["id"]
    dh = make_driver_headers(driver_id)
    ob = legs[0]
    get_success_data(api_client.leg_depart(ob["id"], dh))
    get_success_data(api_client.leg_arrive(ob["id"], dh))
    return assigned, ob, driver_id
