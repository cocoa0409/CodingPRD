"""Coupon item adjudication and lot finalization (PRD 3.4, 3.5)."""

from flask import Blueprint

import db
import middleware as mw
import response
import validate
from db import touch, sort_rows
from errors import ApiError
from middleware import ALL_ROLES
from services import calc, domain

bp = Blueprint("adjudication", __name__)


@bp.route("/coupon-items/<iid>", methods=["GET"])
def get_item(iid):
    ctx = mw.authenticate(ALL_ROLES)
    item = mw.fetch("items", iid, "ERR_COUPON_ITEM_NOT_FOUND")
    lot = domain.lot_of_item(item)
    mw.own_retailer(ctx, domain.submission_of_lot(lot)["retailer_id"])
    return response.object_response(item)


@bp.route("/coupon-items", methods=["GET"])
def list_items():
    mw.authenticate(ALL_ROLES)
    limit, offset = mw.pagination()
    lot_id = mw.str_arg("lot_id")
    status = mw.str_arg("status")
    reject_code = mw.str_arg("reject_code")
    duplicate_of = mw.str_arg("duplicate_of_item_id")
    matched_purchase = mw.str_arg("matched_purchase_record_id")
    rows = [
        i
        for i in db.db.items.values()
        if (lot_id is None or i["lot_id"] == lot_id)
        and (status is None or i["status"] == status)
        and (reject_code is None or i["reject_code"] == reject_code)
        and (duplicate_of is None or i["duplicate_of_item_id"] == duplicate_of)
        and (
            matched_purchase is None
            or i["matched_purchase_record_id"] == matched_purchase
        )
    ]
    rows = sort_rows(rows)
    page, total = mw.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.route("/coupon-items/<iid>/adjudicate", methods=["POST"])
def adjudicate(iid):
    mw.authenticate(["FraudAnalyst"])
    item = mw.fetch("items", iid, "ERR_COUPON_ITEM_NOT_FOUND")
    validate.require_no_body(mw.body())
    if item["status"] != "CAPTURED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a CAPTURED item can be adjudicated",
        )
    lot = domain.lot_of_item(item)
    submission = domain.submission_of_lot(lot)
    offer = domain.offer_of_lot(lot)
    domain.adjudicate_item(item, lot, offer, submission)
    domain.recompute_lot_quantities(lot)
    touch(lot)
    domain.recompute_item_face_values(submission)
    touch(submission)
    return response.object_response(item)


@bp.route("/submission-lots/<lid>/finalize", methods=["POST"])
def finalize_lot(lid):
    ctx = mw.authenticate(["FraudAnalyst"])
    lot = mw.fetch("lots", lid, "ERR_LOT_NOT_FOUND")
    validate.require_no_body(mw.body())
    if lot["status"] != "SORTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Only a SORTED lot can be finalized"
        )
    submission = domain.submission_of_lot(lot)
    retailer = domain.retailer_of_submission(submission)
    if retailer["status"] == "SUSPENDED":
        raise ApiError("ERR_RETAILER_SUSPENDED", "Retailer is suspended")
    if lot["captured_item_count"] != lot["sample_size"]:
        raise ApiError(
            "ERR_SAMPLE_INCOMPLETE",
            "Capture is incomplete: %d of %d images"
            % (lot["captured_item_count"], lot["sample_size"]),
        )
    offer = domain.offer_of_lot(lot)
    for item in domain.items_of_lot(lot["id"]):
        if item["status"] == "CAPTURED":
            domain.adjudicate_item(item, lot, offer, submission)
    domain.recompute_lot_quantities(lot)

    if lot["accepted_qty"] >= 1:
        projected = domain.value_lot(lot)
        if offer["accepted_redemption_count"] + projected > offer["max_redemptions"]:
            raise ApiError(
                "ERR_MAX_REDEMPTIONS_EXCEEDED",
                "Offer redemption ceiling would be exceeded",
            )
        lot["status"] = "VALIDATED"
        lot["reject_reason"] = None
        offer["accepted_redemption_count"] = (
            offer["accepted_redemption_count"] + projected
        )
        touch(offer)
    else:
        lot["status"] = "LOT_REJECTED"
        lot["reject_reason"] = "ALL_ITEMS_REJECTED"
        lot["projected_accepted_units"] = 0
        lot["gross_face_value_cents"] = 0
        lot["handling_fee_cents"] = 0
    lot["adjudicated_by_user_id"] = ctx.user_id
    lot["adjudicated_at"] = db.now_iso()
    touch(lot)

    domain.recompute_item_face_values(submission)
    domain.recompute_settled_money(submission)
    domain.recompute_rejected_lot_count(submission)
    touch(submission)
    domain.close_submission_if_ready(submission, rescore_on_total_loss=True)
    return response.object_response(lot)
