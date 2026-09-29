"""Labels, the re-ship loop and carrier scan events (PRD 3.7)."""
import uuid

from flask import Blueprint

import clock
import response
import validate
from errors import ApiError
from middleware import require, own_winery, own_consumer
from routes import common
from services import derive, orders_svc, screening, serialize, volume
from store import db, base_row, touch

bp = Blueprint("shipments", __name__)

SHIPMENT_STATUSES = ("LABEL_CREATED", "IN_TRANSIT", "EXCEPTION", "DELIVERED", "RETURNED")
SCAN_TYPES = ("PICKUP", "EXCEPTION", "REROUTE_ACCEPTED", "DELIVERED", "RETURN_TO_SENDER")
EXCEPTION_CODES = ("WEATHER", "ADDRESS_UNDELIVERABLE", "ADULT_SIGNATURE_UNAVAILABLE", "REFUSED")
SAFETY_BAND = (
    "ERR_STATE_DTC_PROHIBITED",
    "ERR_PROHIBITED_DESTINATION",
    "ERR_CONSUMER_UNDERAGE",
    "ERR_ID_VERIFICATION_REQUIRED",
    "ERR_PERMIT_MISSING_FOR_STATE",
    "ERR_PERMIT_NOT_ACTIVE",
    "ERR_PERMIT_EXPIRED",
)


def _tracking_number():
    return "TRK-" + uuid.uuid4().hex[:8].upper()


@bp.route("/dtc/shipments", methods=["POST"])
def create_shipment():
    uid, role = require("WineryOperator")
    b = validate.body()
    order_id = validate.field_str(b, "order_id")
    enrollment_id = validate.field_str(b, "carrier_enrollment_id")
    replacement_id = validate.field_str(b, "replacement_of_shipment_id", required=False)

    order = common.order(order_id)
    enrollment = common.carrier_enrollment(enrollment_id)
    prior = common.shipment(replacement_id) if replacement_id is not None else None
    own_winery(uid, role, order["winery_id"])

    reship = replacement_id is not None
    fulfillment = order["fulfillment_status"]
    if order["compliance_status"] != "CLEARED" \
            or (fulfillment != "UNFULFILLED" and not (reship and fulfillment == "RETURNED")):
        raise ApiError("ERR_ORDER_NOT_CLEARED",
                       "The order must be CLEARED and UNFULFILLED (or RETURNED for a re-ship).")
    if reship and (prior["status"] != "RETURNED" or prior["order_id"] != order["id"]):
        validate.bad("replacement_of_shipment_id must name a RETURNED shipment of this order.")

    winery = db.wineries.get(order["winery_id"])
    if winery is not None and winery["status"] == "SUSPENDED":
        raise ApiError("ERR_WINERY_SUSPENDED",
                       "The winery is suspended; no label may be produced.")

    # the safety and permit band is re-verified and RAISED here (PRD 3.7)
    failing = screening.evaluate(order, band=SAFETY_BAND)
    if failing is not None:
        raise ApiError(failing)

    program = db.carrier_programs.get(enrollment["carrier_program_id"])
    if enrollment["winery_id"] != order["winery_id"] \
            or enrollment["status"] != "APPROVED" \
            or program is None \
            or order["ship_to_state_code"] not in (program.get("states_served") or []):
        raise ApiError("ERR_CARRIER_NOT_ENROLLED",
                       "The named enrollment does not authorize this shipment.")
    if order["adult_signature_required"] and not program.get("adult_signature_service_code"):
        raise ApiError("ERR_ADULT_SIGNATURE_NOT_SUPPORTED",
                       "The enrolled program offers no adult-signature service.")

    rule = volume.state_rule_for(order["ship_to_state_code"])
    if reship and rule is not None:
        if not screening.consumer_has_room(order, rule):
            raise ApiError("ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED",
                           "Re-debiting these liters would exceed the per-consumer limit.")
        if not screening.winery_has_room(order, rule):
            raise ApiError("ERR_WINERY_VOLUME_LIMIT_EXCEEDED",
                           "Re-debiting these liters would exceed the winery's annual limit.")

    row = base_row()
    row.update({
        "order_id": order["id"],
        "carrier_enrollment_id": enrollment["id"],
        "replacement_of_shipment_id": replacement_id,
        "tracking_number": _tracking_number(),
        "adult_signature_required": order["adult_signature_required"],
        "adult_signature_service_code": (program.get("adult_signature_service_code")
                                        if order["adult_signature_required"] else None),
        "status": "LABEL_CREATED",
        "exception_code": None,
        "reroute_zip": None,
        "reroute_count": 0,
        "signed_by": None,
        "signer_age_verified": None,
        "delivered_at": None,
        "returned_at": None,
    })
    db.shipments[row["id"]] = row

    order["fulfillment_status"] = "LABELED"
    touch(order)
    if reship:
        orders_svc.redebit_order(order)
    return response.obj(serialize.shipment(row), 201)


@bp.route("/dtc/shipments/<sid>", methods=["GET"])
def read_shipment(sid):
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator",
                        "CarrierAgent", "Consumer")
    shipment = common.shipment(sid)
    order = db.orders.get(shipment["order_id"])
    if order is not None:
        own_winery(uid, role, order["winery_id"])
        own_consumer(uid, role, order["consumer_id"])
    return response.obj(serialize.shipment(shipment))


@bp.route("/dtc/shipments", methods=["GET"])
def list_shipments():
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator", "CarrierAgent")
    order_id = common.arg("order_id")
    enrollment_id = common.arg("carrier_enrollment_id")
    replacement_id = common.arg("replacement_of_shipment_id")
    status = validate.query_enum("status", SHIPMENT_STATUSES)
    rows = []
    for row in db.shipments.values():
        if order_id is not None and row["order_id"] != order_id:
            continue
        if enrollment_id is not None and row["carrier_enrollment_id"] != enrollment_id:
            continue
        if replacement_id is not None and row["replacement_of_shipment_id"] != replacement_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if role == "WineryOperator":
            order = db.orders.get(row["order_id"])
            if order is None or order["winery_id"] != uid:
                continue
        rows.append(row)
    return common.listing(rows, serialize.shipment)


@bp.route("/dtc/shipments/<sid>/scan", methods=["POST"])
def scan_shipment(sid):
    require("CarrierAgent")
    shipment = common.shipment(sid)
    order = db.orders.get(shipment["order_id"])
    b = validate.body()
    scan_type = validate.field_enum(b, "scan_type", SCAN_TYPES)

    exception_code = None
    reroute_zip = None
    reroute_state = None
    signed_by = validate.field_str(b, "signed_by", required=False)
    signer_verified = validate.field_bool(b, "signer_age_verified", required=False)

    if scan_type == "EXCEPTION":
        exception_code = validate.field_enum(b, "exception_code", EXCEPTION_CODES)
    elif scan_type == "REROUTE_ACCEPTED":
        reroute_zip = validate.zip_code(b, "reroute_zip")
        reroute_state = validate.state_code(b, "reroute_state_code")
    elif scan_type == "DELIVERED" and shipment["adult_signature_required"]:
        if signed_by is None or signed_by.strip() == "":
            validate.bad("Field 'signed_by' is required when an adult signature is required.")
        if signer_verified is not True:
            validate.bad("Field 'signer_age_verified' must be true when an adult signature "
                         "is required.")

    status = shipment["status"]
    legal = {
        "PICKUP": ("LABEL_CREATED",),
        "EXCEPTION": ("IN_TRANSIT",),
        "REROUTE_ACCEPTED": ("EXCEPTION",),
        "DELIVERED": ("IN_TRANSIT",),
        "RETURN_TO_SENDER": ("IN_TRANSIT", "EXCEPTION"),
    }[scan_type]
    if status not in legal:
        raise ApiError("ERR_SHIPMENT_NOT_ACTIVE",
                       "A %s scan is not declared from %s." % (scan_type, status))
    if scan_type == "REROUTE_ACCEPTED" and shipment["reroute_count"] != 0:
        raise ApiError("ERR_SHIPMENT_NOT_ACTIVE",
                       "A shipment may be rerouted at most once.")

    if scan_type == "PICKUP":
        shipment["status"] = "IN_TRANSIT"
        touch(shipment)
        if order is not None:
            order["fulfillment_status"] = "IN_TRANSIT"
            touch(order)
            consumer = db.consumers.get(order["consumer_id"])
            if consumer is not None:
                derive.bump_consumer(consumer)
    elif scan_type == "EXCEPTION":
        shipment["status"] = "EXCEPTION"
        shipment["exception_code"] = exception_code
        touch(shipment)
    elif scan_type == "REROUTE_ACCEPTED":
        if order is not None and reroute_state != order["ship_to_state_code"]:
            raise ApiError("ERR_REROUTE_STATE_CHANGE",
                           "A reroute may not change the destination state.")
        rule = volume.state_rule_for(order["ship_to_state_code"]) if order is not None else None
        if screening.zip_blocked(rule, reroute_zip):
            raise ApiError("ERR_PROHIBITED_DESTINATION",
                           "The reroute ZIP is blocked in the destination state.")
        shipment["status"] = "IN_TRANSIT"
        shipment["reroute_zip"] = reroute_zip
        shipment["reroute_count"] = shipment["reroute_count"] + 1
        shipment["exception_code"] = None
        touch(shipment)
        if order is not None:
            order["ship_to_zip"] = reroute_zip
            touch(order)
    elif scan_type == "DELIVERED":
        shipment["status"] = "DELIVERED"
        shipment["delivered_at"] = clock.now_iso()
        shipment["signed_by"] = signed_by
        shipment["signer_age_verified"] = signer_verified
        touch(shipment)
        if order is not None:
            order["fulfillment_status"] = "DELIVERED"
            touch(order)
    else:
        shipment["status"] = "RETURNED"
        shipment["returned_at"] = clock.now_iso()
        touch(shipment)
        if order is not None:
            order["fulfillment_status"] = "RETURNED"
            order["returned_at"] = clock.now_iso()
            orders_svc.reverse_order(order, shipment_id=shipment["id"])
            touch(order)
    return response.obj(serialize.shipment(shipment))
