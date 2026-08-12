"""Producer settlements (PRD 3.11)."""
from flask import Blueprint, request

from db import STORE, base_record, touch
from errors import (
    ApiError,
    ERR_NEGATIVE_SETTLEMENT,
    ERR_PERMIT_NOT_ACTIVE,
    ERR_POOL_NOT_FINALIZED,
    invalid_state,
    not_found,
)
from helpers import body, req_dt, sort_and_paginate
from middleware import require_roles
from response import success_list, success_object
from services import (
    latest_permit,
    pool_for_month,
    recompute_settlement,
    ser_settlement,
)

bp = Blueprint("settlements", __name__)

_PC = "PlantController"
_SI = "StateInspector"


def _get_producer(pid):
    producer = STORE["producers"].get(pid)
    if producer is None:
        raise not_found("Producer not found")
    return producer


def _get_settlement(pid, sid):
    settlement = STORE["settlements"].get(sid)
    if settlement is None or settlement["producer_id"] != pid:
        raise not_found("ProducerSettlement not found")
    return settlement


@bp.route("/dairy/producers/<pid>/settlements", methods=["POST"])
def create_settlement(pid):
    require_roles(_PC)
    _get_producer(pid)
    data = body()
    period_start = req_dt(data, "period_start_date")
    period_end = req_dt(data, "period_end_date")
    rec = base_record()
    rec.update({
        "producer_id": pid,
        "period_start_date": period_start,
        "period_end_date": period_end,
        "gross_pool_credit_cents": 0,
        "over_order_premium_cents": 0,
        "hauling_deduction_cents": 0,
        "net_payment_cents": 0,
        "pricing_variant": "PROVISIONAL",
        "status": "DRAFT",
    })
    recompute_settlement(rec)
    STORE["settlements"][rec["id"]] = rec
    return success_object(ser_settlement(rec), 201)


@bp.route("/dairy/producers/<pid>/settlements", methods=["GET"])
def list_settlements(pid):
    require_roles(_PC, _SI)
    _get_producer(pid)
    producer_filter = request.args.get("producer_id")
    records = [s for s in STORE["settlements"].values()
               if s["producer_id"] == pid]
    if producer_filter is not None:
        records = [s for s in records if s["producer_id"] == producer_filter]
    page, pagination = sort_and_paginate(records)
    return success_list([ser_settlement(s) for s in page], pagination)


@bp.route("/dairy/producers/<pid>/settlements/<sid>", methods=["GET"])
def get_settlement(pid, sid):
    require_roles(_PC, _SI)
    _get_producer(pid)
    return success_object(ser_settlement(_get_settlement(pid, sid)))


@bp.route("/dairy/producers/<pid>/settlements/<sid>/approve", methods=["POST"])
def approve_settlement(pid, sid):
    require_roles(_PC)
    _get_producer(pid)
    settlement = _get_settlement(pid, sid)
    if settlement["status"] != "DRAFT":
        raise invalid_state("ProducerSettlement is not in DRAFT")
    month = settlement["period_start_date"].strftime("%Y-%m")
    pool = pool_for_month(month)
    if pool is None or pool["status"] != "FINALIZED":
        raise ApiError(ERR_POOL_NOT_FINALIZED, 422,
                       "MarketingOrderPool is not FINALIZED")
    if settlement["pricing_variant"] != "FINAL":
        raise invalid_state("pricing_variant is not FINAL")
    permit = latest_permit()
    if permit is not None and permit["status"] == "SUSPENDED":
        raise ApiError(
            ERR_PERMIT_NOT_ACTIVE, 422,
            "ProducerSettlement approvals are blocked while the Grade A "
            "permit is SUSPENDED",
        )
    recompute_settlement(settlement, pool=pool)
    settlement["status"] = "APPROVED"
    touch(settlement)
    return success_object(ser_settlement(settlement), 200)


@bp.route("/dairy/producers/<pid>/settlements/<sid>/mark-paid", methods=["POST"])
def mark_paid_settlement(pid, sid):
    require_roles(_PC)
    _get_producer(pid)
    settlement = _get_settlement(pid, sid)
    if settlement["status"] != "APPROVED":
        raise invalid_state("ProducerSettlement is not in APPROVED")
    if settlement["net_payment_cents"] < 0:
        raise ApiError(ERR_NEGATIVE_SETTLEMENT, 422,
                       "net_payment_cents is negative")
    settlement["status"] = "PAID"
    touch(settlement)
    return success_object(ser_settlement(settlement), 200)


@bp.route("/dairy/producers/<pid>/settlements/<sid>/cancel", methods=["POST"])
def cancel_settlement(pid, sid):
    require_roles(_PC)
    _get_producer(pid)
    settlement = _get_settlement(pid, sid)
    if settlement["status"] != "DRAFT":
        raise invalid_state("ProducerSettlement is not in DRAFT")
    settlement["status"] = "CANCELLED"
    touch(settlement)
    return success_object(ser_settlement(settlement), 200)
