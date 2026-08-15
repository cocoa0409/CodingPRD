"""Technician and LicenseRecord endpoints."""

from flask import Blueprint, request

from db import store
from middleware import (
    require_roles, ALL_ROLES, MARSHAL_AND_ADMIN,
    ROLE_CONTRACTOR_ADMIN, ROLE_FIRE_MARSHAL,
)
from response import success_object, list_response
from util import get_body, check_unknown_fields, req_str, req_enum, req_date
from errors import invalid_state, open_items_block, invalid_date_range
from services.core import (
    base_record, public, touch,
    get_contractor, get_technician, get_license,
    require_contractor_active,
)
from services import calc

bp = Blueprint("technicians", __name__)

NICET_LEVELS = {"I", "II", "III", "IV"}
LICENSE_CLASSES = {"ALARM", "SPRINKLER", "BACKFLOW", "PUMP"}


@bp.route("/fire-compliance/contractors/<cid>/technicians", methods=["POST"])
def create_technician(cid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    con = get_contractor(cid)
    body = get_body()
    check_unknown_fields(body, {"full_name", "nicet_level"})
    full_name = req_str(body, "full_name")
    nicet_level = req_enum(body, "nicet_level", NICET_LEVELS)
    require_contractor_active(con)

    rec = base_record()
    rec.update({
        "contractor_id": con["id"],
        "full_name": full_name,
        "nicet_level": nicet_level,
        "status": "ACTIVE",
    })
    store.technicians[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/fire-compliance/contractors/<cid>/technicians", methods=["GET"])
def list_technicians(cid):
    require_roles(MARSHAL_AND_ADMIN)
    con = get_contractor(cid)
    rows = [t for t in store.technicians.values() if t["contractor_id"] == con["id"]]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/technicians/<tid>", methods=["GET"])
def fetch_technician(tid):
    require_roles(ALL_ROLES)
    return success_object(public(get_technician(tid)))


@bp.route("/fire-compliance/technicians/<tid>/deactivate", methods=["POST"])
def deactivate_technician(tid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    tech = get_technician(tid)
    if tech["status"] != "ACTIVE":
        raise invalid_state("Technician is not ACTIVE")
    con = store.contractors.get(tech["contractor_id"])
    require_contractor_active(con)
    # open engagements block deactivation
    for ev in store.events.values():
        if ev["lead_technician_id"] == tech["id"] and ev["status"] in ("SCHEDULED", "IN_PROGRESS"):
            raise open_items_block("Technician has open inspection events")

    tech["status"] = "INACTIVE"
    # sweep lapsed licenses for this technician
    today = store.today()
    for lic in store.license_records.values():
        if (lic["technician_id"] == tech["id"] and lic["status"] == "ACTIVE"
                and today > lic["expires_on"]):
            lic["status"] = "EXPIRED"
            touch(lic)
    touch(tech)
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(tech))


# ---- LicenseRecord ----

@bp.route("/fire-compliance/technicians/<tid>/license-records", methods=["POST"])
def create_license_record(tid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    tech = get_technician(tid)
    body = get_body()
    check_unknown_fields(body, {"license_class", "issued_on", "expires_on"})
    issued_on = req_date(body, "issued_on")
    expires_on = req_date(body, "expires_on")
    # date-range (priority 10) before enum membership (priority 14)
    if not expires_on > issued_on:
        raise invalid_date_range("expires_on must be strictly after issued_on")
    license_class = req_enum(body, "license_class", LICENSE_CLASSES)
    con = store.contractors.get(tech["contractor_id"])
    require_contractor_active(con)

    rec = base_record()
    rec.update({
        "technician_id": tech["id"],
        "license_class": license_class,
        "issued_on": issued_on,
        "expires_on": expires_on,
        "status": "ACTIVE",
    })
    store.license_records[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/fire-compliance/technicians/<tid>/license-records", methods=["GET"])
def list_license_records(tid):
    require_roles(ALL_ROLES)
    tech = get_technician(tid)
    rows = [l for l in store.license_records.values() if l["technician_id"] == tech["id"]]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/license-records/<lid>", methods=["GET"])
def fetch_license_record(lid):
    require_roles(MARSHAL_AND_ADMIN)
    return success_object(public(get_license(lid)))


@bp.route("/fire-compliance/license-records/<lid>/revoke", methods=["POST"])
def revoke_license(lid):
    require_roles([ROLE_FIRE_MARSHAL])
    lic = get_license(lid)
    if lic["status"] != "ACTIVE":
        raise invalid_state("LicenseRecord is not ACTIVE")
    lic["status"] = "REVOKED"
    touch(lic)
    tech = store.technicians.get(lic["technician_id"])
    if tech is not None:
        con = store.contractors.get(tech["contractor_id"])
        if con is not None:
            calc.recompute_contractor(con)
    return success_object(public(lic))
