"""Dispute endpoints (PRD §3.8). Cyclic review with refund cascade."""
from flask import Blueprint, g, request

from db import db, stamp_create, touch
from errors import err
from helpers import (check_enum, get_json_body, paginate, parse_pagination,
                     require_fields, serialize, sort_by_created)
from middleware import require_roles
from response import success
from services import calculations as calc
from services.lookups import get_account, get_dispute, get_order, get_report

bp = Blueprint("disputes", __name__)

REASONS = {"MISSED_DEFECT", "LATE_DELIVERY", "WRONG_VEHICLE"}


def serialize_dispute(d):
    return serialize(d)


@bp.route("/disputes", methods=["POST"])
@require_roles("AccountHolder")
def file_dispute():
    body = get_json_body()
    require_fields(body, ["order_id", "report_id", "reason", "claimed_cents"])
    order = get_order(body["order_id"])
    report = get_report(body["report_id"])

    # ownership: acting account must own the order
    account = db.accounts[order["account_id"]]
    if account["id"] != g.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting account does not own this order")

    # body well-formedness
    check_enum(body["reason"], REASONS, "reason")
    claimed = body["claimed_cents"]
    if not isinstance(claimed, int) or isinstance(claimed, bool) or claimed < 0:
        raise err("ERR_INVALID_REQUEST", "claimed_cents must be a non-negative integer")

    # state: order must be DELIVERED
    if order["workflow_status"] != "DELIVERED":
        raise err("ERR_INVALID_STATE", "Disputes may only be filed against delivered orders")

    d = {
        "order_id": order["id"],
        "report_id": report["id"],
        "account_id": account["id"],
        "reason": body["reason"],
        "claimed_cents": claimed,
        "approved_cents": 0,
        "status": "OPEN",
    }
    stamp_create(d)
    db.disputes[d["id"]] = d
    return success(serialize_dispute(d), status=201)


@bp.route("/disputes/<dispute_id>", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder")
def get_dispute_ep(dispute_id):
    d = get_dispute(dispute_id)
    return success(serialize_dispute(d), status=200)


@bp.route("/disputes", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder")
def list_disputes():
    limit, offset = parse_pagination()
    order_id = request.args.get("order_id")
    report_id = request.args.get("report_id")
    account_id = request.args.get("account_id")
    items = list(db.disputes.values())
    if order_id is not None:
        items = [d for d in items if d["order_id"] == order_id]
    if report_id is not None:
        items = [d for d in items if d["report_id"] == report_id]
    if account_id is not None:
        items = [d for d in items if d["account_id"] == account_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([serialize_dispute(d) for d in page], status=200, pagination=meta)


@bp.route("/disputes/<dispute_id>/start-review", methods=["POST"])
@require_roles("OpsAdmin")
def start_review(dispute_id):
    d = get_dispute(dispute_id)
    if d["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Dispute is not OPEN")
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return success(serialize_dispute(d), status=200)


@bp.route("/disputes/<dispute_id>/request-info", methods=["POST"])
@require_roles("OpsAdmin")
def request_info(dispute_id):
    d = get_dispute(dispute_id)
    if d["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Dispute is not UNDER_REVIEW")
    d["status"] = "NEEDS_INFO"
    touch(d)
    return success(serialize_dispute(d), status=200)


@bp.route("/disputes/<dispute_id>/supply-info", methods=["POST"])
@require_roles("AccountHolder")
def supply_info(dispute_id):
    d = get_dispute(dispute_id)
    # ownership: only the filing account may supply info
    if d["account_id"] != g.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting account does not own this dispute")
    if d["status"] != "NEEDS_INFO":
        raise err("ERR_INVALID_STATE", "Dispute is not in NEEDS_INFO state")
    d["status"] = "OPEN"
    touch(d)
    return success(serialize_dispute(d), status=200)


@bp.route("/disputes/<dispute_id>/resolve", methods=["POST"])
@require_roles("OpsAdmin")
def resolve_dispute(dispute_id):
    d = get_dispute(dispute_id)
    if d["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Dispute is not UNDER_REVIEW")
    order = db.orders[d["order_id"]]
    if order["workflow_status"] != "DELIVERED":
        raise err("ERR_INVALID_STATE", "Order is not DELIVERED")

    fee_schedule = db.fee_schedules[order["fee_schedule_id"]]
    account = db.accounts[order["account_id"]]
    # rush surcharge actually billed (0 if late-credited) — LATE_DELIVERY reason cap
    rush_billed = calc.rush_surcharge_billed(
        fee_schedule,
        order["include_vin_history"],
        order.get("dispatch_miles"),
        order["rush_tier"],
        account.get("rush_discount_pct", 0),
        order["late_delivery"],
    )

    approved = calc.dispute_refund(
        d["reason"],
        d["claimed_cents"],
        order["fee_total_cents"],
        order["refunded_cents"],
        order["late_delivery"],
        rush_billed,
    )
    d["approved_cents"] = approved
    d["status"] = "RESOLVED"
    touch(d)

    # Cascade A: refund
    order["refunded_cents"] = order["refunded_cents"] + approved
    if order["payment_status"] == "PAID" and approved > 0:
        order["payment_status"] = "REFUNDED"
    elif order["payment_status"] == "INVOICED":
        account["outstanding_balance_cents"] = account.get("outstanding_balance_cents", 0) - approved
        touch(account)
    touch(order)

    # Cascade B: MISSED_DEFECT flags linked report for re-author (SUBMITTED -> AMENDED)
    if d["reason"] == "MISSED_DEFECT":
        report = db.reports.get(d["report_id"])
        if report is not None and report["status"] == "SUBMITTED":
            report["status"] = "AMENDED"
            touch(report)

    return success(serialize_dispute(d), status=200)


@bp.route("/disputes/<dispute_id>/reject", methods=["POST"])
@require_roles("OpsAdmin")
def reject_dispute(dispute_id):
    d = get_dispute(dispute_id)
    if d["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Dispute is not UNDER_REVIEW")
    d["status"] = "REJECTED"
    touch(d)
    return success(serialize_dispute(d), status=200)
