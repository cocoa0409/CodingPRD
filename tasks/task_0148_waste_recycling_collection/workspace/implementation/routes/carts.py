"""Cart endpoints (PRD §3.1)."""
from flask import request, Blueprint

from db import db, base_record, touch
from errors import err
from middleware import authenticate, require_roles
from response import success
from services import serializers as ser
from services.common import check_enum, get_json_body, paginate, parse_pagination, require_fields

bp = Blueprint("carts", __name__)

STREAMS = {"TRASH", "RECYCLE", "ORGANICS"}
SIZES = {35, 65, 96}


@bp.route("/carts", methods=["POST"])
def create_cart():
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    body = get_json_body()
    # Body-reference existence (priority 5) precedes request-shape (priority 6):
    # when account_id is supplied, its existence is checked before remaining
    # required-field / enum validation. A missing account_id is itself a
    # request-shape failure (ERR_INVALID_REQUEST) but, because it gates the FK
    # check, the FK field is validated for presence-then-existence first.
    require_fields(body, ["account_id"])
    if body["account_id"] not in db.accounts:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced account does not exist.")
    require_fields(body, ["stream", "size_gallons"])
    check_enum(body["stream"], STREAMS, "stream")
    # size_gallons must be an integer in {35,65,96}; out-of-domain -> ERR_VALIDATION.
    size = body["size_gallons"]
    if size not in SIZES:
        raise err("ERR_VALIDATION", "size_gallons must be one of 35, 65, 96.")

    tare = body.get("tare_weight_lbs")
    if tare is None:
        tare = 0

    rec = base_record()
    rec.update(
        {
            "account_id": body["account_id"],
            "stream": body["stream"],
            "size_gallons": size,
            "status": "ASSIGNED",
            "tare_weight_lbs": tare,
        }
    )
    db.carts[rec["id"]] = rec
    return success(ser.cart(rec), status=201)


@bp.route("/carts/<cart_id>", methods=["GET"])
def get_cart(cart_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher", "Driver", "Billing"})
    rec = db.carts.get(cart_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Cart not found.")
    return success(ser.cart(rec), status=200)


@bp.route("/carts", methods=["GET"])
def list_carts():
    _, role = authenticate()
    require_roles(role, {"Dispatcher", "Driver", "Billing"})
    parse_pagination()
    items = list(db.carts.values())
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    stream = request.args.get("stream")
    if account_id is not None:
        items = [c for c in items if c["account_id"] == account_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if stream is not None:
        items = [c for c in items if c["stream"] == stream]
    page, pagination = paginate(items)
    return success([ser.cart(c) for c in page], status=200, pagination=pagination)


def _transition(cart_id, allowed_from, target):
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    rec = db.carts.get(cart_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Cart not found.")
    if rec["status"] not in allowed_from:
        raise err("ERR_INVALID_STATE", "Cart cannot transition from its current state.")
    rec["status"] = target
    touch(rec)
    return success(ser.cart(rec), status=200)


@bp.route("/carts/<cart_id>/activate", methods=["POST"])
def activate_cart(cart_id):
    return _transition(cart_id, {"ASSIGNED", "ON_HOLD"}, "ACTIVE")


@bp.route("/carts/<cart_id>/hold", methods=["POST"])
def hold_cart(cart_id):
    return _transition(cart_id, {"ACTIVE"}, "ON_HOLD")


@bp.route("/carts/<cart_id>/retire", methods=["POST"])
def retire_cart(cart_id):
    return _transition(cart_id, {"ASSIGNED", "ACTIVE", "ON_HOLD"}, "RETIRED")
