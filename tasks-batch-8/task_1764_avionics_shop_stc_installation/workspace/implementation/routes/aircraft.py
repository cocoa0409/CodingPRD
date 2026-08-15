"""Aircraft endpoints."""
from flask import Blueprint, request

import db
import errors
from middleware import (
    authenticate,
    body,
    pagination_args,
    paginate,
    req_num,
    req_str,
    require_role,
)
from response import success
from serializers import ser_aircraft
from util import D, rhu

bp = Blueprint("aircraft", __name__)


@bp.post("/avionics/aircraft")
def create_aircraft():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    b = body()
    customer_id = req_str(b, "customer_id")
    tail_number = req_str(b, "tail_number")
    make_model = req_str(b, "make_model")
    weight = req_num(b, "baseline_empty_weight_lb")
    arm = req_num(b, "baseline_arm_in")
    cg_min = req_num(b, "cg_min_arm_in")
    cg_max = req_num(b, "cg_max_arm_in")

    # existence (priority 4): owning customer must exist
    if customer_id not in db.customers:
        errors.raise_err(errors.ERR_NOT_FOUND, "Customer not found")

    # uniqueness (priority 9): tail numbers unique across all aircraft
    if any(a.tail_number == tail_number for a in db.aircraft.values()):
        errors.raise_err(errors.ERR_DUPLICATE_TAIL_NUMBER, "tail_number already registered")

    baseline_moment = float(rhu(D(str(weight)) * D(str(arm)), 1))
    a = db.new_entity(
        customer_id=customer_id,
        tail_number=tail_number,
        make_model=make_model,
        baseline_empty_weight_lb=weight,
        baseline_arm_in=arm,
        baseline_moment_lb_in=baseline_moment,
        cg_min_arm_in=cg_min,
        cg_max_arm_in=cg_max,
        status="AVAILABLE",
    )
    db.aircraft[a.id] = a
    return success(ser_aircraft(a), 201)


@bp.get("/avionics/aircraft/<aircraftId>")
def get_aircraft(aircraftId):
    authenticate()
    a = db.aircraft.get(aircraftId)
    if a is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Aircraft not found")
    return success(ser_aircraft(a), 200)


@bp.get("/avionics/aircraft")
def list_aircraft():
    authenticate()
    limit, offset = pagination_args()
    customer_id = request.args.get("customer_id")
    items = sorted(db.aircraft.values(), key=lambda a: a._seq)
    if customer_id is not None:
        items = [a for a in items if a.customer_id == customer_id]
    page, meta = paginate([ser_aircraft(a) for a in items], limit, offset)
    return success(page, 200, meta)
