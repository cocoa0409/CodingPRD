"""InfusionOrder routes (PRD §3.2/§3.3/§3.7/§3.11/§3.12)."""
from flask import Blueprint, request

import errors
import helpers
from db import db, stamp_create, touch
from middleware import require
from response import object_response, array_response
from services import workflow

bp = Blueprint("infusion_orders", __name__)

ROUTES = {"IV", "SUBQ", "INTRATHECAL"}
READ_ROLES = ["Pharmacist", "MedicalDirector", "Biller", "AuthSpecialist", "VisitingNurse"]
LIST_ROLES = ["Pharmacist", "MedicalDirector", "Biller", "AuthSpecialist"]


@bp.route("/infusion-orders", methods=["POST"])
def create_order():
    require(["Pharmacist"])
    body = helpers.get_body()
    # (3) existence of referenced FK ids runs before (4) other body validity (PRD §2.8)
    referral_id = helpers.as_str(body, "referral_id")
    drug_id = helpers.as_str(body, "drug_id")
    if referral_id not in db.referrals:
        raise errors.not_found("Referral not found")
    if drug_id not in db.drug_catalog:
        raise errors.not_found("Drug not found")

    route = helpers.as_enum(body, "route", ROUTES)
    daily_dose_mg = helpers.as_int(body, "daily_dose_mg")
    frequency_per_day = helpers.as_int(body, "frequency_per_day")
    start_date = helpers.as_datetime(body, "start_date")
    scheduled_days = helpers.as_int(body, "scheduled_days")

    if daily_dose_mg <= 0:
        raise errors.invalid_request("daily_dose_mg must be > 0")
    if frequency_per_day < 1:
        raise errors.invalid_request("frequency_per_day must be >= 1")
    if scheduled_days < 1:
        raise errors.invalid_request("scheduled_days must be >= 1")

    referral = db.referrals[referral_id]
    # (5) state legality (PRD §3.2): an order may only be built against an
    # ACCEPTED referral. A referral in any other state (e.g. RECEIVED, REJECTED)
    # is not a state from which order creation is defined -> ERR_INVALID_STATE.
    if referral["status"] != "ACCEPTED":
        raise errors.invalid_state("Referral is not in ACCEPTED state")

    order = stamp_create({
        "referral_id": referral_id,
        "patient_id": referral["patient_id"],
        "drug_id": drug_id,
        "route": route,
        "daily_dose_mg": daily_dose_mg,
        "frequency_per_day": frequency_per_day,
        "start_date": body["start_date"],
        "scheduled_days": scheduled_days,
        "administered_days": 0,
        "status": "DRAFT",
        "hold_reason": None,
    })
    db.infusion_orders[order["id"]] = order
    return object_response(order, 201)


@bp.route("/infusion-orders/<id>", methods=["GET"])
def get_order(id):
    require(READ_ROLES)
    order = db.infusion_orders.get(id)
    if order is None:
        raise errors.not_found("Infusion order not found")
    return object_response(order, 200)


@bp.route("/infusion-orders", methods=["GET"])
def list_orders():
    require(LIST_ROLES)
    limit, offset = helpers.pagination_params()
    items = list(db.infusion_orders.values())
    referral_id = request.args.get("referral_id")
    patient_id = request.args.get("patient_id")
    drug_id = request.args.get("drug_id")
    if referral_id is not None:
        items = [o for o in items if o["referral_id"] == referral_id]
    if patient_id is not None:
        items = [o for o in items if o["patient_id"] == patient_id]
    if drug_id is not None:
        items = [o for o in items if o["drug_id"] == drug_id]
    items = helpers.sort_by_created(items)
    window, total, has_more = helpers.paginate(items, limit, offset)
    return array_response(window, limit, offset, total, has_more, 200)


@bp.route("/infusion-orders/<id>/submit", methods=["POST"])
def submit_order(id):
    require(["Pharmacist"])
    order = db.infusion_orders.get(id)
    if order is None:
        raise errors.not_found("Infusion order not found")
    if order["status"] != "DRAFT":
        raise errors.invalid_state("Order is not in DRAFT state")
    drug = db.drug_catalog.get(order["drug_id"])
    # specialty -> PENDING_AUTH; non-specialty -> RELEASED directly
    if drug["is_specialty"]:
        order["status"] = "PENDING_AUTH"
    else:
        order["status"] = "RELEASED"
    touch(order)
    return object_response(order, 200)


@bp.route("/infusion-orders/<id>/discontinue", methods=["POST"])
def discontinue_order(id):
    require(["MedicalDirector"])
    order = db.infusion_orders.get(id)
    if order is None:
        raise errors.not_found("Infusion order not found")
    if order["status"] != "ACTIVE":
        raise errors.invalid_state("Order is not in ACTIVE state")
    workflow.discontinue_cascade(order)
    return object_response(order, 200)


@bp.route("/infusion-orders/<id>/complete", methods=["POST"])
def complete_order(id):
    require(["Pharmacist"])
    order = db.infusion_orders.get(id)
    if order is None:
        raise errors.not_found("Infusion order not found")
    if order["status"] != "ACTIVE":
        raise errors.invalid_state("Order is not in ACTIVE state")
    if order["administered_days"] < order["scheduled_days"]:
        raise errors.ApiError(errors.ERR_THERAPY_INCOMPLETE, 409,
                              "administered_days < scheduled_days")
    order["status"] = "COMPLETED"
    touch(order)
    return object_response(order, 200)
