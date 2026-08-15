"""ProtectedSystem endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_CONTRACTOR_ADMIN
from response import success_object, list_response
from util import get_body, check_unknown_fields, req_enum, req_date
from errors import invalid_state, open_items_block, invalid_request
from services.core import (
    base_record, public, touch,
    get_property, get_system,
    contractor_of_property, require_contractor_active, require_property_active,
)
from services import calc

bp = Blueprint("systems", __name__)

SYSTEM_CATEGORIES = {"FIRE_ALARM", "SPRINKLER", "BACKFLOW", "FIRE_PUMP"}


@bp.route("/fire-compliance/properties/<pid>/systems", methods=["POST"])
def create_system(pid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    prop = get_property(pid)
    body = get_body()
    check_unknown_fields(body, {"system_category", "install_date", "certification_cycle_anchor"})
    install_date = req_date(body, "install_date")
    anchor = req_date(body, "certification_cycle_anchor")
    con = contractor_of_property(prop)
    require_contractor_active(con)
    require_property_active(prop)
    system_category = req_enum(body, "system_category", SYSTEM_CATEGORIES)
    # certification_cycle_anchor must be a valid calendar date in year 2000
    if anchor.year != 2000:
        raise invalid_request("certification_cycle_anchor must be a valid calendar date in year 2000")

    rec = base_record()
    rec.update({
        "property_id": prop["id"],
        "system_category": system_category,
        "install_date": install_date,
        "impairment_status": "NORMAL",
        "certification_cycle_anchor": anchor,
        "status": "IN_SERVICE",
    })
    store.systems[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/fire-compliance/properties/<pid>/systems", methods=["GET"])
def list_systems(pid):
    require_roles(ALL_ROLES)
    prop = get_property(pid)
    rows = [s for s in store.systems.values() if s["property_id"] == prop["id"]]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/systems/<sid>", methods=["GET"])
def fetch_system(sid):
    require_roles(ALL_ROLES)
    return success_object(public(get_system(sid)))


@bp.route("/fire-compliance/systems/<sid>/decommission", methods=["POST"])
def decommission_system(sid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    sys = get_system(sid)
    if sys["status"] != "IN_SERVICE":
        raise invalid_state("ProtectedSystem is not IN_SERVICE")
    prop = store.properties.get(sys["property_id"])
    con = contractor_of_property(prop) if prop else None
    require_contractor_active(con)
    require_property_active(prop)
    # no OPEN or NOTIFIED impairment on this system
    for imp in store.impairments.values():
        if imp["system_id"] == sys["id"] and imp["status"] in ("OPEN", "NOTIFIED"):
            raise open_items_block("System has an open impairment")
    # no ModificationPermit in APPLIED, ISSUED, or WORK_COMMENCED
    for perm in store.permits.values():
        if perm["system_id"] == sys["id"] and perm["status"] in ("APPLIED", "ISSUED", "WORK_COMMENCED"):
            raise open_items_block("System has an open modification permit")

    # cascade: every IN_SERVICE device -> REMOVED
    for dev in store.devices.values():
        if dev["system_id"] == sys["id"] and dev["status"] == "IN_SERVICE":
            dev["status"] = "REMOVED"
            touch(dev)
    # cascade: every SCHEDULED event referencing this system -> CANCELLED,
    # each cancellation re-evaluating its parent plan's posture. The cascade
    # does NOT recompute plan requirement counts (devices leaving service via
    # decommission are not the device-remove endpoint).
    affected_plans = set()
    for ev in store.events.values():
        if ev["system_id"] == sys["id"] and ev["status"] == "SCHEDULED":
            ev["status"] = "CANCELLED"
            touch(ev)
            affected_plans.add(ev["plan_id"])
    sys["status"] = "DECOMMISSIONED"
    sys["impairment_status"] = "OUT_OF_SERVICE"
    touch(sys)
    for plan_id in affected_plans:
        plan = store.plans.get(plan_id)
        if plan is not None:
            calc.derive_plan_posture(plan)
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(sys))
