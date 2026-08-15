"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch via PRD-declared endpoints and
uses get_success_data() so a setup failure surfaces as a clear setup error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_dimensioner_scan_payload,
    create_dock_door_payload,
    create_inspection_payload,
    create_linehaul_leg_payload,
    create_manifest_entry_payload,
    create_osd_case_payload,
    create_pickup_route_payload,
    create_pickup_stop_payload,
    create_seal_payload,
    create_shipment_payload,
    create_sortation_batch_payload,
    create_terminal_payload,
    create_trailer_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["terminal_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
DOCK = TEST_USERS["dock_supervisor_headers"]
CLERK = TEST_USERS["rating_clerk_headers"]
OSD = TEST_USERS["osd_clerk_headers"]


# --- Tier 1: single-entity creation -----------------------------------------

def make_terminal(code="CHI", name="Chicago", dock_doors=12, **overrides):
    """Register one ACTIVE terminal."""
    resp = api_client.create_terminal(
        create_terminal_payload(code, name, dock_doors, **overrides), headers=ADMIN
    )
    return get_success_data(resp)


def make_terminal_pair(origin_code="CHI", dest_code="ATL", dest_overrides=None):
    """Two ACTIVE terminals; returns (origin, destination)."""
    origin = make_terminal(code=origin_code, name="Chicago", dock_doors=12)
    dest = make_terminal(code=dest_code, name="Atlanta", dock_doors=10,
                         **(dest_overrides or {}))
    return origin, dest


def make_shipment(origin_terminal_id, destination_terminal_id, **overrides):
    """Tender one shipment (born UNRATED / TENDERED)."""
    resp = api_client.create_shipment(
        create_shipment_payload(origin_terminal_id, destination_terminal_id, **overrides),
        headers=DISP,
    )
    return get_success_data(resp)


def make_rated_shipment(origin_terminal_id, destination_terminal_id, **overrides):
    """Tender + GROSS-variant rate; returns the RATED shipment."""
    shipment = make_shipment(origin_terminal_id, destination_terminal_id, **overrides)
    resp = api_client.rate_shipment(shipment["id"], headers=CLERK)
    return get_success_data(resp)


def make_route(terminal_id, **overrides):
    """Plan one PLANNED pickup route."""
    resp = api_client.create_pickup_route(
        create_pickup_route_payload(terminal_id, **overrides), headers=DISP
    )
    return get_success_data(resp)


def add_stop(route_id, shipment_id, stop_sequence=1, planned_arrival_minute=540):
    """Add one PLANNED stop to a route."""
    resp = api_client.create_pickup_stop(
        create_pickup_stop_payload(
            route_id, shipment_id,
            stop_sequence=stop_sequence,
            planned_arrival_minute=planned_arrival_minute,
        ),
        headers=DISP,
    )
    return get_success_data(resp)


def make_door(terminal_id, door_number, door_kind="OUTBOUND"):
    """Register one AVAILABLE dock door."""
    resp = api_client.create_dock_door(
        create_dock_door_payload(terminal_id, door_number, door_kind), headers=DOCK
    )
    return get_success_data(resp)


def make_trailer(terminal_id, destination_terminal_id, door_id=None, door_number=21,
                 max_weight_lbs=40000, max_cube_cuft=3500):
    """Spot one LOADING trailer (creates its OUTBOUND door when none is given)."""
    if door_id is None:
        door_id = make_door(terminal_id, door_number, "OUTBOUND")["id"]
    resp = api_client.create_trailer(
        create_trailer_payload(
            terminal_id, destination_terminal_id, door_id,
            max_weight_lbs=max_weight_lbs, max_cube_cuft=max_cube_cuft,
        ),
        headers=DOCK,
    )
    return get_success_data(resp)


def get_trailer(trailer_id):
    return get_success_data(api_client.get_trailer(trailer_id, headers=DOCK))


def get_shipment(shipment_id):
    return get_success_data(api_client.get_shipment(shipment_id, headers=DISP))


# --- Tier 2: pickup flow (TENDERED -> ON_DOCK) --------------------------------

def move_shipment_on_dock(shipment_id, terminal_id, route=None, stop_sequence=1,
                          planned_arrival_minute=540):
    """Drive a TENDERED shipment to ON_DOCK via route -> stop -> dispatch ->
    arrive -> complete. When a shared route dict is passed in it may carry a
    stale status, so the route is re-read before deciding to dispatch.
    Returns {"route", "stop"}."""
    if route is None:
        route = make_route(terminal_id)
    stop = add_stop(route["id"], shipment_id,
                    stop_sequence=stop_sequence,
                    planned_arrival_minute=planned_arrival_minute)
    fresh = get_success_data(api_client.get_pickup_route(route["id"], headers=DISP))
    if fresh.get("status") == "PLANNED":
        get_success_data(api_client.dispatch_route(route["id"], headers=DISP))
    get_success_data(api_client.arrive_stop(stop["id"], headers=DISP))
    stop = get_success_data(api_client.complete_stop(stop["id"], headers=DISP))
    return {"route": route, "stop": stop}


def make_on_dock_shipment(origin_terminal_id, destination_terminal_id, route=None,
                          stop_sequence=1, planned_arrival_minute=540,
                          **shipment_overrides):
    """RATED and ON_DOCK shipment. Returns {"shipment", "route", "stop"}."""
    shipment = make_rated_shipment(origin_terminal_id, destination_terminal_id,
                                   **shipment_overrides)
    ctx = move_shipment_on_dock(
        shipment["id"], origin_terminal_id, route=route,
        stop_sequence=stop_sequence, planned_arrival_minute=planned_arrival_minute,
    )
    return {"shipment": get_shipment(shipment["id"]), "route": ctx["route"],
            "stop": ctx["stop"]}


# --- Tier 3: trailer ledger writes (OCC-guarded) ------------------------------

def add_manifest_entry(trailer_id, shipment_id, load_position=1):
    """Manifest a shipment with a fresh OCC read of the trailer version.
    Returns the ACTIVE ManifestEntry."""
    version = get_trailer(trailer_id)["version"]
    resp = api_client.create_manifest_entry(
        trailer_id,
        create_manifest_entry_payload(shipment_id, version, load_position),
        headers=DOCK,
    )
    return get_success_data(resp)


def seal_trailer_fresh(trailer_id):
    """Seal with a fresh OCC read of the trailer version."""
    version = get_trailer(trailer_id)["version"]
    resp = api_client.seal_trailer(
        trailer_id, create_seal_payload(version), headers=DOCK
    )
    return get_success_data(resp)


def make_ready_trailer(terminal_id, destination_terminal_id, shipment_overrides=None,
                       max_weight_lbs=40000, max_cube_cuft=3500, door_number=21):
    """LOADING trailer + one RATED/ON_DOCK shipment manifested + mark-ready.
    Default shipment (26000 lbs, 96x96x96 on a 40000-lb cap) reaches
    utilization 65.0, clearing the 60.0 readiness floor.
    Returns {"trailer", "shipment", "entry", "route", "stop"}."""
    trailer = make_trailer(terminal_id, destination_terminal_id,
                           door_number=door_number, max_weight_lbs=max_weight_lbs,
                           max_cube_cuft=max_cube_cuft)
    overrides = {"actual_weight_lbs": 26000, "length_in": 96, "width_in": 96,
                 "height_in": 96, "nmfc_class": "CLASS_60",
                 "service_standard": "STANDARD"}
    overrides.update(shipment_overrides or {})
    ctx = make_on_dock_shipment(terminal_id, destination_terminal_id, **overrides)
    entry = add_manifest_entry(trailer["id"], ctx["shipment"]["id"])
    resp = api_client.mark_trailer_ready(trailer["id"], headers=DOCK)
    trailer = get_success_data(resp)
    return {"trailer": trailer, "shipment": ctx["shipment"], "entry": entry,
            "route": ctx["route"], "stop": ctx["stop"]}


def make_sealed_trailer(terminal_id, destination_terminal_id, shipment_overrides=None,
                        max_weight_lbs=40000, max_cube_cuft=3500, door_number=21):
    """READY trailer then sealed. Returns the ready-context with SEALED trailer."""
    ctx = make_ready_trailer(terminal_id, destination_terminal_id,
                             shipment_overrides=shipment_overrides,
                             max_weight_lbs=max_weight_lbs,
                             max_cube_cuft=max_cube_cuft, door_number=door_number)
    ctx["trailer"] = seal_trailer_fresh(ctx["trailer"]["id"])
    return ctx


# --- Tier 4: linehaul legs and relays ------------------------------------------

def set_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, headers=ADMIN)
    return get_success_data(resp)


def plan_leg(origin_terminal_id, destination_terminal_id, trailer_id,
             planned_departure_utc, planned_arrival_utc, relay_sequence=1):
    resp = api_client.create_linehaul_leg(
        create_linehaul_leg_payload(
            origin_terminal_id, destination_terminal_id, trailer_id,
            planned_departure_utc, planned_arrival_utc, relay_sequence,
        ),
        headers=DISP,
    )
    return get_success_data(resp)


def depart_leg(leg_id, at_utc=None):
    """Depart a leg; optionally set the logical clock first so the stamped
    actual_departure_utc is deterministic."""
    if at_utc is not None:
        set_clock(at_utc)
    return get_success_data(api_client.depart_leg(leg_id, headers=DISP))


def arrive_leg(leg_id, at_utc=None):
    """Arrive a leg; optionally set the logical clock first."""
    if at_utc is not None:
        set_clock(at_utc)
    return get_success_data(api_client.arrive_leg(leg_id, headers=DISP))


def make_relay_chain(origin_code="CHI", relay_code="KCY", dest_code="DEN",
                     leg1_dep="2026-08-02T10:00:00Z",
                     leg1_arr="2026-08-02T14:00:00Z",
                     leg2_dep="2026-08-02T15:00:00Z",
                     leg2_arr="2026-08-02T19:00:00Z",
                     shipment_overrides=None, door_number=21):
    """SEALED trailer bound for the destination terminal with a two-leg relay
    planned through a relay point (both legs PLANNED, 60-minute planned slack).
    Returns {"t_origin", "t_relay", "t_dest", "trailer", "shipment", "entry",
             "leg1", "leg2"}."""
    t_origin = make_terminal(code=origin_code, name="Chicago", dock_doors=12)
    t_relay = make_terminal(code=relay_code, name="Kansas City", dock_doors=8)
    t_dest = make_terminal(code=dest_code, name="Denver", dock_doors=8)
    overrides = {"actual_weight_lbs": 26000, "length_in": 96, "width_in": 96,
                 "height_in": 96, "nmfc_class": "CLASS_60",
                 "service_standard": "STANDARD"}
    overrides.update(shipment_overrides or {})
    ctx = make_sealed_trailer(t_origin["id"], t_dest["id"],
                              shipment_overrides=overrides, door_number=door_number)
    leg1 = plan_leg(t_origin["id"], t_relay["id"], ctx["trailer"]["id"],
                    leg1_dep, leg1_arr, relay_sequence=1)
    leg2 = plan_leg(t_relay["id"], t_dest["id"], ctx["trailer"]["id"],
                    leg2_dep, leg2_arr, relay_sequence=2)
    return {"t_origin": t_origin, "t_relay": t_relay, "t_dest": t_dest,
            "trailer": ctx["trailer"], "shipment": ctx["shipment"],
            "entry": ctx["entry"], "leg1": leg1, "leg2": leg2}


# --- Tier 5: delivery / terminal states ----------------------------------------

def make_delivered_shipment(origin_code="CHI", dest_code="ATL",
                            shipment_overrides=None, trailer_max_weight_lbs=40000,
                            trailer_max_cube_cuft=3500, door_number=21,
                            leg_dep="2026-08-01T20:00:00Z",
                            leg_arr="2026-08-02T08:00:00Z",
                            t_origin=None, t_dest=None,
                            depart_clock=None, arrive_clock=None):
    """Full lifecycle: tender -> rate -> pickup -> manifest -> ready -> seal ->
    leg -> depart -> arrive, ending with the shipment DELIVERED and the trailer
    ARRIVED. Clock is set to the planned instants so actual stamps are exact
    unless depart_clock/arrive_clock override them (e.g. to land the delivery
    exactly on the commitment instant).
    Returns {"t_origin", "t_dest", "trailer", "shipment", "entry", "leg"}."""
    if t_origin is None or t_dest is None:
        t_origin, t_dest = make_terminal_pair(origin_code, dest_code)
    ctx = make_sealed_trailer(
        t_origin["id"], t_dest["id"],
        shipment_overrides=shipment_overrides,
        max_weight_lbs=trailer_max_weight_lbs,
        max_cube_cuft=trailer_max_cube_cuft,
        door_number=door_number,
    )
    leg = plan_leg(t_origin["id"], t_dest["id"], ctx["trailer"]["id"],
                   leg_dep, leg_arr, relay_sequence=1)
    depart_leg(leg["id"], at_utc=depart_clock or leg_dep)
    arrive_leg(leg["id"], at_utc=arrive_clock or leg_arr)
    return {"t_origin": t_origin, "t_dest": t_dest,
            "trailer": get_trailer(ctx["trailer"]["id"]),
            "shipment": get_shipment(ctx["shipment"]["id"]),
            "entry": ctx["entry"], "leg": leg}


# --- Rating / inspection / claims shortcuts -------------------------------------

def make_dimensioner_scan(shipment_id, **overrides):
    resp = api_client.create_dimensioner_scan(
        create_dimensioner_scan_payload(shipment_id, **overrides), headers=CLERK
    )
    return get_success_data(resp)


def open_inspection(shipment_id, scan_id, claimed_nmfc_class):
    resp = api_client.create_inspection(
        create_inspection_payload(shipment_id, scan_id, claimed_nmfc_class),
        headers=CLERK,
    )
    return get_success_data(resp)


def make_osd_case(shipment_id, **overrides):
    resp = api_client.create_osd_case(
        create_osd_case_payload(shipment_id, **overrides), headers=OSD
    )
    return get_success_data(resp)


def make_sortation_batch(terminal_id, inbound_door_id, destination_terminal_id):
    resp = api_client.create_sortation_batch(
        create_sortation_batch_payload(terminal_id, inbound_door_id,
                                       destination_terminal_id),
        headers=DOCK,
    )
    return get_success_data(resp)
