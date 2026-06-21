"""Box selection endpoints: curate/skip/swap (PRD §3.6)."""
from flask import Blueprint, request, g

from db import db
from common import (new_record, touch, serialize, get_body, require_int,
                    require_field, must_exist, paginate)
from middleware import authenticate, require_roles, require_owner_subscriber
from response import success, list_success
from errors import (err, ERR_INVALID_REQUEST, ERR_BOX_ITEM_COUNT_MISMATCH,
                    ERR_BOX_ALREADY_FINALIZED, ERR_NOT_FOUND)

bp = Blueprint("box_selections", __name__)


def _validate_product_ids(value):
    if not isinstance(value, list):
        raise err(ERR_INVALID_REQUEST, "product_ids must be an array.")
    for pid in value:
        if not isinstance(pid, str) or pid == "":
            raise err(ERR_INVALID_REQUEST, "Each product_id must be a non-empty string.")
    return value


@bp.post("/subscriptions/<sid>/box-selections")
def create_box_selection(sid):
    authenticate()
    require_roles("Subscriber")
    sub = must_exist(db.subscriptions, sid, "Subscription")
    require_owner_subscriber(sub["subscriber_id"])
    body = get_body()
    period_index = require_int(body, "period_index")

    skip = body.get("skip", False)
    if skip is None:
        skip = False
    if not isinstance(skip, bool):
        raise err(ERR_INVALID_REQUEST, "skip must be a boolean.")

    product_ids = body.get("product_ids", [])
    if product_ids is None:
        product_ids = []
    _validate_product_ids(product_ids)

    # period_index must equal current_period_index + 1
    if period_index != sub["current_period_index"] + 1:
        raise err(ERR_INVALID_REQUEST,
                  "period_index must equal current_period_index + 1.")

    plan = db.plans[sub["plan_id"]]

    if skip:
        decision = "SKIPPED"
        stored_products = []
    else:
        # existence of referenced products (body FK)
        for pid in product_ids:
            must_exist(db.products, pid, "Product")
        # business: curated box length must equal plan.box_item_count
        if len(product_ids) != plan["box_item_count"]:
            raise err(ERR_BOX_ITEM_COUNT_MISMATCH,
                      "Curated box product count must equal the plan box_item_count.")
        decision = "CURATED"
        stored_products = list(product_ids)

    box = new_record({
        "subscription_id": sid,
        "period_index": period_index,
        "product_ids": stored_products,
        "decision": decision,
        "allocation_id": None,
    })
    db.box_selections[box["id"]] = box
    return success(serialize(box), status=201)


@bp.get("/box-selections/<bid>")
def get_box_selection(bid):
    authenticate()
    require_roles("Subscriber", "CurationAdmin")
    box = must_exist(db.box_selections, bid, "BoxSelection")
    sub = db.subscriptions.get(box["subscription_id"])
    if sub is not None:
        require_owner_subscriber(sub["subscriber_id"])
    return success(serialize(box))


@bp.get("/box-selections")
def list_box_selections():
    authenticate()
    require_roles("Subscriber", "CurationAdmin")
    records = list(db.box_selections.values())
    if g.role == "Subscriber":
        owned = {s["id"] for s in db.subscriptions.values()
                 if s["subscriber_id"] == g.user_id}
        records = [r for r in records if r["subscription_id"] in owned]
    sub_filter = request.args.get("subscription_id")
    if sub_filter is not None:
        records = [r for r in records if r["subscription_id"] == sub_filter]
    alloc_filter = request.args.get("allocation_id")
    if alloc_filter is not None:
        records = [r for r in records if r.get("allocation_id") == alloc_filter]
    page, limit, offset, total = paginate(records)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.patch("/box-selections/<bid>")
def patch_box_selection(bid):
    authenticate()
    require_roles("Subscriber")
    box = must_exist(db.box_selections, bid, "BoxSelection")
    sub = db.subscriptions.get(box["subscription_id"])
    if sub is not None:
        require_owner_subscriber(sub["subscriber_id"])
    body = get_body()

    skip = body.get("skip")
    if skip is not None and not isinstance(skip, bool):
        raise err(ERR_INVALID_REQUEST, "skip must be a boolean.")

    new_products = body.get("product_ids")
    if new_products is not None:
        _validate_product_ids(new_products)

    # business: a FINALIZED box holding an allocation cannot be swapped/skipped
    if box["decision"] == "FINALIZED" and box.get("allocation_id"):
        raise err(ERR_BOX_ALREADY_FINALIZED,
                  "Cannot swap a box already finalized into a wave.")

    plan = db.plans[sub["plan_id"]] if sub else None

    if skip is True:
        box["decision"] = "SKIPPED"
        box["product_ids"] = []
    elif new_products is not None:
        for pid in new_products:
            must_exist(db.products, pid, "Product")
        if plan is not None and len(new_products) != plan["box_item_count"]:
            raise err(ERR_BOX_ITEM_COUNT_MISMATCH,
                      "Curated box product count must equal the plan box_item_count.")
        box["product_ids"] = list(new_products)
        box["decision"] = "CURATED"
    elif skip is False:
        # explicit un-skip with no products keeps it CURATED only if products exist
        box["decision"] = "CURATED" if box["product_ids"] else "PENDING"

    touch(box)
    return success(serialize(box))
