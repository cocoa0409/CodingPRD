"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: ExecutiveRequester calls are entity-backed by
PassengerProfile, so trip creation / submission / requester-side leg creation
always use make_executive_requester_headers(passenger["id"]). Opaque roles
(Dispatcher, FlightDeptManager, MaintenancePlanner, FinanceAdmin) use shared
constants unless a segregation-of-duties check requires distinct X-User-IDs
(assign vs dispatch, approve-personal-use vs settle on personal-use trips).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_ISO, DEFAULT_RATE_PERIOD
from .factories import (
    create_aircraft_payload,
    create_business_unit_payload,
    create_catering_order_payload,
    create_charter_supplement_payload,
    create_crew_member_payload,
    create_document_payload,
    create_flight_leg_payload,
    create_ground_transport_payload,
    create_maintenance_window_payload,
    create_passenger_profile_payload,
    create_sifl_rate_period_payload,
    create_trip_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_dispatcher_headers,
    make_executive_requester_headers,
    make_finance_headers,
)

MANAGER = TEST_USERS["manager_headers"]
PLANNER = TEST_USERS["planner_headers"]
FINANCE = TEST_USERS["finance_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]

FAR_FUTURE_TRAINING = "2027-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: clock + single-resource creation
# ---------------------------------------------------------------------------

def reset_clock(to_iso8601=CLOCK_START_ISO):
    """Pin the logical clock; returns the reported now_utc payload."""
    return get_success_data(api_client.set_clock(to_iso8601, MANAGER))


def create_business_unit(bu_code=None, annual_flight_budget_cents=100_000_000, name=None):
    overrides = {"annual_flight_budget_cents": annual_flight_budget_cents}
    if bu_code is not None:
        overrides["bu_code"] = bu_code
    if name is not None:
        overrides["name"] = name
    return get_success_data(
        api_client.create_business_unit(create_business_unit_payload(**overrides), FINANCE)
    )


def create_passenger(home_bu_id, priority_tier="TIER_1", sifl_control_employee=False,
                     full_name=None, employee_number=None):
    overrides = {
        "home_bu_id": home_bu_id,
        "priority_tier": priority_tier,
        "sifl_control_employee": sifl_control_employee,
    }
    if full_name is not None:
        overrides["full_name"] = full_name
    if employee_number is not None:
        overrides["employee_number"] = employee_number
    return get_success_data(
        api_client.create_passenger_profile(
            create_passenger_profile_payload(**overrides), MANAGER)
    )


def create_aircraft(aircraft_type="LIGHT_JET", passenger_capacity=6,
                    home_base_icao="KTEB", tail_number=None):
    overrides = {
        "aircraft_type": aircraft_type,
        "passenger_capacity": passenger_capacity,
        "home_base_icao": home_base_icao,
    }
    if tail_number is not None:
        overrides["tail_number"] = tail_number
    return get_success_data(
        api_client.create_aircraft(create_aircraft_payload(**overrides), MANAGER)
    )


def create_crew(seat_qualification="PIC", type_ratings=("LIGHT_JET",),
                training_valid_until=FAR_FUTURE_TRAINING, full_name=None):
    overrides = {
        "seat_qualification": seat_qualification,
        "type_ratings": list(type_ratings),
        "training_valid_until": training_valid_until,
    }
    if full_name is not None:
        overrides["full_name"] = full_name
    return get_success_data(
        api_client.create_crew_member(create_crew_member_payload(**overrides), MANAGER)
    )


def create_default_rate_period(**overrides):
    return get_success_data(
        api_client.create_sifl_rate_period(create_sifl_rate_period_payload(**overrides), FINANCE)
    )


def create_document(aircraft_id, doc_kind="AIRWORTHINESS_CERT", identifier=None,
                    issued_at="2025-01-01T00:00:00Z", expires_at="2027-06-01T00:00:00Z"):
    overrides = {
        "doc_kind": doc_kind,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    if identifier is not None:
        overrides["identifier"] = identifier
    return get_success_data(
        api_client.create_document(aircraft_id, create_document_payload(**overrides), PLANNER)
    )


def create_maintenance_window(aircraft_id, window_start_utc, window_end_utc,
                              maintenance_kind="SCHEDULED_INSPECTION"):
    payload = create_maintenance_window_payload(
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
        maintenance_kind=maintenance_kind,
    )
    return get_success_data(api_client.create_maintenance_window(aircraft_id, payload, PLANNER))


# ---------------------------------------------------------------------------
# Tier 1: trip + legs
# ---------------------------------------------------------------------------

def create_trip(requester, charge_bu_id, trip_kind="BUSINESS",
                passenger_ids=None, personal_use_flag=None,
                requested_departure_utc="2026-08-10T12:00:00Z",
                requested_return_utc="2026-08-10T14:00:00Z", purpose="Client visit"):
    """Create a DRAFT trip owned by `requester` (a PassengerProfile dict)."""
    overrides = {
        "trip_kind": trip_kind,
        "purpose": purpose,
        "requested_departure_utc": requested_departure_utc,
        "requested_return_utc": requested_return_utc,
    }
    overrides["passenger_ids"] = passenger_ids if passenger_ids is not None else [requester["id"]]
    if personal_use_flag is not None:
        overrides["personal_use_flag"] = personal_use_flag
    headers = make_executive_requester_headers(requester["id"])
    return get_success_data(
        api_client.create_trip_request(
            create_trip_request_payload(requester["id"], charge_bu_id, **overrides), headers)
    )


def add_leg(trip, requester, leg_sequence=1, origin_icao="KTEB", destination_icao="KDCA",
            scheduled_departure_utc="2026-08-10T12:00:00Z",
            scheduled_arrival_utc="2026-08-10T14:00:00Z", distance_statute_miles=200,
            as_dispatcher=False):
    """Add a PLANNED leg to a trip. Defaults to the requester as the actor."""
    payload = create_flight_leg_payload(
        leg_sequence=leg_sequence,
        origin_icao=origin_icao,
        destination_icao=destination_icao,
        scheduled_departure_utc=scheduled_departure_utc,
        scheduled_arrival_utc=scheduled_arrival_utc,
        distance_statute_miles=distance_statute_miles,
    )
    if as_dispatcher:
        headers = DISPATCHER
    else:
        headers = make_executive_requester_headers(requester["id"])
    return get_success_data(api_client.create_flight_leg(trip["id"], payload, headers))


def submit_trip(trip, requester):
    return get_success_data(
        api_client.submit_trip(trip["id"], make_executive_requester_headers(requester["id"]))
    )


def approve_trip(trip):
    return get_success_data(api_client.approve_trip(trip["id"], MANAGER))


def current_trip_version(trip_id, headers=None):
    return get_success_data(api_client.get_trip_request(trip_id, headers or MANAGER))["version"]


def assign_aircraft(trip_id, dispatcher_id="disp-1"):
    version = current_trip_version(trip_id)
    return get_success_data(
        api_client.assign_aircraft(trip_id, version, make_dispatcher_headers(dispatcher_id))
    )


def assign_crew(leg_id, pic_id, sic_id, dispatcher_id="disp-1"):
    return get_success_data(
        api_client.assign_crew(leg_id, pic_id, sic_id, make_dispatcher_headers(dispatcher_id))
    )


def release_leg(leg_id, dispatcher_id="disp-1"):
    return get_success_data(
        api_client.release_leg(leg_id, make_dispatcher_headers(dispatcher_id))
    )


def dispatch_trip(trip_id, dispatcher_id="disp-1"):
    return get_success_data(
        api_client.dispatch_trip(trip_id, make_dispatcher_headers(dispatcher_id))
    )


def complete_leg(leg_id, dispatcher_id="disp-1"):
    return get_success_data(
        api_client.complete_leg(leg_id, make_dispatcher_headers(dispatcher_id))
    )


def settle_trip(trip_id, finance_id="fin-1"):
    version = current_trip_version(trip_id, FINANCE)
    return get_success_data(
        api_client.settle_trip(trip_id, version, make_finance_headers(finance_id))
    )


# ---------------------------------------------------------------------------
# Tier 2: named scenario building blocks
# ---------------------------------------------------------------------------

def setup_bu_and_passenger(bu_code="BU-EXEC", priority_tier="TIER_1",
                           sifl_control_employee=False, annual_budget=100_000_000):
    """BusinessUnit + one passenger homed at it. Returns (bu, pax)."""
    bu = create_business_unit(bu_code=bu_code, annual_flight_budget_cents=annual_budget)
    pax = create_passenger(bu["id"], priority_tier=priority_tier,
                           sifl_control_employee=sifl_control_employee)
    return bu, pax


def setup_fleet_and_crew(aircraft_type="LIGHT_JET", passenger_capacity=6,
                         training_valid_until=FAR_FUTURE_TRAINING):
    """One aircraft + a PIC/SIC pair type-rated for it. Returns (aircraft, pic, sic)."""
    aircraft = create_aircraft(aircraft_type=aircraft_type,
                               passenger_capacity=passenger_capacity)
    pic = create_crew("PIC", (aircraft_type,), training_valid_until)
    sic = create_crew("SIC", (aircraft_type,), training_valid_until)
    return aircraft, pic, sic


def setup_submitted_trip(trip_kind="BUSINESS", personal_use_flag=None,
                         legs=(("2026-08-10T12:00:00Z", "2026-08-10T14:00:00Z", 200),),
                         priority_tier="TIER_1", sifl_control_employee=False,
                         extra_passenger_tiers=()):
    """BU + passenger(s) + DRAFT trip with the given legs, submitted.

    `legs` is a tuple of (departure, arrival, distance) triples.
    Returns (bu, requester, trip, legs_list).
    """
    bu, requester = setup_bu_and_passenger(priority_tier=priority_tier,
                                           sifl_control_employee=sifl_control_employee)
    passenger_ids = [requester["id"]]
    for tier in extra_passenger_tiers:
        other = create_passenger(bu["id"], priority_tier=tier)
        passenger_ids.append(other["id"])
    dep = legs[0][0]
    ret = legs[-1][1]
    trip = create_trip(requester, bu["id"], trip_kind=trip_kind,
                       passenger_ids=passenger_ids, personal_use_flag=personal_use_flag,
                       requested_departure_utc=dep, requested_return_utc=ret)
    legs_list = []
    for i, (dep_i, arr_i, dist_i) in enumerate(legs, start=1):
        legs_list.append(add_leg(trip, requester, leg_sequence=i,
                                 scheduled_departure_utc=dep_i,
                                 scheduled_arrival_utc=arr_i,
                                 distance_statute_miles=dist_i))
    trip = submit_trip(trip, requester)
    return bu, requester, trip, legs_list


def setup_approved_trip(**kwargs):
    """setup_submitted_trip + manager approval. Returns (bu, requester, trip, legs)."""
    bu, requester, trip, legs_list = setup_submitted_trip(**kwargs)
    trip = approve_trip(trip)
    return bu, requester, trip, legs_list


def setup_assigned_trip(aircraft_type="LIGHT_JET", dispatcher_id="disp-1", **kwargs):
    """Full chain through assign-aircraft: trip APPROVED + ASSIGNED, each leg
    AIRCRAFT_ASSIGNED. Returns (bu, requester, trip, legs, aircraft, pic, sic)."""
    aircraft, pic, sic = setup_fleet_and_crew(aircraft_type=aircraft_type)
    bu, requester, trip, legs_list = setup_approved_trip(**kwargs)
    trip = assign_aircraft(trip["id"], dispatcher_id)
    return bu, requester, trip, legs_list, aircraft, pic, sic


def setup_crewed_trip(dispatcher_id="disp-1", **kwargs):
    """setup_assigned_trip + crew pairing on every leg (legs CREWED)."""
    bu, requester, trip, legs_list, aircraft, pic, sic = setup_assigned_trip(
        dispatcher_id=dispatcher_id, **kwargs)
    crewed = [assign_crew(leg["id"], pic["id"], sic["id"], dispatcher_id) for leg in legs_list]
    return bu, requester, trip, crewed, aircraft, pic, sic


def setup_released_trip(dispatcher_id="disp-1", **kwargs):
    """setup_crewed_trip + release on every leg (legs RELEASED)."""
    bu, requester, trip, crewed, aircraft, pic, sic = setup_crewed_trip(
        dispatcher_id=dispatcher_id, **kwargs)
    released = [release_leg(leg["id"], dispatcher_id) for leg in crewed]
    return bu, requester, trip, released, aircraft, pic, sic


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_dispatched_trip(dispatcher_id="disp-1", personal_dispatcher_id=None,
                          finance_id="fin-1", **kwargs):
    """Full chain through dispatch. For personal-use trips (personal_use_flag
    truthy in kwargs) a FinanceAdmin approves personal use first and the
    dispatch runs under a different dispatcher (SoD). Returns the tuple from
    setup_released_trip with the trip refreshed."""
    personal = bool(kwargs.get("personal_use_flag"))
    bu, requester, trip, released, aircraft, pic, sic = setup_released_trip(
        dispatcher_id=dispatcher_id, **kwargs)
    if personal:
        api_client_resp = api_client.approve_personal_use(
            trip["id"], make_finance_headers(finance_id))
        get_success_data(api_client_resp)
        dispatcher_id = personal_dispatcher_id or "disp-2"
    trip = dispatch_trip(trip["id"], dispatcher_id)
    return bu, requester, trip, released, aircraft, pic, sic


def setup_completed_trip(clock_to=None, dispatcher_id="disp-1", **kwargs):
    """Full chain through leg completion: every leg COMPLETED, trip
    assignment_status COMPLETED. Clock is advanced past the final arrival."""
    bu, requester, trip, released, aircraft, pic, sic = setup_dispatched_trip(
        dispatcher_id=dispatcher_id, **kwargs)
    final_arrival = max(leg["scheduled_arrival_utc"] for leg in released)
    reset_clock(clock_to or final_arrival)
    completed = [complete_leg(leg["id"], dispatcher_id) for leg in released]
    trip = get_success_data(api_client.get_trip_request(trip["id"], MANAGER))
    return bu, requester, trip, completed, aircraft, pic, sic


def setup_settled_trip(with_rate_period=True, finance_id="fin-1", **kwargs):
    """Full lifecycle through SETTLED. Returns
    (bu, requester, trip, legs, aircraft, pic, sic, settle_response_data)."""
    if with_rate_period:
        create_default_rate_period()
    bu, requester, trip, completed, aircraft, pic, sic = setup_completed_trip(**kwargs)
    settled = settle_trip(trip["id"], finance_id)
    return bu, requester, settled, completed, aircraft, pic, sic, settled


# ---------------------------------------------------------------------------
# Tier 4: charter-path helpers
# ---------------------------------------------------------------------------

def create_charter_for_trip(trip_id, quoted_cost_cents=1_200_000,
                            aircraft_type_offered="LIGHT_JET", vendor_name="CharterCo"):
    payload = create_charter_supplement_payload(
        trip_id, quoted_cost_cents=quoted_cost_cents,
        aircraft_type_offered=aircraft_type_offered, vendor_name=vendor_name)
    return get_success_data(api_client.create_charter_supplement(payload, DISPATCHER))


def accept_charter(charter_id):
    return get_success_data(api_client.accept_charter(charter_id, MANAGER))


def setup_charter_dispatched_trip(quoted_cost_cents=1_200_000,
                                  legs=(("2026-08-10T12:00:00Z", "2026-08-10T14:00:00Z", 200),),
                                  trip_kind="BUSINESS"):
    """Approved trip with the only fleet aircraft retired before assignment,
    a charter quote recorded and ACCEPTED: trip moves to DISPATCHED under
    vendor operation. Returns (bu, requester, trip, legs_list, charter)."""
    bu, requester, trip, legs_list = setup_approved_trip(trip_kind=trip_kind, legs=legs)
    charter = create_charter_for_trip(trip["id"], quoted_cost_cents=quoted_cost_cents)
    charter = accept_charter(charter["id"])
    trip = get_success_data(api_client.get_trip_request(trip["id"], MANAGER))
    return bu, requester, trip, legs_list, charter


# ---------------------------------------------------------------------------
# Service helpers
# ---------------------------------------------------------------------------

def add_catering(leg_id, quoted_cost_cents=25_000, headcount=1):
    return get_success_data(
        api_client.create_catering_order(
            leg_id, create_catering_order_payload(
                quoted_cost_cents=quoted_cost_cents, headcount=headcount), DISPATCHER)
    )


def confirm_catering(order_id):
    return get_success_data(api_client.confirm_catering_order(order_id, DISPATCHER))


def add_ground_transport(leg_id, quoted_cost_cents=12_000, pickup_minutes_after_arrival=15):
    return get_success_data(
        api_client.create_ground_transport(
            leg_id, create_ground_transport_payload(
                quoted_cost_cents=quoted_cost_cents,
                pickup_minutes_after_arrival=pickup_minutes_after_arrival), DISPATCHER)
    )


def confirm_ground_transport(transport_id):
    return get_success_data(api_client.confirm_ground_transport(transport_id, DISPATCHER))
