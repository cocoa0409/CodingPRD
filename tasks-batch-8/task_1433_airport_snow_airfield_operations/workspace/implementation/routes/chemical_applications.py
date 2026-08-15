"""Chemical application routes."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import db
from errors import (ApiError, ERR_APPLICATION_NOT_FOUND, ERR_BUDGET_EXCEEDED,
                    ERR_ENV_LIMIT_EXCEEDED, ERR_EVENT_NOT_ACTIVE,
                    ERR_EVENT_NOT_FOUND, ERR_INVALID_APPLICATION_STATE,
                    ERR_PRODUCT_CONSTRAINED, ERR_PRODUCT_NOT_FOUND,
                    ERR_SEGREGATION_OF_DUTIES, ERR_SURFACE_NOT_FOUND,
                    not_found, validation)
from middleware import require_roles
from response import success_list, success_object
from services.core import (get_pagination, is_number, new_id, now_iso_ms,
                           paginate, round_cents, to_decimal)
from services.domain import (compute_event_remaining_lbs,
                             compute_raw_quantity_lbs,
                             flip_product_constrained_if_threshold,
                             recompute_event_chemical_used,
                             recompute_event_costs,
                             recompute_product_counters,
                             serialize_chemical_application)

bp = Blueprint("chemical_applications", __name__)


def _get_app_or_404(app_id: str) -> dict:
    a = db.chemical_applications.get(app_id)
    if not a:
        raise not_found(ERR_APPLICATION_NOT_FOUND, "ChemicalApplication not found")
    return a


@bp.route("/chemical-applications", methods=["POST"])
def create_application():
    user_id, role = require_roles("MaintenanceLead")
    body = request.get_json(silent=True) or {}
    for f in ("event_id", "surface_id", "product_id", "pavement_temp_f"):
        if f not in body:
            raise validation(f"Missing required field: {f}")
    if not is_number(body["pavement_temp_f"]):
        raise validation("pavement_temp_f must be a number")
    temp = to_decimal(body["pavement_temp_f"], "pavement_temp_f")

    ev = db.snow_events.get(body["event_id"])
    if not ev:
        raise not_found(ERR_EVENT_NOT_FOUND, "SnowEvent not found")
    surface = db.airfield_surfaces.get(body["surface_id"])
    if not surface:
        raise not_found(ERR_SURFACE_NOT_FOUND, "AirfieldSurface not found")
    product = db.chemical_products.get(body["product_id"])
    if not product:
        raise not_found(ERR_PRODUCT_NOT_FOUND, "ChemicalProduct not found")

    raw = compute_raw_quantity_lbs(surface, product, temp)
    now = now_iso_ms()
    a = {
        "id": new_id(),
        "event_id": body["event_id"],
        "surface_id": body["surface_id"],
        "product_id": body["product_id"],
        "pavement_temp_f": temp,
        "raw_quantity_lbs": raw,
        "authorized_quantity_lbs": None,
        "capped": False,
        "authorized_by": None,
        "line_cost_cents": 0,
        "status": "PROPOSED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.chemical_applications[a["id"]] = a
    return success_object(serialize_chemical_application(a), 201)


@bp.route("/chemical-applications/<app_id>/application-actions", methods=["POST"])
def application_actions(app_id):
    user_id, role = require_roles("MaintenanceLead")
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if not isinstance(action, str) or not action:
        raise validation("action is required")
    if action not in ("AUTHORIZE", "DISPENSE", "VOID"):
        raise validation("Unknown action")

    a = _get_app_or_404(app_id)

    # state
    if action == "AUTHORIZE":
        if a["status"] != "PROPOSED":
            raise ApiError(ERR_INVALID_APPLICATION_STATE, 409,
                           "AUTHORIZE requires PROPOSED")
    elif action == "DISPENSE":
        if a["status"] != "AUTHORIZED":
            raise ApiError(ERR_INVALID_APPLICATION_STATE, 409,
                           "DISPENSE requires AUTHORIZED")
    elif action == "VOID":
        if a["status"] != "AUTHORIZED":
            raise ApiError(ERR_INVALID_APPLICATION_STATE, 409,
                           "VOID requires AUTHORIZED")

    ev = db.snow_events.get(a["event_id"])
    if not ev:
        raise not_found(ERR_EVENT_NOT_FOUND, "SnowEvent not found")
    product = db.chemical_products.get(a["product_id"])
    if not product:
        raise not_found(ERR_PRODUCT_NOT_FOUND, "ChemicalProduct not found")

    if action == "AUTHORIZE":
        # event must be ACTIVATED/ESCALATED
        if ev["status"] not in ("ACTIVATED", "ESCALATED"):
            raise ApiError(ERR_EVENT_NOT_ACTIVE, 409,
                           "Referenced SnowEvent not ACTIVATED/ESCALATED")
        # product must be ACTIVE
        if product["status"] != "ACTIVE":
            raise ApiError(ERR_PRODUCT_CONSTRAINED, 409,
                           "ChemicalProduct is CONSTRAINED")
        # environmental pools
        event_remaining = compute_event_remaining_lbs(ev)
        product_available = product["seasonal_available_lbs"]
        if min(event_remaining, product_available) <= 0:
            raise ApiError(ERR_ENV_LIMIT_EXCEEDED, 422,
                           "Environmental pools exhausted")
        authorized_qty = min(a["raw_quantity_lbs"], event_remaining,
                             product_available)
        line_cost = round_cents(authorized_qty *
                                product["unit_cost_cents_per_lb"])
        # budget check
        if ev["estimated_cost_cents"] + line_cost > ev["budget_cents"]:
            raise ApiError(ERR_BUDGET_EXCEEDED, 422,
                           "Authorization would exceed budget_cents")
        a["authorized_quantity_lbs"] = authorized_qty
        a["capped"] = authorized_qty < a["raw_quantity_lbs"]
        a["line_cost_cents"] = line_cost
        a["authorized_by"] = user_id
        a["status"] = "AUTHORIZED"
        a["version"] += 1
        a["updated_at"] = now_iso_ms()
        recompute_product_counters(product)
        recompute_event_costs(ev)
        ev["updated_at"] = now_iso_ms()
    elif action == "DISPENSE":
        if user_id == a["authorized_by"]:
            raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                           "Same user may not authorize and dispense")
        a["status"] = "DISPENSED"
        a["version"] += 1
        a["updated_at"] = now_iso_ms()
        recompute_product_counters(product)
        recompute_event_chemical_used(ev)
        recompute_event_costs(ev)
        ev["updated_at"] = now_iso_ms()
        # CONSTRAINED cascade
        flip_product_constrained_if_threshold(product)
    elif action == "VOID":
        a["status"] = "VOIDED"
        a["version"] += 1
        a["updated_at"] = now_iso_ms()
        recompute_product_counters(product)
        recompute_event_costs(ev)
        ev["updated_at"] = now_iso_ms()

    return success_object(serialize_chemical_application(a))


@bp.route("/chemical-applications", methods=["GET"])
def list_applications():
    user_id, role = require_roles("MaintenanceLead", "OpsController")
    limit, offset = get_pagination(request.args)
    items = list(db.chemical_applications.values())
    for f in ("event_id", "surface_id", "product_id", "status"):
        q = request.args.get(f)
        if q:
            items = [a for a in items if a[f] == q]
    items.sort(key=lambda a: a["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_chemical_application(a) for a in page],
                        limit, offset, total)


@bp.route("/chemical-applications/<app_id>", methods=["GET"])
def get_application(app_id):
    user_id, role = require_roles("MaintenanceLead", "OpsController")
    a = _get_app_or_404(app_id)
    return success_object(serialize_chemical_application(a))
