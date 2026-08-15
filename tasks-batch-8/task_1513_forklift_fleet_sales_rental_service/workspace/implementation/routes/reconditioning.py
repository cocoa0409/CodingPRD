"""Reconditioning order endpoints."""
from flask import Blueprint, request

import store
from auth import authenticate, authorize, ALL_ROLES
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_UNIT_NOT_AVAILABLE, ERR_UNIT_DISPOSITION_MISMATCH,
)
from util import (
    body_json, req_str, opt_str, new_record, bump,
    success_object, list_response, get_or_404,
)
import services

bp = Blueprint("reconditioning", __name__)


@bp.post("/fleet/reconditioning-orders")
def create_recon():
    _, role = authenticate()
    authorize(role, ["FleetManager"])
    body = body_json()
    unit_id = req_str(body, "unit_id")
    notes = opt_str(body, "notes")
    unit = get_or_404(store.units, unit_id, "Unit")
    if unit["disposition"] != "USED_SALE":
        raise_err(ERR_UNIT_DISPOSITION_MISMATCH, "Reconditioning requires disposition USED_SALE")
    if unit["availability_status"] != "AVAILABLE":
        raise_err(ERR_UNIT_NOT_AVAILABLE, "Unit must be AVAILABLE for reconditioning")
    rec = new_record()
    rec.update({
        "unit_id": unit_id,
        "notes": notes,
        "qc_fail_count": 0,
        "listing_price_cents": None,
        "status": "IN_PROGRESS",
    })
    store.reconditioning_orders[rec["id"]] = rec
    unit["availability_status"] = "IN_RECON"
    bump(unit)
    return success_object(services.serialize_reconditioning_order(rec), 201)


@bp.get("/fleet/reconditioning-orders/<rid>")
def get_recon(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    ro = get_or_404(store.reconditioning_orders, rid, "ReconditioningOrder")
    return success_object(services.serialize_reconditioning_order(ro), 200)


@bp.get("/fleet/reconditioning-orders")
def list_recons():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.reconditioning_orders.values())
    unit_id = request.args.get("unit_id")
    status = request.args.get("status")
    if unit_id:
        records = [r for r in records if r["unit_id"] == unit_id]
    if status:
        records = [r for r in records if r["status"] == status]
    return list_response(records, services.serialize_reconditioning_order)


@bp.post("/fleet/reconditioning-orders/<rid>/complete")
def complete_recon(rid):
    _, role = authenticate()
    authorize(role, ["FleetManager"])
    body = body_json()
    qc_result = req_str(body, "qc_result")
    if qc_result not in ("PASS", "FAIL"):
        raise_err(ERR_INVALID_REQUEST, "qc_result must be PASS or FAIL")
    listing_price = body.get("listing_price_cents")
    if qc_result == "PASS":
        if not isinstance(listing_price, int) or isinstance(listing_price, bool):
            raise_err(ERR_INVALID_REQUEST, "listing_price_cents is required on QC PASS")
        if listing_price < 0:
            raise_err(ERR_INVALID_REQUEST, "listing_price_cents must be >= 0")
    ro = get_or_404(store.reconditioning_orders, rid, "ReconditioningOrder")
    if ro["status"] != "IN_PROGRESS":
        raise_err(ERR_INVALID_STATE, "ReconditioningOrder must be IN_PROGRESS to complete")
    if qc_result == "FAIL":
        ro["qc_fail_count"] = ro.get("qc_fail_count", 0) + 1
        bump(ro)
        return success_object(services.serialize_reconditioning_order(ro), 200)
    # PASS
    ro["listing_price_cents"] = listing_price
    ro["status"] = "COMPLETED"
    bump(ro)
    unit = get_or_404(store.units, ro["unit_id"], "Unit")
    unit["availability_status"] = "LISTED"
    unit["resale_price_cents"] = listing_price
    bump(unit)
    return success_object(services.serialize_reconditioning_order(ro), 200)
