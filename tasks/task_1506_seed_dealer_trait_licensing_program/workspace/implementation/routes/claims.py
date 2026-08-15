"""ReplantClaim endpoints with segregation of duties and the replacement
order cascade on approval."""

from datetime import timedelta

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_ORDER_LINE_MISMATCH,
    ERR_FIELD_GROWER_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_REPLANT_WINDOW_CLOSED,
    ERR_NO_DELIVERED_UNITS,
)
from middleware import authenticate, check_grower_ownership, GROWER
from response import success_obj, success_list
from routes import make_blueprint
from services import replant_replacement_units, plan_allocation, apply_allocation
from util import body_json, check_shape, pagination_params, paginate, apply_filters, require_fk, exist_body_fks, dt_of, rhu_div

bp = make_blueprint("claims")

READ_ROLES = ["DealerAdmin", "SalesRep", "Grower", "ClaimsAdjuster"]
EVENT_TYPES = ["FROST", "FLOOD", "HAIL", "DROUGHT", "PEST"]
OPEN_CLAIM_STATES = ("FILED", "UNDER_REVIEW", "INFO_REQUESTED")


def _claim_grower_id(claim):
    order = db.get("orders", claim["order_id"])
    return order["grower_id"] if order else None


def _check_segregation(uid, claim):
    if uid == claim["filed_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "claims adjuster must not be the claim filer")


@bp.post("/replant-claims")
def create_claim():
    uid, role = authenticate(["SalesRep", "Grower", "ClaimsAdjuster"])
    body = body_json()
    exist_body_fks(body, {
        "order_id": ("orders", "order"),
        "order_line_id": ("order_lines", "order line"),
        "field_id": ("fields", "field"),
    })
    check_shape(body, {
        "order_id": {"type": "string", "required": True},
        "order_line_id": {"type": "string", "required": True},
        "field_id": {"type": "string", "required": True},
        "event_date": {"type": "datetime", "required": True},
        "event_type": {"type": "enum", "required": True, "values": EVENT_TYPES},
        "acres_affected": {"type": "number", "required": True, "min": 0, "min_exclusive": True},
    })
    order = db.get("orders", body["order_id"])
    line = db.get("order_lines", body["order_line_id"])
    field = db.get("fields", body["field_id"])
    check_grower_ownership(uid, role, order["grower_id"])
    if body["acres_affected"] > field["acres"]:
        raise ApiError(ERR_INVALID_REQUEST, 400, "acres_affected exceeds the field's acres")
    clock = db.now()
    if dt_of(body, "event_date") > clock:
        raise ApiError(ERR_INVALID_REQUEST, 400, "event_date may not lie in the future")
    if line["order_id"] != order["id"]:
        raise ApiError(ERR_ORDER_LINE_MISMATCH, 409, "order_line_id does not belong to order_id")
    if field["grower_id"] != order["grower_id"]:
        raise ApiError(ERR_FIELD_GROWER_MISMATCH, 409, "field_id does not belong to the order's grower")
    program = db.get("programs", order["program_id"])
    deadline = dt_of(body, "event_date") + timedelta(days=program["replant_claim_window_days"])
    if clock > deadline:
        raise ApiError(ERR_REPLANT_WINDOW_CLOSED, 409, "replant claim window has closed")
    if line["delivered_units"] - line["returned_units"] <= 0:
        raise ApiError(ERR_NO_DELIVERED_UNITS, 409, "claimed line has no delivered, unreturned units")
    claim = db.new_entity("replant_claims", {
        "order_id": order["id"],
        "order_line_id": line["id"],
        "field_id": field["id"],
        "event_date": body["event_date"],
        "event_type": body["event_type"],
        "acres_affected": body["acres_affected"],
        "filed_by_user_id": uid,
        "status": "FILED",
        "replacement_order_id": None,
        "decided_by_user_id": None,
        "decided_at": None,
        "denial_reason": None,
    })
    return success_obj(db.public(claim), 201)


@bp.get("/replant-claims/<cid>")
def get_claim(cid):
    uid, role = authenticate(READ_ROLES)
    claim = require_fk("replant_claims", cid, "replant claim")
    if role == GROWER:
        check_grower_ownership(uid, role, _claim_grower_id(claim))
    return success_obj(db.public(claim), 200)


@bp.get("/replant-claims")
def list_claims():
    uid, role = authenticate(READ_ROLES)
    limit, offset = pagination_params()
    items = db.all_of("replant_claims")
    if role == GROWER:
        own_orders = {o["id"] for o in db.all_of("orders") if o["grower_id"] == uid}
        items = [c for c in items if c["order_id"] in own_orders]
    items = apply_filters(items, ["order_id", "order_line_id", "field_id", "replacement_order_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(c) for c in page], limit, offset, total, has_more)


@bp.post("/replant-claims/<cid>/start_review")
def start_review(cid):
    uid, _role = authenticate(["ClaimsAdjuster"])
    claim = require_fk("replant_claims", cid, "replant claim")
    if claim["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a FILED claim can enter review")
    _check_segregation(uid, claim)
    claim["status"] = "UNDER_REVIEW"
    db.touch(claim)
    return success_obj(db.public(claim), 200)


@bp.post("/replant-claims/<cid>/request_info")
def request_info(cid):
    uid, _role = authenticate(["ClaimsAdjuster"])
    claim = require_fk("replant_claims", cid, "replant claim")
    body = body_json()
    check_shape(body, {"note": {"type": "string"}})
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only an UNDER_REVIEW claim can receive an info request")
    _check_segregation(uid, claim)
    claim["status"] = "INFO_REQUESTED"
    db.touch(claim)
    return success_obj(db.public(claim), 200)


@bp.post("/replant-claims/<cid>/provide_info")
def provide_info(cid):
    uid, role = authenticate(["SalesRep", "Grower", "ClaimsAdjuster"])
    claim = require_fk("replant_claims", cid, "replant claim")
    body = body_json()
    check_shape(body, {"note": {"type": "string"}})
    if role == GROWER:
        check_grower_ownership(uid, role, _claim_grower_id(claim))
    if claim["status"] != "INFO_REQUESTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only an INFO_REQUESTED claim can be answered")
    claim["status"] = "UNDER_REVIEW"
    db.touch(claim)
    return success_obj(db.public(claim), 200)


@bp.post("/replant-claims/<cid>/approve")
def approve_claim(cid):
    uid, _role = authenticate(["ClaimsAdjuster"])
    claim = require_fk("replant_claims", cid, "replant claim")
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only an UNDER_REVIEW claim can be approved")
    _check_segregation(uid, claim)
    order = db.get("orders", claim["order_id"])
    line = db.get("order_lines", claim["order_line_id"])
    field = db.get("fields", claim["field_id"])
    program = db.get("programs", order["program_id"])
    variety = db.get("varieties", line["variety_id"])
    units = replant_replacement_units(line, field, claim["acres_affected"])
    # Build the replacement order + line in memory; allocation must succeed
    # for every replacement line before anything is committed.
    locked_bps = program["replant_replacement_discount_bps"]
    disc_unit = rhu_div(variety["base_price_cents_per_unit"] * (10000 - locked_bps), 10000)
    pending_line = {
        "variety_id": variety["id"],
        "treatment_option_id": None,
        "units": units,
    }
    allocation = plan_allocation([pending_line])
    # Commit: replacement order directly CONFIRMED, bypassing DRAFT.
    replacement = db.new_entity("orders", {
        "grower_id": order["grower_id"],
        "program_id": order["program_id"],
        "recommendation_id": None,
        "is_replacement": True,
        "status": "CONFIRMED",
        "payment_status": "UNPAID",
        "fulfillment_status": "NONE",
        "confirmed_at": db.fmt_ts(db.now()),
        "locked_discount_bps": locked_bps,
        "total_units": units,
        "gross_amount_cents": disc_unit * units,
        "rebate_bps_applied": 0,
        "rebate_amount_cents": 0,
        "prepay_discount_cents": 0,
        "net_amount_cents": disc_unit * units,
        "prepaid_amount_cents": 0,
        "paid_amount_cents": 0,
    })
    new_line = db.new_entity("order_lines", {
        "order_id": replacement["id"],
        "variety_id": variety["id"],
        "treatment_option_id": None,
        "units": units,
        "unit_price_cents": variety["base_price_cents_per_unit"],
        "discounted_unit_price_cents": disc_unit,
        "line_total_cents": disc_unit * units,
        "inventory_lot_id": None,
        "reserved_units": 0,
        "delivered_units": 0,
        "returned_units": 0,
    })
    apply_allocation([(new_line, allocation[0][1])])
    if replacement["net_amount_cents"] == 0:
        replacement["payment_status"] = "SETTLED"
    db.touch(replacement)
    claim["replacement_order_id"] = replacement["id"]
    claim["status"] = "APPROVED"
    claim["decided_by_user_id"] = uid
    claim["decided_at"] = db.fmt_ts(db.now())
    db.touch(claim)
    return success_obj(db.public(claim), 200)


@bp.post("/replant-claims/<cid>/deny")
def deny_claim(cid):
    uid, _role = authenticate(["ClaimsAdjuster"])
    claim = require_fk("replant_claims", cid, "replant claim")
    body = body_json()
    check_shape(body, {"denial_reason": {"type": "string", "required": True}})
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only an UNDER_REVIEW claim can be denied")
    _check_segregation(uid, claim)
    claim["status"] = "DENIED"
    claim["denial_reason"] = body["denial_reason"]
    claim["decided_by_user_id"] = uid
    claim["decided_at"] = db.fmt_ts(db.now())
    db.touch(claim)
    return success_obj(db.public(claim), 200)


@bp.post("/replant-claims/<cid>/withdraw")
def withdraw_claim(cid):
    uid, role = authenticate(["SalesRep", "Grower"])
    claim = require_fk("replant_claims", cid, "replant claim")
    if role == GROWER:
        check_grower_ownership(uid, role, _claim_grower_id(claim))
    if claim["status"] not in OPEN_CLAIM_STATES:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "claim cannot be withdrawn from its current state")
    claim["status"] = "WITHDRAWN"
    db.touch(claim)
    return success_obj(db.public(claim), 200)
