"""Inspection routes — PRD §3.3, §3.4 (citation creation)."""

import re

from flask import Blueprint

import calc
import config
import domain
import serialize
import store
import validate as V
from auth import authenticate
from envelope import array_response, send, watch
from errors import ApiError
from util import days, minutes

bp = Blueprint("inspections", __name__)

READ_ROLES = ["HealthOfficer", "Inspector", "RecordsClerk", "EstablishmentOperator"]

VIOLATION_CODE_RE = re.compile(r"^[A-Z0-9_]{1,16}$")


@bp.post("/body-art/inspections")
def create_inspection():
    authenticate(["HealthOfficer", "Inspector"])
    data = V.body()
    establishment_id = V.req_id(data, "establishment_id")
    inspection_type = V.req_enum(data, "inspection_type", config.INSPECTION_TYPES)
    start = V.req_datetime(data, "scheduled_start_at")
    end = V.req_datetime(data, "scheduled_end_at")
    if not end > start:
        raise V.bad("scheduled_end_at must be strictly after scheduled_start_at.")
    est = V.get_establishment(establishment_id)

    if domain.inspection_window_conflicts(est["id"], start, end):
        raise ApiError("ERR_INSPECTION_WINDOW_CONFLICT")

    rec = domain.create_inspection(est["id"], inspection_type, start, end)
    return send(lambda: serialize.inspection(rec), 201)


@bp.get("/body-art/inspections/<inspection_id>")
def read_inspection(inspection_id):
    authenticate(READ_ROLES)
    rec = V.get_inspection(inspection_id)
    return send(lambda: serialize.inspection(rec), 200)


@bp.get("/body-art/inspections")
def list_inspections():
    authenticate(READ_ROLES)
    limit, offset = V.pagination()
    establishment_id = V.filter_string("establishment_id")
    source_complaint_id = V.filter_string("source_complaint_id")
    status = V.filter_enum("status", config.INSPECTION_STATUSES)
    inspection_type = V.filter_enum("inspection_type", config.INSPECTION_TYPES)

    rows = store.sorted_rows(store.inspections)
    if establishment_id is not None:
        rows = [r for r in rows if r["establishment_id"] == establishment_id]
    if source_complaint_id is not None:
        rows = [r for r in rows if r["source_complaint_id"] == source_complaint_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if inspection_type is not None:
        rows = [r for r in rows if r["inspection_type"] == inspection_type]
    page, total = V.paginate(rows, limit, offset)
    return array_response(
        [serialize.inspection(r) for r in page], limit, offset, total
    )


@bp.post("/body-art/inspections/<inspection_id>/start")
def start_inspection(inspection_id):
    caller = authenticate(["Inspector"])
    rec = V.get_inspection(inspection_id)
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INSPECTION_STATE_INVALID")
    if store.now() < rec["scheduled_start_at"]:
        raise ApiError("ERR_INSPECTION_STATE_INVALID")

    est = store.establishments.get(rec["establishment_id"])
    watch(rec)
    rec["status"] = "IN_PROGRESS"
    rec["inspector_user_id"] = caller.user_id
    rec["open_violation_count_at_start"] = (
        est["open_violation_count"] if est is not None else 0
    )
    return send(lambda: serialize.inspection(rec), 200)


@bp.post("/body-art/inspections/<inspection_id>/finalize")
def finalize_inspection(inspection_id):
    caller = authenticate(["Inspector"])
    rec = V.get_inspection(inspection_id)
    if rec["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INSPECTION_STATE_INVALID")
    if caller.user_id != rec["inspector_user_id"]:
        raise ApiError("ERR_INSPECTION_STATE_INVALID")

    est = store.establishments.get(rec["establishment_id"])
    cited = domain.rows_for(store.violations, inspection_id=rec["id"])
    score, lines = calc.inspection_score(rec, cited, rec["establishment_id"])
    for violation, multiplier, deduction in lines:
        watch(violation)
        violation["repeat_multiplier_applied"] = multiplier
        violation["deduction_points"] = deduction

    has_critical = any(v["severity"] == "CRITICAL" for v in cited)
    passed = score >= config.INSPECTION_PASS_SCORE and not has_critical

    watch(rec)
    rec["score"] = score
    rec["finalized_at"] = store.now()
    rec["status"] = "PASSED" if passed else "FAILED"

    if not passed and rec["inspection_type"] in ("ROUTINE", "COMPLAINT", "REINSPECTION"):
        start = rec["finalized_at"] + days(config.REINSPECTION_LEAD_DAYS)
        end = start + minutes(config.REINSPECTION_WINDOW_MINUTES)
        domain.create_inspection(rec["establishment_id"], "REINSPECTION", start, end)

    if est is not None:
        domain.recompute_risk_and_posture(est)
    return send(lambda: serialize.inspection(rec), 200)


@bp.post("/body-art/inspections/<inspection_id>/violations")
def cite_violation(inspection_id):
    caller = authenticate(["Inspector"])
    inspection = V.get_inspection(inspection_id)
    data = V.body()
    violation_code = V.req_string(data, "violation_code", 1, 16)
    if not VIOLATION_CODE_RE.match(violation_code):
        raise V.bad(
            "Field 'violation_code' accepts uppercase letters, digits and underscore."
        )
    severity = V.req_enum(data, "severity", config.VIOLATION_SEVERITIES)
    narrative = V.req_string(data, "narrative", 1, 500)

    if inspection["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INSPECTION_STATE_INVALID")
    if caller.user_id != inspection["inspector_user_id"]:
        raise ApiError("ERR_INSPECTION_STATE_INVALID")

    issued_at = store.now()
    rec = domain.new_record(
        {
            "inspection_id": inspection["id"],
            "violation_code": violation_code,
            "severity": severity,
            "narrative": narrative,
            "status": "ISSUED",
            "issued_at": issued_at,
            "abatement_due_at": calc.abatement_due_at(issued_at, severity),
            "repeat_multiplier_applied": 1.0,
            "deduction_points": 0,
            "correction_note": None,
            "correction_submitted_at": None,
        }
    )
    store.violations[rec["id"]] = rec

    est = store.establishments.get(inspection["establishment_id"])
    if est is not None:
        domain.recompute_counters(est)   # hop 1
        domain.recompute_risk(est)       # hop 2
        domain.maybe_auto_suspend(est)   # hops 3-5 (or posture-only)
    return send(lambda: serialize.violation(rec), 201)
