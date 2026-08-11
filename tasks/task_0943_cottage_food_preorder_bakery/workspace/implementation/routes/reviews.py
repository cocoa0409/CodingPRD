"""Reviews: submission inside the window, the baker response, moderation."""

from datetime import timedelta

from flask import Blueprint

import config
from db import DB, base_record, touch
from errors import ApiError
from ladder import endpoint
from response import created, ok
from routes.common import list_endpoint
from serialize import dump
from services import rollup
from services.gates import require_state
from tsutil import lt, ts_shift

bp = Blueprint("reviews", __name__)

ADMIN = config.ROLE_ADMIN
BAKER = config.ROLE_BAKER
CUSTOMER = config.ROLE_CUSTOMER


def _baker_of_review(review):
    order = DB.get("orders", review.get("order_id"))
    window = DB.get("offer_windows", (order or {}).get("offer_window_id"))
    if window is not None:
        return window.get("baker_id")
    item = DB.get("menu_items", review.get("menu_item_id"))
    return (item or {}).get("baker_id")


@bp.post("/bakery/reviews")
@endpoint(roles=[CUSTOMER])
def create_review(ctx):
    # CARVE-OUT: rung 15 never applies -- reviews stay reachable while the
    # operator's permit is suspended.
    fks = ctx.body_fks(required=("menu_item_id", "order_id"))       # rungs 9, 10
    item = fks["menu_item_id"]
    order = fks["order_id"]
    if item is None:
        raise ApiError("ERR_VALIDATION", "menu_item_id is required.")
    if order is None:
        raise ApiError("ERR_VALIDATION", "order_id is required.")
    ctx.ownership(customer_id=order.get("customer_id"))             # rung 11
    rating = ctx.req_int("rating", minimum=config.RATING_SCALE_MIN,  # rung 13
                         maximum=config.RATING_SCALE_MAX)
    body = ctx.req_str("body")
    require_state(order.get("order_status"), ("FULFILLED",), "order_status")
    for existing in DB.coll("reviews").values():                     # rung 37
        if existing.get("order_id") == order["id"]:
            raise ApiError("ERR_DUPLICATE_REVIEW",
                           "A review already exists for this order.")
    # rung 41.  Adjudication of friction 5: the latch is ACTIVELY SET on the
    # first observation of a closed window, and the rung then rejects on the
    # strength of the latch OR the clock.  Under the passive reading nothing in
    # the system ever writes review_window_closed_latch, so the value `true`
    # would be unreachable for a declared field; setting it on observation keeps
    # that value reachable and costs nothing, since the request is rejected
    # either way.  Only this rung writes it -- plain reads stay side-effect free
    # per PRD 2.11.
    closes = order.get("review_window_closes_at")
    if order.get("review_window_closed_latch") or closes is None or not lt(ctx.now, closes):
        if not order.get("review_window_closed_latch"):
            order["review_window_closed_latch"] = True
            touch(order, ctx.now)
        raise ApiError("ERR_REVIEW_WINDOW_CLOSED", "The review window has closed.")

    has_refund = any(m.get("order_id") == order["id"]
                     and m.get("movement_kind") == "REFUND"
                     for m in DB.coll("money_movements").values())
    rec = base_record(ctx.now)
    rec.update({
        "order_id": order["id"],
        "menu_item_id": item["id"],
        "customer_id": order.get("customer_id"),
        "rating": rating,
        "body": body,
        "review_status": "SUBMITTED",
        "baker_response": None,
        "responded_at": None,
        "shortfall_affected": bool(order.get("shortfall_flag")) or has_refund,
        "counts_toward_rollup": True,
    })
    DB.coll("reviews")[rec["id"]] = rec
    rollup.recompute(item)
    touch(item, ctx.now)
    return created(dump("reviews", rec))


@bp.post("/bakery/reviews/<review_id>/respond")
@endpoint(roles=[BAKER], path=("review_id",))
def respond(ctx):
    review = ctx.p["review_id"]
    ctx.ownership(baker_id=_baker_of_review(review))                # rung 12
    baker_response = ctx.req_str("baker_response")                   # rung 13
    require_state(review.get("review_status"), ("SUBMITTED",), "review_status")
    deadline = ts_shift(review["created_at"],                        # rung 42
                        timedelta(days=config.BAKER_RESPONSE_WINDOW_DAYS))
    if not lt(ctx.now, deadline):
        raise ApiError("ERR_RESPONSE_WINDOW_CLOSED",
                       "The baker response window has closed.")
    review["review_status"] = "RESPONDED"
    review["baker_response"] = baker_response
    review["responded_at"] = ctx.now
    touch(review, ctx.now)
    rollup.recompute(DB.get("menu_items", review.get("menu_item_id")))
    return ok(dump("reviews", review))


@bp.post("/bakery/reviews/<review_id>/moderation")
@endpoint(roles=[ADMIN], path=("review_id",))
def moderate(ctx):
    review = ctx.p["review_id"]
    if ctx.body.get("to_status") is None:                            # rung 13
        raise ApiError("ERR_VALIDATION", "to_status is required.")
    to_status = ctx.enum("to_status", "review_status")               # rung 14
    current = review.get("review_status")
    if to_status == "HIDDEN":                                       # rung 19
        require_state(current, ("SUBMITTED", "RESPONDED"), "review_status")
        review["counts_toward_rollup"] = False
    elif to_status == "SUBMITTED":
        require_state(current, ("HIDDEN",), "review_status")
        # the baker_response, if any, is preserved on unhide
        review["counts_toward_rollup"] = True
    else:
        raise ApiError("ERR_INVALID_STATE",
                       "%s is not reachable through this capability." % to_status)
    review["review_status"] = to_status
    touch(review, ctx.now)
    rollup.recompute(DB.get("menu_items", review.get("menu_item_id")))
    return ok(dump("reviews", review))


@bp.get("/bakery/reviews/<review_id>")
@endpoint(roles=[CUSTOMER, BAKER, ADMIN], path=("review_id",))
def read_review(ctx):
    review = ctx.p["review_id"]
    ctx.ownership(customer_id=review.get("customer_id"),
                  baker_id=_baker_of_review(review))
    return ok(dump("reviews", review))


@bp.get("/bakery/reviews")
@endpoint(roles=[CUSTOMER, BAKER, ADMIN], list_ep=True)
def list_reviews(ctx):
    return list_endpoint(ctx, "reviews", {
        "order_id": "order_id",
        "menu_item_id": "menu_item_id",
        "customer_id": "customer_id",
        "review_status": "review_status",
    })
