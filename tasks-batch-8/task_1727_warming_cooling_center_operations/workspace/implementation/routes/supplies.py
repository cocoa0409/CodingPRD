"""Donations and meal services."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INSUFFICIENT_MEAL_STOCK,
)
from flask import Blueprint, request
from response import respond, respond_list
from services import (
    meal_planned, meal_stock, ser_donation, ser_meal_service,
)
from util import body, paginate, req_dt, req_enum, req_int, req_str, touch

bp = Blueprint("supplies", __name__)

CATEGORIES = ("MEAL", "WATER", "BEDDING", "HYGIENE", "PET_SUPPLIES")
MEAL_PERIODS = ("BREAKFAST", "LUNCH", "DINNER")


def get_activation(act_id):
    act = db.store["activations"].get(act_id)
    if act is None:
        raise_err(ERR_NOT_FOUND, f"SiteActivation {act_id} not found")
    return act


def get_donation(donation_id):
    d = db.store["donations"].get(donation_id)
    if d is None:
        raise_err(ERR_NOT_FOUND, f"Donation {donation_id} not found")
    return d


def get_meal_service(meal_service_id):
    m = db.store["meal_services"].get(meal_service_id)
    if m is None:
        raise_err(ERR_NOT_FOUND, f"MealService {meal_service_id} not found")
    return m


# --------------------------------------------------------------- donations
@bp.route("/site-activations/<act_id>/donations", methods=["POST"])
@require_roles("SiteLead")
def create_donation(act_id):
    act = get_activation(act_id)
    b = body()
    partner_name = req_str(b, "partner_name")
    category = req_enum(b, "category", CATEGORIES)
    quantity = req_int(b, "quantity", min_value=1)
    now = clock.now()
    d = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "site_activation_id": act["id"],
        "partner_name": partner_name,
        "category": category,
        "quantity": quantity,
        "status": "PLEDGED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["donations"][d["id"]] = d
    return respond(ser_donation(d), 201)


@bp.route("/site-activations/<act_id>/donations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_donations(act_id):
    get_activation(act_id)
    items = [d for d in db.store["donations"].values()
             if d["site_activation_id"] == act_id]
    status = request.args.get("status")
    category = request.args.get("category")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if category is not None:
        items = [d for d in items if d["category"] == category]
    items.sort(key=lambda d: (d["created_at"], d["_seq"]))
    page, pagination = paginate([ser_donation(d) for d in items])
    return respond_list(page, pagination)


@bp.route("/donations/<donation_id>/receive", methods=["POST"])
@require_roles("SiteLead")
def receive_donation(donation_id):
    d = get_donation(donation_id)
    if d["status"] != "PLEDGED":
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot receive a donation in status {d['status']}",
        )
    d["status"] = "RECEIVED"
    touch(d)
    return respond(ser_donation(d), 200)


# ------------------------------------------------------------ meal services
@bp.route("/site-activations/<act_id>/meal-services", methods=["POST"])
@require_roles("SiteLead")
def create_meal_service(act_id):
    act = get_activation(act_id)
    b = body()
    service_date = req_dt(b, "service_date")
    meal_period = req_enum(b, "meal_period", MEAL_PERIODS)
    planned = meal_planned(act, meal_period)
    now = clock.now()
    m = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "site_activation_id": act["id"],
        "service_date": service_date,
        "meal_period": meal_period,
        "planned_meals": planned,
        "served_count": None,
        "status": "PLANNED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["meal_services"][m["id"]] = m
    return respond(ser_meal_service(m), 201)


@bp.route("/site-activations/<act_id>/meal-services", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_meal_services(act_id):
    get_activation(act_id)
    items = [m for m in db.store["meal_services"].values()
             if m["site_activation_id"] == act_id]
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    items.sort(key=lambda m: (m["created_at"], m["_seq"]))
    page, pagination = paginate([ser_meal_service(m) for m in items])
    return respond_list(page, pagination)


@bp.route("/meal-services/<meal_service_id>/serve", methods=["POST"])
@require_roles("SiteLead")
def serve_meal(meal_service_id):
    m = get_meal_service(meal_service_id)
    if m["status"] != "PLANNED":
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot serve a meal service in status {m['status']}",
        )
    b = body()
    served_count = req_int(b, "served_count", min_value=0)
    act = db.store["activations"].get(m["site_activation_id"])
    on_hand, _ = meal_stock(act)
    if served_count > on_hand:
        raise_err(
            ERR_INSUFFICIENT_MEAL_STOCK,
            f"served_count {served_count} exceeds meal stock on hand "
            f"{on_hand}",
        )
    m["status"] = "SERVED"
    m["served_count"] = served_count
    touch(m)
    return respond(ser_meal_service(m), 200)
