"""Shipment endpoints: tender, rate, bill, cancel (PRD sections 3.1, 3.2, 3.7)."""
from flask import Blueprint, request

import db
from errors import err_invalid_request, err_invalid_state, err_not_billable, err_terminal_closed
from middleware import require_roles
from response import success, success_list
from routes.common import (as_enum, as_int, body_json, check_route_completion,
                           get_path, new_record, paginate, resolve_fk,
                           ser_shipment, touch)
from services.calculations import (ACCESSORIAL_CODES, NMFC_CLASSES,
                                   SERVICE_DAYS, SERVICE_STANDARDS,
                                   freight_rating)
from services.timeutil import committed_delivery_utc

bp = Blueprint("shipments", __name__)

_READ_ROLES = ("TerminalAdmin", "Dispatcher", "DockSupervisor", "RatingClerk", "OsdClerk")


@bp.route("/ltl/shipments", methods=["POST"])
@require_roles("Dispatcher")
def create_shipment():
    body = body_json()
    # Priority 4: body FK resolution.
    origin = resolve_fk("terminals", body.get("origin_terminal_id"), "origin_terminal_id")
    dest = resolve_fk("terminals", body.get("destination_terminal_id"), "destination_terminal_id")
    # Priority 16: closed-terminal guard on the origin.
    if origin["status"] == "CLOSED":
        raise err_terminal_closed("Cannot tender a shipment whose origin terminal is CLOSED")
    # Priority 20: field-level validity.
    nmfc_class = as_enum(body, "nmfc_class", NMFC_CLASSES)
    actual_weight = as_int(body, "actual_weight_lbs", minimum=1)
    length_in = as_int(body, "length_in", minimum=1)
    width_in = as_int(body, "width_in", minimum=1)
    height_in = as_int(body, "height_in", minimum=1)
    service_standard = as_enum(body, "service_standard", SERVICE_STANDARDS)
    accessorials = body.get("accessorial_codes", [])
    if not isinstance(accessorials, list) or any(
            not isinstance(c, str) or c not in ACCESSORIAL_CODES for c in accessorials):
        raise err_invalid_request(
            "accessorial_codes must be a list whose elements are in {}".format(
                ", ".join(ACCESSORIAL_CODES)))
    tendered = db.now()
    rec = new_record({
        "pro_number": db.next_pro_number(),
        "origin_terminal_id": origin["id"],
        "destination_terminal_id": dest["id"],
        "nmfc_class": nmfc_class,
        "actual_weight_lbs": actual_weight,
        "length_in": length_in, "width_in": width_in, "height_in": height_in,
        "accessorial_codes": list(accessorials),
        "service_standard": service_standard,
        "chargeable_weight_lbs": actual_weight,
        "dim_weight_lbs": 0,
        "rated_amount_cents": 0,
        "billed_amount_cents": 0,
        "rating_status": "UNRATED",
        "handling_status": "TENDERED",
        "osd_hold": False,
        "tendered_at_utc": tendered,
        "committed_delivery_utc": committed_delivery_utc(
            tendered, dest["timezone"], SERVICE_DAYS[service_standard]),
        "delivered_at_utc": None,
    })
    db.store["shipments"][rec["id"]] = rec
    return success(ser_shipment(rec), 201)


@bp.route("/ltl/shipments", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_shipments():
    items = list(db.store["shipments"].values())
    for param in ("origin_terminal_id", "destination_terminal_id",
                  "rating_status", "handling_status"):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s.get(param) == value]
    page, total, limit, offset = paginate(items)
    return success_list([ser_shipment(s) for s in page], total, limit, offset)


@bp.route("/ltl/shipments/<shipmentId>", methods=["GET"])
@require_roles(*_READ_ROLES)
def get_shipment(shipmentId):
    return success(ser_shipment(get_path("shipments", shipmentId)))


@bp.route("/ltl/shipments/<shipmentId>/rate", methods=["POST"])
@require_roles("RatingClerk")
def rate_shipment(shipmentId):
    s = get_path("shipments", shipmentId)
    # Priority 5: state preconditions (GROSS baseline rating).
    if s["rating_status"] != "UNRATED" or s["handling_status"] not in ("TENDERED", "ON_DOCK"):
        raise err_invalid_state(
            "Rating requires rating_status UNRATED and handling_status TENDERED or ON_DOCK")
    origin = db.store["terminals"].get(s["origin_terminal_id"])
    dest = db.store["terminals"].get(s["destination_terminal_id"])
    if origin is None or dest is None or origin["status"] != "ACTIVE" or dest["status"] != "ACTIVE":
        raise err_invalid_state(
            "Both origin and destination terminals must be ACTIVE at rating time")
    s["rated_amount_cents"] = freight_rating(
        s["nmfc_class"], s["actual_weight_lbs"], s["accessorial_codes"])
    s["chargeable_weight_lbs"] = s["actual_weight_lbs"]
    s["dim_weight_lbs"] = 0
    s["rating_status"] = "RATED"
    touch(s)
    return success(ser_shipment(s))


@bp.route("/ltl/shipments/<shipmentId>/bill", methods=["POST"])
@require_roles("RatingClerk")
def bill_shipment(shipmentId):
    s = get_path("shipments", shipmentId)
    # Priority 5: rating-axis state precondition.
    if s["rating_status"] not in ("RATED", "RERATED"):
        raise err_invalid_state("Billing requires rating_status RATED or RERATED")
    # Priority 15: billability.
    open_case = any(
        c["shipment_id"] == s["id"] and c["status"] in ("OPEN", "UNDER_REVIEW")
        for c in db.store["osd_cases"].values())
    if s["handling_status"] != "DELIVERED" or open_case:
        raise err_not_billable()
    s["billed_amount_cents"] = s["rated_amount_cents"]
    s["rating_status"] = "BILLED"
    touch(s)
    return success(ser_shipment(s))


@bp.route("/ltl/shipments/<shipmentId>/cancel", methods=["POST"])
@require_roles("Dispatcher")
def cancel_shipment(shipmentId):
    s = get_path("shipments", shipmentId)
    if s["handling_status"] not in ("TENDERED", "ON_DOCK"):
        raise err_invalid_state("Only a TENDERED or ON_DOCK shipment can be cancelled")
    if any(e["shipment_id"] == s["id"] and e["status"] == "ACTIVE"
           for e in db.store["manifest_entries"].values()):
        raise err_invalid_state("A manifested shipment cannot be cancelled")
    s["handling_status"] = "CANCELLED"
    touch(s)
    affected_routes = set()
    for stop in db.store["pickup_stops"].values():
        if stop["shipment_id"] == s["id"] and stop["status"] == "PLANNED":
            stop["status"] = "SKIPPED"
            touch(stop)
            affected_routes.add(stop["route_id"])
    for route_id in affected_routes:
        check_route_completion(db.store["pickup_routes"][route_id])
    return success(ser_shipment(s))
