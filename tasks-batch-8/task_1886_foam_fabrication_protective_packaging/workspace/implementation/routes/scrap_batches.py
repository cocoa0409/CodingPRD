"""Offcut collection and scrap recycling credits (PRD §3.7)."""
from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object
from services.calculations import net_recyclable_lb, scrap_credit_cents
from services.common import (
    body, get_or_404, get_single, list_many, now_iso, owner_of_scrap_batch, pub,
    req_num, req_str, stamp_new, touch,
)

bp = Blueprint("scrap_batches", __name__)


@bp.route("/scrap-batches", methods=["POST"])
def create_scrap_batch():
    user_id, role = get_auth_context()
    require_role(role, ("PlantManager",))
    data = body()
    production_order_id = req_str(data, "production_order_id")
    gross = req_num(data, "gross_weight_lb", minimum=0, strict_min=True)
    contamination = req_num(data, "contamination_pct", minimum=0, maximum=100)
    order = get_or_404(db.production_orders, production_order_id, "ProductionOrder")
    if order["fab_status"] != "COMPLETED":
        raise ApiError(
            errors.ERR_INVALID_STATE,
            "Scrap batches may be collected only from COMPLETED production orders",
            409,
        )
    spec = db.package_specs.get(order["package_spec_id"])
    material = db.materials.get(spec["material_id"]) if spec else None
    if material is None or not material["recyclable"]:
        raise ApiError(
            errors.ERR_MATERIAL_NOT_RECYCLABLE,
            "Offcuts of this material are not accepted for recycling credit",
            422,
        )
    rec = stamp_new({
        "production_order_id": production_order_id,
        "gross_weight_lb": gross,
        "contamination_pct": contamination,
        "net_recyclable_lb": net_recyclable_lb(gross, contamination),
        "credit_cents": None,
        "credited_at": None,
        "status": "COLLECTED",
    })
    db.scrap_batches[rec["id"]] = rec
    return success_object(pub(rec), 201)


@bp.route("/scrap-batches", methods=["GET"])
def list_scrap_batches():
    return list_many(db.scrap_batches, owner_of_scrap_batch, ("production_order_id", "status"))


@bp.route("/scrap-batches/<rid>", methods=["GET"])
def get_scrap_batch(rid):
    return get_single(db.scrap_batches, rid, owner_of_scrap_batch, "ScrapBatch")


@bp.route("/scrap-batches/<rid>/process", methods=["POST"])
def process_scrap_batch(rid):
    user_id, role = get_auth_context()
    require_role(role, ("PlantManager",))
    rec = get_or_404(db.scrap_batches, rid, "ScrapBatch")
    if rec["status"] != "COLLECTED":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot process a batch in {rec['status']}", 409)
    rec["status"] = "PROCESSED"
    touch(rec)
    return success_object(pub(rec))


@bp.route("/scrap-batches/<rid>/credit", methods=["POST"])
def credit_scrap_batch(rid):
    user_id, role = get_auth_context()
    require_role(role, ("PlantManager",))
    rec = get_or_404(db.scrap_batches, rid, "ScrapBatch")
    if rec["status"] != "PROCESSED":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot credit a batch in {rec['status']}", 409)
    order = db.production_orders.get(rec["production_order_id"])
    spec = db.package_specs.get(order["package_spec_id"]) if order else None
    material = db.materials.get(spec["material_id"]) if spec else None
    credit = scrap_credit_cents(rec, material)
    rec["credit_cents"] = credit
    rec["credited_at"] = now_iso()
    rec["status"] = "CREDITED"
    touch(rec)
    # The credit posts to the customer of the production order's specification.
    customer = db.customers.get(spec["customer_id"]) if spec else None
    if customer is not None:
        customer["credit_balance_cents"] += credit
        touch(customer)
    return success_object(pub(rec))
