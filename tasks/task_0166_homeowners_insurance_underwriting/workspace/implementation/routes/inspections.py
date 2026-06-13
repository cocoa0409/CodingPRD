"""Inspection routes (PRD §3.3) — 4-point inspection, buffer conflict, complete/reschedule."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success
from services.calc import wildfire_score
from services.common import (
    get_json_body, require_field, as_int, as_bool,
    get_or_404, parse_pagination, paginate,
)
from services.models import base_record, serialize, touch

bp = Blueprint("inspections", __name__)

# Inspection statuses that occupy an inspector's calendar for conflict checks.
_BLOCKING = {"SCHEDULED", "COMPLETED", "PASSED"}


def _conflicts(inspector_id, new_start, new_end, buffer_seconds, exclude_id=None):
    """True if [new_start,new_end) is within buffer of another blocking inspection
    on the same inspector. No conflict iff a_end+buf <= b_start OR b_end+buf <= a_start
    (half-open windows; an exact buffer gap is allowed)."""
    for ins in db.inspections.values():
        if ins["inspector_id"] != inspector_id:
            continue
        if exclude_id is not None and ins["id"] == exclude_id:
            continue
        if ins["status"] not in _BLOCKING:
            continue
        e_start, e_end = ins["window_start"], ins["window_end"]
        separated = (new_end + buffer_seconds <= e_start) or (e_end + buffer_seconds <= new_start)
        if not separated:
            return True
    return False


@bp.post("/inspections")
@require_roles("Underwriter")
def create_inspection():
    body = get_json_body()
    property_id = require_field(body, "property_id")
    inspector_id = require_field(body, "inspector_id")
    window_start = as_int(require_field(body, "window_start"), "window_start")
    window_end = as_int(require_field(body, "window_end"), "window_end")
    if window_end <= window_start:
        raise err("ERR_INVALID_REQUEST", "window_end must be > window_start.")

    with db.lock:
        # existence: body ids left-to-right (property then inspector)
        get_or_404("property", property_id)
        inspector = get_or_404("inspector", inspector_id)
        buffer_seconds = int(inspector["buffer_minutes"]) * 60
        if _conflicts(inspector_id, window_start, window_end, buffer_seconds):
            raise err("ERR_INSPECTION_WINDOW_CONFLICT",
                      "Inspection window collides with another inspection on this inspector.")
        rec = base_record()
        rec.update({
            "property_id": property_id,
            "inspector_id": inspector_id,
            "window_start": window_start,
            "window_end": window_end,
            "roof_ok": False,
            "electrical_ok": False,
            "plumbing_ok": False,
            "hvac_ok": False,
            "passed_count": 0,
            "status": "SCHEDULED",
        })
        db.inspections[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/inspections")
@require_roles("Admin", "Agent", "Underwriter", "Inspector")
def list_inspections():
    limit, offset = parse_pagination()
    property_id = request.args.get("property_id")
    inspector_id = request.args.get("inspector_id")
    with db.lock:
        items = list(db.inspections.values())
        if property_id is not None:
            items = [i for i in items if i["property_id"] == property_id]
        if inspector_id is not None:
            items = [i for i in items if i["inspector_id"] == inspector_id]
        window, meta = paginate(items, limit, offset)
        data = [serialize(i) for i in window]
    return success(data, status=200, list_meta=meta)


@bp.get("/inspections/<rid>")
@require_roles("Admin", "Agent", "Underwriter", "Inspector")
def get_inspection(rid):
    with db.lock:
        rec = get_or_404("inspection", rid)
        return success(serialize(rec), status=200)


@bp.post("/inspections/<rid>/complete")
@require_roles("Inspector")
def complete_inspection(rid):
    body = get_json_body()
    with db.lock:
        ins = get_or_404("inspection", rid)
        if ins["status"] != "SCHEDULED":
            raise err("ERR_INSPECTION_NOT_SCHEDULED", "complete requires Inspection in SCHEDULED.")
        # input integrity (lowest priority) after the state gate
        roof_ok = as_bool(require_field(body, "roof_ok"), "roof_ok")
        electrical_ok = as_bool(require_field(body, "electrical_ok"), "electrical_ok")
        plumbing_ok = as_bool(require_field(body, "plumbing_ok"), "plumbing_ok")
        hvac_ok = as_bool(require_field(body, "hvac_ok"), "hvac_ok")
        ins["roof_ok"] = roof_ok
        ins["electrical_ok"] = electrical_ok
        ins["plumbing_ok"] = plumbing_ok
        ins["hvac_ok"] = hvac_ok
        passed = sum(1 for v in (roof_ok, electrical_ok, plumbing_ok, hvac_ok) if v)
        ins["passed_count"] = passed
        if passed == 4:
            ins["status"] = "PASSED"
            _finalize_score(ins["property_id"])
        else:
            ins["status"] = "FAILED"
        touch(ins)
        return success(serialize(ins), status=200)


def _finalize_score(property_id):
    """On inspection PASS, flip the property's RiskAssessment to FINAL and recompute."""
    for ra in db.risk_assessments.values():
        if ra["property_id"] == property_id:
            ra["score_stage"] = "FINAL"
            ra["wildfire_score"] = wildfire_score(ra, "FINAL")
            touch(ra)


@bp.post("/inspections/<rid>/reschedule")
@require_roles("Inspector")
def reschedule_inspection(rid):
    body = get_json_body()
    with db.lock:
        ins = get_or_404("inspection", rid)
        if ins["status"] != "FAILED":
            raise err("ERR_INSPECTION_NOT_FAILED", "reschedule requires Inspection in FAILED.")
        window_start = as_int(require_field(body, "window_start"), "window_start")
        window_end = as_int(require_field(body, "window_end"), "window_end")
        if window_end <= window_start:
            raise err("ERR_INVALID_REQUEST", "window_end must be > window_start.")
        inspector = db.inspectors[ins["inspector_id"]]
        buffer_seconds = int(inspector["buffer_minutes"]) * 60
        if _conflicts(ins["inspector_id"], window_start, window_end, buffer_seconds, exclude_id=rid):
            raise err("ERR_INSPECTION_WINDOW_CONFLICT",
                      "Inspection window collides with another inspection on this inspector.")
        ins["window_start"] = window_start
        ins["window_end"] = window_end
        ins["roof_ok"] = False
        ins["electrical_ok"] = False
        ins["plumbing_ok"] = False
        ins["hvac_ok"] = False
        ins["passed_count"] = 0
        ins["status"] = "SCHEDULED"
        touch(ins)
        return success(serialize(ins), status=200)
