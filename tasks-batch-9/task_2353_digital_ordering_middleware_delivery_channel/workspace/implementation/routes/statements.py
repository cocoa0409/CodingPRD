"""Remittance statements: assignment, reconciliation, dispute and settlement."""
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

bp = Blueprint("statements", __name__)


@bp.post("/remittance-statements")
@M.endpoint(M.SETTLEMENT_ANALYST)
def create_statement():
    payload = validation.body()
    channel_id = validation.req_str(payload, "channel_id")
    period_start = validation.req_datetime(payload, "period_start")
    period_end = validation.req_datetime(payload, "period_end")
    channel = common.get_channel(channel_id)

    if not (period_start < period_end) or period_end > clock.now():
        fail(errors.ERR_INVALID_PERIOD)

    statement = db.record()
    statement.update({
        "channel_id": channel["id"],
        "period_start": period_start,
        "period_end": period_end,
        "state": "OPEN",
        "order_count": 0,
        "gross_sales_cents": 0,
        "adjustment_total_cents": 0,
        "tier_base_cents": 0,
        "tier": "TIER_1",
        "commission_cents": 0,
        "rebate_cents": 0,
        "net_payable_cents": 0,
        "open_adjustment_count": 0,
        "reconciled_by_user_id": None,
        "settled_at": None,
    })
    db.statements[statement["id"]] = statement
    return response.object_response(serializers.statement(statement), 201)


@bp.get("/remittance-statements/<statement_id>")
@M.endpoint(M.PLATFORM_ADMIN, M.CHANNEL_PARTNER, M.SETTLEMENT_ANALYST)
def read_statement(statement_id):
    statement = common.get_statement(statement_id)
    M.require_channel_scope(statement["channel_id"])
    return response.object_response(serializers.statement(statement))


@bp.get("/remittance-statements")
@M.endpoint(M.PLATFORM_ADMIN, M.CHANNEL_PARTNER, M.SETTLEMENT_ANALYST)
def list_statements():
    limit, offset = validation.pagination()
    channel_id = validation.query_str("channel_id")
    state = validation.query_enum("state", K.STATEMENT_STATES)

    def keep(rec):
        if channel_id is not None and rec["channel_id"] != channel_id:
            return False
        if state is not None and rec["state"] != state:
            return False
        return True

    records = db.sorted_records(db.statements, keep)
    page, meta = response.paginate(records, limit, offset)
    return response.array_response([serializers.statement(r) for r in page], meta)


@bp.post("/remittance-statements/<statement_id>/assign-orders")
@M.endpoint(M.SETTLEMENT_ANALYST)
def assign_orders(statement_id):
    payload = validation.body()
    order_ids = validation.req_str_list(payload, "order_ids")
    statement = common.get_statement(statement_id)
    orders = [common.get_order(oid) for oid in order_ids]

    if statement["state"] not in ("OPEN", "DISPUTED"):
        fail(errors.ERR_INVALID_STATEMENT_STATE)

    for order in orders:
        if order["channel_id"] != statement["channel_id"]:
            fail(errors.ERR_ORDER_NOT_ELIGIBLE)
        if not (statement["period_start"] <= order["created_at"] < statement["period_end"]):
            fail(errors.ERR_ORDER_NOT_ELIGIBLE)
        if order["fulfillment_status"] not in K.STATEMENT_ELIGIBLE_FULFILLMENT:
            fail(errors.ERR_ORDER_NOT_ELIGIBLE)
    for order in orders:
        if order["settlement_status"] != "SETTLEABLE":
            fail(errors.ERR_ORDER_ALREADY_ASSIGNED)

    for order in orders:
        order["settlement_status"] = "STATEMENT_ASSIGNED"
        order["remittance_statement_id"] = statement["id"]
        db.touch(order)
        for adjustment in db.adjustments.values():
            if adjustment["order_id"] == order["id"] and adjustment["state"] == "ACCEPTED":
                if adjustment["remittance_statement_id"] != statement["id"]:
                    adjustment["remittance_statement_id"] = statement["id"]
                    db.touch(adjustment)

    domain.apply_settlement_figures(statement)
    return response.object_response(serializers.statement(statement))


@bp.get("/remittance-statements/<statement_id>/preview")
@M.endpoint(M.PLATFORM_ADMIN, M.CHANNEL_PARTNER, M.SETTLEMENT_ANALYST)
def preview_statement(statement_id):
    statement = common.get_statement(statement_id)
    M.require_channel_scope(statement["channel_id"])
    channel = db.channels.get(statement["channel_id"])
    figures = domain.settlement_figures(statement, channel)
    data = {
        "statement_id": statement["id"],
        "settlement_mode": channel["settlement_mode"],
        "gross_sales_cents": figures["gross_sales_cents"],
        "adjustment_total_cents": figures["adjustment_total_cents"],
        "tier_base_cents": figures["tier_base_cents"],
        "tier": figures["tier"],
        "effective_commission_bps": figures["effective_commission_bps"],
        "commission_cents": figures["commission_cents"],
        "rebate_cents": figures["rebate_cents"],
        "net_payable_cents": figures["net_payable_cents"],
        "gross_mode_net_payable_cents": figures["gross_mode_net_payable_cents"],
        "net_mode_net_payable_cents": figures["net_mode_net_payable_cents"],
    }
    return response.object_response(data)


@bp.post("/remittance-statements/<statement_id>/reconcile")
@M.endpoint(M.SETTLEMENT_ANALYST)
def reconcile_statement(statement_id):
    statement = common.get_statement(statement_id)

    if statement["state"] not in ("OPEN", "DISPUTED"):
        fail(errors.ERR_INVALID_STATEMENT_STATE)
    if not domain.statement_orders(statement["id"]):
        fail(errors.ERR_STATEMENT_EMPTY)
    if domain.count_open_adjustments(statement["id"]) != 0:
        fail(errors.ERR_OPEN_ADJUSTMENTS_PRESENT)

    domain.apply_settlement_figures(statement)
    statement["state"] = "RECONCILED"
    statement["reconciled_by_user_id"] = M.identity().user_id
    db.touch(statement)
    return response.object_response(serializers.statement(statement))


@bp.post("/remittance-statements/<statement_id>/dispute")
@M.endpoint(M.CHANNEL_PARTNER)
def dispute_statement(statement_id):
    payload = validation.body()
    validation.req_str(payload, "reason_code")
    statement = common.get_statement(statement_id)
    M.require_channel_scope(statement["channel_id"])

    if statement["state"] != "RECONCILED":
        fail(errors.ERR_INVALID_STATEMENT_STATE)

    for order in domain.statement_orders(statement["id"]):
        order["settlement_status"] = "SETTLEABLE"
        order["remittance_statement_id"] = None
        db.touch(order)
    for adjustment in db.adjustments.values():
        if adjustment["remittance_statement_id"] == statement["id"]:
            adjustment["remittance_statement_id"] = None
            db.touch(adjustment)

    statement["state"] = "DISPUTED"
    statement["order_count"] = 0
    statement["gross_sales_cents"] = 0
    statement["adjustment_total_cents"] = 0
    statement["tier_base_cents"] = 0
    statement["tier"] = "TIER_1"
    statement["commission_cents"] = 0
    statement["rebate_cents"] = 0
    statement["net_payable_cents"] = 0
    statement["open_adjustment_count"] = 0
    db.touch(statement)
    return response.object_response(serializers.statement(statement))


@bp.post("/remittance-statements/<statement_id>/settle")
@M.endpoint(M.SETTLEMENT_ANALYST)
def settle_statement(statement_id):
    statement = common.get_statement(statement_id)

    if (statement["reconciled_by_user_id"] is not None
            and M.identity().user_id == statement["reconciled_by_user_id"]):
        fail(errors.ERR_SEGREGATION_OF_DUTIES)
    if statement["state"] != "RECONCILED":
        fail(errors.ERR_INVALID_STATEMENT_STATE)

    statement["state"] = "SETTLED"
    statement["settled_at"] = clock.now()
    db.touch(statement)
    for order in domain.statement_orders(statement["id"]):
        order["settlement_status"] = "SETTLED"
        db.touch(order)
    return response.object_response(serializers.statement(statement))
