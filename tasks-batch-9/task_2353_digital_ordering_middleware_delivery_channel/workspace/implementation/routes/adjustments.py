"""Refunds, fee credits and the channel review loop."""
from flask import Blueprint

import clock
import db
import errors
import middleware as M
import response
import validation
from errors import fail
from routes import common
from services import constants as K
from services import domain, serializers
from services.money import apply_bps

bp = Blueprint("adjustments", __name__)


def _relief_cents(adjustment_type, amount_cents, channel):
    if adjustment_type != "REFUND":
        return 0
    return apply_bps(amount_cents, channel["commission_bps"])


def _check_refund_ceiling(order, adjustment_type, amount_cents, exclude_amount=0):
    if adjustment_type != "REFUND":
        return
    already = order["refunded_total_cents"] - exclude_amount
    if already + amount_cents > order["channel_collected_cents"]:
        fail(errors.ERR_REFUND_EXCEEDS_COLLECTED)


def _apply_acceptance(adjustment, order):
    order["refunded_total_cents"] += adjustment["amount_cents"]
    order["commission_cents"] -= adjustment["commission_relief_cents"]
    order["brand_net_cents"] -= (adjustment["amount_cents"]
                                 - adjustment["commission_relief_cents"])
    db.touch(order)

    adjustment["state"] = "ACCEPTED"
    adjustment["accepted_at"] = clock.now()
    if order["remittance_statement_id"] is not None:
        adjustment["remittance_statement_id"] = order["remittance_statement_id"]
    db.touch(adjustment)

    statement = domain.statement_for_order(order)
    if statement is not None:
        domain.apply_settlement_figures(statement)


# --------------------------------------------------------------- propose ----
@bp.post("/adjustments")
@M.endpoint(M.SETTLEMENT_ANALYST)
def create_adjustment():
    payload = validation.body()
    order_id = validation.req_str(payload, "order_id")
    adjustment_type = validation.req_enum(payload, "adjustment_type", K.ADJUSTMENT_TYPES)
    amount = validation.req_int(payload, "amount_cents", 1)
    reason_code = validation.req_str(payload, "reason_code")
    expected = validation.req_int(payload, "expected_order_version")

    order = common.get_order(order_id)
    if expected != order["version"]:
        fail(errors.ERR_STALE_ORDER_VERSION)
    if order["settlement_status"] == "SETTLED":
        fail(errors.ERR_ORDER_ALREADY_SETTLED)
    _check_refund_ceiling(order, adjustment_type, amount)

    channel = db.channels.get(order["channel_id"])
    adjustment = db.record()
    adjustment.update({
        "order_id": order["id"],
        "channel_id": order["channel_id"],
        "remittance_statement_id": None,
        "adjustment_type": adjustment_type,
        "amount_cents": amount,
        "reason_code": reason_code,
        "state": "DRAFT",
        "revision_round": 0,
        "commission_relief_cents": _relief_cents(adjustment_type, amount, channel),
        "proposed_by_user_id": M.identity().user_id,
        "accepted_at": None,
        "reversed_at": None,
    })
    db.adjustments[adjustment["id"]] = adjustment

    db.touch(order)
    statement = domain.statement_for_order(order)
    if statement is not None:
        domain.recompute_statement_open_adjustments(statement)
    return response.object_response(serializers.adjustment(adjustment), 201)


@bp.get("/adjustments/<adjustment_id>")
@M.endpoint(M.PLATFORM_ADMIN, M.CHANNEL_PARTNER, M.SETTLEMENT_ANALYST)
def read_adjustment(adjustment_id):
    adjustment = common.get_adjustment(adjustment_id)
    M.require_channel_scope(adjustment["channel_id"])
    return response.object_response(serializers.adjustment(adjustment))


@bp.get("/adjustments")
@M.endpoint(M.PLATFORM_ADMIN, M.CHANNEL_PARTNER, M.SETTLEMENT_ANALYST)
def list_adjustments():
    limit, offset = validation.pagination()
    order_id = validation.query_str("order_id")
    channel_id = validation.query_str("channel_id")
    statement_id = validation.query_str("remittance_statement_id")
    state = validation.query_enum("state", K.ADJUSTMENT_STATES)
    adjustment_type = validation.query_enum("adjustment_type", K.ADJUSTMENT_TYPES)

    def keep(rec):
        if order_id is not None and rec["order_id"] != order_id:
            return False
        if channel_id is not None and rec["channel_id"] != channel_id:
            return False
        if statement_id is not None and rec["remittance_statement_id"] != statement_id:
            return False
        if state is not None and rec["state"] != state:
            return False
        if adjustment_type is not None and rec["adjustment_type"] != adjustment_type:
            return False
        return True

    records = db.sorted_records(db.adjustments, keep)
    page, meta = response.paginate(records, limit, offset)
    return response.array_response([serializers.adjustment(r) for r in page], meta)


# ---------------------------------------------------------------- submit ----
@bp.post("/adjustments/<adjustment_id>/submit")
@M.endpoint(M.SETTLEMENT_ANALYST)
def submit_adjustment(adjustment_id):
    adjustment = common.get_adjustment(adjustment_id)
    if adjustment["state"] != "DRAFT":
        fail(errors.ERR_INVALID_ADJUSTMENT_STATE)

    order = db.orders.get(adjustment["order_id"])
    channel = db.channels.get(adjustment["channel_id"])
    if channel is not None and channel["adjustment_review_mode"] == "AUTO_ACCEPT":
        _apply_acceptance(adjustment, order)
        statement = domain.statement_for_order(order) if order else None
        if statement is not None:
            domain.recompute_statement_open_adjustments(statement)
    else:
        adjustment["state"] = "CHANNEL_REVIEW"
        db.touch(adjustment)
        statement = domain.statement_for_order(order) if order else None
        if statement is not None:
            domain.recompute_statement_open_adjustments(statement)
    return response.object_response(serializers.adjustment(adjustment))


@bp.post("/adjustments/<adjustment_id>/request-revision")
@M.endpoint(M.CHANNEL_PARTNER)
def request_revision(adjustment_id):
    payload = validation.body()
    validation.opt_str(payload, "note")
    adjustment = common.get_adjustment(adjustment_id)
    M.require_channel_scope(adjustment["channel_id"])

    if adjustment["state"] != "CHANNEL_REVIEW":
        fail(errors.ERR_INVALID_ADJUSTMENT_STATE)
    if adjustment["revision_round"] >= K.MAX_REVISION_ROUNDS:
        fail(errors.ERR_REVISION_LIMIT_REACHED)

    adjustment["state"] = "REVISION_REQUESTED"
    db.touch(adjustment)
    return response.object_response(serializers.adjustment(adjustment))


@bp.post("/adjustments/<adjustment_id>/revise")
@M.endpoint(M.SETTLEMENT_ANALYST)
def revise_adjustment(adjustment_id):
    payload = validation.body()
    amount = validation.opt_int(payload, "amount_cents", 1)
    reason_code = validation.opt_str(payload, "reason_code")
    adjustment = common.get_adjustment(adjustment_id)
    order = db.orders.get(adjustment["order_id"])

    # The refund ceiling (rank 35) outranks the adjustment state (rank 36).
    if amount is not None and order is not None:
        _check_refund_ceiling(order, adjustment["adjustment_type"], amount)
    if adjustment["state"] != "REVISION_REQUESTED":
        fail(errors.ERR_INVALID_ADJUSTMENT_STATE)

    channel = db.channels.get(adjustment["channel_id"])
    if amount is not None:
        adjustment["amount_cents"] = amount
        adjustment["commission_relief_cents"] = _relief_cents(
            adjustment["adjustment_type"], amount, channel)
    if reason_code is not None:
        adjustment["reason_code"] = reason_code
    adjustment["state"] = "CHANNEL_REVIEW"
    adjustment["revision_round"] += 1
    db.touch(adjustment)
    return response.object_response(serializers.adjustment(adjustment))


@bp.post("/adjustments/<adjustment_id>/accept")
@M.endpoint(M.CHANNEL_PARTNER)
def accept_adjustment(adjustment_id):
    adjustment = common.get_adjustment(adjustment_id)
    M.require_channel_scope(adjustment["channel_id"])
    order = db.orders.get(adjustment["order_id"])

    if order is not None and order["settlement_status"] == "SETTLED":
        fail(errors.ERR_ORDER_ALREADY_SETTLED)
    if adjustment["state"] != "CHANNEL_REVIEW":
        fail(errors.ERR_INVALID_ADJUSTMENT_STATE)

    _apply_acceptance(adjustment, order)
    statement = domain.statement_for_order(order) if order else None
    if statement is not None:
        domain.recompute_statement_open_adjustments(statement)
    return response.object_response(serializers.adjustment(adjustment))


@bp.post("/adjustments/<adjustment_id>/reverse")
@M.endpoint(M.SETTLEMENT_ANALYST)
def reverse_adjustment(adjustment_id):
    payload = validation.body()
    validation.req_str(payload, "reason_code")
    adjustment = common.get_adjustment(adjustment_id)

    if M.identity().user_id == adjustment["proposed_by_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES)
    order = db.orders.get(adjustment["order_id"])
    if order is not None and order["settlement_status"] == "SETTLED":
        fail(errors.ERR_ORDER_ALREADY_SETTLED)
    if adjustment["state"] != "ACCEPTED":
        fail(errors.ERR_INVALID_ADJUSTMENT_STATE)

    adjustment["state"] = "REVERSED"
    adjustment["reversed_at"] = clock.now()
    db.touch(adjustment)

    if order is not None:
        order["refunded_total_cents"] -= adjustment["amount_cents"]
        order["commission_cents"] += adjustment["commission_relief_cents"]
        order["brand_net_cents"] += (adjustment["amount_cents"]
                                     - adjustment["commission_relief_cents"])
        db.touch(order)
        statement = domain.statement_for_order(order)
        if statement is not None:
            domain.apply_settlement_figures(statement)
    return response.object_response(serializers.adjustment(adjustment))
