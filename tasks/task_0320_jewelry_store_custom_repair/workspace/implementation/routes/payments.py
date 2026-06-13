"""Payments and the money they move (PRD §3.9)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_caller, require_role, parse_pagination, paginate
from response import success
from services import serialize
from services.common import get_body, require_int, require_enum, resolve_path
from routes.custom_orders import recompute_deposit_paid as co_recompute, recompute_balance as co_balance
from routes.layaway_plans import recompute_paid_to_date as la_recompute
from routes.special_orders import recompute_deposit_paid as so_recompute

bp = Blueprint("payments", __name__)

TARGET_TYPES = {"CUSTOM_ORDER", "LAYAWAY", "SPECIAL_ORDER"}

# target_type -> (request FK field, db collection, the other two FK fields)
_TARGET_MAP = {
    "CUSTOM_ORDER": ("custom_order_id", lambda: db.custom_orders,
                     ("layaway_plan_id", "special_order_id")),
    "LAYAWAY": ("layaway_plan_id", lambda: db.layaway_plans,
                ("custom_order_id", "special_order_id")),
    "SPECIAL_ORDER": ("special_order_id", lambda: db.special_orders,
                      ("custom_order_id", "layaway_plan_id")),
}


@bp.route("/payments", methods=["POST"])
def create_payment():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager"})
    body = get_body()
    # Body well-formedness first (priority 5): valid enum + amount > 0.
    target_type = require_enum(body, "target_type", TARGET_TYPES)
    amount = require_int(body, "amount_cents", gt=0)

    # Payment-target consistency (priority 7): exactly the matching FK present,
    # references an existing parent, and the other two absent.
    fk_field, collection_getter, other_fields = _TARGET_MAP[target_type]
    collection = collection_getter()
    fk_val = body.get(fk_field)
    if not isinstance(fk_val, str) or fk_val == "":
        raise ApiError("ERR_PAYMENT_TARGET_MISMATCH", "Matching target FK missing")
    for of in other_fields:
        if body.get(of) is not None:
            raise ApiError("ERR_PAYMENT_TARGET_MISMATCH", "Conflicting target FK present")
    parent = collection.get(fk_val)
    if parent is None:
        raise ApiError("ERR_PAYMENT_TARGET_MISMATCH", "Target parent does not exist")

    rec = db.new_record(common_fields=False)
    rec.update({
        "target_type": target_type,
        "custom_order_id": body.get("custom_order_id") if target_type == "CUSTOM_ORDER" else None,
        "layaway_plan_id": body.get("layaway_plan_id") if target_type == "LAYAWAY" else None,
        "special_order_id": body.get("special_order_id") if target_type == "SPECIAL_ORDER" else None,
        "amount_cents": amount, "outcome": "SUCCEEDED",
    })
    db.payments[rec["id"]] = rec

    # Recompute parent totals and drive automatic state advances.
    if target_type == "CUSTOM_ORDER":
        co_recompute(parent)
        co_balance(parent)
        if parent["status"] == "QUOTED" and parent["deposit_required_cents"] is not None \
                and parent["deposit_paid_cents"] >= parent["deposit_required_cents"]:
            parent["status"] = "DEPOSIT_PAID"
            db.touch(parent)
    elif target_type == "LAYAWAY":
        la_recompute(parent)
        if parent["status"] == "ACTIVE" and parent["item_price_cents"] is not None \
                and parent["paid_to_date_cents"] >= parent["item_price_cents"]:
            parent["status"] = "PAID_IN_FULL"
            db.touch(parent)
    else:  # SPECIAL_ORDER
        so_recompute(parent)

    return success(serialize.payment(rec), status=201)


@bp.route("/payments", methods=["GET"])
def list_payments():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    limit, offset = parse_pagination()
    f_co = request.args.get("custom_order_id")
    f_la = request.args.get("layaway_plan_id")
    f_so = request.args.get("special_order_id")
    records = []
    for p in db.payments.values():
        if f_co is not None and p.get("custom_order_id") != f_co:
            continue
        if f_la is not None and p.get("layaway_plan_id") != f_la:
            continue
        if f_so is not None and p.get("special_order_id") != f_so:
            continue
        records.append(p)
    page, meta = paginate(records, limit, offset)
    return success([serialize.payment(r) for r in page], status=200, pagination=meta)


@bp.route("/payments/<pid>", methods=["GET"])
def get_payment(pid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    rec = resolve_path(db.payments, pid)
    return success(serialize.payment(rec), status=200)
