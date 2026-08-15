"""EquipmentLine endpoints (PRD §3.2). Two parallel state dimensions evolve
independently on one row: dedication_status (UNASSESSED -> DEDICATED | SHARED)
and kosherization_state (NONE <-> VALID -> EXPIRED / COMPROMISED)."""
from datetime import timedelta

from flask import Blueprint

from db import logical_now, new_common, store, touch
from errors import err
from middleware import get_or_404, require_client_scope, require_roles
from response import Paginator, created, ok
from validation import body_json, req_enum, req_str

bp = Blueprint("equipment", __name__)

KOSHERIZATION_VALIDITY_HOURS = 72


@bp.post("/equipment-lines")
def create_equipment_line():
    data = body_json()
    facility_id = req_str(data, "facility_id")
    designation = req_str(data, "designation")
    require_roles("ClientContact", "AccountManager")
    facility = get_or_404(store.facilities, facility_id, "Facility")
    require_client_scope(facility["client_id"])
    line = new_common({
        "facility_id": facility_id,
        "designation": designation,
        "dedication_status": "UNASSESSED",
        "kosherization_state": "NONE",
        "kosherized_valid_until": None,
    })
    store.equipment_lines[line["id"]] = line
    return created(line)


@bp.get("/equipment-lines/<line_id>")
def get_equipment_line(line_id):
    return ok(get_or_404(store.equipment_lines, line_id, "EquipmentLine"))


@bp.get("/facilities/<facility_id>/equipment-lines")
def list_facility_equipment_lines(facility_id):
    get_or_404(store.facilities, facility_id, "Facility")
    p = Paginator()
    rows = [l for l in store.equipment_lines.values() if l["facility_id"] == facility_id]
    return ok(p(rows), rtype="array", pagination=p)


@bp.post("/equipment-lines/<line_id>/assess")
def assess_equipment_line(line_id):
    data = body_json()
    dedication = req_enum(data, "dedication_status", ("DEDICATED", "SHARED"))
    require_roles("CertificationReviewer")
    line = get_or_404(store.equipment_lines, line_id, "EquipmentLine")
    if line["dedication_status"] != "UNASSESSED":
        err("ERR_EQUIPMENT_LINE_INVALID_STATE",
            "assess requires dedication_status UNASSESSED")
    facility = store.facilities.get(line["facility_id"])
    if facility is None or facility["status"] not in ("PENDING_REVIEW", "APPROVED"):
        err("ERR_FACILITY_INVALID_STATE",
            "assessment requires the hosting facility PENDING_REVIEW or APPROVED")
    line["dedication_status"] = dedication
    # A SHARED line is never clean by default.
    if dedication == "SHARED" and line["kosherization_state"] == "NONE":
        line["kosherization_state"] = "EXPIRED"
    touch(line)
    return ok(line)


@bp.post("/equipment-lines/<line_id>/kosherization-events")
def record_kosherization_event(line_id):
    body_json()  # no fields; consume/ignore body shape
    require_roles("FieldSupervisor")
    line = get_or_404(store.equipment_lines, line_id, "EquipmentLine")
    facility = store.facilities.get(line["facility_id"])
    if facility is None or facility["status"] != "APPROVED":
        err("ERR_FACILITY_INVALID_STATE",
            "kosherization requires the hosting facility APPROVED")
    if line["kosherization_state"] not in ("NONE", "EXPIRED", "COMPROMISED"):
        err("ERR_EQUIPMENT_LINE_INVALID_STATE",
            "kosherization requires kosherization_state NONE, EXPIRED or COMPROMISED")
    line["kosherization_state"] = "VALID"
    line["kosherized_valid_until"] = logical_now() + timedelta(hours=KOSHERIZATION_VALIDITY_HOURS)
    touch(line)
    return created(line)


@bp.post("/equipment-lines/<line_id>/report-compromise")
def report_compromise(line_id):
    body_json()
    require_roles("FieldSupervisor")
    line = get_or_404(store.equipment_lines, line_id, "EquipmentLine")
    if line["kosherization_state"] == "COMPROMISED":
        err("ERR_EQUIPMENT_LINE_INVALID_STATE",
            "line is already COMPROMISED")
    line["kosherization_state"] = "COMPROMISED"
    line["kosherized_valid_until"] = None
    touch(line)
    return ok(line)
