"""Composite setup helpers for the hospital transport domain.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Transporter calls are entity-backed (X-User-ID must equal
the acting Transporter record's id), so every helper that acts as a
transporter builds headers via make_transporter_headers(transporter_id).
Clinician, dispatcher, housekeeping, and supervisor identities are opaque;
their shared constants below are canonical.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CLOCK_START,
    COVERING_SHIFT_END,
    COVERING_SHIFT_START,
    DEFAULT_ASSET_TAGS,
    EDGE_HUB_WARD,
    EDGE_WARD_IMG,
)
from .factories import (
    create_cleaning_advance_payload,
    create_close_payload,
    create_demand_curve_payload,
    create_equipment_asset_payload,
    create_location_payload,
    create_offer_payload,
    create_request_payload,
    create_shift_payload,
    create_transporter_payload,
    create_travel_edge_payload,
    create_trip_event_payload,
)
from .test_users import (
    TEST_USERS,
    make_clinician_headers,
    make_housekeeping_headers,
    make_supervisor_headers,
    make_transporter_headers,
)

# Shared opaque-identity headers.
SUP = TEST_USERS["supervisor_headers"]
DISP = TEST_USERS["dispatcher_headers"]
CLIN = TEST_USERS["clinician_headers"]
HK = TEST_USERS["housekeeping_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Pin the logical clock (PRD §2.5). Returns the clock payload."""
    return get_success_data(api_client.set_clock(to_iso8601, SUP))


def run_sweep():
    """Run the time-driven sweep. Returns {offers_expired, requests_escalated,
    sla_records_created} (PRD §3.6)."""
    return get_success_data(api_client.run_sweeps(SUP))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_location(code, name=None, location_type="WARD", zone_code="Z1"):
    payload = create_location_payload(code, name or code, location_type, zone_code)
    return get_success_data(api_client.create_location(payload, SUP))


def create_travel_edge(from_location_id, to_location_id, base_minutes,
                       airborne_minutes):
    payload = create_travel_edge_payload(from_location_id, to_location_id,
                                         base_minutes, airborne_minutes)
    return get_success_data(api_client.create_travel_edge(payload, SUP))


def add_transporter(name, home_location_id, certified_equipment=None,
                    oxygen_certified=False, isolation_certified=False):
    """Register a transporter (born OFF_SHIFT, located at home)."""
    payload = create_transporter_payload(
        name, home_location_id,
        certified_equipment=certified_equipment,
        oxygen_certified=True if oxygen_certified else None,
        isolation_certified=True if isolation_certified else None,
    )
    return get_success_data(api_client.create_transporter(payload, SUP))


def add_covering_shift(transporter_id, shift_start=COVERING_SHIFT_START,
                       shift_end=COVERING_SHIFT_END):
    """Plan a PLANNED shift; the defaults cover the whole fixture window."""
    payload = create_shift_payload(transporter_id, shift_start, shift_end)
    return get_success_data(api_client.create_staffing_shift(payload, SUP))


def clock_in_transporter(transporter_id):
    """Clock a transporter in as themselves (entity-backed identity)."""
    return get_success_data(api_client.set_transporter_status(
        transporter_id, {"status": "ON_SHIFT"},
        make_transporter_headers(transporter_id)))


def add_on_shift_transporter(name, home_location_id, certified_equipment=None,
                             oxygen_certified=False, isolation_certified=False):
    """Register + plan a covering shift + clock in. Returns the transporter."""
    transporter = add_transporter(
        name, home_location_id,
        certified_equipment=certified_equipment,
        oxygen_certified=oxygen_certified,
        isolation_certified=isolation_certified,
    )
    add_covering_shift(transporter["id"])
    clock_in_transporter(transporter["id"])
    return transporter


def add_equipment_asset(asset_tag, equipment_type, current_location_id):
    """Register an equipment asset (born AVAILABLE)."""
    payload = create_equipment_asset_payload(asset_tag, equipment_type,
                                             current_location_id)
    return get_success_data(api_client.create_equipment_asset(payload, SUP))


def create_transport_request(patient_ref, origin_location_id,
                             destination_location_id, priority="ROUTINE",
                             required_equipment="PORTER_ONLY",
                             clinician_id="clin-1", oxygen_required=None,
                             isolation_precaution=None,
                             scheduled_pickup_time=None,
                             appointment_deadline=None):
    """Place a transport request as a RequestingClinician (born QUEUED,
    posture ON_TRACK)."""
    payload = create_request_payload(
        patient_ref, origin_location_id, destination_location_id,
        priority, required_equipment,
        oxygen_required=oxygen_required,
        isolation_precaution=isolation_precaution,
        scheduled_pickup_time=scheduled_pickup_time,
        appointment_deadline=appointment_deadline,
    )
    return get_success_data(
        api_client.create_request(payload, make_clinician_headers(clinician_id)))


def add_demand_curve(day_type, hour_block, priority, expected_requests,
                     mean_service_minutes):
    payload = create_demand_curve_payload(day_type, hour_block, priority,
                                          expected_requests,
                                          mean_service_minutes)
    return get_success_data(api_client.create_demand_curve(payload, SUP))


# ---------------------------------------------------------------------------
# Tier 1: reads and thin action wrappers
# ---------------------------------------------------------------------------

def get_request(request_id, headers=DISP):
    return get_success_data(api_client.get_request(request_id, headers))


def get_transporter(transporter_id, headers=DISP):
    return get_success_data(api_client.get_transporter(transporter_id, headers))


def get_asset(asset_id, headers=DISP):
    return get_success_data(api_client.get_equipment_asset(asset_id, headers))


def list_requests(headers=DISP, params=None):
    """Returns (data, meta) from the paginated list endpoint."""
    return validate_paginated(api_client.list_requests(headers, params=params))


def list_equipment_assets(headers=DISP, params=None):
    return validate_paginated(
        api_client.list_equipment_assets(headers, params=params))


def list_request_offers(request_id, headers=DISP, params=None):
    """Offers of a request, oldest first. Returns (data, meta)."""
    return validate_paginated(
        api_client.list_request_offers(request_id, headers, params=params))


def list_delay_records(request_id, headers=DISP, params=None):
    """Delay records of a request, oldest first. Returns (data, meta)."""
    return validate_paginated(
        api_client.list_delay_records(request_id, headers, params=params))


def list_cleaning_tasks(headers=HK, params=None):
    return validate_paginated(
        api_client.list_cleaning_tasks(headers, params=params))


def find_cleaning_task(equipment_asset_id=None, transport_request_id=None):
    """Locate the single cleaning task for an asset or request."""
    params = {}
    if equipment_asset_id is not None:
        params["equipment_asset_id"] = equipment_asset_id
    if transport_request_id is not None:
        params["transport_request_id"] = transport_request_id
    data, _meta = list_cleaning_tasks(params=params)
    assert len(data) >= 1, "Setup failed: expected a cleaning task to exist"
    return data[0]


def get_cleaning_task(task_id, headers=HK):
    return get_success_data(api_client.get_cleaning_task(task_id, headers))


def create_dispatch_offer(request, transporter_id=None):
    """Create a PENDING offer on a QUEUED request, threading the request's
    current version for the optimistic-concurrency guard (PRD §2.7).
    `request` is the request dict carrying id and version."""
    payload = create_offer_payload(request["version"], transporter_id)
    return get_success_data(api_client.create_offer(request["id"], payload, DISP))


def respond_to_offer(offer_id, decision, transporter_id):
    """Raw respond call as the addressed transporter."""
    return api_client.respond_offer(
        offer_id, {"decision": decision},
        make_transporter_headers(transporter_id))


def accept_offer(offer_id, transporter_id):
    return get_success_data(respond_to_offer(offer_id, "ACCEPT", transporter_id))


def decline_offer(offer_id, transporter_id):
    return get_success_data(respond_to_offer(offer_id, "DECLINE", transporter_id))


def post_trip_event(request_id, event, transporter_id=None, headers=None,
                    cause_code=None):
    """Raw trip-event call. Defaults to acting as the assigned transporter
    (entity-backed identity); pass headers to act as a dispatcher."""
    payload = create_trip_event_payload(event, cause_code)
    hdrs = headers if headers is not None else make_transporter_headers(transporter_id)
    return api_client.post_trip_event(request_id, payload, hdrs)


def trip_event_ok(request_id, event, transporter_id=None, headers=None,
                  cause_code=None):
    return get_success_data(post_trip_event(
        request_id, event, transporter_id=transporter_id, headers=headers,
        cause_code=cause_code))


def close_request(request_id, action, headers, reason=None, duplicate_of_id=None):
    """Raw close call (CANCEL or SUPERSEDE)."""
    payload = create_close_payload(action, reason=reason,
                                   duplicate_of_id=duplicate_of_id)
    return api_client.close_request(request_id, payload, headers)


def close_request_ok(request_id, action, headers, reason=None,
                     duplicate_of_id=None):
    return get_success_data(close_request(
        request_id, action, headers, reason=reason,
        duplicate_of_id=duplicate_of_id))


def advance_cleaning(task_id, to_state, headers, note=None):
    """Raw cleaning advance call."""
    payload = create_cleaning_advance_payload(to_state, note=note)
    return api_client.advance_cleaning_task(task_id, payload, headers)


def advance_cleaning_ok(task_id, to_state, headers, note=None):
    return get_success_data(advance_cleaning(task_id, to_state, headers,
                                             note=note))


def set_asset_service_status(asset_id, service_status):
    return get_success_data(api_client.set_equipment_service_status(
        asset_id, {"service_status": service_status}, SUP))


def cancel_shift(shift_id):
    return get_success_data(api_client.set_shift_status(
        shift_id, {"status": "CANCELLED"}, SUP))


def get_adequacy(date, hour_block, window_hours, variant, headers=SUP):
    """Computed staffing-adequacy read. Returns
    {required_transporters, scheduled_transporters, gap} (PRD §3.8)."""
    return get_success_data(api_client.get_staffing_adequacy(
        headers, params={"date": date, "hour_block": hour_block,
                         "window_hours": window_hours, "variant": variant}))


# ---------------------------------------------------------------------------
# Tier 2: site and roster composites
# ---------------------------------------------------------------------------

def setup_transport_site(clock=CLOCK_START):
    """Pin the logical clock and register the standard estate: HUB (OTHER),
    W4 (WARD), IMG (IMAGING) plus edges HUB->W4 (8/12) and W4->IMG (10/16).
    Pass clock=None to leave the clock at its startup default."""
    if clock is not None:
        set_clock(clock)
    hub = create_location("HUB", "Hub", "OTHER", "Z1")
    ward = create_location("W4", "Ward 4", "WARD", "Z1")
    img = create_location("IMG", "Imaging", "IMAGING", "Z2")
    edge_hub_ward = create_travel_edge(hub["id"], ward["id"], *EDGE_HUB_WARD)
    edge_ward_img = create_travel_edge(ward["id"], img["id"], *EDGE_WARD_IMG)
    return {
        "hub": hub,
        "ward": ward,
        "img": img,
        "edge_hub_ward": edge_hub_ward,
        "edge_ward_img": edge_ward_img,
    }


def setup_two_transporter_board(site=None, equipment="WHEELCHAIR", clock=CLOCK_START,
                                asset_tag=None, asset_type=None):
    """Standard dispatch board: site plus two ON_SHIFT transporters certified
    for `equipment` and one matching asset at W4. T One is created one logical
    minute before T Two so the created_at tie-break between them (PRD §3.4) is
    strict; the clock is left two minutes past `clock` on return.
    Returns {"site", "t1", "t2", "asset"}."""
    site = site or setup_transport_site(clock=clock)
    certs = {"certified_equipment": [equipment]} if equipment != "PORTER_ONLY" else {}
    t1 = add_on_shift_transporter("T One", site["hub"]["id"], **certs)
    if clock is not None:
        set_clock("2026-08-01T00:01:00Z")
    t2 = add_on_shift_transporter("T Two", site["hub"]["id"], **certs)
    if clock is not None:
        set_clock("2026-08-01T00:02:00Z")
    asset = None
    if equipment != "PORTER_ONLY":
        asset = add_equipment_asset(asset_tag or DEFAULT_ASSET_TAGS[equipment],
                                    asset_type or equipment, site["ward"]["id"])
    return {"site": site, "t1": t1, "t2": t2, "asset": asset}


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle composites
# ---------------------------------------------------------------------------

def setup_assigned_trip(equipment="WHEELCHAIR", isolation="NONE",
                        oxygen_required=False, priority="ROUTINE",
                        patient_ref="P1", appointment_deadline=None,
                        transporter_name="T One", asset_tag=None, site=None,
                        clock=CLOCK_START, origin_key="ward",
                        destination_key="img"):
    """QUEUED request + offer + ACCEPT -> ASSIGNED. The transporter carries
    exactly the certifications the trip demands. Returns a world dict with
    keys: site, transporter, asset (None for PORTER_ONLY), request, offer."""
    site = site or setup_transport_site(clock=clock)
    certs = {}
    if equipment != "PORTER_ONLY":
        certs["certified_equipment"] = [equipment]
    if oxygen_required:
        certs["oxygen_certified"] = True
    if isolation != "NONE":
        certs["isolation_certified"] = True
    transporter = add_on_shift_transporter(transporter_name,
                                           site["hub"]["id"], **certs)
    asset = None
    if equipment != "PORTER_ONLY":
        asset = add_equipment_asset(asset_tag or DEFAULT_ASSET_TAGS[equipment],
                                    equipment, site[origin_key]["id"])
    request = create_transport_request(
        patient_ref, site[origin_key]["id"], site[destination_key]["id"],
        priority=priority, required_equipment=equipment,
        oxygen_required=True if oxygen_required else None,
        isolation_precaution=isolation if isolation != "NONE" else None,
        appointment_deadline=appointment_deadline)
    offer = create_dispatch_offer(request, transporter_id=transporter["id"])
    accept_offer(offer["id"], transporter["id"])
    request = get_request(request["id"])
    return {"site": site, "transporter": transporter, "asset": asset,
            "request": request, "offer": offer}


def setup_trip_in_transit(arrive_at=None, **kwargs):
    """An assigned trip advanced through ARRIVE_PICKUP and PICKUP
    (IN_TRANSIT). `arrive_at` pins the clock before ARRIVE_PICKUP."""
    world = setup_assigned_trip(**kwargs)
    transporter = world["transporter"]
    request_id = world["request"]["id"]
    if arrive_at is not None:
        set_clock(arrive_at)
    trip_event_ok(request_id, "ARRIVE_PICKUP", transporter_id=transporter["id"])
    trip_event_ok(request_id, "PICKUP", transporter_id=transporter["id"])
    world["request"] = get_request(request_id)
    return world


def setup_completed_trip(arrive_at=None, complete_at=None, cause_code=None,
                         **kwargs):
    """A trip driven to COMPLETED. When an asset was assigned, the world dict
    gains its freshly spawned cleaning task under "cleaning_task"."""
    world = setup_trip_in_transit(arrive_at=arrive_at, **kwargs)
    transporter = world["transporter"]
    request_id = world["request"]["id"]
    if complete_at is not None:
        set_clock(complete_at)
    trip_event_ok(request_id, "COMPLETE", transporter_id=transporter["id"],
                  cause_code=cause_code)
    world["request"] = get_request(request_id)
    if world["asset"] is not None:
        world["cleaning_task"] = find_cleaning_task(
            equipment_asset_id=world["asset"]["id"])
    return world


def setup_cleaning_in_progress(isolation="NONE", start_at=None, **kwargs):
    """A completed trip whose cleaning task has been started by housekeeping
    (task IN_PROGRESS, asset IN_CLEANING). `start_at` pins the clock (and
    therefore started_at) before the IN_PROGRESS advance."""
    world = setup_completed_trip(isolation=isolation, **kwargs)
    if start_at is not None:
        set_clock(start_at)
    advance_cleaning_ok(world["cleaning_task"]["id"], "IN_PROGRESS", HK)
    world["cleaning_task"] = get_cleaning_task(world["cleaning_task"]["id"])
    return world


# ---------------------------------------------------------------------------
# Tier 4: staffing adequacy scenario
# ---------------------------------------------------------------------------

# Six WEEKDAY demand rows over hour blocks 9 and 10: block 9 carries
# 2*30 + 4*40 + 5*58 = 510 expected service-minutes, block 10 carries
# 1*30 + 1*40 + 2*67 = 204 (PRD §3.8 FORECAST inputs).
STAFFING_DEMAND_ROWS = [
    ("WEEKDAY", 9, "STAT", 2, 30),
    ("WEEKDAY", 9, "URGENT", 4, 40),
    ("WEEKDAY", 9, "ROUTINE", 5, 58),
    ("WEEKDAY", 10, "STAT", 1, 30),
    ("WEEKDAY", 10, "URGENT", 1, 40),
    ("WEEKDAY", 10, "ROUTINE", 2, 67),
]


def setup_staffing_demand_rows():
    """Create just the six WEEKDAY demand rows for blocks 9 and 10."""
    for day_type, hour_block, priority, expected, mean in STAFFING_DEMAND_ROWS:
        add_demand_curve(day_type, hour_block, priority, expected, mean)


def setup_staffing_adequacy_scenario():
    """Demand rows for blocks 9/10 plus three transporters (T A, T B, T C)
    each with a PLANNED shift 2026-08-03T08:00-12:00 covering both blocks;
    clock pinned at 2026-08-03T12:00:00Z (a Monday)."""
    set_clock("2026-08-03T12:00:00Z")
    hub = create_location("HUB", "Hub", "OTHER", "Z1")
    setup_staffing_demand_rows()
    transporters = [
        add_transporter(name, hub["id"]) for name in ("T A", "T B", "T C")
    ]
    for transporter in transporters:
        add_covering_shift(transporter["id"],
                           shift_start="2026-08-03T08:00:00Z",
                           shift_end="2026-08-03T12:00:00Z")
    return {"hub": hub, "transporters": transporters}
