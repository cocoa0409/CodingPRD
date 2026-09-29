"""Replenishment routes, the allocation waterfall and stop execution
(PRD 3.7)."""

from flask import Blueprint

from calc import allocation_candidates, grant_for, stop_window_overlap
from cascade import recompute_alert_after_delivery, skip_stop
from core import (
    ROUTE_STATUSES,
    SKIP_REASONS,
    STOP_STATUSES,
    Ladder,
    body,
    db,
    endpoint,
    f_dt,
    f_int,
    f_str,
    f_str_list,
    fail,
    get_outlet,
    get_position,
    get_route,
    get_stop,
    interval_ok,
    new_id,
    ok,
    ok_list,
    pagination,
    paginate,
    q_str,
    require,
    sort_rows,
    stamp_new,
    touch,
)
from serialize import ser_route, ser_stop

bp = Blueprint("routes", __name__)


# ===========================================================================
# Replenishment routes
# ===========================================================================
@bp.post("/replenishment-routes")
@endpoint(["SupplyPlanner"])
def create_route():
    payload = body()
    # rung 3
    route_code = f_str(payload, "route_code", required=True)
    depot_region_code = f_str(payload, "depot_region_code", required=True)
    service_raw, service_dt = f_dt(payload, "service_date", required=True)
    van_code = f_str(payload, "van_code", required=True)
    capacity_units = f_int(payload, "capacity_units", required=True, ge=1)
    # rung 30
    for row in db.routes.values():
        if row["route_code"] == route_code:
            fail("ERR_DUPLICATE_ROUTE_CODE", "Route code %s already exists." % route_code)

    route = {
        "id": new_id(),
        "route_code": route_code,
        "depot_region_code": depot_region_code,
        "service_date": service_raw,
        "_service_date": service_dt,
        "van_code": van_code,
        "capacity_units": capacity_units,
        "status": "PLANNED",
        "committed_units": 0,
        "delivered_units": 0,
    }
    stamp_new(route)
    db.routes[route["id"]] = route
    return ok(ser_route(route), 201)


@bp.get("/replenishment-routes/<rid>")
@endpoint(["NetworkAdmin", "SupplyPlanner", "RouteDriver"])
def read_route(rid):
    return ok(ser_route(get_route(rid)))


@bp.post("/replenishment-routes/<rid>/stops")
@endpoint(["SupplyPlanner"])
def create_stop(rid):
    payload = body()
    state = {}
    ladder = Ladder()

    def shape():
        state["outlet_id"] = f_str(payload, "outlet_id", required=True)
        state["sequence_index"] = f_int(payload, "sequence_index", required=True, ge=1)
        state["window_start_raw"], state["window_start"] = f_dt(payload, "window_start", required=True)
        state["window_end_raw"], state["window_end"] = f_dt(payload, "window_end", required=True)
        state["expected_route_version"] = f_int(payload, "expected_route_version", required=True)

    def path_exists():
        state["route"] = get_route(rid)

    def body_refs():
        state["outlet"] = get_outlet(state["outlet_id"])

    def route_version():
        route = state["route"]
        require(
            state["expected_route_version"] == route["version"],
            "ERR_STALE_ROUTE_VERSION",
            "expected_route_version %s does not match the route's stored version %s."
            % (state["expected_route_version"], route["version"]),
        )

    def state_legal():
        require(
            state["route"]["status"] == "PLANNED",
            "ERR_INVALID_STATE_TRANSITION",
            "Stops may only be added to a PLANNED route.",
        )

    def region():
        require(
            state["outlet"]["region_code"] == state["route"]["depot_region_code"],
            "ERR_REGION_MISMATCH",
            "The outlet's region_code does not match the route's depot_region_code.",
        )

    def interval():
        interval_ok(state["window_start"], state["window_end"])

    def overlap():
        require(
            not stop_window_overlap(state["route"]["id"], state["window_start"], state["window_end"]),
            "ERR_STOP_WINDOW_OVERLAP",
            "The delivery window overlaps another PENDING or ARRIVED stop of this route.",
        )

    def unique_sequence():
        for row in db.stops.values():
            if row["route_id"] == state["route"]["id"] and row["sequence_index"] == state["sequence_index"]:
                fail(
                    "ERR_DUPLICATE_STOP_SEQUENCE",
                    "sequence_index %s is already used on this route." % state["sequence_index"],
                )

    ladder.add(3, shape).add(4, path_exists).add(5, body_refs).add(8, route_version)
    ladder.add(9, state_legal).add(19, region).add(21, interval).add(23, overlap).add(30, unique_sequence)
    ladder.run()

    stop = {
        "id": new_id(),
        "route_id": state["route"]["id"],
        "outlet_id": state["outlet"]["id"],
        "sequence_index": state["sequence_index"],
        "window_start": state["window_start_raw"],
        "window_end": state["window_end_raw"],
        "_window_start": state["window_start"],
        "_window_end": state["window_end"],
        "status": "PENDING",
        "delivered_units": 0,
        "skip_reason_code": None,
    }
    stamp_new(stop)
    db.stops[stop["id"]] = stop
    touch(state["route"])
    return ok(ser_stop(stop), 201)


@bp.post("/replenishment-routes/<rid>/dispatch")
@endpoint(["SupplyPlanner"])
def dispatch_route(rid):
    payload = body()
    # rung 3
    expected_route_version = f_int(payload, "expected_route_version", required=True)
    # rung 4
    route = get_route(rid)
    # rung 8
    require(
        expected_route_version == route["version"],
        "ERR_STALE_ROUTE_VERSION",
        "expected_route_version %s does not match the route's stored version %s."
        % (expected_route_version, route["version"]),
    )
    # rung 9
    require(
        route["status"] == "PLANNED",
        "ERR_INVALID_STATE_TRANSITION",
        "Only a PLANNED route can be dispatched.",
    )
    stops = [s for s in db.stops.values() if s["route_id"] == route["id"]]
    require(
        len(stops) >= 1,
        "ERR_INVALID_STATE_TRANSITION",
        "A route must have at least one stop before dispatch.",
    )
    require(
        route["committed_units"] <= route["capacity_units"],
        "ERR_INVALID_STATE_TRANSITION",
        "The route's committed units exceed its capacity.",
    )
    route["status"] = "DISPATCHED"
    touch(route)
    return ok(ser_route(route))


@bp.post("/replenishment-routes/<rid>/complete")
@endpoint(["SupplyPlanner"])
def complete_route(rid):
    # rung 4 - completion takes no body and no expected-version field
    route = get_route(rid)
    # rung 9
    require(
        route["status"] == "DISPATCHED",
        "ERR_INVALID_STATE_TRANSITION",
        "Only a DISPATCHED route can be completed.",
    )
    stops = [s for s in db.stops.values() if s["route_id"] == route["id"]]
    require(
        all(s["status"] in ("SERVED", "SKIPPED") for s in stops),
        "ERR_INVALID_STATE_TRANSITION",
        "Every stop of the route must be SERVED or SKIPPED before completion.",
    )
    route["delivered_units"] = sum(s["delivered_units"] for s in stops if s["status"] == "SERVED")
    route["status"] = "COMPLETED"
    touch(route)
    return ok(ser_route(route))


@bp.post("/replenishment-routes/<rid>/cancel")
@endpoint(["SupplyPlanner"])
def cancel_route(rid):
    payload = body()
    # rung 3
    expected_route_version = f_int(payload, "expected_route_version", required=True)
    f_str(payload, "reason_code")
    # rung 4
    route = get_route(rid)
    # rung 8
    require(
        expected_route_version == route["version"],
        "ERR_STALE_ROUTE_VERSION",
        "expected_route_version %s does not match the route's stored version %s."
        % (expected_route_version, route["version"]),
    )
    # rung 9
    require(
        route["status"] in ("PLANNED", "DISPATCHED"),
        "ERR_INVALID_STATE_TRANSITION",
        "Only a PLANNED or DISPATCHED route can be cancelled.",
    )
    route["status"] = "CANCELLED"
    touch(route)
    for stop in sort_rows(
        [
            s
            for s in db.stops.values()
            if s["route_id"] == route["id"] and s["status"] in ("PENDING", "ARRIVED")
        ]
    ):
        skip_stop(stop, "ACCESS_DENIED")
    return ok(ser_route(route))


# ===========================================================================
# Route stops
# ===========================================================================
@bp.get("/route-stops/<sid>")
@endpoint(["NetworkAdmin", "SupplyPlanner", "RouteDriver", "OutletManager"])
def read_stop(sid):
    return ok(ser_stop(get_stop(sid)))


@bp.get("/route-stops")
@endpoint(["NetworkAdmin", "SupplyPlanner", "RouteDriver", "OutletManager"])
def list_stops():
    limit, offset = pagination()
    route_id = q_str("route_id")
    outlet_id = q_str("outlet_id")
    status = q_str("status", enum=STOP_STATUSES)
    rows = list(db.stops.values())
    if route_id is not None:
        rows = [r for r in rows if r["route_id"] == route_id]
    if outlet_id is not None:
        rows = [r for r in rows if r["outlet_id"] == outlet_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([ser_stop(r) for r in page], limit, offset, total)


@bp.post("/route-stops/<sid>/allocations")
@endpoint(["SupplyPlanner"])
def allocate_stop(sid):
    payload = body()
    # rung 3
    position_ids = f_str_list(payload, "supply_position_ids", required=True)
    # rung 4
    stop = get_stop(sid)
    # rung 5 - every member of supply_position_ids must resolve
    positions = [get_position(pid) for pid in position_ids]
    route = db.routes[stop["route_id"]]
    outlet = db.outlets[stop["outlet_id"]]
    # rung 13
    require(
        outlet["service_posture"] != "FROZEN",
        "ERR_OUTLET_POSTURE_FROZEN",
        "The stop's outlet is FROZEN.",
    )

    # the waterfall's eligibility filter, then its pinned processing order
    candidates = allocation_candidates(positions, stop)
    # rung 31
    require(
        len(candidates) >= 1,
        "ERR_NO_ELIGIBLE_POSITIONS",
        "No submitted supply position survived the eligibility filter.",
    )

    grants = []
    for position in candidates:
        item = db.supply_items[position["supply_item_id"]]
        case_pack = item["case_pack_units"]
        unreserved_pool = item["national_allocation_units"] - item["reserved_pool_units"]
        remaining_capacity = route["capacity_units"] - route["committed_units"]
        # rung 32
        require(
            unreserved_pool >= case_pack,
            "ERR_ALLOCATION_POOL_EXHAUSTED",
            "The unreserved national pool of %s is below one case pack." % item["sku_code"],
        )
        # rung 33
        require(
            remaining_capacity >= case_pack,
            "ERR_ROUTE_CAPACITY_EXCEEDED",
            "The route's remaining capacity is below one case pack.",
        )
        granted = grant_for(position["requested_units"], unreserved_pool, remaining_capacity, case_pack)
        if granted > 0:
            position["allocated_units"] = granted
            position["planned_route_stop_id"] = stop["id"]
            touch(position)
            item["reserved_pool_units"] = item["reserved_pool_units"] + granted
            touch(item)
            route["committed_units"] = route["committed_units"] + granted
            touch(route)
            grants.append({"supply_position_id": position["id"], "granted_units": granted})

    return ok(
        {
            "route_stop_id": stop["id"],
            "allocated_position_count": len(grants),
            "total_allocated_units": sum(grant["granted_units"] for grant in grants),
            "granted_units_by_position": grants,
        }
    )


@bp.post("/route-stops/<sid>/arrive")
@endpoint(["RouteDriver"])
def arrive_stop(sid):
    # rung 4
    stop = get_stop(sid)
    route = db.routes[stop["route_id"]]
    # rung 9
    require(
        route["status"] == "DISPATCHED",
        "ERR_INVALID_STATE_TRANSITION",
        "The owning route must be DISPATCHED.",
    )
    require(
        stop["status"] == "PENDING",
        "ERR_INVALID_STATE_TRANSITION",
        "Only a PENDING stop can be arrived at.",
    )
    stop["status"] = "ARRIVED"
    touch(stop)
    return ok(ser_stop(stop))


@bp.post("/route-stops/<sid>/serve")
@endpoint(["RouteDriver"])
def serve_stop(sid):
    # rung 4
    stop = get_stop(sid)
    outlet = db.outlets[stop["outlet_id"]]
    # rung 9
    require(
        stop["status"] == "ARRIVED",
        "ERR_INVALID_STATE_TRANSITION",
        "Only an ARRIVED stop can be served.",
    )
    # rung 13
    require(
        outlet["service_posture"] != "FROZEN",
        "ERR_OUTLET_POSTURE_FROZEN",
        "The stop's outlet is FROZEN.",
    )
    # rung 14
    out_of_spec = any(
        u["outlet_id"] == outlet["id"] and u["calibration_status"] == "OUT_OF_SPEC"
        for u in db.units.values()
    )
    require(
        not out_of_spec,
        "ERR_CALIBRATION_OUT_OF_SPEC",
        "A dispenser unit at this outlet is OUT_OF_SPEC.",
    )

    delivered_total = 0
    positions = sort_rows([p for p in db.positions.values() if p["planned_route_stop_id"] == stop["id"]])
    for position in positions:
        delivered = position["allocated_units"]
        position["on_hand_units"] = position["on_hand_units"] + delivered
        position["allocated_units"] = 0
        position["planned_route_stop_id"] = None
        item = db.supply_items[position["supply_item_id"]]
        if delivered:
            item["reserved_pool_units"] = max(0, item["reserved_pool_units"] - delivered)
            touch(item)
        # the alert band is re-derived from the position's new on_hand_units
        recompute_alert_after_delivery(position, item)
        touch(position)
        delivered_total += delivered

    stop["delivered_units"] = delivered_total
    stop["status"] = "SERVED"
    touch(stop)
    # the route's committed_units is deliberately NOT reduced (PRD 2.11)
    return ok(ser_stop(stop))


@bp.post("/route-stops/<sid>/skip")
@endpoint(["RouteDriver"])
def skip_route_stop(sid):
    payload = body()
    # rung 3
    reason_code = f_str(payload, "skip_reason_code", required=True, enum=SKIP_REASONS)
    # rung 4
    stop = get_stop(sid)
    # rung 9
    require(
        stop["status"] in ("PENDING", "ARRIVED"),
        "ERR_INVALID_STATE_TRANSITION",
        "Only a PENDING or ARRIVED stop can be skipped.",
    )
    skip_stop(stop, reason_code)
    return ok(ser_stop(stop))
