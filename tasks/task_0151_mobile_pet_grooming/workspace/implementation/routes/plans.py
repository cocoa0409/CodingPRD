"""RecurringPlan routes and plan-driven appointment generation."""
from flask import Blueprint, request

import db
import models
import validate as V
from middleware import get_identity, require_role
from errors import err, ERR_INVALID_STATE, ERR_ACCOUNT_SUSPENDED, ERR_INVALID_REQUEST
import lookup
from response import object_response, array_response
from services import reconcile

bp = Blueprint("plans", __name__)

CADENCE_VALUES = {28, 42, 56}


@bp.route("/recurring-plans", methods=["POST"])
def create_plan():
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer"})
    body = V.require_body(request.get_json(silent=True))
    pet_id = V.require_str(body, "pet_id")
    service_tier_id = V.require_str(body, "service_tier_id")
    cadence_days = V.require_int(body, "cadence_days")
    if cadence_days not in CADENCE_VALUES:
        raise err(ERR_INVALID_REQUEST, "cadence_days must be one of 28, 42, 56")
    discount_pct = V.require_number(body, "discount_pct", minimum=0, maximum=0.20)
    pet = lookup.get_pet(pet_id)
    lookup.get_service_tier(service_tier_id)
    if role == "Customer":
        lookup.forbid_unless(uid == pet["customer_id"])
    rec = models.base_versioned()
    rec.update({
        "pet_id": pet_id, "service_tier_id": service_tier_id,
        "cadence_days": cadence_days, "discount_pct": discount_pct,
        "status": "ACTIVE",
    })
    db.recurring_plans[rec["id"]] = rec
    return object_response(models.ser_recurring_plan(rec), 201)


@bp.route("/recurring-plans/<rid>", methods=["GET"])
def get_plan(rid):
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer"})
    rec = lookup.get_recurring_plan(rid)
    if role == "Customer":
        lookup.forbid_unless(uid == lookup.customer_of_plan(rec))
    return object_response(models.ser_recurring_plan(rec), 200)


@bp.route("/recurring-plans", methods=["GET"])
def list_plans():
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer"})
    limit, offset = V.parse_pagination(request.args)
    items = list(db.recurring_plans.values())
    pet_id = request.args.get("pet_id")
    service_tier_id = request.args.get("service_tier_id")
    if pet_id:
        items = [p for p in items if p["pet_id"] == pet_id]
    if service_tier_id:
        items = [p for p in items if p["service_tier_id"] == service_tier_id]
    if role == "Customer":
        items = [p for p in items if lookup.customer_of_plan(p) == uid]
    page, total = V.paginate(items, limit, offset)
    return array_response([models.ser_recurring_plan(p) for p in page], limit, offset, total, 200)


def _owner_check(rec, uid):
    lookup.forbid_unless(uid == lookup.customer_of_plan(rec))


@bp.route("/recurring-plans/<rid>/pause", methods=["POST"])
def pause_plan(rid):
    uid, role = get_identity()
    require_role(role, {"Customer"})
    rec = lookup.get_recurring_plan(rid)
    _owner_check(rec, uid)
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Plan is not ACTIVE")
    rec["status"] = "PAUSED"
    models.touch(rec)
    return object_response(models.ser_recurring_plan(rec), 200)


@bp.route("/recurring-plans/<rid>/resume", methods=["POST"])
def resume_plan(rid):
    uid, role = get_identity()
    require_role(role, {"Customer"})
    rec = lookup.get_recurring_plan(rid)
    _owner_check(rec, uid)
    if rec["status"] != "PAUSED":
        raise err(ERR_INVALID_STATE, "Plan is not PAUSED")
    rec["status"] = "ACTIVE"
    models.touch(rec)
    return object_response(models.ser_recurring_plan(rec), 200)


@bp.route("/recurring-plans/<rid>/cancel", methods=["POST"])
def cancel_plan(rid):
    uid, role = get_identity()
    require_role(role, {"Customer"})
    rec = lookup.get_recurring_plan(rid)
    _owner_check(rec, uid)
    if rec["status"] not in ("ACTIVE", "PAUSED"):
        raise err(ERR_INVALID_STATE, "Plan cannot be cancelled from %s" % rec["status"])
    rec["status"] = "CANCELLED"
    models.touch(rec)
    return object_response(models.ser_recurring_plan(rec), 200)


@bp.route("/recurring-plans/<rid>/generate-appointment", methods=["POST"])
def generate_appointment(rid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    rec = lookup.get_recurring_plan(rid)
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Plan is not ACTIVE")
    pet = db.pets[rec["pet_id"]]
    customer = db.customers[pet["customer_id"]]
    reconcile.recompute_customer_strikes(customer)
    if customer["account_status"] != "ACTIVE":
        raise err(ERR_ACCOUNT_SUSPENDED, "Customer account is suspended")
    appt = models.base_versioned()
    appt.update({
        "pet_id": rec["pet_id"], "service_tier_id": rec["service_tier_id"],
        "route_stop_id": None, "groomer_id": None,
        "recurring_plan_id": rec["id"],
        "estimated_minutes": 0, "quoted_price_cents": 0, "final_price_cents": 0,
        "quote_round": 0, "status": "REQUESTED",
    })
    db.appointments[appt["id"]] = appt
    models.touch(rec)
    return object_response(models.ser_appointment(appt), 201)
