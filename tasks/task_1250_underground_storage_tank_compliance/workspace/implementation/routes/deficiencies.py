"""Deficiency reads and owner-driven correction flow (PRD 3.5)."""
from flask import Blueprint

from authz import FACILITY_OWNER, READ_ROLES, check_facility_ownership, require_roles
from calc import recompute_posture
from db import store
from errors import deficiency_not_found, deficiency_not_open, deficiency_not_ordered
from respond import success
from routes.facilities import get_facility_or_404
from serialize import ser_deficiency
from store_ops import get_or_404, json_body, paginate, qparam, sorted_by_creation, touch

bp = Blueprint("deficiencies", __name__)


def get_deficiency_or_404(def_id):
    return get_or_404(store.deficiencies, def_id, deficiency_not_found)


@bp.route("/deficiencies", methods=["GET"])
def list_deficiencies():
    require_roles(READ_ROLES)
    items = store.deficiencies.values()
    for f in ("facility_id", "tank_system_id", "component_id",
              "source_service_order_id", "verified_by_service_order_id",
              "status", "severity"):
        v = qparam(f)
        if v is not None:
            items = [d for d in items if d[f] == v]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_deficiency(d) for d in page], response_type="array",
                   pagination=pagination)


@bp.route("/deficiencies/<def_id>", methods=["GET"])
def get_deficiency(def_id):
    require_roles(READ_ROLES)
    return success(ser_deficiency(get_deficiency_or_404(def_id)))


@bp.route("/deficiencies/<def_id>/order-correction", methods=["POST"])
def order_correction(def_id):
    uid, _ = require_roles([FACILITY_OWNER])
    json_body()  # no declared inputs
    d = get_deficiency_or_404(def_id)
    fac = get_facility_or_404(d["facility_id"])
    check_facility_ownership(uid, fac)
    if d["status"] not in ("OPEN", "ESCALATED"):
        raise deficiency_not_open()
    d["status"] = "CORRECTION_ORDERED"
    touch(d)
    # De-escalation (ESCALATED -> CORRECTION_ORDERED) lifts the surcharge.
    recompute_posture(fac)
    return success(ser_deficiency(d))


@bp.route("/deficiencies/<def_id>/mark-corrected", methods=["POST"])
def mark_corrected(def_id):
    uid, _ = require_roles([FACILITY_OWNER])
    json_body()
    d = get_deficiency_or_404(def_id)
    fac = get_facility_or_404(d["facility_id"])
    check_facility_ownership(uid, fac)
    if d["status"] != "CORRECTION_ORDERED":
        raise deficiency_not_ordered()
    d["status"] = "CORRECTED"
    touch(d)
    return success(ser_deficiency(d))
