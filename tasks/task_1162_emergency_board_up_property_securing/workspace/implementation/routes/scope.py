"""Scope item endpoints."""
from flask import Blueprint, request
import db
from errors import err
from middleware import require_role, get_body, require_fields, check_enum, paginate_args
from response import success_obj, success_list
from services.common import (
    base_record, touch, get_or_404, serialize_scope_item,
    compute_scope_qty, recompute_job_total_planned_sheets,
    recompute_required_photo_count, find_current_assignment,
)

bp = Blueprint("scope", __name__)

SCOPE_KINDS = {"BOARD", "TARP", "FENCE"}
MEASUREMENT_FIELDS = ["opening_count", "width_in", "height_in", "door_count", "length_ft", "width_ft", "linear_ft"]


@bp.route("/jobs/<jid>/scope-items", methods=["POST"])
def create_scope_item(jid):
    require_role("Dispatcher")
    job = get_or_404(db.jobs, jid, "Job")
    body = get_body()
    require_fields(body, ["kind", "expected_job_version"])
    kind = check_enum(body["kind"], SCOPE_KINDS, "kind")
    if job["work_status"] == "CLOSED":
        raise err("ERR_ALREADY_TERMINAL", "Job is CLOSED")
    # scope add allowed until job reaches SECURED
    if job["work_status"] in ("SECURED", "READY_FOR_REMOVAL", "REMOVED"):
        raise err("ERR_INVALID_STATE", "Cannot add scope items in state %s" % job["work_status"])
    prop = db.properties.get(job["property_id"])
    wind_zone = prop["wind_zone"] if prop else "LOW"
    measurements = {k: body.get(k) for k in MEASUREMENT_FIELDS}
    planned_qty, unit = compute_scope_qty(kind, measurements, wind_zone)
    # OCC last
    expected = body["expected_job_version"]
    if not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_job_version must be integer")
    if expected != job["version"]:
        raise err("ERR_STALE_VERSION", "Stale job version")
    rec = base_record()
    rec.update({
        "job_id": job["id"],
        "kind": kind,
        "opening_count": body.get("opening_count"),
        "width_in": body.get("width_in"),
        "height_in": body.get("height_in"),
        "door_count": body.get("door_count", 0),
        "length_ft": body.get("length_ft"),
        "width_ft": body.get("width_ft"),
        "linear_ft": body.get("linear_ft"),
        "planned_qty": planned_qty,
        "unit": unit,
        "actual_qty": None,
        "status": "PLANNED",
    })
    db.scope_items[rec["id"]] = rec
    touch(job)
    recompute_job_total_planned_sheets(job["id"])
    return success_obj(serialize_scope_item(rec), 201)


@bp.route("/jobs/<jid>/scope-items", methods=["GET"])
def list_scope_items(jid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    get_or_404(db.jobs, jid, "Job")
    limit, offset = paginate_args()
    items = [s for s in db.scope_items.values() if s["job_id"] == jid]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_scope_item(s) for s in page], total, limit, offset)


@bp.route("/scope-items/<sid>/install", methods=["POST"])
def install_scope_item(sid):
    user_id, _ = require_role("Subcontractor")
    rec = get_or_404(db.scope_items, sid, "ScopeItem")
    body = get_body()
    job = db.jobs.get(rec["job_id"])
    if job is None:
        raise err("ERR_NOT_FOUND", "Parent job not found")
    assignee = find_current_assignment(job["id"])
    if assignee is None or assignee["subcontractor_id"] != user_id:
        raise err("ERR_NOT_ASSIGNEE", "Caller is not the assignee")
    if rec["status"] in ("INSTALLED", "VOIDED"):
        raise err("ERR_ALREADY_TERMINAL", "Scope item is terminal")
    if job["work_status"] != "ON_SITE":
        raise err("ERR_INVALID_STATE", "Job must be ON_SITE to install")
    prop = db.properties.get(job["property_id"])
    wind_zone = prop["wind_zone"] if prop else "LOW"
    # Use supplied measurements, falling back to existing item values
    measurements = {}
    for k in MEASUREMENT_FIELDS:
        v = body.get(k, rec.get(k))
        measurements[k] = v
    actual_qty, _unit = compute_scope_qty(rec["kind"], measurements, wind_zone)
    # persist the measurements actually used
    for k in MEASUREMENT_FIELDS:
        if k in body:
            rec[k] = body[k]
    rec["actual_qty"] = actual_qty
    rec["status"] = "INSTALLED"
    touch(rec)
    recompute_job_total_planned_sheets(job["id"])
    recompute_required_photo_count(job["id"])
    return success_obj(serialize_scope_item(rec))


@bp.route("/scope-items/<sid>/void", methods=["POST"])
def void_scope_item(sid):
    require_role("Dispatcher")
    rec = get_or_404(db.scope_items, sid, "ScopeItem")
    job = db.jobs.get(rec["job_id"])
    if job is None:
        raise err("ERR_NOT_FOUND", "Parent job not found")
    if rec["status"] in ("INSTALLED", "VOIDED"):
        raise err("ERR_ALREADY_TERMINAL", "Scope item is terminal")
    if job["work_status"] not in ("INTAKE", "DISPATCHED", "ON_SITE", "BREACH_HOLD"):
        raise err("ERR_INVALID_STATE", "Job state does not permit void")
    rec["status"] = "VOIDED"
    touch(rec)
    touch(job)
    recompute_job_total_planned_sheets(job["id"])
    recompute_required_photo_count(job["id"])
    return success_obj(serialize_scope_item(rec))
