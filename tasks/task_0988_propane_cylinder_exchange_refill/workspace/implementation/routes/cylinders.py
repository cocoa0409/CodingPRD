"""Cylinder registration, reads, quarantine lifecycle."""
from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_VALIDATION, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND,
    ERR_INVALID_STATE, ERR_CYLINDER_NOT_CERTIFIED, ERR_FORBIDDEN,
)
from middleware import get_actor, require_roles
from response import success_object, success_list
from services import core
from util import body, req_str, opt_str, req_num, req_date, req_enum, add_years, paginate, sorted_by_creation

bp = Blueprint("cylinders", __name__)


def get_cylinder(cylinder_id):
    c = db.cylinders.get(cylinder_id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Cylinder not found")
    return c


@bp.route("/cylinders", methods=["POST"])
def create_cylinder():
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin", "SiteClerk"))
    b = body()
    serial = req_str(b, "serial_number")
    owner = req_enum(b, "owner_kind", ("FLEET", "CUSTOMER"))
    # Stage 2: a clerk never registers a fleet cylinder.
    if role == "SiteClerk" and owner == "FLEET":
        raise ApiError(ERR_FORBIDDEN, 403, "SiteClerk may register CUSTOMER cylinders only")
    wc = req_num(b, "water_capacity_lbs")
    if wc <= 0:
        raise ApiError(ERR_VALIDATION, 400, "water_capacity_lbs must be > 0")
    tw = req_num(b, "tare_weight_lbs")
    if tw <= 0:
        raise ApiError(ERR_VALIDATION, 400, "tare_weight_lbs must be > 0")
    mfg = req_date(b, "manufacture_date")
    initial_fill = req_enum(b, "initial_fill", ("FULL", "EMPTY"))
    site_id = opt_str(b, "current_site_id", None)
    if owner == "CUSTOMER" and site_id is not None:
        raise ApiError(ERR_VALIDATION, 400, "CUSTOMER cylinders must be registered with current_site_id null")
    # Stage 4: body reference existence.
    if site_id is not None and site_id not in db.sites:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "current_site_id does not reference an existing site")
    # Stage 11: serial uniqueness.
    for c in db.cylinders.values():
        if c["serial_number"] == serial:
            raise ApiError(ERR_VALIDATION, 400, "serial_number must be unique across cylinders")

    cyl = db.new_entity({
        "serial_number": serial,
        "owner_kind": owner,
        "water_capacity_lbs": wc,
        "tare_weight_lbs": tw,
        "manufacture_date": mfg,
        "certified_on": mfg,
        "certification_expires_on": add_years(mfg, core.INITIAL_CERT_YEARS),
        "cert_method_last": "INITIAL",
        "cert_status": "CERTIFIED",
        "fill_status": initial_fill,
        "current_site_id": site_id if owner == "FLEET" else None,
        "in_transit_run_id": None,
    })
    db.cylinders[cyl["id"]] = cyl
    return success_object(core.serialize(cyl), 201)


@bp.route("/cylinders/<cylinderId>", methods=["GET"])
def read_cylinder(cylinderId):
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin", "SiteClerk", "Technician", "ComplianceOfficer", "Driver"))
    return success_object(core.serialize(get_cylinder(cylinderId)))


@bp.route("/cylinders", methods=["GET"])
def list_cylinders():
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin", "SiteClerk", "Technician", "ComplianceOfficer"))
    items = list(db.cylinders.values())
    for param in ("current_site_id", "in_transit_run_id", "fill_status", "cert_status", "owner_kind"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[param] == v]
    items = sorted_by_creation(items)
    page, total, limit, offset = paginate(items)
    return success_list([core.serialize(c) for c in page], total, limit, offset)


@bp.route("/cylinders/<cylinderId>/quarantine", methods=["POST"])
def quarantine_cylinder(cylinderId):
    uid, role = get_actor()
    require_roles(role, ("ComplianceOfficer",))
    c = get_cylinder(cylinderId)
    if c["fill_status"] not in ("FULL", "EMPTY"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only FULL or EMPTY cylinders can be quarantined")
    c["fill_status"] = "QUARANTINED"
    db.touch(c)
    return success_object(core.serialize(c))


@bp.route("/cylinders/<cylinderId>/release-quarantine", methods=["POST"])
def release_quarantine(cylinderId):
    uid, role = get_actor()
    require_roles(role, ("ComplianceOfficer",))
    c = get_cylinder(cylinderId)
    if c["fill_status"] != "QUARANTINED":
        raise ApiError(ERR_INVALID_STATE, 409, "Cylinder is not quarantined")
    if c["cert_status"] != "CERTIFIED":
        raise ApiError(ERR_CYLINDER_NOT_CERTIFIED, 409, "Quarantine release requires cert_status CERTIFIED")
    c["fill_status"] = "EMPTY"
    db.touch(c)
    return success_object(core.serialize(c))
