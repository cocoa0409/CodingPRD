"""Technician, dispenser, and training record endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import services as svc
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_FACILITY_INACTIVE, ERR_VALIDATION,
    ERR_INCOMPATIBLE_PLACEMENT, ERR_TECHNICIAN_WINDOW_CONFLICT,
    ERR_TRAINING_NOT_CERTIFIED, not_found, forbidden,
)
from middleware import require_roles, check_facility_ownership
from response import success_object, success_list
from routes_facilities import get_facility_or_404
from routes_products import get_product_or_404

bp = Blueprint("field", __name__)


def _pagination():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise ApiError(ERR_VALIDATION, "limit/offset must be integers", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_VALIDATION, "limit must be 1..100, offset >= 0", 400)
    return limit, offset


def _sort_by_created(items):
    items.sort(key=lambda x: clock.parse_iso(x["created_at"]))
    return items


# ---------------------------------------------------------------------------
# Technicians
# ---------------------------------------------------------------------------

@bp.post("/jansan/technicians")
def create_technician():
    require_roles("DistributorAdmin")
    body = request.get_json(silent=True) or {}
    name = svc.as_str(svc.require_field(body, "name"), "name")
    t = svc.base_resource()
    t.update({"name": name, "status": "ACTIVE"})
    db.technicians[t["id"]] = t
    return success_object(dict(t), 201)


def get_technician_or_404(technician_id):
    t = db.technicians.get(technician_id)
    if t is None:
        raise not_found("Technician not found")
    return t


# ---------------------------------------------------------------------------
# Dispensers
# ---------------------------------------------------------------------------

@bp.post("/jansan/dispensers")
def create_dispenser():
    require_roles("DistributorAdmin")
    body = request.get_json(silent=True) or {}
    facility_id = svc.as_str(svc.require_field(body, "facility_id"), "facility_id")
    product_id = svc.as_str(svc.require_field(body, "product_id"), "product_id")
    zone = svc.as_str(svc.require_field(body, "zone"), "zone")
    technician_id = svc.as_str(svc.require_field(body, "technician_id"), "technician_id")
    facility = get_facility_or_404(facility_id)
    product = get_product_or_404(product_id)
    get_technician_or_404(technician_id)
    is_raw = svc.require_field(body, "install_start")
    ie_raw = svc.require_field(body, "install_end")
    install_start = svc.as_datetime(is_raw, "install_start")
    install_end = svc.as_datetime(ie_raw, "install_end")
    if install_end <= install_start:
        raise ApiError(ERR_VALIDATION, "install_end must be > install_start", 400)
    if product["category"] != "CHEMICAL":
        raise ApiError(ERR_VALIDATION, "Dispenser product must have category CHEMICAL", 400)

    # Zone incompatibility (ACID x OXIDIZER in same facility+zone, SCHEDULED/INSTALLED)
    new_family = product["chemical_family"]
    if new_family in ("ACID", "OXIDIZER"):
        for d in db.dispensers.values():
            if d["facility_id"] != facility_id or d["zone"] != zone:
                continue
            if d["status"] not in ("SCHEDULED", "INSTALLED"):
                continue
            other = db.products.get(d["product_id"])
            if other is None:
                continue
            of = other["chemical_family"]
            if (new_family == "ACID" and of == "OXIDIZER") or (new_family == "OXIDIZER" and of == "ACID"):
                raise ApiError(ERR_INCOMPATIBLE_PLACEMENT,
                               "ACID/OXIDIZER pairing in same facility+zone", 409)

    # Technician window conflict (half-open [start, end))
    for d in db.dispensers.values():
        if d["technician_id"] != technician_id:
            continue
        if d["status"] not in ("SCHEDULED", "INSTALLED"):
            continue
        os_ = clock.parse_iso(d["install_start"])
        oe = clock.parse_iso(d["install_end"])
        # half-open overlap: start < other_end AND other_start < end
        if install_start < oe and os_ < install_end:
            raise ApiError(ERR_TECHNICIAN_WINDOW_CONFLICT,
                           "Install window overlaps another install for this technician", 409)

    d = svc.base_resource()
    d.update({
        "facility_id": facility_id,
        "product_id": product_id,
        "zone": zone,
        "technician_id": technician_id,
        "install_start": clock.iso_format(install_start),
        "install_end": clock.iso_format(install_end),
        "status": "SCHEDULED",
        "installed_at": None,
    })
    db.dispensers[d["id"]] = d
    return success_object(dict(d), 201)


def get_dispenser_or_404(dispenser_id):
    d = db.dispensers.get(dispenser_id)
    if d is None:
        raise not_found("Dispenser not found")
    return d


@bp.get("/jansan/dispensers/<dispenser_id>")
def get_dispenser(dispenser_id):
    user_id, role = require_roles("DistributorAdmin", "FacilityManager", "FieldTechnician")
    d = get_dispenser_or_404(dispenser_id)
    check_facility_ownership(user_id, role, d["facility_id"])
    return success_object(dict(d))


@bp.get("/jansan/dispensers")
def list_dispensers():
    user_id, role = require_roles("DistributorAdmin", "FacilityManager", "FieldTechnician")
    facility_id = request.args.get("facility_id")
    product_id = request.args.get("product_id")
    technician_id = request.args.get("technician_id")
    status = request.args.get("status")
    limit, offset = _pagination()
    items = list(db.dispensers.values())
    if role == "FacilityManager":
        items = [d for d in items if d["facility_id"] == user_id]
    if facility_id:
        items = [d for d in items if d["facility_id"] == facility_id]
    if product_id:
        items = [d for d in items if d["product_id"] == product_id]
    if technician_id:
        items = [d for d in items if d["technician_id"] == technician_id]
    if status:
        items = [d for d in items if d["status"] == status]
    _sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([dict(d) for d in page], limit, offset, total)


@bp.post("/jansan/dispensers/<dispenser_id>/complete")
def complete_dispenser(dispenser_id):
    user_id, role = require_roles("FieldTechnician")
    d = get_dispenser_or_404(dispenser_id)
    # ownership (priority 3)
    if d["technician_id"] != user_id:
        raise forbidden("FieldTechnician may only complete their own installs")
    # state (priority 7)
    if d["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "Dispenser is not SCHEDULED", 409)
    # facility gate (priority 8)
    facility = db.facilities.get(d["facility_id"])
    if facility is None or facility["status"] != "ACTIVE":
        raise ApiError(ERR_FACILITY_INACTIVE, "Facility is not ACTIVE", 409)
    # dilution training (priority 11)
    product = db.products.get(d["product_id"])
    if product is not None and product["dilution_required"]:
        certified = any(
            t["facility_id"] == d["facility_id"]
            and t["product_id"] == d["product_id"]
            and t["status"] == "CERTIFIED"
            for t in db.training_records.values()
        )
        if not certified:
            raise ApiError(ERR_TRAINING_NOT_CERTIFIED,
                           "Dilution-required chemical lacks CERTIFIED training record", 409)
    d["status"] = "INSTALLED"
    d["installed_at"] = clock.iso_now()
    svc.touch(d)
    svc.recompute_closed_loop(facility)
    return success_object(dict(d))


@bp.post("/jansan/dispensers/<dispenser_id>/decommission")
def decommission_dispenser(dispenser_id):
    require_roles("DistributorAdmin")
    d = get_dispenser_or_404(dispenser_id)
    if d["status"] != "INSTALLED":
        raise ApiError(ERR_INVALID_STATE, "Dispenser is not INSTALLED", 409)
    d["status"] = "DECOMMISSIONED"
    svc.touch(d)
    facility = db.facilities.get(d["facility_id"])
    if facility:
        svc.recompute_closed_loop(facility)
    return success_object(dict(d))


# ---------------------------------------------------------------------------
# Training records
# ---------------------------------------------------------------------------

@bp.post("/jansan/training-records")
def create_training_record():
    require_roles("DistributorAdmin")
    body = request.get_json(silent=True) or {}
    facility_id = svc.as_str(svc.require_field(body, "facility_id"), "facility_id")
    product_id = svc.as_str(svc.require_field(body, "product_id"), "product_id")
    employee = svc.as_str(svc.require_field(body, "employee_name"), "employee_name")
    get_facility_or_404(facility_id)
    get_product_or_404(product_id)
    t = svc.base_resource()
    t.update({
        "facility_id": facility_id,
        "product_id": product_id,
        "employee_name": employee,
        "status": "SCHEDULED",
        "score_pct": None,
        "certified_at": None,
        "expires_at": None,
    })
    db.training_records[t["id"]] = t
    return success_object(dict(t), 201)


@bp.get("/jansan/training-records/<training_record_id>")
def get_training_record(training_record_id):
    user_id, role = require_roles("DistributorAdmin", "FacilityManager", "SalesRep")
    t = db.training_records.get(training_record_id)
    if t is None:
        raise not_found("Training record not found")
    check_facility_ownership(user_id, role, t["facility_id"])
    return success_object(dict(t))


@bp.get("/jansan/training-records")
def list_training_records():
    user_id, role = require_roles("DistributorAdmin", "FacilityManager", "SalesRep")
    facility_id = request.args.get("facility_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    limit, offset = _pagination()
    items = list(db.training_records.values())
    if role == "FacilityManager":
        items = [t for t in items if t["facility_id"] == user_id]
    if facility_id:
        items = [t for t in items if t["facility_id"] == facility_id]
    if product_id:
        items = [t for t in items if t["product_id"] == product_id]
    if status:
        items = [t for t in items if t["status"] == status]
    _sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([dict(t) for t in page], limit, offset, total)


@bp.post("/jansan/training-records/<training_record_id>/certify")
def certify_training_record(training_record_id):
    require_roles("DistributorAdmin")
    t = db.training_records.get(training_record_id)
    if t is None:
        raise not_found("Training record not found")
    body = request.get_json(silent=True) or {}
    score = svc.as_int(svc.require_field(body, "score_pct"), "score_pct")
    if score < 0 or score > 100:
        raise ApiError(ERR_VALIDATION, "score_pct must be in 0..100", 400)
    if t["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "Training record is not SCHEDULED", 409)
    t["score_pct"] = score
    if score >= svc.PASS_SCORE_PCT:
        now = clock.now()
        t["status"] = "CERTIFIED"
        t["certified_at"] = clock.iso_format(now)
        t["expires_at"] = clock.iso_format(now + timedelta(days=svc.TRAINING_VALIDITY_DAYS))
    else:
        t["status"] = "FAILED"
    svc.touch(t)
    return success_object(dict(t))
