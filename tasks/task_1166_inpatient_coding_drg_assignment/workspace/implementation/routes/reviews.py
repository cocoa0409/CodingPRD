"""PostPaymentReview and RebillRequest endpoints (PRD §3.9)."""
from flask import Blueprint, request

from db import now, sort_default, stamp_new, store, touch
from errors import (ERR_BILL_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_REBILL_DELTA_MISMATCH, ERR_REBILL_NOT_FOUND,
                    ERR_REVIEW_NOT_FOUND, ERR_SEGREGATION_OF_DUTIES,
                    ERR_STALE_VERSION, ERR_TIMELY_FILING_EXPIRED, fail)
from middleware import ALL_ROLES, require_roles
from response import ok_obj, paginate
from services.calc import timely_filing_deadline
from services.core import ser_rebill, ser_review
from validators import body, has, req_int, req_str

bp = Blueprint("reviews", __name__)


def get_review_or_404(review_id):
    r = store.reviews.get(review_id)
    if r is None:
        fail(404, ERR_REVIEW_NOT_FOUND,
             f"PostPaymentReview {review_id} does not exist")
    return r


def get_rebill_or_404(rebill_id):
    r = store.rebills.get(rebill_id)
    if r is None:
        fail(404, ERR_REBILL_NOT_FOUND, f"RebillRequest {rebill_id} does not exist")
    return r


# ---------------- PostPaymentReview ----------------

@bp.route("/bills/<id>/post-payment-reviews", methods=["POST"])
def create_review(id):
    require_roles("BillingClerk")
    bill = store.bills.get(id)
    if bill is None:
        fail(404, ERR_BILL_NOT_FOUND, f"Bill {id} does not exist")
    if bill["status"] != "PAID":
        fail(409, ERR_INVALID_STATE,
             f"Cannot open a post-payment review on a bill in state {bill['status']}")
    b = body()
    payer_ref = req_str(b, "payer_ref")
    claimed = req_int(b, "claimed_delta_cents")
    review = stamp_new({
        "bill_id": bill["id"],
        "payer_ref": payer_ref,
        "claimed_delta_cents": claimed,
        "status": "OPEN",
    })
    store.reviews[review["id"]] = review
    bill["status"] = "POST_PAYMENT_REVIEW"  # bill version bumps via touch
    touch(bill)
    return ok_obj(ser_review(review), 201)


@bp.route("/post-payment-reviews/<id>", methods=["GET"])
def get_review(id):
    require_roles(*ALL_ROLES)
    return ok_obj(ser_review(get_review_or_404(id)), 200)


@bp.route("/post-payment-reviews", methods=["GET"])
def list_reviews():
    require_roles(*ALL_ROLES)
    items = list(store.reviews.values())
    bill_id = request.args.get("bill_id")
    if bill_id is not None:
        items = [r for r in items if r["bill_id"] == bill_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate([ser_review(r) for r in sort_default(items)])


@bp.route("/post-payment-reviews/<id>/close", methods=["POST"])
def close_review(id):
    require_roles("BillingClerk")
    review = get_review_or_404(id)
    if review["status"] != "OPEN":
        fail(409, ERR_INVALID_STATE,
             f"Cannot close a review in state {review['status']}")
    review["status"] = "CLOSED_NO_CHANGE"
    touch(review)
    bill = store.bills[review["bill_id"]]
    if bill["status"] == "POST_PAYMENT_REVIEW":
        bill["status"] = "PAID"
        touch(bill)
    return ok_obj(ser_review(review), 200)


# ---------------- RebillRequest ----------------

@bp.route("/rebill-requests", methods=["POST"])
def create_rebill():
    uid, _ = require_roles("BillingClerk")
    b = body()
    review = None
    if has(b, "review_id"):
        review = store.reviews.get(b["review_id"])
        if review is None:
            fail(404, ERR_REVIEW_NOT_FOUND,
                 f"PostPaymentReview {b['review_id']} does not exist")
    if review is None:
        fail(400, ERR_INVALID_REQUEST, "review_id is required")
    if review["status"] != "OPEN":
        fail(409, ERR_INVALID_STATE,
             f"Cannot file a rebill against a review in state {review['status']}")
    bill = store.bills[review["bill_id"]]
    # OCC tier: stale bill version
    if has(b, "expected_bill_version"):
        expected = req_int(b, "expected_bill_version")
        if expected != bill["version"]:
            fail(412, ERR_STALE_VERSION,
                 "expected_bill_version does not match the bill's current version")
    else:
        fail(400, ERR_INVALID_REQUEST, "expected_bill_version is required")
    delta = req_int(b, "delta_cents")
    # temporal tier: timely filing (exactly at the deadline is permitted)
    if bill["paid_at"] is not None and now() > timely_filing_deadline(bill["paid_at"]):
        fail(422, ERR_TIMELY_FILING_EXPIRED,
             "Rebill is past the timely-filing window (paid_at + 120 days)")
    # fiscal tier
    if delta != review["claimed_delta_cents"]:
        fail(422, ERR_REBILL_DELTA_MISMATCH,
             "delta_cents must equal the review's claimed_delta_cents")
    rebill = stamp_new({
        "review_id": review["id"],
        "delta_cents": delta,
        "requested_by": uid,
        "decided_by": None,
        "status": "PENDING",
    })
    store.rebills[rebill["id"]] = rebill
    review["status"] = "CLOSED_REBILL"
    touch(review)
    bill["status"] = "REBILL_REQUIRED"
    touch(bill)
    return ok_obj(ser_rebill(rebill), 201)


@bp.route("/rebill-requests/<id>", methods=["GET"])
def get_rebill(id):
    require_roles(*ALL_ROLES)
    return ok_obj(ser_rebill(get_rebill_or_404(id)), 200)


@bp.route("/rebill-requests", methods=["GET"])
def list_rebills():
    require_roles(*ALL_ROLES)
    items = list(store.rebills.values())
    review_id = request.args.get("review_id")
    if review_id is not None:
        items = [r for r in items if r["review_id"] == review_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate([ser_rebill(r) for r in sort_default(items)])


@bp.route("/rebill-requests/<id>/approve", methods=["POST"])
def approve_rebill(id):
    uid, _ = require_roles("ComplianceOfficer")
    rebill = get_rebill_or_404(id)
    if rebill["status"] != "PENDING":
        fail(409, ERR_INVALID_STATE,
             f"Cannot approve a rebill request in state {rebill['status']}")
    if uid == rebill["requested_by"]:
        fail(403, ERR_SEGREGATION_OF_DUTIES,
             "The approver must differ from the rebill requester")
    review = store.reviews[rebill["review_id"]]
    bill = store.bills[review["bill_id"]]
    rebill["status"] = "APPROVED"
    rebill["decided_by"] = uid
    touch(rebill)
    bill["status"] = "REBILLED"
    bill["net_receivable_cents"] = (bill["billed_amount_cents"]
                                    - bill["paid_amount_cents"]
                                    + rebill["delta_cents"])
    touch(bill)
    return ok_obj(ser_rebill(rebill), 200)


@bp.route("/rebill-requests/<id>/cancel", methods=["POST"])
def cancel_rebill(id):
    uid, _ = require_roles("ComplianceOfficer")
    rebill = get_rebill_or_404(id)
    if rebill["status"] != "PENDING":
        fail(409, ERR_INVALID_STATE,
             f"Cannot cancel a rebill request in state {rebill['status']}")
    review = store.reviews[rebill["review_id"]]
    bill = store.bills[review["bill_id"]]
    rebill["status"] = "CANCELLED"
    rebill["decided_by"] = uid
    touch(rebill)
    bill["status"] = "PAID"
    bill["net_receivable_cents"] = (bill["billed_amount_cents"]
                                    - bill["paid_amount_cents"])
    touch(bill)
    return ok_obj(ser_rebill(rebill), 200)
