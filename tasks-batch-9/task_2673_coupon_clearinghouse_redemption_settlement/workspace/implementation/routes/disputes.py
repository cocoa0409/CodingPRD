"""Dispute lifecycle endpoints (PRD 3.7)."""

from flask import Blueprint

import db
import middleware as mw
import response
import validate
from db import touch, sort_rows
from errors import ApiError
from services import calc, domain

bp = Blueprint("disputes", __name__)

DISPUTE_ROLES = [
    "Manufacturer",
    "Retailer",
    "FraudAnalyst",
    "SettlementOfficer",
    "ClearinghouseAdmin",
]

DISPUTE_SPEC = {
    "lot_id": {"type": "string", "required": True, "min_len": 1},
    "reason_code": {
        "type": "enum",
        "required": True,
        "values": [
            "WRONG_EXPIRY_CALL",
            "IMAGE_QUALITY",
            "POS_DATA_LATE",
            "DUPLICATE_MISMATCH",
        ],
    },
    "narrative": {"type": "string", "required": True, "min_len": 1, "max_len": 1000},
}


@bp.route("/disputes", methods=["POST"])
def file_dispute():
    ctx = mw.authenticate(["Retailer"])
    values = validate.parse(mw.body(), DISPUTE_SPEC)
    lot = mw.fetch("lots", values["lot_id"], "ERR_LOT_NOT_FOUND")
    submission = domain.submission_of_lot(lot)
    mw.own_retailer(ctx, submission["retailer_id"])
    if lot["status"] != "LOT_REJECTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a LOT_REJECTED lot can be appealed",
        )
    retailer = domain.retailer_of_submission(submission)
    if retailer["status"] == "SUSPENDED":
        raise ApiError("ERR_RETAILER_SUSPENDED", "Retailer is suspended")
    offer = domain.offer_of_lot(lot)
    manufacturer = db.db.manufacturers[offer["manufacturer_id"]]
    anchor = db.parse_instant(lot["adjudicated_at"])
    if anchor is None:
        raise ApiError(
            "ERR_DISPUTE_WINDOW_CLOSED", "The lot has no adjudication date to appeal"
        )
    deadline = db.add_days(anchor.date(), manufacturer["dispute_window_days"])
    if db.today() > deadline:
        raise ApiError(
            "ERR_DISPUTE_WINDOW_CLOSED", "The dispute window has closed"
        )
    claimed = 0
    face = offer["face_value_cents"]
    for item in domain.items_of_lot(lot["id"]):
        if item["status"] in calc.REJECTED_STATUSES:
            claimed += face * item["claimed_units"]
    row = db.base_row()
    row.update(
        {
            "lot_id": lot["id"],
            "retailer_id": submission["retailer_id"],
            "reason_code": values["reason_code"],
            "narrative": values["narrative"],
            "claimed_face_value_cents": claimed,
            "info_request_count": 0,
            "status": "UNDER_REVIEW",
            "resolution_note": None,
            "resolved_by_user_id": None,
            "filed_at": db.now_iso(),
        }
    )
    db.db.disputes[row["id"]] = row
    lot["status"] = "DISPUTED"
    touch(lot)
    domain.hold_statements_for_dispute(submission)
    return response.object_response(row, 201)


@bp.route("/disputes/<did>", methods=["GET"])
def get_dispute(did):
    ctx = mw.authenticate(DISPUTE_ROLES)
    row = mw.fetch("disputes", did, "ERR_DISPUTE_NOT_FOUND")
    mw.own_retailer(ctx, row["retailer_id"])
    return response.object_response(row)


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    mw.authenticate(DISPUTE_ROLES)
    limit, offset = mw.pagination()
    lot_id = mw.str_arg("lot_id")
    retailer_id = mw.str_arg("retailer_id")
    status = mw.str_arg("status")
    rows = [
        d
        for d in db.db.disputes.values()
        if (lot_id is None or d["lot_id"] == lot_id)
        and (retailer_id is None or d["retailer_id"] == retailer_id)
        and (status is None or d["status"] == status)
    ]
    rows = sort_rows(rows)
    page, total = mw.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.route("/disputes/<did>/request-info", methods=["POST"])
def request_info(did):
    mw.authenticate(["FraudAnalyst"])
    dispute = mw.fetch("disputes", did, "ERR_DISPUTE_NOT_FOUND")
    validate.parse(
        mw.body(),
        {
            "info_request_note": {
                "type": "string",
                "required": True,
                "min_len": 1,
                "max_len": 1000,
            }
        },
    )
    if dispute["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only an UNDER_REVIEW dispute can request information",
        )
    if dispute["info_request_count"] >= calc.MAX_INFO_ROUNDS:
        raise ApiError(
            "ERR_INFO_ROUND_LIMIT", "The information-request limit has been reached"
        )
    dispute["status"] = "INFO_REQUESTED"
    dispute["info_request_count"] = dispute["info_request_count"] + 1
    touch(dispute)
    return response.object_response(dispute)


@bp.route("/disputes/<did>/resubmit", methods=["POST"])
def resubmit_dispute(did):
    ctx = mw.authenticate(["Retailer"])
    dispute = mw.fetch("disputes", did, "ERR_DISPUTE_NOT_FOUND")
    mw.own_retailer(ctx, dispute["retailer_id"])
    values = validate.parse(
        mw.body(),
        {
            "narrative": {
                "type": "string",
                "required": True,
                "min_len": 1,
                "max_len": 1000,
            }
        },
    )
    if dispute["status"] != "INFO_REQUESTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only an INFO_REQUESTED dispute can be resubmitted",
        )
    dispute["narrative"] = dispute["narrative"] + "\n" + values["narrative"]
    dispute["status"] = "UNDER_REVIEW"
    touch(dispute)
    return response.object_response(dispute)


@bp.route("/disputes/<did>/resolve", methods=["POST"])
def resolve_dispute(did):
    ctx = mw.authenticate(["FraudAnalyst"])
    dispute = mw.fetch("disputes", did, "ERR_DISPUTE_NOT_FOUND")
    values = validate.parse(
        mw.body(),
        {
            "outcome": {
                "type": "enum",
                "required": True,
                "values": ["UPHELD", "OVERTURNED"],
            },
            "resolution_note": {
                "type": "string",
                "required": True,
                "min_len": 1,
                "max_len": 1000,
            },
        },
    )
    if dispute["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only an UNDER_REVIEW dispute can be resolved",
        )
    lot = db.db.lots[dispute["lot_id"]]
    if ctx.user_id == lot["adjudicated_by_user_id"]:
        raise ApiError(
            "ERR_SOD_VIOLATION",
            "The analyst who adjudicated the lot may not resolve its appeal",
        )
    submission = domain.submission_of_lot(lot)
    if values["outcome"] == "UPHELD":
        dispute["status"] = "UPHELD"
        lot["status"] = "LOT_REJECTED"
        lot["reject_reason"] = "DISPUTE_UPHELD"
        touch(lot)
    else:
        dispute["status"] = "OVERTURNED"
        offer = domain.offer_of_lot(lot)
        for item in domain.items_of_lot(lot["id"]):
            if item["status"] in calc.REJECTED_STATUSES:
                item["status"] = "REINSTATED"
                item["reject_code"] = None
                item["duplicate_of_item_id"] = None
                touch(item)
        previous_units = lot["projected_accepted_units"]
        domain.recompute_lot_quantities(lot)
        projected = domain.value_lot(lot)
        lot["status"] = "REINSTATED"
        lot["reject_reason"] = None
        touch(lot)
        newly_cleared = projected - previous_units
        if newly_cleared:
            offer["accepted_redemption_count"] = (
                offer["accepted_redemption_count"] + newly_cleared
            )
            touch(offer)
        domain.recompute_item_face_values(submission)
        domain.recompute_settled_money(submission)
        domain.recompute_rejected_lot_count(submission)
        touch(submission)
    dispute["resolution_note"] = values["resolution_note"]
    dispute["resolved_by_user_id"] = ctx.user_id
    touch(dispute)
    return response.object_response(dispute)
