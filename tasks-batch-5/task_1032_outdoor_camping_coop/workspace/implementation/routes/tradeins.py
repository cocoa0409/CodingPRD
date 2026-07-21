from flask import Blueprint, request

import core
from core import (
    db, ok, get_body, req_str, req_int, req_enum, fetch,
    authenticate, authorize, require_owner, new_common, touch, serialize,
    sorted_by_created, paginate, round_half_up, ApiError,
    INSTANT_CREDIT_PCT, CONSIGNMENT_MEMBER_PCT, credit_wallet,
)
from decimal import Decimal

bp = Blueprint("tradeins", __name__)

CONDITIONS = {"LIKE_NEW", "GOOD", "WORN"}
PAYOUT_METHODS = {"INSTANT_CREDIT", "CONSIGNMENT"}
ACTIONS = {"ACCEPT", "COUNTER", "REJECT"}


@bp.route("/coop/trade-ins", methods=["POST"])
def submit_trade_in():
    uid, role = authenticate()
    authorize(role, {"Member"})
    data = get_body()
    member_id = req_str(data, "member_id")
    gear_sku_id = req_str(data, "gear_sku_id")
    described_condition = req_enum(data, "described_condition", CONDITIONS)
    payout_method = req_enum(data, "payout_method", PAYOUT_METHODS)

    require_owner(role, uid, member_id)
    fetch("members", member_id)
    fetch("gear_skus", gear_sku_id)

    ti = new_common()
    ti.update({
        "member_id": member_id,
        "gear_sku_id": gear_sku_id,
        "described_condition": described_condition,
        "payout_method": payout_method,
        "status": "SUBMITTED",
        "appraised_value_cents": None,
        "member_counter_cents": None,
        "instant_credit_cents": None,
        "consignment_estimate_cents": None,
        "resale_price_cents": None,
        "payout_cents": None,
    })
    db.trade_ins[ti["id"]] = ti
    return ok(serialize(ti), status=201)


@bp.route("/coop/trade-ins/<tid>", methods=["GET"])
def get_trade_in(tid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    ti = fetch("trade_ins", tid)
    require_owner(role, uid, ti["member_id"])
    return ok(serialize(ti))


@bp.route("/coop/trade-ins", methods=["GET"])
def list_trade_ins():
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    member_id = request.args.get("member_id")
    if role == "Member":
        if member_id is not None and member_id != uid:
            raise ApiError("ERR_UNAUTHORIZED", "Members may only list their own trade-ins")
        member_id = uid
    gear_sku_id = request.args.get("gear_sku_id")
    status = request.args.get("status")
    items = list(db.trade_ins.values())
    if member_id is not None:
        items = [t for t in items if t["member_id"] == member_id]
    if gear_sku_id is not None:
        items = [t for t in items if t["gear_sku_id"] == gear_sku_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok(page, is_array=True, pagination=meta)


@bp.route("/coop/trade-ins/<tid>/appraise", methods=["POST"])
def appraise_trade_in(tid):
    uid, role = authenticate()
    authorize(role, {"StoreStaff"})
    data = get_body()
    appraised = req_int(data, "appraised_value_cents", min_value=0)
    ti = fetch("trade_ins", tid)
    if ti["status"] not in ("SUBMITTED", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE", "Trade-in is not appraisable in its current state")

    ti["appraised_value_cents"] = appraised
    ti["instant_credit_cents"] = round_half_up(Decimal(appraised) * INSTANT_CREDIT_PCT)
    ti["consignment_estimate_cents"] = round_half_up(Decimal(appraised) * CONSIGNMENT_MEMBER_PCT)
    ti["status"] = "OFFERED"
    touch(ti)
    return ok(serialize(ti))


@bp.route("/coop/trade-ins/<tid>/respond", methods=["POST"])
def respond_trade_in(tid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    data = get_body()
    action = req_enum(data, "action", ACTIONS)  # bad/missing enum -> ERR_VALIDATION
    ti = fetch("trade_ins", tid)
    require_owner(role, uid, ti["member_id"])

    if ti["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_OFFER_RESPONSE", "Trade-in is not in an OFFERED state")

    if action == "COUNTER":
        cc = data.get("counter_cents")
        if cc is None:
            raise ApiError("ERR_INVALID_OFFER_RESPONSE", "COUNTER requires counter_cents")
        if not isinstance(cc, int) or isinstance(cc, bool):
            raise ApiError("ERR_VALIDATION", "'counter_cents' must be an integer")
        ti["member_counter_cents"] = cc
        ti["status"] = "COUNTERED"
        touch(ti)
        return ok(serialize(ti))

    if action == "REJECT":
        ti["status"] = "REJECTED"
        touch(ti)
        return ok(serialize(ti))

    # ACCEPT
    member = fetch("members", ti["member_id"])
    if ti["payout_method"] == "INSTANT_CREDIT":
        ti["payout_cents"] = ti["instant_credit_cents"]
        ti["status"] = "ACCEPTED"
        touch(ti)
        credit_wallet(member, ti["payout_cents"])
    else:  # CONSIGNMENT -> advance immediately to LISTED, no wallet change yet
        ti["status"] = "LISTED"
        touch(ti)
    return ok(serialize(ti))


@bp.route("/coop/trade-ins/<tid>/sell", methods=["POST"])
def sell_trade_in(tid):
    uid, role = authenticate()
    authorize(role, {"StoreStaff"})
    data = get_body()
    resale_price = req_int(data, "resale_price_cents", min_value=0)
    ti = fetch("trade_ins", tid)
    if ti["status"] != "LISTED" or ti["payout_method"] != "CONSIGNMENT":
        raise ApiError("ERR_INVALID_STATE", "Trade-in is not a LISTED consignment")

    ti["resale_price_cents"] = resale_price
    ti["payout_cents"] = round_half_up(Decimal(resale_price) * CONSIGNMENT_MEMBER_PCT)
    ti["status"] = "SOLD"
    touch(ti)
    member = fetch("members", ti["member_id"])
    credit_wallet(member, ti["payout_cents"])
    return ok(serialize(ti))
