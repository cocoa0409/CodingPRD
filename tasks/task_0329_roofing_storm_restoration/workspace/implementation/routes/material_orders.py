"""MaterialOrder resource: place, read, list, deliver, cancel."""
from flask import Blueprint, request

import errors
from errors import ApiError
from db import db, common_create_fields, touch
from middleware import require_role, get_json_body
from response import success, list_response
from services import calculations as calc
from services.jobledger import effective_shingle_squares
import validators as V

bp = Blueprint("material_orders", __name__)

ROLE_ALL = {"FieldAdjuster", "Estimator", "ProductionManager"}


@bp.route("/material-orders", methods=["POST"])
def create_material_order():
    require_role({"ProductionManager"})
    body = get_json_body()
    job_id = V.require_field(body, "job_id")
    if not isinstance(job_id, str):
        V.missing_field("job_id")
    job = V.resolve_fk(db.jobs, job_id)

    with db.lock:
        squares = effective_shingle_squares(job)
        bundles, total_weight, freight = calc.material_sizing(squares)
        ent = common_create_fields(versioned=True)
        ent.update({
            "job_id": job_id,
            "bundles": bundles,
            "total_weight_lbs": total_weight,
            "freight_cents": freight,
            "status": "ORDERED",
            "delivered_short": None,
        })
        db.material_orders[ent["id"]] = ent
    return success(ent, status=201)


@bp.route("/material-orders/<entity_id>", methods=["GET"])
def get_material_order(entity_id):
    require_role(ROLE_ALL)
    ent = V.find_or_404(db.material_orders, entity_id)
    return success(ent, status=200)


@bp.route("/material-orders", methods=["GET"])
def list_material_orders():
    require_role(ROLE_ALL)
    limit, offset = V.parse_pagination()
    items = list(db.material_orders.values())
    for key in ("job_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [m for m in items if m.get(key) == val]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/material-orders/<entity_id>/deliver", methods=["POST"])
def deliver_material_order(entity_id):
    require_role({"ProductionManager"})
    with db.lock:
        mo = V.find_or_404(db.material_orders, entity_id)
        body = get_json_body()
        # state (priority 7): must be ORDERED
        if mo["status"] != "ORDERED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Material order not ORDERED")
        # cross-entity: parent job must be CONTRACTED or IN_PRODUCTION
        job = db.jobs.get(mo["job_id"])
        if job is None or job["status"] not in ("CONTRACTED", "IN_PRODUCTION"):
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Parent job must be CONTRACTED or IN_PRODUCTION")
        delivered_short = body.get("delivered_short")
        if delivered_short is not None and not isinstance(delivered_short, bool):
            V.invalid_request("delivered_short must be a boolean")
        mo["status"] = "DELIVERED"
        if delivered_short is not None:
            mo["delivered_short"] = delivered_short
        touch(mo)
        return success(mo, status=200)


@bp.route("/material-orders/<entity_id>/cancel", methods=["POST"])
def cancel_material_order(entity_id):
    require_role({"ProductionManager"})
    with db.lock:
        mo = V.find_or_404(db.material_orders, entity_id)
        if mo["status"] != "ORDERED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Material order not ORDERED")
        mo["status"] = "CANCELLED"
        touch(mo)
        return success(mo, status=200)
