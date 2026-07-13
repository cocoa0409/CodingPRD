"""Schedule-time guards: route-open gate, temporal overlap, capacity, item
presence, slot window, vehicle status, and optimistic concurrency.

Difficulty instances: cross_entity_state_dependency/schedule_requires_route_open,
resource_temporal_overlap/{route_window_overlap_on_vehicle,
stop_slot_overlap_with_buffer_on_route}, boundary_precision_check/schedule_empty_item_set.
Corner instances: validations/*, cross_cutting_complexity_layers/schedule_stale_route_version.
"""
from test_helpers import (
    api_client as api,
    validate_success, validate_error,
    schedule_payload,
    create_partner, create_vehicle, create_donor, create_route, open_route,
    create_request, add_item, schedule_request, route_version,
    setup_schedulable_request, setup_scheduled_request,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]

S10 = "2026-03-15T10:00:00Z"
E10 = "2026-03-15T10:30:00Z"
S11 = "2026-03-15T11:00:00Z"
E11 = "2026-03-15T11:30:00Z"


# ─── Difficulty: schedule requires an OPEN route ──────────────────────

def test_schedule_onto_planned_route_rejected():
    """PRD §3.4: "The target route must be `OPEN`; otherwise `ERR_ROUTE_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_route_open
    """
    ctx = setup_schedulable_request(partner_categories=["FURNITURE"], capacity_cf=100,
                                    disposition="DONATION", items=[{"volume_cf": 20}],
                                    open_route_flag=False)
    res = api.schedule_pickup(
        ctx["request"]["id"],
        schedule_payload(ctx["route"]["id"], ctx["route_version"], S10, E10),
        DISPATCHER,
    )
    validate_error(res, "ERR_ROUTE_NOT_OPEN", expected_status=409)


def test_schedule_onto_open_route_succeeds():
    """PRD §3.3: "Only an OPEN route accepts new stops."
    PRD §3.4: "A successful schedule advances the request REQUESTED -> SCHEDULED"

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_route_open
    """
    ctx = setup_schedulable_request(partner_categories=["FURNITURE"], capacity_cf=100,
                                    disposition="DONATION", items=[{"volume_cf": 20}],
                                    open_route_flag=True)
    res = api.schedule_pickup(
        ctx["request"]["id"],
        schedule_payload(ctx["route"]["id"], ctx["route_version"], S10, E10),
        DISPATCHER,
    )
    validate_success(res, 201)
    request = validate_success(api.get_pickup_request(ctx["request"]["id"], DISPATCHER), 200)
    assert request["status"] == "SCHEDULED"


# ─── Difficulty: route-window overlap on a vehicle ────────────────────

def test_overlapping_route_window_on_vehicle_rejected():
    """PRD §3.3: "the new half-open window must not overlap any non-CLOSED route
    already booked on the same vehicle_id and service_date."
    PRD §3.3: "A genuine overlap is rejected with ERR_ROUTE_WINDOW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/route_window_overlap_on_vehicle
    """
    partner = create_partner()
    vehicle = create_vehicle(capacity_cf=100)
    create_route(vehicle["id"], partner["id"],
                 window_start="2026-03-15T09:00:00Z", window_end="2026-03-15T12:00:00Z")
    res = api.create_route(
        {"vehicle_id": vehicle["id"], "partner_id": partner["id"],
         "service_date": "2026-03-15",
         "window_start": "2026-03-15T11:00:00Z", "window_end": "2026-03-15T13:00:00Z"},
        DISPATCHER,
    )
    validate_error(res, "ERR_ROUTE_WINDOW_CONFLICT", expected_status=409)


def test_adjacent_route_window_on_vehicle_allowed():
    """PRD §3.3: "Because the window is half-open, exact adjacency is permitted
    — a new route whose window_start equals a prior route's window_end does not
    overlap it."

    Design: Difficulty/resource_temporal_overlap/route_window_overlap_on_vehicle
    """
    partner = create_partner()
    vehicle = create_vehicle(capacity_cf=100)
    create_route(vehicle["id"], partner["id"],
                 window_start="2026-03-15T09:00:00Z", window_end="2026-03-15T12:00:00Z")
    res = api.create_route(
        {"vehicle_id": vehicle["id"], "partner_id": partner["id"],
         "service_date": "2026-03-15",
         "window_start": "2026-03-15T12:00:00Z", "window_end": "2026-03-15T13:00:00Z"},
        DISPATCHER,
    )
    validate_success(res, 201)


# ─── Difficulty: stop-slot buffer overlap on a route ──────────────────

def _second_request_on_route(ctx, volume_cf=20):
    """Create a second REQUESTED FURNITURE request owned by ctx's donor."""
    req = create_request(ctx["donor"]["id"], ctx["partner"]["id"], disposition="DONATION")
    add_item(req["id"], ctx["donor"]["id"], category="FURNITURE", volume_cf=volume_cf)
    return req


def test_stop_slot_within_travel_buffer_rejected():
    """PRD §3.4: "Considering every RESERVED or SERVICED stop already on the
    route, expand each such stop's slot by a 15-minute travel buffer on each
    side; if the requested slot overlaps any so-expanded slot, the schedule is
    rejected with ERR_STOP_SLOT_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/stop_slot_overlap_with_buffer_on_route
    """
    ctx = setup_scheduled_request(partner_categories=["FURNITURE"], capacity_cf=300,
                                  disposition="DONATION", items=[{"volume_cf": 20}],
                                  slot_start=S10, slot_end=E10)
    req_b = _second_request_on_route(ctx)
    res = api.schedule_pickup(
        req_b["id"],
        schedule_payload(ctx["route"]["id"], route_version(ctx["route"]["id"]),
                         "2026-03-15T10:40:00Z", "2026-03-15T11:00:00Z"),
        DISPATCHER,
    )
    validate_error(res, "ERR_STOP_SLOT_CONFLICT", expected_status=409)


def test_stop_slot_exactly_at_buffer_gap_allowed():
    """PRD §3.4: "Equivalently, the gap between the requested slot and any
    adjacent existing stop must be at least 15 minutes."

    Design: Difficulty/resource_temporal_overlap/stop_slot_overlap_with_buffer_on_route
    """
    ctx = setup_scheduled_request(partner_categories=["FURNITURE"], capacity_cf=300,
                                  disposition="DONATION", items=[{"volume_cf": 20}],
                                  slot_start=S10, slot_end=E10)
    req_b = _second_request_on_route(ctx)
    # Existing stop ends 10:30; a 15-minute gap makes 10:45 the earliest allowed start.
    res = api.schedule_pickup(
        req_b["id"],
        schedule_payload(ctx["route"]["id"], route_version(ctx["route"]["id"]),
                         "2026-03-15T10:45:00Z", "2026-03-15T11:15:00Z"),
        DISPATCHER,
    )
    validate_success(res, 201)


# ─── Difficulty: empty item set boundary ──────────────────────────────

def test_schedule_with_zero_items_rejected():
    """PRD §3.4: "The request must have at least one donation item; a request
    with none is rejected with ERR_NO_ITEMS."

    Design: Difficulty/boundary_precision_check/schedule_empty_item_set
    """
    ctx = setup_schedulable_request(partner_categories=["FURNITURE"], capacity_cf=100,
                                    disposition="DONATION", items=[])
    res = api.schedule_pickup(
        ctx["request"]["id"],
        schedule_payload(ctx["route"]["id"], ctx["route_version"], S10, E10),
        DISPATCHER,
    )
    validate_error(res, "ERR_NO_ITEMS", expected_status=422)


def test_schedule_with_one_item_allowed():
    """PRD §3.4: "The request must have at least one donation item; a request
    with none is rejected with ERR_NO_ITEMS."

    Design: Difficulty/boundary_precision_check/schedule_empty_item_set
    """
    ctx = setup_schedulable_request(partner_categories=["FURNITURE"], capacity_cf=100,
                                    disposition="DONATION", items=[{"volume_cf": 20}])
    res = api.schedule_pickup(
        ctx["request"]["id"],
        schedule_payload(ctx["route"]["id"], ctx["route_version"], S10, E10),
        DISPATCHER,
    )
    validate_success(res, 201)


# ─── Corner: field validity, slot window, vehicle status, category, capacity ─

def test_create_route_window_end_before_start_rejected():
    """PRD §2.10: "Field-level input validity — required fields present, enum
    values in range, numeric fields within their declared bounds, and
    window/slot end strictly after start (ERR_INVALID_REQUEST, 400)."

    Design: Corner/validations/create_route_window_end_before_start_returns_invalid_request
    """
    partner = create_partner()
    vehicle = create_vehicle(capacity_cf=100)
    res = api.create_route(
        {"vehicle_id": vehicle["id"], "partner_id": partner["id"],
         "service_date": "2026-03-15",
         "window_start": "2026-03-15T12:00:00Z", "window_end": "2026-03-15T09:00:00Z"},
        DISPATCHER,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_schedule_slot_before_window_start_rejected():
    """PRD §3.4: "The requested slot must sit inside the route window and be
    well-formed: slot_start at or after the route's window_start, slot_end at or
    before the route's window_end, and slot_end strictly after slot_start; any
    violation yields ERR_SLOT_OUTSIDE_WINDOW."

    Design: Corner/validations/schedule_slot_outside_window_returns_error
    """
    ctx = setup_schedulable_request(partner_categories=["FURNITURE"], capacity_cf=100,
                                    disposition="DONATION", items=[{"volume_cf": 20}])
    res = api.schedule_pickup(
        ctx["request"]["id"],
        schedule_payload(ctx["route"]["id"], ctx["route_version"],
                         "2026-03-15T08:00:00Z", "2026-03-15T08:30:00Z"),
        DISPATCHER,
    )
    validate_error(res, "ERR_SLOT_OUTSIDE_WINDOW", expected_status=422)


def test_open_route_on_out_of_service_vehicle_rejected():
    """PRD §3.3: "opening a route onto an `OUT_OF_SERVICE` vehicle is refused with `ERR_VEHICLE_OUT_OF_SERVICE`"

    Design: Corner/validations/open_route_on_out_of_service_vehicle_returns_error
    """
    partner = create_partner()
    vehicle = create_vehicle(capacity_cf=100, status="OUT_OF_SERVICE")
    route = create_route(vehicle["id"], partner["id"])
    res = api.open_route(route["id"], DISPATCHER)
    validate_error(res, "ERR_VEHICLE_OUT_OF_SERVICE", expected_status=409)


def test_donation_item_category_not_accepted_rejected():
    """PRD §3.4: "If the request's disposition is DONATION, every one of its
    items must have a category that is contained in the partner's
    accepted_categories; any item outside that set yields
    ERR_CATEGORY_NOT_ACCEPTED."

    Design: Corner/validations/category_not_accepted_on_donation_schedule_returns_error
    """
    ctx = setup_schedulable_request(partner_categories=["FURNITURE"], capacity_cf=100,
                                    disposition="DONATION",
                                    items=[{"category": "ELECTRONICS", "volume_cf": 20}])
    res = api.schedule_pickup(
        ctx["request"]["id"],
        schedule_payload(ctx["route"]["id"], ctx["route_version"], S10, E10),
        DISPATCHER,
    )
    validate_error(res, "ERR_CATEGORY_NOT_ACCEPTED", expected_status=422)


def test_route_capacity_exceeded_on_schedule_rejected():
    """PRD §3.4: "The truck must have room: the route's current
    reserved_volume_cf plus the request's declared_volume_cf must not exceed the
    vehicle's capacity_cf; otherwise ERR_ROUTE_CAPACITY_EXCEEDED."

    Design: Corner/validations/route_capacity_exceeded_on_schedule_returns_error
    """
    ctx = setup_scheduled_request(partner_categories=["FURNITURE"], capacity_cf=50,
                                  disposition="DONATION", items=[{"volume_cf": 40}],
                                  slot_start=S10, slot_end=E10)
    req_b = _second_request_on_route(ctx, volume_cf=20)
    res = api.schedule_pickup(
        req_b["id"],
        schedule_payload(ctx["route"]["id"], route_version(ctx["route"]["id"]), S11, E11),
        DISPATCHER,
    )
    validate_error(res, "ERR_ROUTE_CAPACITY_EXCEEDED", expected_status=409)


# ─── Corner: optimistic concurrency (stale route version) ─────────────

def test_schedule_with_stale_route_version_rejected():
    """PRD §2.7: "If another writer has added or removed a stop on that route
    since the dispatcher read it, the route's version (and its
    reserved_volume_cf) will have advanced, the submitted value will no longer
    match, and the schedule is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/schedule_stale_route_version_returns_412
    """
    prov = setup_schedulable_request(partner_categories=["FURNITURE"], capacity_cf=300,
                                     disposition="DONATION", items=[{"volume_cf": 20}])
    stale_version = prov["route_version"]
    req_b = _second_request_on_route(prov)
    # First schedule bumps route.version away from stale_version.
    schedule_request(prov["request"]["id"], prov["route"]["id"], S10, E10,
                     expected_route_version=stale_version)
    res = api.schedule_pickup(
        req_b["id"],
        schedule_payload(prov["route"]["id"], stale_version, S11, E11),
        DISPATCHER,
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
