"""Compound routes (PRD §3.4/§3.5)."""
from flask import Blueprint, request

import errors
import helpers
from db import db, stamp_create, touch
from middleware import require
from response import object_response, array_response
from services import calculations as calc

bp = Blueprint("compounds", __name__)

READ_ROLES = ["Pharmacist", "MedicalDirector", "VisitingNurse"]


@bp.route("/compounds", methods=["POST"])
def create_compound():
    require(["Pharmacist"])
    body = helpers.get_body()
    # (3) existence before (4) other body validity (PRD §2.8)
    order_id = helpers.as_str(body, "order_id")
    pump_id = helpers.as_str(body, "pump_id")
    if order_id not in db.infusion_orders:
        raise errors.not_found("Infusion order not found")
    if pump_id not in db.pumps:
        raise errors.not_found("Pump not found")
    delivery_at = helpers.as_datetime(body, "delivery_at")
    retrieval_at = helpers.as_datetime(body, "retrieval_at")

    compound = stamp_create({
        "order_id": order_id,
        "vials_reserved": 0,
        "pump_id": pump_id,
        "delivery_at": body["delivery_at"],
        "retrieval_at": body["retrieval_at"],
        "status": "ORDERED",
    })
    db.compounds[compound["id"]] = compound
    return object_response(compound, 201)


@bp.route("/compounds/<id>", methods=["GET"])
def get_compound(id):
    require(READ_ROLES)
    compound = db.compounds.get(id)
    if compound is None:
        raise errors.not_found("Compound not found")
    return object_response(compound, 200)


@bp.route("/compounds", methods=["GET"])
def list_compounds():
    require(READ_ROLES)
    limit, offset = helpers.pagination_params()
    items = list(db.compounds.values())
    order_id = request.args.get("order_id")
    pump_id = request.args.get("pump_id")
    if order_id is not None:
        items = [c for c in items if c["order_id"] == order_id]
    if pump_id is not None:
        items = [c for c in items if c["pump_id"] == pump_id]
    items = helpers.sort_by_created(items)
    window, total, has_more = helpers.paginate(items, limit, offset)
    return array_response(window, limit, offset, total, has_more, 200)


@bp.route("/compounds/<id>/compound", methods=["POST"])
def compound_batch(id):
    require(["Pharmacist"])
    compound = db.compounds.get(id)
    if compound is None:
        raise errors.not_found("Compound not found")

    # (5) state legality
    if compound["status"] != "ORDERED":
        raise errors.invalid_state("Compound is not in ORDERED state")
    order = db.infusion_orders.get(compound["order_id"])
    if order is None or order["status"] not in ("RELEASED", "ACTIVE"):
        raise errors.invalid_state("Order is not in RELEASED or ACTIVE state")

    drug = db.drug_catalog.get(order["drug_id"])
    pump = db.pumps.get(compound["pump_id"])
    needed = calc.whole_vials(order["daily_dose_mg"], order["scheduled_days"], drug["vial_size_mg"])

    # (10) pump reservation overlap — pump must be AVAILABLE and free of conflict
    if pump is None or pump["status"] != "AVAILABLE":
        raise errors.ApiError(errors.ERR_PUMP_DOUBLE_BOOKED, 409, "Pump is not AVAILABLE")
    new_delivery = helpers.parse_iso(compound["delivery_at"])
    new_retrieval = helpers.parse_iso(compound["retrieval_at"])
    for other in db.compounds.values():
        if other["id"] == compound["id"]:
            continue
        if other["pump_id"] != compound["pump_id"]:
            continue
        if other["status"] not in ("COMPOUNDED", "DELIVERED"):
            continue
        ex_delivery = helpers.parse_iso(other["delivery_at"])
        ex_retrieval = helpers.parse_iso(other["retrieval_at"])
        if calc.pump_conflict(new_delivery, new_retrieval, ex_delivery, ex_retrieval):
            raise errors.ApiError(errors.ERR_PUMP_DOUBLE_BOOKED, 409,
                                  "Pump reservation conflict")

    # (12) inventory sufficiency
    if needed > drug["on_hand_vials"]:
        raise errors.ApiError(errors.ERR_INSUFFICIENT_INVENTORY, 409,
                              "Insufficient on-hand vials")

    # (13) authorization-unit ceiling (only when the order went through authorization)
    auth = _latest_approved_auth(order["id"])
    if auth is not None and needed > auth["approved_units"]:
        raise errors.ApiError(errors.ERR_AUTH_UNITS_EXCEEDED, 422,
                              "Required vials exceed approved_units")

    # commit
    compound["vials_reserved"] = needed
    compound["status"] = "COMPOUNDED"
    touch(compound)
    drug["on_hand_vials"] -= needed
    touch(drug)
    return object_response(compound, 200)


@bp.route("/compounds/<id>/deliver", methods=["POST"])
def deliver_compound(id):
    require(["Pharmacist"])
    compound = db.compounds.get(id)
    if compound is None:
        raise errors.not_found("Compound not found")
    if compound["status"] != "COMPOUNDED":
        raise errors.invalid_state("Compound is not in COMPOUNDED state")
    compound["status"] = "DELIVERED"
    touch(compound)
    return object_response(compound, 200)


def _latest_approved_auth(order_id):
    """An APPROVED PriorAuthorization for this order, if any (the order went
    through authorization)."""
    approved = [a for a in db.prior_authorizations.values()
                if a["order_id"] == order_id and a["status"] == "APPROVED"]
    if not approved:
        return None
    return helpers.sort_by_created(approved)[-1]
