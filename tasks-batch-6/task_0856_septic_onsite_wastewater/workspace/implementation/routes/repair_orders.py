"""Repair orders: the enforcement cascade and its resolve/escalate branch."""
from flask import Blueprint

import calc
import derive
import lookup
import response
import serialize
import store
import validate as v
from auth import authenticate
from errors import ApiError
from store import ordered, touch
from util import add_days, now

bp = Blueprint("repair_orders", __name__)

FAILURE_TYPES = ("SURFACING_EFFLUENT", "BACKUP", "STRUCTURAL",
                 "GROUNDWATER_CONTAMINATION")
REPAIR_READ_ROLES = ["Applicant", "Installer", "EnvironmentalHealthSpecialist",
                     "HealthOfficer", "RecordsClerk"]
OUTCOMES = ("REPAIRED", "ESCALATE")


@bp.post("/repair-orders")
def open_repair_order():
    authenticate(["EnvironmentalHealthSpecialist"])
    body = v.body()
    permit = lookup.operating_permit(v.req_fk(body, "operating_permit_id"))
    failure_type = v.req_enum(body, "failure_type", FAILURE_TYPES)
    reported_on = v.req_dt(body, "reported_on")

    order = store.new_record()
    order.update({
        "parcel_id": permit["parcel_id"],
        "operating_permit_id": permit["id"],
        "failure_type": failure_type,
        "reported_on": reported_on,
        "severity": None,
        "compliance_deadline": None,
        "issued_by_user_id": None,
        "closed_by_user_id": None,
        "extension_count": 0,
        "status": "DRAFT",
    })
    store.repair_orders[order["id"]] = order
    return response.ok(serialize.repair_order(order), 201)


@bp.get("/repair-orders/<order_id>")
def read_repair_order(order_id):
    authenticate(REPAIR_READ_ROLES)
    order = lookup.repair_order(order_id)
    return response.ok(serialize.repair_order(order))


@bp.get("/repair-orders")
def list_repair_orders():
    authenticate(REPAIR_READ_ROLES)
    limit, offset = v.pagination()
    rows = ordered(store.repair_orders.values())
    for field in ("parcel_id", "operating_permit_id", "status", "severity"):
        value = v.q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(serialize.many("repair_order", page),
                            limit, offset, total)


@bp.post("/repair-orders/<order_id>/issue")
def issue_repair_order(order_id):
    actor = authenticate(["HealthOfficer"])
    order = lookup.repair_order(order_id)

    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    permit = store.operating_permits[order["operating_permit_id"]]
    if permit["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_OPERATING_PERMIT_NOT_ACTIVE")

    parcel = store.parcels.get(order["parcel_id"])
    water_flag = bool(parcel["water_quality_flag"]) if parcel else False
    severity, deadline = calc.repair_order_severity_and_deadline(
        order["failure_type"], water_flag, now())

    order["severity"] = severity
    order["compliance_deadline"] = deadline
    order["issued_by_user_id"] = actor.user_id
    order["status"] = "ISSUED"
    touch(order)

    if parcel is not None:
        derive.recompute_parcel(parcel)
    if permit["status"] == "ACTIVE":
        derive.set_operating_permit_status(permit, "SUSPENDED")
    if parcel is not None:
        derive.recompute_parcel(parcel)

    return response.ok(serialize.repair_order(order))


@bp.post("/repair-orders/<order_id>/extend")
def extend_repair_order(order_id):
    authenticate(["HealthOfficer"])
    order = lookup.repair_order(order_id)

    if order["status"] not in ("ISSUED", "EXTENDED"):
        raise ApiError("ERR_INVALID_STATE")
    if order["extension_count"] >= calc.MAX_REPAIR_EXTENSIONS:
        raise ApiError("ERR_MAX_EXTENSIONS_REACHED")
    if order["severity"] == "IMMINENT_HAZARD":
        raise ApiError("ERR_EXTENSION_NOT_ALLOWED")

    order["compliance_deadline"] = add_days(order["compliance_deadline"],
                                            calc.REPAIR_EXTENSION_DAYS)
    order["extension_count"] += 1
    order["status"] = "EXTENDED"
    touch(order)
    return response.ok(serialize.repair_order(order))


@bp.post("/repair-orders/<order_id>/resolve")
def resolve_repair_order(order_id):
    actor = authenticate(["EnvironmentalHealthSpecialist"])
    order = lookup.repair_order(order_id)
    body = v.body()
    outcome = v.req_enum(body, "outcome", OUTCOMES)

    if order["status"] not in ("ISSUED", "EXTENDED"):
        raise ApiError("ERR_INVALID_STATE")
    if outcome == "REPAIRED" and now() > order["compliance_deadline"]:
        raise ApiError("ERR_REPAIR_DEADLINE_PASSED")

    permit = store.operating_permits[order["operating_permit_id"]]
    parcel = store.parcels.get(order["parcel_id"])

    order["closed_by_user_id"] = actor.user_id
    order["status"] = "RESOLVED" if outcome == "REPAIRED" else "ESCALATED"
    touch(order)

    if parcel is not None:
        derive.recompute_parcel(parcel)

    if outcome == "REPAIRED":
        still_open = [r for r in derive.repair_orders_of_parcel(order["parcel_id"])
                      if r["status"] in calc.OPEN_REPAIR_STATES]
        if not still_open and permit["status"] == "SUSPENDED":
            derive.set_operating_permit_status(permit, "ACTIVE")
    else:
        derive.set_operating_permit_status(permit, "REVOKED")

    if parcel is not None:
        derive.recompute_parcel(parcel)

    return response.ok(serialize.repair_order(order))
