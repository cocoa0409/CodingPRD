"""Commercial parties: consignee dealers and inland truck carriers (PRD §3.8)."""
from flask import Blueprint

import db
import validation as v
from errors import fail, invalid
from middleware import OPS_ROLES, ROLE_MANAGER, authenticate
from response import list_response, object_response
from services import calculations as calc
from services import serializers as ser
from services import state

bp = Blueprint("parties", __name__)


# ------------------------------------------------------------------ dealers
@bp.route("/vpc/dealers", methods=["POST"])
def create_dealer():
    authenticate([ROLE_MANAGER])
    body = v.body()
    dealer_code = v.req_str(body, "dealer_code")
    name = v.req_str(body, "name")
    route_zone = v.req_enum(body, "route_zone", calc.ROUTE_ZONES)
    distance = v.req_int(body, "distance_miles", minimum=1)
    quota = v.req_int(body, "allocation_quota", minimum=1)

    if any(d["dealer_code"] == dealer_code for d in db.dealers.values()):
        fail("ERR_DUPLICATE_KEY", "dealer_code %s already exists" % dealer_code)

    record = db.base_record()
    record.update(
        {
            "dealer_code": dealer_code,
            "name": name,
            "route_zone": route_zone,
            "distance_miles": distance,
            "allocation_quota": quota,
            "open_allocation_count": 0,
        }
    )
    db.dealers[record["id"]] = record
    return object_response(ser.dealer(record), 201)


@bp.route("/vpc/dealers/<dealer_id>", methods=["GET"])
def read_dealer(dealer_id):
    authenticate(OPS_ROLES)
    dealer = db.must_get("dealers", dealer_id)
    state.recompute_dealer(dealer)
    return object_response(ser.dealer(dealer))


@bp.route("/vpc/dealers", methods=["GET"])
def list_dealers():
    authenticate(OPS_ROLES)
    dealer_code = v.query_filter("dealer_code")
    route_zone = v.query_filter("route_zone")
    records = db.ordered(db.dealers)
    for dealer in records:
        state.recompute_dealer(dealer)
    if dealer_code is not None:
        records = [r for r in records if r["dealer_code"] == dealer_code]
    if route_zone is not None:
        records = [r for r in records if r["route_zone"] == route_zone]
    items, limit, offset, total = v.paginate(records, ser.dealer)
    return list_response(items, limit, offset, total)


# ----------------------------------------------------------------- carriers
def _served_zones(body):
    value = body.get("served_route_zones")
    if value is None:
        invalid("served_route_zones is required")
    if not isinstance(value, list) or len(value) < 1:
        invalid("served_route_zones must be a non-empty array of route zones")
    zones = []
    for entry in value:
        if not isinstance(entry, str) or entry not in calc.ROUTE_ZONES:
            invalid("served_route_zones must be a subset of A, B and C")
        if entry not in zones:
            zones.append(entry)
    return zones


@bp.route("/vpc/truck-carriers", methods=["POST"])
def create_carrier():
    authenticate([ROLE_MANAGER])
    body = v.body()
    carrier_code = v.req_str(body, "carrier_code")
    name = v.req_str(body, "name")
    zones = _served_zones(body)
    rate = v.req_int(body, "linehaul_rate_cents_per_mile", minimum=0)
    slot_capacity = v.req_int(body, "slot_capacity", minimum=1)
    concurrent = v.req_int(body, "concurrent_load_capacity", minimum=1)
    status = v.opt_enum(body, "status", ("ACTIVE", "SUSPENDED"), default="ACTIVE")

    if any(c["carrier_code"] == carrier_code for c in db.carriers.values()):
        fail("ERR_DUPLICATE_KEY", "carrier_code %s already exists" % carrier_code)

    record = db.base_record()
    record.update(
        {
            "carrier_code": carrier_code,
            "name": name,
            "served_route_zones": zones,
            "linehaul_rate_cents_per_mile": rate,
            "slot_capacity": slot_capacity,
            "committed_slots": 0,
            "available_slots": slot_capacity,
            "concurrent_load_capacity": concurrent,
            "status": status,
        }
    )
    db.carriers[record["id"]] = record
    return object_response(ser.carrier(record), 201)


@bp.route("/vpc/truck-carriers/<carrier_id>", methods=["GET"])
def read_carrier(carrier_id):
    authenticate(OPS_ROLES)
    carrier = db.must_get("carriers", carrier_id)
    state.recompute_carrier(carrier)
    return object_response(ser.carrier(carrier))


@bp.route("/vpc/truck-carriers", methods=["GET"])
def list_carriers():
    authenticate(OPS_ROLES)
    status = v.query_filter("status")
    zone = v.query_filter("served_route_zone")
    carrier_code = v.query_filter("carrier_code")
    records = db.ordered(db.carriers)
    for carrier in records:
        state.recompute_carrier(carrier)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if zone is not None:
        records = [r for r in records if zone in r["served_route_zones"]]
    if carrier_code is not None:
        records = [r for r in records if r["carrier_code"] == carrier_code]
    items, limit, offset, total = v.paginate(records, ser.carrier)
    return list_response(items, limit, offset, total)


@bp.route("/vpc/truck-carriers/<carrier_id>", methods=["PATCH"])
def update_carrier(carrier_id):
    authenticate([ROLE_MANAGER])
    carrier = db.must_get("carriers", carrier_id)
    body = v.body()
    status = v.opt_enum(body, "status", ("ACTIVE", "SUSPENDED"))
    rate = v.opt_int(body, "linehaul_rate_cents_per_mile", minimum=0)
    concurrent = v.opt_int(body, "concurrent_load_capacity", minimum=1)

    changed = False
    if status is not None and status != carrier["status"]:
        carrier["status"] = status
        changed = True
    if rate is not None and rate != carrier["linehaul_rate_cents_per_mile"]:
        carrier["linehaul_rate_cents_per_mile"] = rate
        changed = True
    if concurrent is not None and concurrent != carrier["concurrent_load_capacity"]:
        carrier["concurrent_load_capacity"] = concurrent
        changed = True
    if changed:
        db.touch(carrier)
    state.recompute_carrier(carrier)
    return object_response(ser.carrier(carrier))
