"""DeviceOrder endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import errors
import validation as v
from db import store, new_entity, touch, clock
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.calculations import trial_conversion_fee
from routes.catalog import recompute_model_counts

bp = Blueprint("device_orders", __name__)

FULFILLMENT_TYPES = {"PURCHASE", "TRIAL", "LOANER"}

_CONDITION_RANK = {
    "PURCHASE": {"NEW": 0, "REFURB": 1},
    "TRIAL": {"LOANER": 0, "REFURB": 1, "NEW": 2},
    "LOANER": {"LOANER": 0, "REFURB": 1, "NEW": 2},
}


def _eligible_conditions(fulfillment_type):
    if fulfillment_type == "PURCHASE":
        return {"NEW", "REFURB"}
    return {"LOANER", "REFURB", "NEW"}


def _auto_select_unit(order):
    model_id = order["device_model_id"]
    ftype = order["fulfillment_type"]
    eligible = [
        u for u in store.device_units.values()
        if u["device_model_id"] == model_id
        and u["status"] == "IN_STOCK"
        and u["condition"] in _eligible_conditions(ftype)
    ]
    if not eligible:
        raise errors.no_eligible_unit()
    rank = _CONDITION_RANK[ftype]
    eligible.sort(key=lambda u: (rank[u["condition"]], u["created_at"], u["id"]))
    return eligible[0]


@bp.post("/api/device-orders")
def create_device_order():
    require_roles(["VisionSpecialist"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {
        "client_id", "evaluation_id", "device_model_id", "fulfillment_type",
        "trial_days", "warranty_cents",
    })
    client_id = v.req_string(body, "client_id")
    evaluation_id = v.req_string(body, "evaluation_id")
    device_model_id = v.req_string(body, "device_model_id")
    fulfillment_type = v.req_enum(body, "fulfillment_type", FULFILLMENT_TYPES)
    if fulfillment_type == "TRIAL":
        trial_days = v.req_int(body, "trial_days", min_v=1, max_v=60)
    else:
        trial_days = v.opt_int(body, "trial_days", default=None, min_v=1, max_v=60)
    warranty_cents = v.opt_int(body, "warranty_cents", default=0, min_v=0)

    # existence
    if client_id not in store.clients:
        raise errors.not_found("Client not found")
    evaluation = store.evaluations.get(evaluation_id)
    if evaluation is None:
        raise errors.not_found("Evaluation not found")
    model = store.device_models.get(device_model_id)
    if model is None:
        raise errors.not_found("DeviceModel not found")

    # cross-entity state: evaluation FINALIZED
    if evaluation["status"] != "FINALIZED":
        raise errors.evaluation_not_final()

    # domain: category match
    if model["category"] != evaluation["recommended_category"]:
        raise errors.category_mismatch()

    order = new_entity()
    order.update({
        "client_id": client_id,
        "evaluation_id": evaluation_id,
        "device_model_id": device_model_id,
        "fulfillment_type": fulfillment_type,
        "trial_days": trial_days if fulfillment_type == "TRIAL" else trial_days,
        "warranty_cents": warranty_cents,
        "device_unit_id": None,
        "dispensed_at": None,
        "trial_ends_at": None,
        "conversion_total_cents": None,
        "status": "PLACED",
    })
    store.device_orders[order["id"]] = order
    return success_object(order, status=201)


@bp.get("/api/device-orders/<oid>")
def get_device_order(oid):
    require_roles(ALL_ROLES)
    order = store.device_orders.get(oid)
    if order is None:
        raise errors.not_found("DeviceOrder not found")
    return success_object(order)


@bp.get("/api/device-orders")
def list_device_orders():
    require_roles(ALL_ROLES)
    limit, offset = v.parse_pagination(request.args)
    items = v.apply_filters(list(store.device_orders.values()), [
        (request.args.get("client_id"), "client_id"),
        (request.args.get("evaluation_id"), "evaluation_id"),
        (request.args.get("device_model_id"), "device_model_id"),
        (request.args.get("device_unit_id"), "device_unit_id"),
        (request.args.get("status"), "status"),
    ])
    items = v.sort_by_created(items)
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.post("/api/device-orders/<oid>/allocate")
def allocate_device_order(oid):
    require_roles(["VisionSpecialist"])
    body = request.get_json(silent=True)
    if body is not None:
        if not isinstance(body, dict):
            raise errors.validation("Request body must be a JSON object")
        v.reject_unknown_fields(body, {"device_unit_id"})
        explicit_unit_id = v.opt_string(body, "device_unit_id", default=None)
    else:
        explicit_unit_id = None

    order = store.device_orders.get(oid)
    if order is None:
        raise errors.not_found("DeviceOrder not found")
    if order["status"] != "PLACED":
        raise errors.invalid_state("Order is not PLACED")

    evaluation = store.evaluations.get(order["evaluation_id"])
    if evaluation is None or evaluation["status"] != "FINALIZED":
        raise errors.evaluation_not_final()

    # unit selection
    if explicit_unit_id is not None:
        unit = store.device_units.get(explicit_unit_id)
        if (unit is None or unit["status"] != "IN_STOCK"
                or unit["device_model_id"] != order["device_model_id"]):
            raise errors.unit_not_available()
    else:
        unit = _auto_select_unit(order)

    now = clock.now()
    ftype = order["fulfillment_type"]

    # unit transition
    if ftype in ("PURCHASE", "TRIAL"):
        unit["status"] = "DEPLOYED"
    else:  # LOANER
        unit["status"] = "ON_LOAN"
    touch(unit)
    recompute_model_counts(unit["device_model_id"])

    order["device_unit_id"] = unit["id"]
    order["dispensed_at"] = clock.now_iso()

    if ftype == "TRIAL":
        order["trial_ends_at"] = _format(now + timedelta(days=order["trial_days"]))
    elif ftype == "PURCHASE":
        model = store.device_models[order["device_model_id"]]
        order["conversion_total_cents"] = trial_conversion_fee(
            model["list_price_cents"], order["warranty_cents"], 0, None, now,
        )
    elif ftype == "LOANER":
        loan = new_entity()
        loan.update({
            "client_id": order["client_id"],
            "device_unit_id": unit["id"],
            "device_order_id": order["id"],
            "repair_ticket_id": None,
            "loaned_at": clock.now_iso(),
            "due_at": _format(now + timedelta(days=30)),
            "returned_at": None,
            "overdue_days": 0,
            "status": "ACTIVE",
        })
        store.loan_agreements[loan["id"]] = loan

    order["status"] = "ACTIVE"
    touch(order)
    return success_object(order)


@bp.post("/api/device-orders/<oid>/convert")
def convert_device_order(oid):
    require_roles(["VisionSpecialist"])
    order = store.device_orders.get(oid)
    if order is None:
        raise errors.not_found("DeviceOrder not found")
    if order["fulfillment_type"] != "TRIAL":
        raise errors.invalid_state("Only TRIAL orders can be converted")
    if order["status"] != "ACTIVE":
        raise errors.invalid_state("Order is not ACTIVE")

    now = clock.now()
    trial_ends_at = _parse(order["trial_ends_at"])
    if now > trial_ends_at:
        raise errors.trial_expired()

    model = store.device_models[order["device_model_id"]]
    order["conversion_total_cents"] = trial_conversion_fee(
        model["list_price_cents"], order["warranty_cents"],
        order["trial_days"], _parse(order["dispensed_at"]), now,
    )
    order["status"] = "CONVERTED"
    touch(order)
    return success_object(order)


@bp.post("/api/device-orders/<oid>/return")
def return_device_order(oid):
    require_roles(["VisionSpecialist"])
    order = store.device_orders.get(oid)
    if order is None:
        raise errors.not_found("DeviceOrder not found")
    if order["fulfillment_type"] not in ("TRIAL", "LOANER"):
        raise errors.invalid_state("PURCHASE orders cannot be returned")
    if order["status"] not in ("ACTIVE", "EXPIRED"):
        raise errors.invalid_state("Order cannot be returned from its current state")

    now = clock.now()
    unit = store.device_units.get(order["device_unit_id"])
    if unit is not None and unit["status"] in ("DEPLOYED", "ON_LOAN"):
        unit["status"] = "IN_STOCK"
        touch(unit)
        recompute_model_counts(unit["device_model_id"])

    if order["fulfillment_type"] == "LOANER":
        for loan in store.loan_agreements.values():
            if loan.get("device_order_id") == order["id"] and loan["status"] in ("ACTIVE", "OVERDUE"):
                loan["status"] = "RETURNED"
                loan["returned_at"] = clock.now_iso()
                due_at = _parse(loan["due_at"])
                days = (now - due_at).total_seconds() // 86400
                loan["overdue_days"] = int(days) if days > 0 else 0
                touch(loan)

    order["status"] = "RETURNED"
    touch(order)
    return success_object(order)


def _format(dt):
    from db import format_instant
    return format_instant(dt)


def _parse(s):
    from db import parse_datetime
    return parse_datetime(s)
