"""ConditionReport endpoints (PRD §3.7)."""

from flask import Blueprint

import calc
import db
import system
from envelope import ok_object
from errors import fail
from security import require_roles, ALL_ROLES
from serializers import report_out
from validate import (json_body, req_str, req_bool, get_tour, get_shipment,
                      get_report, paginate, apply_filters, sorted_created)

bp = Blueprint("reports", __name__)


def _req_score(data, field):
    v = data.get(field)
    if not isinstance(v, int) or isinstance(v, bool) or not (0 <= v <= 100):
        fail("ERR_INVALID_REQUEST",
             "Field %s must be an integer between 0 and 100" % field)
    return v


@bp.route("/tours/<tour_id>/shipments/<shipment_id>/reports", methods=["POST"])
def create_report(tour_id, shipment_id):
    require_roles("Registrar")
    tour = get_tour(tour_id)
    shipment = get_shipment(tour, shipment_id)
    data = json_body()
    crate_id = data.get("crate_id")
    if not isinstance(crate_id, str) or not crate_id:
        fail("ERR_INVALID_REQUEST", "Missing or invalid required field: crate_id")
    inspector = req_str(data, "inspector_name")
    phase = data.get("phase")
    if phase not in ("UNPACK", "PACK"):
        fail("ERR_INVALID_REQUEST", "phase must be UNPACK or PACK")
    surface = _req_score(data, "surface_score")
    structural = _req_score(data, "structural_score")
    seal = req_bool(data, "seal_intact")
    # The crate must be on the shipment's manifest (business priority 14).
    if crate_id not in shipment["crate_ids"]:
        fail("ERR_CRATE_NOT_ON_SHIPMENT",
             "crate_id is not on the shipment's manifest")
    report = db.stamp_new({
        "id": db.new_id(),
        "shipment_id": shipment["id"],
        "crate_id": crate_id,
        "inspector_name": inspector,
        "phase": phase,
        "surface_score": surface,
        "structural_score": structural,
        "seal_intact": seal,
        "status": "DRAFT",
        "composite_score": None,
    })
    db.reports[report["id"]] = report
    return ok_object(report_out(report), status=201)


@bp.route("/tours/<tour_id>/shipments/<shipment_id>/reports", methods=["GET"])
def list_reports(tour_id, shipment_id):
    require_roles(*ALL_ROLES)
    tour = get_tour(tour_id)
    shipment = get_shipment(tour, shipment_id)
    items = system.reports_of_shipment(shipment["id"])
    items = apply_filters(items, [("crate_id", "crate_id"),
                                  ("phase", "phase"),
                                  ("status", "status")])
    return paginate([report_out(r) for r in sorted_created(items)])


@bp.route("/tours/<tour_id>/shipments/<shipment_id>/reports/<report_id>/transition",
          methods=["POST"])
def report_transition(tour_id, shipment_id, report_id):
    require_roles("Registrar", "Shipper", "TourManager")
    tour = get_tour(tour_id)
    shipment = get_shipment(tour, shipment_id)
    report = get_report(shipment, report_id)
    data = json_body()
    action = data.get("action")
    if action not in ("SUBMIT", "ACCEPT", "DISPUTE"):
        fail("ERR_INVALID_REQUEST", "Unrecognized action: %r" % action)
    # Action-level authorization: SUBMIT Registrar; ACCEPT TourManager;
    # DISPUTE Shipper.
    if action == "SUBMIT":
        require_roles("Registrar")
    elif action == "ACCEPT":
        require_roles("TourManager")
    else:
        require_roles("Shipper")

    if action == "SUBMIT":
        if report["status"] != "DRAFT":
            fail("ERR_INVALID_STATE", "SUBMIT is only permitted from DRAFT")
        if report["phase"] == "UNPACK":
            if shipment["status"] not in ("RECEIVED", "DAMAGE_HOLD"):
                fail("ERR_INVALID_STATE",
                     "UNPACK reports submit only while the shipment is "
                     "RECEIVED or DAMAGE_HOLD")
        else:
            # PACK: the stop the crates are packing out of (the shipment's
            # origin, or its destination for the first leg) must be TEARDOWN
            # or CLOSED.
            pack_stop_id = shipment["origin_stop_id"] \
                or shipment["destination_stop_id"]
            pack_stop = db.stops.get(pack_stop_id)
            if pack_stop is None \
                    or pack_stop["status"] not in ("TEARDOWN", "CLOSED"):
                fail("ERR_INVALID_STATE",
                     "PACK reports submit only while the stop is TEARDOWN or "
                     "CLOSED")
        report["composite_score"] = calc.condition_composite(
            report["surface_score"], report["structural_score"],
            report["seal_intact"])
        report["status"] = "SUBMITTED"
        db.touch(report)
        if report["phase"] == "UNPACK" \
                and report["composite_score"] < calc.DAMAGE_THRESHOLD \
                and shipment["status"] == "RECEIVED":
            shipment["status"] = "DAMAGE_HOLD"
            db.touch(shipment)
        return ok_object(report_out(report))

    if action == "ACCEPT":
        if report["status"] not in ("SUBMITTED", "DISPUTED"):
            fail("ERR_INVALID_STATE",
                 "ACCEPT is only permitted from SUBMITTED or DISPUTED")
        report["status"] = "ACCEPTED"
        db.touch(report)
        crate = db.crates.get(report["crate_id"])
        if crate is not None:
            crate["condition_score"] = report["composite_score"]
            db.touch(crate)
        return ok_object(report_out(report))

    # DISPUTE
    if report["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "DISPUTE is only permitted from SUBMITTED")
    report["status"] = "DISPUTED"
    db.touch(report)
    return ok_object(report_out(report))
