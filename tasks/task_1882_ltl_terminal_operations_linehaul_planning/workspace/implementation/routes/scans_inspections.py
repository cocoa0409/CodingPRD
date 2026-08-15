"""Dimensioner scan and re-class inspection endpoints (PRD section 3.4)."""
from flask import Blueprint, g, request

import db
from errors import (err_invalid_state, err_scan_shipment_mismatch)
from middleware import require_roles
from response import success, success_list
from routes.common import (as_enum, as_int, body_json, get_path, new_record,
                           paginate, resolve_fk, ser_inspection, ser_scan,
                           touch)
from services.calculations import NMFC_CLASSES, dim_weight_lbs, freight_rating

bp = Blueprint("scans_inspections", __name__)

_READ_ROLES = ("TerminalAdmin", "RatingClerk", "OsdClerk")


# --- DimensionerScan (append-only: id + created_at only) ------------------------

@bp.route("/ltl/dimensioner-scans", methods=["POST"])
@require_roles("RatingClerk")
def create_scan():
    body = body_json()
    shipment = resolve_fk("shipments", body.get("shipment_id"), "shipment_id")
    measured_length = as_int(body, "measured_length_in", minimum=1)
    measured_width = as_int(body, "measured_width_in", minimum=1)
    measured_height = as_int(body, "measured_height_in", minimum=1)
    measured_weight = as_int(body, "measured_weight_lbs", minimum=1)
    rec = new_record({
        "shipment_id": shipment["id"],
        "measured_length_in": measured_length,
        "measured_width_in": measured_width,
        "measured_height_in": measured_height,
        "measured_weight_lbs": measured_weight,
        "scanned_by": g.user_id,
    }, common=False)
    db.store["dimensioner_scans"][rec["id"]] = rec
    return success(ser_scan(rec), 201)


@bp.route("/ltl/dimensioner-scans", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_scans():
    items = list(db.store["dimensioner_scans"].values())
    value = request.args.get("shipment_id")
    if value is not None:
        items = [s for s in items if s["shipment_id"] == value]
    page, total, limit, offset = paginate(items)
    return success_list([ser_scan(s) for s in page], total, limit, offset)


@bp.route("/ltl/dimensioner-scans/<scanId>", methods=["GET"])
@require_roles(*_READ_ROLES)
def get_scan(scanId):
    return success(ser_scan(get_path("dimensioner_scans", scanId)))


@bp.route("/ltl/shipments/<shipmentId>/dimensioner-scans", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_shipment_scans(shipmentId):
    shipment = get_path("shipments", shipmentId)
    items = [s for s in db.store["dimensioner_scans"].values()
             if s["shipment_id"] == shipment["id"]]
    page, total, limit, offset = paginate(items)
    return success_list([ser_scan(s) for s in page], total, limit, offset)


# --- Inspection -------------------------------------------------------------------

def _apply_scan_basis(shipment, scan):
    """Rebase the shipment's weight fields from scan evidence."""
    dw = dim_weight_lbs(scan["measured_length_in"], scan["measured_width_in"],
                        scan["measured_height_in"])
    shipment["dim_weight_lbs"] = dw
    shipment["chargeable_weight_lbs"] = max(scan["measured_weight_lbs"], dw)


@bp.route("/ltl/inspections", methods=["POST"])
@require_roles("RatingClerk")
def create_inspection():
    body = body_json()
    shipment = resolve_fk("shipments", body.get("shipment_id"), "shipment_id")
    scan = resolve_fk("dimensioner_scans", body.get("scan_id"), "scan_id")
    # Priority 5: state preconditions.
    if shipment["rating_status"] not in ("RATED", "RERATED"):
        raise err_invalid_state(
            "Inspection requires shipment rating_status RATED or RERATED")
    if shipment["rating_status"] == "RERATED":
        # Re-inspection freshness: the scan must be newer than the scan behind
        # the previous inspection, ordered by created_at.
        priors = [i for i in db.store["inspections"].values()
                  if i["shipment_id"] == shipment["id"]]
        if priors:
            prior = max(priors, key=lambda i: (i["created_at"], i["_seq"]))
            prior_scan = db.store["dimensioner_scans"].get(prior["scan_id"])
            if prior_scan is not None:
                new_key = (scan["created_at"], scan["_seq"])
                old_key = (prior_scan["created_at"], prior_scan["_seq"])
                if not new_key > old_key:
                    raise err_invalid_state(
                        "Re-inspection requires a scan newer than the previous inspection's scan")
    # Priority 20: claimed class enum membership.
    claimed = as_enum(body, "claimed_nmfc_class", NMFC_CLASSES)
    # Priority 21: the scan must belong to this shipment.
    if scan["shipment_id"] != shipment["id"]:
        raise err_scan_shipment_mismatch()
    shipment["rating_status"] = "INSPECTION_PENDING"
    _apply_scan_basis(shipment, scan)
    touch(shipment)
    rec = new_record({
        "shipment_id": shipment["id"], "scan_id": scan["id"],
        "claimed_nmfc_class": claimed,
        "outcome": "PENDING", "adjustment_cents": 0,
    })
    db.store["inspections"][rec["id"]] = rec
    return success(ser_inspection(rec), 201)


@bp.route("/ltl/inspections", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_inspections():
    items = list(db.store["inspections"].values())
    for param in ("shipment_id", "scan_id", "outcome"):
        value = request.args.get(param)
        if value is not None:
            items = [i for i in items if i.get(param) == value]
    page, total, limit, offset = paginate(items)
    return success_list([ser_inspection(i) for i in page], total, limit, offset)


@bp.route("/ltl/inspections/<inspectionId>", methods=["GET"])
@require_roles(*_READ_ROLES)
def get_inspection(inspectionId):
    return success(ser_inspection(get_path("inspections", inspectionId)))


@bp.route("/ltl/shipments/<shipmentId>/inspections", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_shipment_inspections(shipmentId):
    shipment = get_path("shipments", shipmentId)
    items = [i for i in db.store["inspections"].values()
             if i["shipment_id"] == shipment["id"]]
    page, total, limit, offset = paginate(items)
    return success_list([ser_inspection(i) for i in page], total, limit, offset)


@bp.route("/ltl/inspections/<inspectionId>/confirm", methods=["POST"])
@require_roles("RatingClerk")
def confirm_inspection(inspectionId):
    insp = get_path("inspections", inspectionId)
    if insp["outcome"] != "PENDING":
        raise err_invalid_state("Only a PENDING inspection can be confirmed")
    shipment = db.store["shipments"][insp["shipment_id"]]
    scan = db.store["dimensioner_scans"][insp["scan_id"]]
    pre_inspection_rated = shipment["rated_amount_cents"]
    # DIM-variant re-rate under the claimed class.
    shipment["nmfc_class"] = insp["claimed_nmfc_class"]
    _apply_scan_basis(shipment, scan)
    shipment["rated_amount_cents"] = freight_rating(
        insp["claimed_nmfc_class"], shipment["chargeable_weight_lbs"],
        shipment["accessorial_codes"])
    shipment["rating_status"] = "RERATED"
    touch(shipment)
    insp["outcome"] = "CONFIRMED_RECLASS"
    insp["adjustment_cents"] = shipment["rated_amount_cents"] - pre_inspection_rated
    touch(insp)
    return success(ser_inspection(insp))


@bp.route("/ltl/inspections/<inspectionId>/reject", methods=["POST"])
@require_roles("RatingClerk")
def reject_inspection(inspectionId):
    insp = get_path("inspections", inspectionId)
    if insp["outcome"] != "PENDING":
        raise err_invalid_state("Only a PENDING inspection can be rejected")
    shipment = db.store["shipments"][insp["shipment_id"]]
    insp["outcome"] = "REJECTED"
    insp["adjustment_cents"] = 0
    touch(insp)
    shipment["chargeable_weight_lbs"] = shipment["actual_weight_lbs"]
    shipment["dim_weight_lbs"] = 0
    shipment["rating_status"] = "RATED"
    touch(shipment)
    return success(ser_inspection(insp))
