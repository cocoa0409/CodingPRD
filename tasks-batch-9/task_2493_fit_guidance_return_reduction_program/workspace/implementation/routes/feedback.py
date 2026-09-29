"""Reviewer fit feedback: the item's fit signal pool (PRD 3.6)."""

from flask import Blueprint

import constants as C
import validate as V
from db import db, new_row, touch
from errors import ApiError
from lookup import filtered, get_customer, get_feedback, get_item
from middleware import authenticate, require_owner
from response import array_response, object_response
from services.derive import lines_of_customer, recompute_item

bp = Blueprint("fit_feedback", __name__)


@bp.post("/fit-program/fit-feedback")
def publish_feedback():
    actor = authenticate(C.ROLE_CUSTOMER)

    # rank 4 precedes rank 5: the body's customer_profile_id must be the caller
    peeked = V.peek_str(V.raw_body(), "customer_profile_id")
    if peeked is not None:
        require_owner(peeked == actor.user_id,
                      "A Customer may only publish feedback under their own "
                      "profile id.")

    body = V.get_body()
    item_id = V.req_str(body, "item_id", min_len=1)
    customer_profile_id = V.req_str(body, "customer_profile_id", min_len=1)
    purchased_size_label = V.req_str(body, "purchased_size_label", min_len=1)
    fit_verdict = V.req_enum(body, "fit_verdict", C.FIT_VERDICTS)
    comment = V.opt_str(body, "comment")

    require_owner(customer_profile_id == actor.user_id,
                  "A Customer may only publish feedback under their own profile id.")

    # rank 7 walks the body FKs in declaration order
    item = get_item(item_id)
    customer = get_customer(customer_profile_id)

    for existing in db.feedback.values():
        if (existing["item_id"] == item["id"]
                and existing["customer_profile_id"] == customer["id"]
                and existing["status"] == "ACTIVE"):
            raise ApiError("ERR_DUPLICATE_FIT_FEEDBACK",
                           "This shopper already has ACTIVE feedback on this item.")

    purchased = any(line["item_id"] == item["id"]
                    and line["status"] in C.PURCHASED_LINE_STATUSES
                    for line in lines_of_customer(customer["id"]))

    feedback = new_row({
        "item_id": item["id"],
        "customer_profile_id": customer["id"],
        "purchased_size_label": purchased_size_label,
        "fit_verdict": fit_verdict,
        "comment": comment,
        "verdict_offset_centi": C.VERDICT_OFFSET_CENTI[fit_verdict],
        "signal_weight": C.FIT_RETURN_SIGNAL_WEIGHT if purchased else 100,
        "status": "ACTIVE",
        "retract_reason": None,
    })
    db.feedback[feedback["id"]] = feedback

    recompute_item(item)
    return object_response(feedback, 201)


@bp.get("/fit-program/fit-feedback/<feedback_id>")
def read_feedback(feedback_id):
    authenticate(C.ROLE_CUSTOMER, C.ROLE_FIT_ANALYST, C.ROLE_MERCH_OPS_ADMIN)
    return object_response(get_feedback(feedback_id))


@bp.get("/fit-program/fit-feedback")
def list_feedback():
    authenticate(C.ROLE_CUSTOMER, C.ROLE_FIT_ANALYST, C.ROLE_MERCH_OPS_ADMIN)
    limit, offset = V.pagination_params()
    rows = filtered(db.feedback.values(), {
        "item_id": "item_id",
        "customer_profile_id": "customer_profile_id",
        "status": "status",
    })
    page, meta = V.paginate(rows, limit, offset)
    return array_response(page, meta)


@bp.post("/fit-program/fit-feedback/<feedback_id>/retract")
def retract_feedback(feedback_id):
    actor = authenticate(C.ROLE_CUSTOMER)
    feedback = get_feedback(feedback_id)
    require_owner(feedback["customer_profile_id"] == actor.user_id,
                  "A Customer may only retract their own feedback.")

    body = V.get_body()
    retract_reason = V.req_enum(body, "retract_reason", C.RETRACT_REASONS)

    if feedback["status"] != "ACTIVE":
        raise ApiError("ERR_FEEDBACK_ALREADY_RETRACTED",
                       "This feedback row is already RETRACTED.")

    feedback["status"] = "RETRACTED"
    feedback["retract_reason"] = retract_reason
    touch(feedback)

    item = db.items.get(feedback["item_id"])
    if item is not None:
        recompute_item(item)

    return object_response(feedback)
