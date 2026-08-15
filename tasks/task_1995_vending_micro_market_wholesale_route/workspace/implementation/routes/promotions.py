"""Promotion endpoints (scaffold §1.5; overlap rule per PRD §3.5)."""
from flask import Blueprint, request
import db
from middleware import get_auth, require_role
from response import success_object, success_list, parse_pagination
from util import get_json_body, req_string, req_int, req_enum, stamp_new, touch
from errors import (
    ApiError, ERR_PRODUCT_NOT_FOUND, ERR_OPERATOR_NOT_FOUND, ERR_PROMOTION_NOT_FOUND,
    ERR_INVALID_REQUEST, ERR_PROMOTION_WINDOW_OVERLAP,
)
import clock

bp = Blueprint("promotions", __name__)

DISCOUNT_TYPES = {"PERCENT_OFF", "CENTS_OFF"}
STACKING = {"EXCLUSIVE", "STACKABLE"}


def view(p):
    out = {}
    for k, v in p.items():
        if k in ("starts_at_dt", "ends_at_dt"):
            continue
        out[k] = v
    return out


@bp.post("/wholesale/promotions")
def create_promotion():
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["WholesaleAdmin"])
    product_id = req_string(body, "product_id")
    operator_id = body.get("operator_id", None)
    if operator_id is not None and not isinstance(operator_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "operator_id must be a string or null")
    discount_type = req_enum(body, "discount_type", DISCOUNT_TYPES)
    discount_value = req_int(body, "discount_value")
    if discount_type == "PERCENT_OFF":
        if discount_value < 1 or discount_value > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "discount_value must be 1-100 for PERCENT_OFF")
    else:
        if discount_value <= 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "discount_value must be > 0 for CENTS_OFF")
    starts_raw = req_string(body, "starts_at")
    ends_raw = req_string(body, "ends_at")
    try:
        starts_dt = clock.parse_iso(starts_raw)
        ends_dt = clock.parse_iso(ends_raw)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "starts_at/ends_at must be ISO 8601 datetimes")
    if not (starts_dt < ends_dt):
        raise ApiError(ERR_INVALID_REQUEST, 400, "starts_at must be before ends_at")
    stacking_class = req_enum(body, "stacking_class", STACKING)
    # Body-referenced existence
    if product_id not in db.products:
        raise ApiError(ERR_PRODUCT_NOT_FOUND, 404, "Product id does not exist")
    if operator_id is not None and operator_id not in db.operators:
        raise ApiError(ERR_OPERATOR_NOT_FOUND, 404, "Operator id does not exist")
    # Overlap check (tier 10): same product AND equal operator scope (null == null only);
    # half-open windows overlap iff starts < other.ends and other.starts < ends.
    for p in db.promotions.values():
        if p["status"] != "ACTIVE":
            continue
        if p["product_id"] != product_id:
            continue
        if p.get("operator_id") != operator_id:
            continue
        if starts_dt < p["ends_at_dt"] and p["starts_at_dt"] < ends_dt:
            raise ApiError(
                ERR_PROMOTION_WINDOW_OVERLAP, 409,
                "Promotion window overlaps another ACTIVE promotion for the same product and operator scope",
            )
    p = stamp_new({
        "product_id": product_id,
        "operator_id": operator_id,
        "discount_type": discount_type,
        "discount_value": discount_value,
        "starts_at": starts_raw,
        "ends_at": ends_raw,
        "starts_at_dt": starts_dt,
        "ends_at_dt": ends_dt,
        "stacking_class": stacking_class,
        "status": "ACTIVE",
    })
    db.promotions[p["id"]] = p
    return success_object(view(p), 201)


@bp.get("/wholesale/promotions")
def list_promotions():
    get_auth()
    limit, offset = parse_pagination(request.args)
    prod_f = request.args.get("product_id")
    op_f = request.args.get("operator_id")
    items = list(db.promotions.values())
    if prod_f is not None:
        items = [p for p in items if p["product_id"] == prod_f]
    if op_f is not None:
        items = [p for p in items if p.get("operator_id") == op_f]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    return success_list([view(p) for p in items[offset:offset + limit]], limit, offset, total)


@bp.get("/wholesale/promotions/<promotionId>")
def get_promotion(promotionId):
    get_auth()
    p = db.promotions.get(promotionId)
    if p is None:
        raise ApiError(ERR_PROMOTION_NOT_FOUND, 404, "Promotion id does not exist")
    return success_object(view(p))


@bp.post("/wholesale/promotions/<promotionId>/terminate")
def terminate_promotion(promotionId):
    user_id, role = get_auth()
    require_role(role, ["WholesaleAdmin"])
    p = db.promotions.get(promotionId)
    if p is None:
        raise ApiError(ERR_PROMOTION_NOT_FOUND, 404, "Promotion id does not exist")
    if p["status"] == "TERMINATED":
        # No distinct error declared; treat as invalid state transition.
        from errors import ERR_INVALID_STATE_TRANSITION
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Promotion already TERMINATED")
    p["status"] = "TERMINATED"
    touch(p)
    return success_object(view(p))
