"""Contractor endpoints."""

from flask import Blueprint, request

from db import store
from middleware import (
    require_roles, ALL_ROLES, MARSHAL_AND_ADMIN,
    ROLE_FIRE_MARSHAL,
)
from response import success_object, list_response
from util import get_body, check_unknown_fields, req_str
from errors import duplicate_constraint, invalid_state, open_items_block
from services.core import (
    base_record, public, touch, get_contractor,
)
from services import calc

bp = Blueprint("contractors", __name__)


@bp.route("/fire-compliance/contractors", methods=["POST"])
def create_contractor():
    require_roles([ROLE_FIRE_MARSHAL])
    body = get_body()
    check_unknown_fields(body, {"legal_name", "state_license_no"})
    legal_name = req_str(body, "legal_name")
    state_license_no = req_str(body, "state_license_no")

    # uniqueness: state_license_no globally unique (priority 13)
    for c in store.contractors.values():
        if c["state_license_no"] == state_license_no:
            raise duplicate_constraint("state_license_no is already registered")

    rec = base_record()
    rec.update({
        "legal_name": legal_name,
        "state_license_no": state_license_no,
        "compliance_score": 1000,
        "posture": "GOOD_STANDING",
        "status": "ACTIVE",
    })
    store.contractors[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/fire-compliance/contractors/<cid>", methods=["GET"])
def fetch_contractor(cid):
    require_roles(ALL_ROLES)
    return success_object(public(get_contractor(cid)))


@bp.route("/fire-compliance/contractors", methods=["GET"])
def list_contractors():
    require_roles(MARSHAL_AND_ADMIN)
    posture = request.args.get("posture")
    rows = list(store.contractors.values())
    if posture is not None:
        rows = [c for c in rows if c["posture"] == posture]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/contractors/<cid>/deactivate", methods=["POST"])
def deactivate_contractor(cid):
    require_roles([ROLE_FIRE_MARSHAL])
    con = get_contractor(cid)
    if con["status"] != "ACTIVE":
        raise invalid_state("Contractor is not ACTIVE")
    # no InspectionEvent in SCHEDULED or IN_PROGRESS under any plan of any
    # property of this contractor
    for prop in store.properties.values():
        if prop["contractor_id"] != con["id"]:
            continue
        for plan in store.plans.values():
            if plan["property_id"] != prop["id"]:
                continue
            for ev in store.events.values():
                if ev["plan_id"] == plan["id"] and ev["status"] in ("SCHEDULED", "IN_PROGRESS"):
                    raise open_items_block("Contractor has open inspection events")

    now = store.now()
    # cascade: every technician -> INACTIVE
    for tech in store.technicians.values():
        if tech["contractor_id"] == con["id"] and tech["status"] != "INACTIVE":
            tech["status"] = "INACTIVE"
            touch(tech)
    # cascade: every OPEN impairment on this contractor's systems -> CLOSED,
    # restored_at stamped at deactivation time
    for prop in store.properties.values():
        if prop["contractor_id"] != con["id"]:
            continue
        for sys in store.systems.values():
            if sys["property_id"] != prop["id"]:
                continue
            for imp in store.impairments.values():
                if imp["system_id"] == sys["id"] and imp["status"] == "OPEN":
                    imp["status"] = "CLOSED"
                    imp["restored_at"] = now
                    touch(imp)
    # DRAFT marshal reports leave the workflow but remain queryable with status
    # unchanged — no record mutation.
    con["status"] = "DEACTIVATED"
    touch(con)
    calc.recompute_contractor(con)
    return success_object(public(con))


@bp.route("/fire-compliance/contractors/<cid>/audit-score", methods=["POST"])
def audit_score(cid):
    require_roles([ROLE_FIRE_MARSHAL])
    con = get_contractor(cid)
    audited, provisional = calc.audited_score(con)
    return success_object({
        "audited_score": audited,
        "provisional_score": provisional,
    })
