"""RecareRecall endpoints (PRD §3.7, §3.9)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_PATIENT_NOT_FOUND,
    ERR_RECALL_NOT_FOUND,
    ERR_VALIDATION,
)
from middleware import ROLE_BILLING, ROLE_CLINICIAN, ROLE_FRONT_DESK, ROLE_PATIENT
from response import ok_array, ok_object
from routes._helpers import apply_filters, enforce_patient_ownership, guard
from services import calculations, common

bp = Blueprint("recare", __name__)


@bp.post("/recare-recalls")
def create_recall():
    guard([ROLE_FRONT_DESK])
    body = common.get_json_body()
    common.require_fields(body, ["patient_id", "recall_type", "interval_months", "last_visit_date"])
    patient_id = common.require_string(body, "patient_id")
    common.resolve(db.patients, patient_id, ERR_PATIENT_NOT_FOUND)
    recall_type = common.require_enum(body, "recall_type", {"PROPHY", "PERIO_MAINT", "EXAM"})
    interval_months = common.require_int(body, "interval_months")
    if interval_months <= 0:
        raise APIError(ERR_VALIDATION, 422, "interval_months must be > 0")
    last_visit_date = common.require_string(body, "last_visit_date")

    rec = common.new_common_fields()
    rec.update({
        "patient_id": patient_id,
        "recall_type": recall_type,
        "interval_months": interval_months,
        "last_visit_date": last_visit_date,
        "next_due_date": calculations.recare_next_due(last_visit_date, interval_months),
        "status": "ACTIVE",
    })
    db.recare_recalls[rec["id"]] = rec
    return ok_object(common.serialize(rec), 201)


@bp.get("/recare-recalls")
def list_recalls():
    guard([ROLE_FRONT_DESK, ROLE_CLINICIAN, ROLE_BILLING])
    records = apply_filters(list(db.recare_recalls.values()), {
        "patient_id": request.args.get("patient_id"),
        "status": request.args.get("status"),
    })
    items, limit, offset, total = common.paginate(records)
    return ok_array(items, limit, offset, total)


@bp.get("/recare-recalls/<recall_id>")
def get_recall(recall_id):
    guard([ROLE_FRONT_DESK, ROLE_CLINICIAN, ROLE_BILLING, ROLE_PATIENT])
    rec = common.resolve(db.recare_recalls, recall_id, ERR_RECALL_NOT_FOUND)
    enforce_patient_ownership(rec["patient_id"])
    return ok_object(common.serialize(rec), 200)


@bp.post("/recare-recalls/<recall_id>/fulfill")
def fulfill_recall(recall_id):
    guard([ROLE_FRONT_DESK])
    rec = common.resolve(db.recare_recalls, recall_id, ERR_RECALL_NOT_FOUND)
    body = common.get_json_body()
    common.require_fields(body, ["visit_date"])
    visit_date = common.require_string(body, "visit_date")
    rec["last_visit_date"] = visit_date
    rec["next_due_date"] = calculations.recare_next_due(visit_date, rec["interval_months"])
    rec["status"] = "ACTIVE"
    common.touch(rec)
    return ok_object(common.serialize(rec), 200)
