"""Property CRUD + reverse-reachability listings."""

from flask import Blueprint, request

import db
from auth import require_role
from clock import get_now_iso, sweep_time_transitions
from entities import new_property
from errors import raise_error
from response import success
from services import property as property_svc
from utils import paginate, require_fields, require_int, require_str, require_json

bp = Blueprint("properties", __name__)


@bp.route("/properties", methods=["POST"])
@require_role("HOAManager")
def create_property():
    body = require_json(request)
    require_fields(body, "homeowner_id", "address", "monthly_dues_cents")
    hid = require_str(body, "homeowner_id")
    address = require_str(body, "address")
    dues = require_int(body, "monthly_dues_cents", minimum=0)

    # FK check on body-referenced homeowner_id.
    if hid not in db.homeowners:
        raise_error("ERR_FK_NOT_FOUND", "homeowner_id does not resolve")

    # Uniqueness on address across community.
    for p in db.properties.values():
        if p["address"] == address:
            raise_error("ERR_UNIQUE_VIOLATION", "duplicate property address")

    now_iso = get_now_iso()
    row = new_property(hid, address, dues, now_iso)
    db.properties[row["id"]] = row
    return success(row, status=201)


@bp.route("/properties/<pid>", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager", "ComplianceOfficer")
def get_property(pid):
    sweep_time_transitions()
    p = db.properties.get(pid)
    if not p:
        raise_error("ERR_NOT_FOUND", "property not found")
    # Ensure derived fields are current at read time.
    property_svc.recompute(p, get_now_iso())
    return success(p)


@bp.route("/properties/<pid>/assessments", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def list_property_assessments(pid):
    if pid not in db.properties:
        raise_error("ERR_NOT_FOUND", "property not found")
    items = [a for a in db.assessments.values() if a["property_id"] == pid]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)


@bp.route("/properties/<pid>/arc-requests", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def list_property_arc_requests(pid):
    if pid not in db.properties:
        raise_error("ERR_NOT_FOUND", "property not found")
    items = [r for r in db.arc_requests.values() if r["property_id"] == pid]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)


@bp.route("/properties/<pid>/violations", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager", "ComplianceOfficer")
def list_property_violations(pid):
    if pid not in db.properties:
        raise_error("ERR_NOT_FOUND", "property not found")
    items = [v for v in db.violations.values() if v["property_id"] == pid]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)


@bp.route("/properties/<pid>/work-orders", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def list_property_work_orders(pid):
    if pid not in db.properties:
        raise_error("ERR_NOT_FOUND", "property not found")
    items = [w for w in db.work_orders.values() if w.get("related_property_id") == pid]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)
