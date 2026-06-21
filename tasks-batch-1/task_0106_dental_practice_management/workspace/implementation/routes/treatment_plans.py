"""TreatmentPlan + TreatmentPlanItem endpoints and state machine (PRD §3.3, §3.4)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_ITEM_NOT_FOUND,
    ERR_PATIENT_INACTIVE,
    ERR_PATIENT_NOT_FOUND,
    ERR_PLAN_HAS_NO_ITEMS,
    ERR_PLAN_ITEMS_NOT_COMPLETE,
    ERR_PROVIDER_NOT_FOUND,
    ERR_TREATMENT_PLAN_NOT_FOUND,
    ERR_VALIDATION,
)
from middleware import (
    ROLE_BILLING,
    ROLE_CLINICIAN,
    ROLE_FRONT_DESK,
    ROLE_PATIENT,
    current_role,
    current_user_id,
)
from response import ok_array, ok_object
from routes._helpers import apply_filters, enforce_patient_ownership, guard
from services import calculations, common

bp = Blueprint("treatment_plans", __name__)


def _recompute_plan_totals(plan):
    items = [
        it for it in db.treatment_plan_items.values()
        if it["treatment_plan_id"] == plan["id"] and it["status"] != "CANCELLED"
    ]
    plan["total_fee_cents"] = sum(it["fee_cents"] for it in items)
    plan["estimated_patient_portion_cents"] = sum(
        it["estimated_patient_portion_cents"] for it in items
    )
    common.touch(plan)


# ---------------------------------------------------------------------------
# Treatment Plans
# ---------------------------------------------------------------------------
@bp.post("/treatment-plans")
def create_plan():
    guard([ROLE_CLINICIAN])
    body = common.get_json_body()
    common.require_fields(body, ["patient_id", "provider_id"])
    patient_id = common.require_string(body, "patient_id")
    common.resolve(db.patients, patient_id, ERR_PATIENT_NOT_FOUND)
    provider_id = common.require_string(body, "provider_id")
    common.resolve(db.providers, provider_id, ERR_PROVIDER_NOT_FOUND)

    rec = common.new_common_fields()
    rec.update({
        "patient_id": patient_id,
        "provider_id": provider_id,
        "total_fee_cents": 0,
        "estimated_patient_portion_cents": 0,
        "status": "DRAFT",
    })
    db.treatment_plans[rec["id"]] = rec
    return ok_object(common.serialize(rec), 201)


@bp.get("/treatment-plans")
def list_plans():
    guard([ROLE_CLINICIAN, ROLE_FRONT_DESK, ROLE_BILLING])
    records = apply_filters(list(db.treatment_plans.values()), {
        "patient_id": request.args.get("patient_id"),
        "provider_id": request.args.get("provider_id"),
        "status": request.args.get("status"),
    })
    items, limit, offset, total = common.paginate(records)
    return ok_array(items, limit, offset, total)


@bp.get("/treatment-plans/<plan_id>")
def get_plan(plan_id):
    guard([ROLE_CLINICIAN, ROLE_FRONT_DESK, ROLE_BILLING, ROLE_PATIENT])
    rec = common.resolve(db.treatment_plans, plan_id, ERR_TREATMENT_PLAN_NOT_FOUND)
    enforce_patient_ownership(rec["patient_id"])
    return ok_object(common.serialize(rec), 200)


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------
@bp.post("/treatment-plans/<plan_id>/items")
def add_item(plan_id):
    guard([ROLE_CLINICIAN])
    plan = common.resolve(db.treatment_plans, plan_id, ERR_TREATMENT_PLAN_NOT_FOUND)
    body = common.get_json_body()
    common.require_fields(body, ["cdt_code", "category", "fee_cents"])
    cdt_code = common.require_string(body, "cdt_code")
    category = common.require_enum(body, "category", {"PREVENTIVE", "BASIC", "MAJOR"})
    fee_cents = common.require_int(body, "fee_cents")
    if fee_cents <= 0:
        raise APIError(ERR_VALIDATION, 422, "fee_cents must be > 0")
    phase_number = common.optional_int(body, "phase_number", 1)
    if phase_number < 1:
        raise APIError(ERR_VALIDATION, 422, "phase_number must be >= 1")
    tooth_number = None
    if body.get("tooth_number") is not None:
        tooth_number = common.require_int(body, "tooth_number")
        if not (1 <= tooth_number <= 32):
            raise APIError(ERR_VALIDATION, 422, "tooth_number must be in 1..32")
    requires_predetermination = common.optional_bool(body, "requires_predetermination", False)

    # Adding items is a DRAFT-time activity (PRD §3.3). State precedes the add.
    if plan["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Items can only be added while plan is DRAFT")

    rec = common.new_common_fields()
    rec.update({
        "treatment_plan_id": plan["id"],
        "predetermination_id": None,
        "appointment_id": None,
        "cdt_code": cdt_code,
        "category": category,
        "phase_number": phase_number,
        "tooth_number": tooth_number,
        "fee_cents": fee_cents,
        "requires_predetermination": requires_predetermination,
        "estimated_insurance_cents": 0,
        "estimated_patient_portion_cents": 0,
        "status": "PLANNED",
    })
    db.treatment_plan_items[rec["id"]] = rec
    _recompute_plan_totals(plan)
    return ok_object(common.serialize(rec), 201)


@bp.get("/treatment-plan-items")
def list_items():
    guard([ROLE_CLINICIAN, ROLE_FRONT_DESK, ROLE_BILLING, ROLE_PATIENT])
    records = apply_filters(list(db.treatment_plan_items.values()), {
        "treatment_plan_id": request.args.get("treatment_plan_id"),
        "predetermination_id": request.args.get("predetermination_id"),
        "appointment_id": request.args.get("appointment_id"),
        "status": request.args.get("status"),
    })
    if current_role() == ROLE_PATIENT:
        records = [
            it for it in records
            if db.treatment_plans[it["treatment_plan_id"]]["patient_id"] == current_user_id()
        ]
    items, limit, offset, total = common.paginate(records)
    return ok_array(items, limit, offset, total)


@bp.get("/treatment-plan-items/<item_id>")
def get_item(item_id):
    guard([ROLE_CLINICIAN, ROLE_FRONT_DESK, ROLE_BILLING, ROLE_PATIENT])
    rec = common.resolve(db.treatment_plan_items, item_id, ERR_ITEM_NOT_FOUND)
    plan = db.treatment_plans[rec["treatment_plan_id"]]
    enforce_patient_ownership(plan["patient_id"])
    return ok_object(common.serialize(rec), 200)


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------
@bp.post("/treatment-plans/<plan_id>/propose")
def propose_plan(plan_id):
    guard([ROLE_CLINICIAN])
    plan = common.resolve(db.treatment_plans, plan_id, ERR_TREATMENT_PLAN_NOT_FOUND)
    if plan["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Plan must be DRAFT to propose")
    planned_items = [
        it for it in db.treatment_plan_items.values()
        if it["treatment_plan_id"] == plan["id"] and it["status"] == "PLANNED"
    ]
    if not planned_items:
        raise APIError(ERR_PLAN_HAS_NO_ITEMS, 409, "Plan has no PLANNED items")

    # Recompute estimates on every PLANNED item (forward-looking estimate, PRD §3.8).
    for it in planned_items:
        est_ins = calculations.estimated_insurance_benefit(it)
        it["estimated_insurance_cents"] = est_ins
        it["estimated_patient_portion_cents"] = it["fee_cents"] - est_ins
        common.touch(it)

    plan["status"] = "PROPOSED"
    _recompute_plan_totals(plan)
    return ok_object(common.serialize(plan), 200)


@bp.post("/treatment-plans/<plan_id>/revise")
def revise_plan(plan_id):
    guard([ROLE_CLINICIAN])
    plan = common.resolve(db.treatment_plans, plan_id, ERR_TREATMENT_PLAN_NOT_FOUND)
    if plan["status"] != "PROPOSED":
        raise APIError(ERR_INVALID_STATE, 409, "Plan must be PROPOSED to revise")
    plan["status"] = "DRAFT"
    common.touch(plan)
    return ok_object(common.serialize(plan), 200)


@bp.post("/treatment-plans/<plan_id>/accept")
def accept_plan(plan_id):
    guard([ROLE_FRONT_DESK])
    plan = common.resolve(db.treatment_plans, plan_id, ERR_TREATMENT_PLAN_NOT_FOUND)
    if plan["status"] != "PROPOSED":
        raise APIError(ERR_INVALID_STATE, 409, "Plan must be PROPOSED to accept")
    patient = db.patients[plan["patient_id"]]
    if patient["status"] != "ACTIVE":
        raise APIError(ERR_PATIENT_INACTIVE, 409, "Patient is INACTIVE")
    plan["status"] = "ACCEPTED"
    common.touch(plan)
    return ok_object(common.serialize(plan), 200)


@bp.post("/treatment-plans/<plan_id>/complete")
def complete_plan(plan_id):
    guard([ROLE_CLINICIAN])
    plan = common.resolve(db.treatment_plans, plan_id, ERR_TREATMENT_PLAN_NOT_FOUND)
    if plan["status"] != "ACCEPTED":
        raise APIError(ERR_INVALID_STATE, 409, "Plan must be ACCEPTED to complete")
    non_cancelled = [
        it for it in db.treatment_plan_items.values()
        if it["treatment_plan_id"] == plan["id"] and it["status"] != "CANCELLED"
    ]
    if any(it["status"] != "COMPLETED" for it in non_cancelled):
        raise APIError(ERR_PLAN_ITEMS_NOT_COMPLETE, 409, "Every non-CANCELLED item must be COMPLETED")
    plan["status"] = "COMPLETED"
    common.touch(plan)
    return ok_object(common.serialize(plan), 200)


@bp.post("/treatment-plans/<plan_id>/cancel")
def cancel_plan(plan_id):
    guard([ROLE_FRONT_DESK])
    plan = common.resolve(db.treatment_plans, plan_id, ERR_TREATMENT_PLAN_NOT_FOUND)
    if plan["status"] not in ("DRAFT", "PROPOSED", "ACCEPTED"):
        raise APIError(ERR_INVALID_STATE, 409, "Plan must be DRAFT/PROPOSED/ACCEPTED to cancel")

    plan["status"] = "CANCELLED"
    # Cascade depth-1: every non-terminal (PLANNED|SCHEDULED) item -> CANCELLED.
    for it in db.treatment_plan_items.values():
        if it["treatment_plan_id"] != plan["id"]:
            continue
        if it["status"] in ("PLANNED", "SCHEDULED"):
            appt_id = it.get("appointment_id")
            was_scheduled = it["status"] == "SCHEDULED"
            it["status"] = "CANCELLED"
            common.touch(it)
            # Cascade depth-2: linked SCHEDULED appointment -> CANCELLED.
            if was_scheduled and appt_id:
                appt = db.appointments.get(appt_id)
                if appt is not None and appt["status"] == "SCHEDULED":
                    appt["status"] = "CANCELLED"
                    common.touch(appt)
    _recompute_plan_totals(plan)
    return ok_object(common.serialize(plan), 200)
