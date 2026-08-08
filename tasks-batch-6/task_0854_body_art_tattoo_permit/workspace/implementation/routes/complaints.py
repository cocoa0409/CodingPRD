"""Complaint routes — PRD §3.7."""

from flask import Blueprint

import config
import domain
import serialize
import store
import validate as V
from auth import authenticate
from envelope import array_response, force, send, watch
from errors import ApiError
from util import days, hours, minutes

bp = Blueprint("complaints", __name__)

READ_ROLES = ["HealthOfficer", "Inspector", "RecordsClerk", "EstablishmentOperator"]


@bp.post("/body-art/complaints")
def create_complaint():
    authenticate(["PublicUser"])
    data = V.body()
    establishment_id = V.req_id(data, "establishment_id")
    complainant_contact = V.req_string(data, "complainant_contact", 1, 120)
    category = V.req_enum(data, "category", config.COMPLAINT_CATEGORIES)
    narrative = V.req_string(data, "narrative", 1, 500)
    est = V.get_establishment(establishment_id)

    received_at = store.now()
    rec = domain.new_record(
        {
            "establishment_id": est["id"],
            "complainant_contact": complainant_contact,
            "category": category,
            "narrative": narrative,
            "status": "RECEIVED",
            "received_at": received_at,
            "triage_due_at": received_at
            + days(config.COMPLAINT_TRIAGE_DEADLINE_DAYS),
            "triage_overdue": False,
            "reopen_count": 0,
        }
    )
    store.complaints[rec["id"]] = rec
    return send(lambda: serialize.complaint(rec), 201)


@bp.get("/body-art/complaints/<complaint_id>")
def read_complaint(complaint_id):
    authenticate(READ_ROLES)
    rec = V.get_complaint(complaint_id)
    return send(lambda: serialize.complaint(rec), 200)


@bp.get("/body-art/complaints")
def list_complaints():
    authenticate(READ_ROLES)
    limit, offset = V.pagination()
    establishment_id = V.filter_string("establishment_id")
    status = V.filter_enum("status", config.COMPLAINT_STATUSES)

    rows = store.sorted_rows(store.complaints)
    if establishment_id is not None:
        rows = [r for r in rows if r["establishment_id"] == establishment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return array_response([serialize.complaint(r) for r in page], limit, offset, total)


@bp.post("/body-art/complaints/<complaint_id>/transition")
def transition_complaint(complaint_id):
    authenticate(["HealthOfficer"])
    rec = V.get_complaint(complaint_id)
    data = V.body()
    action = V.req_enum(data, "action", config.COMPLAINT_ACTIONS)

    expected_from = {
        "TRIAGE": "RECEIVED",
        "INVESTIGATE": "TRIAGED",
        "SUBSTANTIATE": "INVESTIGATING",
        "UNSUBSTANTIATE": "INVESTIGATING",
        "REOPEN": "UNSUBSTANTIATED",
    }[action]
    if rec["status"] != expected_from:
        raise ApiError("ERR_COMPLAINT_STATE_INVALID")

    est = store.establishments.get(rec["establishment_id"])
    now = store.now()

    if action == "TRIAGE":
        start = now + hours(config.COMPLAINT_INSPECTION_LEAD_HOURS)
        end = start + minutes(config.COMPLAINT_INSPECTION_WINDOW_MINUTES)
        if domain.inspection_window_conflicts(rec["establishment_id"], start, end):
            raise ApiError("ERR_INSPECTION_WINDOW_CONFLICT")
        watch(rec)
        rec["status"] = "TRIAGED"
        rec["triage_overdue"] = now >= rec["triage_due_at"]
        domain.create_inspection(
            rec["establishment_id"],
            "COMPLAINT",
            start,
            end,
            source_complaint_id=rec["id"],
        )
    elif action == "INVESTIGATE":
        watch(rec)
        rec["status"] = "INVESTIGATING"
    elif action == "SUBSTANTIATE":
        watch(rec)
        rec["status"] = "SUBSTANTIATED"
        if est is not None:
            force(est)
            domain.recompute_risk_and_posture(est)
    elif action == "UNSUBSTANTIATE":
        watch(rec)
        rec["status"] = "UNSUBSTANTIATED"
        if est is not None:
            domain.recompute_risk_and_posture(est)
    else:  # REOPEN
        if rec["reopen_count"] >= config.COMPLAINT_MAX_REOPENS:
            raise ApiError("ERR_COMPLAINT_REOPEN_LIMIT")
        watch(rec)
        rec["status"] = "INVESTIGATING"
        rec["reopen_count"] += 1
        if est is not None:
            domain.recompute_risk_and_posture(est)

    return send(lambda: serialize.complaint(rec), 200)
