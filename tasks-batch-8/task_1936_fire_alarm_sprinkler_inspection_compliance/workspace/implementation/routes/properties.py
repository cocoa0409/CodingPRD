"""Property endpoints."""

from flask import Blueprint, request

from db import store
from middleware import (
    require_roles, ALL_ROLES, MARSHAL_AND_ADMIN,
    ROLE_CONTRACTOR_ADMIN,
)
from response import success_object, list_response
from util import get_body, check_unknown_fields, req_str, req_enum
from errors import invalid_state, open_items_block
from services.core import (
    base_record, public, touch,
    get_property, ref_contractor,
    require_contractor_active, contractor_of_property,
)
from services import calc

bp = Blueprint("properties", __name__)

OCCUPANCY_CLASSES = {
    "ASSEMBLY", "BUSINESS", "EDUCATIONAL",
    "MERCANTILE", "RESIDENTIAL", "STORAGE",
}


@bp.route("/fire-compliance/properties", methods=["POST"])
def create_property():
    require_roles([ROLE_CONTRACTOR_ADMIN])
    body = get_body()
    check_unknown_fields(body, {"contractor_id", "address_line", "occupancy_class", "jurisdiction_code"})
    contractor_id = req_str(body, "contractor_id")
    address_line = req_str(body, "address_line")
    jurisdiction_code = req_str(body, "jurisdiction_code")
    con = ref_contractor(contractor_id)
    require_contractor_active(con)
    occupancy_class = req_enum(body, "occupancy_class", OCCUPANCY_CLASSES)

    rec = base_record()
    rec.update({
        "contractor_id": con["id"],
        "address_line": address_line,
        "occupancy_class": occupancy_class,
        "jurisdiction_code": jurisdiction_code,
        "status": "ACTIVE",
    })
    store.properties[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/fire-compliance/properties/<pid>", methods=["GET"])
def fetch_property(pid):
    require_roles(ALL_ROLES)
    return success_object(public(get_property(pid)))


@bp.route("/fire-compliance/properties", methods=["GET"])
def list_properties():
    require_roles(MARSHAL_AND_ADMIN)
    contractor_id = request.args.get("contractor_id")
    occupancy_class = request.args.get("occupancy_class")
    rows = list(store.properties.values())
    if contractor_id is not None:
        rows = [p for p in rows if p["contractor_id"] == contractor_id]
    if occupancy_class is not None:
        rows = [p for p in rows if p["occupancy_class"] == occupancy_class]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/properties/<pid>/archive", methods=["POST"])
def archive_property(pid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    prop = get_property(pid)
    if prop["status"] != "ACTIVE":
        raise invalid_state("Property is not ACTIVE")
    con = contractor_of_property(prop)
    require_contractor_active(con)
    # every system must be DECOMMISSIONED
    for sys in store.systems.values():
        if sys["property_id"] == prop["id"] and sys["status"] != "DECOMMISSIONED":
            raise open_items_block("Property has systems still in service")
    # no false-alarm case in OPEN or ASSESSED
    for case in store.false_alarm_cases.values():
        if case["property_id"] == prop["id"] and case["status"] in ("OPEN", "ASSESSED"):
            raise open_items_block("Property has unresolved false-alarm cases")

    # cascade: DRAFT/SCHEDULED plans -> LAPSED (with their SCHEDULED children
    # cancelled, per the lapse transition's side effects)
    for plan in store.plans.values():
        if plan["property_id"] == prop["id"] and plan["plan_posture"] in ("DRAFT", "SCHEDULED"):
            plan["plan_posture"] = "LAPSED"
            touch(plan)
            for ev in store.events.values():
                if ev["plan_id"] == plan["id"] and ev["status"] == "SCHEDULED":
                    ev["status"] = "CANCELLED"
                    touch(ev)
    prop["status"] = "ARCHIVED"
    touch(prop)
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(prop))
