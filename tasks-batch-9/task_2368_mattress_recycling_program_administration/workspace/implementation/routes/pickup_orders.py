"""Pickup orders: dispatch, the two status axes, inspections and settlement."""

from flask import Blueprint, g

import calc
import response
import services
from db import db
from errors import ApiError
from middleware import (ADMIN, AUDITOR, HAULER, RECYCLER, SITE_OPERATOR, auth,
                        get_hauler, get_order, get_recycler, get_site, own)
from util import (F, apply_filters, base_record, pagination, paginate, parse_dt,
                  public, sort_records, touch, validate_body)

bp = Blueprint("pickup_orders", __name__)

READ_ROLES = [ADMIN, AUDITOR, SITE_OPERATOR, HAULER, RECYCLER]

CREATE_SPEC = [
    F("collection_site_id", "string"),
    F("recycler_id", "string"),
    F("hauler_id", "string", required=False, nullable=True),
    F("units_manifested", "int", minimum=1),
    F("route_distance_km", "number", exclusive_min=0),
    F("pickup_window_start", "datetime"),
    F("pickup_window_end", "datetime"),
]


def _order_ownership(order):
    if g.role == SITE_OPERATOR:
        own(order["collection_site_id"])
    elif g.role == HAULER:
        own(order["hauler_id"])
    elif g.role == RECYCLER:
        own(order["recycler_id"])


def _inspection_of(order_id):
    for inspection in db.load_inspections.values():
        if inspection["pickup_order_id"] == order_id:
            return inspection
    return None


@bp.post("/pickup-orders")
def dispatch():
    auth([SITE_OPERATOR])
    body = validate_body(CREATE_SPEC)
    window_start = parse_dt(body["pickup_window_start"])
    window_end = parse_dt(body["pickup_window_end"])
    if not window_end > window_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "pickup_window_end must be later than pickup_window_start.")

    site = get_site(body["collection_site_id"])
    recycler = get_recycler(body["recycler_id"])
    explicit_hauler = None
    if body.get("hauler_id"):
        explicit_hauler = get_hauler(body["hauler_id"])

    own(site["id"])

    # step 9 — cross-entity lifecycle states
    if recycler["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_RECYCLER_NOT_CERTIFIED")
    if site["enrollment_status"] != "ENROLLED":
        raise ApiError("ERR_SITE_NOT_ENROLLED")

    # step 10/11 — business safety
    if services.quarantine_active(site):
        raise ApiError("ERR_SITE_QUARANTINED")

    # step 12 — temporal capacity of an explicitly named hauler
    if explicit_hauler is not None:
        conflicts = calc.conflicting_route_count(explicit_hauler["id"],
                                                 window_start, window_end)
        if conflicts >= explicit_hauler["max_concurrent_routes"]:
            raise ApiError("ERR_HAULER_WINDOW_CAPACITY_EXCEEDED")

    # step 13 — referential coherence
    if recycler["state_program_id"] != site["state_program_id"]:
        raise ApiError("ERR_RECYCLER_PROGRAM_MISMATCH")
    if explicit_hauler is not None:
        if (explicit_hauler["state_program_id"] != site["state_program_id"]
                or site["region_code"] not in explicit_hauler["service_regions"]):
            raise ApiError("ERR_HAULER_REGION_MISMATCH")

    # step 14 — quantitative capacity
    if body["units_manifested"] > site["units_on_hand"]:
        raise ApiError("ERR_INSUFFICIENT_SITE_UNITS")

    if explicit_hauler is not None:
        hauler = explicit_hauler
        auto_selected = False
    else:
        pool = calc.eligible_haulers(site, window_start, window_end)
        if not pool:
            raise ApiError("ERR_NO_ELIGIBLE_HAULER")
        hauler = pool[0]
        auto_selected = True

    rec = base_record()
    rec.update({
        "collection_site_id": site["id"],
        "hauler_id": hauler["id"],
        "recycler_id": recycler["id"],
        "units_manifested": body["units_manifested"],
        "units_delivered": None,
        "units_accepted": None,
        "route_distance_km": body["route_distance_km"],
        "pickup_window_start": body["pickup_window_start"],
        "pickup_window_end": body["pickup_window_end"],
        "fulfillment_status": "SCHEDULED",
        "settlement_status": "UNSETTLED",
        "estimated_payment_cents": None,
        "final_payment_cents": None,
        "hauler_auto_selected": auto_selected,
    })
    db.pickup_orders[rec["id"]] = rec

    site["units_on_hand"] -= body["units_manifested"]
    site["units_in_transit"] += body["units_manifested"]
    touch(site)
    services.refresh_hauler(hauler)
    touch(hauler)
    return response.obj(public(rec), 201)


@bp.get("/pickup-orders/<order_id>")
def read_order(order_id):
    auth(READ_ROLES)
    order = get_order(order_id)
    _order_ownership(order)
    return response.obj(public(order))


@bp.get("/pickup-orders")
def list_orders():
    auth(READ_ROLES)
    limit, offset = pagination()
    records = sort_records(list(db.pickup_orders.values()))
    records = apply_filters(records, [
        ("collection_site_id", "collection_site_id"),
        ("hauler_id", "hauler_id"),
        ("recycler_id", "recycler_id"),
        ("fulfillment_status", "fulfillment_status"),
        ("settlement_status", "settlement_status"),
    ])
    window, total = paginate(records, limit, offset)
    return response.arr([public(r) for r in window], limit, offset, total)


@bp.post("/pickup-orders/<order_id>/pickup-confirm")
def pickup_confirm(order_id):
    auth([HAULER])
    order = get_order(order_id)
    own(order["hauler_id"])
    if order["fulfillment_status"] != "SCHEDULED":
        raise ApiError("ERR_PICKUP_STATE_INVALID")
    order["fulfillment_status"] = "PICKED_UP"
    touch(order)
    return response.obj(public(order))


@bp.post("/pickup-orders/<order_id>/deliver")
def deliver(order_id):
    auth([HAULER])
    body = validate_body([F("units_delivered", "int", minimum=0)])
    order = get_order(order_id)
    own(order["hauler_id"])

    if order["fulfillment_status"] != "PICKED_UP":
        raise ApiError("ERR_PICKUP_STATE_INVALID")
    if body["units_delivered"] > order["units_manifested"]:
        raise ApiError("ERR_UNITS_EXCEED_MANIFEST")

    delivered = body["units_delivered"]
    manifested = order["units_manifested"]
    hauler = db.haulers[order["hauler_id"]]

    order["units_delivered"] = delivered
    order["fulfillment_status"] = "DELIVERED"
    order["settlement_status"] = "ESTIMATED"
    order["estimated_payment_cents"] = calc.hauler_route_payment(
        order, hauler, manifested, 0)
    touch(order)

    site = db.collection_sites[order["collection_site_id"]]
    site["units_in_transit"] -= manifested
    site["units_at_recycler_count"] += delivered
    site["units_written_off_count"] += (manifested - delivered)
    touch(site)

    recycler = db.recyclers[order["recycler_id"]]
    services.refresh_recycler(recycler)
    touch(recycler)
    return response.obj(public(order))


@bp.post("/pickup-orders/<order_id>/inspections")
def record_inspection(order_id):
    auth([RECYCLER])
    body = validate_body([
        F("contaminated_unit_count", "int", minimum=0),
        F("infestation_finding", "enum", enum=["NONE", "BED_BUG", "MOLD"]),
    ])
    order = get_order(order_id)
    own(order["recycler_id"])

    if order["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_PICKUP_STATE_INVALID")
    if _inspection_of(order["id"]) is not None:
        raise ApiError("ERR_LOAD_ALREADY_INSPECTED")
    if order["settlement_status"] != "ESTIMATED":
        raise ApiError("ERR_PICKUP_STATE_INVALID")

    delivered = order["units_delivered"] or 0
    contaminated = body["contaminated_unit_count"]
    if contaminated > delivered:
        raise ApiError("ERR_UNITS_EXCEED_MANIFEST")

    pct, disposition, accepted, reason = calc.load_inspection_disposition(
        delivered, contaminated, body["infestation_finding"])

    rec = base_record(with_version=False)
    rec.update({
        "pickup_order_id": order["id"],
        "contaminated_unit_count": contaminated,
        "infestation_finding": body["infestation_finding"],
        "contamination_pct": pct,
        "disposition": disposition,
        "units_accepted": accepted,
        "rejection_reason": reason,
        "inspected_by_user_id": g.user_id,
    })
    db.load_inspections[rec["id"]] = rec

    order["units_accepted"] = accepted
    site = db.collection_sites[order["collection_site_id"]]
    site["units_at_recycler_count"] -= delivered
    site["units_recycled_count"] += accepted
    site["units_written_off_count"] += (delivered - accepted)

    recycler = db.recyclers[order["recycler_id"]]
    services.refresh_recycler(recycler)
    touch(recycler)

    if disposition == "FULL_REJECT":
        order["settlement_status"] = "DISPUTED"
        site["contamination_strike_count"] += 1
        if reason == "INFESTATION":
            services.set_quarantine(site)
        if (site["contamination_strike_count"] >= calc.MAX_CONTAMINATION_STRIKES
                and site["enrollment_status"] == "ENROLLED"):
            services.suspend_site(site, db.state_programs[site["state_program_id"]],
                                  skip_order_id=order["id"])

    touch(order)
    touch(site)
    return response.obj(public(rec), 201)


@bp.get("/pickup-orders/<order_id>/inspections")
def list_inspections(order_id):
    auth([ADMIN, AUDITOR, RECYCLER, SITE_OPERATOR, HAULER])
    limit, offset = pagination()
    order = get_order(order_id)
    _order_ownership(order)
    records = sort_records([i for i in db.load_inspections.values()
                            if i["pickup_order_id"] == order["id"]])
    window, total = paginate(records, limit, offset)
    return response.arr([public(r) for r in window], limit, offset, total)


@bp.post("/pickup-orders/<order_id>/finalize-settlement")
def finalize_settlement(order_id):
    auth([ADMIN])
    order = get_order(order_id)

    if order["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_PICKUP_STATE_INVALID")
    if order["settlement_status"] not in ("ESTIMATED", "DISPUTED"):
        raise ApiError("ERR_SETTLEMENT_NOT_READY")
    if _inspection_of(order["id"]) is None:
        raise ApiError("ERR_SETTLEMENT_NOT_READY")

    hauler = db.haulers[order["hauler_id"]]
    delivered = order["units_delivered"] or 0
    accepted = order["units_accepted"] or 0
    order["final_payment_cents"] = calc.hauler_route_payment(
        order, hauler, accepted, delivered - accepted)
    order["settlement_status"] = "FINALIZED"
    order["fulfillment_status"] = "CLOSED"
    touch(order)

    services.refresh_hauler(hauler)
    touch(hauler)
    site = db.collection_sites[order["collection_site_id"]]
    services.refresh_program_and_touch(db.state_programs[site["state_program_id"]])
    return response.obj(public(order))


@bp.post("/pickup-orders/<order_id>/void")
def void(order_id):
    auth([SITE_OPERATOR])
    body = validate_body([F("reason", "string")])
    order = get_order(order_id)
    own(order["collection_site_id"])

    if order["fulfillment_status"] != "SCHEDULED" or order["settlement_status"] != "UNSETTLED":
        raise ApiError("ERR_PICKUP_STATE_INVALID")
    del body

    order["fulfillment_status"] = "CANCELLED"
    order["settlement_status"] = "VOIDED"
    touch(order)

    site = db.collection_sites[order["collection_site_id"]]
    site["units_in_transit"] -= order["units_manifested"]
    site["units_on_hand"] += order["units_manifested"]
    touch(site)

    hauler = db.haulers.get(order["hauler_id"])
    if hauler is not None:
        services.refresh_hauler(hauler)
        touch(hauler)
    return response.obj(public(order))
