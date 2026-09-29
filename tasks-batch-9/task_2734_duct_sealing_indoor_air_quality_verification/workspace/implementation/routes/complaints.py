"""Comfort complaints: diagnosis, the balancing cycle and the airflow readings."""

from flask import Blueprint

import calc
import lookup
import serialize
from envelope import array_response, object_response
from errors import ApiError
from guard import (ALL_ROLES, ROLE_FIELD_TECHNICIAN, ROLE_PROGRAM_ADMIN, authenticate,
                   body, fk_candidate, pagination, qstr, venum, vid, vint, vnum, vstr)
from routes import PREFIX
from store import clock, db, new_record, touch

bp = Blueprint("complaints", __name__)


@bp.post(PREFIX + "/comfort-complaints")
def create_comfort_complaint():
    authenticate((ROLE_PROGRAM_ADMIN, ROLE_FIELD_TECHNICIAN))
    data = body()
    # --- rung 4 ---
    project_id = fk_candidate(data, "project_id")
    if project_id is None:
        vid(data, "project_id")
    project = lookup.project_or_404(project_id)
    # --- rung 5 ---
    room_label = vstr(data, "room_label")
    complaint_type = venum(data, "complaint_type", calc.COMPLAINT_TYPE)
    reported_by = vstr(data, "reported_by")

    row = new_record()
    row.update({
        "project_id": project["id"],
        "room_label": room_label,
        "complaint_type": complaint_type,
        "reported_by": reported_by,
        "status": "OPEN",
        "diagnosis_code": None,
        "tolerance_pct": None,
        "rebalance_count": 0,
        "damper_adjustment_note": None,
        "resolved_at": None,
    })
    db.comfort_complaints[row["id"]] = row
    return object_response(serialize.comfort_complaint(row), 201)


@bp.get(PREFIX + "/comfort-complaints/<complaint_id>")
def read_comfort_complaint(complaint_id):
    authenticate(ALL_ROLES)
    row = lookup.complaint_or_404(complaint_id)
    return object_response(serialize.comfort_complaint(row))


@bp.post(PREFIX + "/comfort-complaints/<complaint_id>/diagnose")
def diagnose_complaint(complaint_id):
    authenticate((ROLE_FIELD_TECHNICIAN,))
    complaint = lookup.complaint_or_404(complaint_id)
    data = body()
    # --- rung 5.  The house default tolerance is 10.00 percent. ---
    diagnosis_code = venum(data, "diagnosis_code", calc.DIAGNOSIS_CODE)
    tolerance = vnum(data, "tolerance_pct", required=False,
                     default=calc.DEFAULT_TOLERANCE_PCT, minimum=0, maximum=50)
    # --- rung 6 ---
    if complaint["status"] != "OPEN":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE", "Diagnosis requires status OPEN.")

    complaint["diagnosis_code"] = diagnosis_code
    complaint["tolerance_pct"] = calc.rhu(tolerance, 2)
    complaint["status"] = "DIAGNOSED"
    touch(complaint)
    return object_response(serialize.comfort_complaint(complaint))


@bp.post(PREFIX + "/comfort-complaints/<complaint_id>/balance")
def balance_complaint(complaint_id):
    authenticate((ROLE_FIELD_TECHNICIAN,))
    complaint = lookup.complaint_or_404(complaint_id)
    data = body()
    note = vstr(data, "damper_adjustment_note")
    # --- rung 6 ---
    if complaint["status"] != "DIAGNOSED":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE",
                       "Entering the balancing phase requires status DIAGNOSED.")
    # --- rung 10 ---
    if not lookup.readings_of_complaint(complaint["id"]):
        raise ApiError("ERR_NO_AIRFLOW_READINGS",
                       "At least one airflow reading is required before balancing.")

    complaint["damper_adjustment_note"] = note
    complaint["status"] = "BALANCING"
    touch(complaint)
    return object_response(serialize.comfort_complaint(complaint))


@bp.post(PREFIX + "/comfort-complaints/<complaint_id>/airflow-readings")
def create_airflow_reading(complaint_id):
    user_id, _role = authenticate((ROLE_FIELD_TECHNICIAN,))
    complaint = lookup.complaint_or_404(complaint_id)
    data = body()
    # --- rung 5 ---
    room_label = vstr(data, "room_label")
    reading_seq = vint(data, "reading_seq", minimum=1)
    measured = vnum(data, "measured_cfm", minimum=0)
    design = vnum(data, "design_cfm", exclusive_minimum=0)
    damper = vnum(data, "damper_position_pct", minimum=0, maximum=100)
    # --- rung 6 ---
    if complaint["status"] == "RESOLVED":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE",
                       "A resolved complaint accepts no further readings.")
    # --- rung 10: reading_seq is unique per (complaint, room_label) ---
    for other in lookup.readings_of_complaint(complaint["id"]):
        if other["room_label"] == room_label and other["reading_seq"] == reading_seq:
            raise ApiError("ERR_DUPLICATE_READING_SEQ",
                           "reading_seq already exists for this room.")

    tolerance = complaint.get("tolerance_pct")
    if tolerance is None:
        tolerance = calc.DEFAULT_TOLERANCE_PCT
    deviation = calc.deviation_pct(measured, design)
    within = abs(deviation) <= calc.dec(tolerance)

    row = new_record(versioned=False)
    row.update({
        "comfort_complaint_id": complaint["id"],
        "room_label": room_label,
        "reading_seq": reading_seq,
        "measured_cfm": measured,
        "design_cfm": design,
        "damper_position_pct": damper,
        "deviation_pct": deviation,
        "within_tolerance": within,
        "measured_by_user_id": user_id,
    })
    db.airflow_readings[row["id"]] = row

    if complaint["status"] == "BALANCING":
        if not within:
            complaint["status"] = "DIAGNOSED"
            complaint["rebalance_count"] = complaint["rebalance_count"] + 1
        else:
            governing = lookup.governing_readings(complaint["id"])
            if governing and all(r["within_tolerance"] for r in governing.values()):
                complaint["status"] = "RESOLVED"
                complaint["resolved_at"] = clock()
    touch(complaint)
    return object_response(serialize.airflow_reading(row), 201)


@bp.get(PREFIX + "/comfort-complaints/<complaint_id>/airflow-readings")
def list_airflow_readings(complaint_id):
    authenticate(ALL_ROLES)
    complaint = lookup.complaint_or_404(complaint_id)
    room_label = qstr("room_label")
    limit, offset = pagination()
    rows = [r for r in lookup.readings_of_complaint(complaint["id"])
            if room_label is None or r["room_label"] == room_label]
    window = rows[offset:offset + limit]
    return array_response([serialize.airflow_reading(r) for r in window],
                          limit, offset, len(rows))
