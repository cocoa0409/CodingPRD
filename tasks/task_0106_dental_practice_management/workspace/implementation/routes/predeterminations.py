"""Predetermination endpoints, eligibility gates, and state machine (PRD §3.5)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_ANNUAL_MAX_REACHED,
    ERR_COVERAGE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ITEM_NOT_FOUND,
    ERR_PREDETERMINATION_NOT_FOUND,
    ERR_VALIDATION,
    ERR_WAITING_PERIOD_NOT_MET,
)
from middleware import ROLE_BILLING, ROLE_CLINICIAN, ROLE_FRONT_DESK
from response import ok_array, ok_object
from routes._helpers import apply_filters, guard
from services import calculations, common


bp = Blueprint("predeterminations", __name__)


@bp.post("/predeterminations")
def create_predetermination():
    guard([ROLE_BILLING])
    body = common.get_json_body()
    common.require_fields(body, ["treatment_plan_item_id", "patient_coverage_id"])
    item_id = common.require_string(body, "treatment_plan_item_id")
    item = common.resolve(db.treatment_plan_items, item_id, ERR_ITEM_NOT_FOUND)
    coverage_id = common.require_string(body, "patient_coverage_id")
    coverage = common.resolve(db.patient_coverages, coverage_id, ERR_COVERAGE_NOT_FOUND)

    plan_rec = db.treatment_plans[item["treatment_plan_id"]]
    patient_id = plan_rec["patient_id"]
    plan = db.insurance_plans[coverage["insurance_plan_id"]]

    # Eligibility gates (priority 9, ERR_WAITING_PERIOD_NOT_MET) — both whole months.
    if not calculations.waiting_ok(item["category"], coverage, plan):
        raise APIError(ERR_WAITING_PERIOD_NOT_MET, 409, "MAJOR waiting period not met")
    if not calculations.frequency_ok(patient_id, item["cdt_code"], plan):
        raise APIError(ERR_WAITING_PERIOD_NOT_MET, 409, "Same-CDT frequency gap not met")

    # Annual maximum already reached (priority 11, ERR_ANNUAL_MAX_REACHED, 402).
    if coverage["annual_max_reached"]:
        raise APIError(ERR_ANNUAL_MAX_REACHED, 402, "Coverage annual maximum already reached")

    rec = common.new_common_fields()
    rec.update({
        "treatment_plan_item_id": item_id,
        "patient_coverage_id": coverage_id,
        "submitted_fee_cents": item["fee_cents"],
        "approved_benefit_cents": None,
        "valid_until_date": None,
        "status": "PENDING",
    })
    db.predeterminations[rec["id"]] = rec

    # Set the item's predetermination_id to the new predetermination (PRD §3.5).
    item["predetermination_id"] = rec["id"]
    common.touch(item)

    return ok_object(common.serialize(rec), 201)


@bp.get("/predeterminations")
def list_predeterminations():
    guard([ROLE_BILLING, ROLE_CLINICIAN, ROLE_FRONT_DESK])
    records = apply_filters(list(db.predeterminations.values()), {
        "treatment_plan_item_id": request.args.get("treatment_plan_item_id"),
        "patient_coverage_id": request.args.get("patient_coverage_id"),
        "status": request.args.get("status"),
    })
    items, limit, offset, total = common.paginate(records)
    return ok_array(items, limit, offset, total)


@bp.get("/predeterminations/<pre_id>")
def get_predetermination(pre_id):
    guard([ROLE_BILLING, ROLE_CLINICIAN, ROLE_FRONT_DESK])
    rec = common.resolve(db.predeterminations, pre_id, ERR_PREDETERMINATION_NOT_FOUND)
    return ok_object(common.serialize(rec), 200)


@bp.post("/predeterminations/<pre_id>/approve")
def approve_predetermination(pre_id):
    guard([ROLE_BILLING])
    rec = common.resolve(db.predeterminations, pre_id, ERR_PREDETERMINATION_NOT_FOUND)
    body = common.get_json_body()
    # approve serves PENDING and REQUIRES_REVALIDATION (PRD §3.5).
    if rec["status"] not in ("PENDING", "REQUIRES_REVALIDATION"):
        raise APIError(ERR_INVALID_STATE, 409, "Predetermination not approvable from its state")
    if body.get("approved_benefit_cents") is None or body.get("valid_until_date") is None:
        raise APIError(ERR_VALIDATION, 422, "approved_benefit_cents and valid_until_date required")
    approved = common.require_int(body, "approved_benefit_cents")
    if approved < 0:
        raise APIError(ERR_VALIDATION, 422, "approved_benefit_cents must be >= 0")
    valid_until = common.require_string(body, "valid_until_date")

    rec["approved_benefit_cents"] = approved
    rec["valid_until_date"] = valid_until
    rec["status"] = "APPROVED"
    common.touch(rec)
    return ok_object(common.serialize(rec), 200)


@bp.post("/predeterminations/<pre_id>/deny")
def deny_predetermination(pre_id):
    guard([ROLE_BILLING])
    rec = common.resolve(db.predeterminations, pre_id, ERR_PREDETERMINATION_NOT_FOUND)
    if rec["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Predetermination must be PENDING to deny")
    rec["status"] = "DENIED"
    common.touch(rec)
    return ok_object(common.serialize(rec), 200)
