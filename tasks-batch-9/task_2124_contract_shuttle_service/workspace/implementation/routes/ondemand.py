"""OnDemandRequest endpoints (PRD 3.5)."""

from flask import Blueprint

import calc
import store
from envelope import created, ok, paginate, pagination
from errors import ApiError
from guards import (ALL_ROLES, authorize, body, equality_filter, id_field,
                    minute_field, must_exist, validate_body)
from store import touch

bp = Blueprint("ondemand", __name__)

CREATE_SPEC = [
    id_field("contract_id"),
    {"name": "service_date", "kind": "date"},
    minute_field("requested_pickup_min"),
    {"name": "party_size", "kind": "int", "min": 1},
    {"name": "requires_ada", "kind": "bool"},
]
MATCH_SPEC = [id_field("trip_id", required=False, nullable=True)]
SERVE_SPEC = [minute_field("actual_pickup_min")]


@bp.post("/on-demand-requests")
def create_request():
    authorize(["ClientLiaison"])
    data = validate_body(body(), CREATE_SPEC)
    contract = must_exist(store.contracts, data["contract_id"], "ERR_CONTRACT_NOT_FOUND")
    if not (contract["term_start_date"] <= data["service_date"] <= contract["term_end_date"]):
        raise ApiError("ERR_DATE_OUT_OF_TERM")
    candidates = calc.eligible_promise_routes(contract["id"], data["service_date"],
                                              data["requested_pickup_min"])
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_ROUTE")
    chosen = candidates[0]

    row = store.base_row()
    row.update({
        "contract_id": contract["id"],
        "matched_trip_id": None,
        "service_date": data["service_date"],
        "requested_pickup_min": data["requested_pickup_min"],
        "party_size": data["party_size"],
        "requires_ada": data["requires_ada"],
        "promised_headway_minutes": chosen["headway_minutes"],
        "promised_wait_minutes": calc.promised_wait_from_headway(chosen["headway_minutes"]),
        "actual_wait_minutes": None,
        "wait_overage_minutes": None,
        "status": "PENDING",
    })
    store.register_new(row)
    store.on_demand_requests[row["id"]] = row
    return created(store.public(row))


@bp.get("/on-demand-requests/<rid>")
def get_request(rid):
    authorize(ALL_ROLES)
    return ok(store.public(must_exist(store.on_demand_requests, rid,
                                      "ERR_REQUEST_NOT_FOUND")))


@bp.get("/on-demand-requests")
def list_requests():
    authorize(ALL_ROLES)
    limit, offset = pagination()
    rows = list(store.on_demand_requests.values())
    for param in ("contract_id", "matched_trip_id", "status", "service_date"):
        rows = equality_filter(rows, param, param)
    rows.sort(key=store.sort_key_created)
    return paginate(rows, limit, offset, store.public)


@bp.post("/on-demand-requests/<rid>/match")
def match_request(rid):
    authorize(["OpsPlanner"])
    data = validate_body(body(), MATCH_SPEC)
    req = must_exist(store.on_demand_requests, rid, "ERR_REQUEST_NOT_FOUND")
    explicit = None
    if data.get("trip_id") is not None:
        explicit = must_exist(store.trips, data["trip_id"], "ERR_TRIP_NOT_FOUND")
    if req["status"] != "PENDING":
        raise ApiError("ERR_REQUEST_NOT_PENDING")

    if explicit is not None:
        route = store.routes.get(explicit["route_id"])
        if route is None or route["status"] != "PUBLISHED":
            raise ApiError("ERR_ROUTE_NOT_PUBLISHED")
        if explicit["dispatch_status"] not in ("SCHEDULED", "ASSIGNED"):
            raise ApiError("ERR_TRIP_NOT_SCHEDULABLE")
        if req["requires_ada"]:
            vehicle = (store.vehicles.get(explicit["vehicle_id"])
                       if explicit["vehicle_id"] else None)
            if vehicle is None or not vehicle["is_ada_accessible"]:
                raise ApiError("ERR_ADA_VEHICLE_REQUIRED")
        if calc.remaining_seats(explicit) < req["party_size"]:
            raise ApiError("ERR_TRIP_SEATS_EXHAUSTED")
        if explicit["service_date"] != req["service_date"] or \
                explicit["scheduled_departure_min"] < req["requested_pickup_min"]:
            raise ApiError("ERR_TRIP_DEPARTURE_TOO_EARLY")
        if explicit["contract_id"] != req["contract_id"]:
            raise ApiError("ERR_TRIP_CONTRACT_MISMATCH")
        chosen = explicit
    else:
        candidates = calc.selector_candidates(req)
        if not candidates:
            req["status"] = "DENIED"
            touch(req)
            return ok(store.public(req))
        chosen = candidates[0]

    req["matched_trip_id"] = chosen["id"]
    req["status"] = "MATCHED"
    touch(req)
    calc.recompute_trip_matched_party_seats(chosen)
    return ok(store.public(req))


@bp.post("/on-demand-requests/<rid>/serve")
def serve_request(rid):
    caller = authorize(["DriverUser"])
    pending = store.on_demand_requests.get(rid)
    if pending is not None and pending["matched_trip_id"]:
        matched = store.trips.get(pending["matched_trip_id"])
        if matched is None or matched["driver_id"] != caller.user_id:
            raise ApiError("ERR_DRIVER_NOT_ASSIGNED")
    data = validate_body(body(), SERVE_SPEC)
    req = must_exist(store.on_demand_requests, rid, "ERR_REQUEST_NOT_FOUND")
    if req["status"] != "MATCHED":
        raise ApiError("ERR_REQUEST_NOT_MATCHED")
    trip = store.trips.get(req["matched_trip_id"])
    if trip is None or trip["dispatch_status"] not in ("IN_SERVICE", "COMPLETED"):
        raise ApiError("ERR_TRIP_NOT_IN_SERVICE")

    actual_wait = max(0, data["actual_pickup_min"] - req["requested_pickup_min"])
    overage = max(0, actual_wait - req["promised_wait_minutes"])
    req["actual_wait_minutes"] = actual_wait
    req["wait_overage_minutes"] = overage
    req["status"] = "SERVED"
    touch(req)

    if overage > calc.WAIT_SLA_GRACE_MINUTES:
        contract = store.contracts.get(req["contract_id"])
        if contract is not None:
            amount = min(overage * calc.WAIT_CREDIT_CENTS_PER_MINUTE,
                         contract["penalty_rate_cents_per_missed_trip"])
            calc.mint_credit_memo(contract, trip["id"], "WAIT_SLA_BREACH", amount)
    return ok(store.public(req))
