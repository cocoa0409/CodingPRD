"""Feedback endpoints. PRD §3.11."""
from flask import Blueprint, request

import db
import errors
import response
import middleware as mw
from services import core
from routes.helpers import get_json_body, paginate_list

bp = Blueprint("feedback", __name__)

VALID_RATINGS = {"POSITIVE", "NEUTRAL", "NEGATIVE"}


@bp.route("/orders/<order_id>/feedback", methods=["POST"])
def leave_feedback(order_id):
    caller = mw.require_auth()                          # priority 1
    mw.require_role(caller, {"Buyer", "Seller"})        # priority 2
    body = get_json_body()
    order = db.orders.get(order_id)                     # existence (priority 4)
    if order is None:
        raise errors.not_found("Order not found.")

    rater_account_id = body.get("rater_account_id")
    if not isinstance(rater_account_id, str) or rater_account_id == "":
        raise errors.invalid_request("rater_account_id is required.")
    # Ownership (priority 3): the rater must be the acting account.
    if rater_account_id != caller.user_id:
        raise errors.not_owner("rater_account_id must be the acting account.")
    rater = db.accounts.get(rater_account_id)
    if rater is None:
        raise errors.not_found("Rater account not found.")
    mw.check_account_not_closed(caller)

    # Feedback eligibility (priority 15, ERR_FEEDBACK_NOT_ELIGIBLE).
    if order["fulfillment_status"] not in ("DELIVERED", "RETURNED"):
        raise errors.feedback_not_eligible("Order is not in a feedback-eligible state.")

    is_buyer = rater_account_id == order["buyer_account_id"]
    is_seller = rater_account_id == order["seller_account_id"]
    if not (is_buyer or is_seller):
        raise errors.feedback_not_eligible("The rater is not a party to this order.")

    # Pin role + ratee from the order.
    if is_buyer:
        role = "BUYER"
        ratee_account_id = order["seller_account_id"]
    else:
        role = "SELLER"
        ratee_account_id = order["buyer_account_id"]

    # Uniqueness on (order_id, role).
    for f in db.feedback.values():
        if f["order_id"] == order_id and f["role"] == role:
            raise errors.feedback_not_eligible("Feedback already exists for this order and role.")

    rating = body.get("rating")
    if rating not in VALID_RATINGS:
        raise errors.invalid_request("rating must be POSITIVE, NEUTRAL, or NEGATIVE.")
    comment = body.get("comment", "")
    if comment is None:
        comment = ""
    if not isinstance(comment, str):
        raise errors.invalid_request("comment must be a string.")

    fid = db.new_id()
    fb = {
        "id": fid,
        "order_id": order_id,
        "rater_account_id": rater_account_id,
        "ratee_account_id": ratee_account_id,
        "role": role,
        "rating": rating,
        "comment": comment,
    }
    core.stamp_new(fb, with_version=False)
    db.feedback[fid] = fb

    # Recompute the ratee account's feedback score.
    core.recompute_feedback_score(ratee_account_id)
    return response.success(core.ser_feedback(fb), status=201)


@bp.route("/orders/<order_id>/feedback-entries", methods=["GET"])
def list_order_feedback(order_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"Anonymous", "Buyer", "Seller", "PlatformAdmin"})
    order = db.orders.get(order_id)
    if order is None:
        raise errors.not_found("Order not found.")
    items = [f for f in db.feedback.values() if f["order_id"] == order_id]
    return paginate_list(items, core.ser_feedback)


@bp.route("/feedback/<feedback_id>", methods=["GET"])
def get_feedback(feedback_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"Anonymous", "Buyer", "Seller", "PlatformAdmin"})
    fb = db.feedback.get(feedback_id)
    if fb is None:
        raise errors.not_found("Feedback not found.")
    return response.success(core.ser_feedback(fb), status=200)


@bp.route("/feedback", methods=["GET"])
def list_feedback():
    caller = mw.require_auth()
    mw.require_role(caller, {"Anonymous", "Buyer", "Seller", "PlatformAdmin"})
    order_id = request.args.get("order_id")
    rater_account_id = request.args.get("rater_account_id")
    ratee_account_id = request.args.get("ratee_account_id")
    items = list(db.feedback.values())
    if order_id is not None:
        items = [f for f in items if f["order_id"] == order_id]
    if rater_account_id is not None:
        items = [f for f in items if f["rater_account_id"] == rater_account_id]
    if ratee_account_id is not None:
        items = [f for f in items if f["ratee_account_id"] == ratee_account_id]
    return paginate_list(items, core.ser_feedback)
