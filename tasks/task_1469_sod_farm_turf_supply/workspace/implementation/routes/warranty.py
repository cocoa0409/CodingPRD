"""Establishment warranty claims and watering logs (PRD section 3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import db
from auth import check_ownership, require_roles
from db import common_fields, sub_fields
from errors import (err, ERR_ALREADY_TERMINAL, ERR_CLAIM_WINDOW_EXPIRED,
                    ERR_DUPLICATE_CLAIM, ERR_INVALID_ENUM, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_ORDER_NOT_SETTLED)
from serialize import pub_claim, pub_watering_log
from util import (as_num, body, ok, ok_list, paged, pagination, parse_date,
                  r2, require, sort_created)

bp = Blueprint("warranty", __name__)

WEATHER_CASES = {"W1", "W2", "W3"}
CLAIM_WINDOW_DAYS = 30


def _get_order(oid):
    order = db.store.orders.get(oid)
    if order is None:
        raise err(ERR_NOT_FOUND, f"order {oid} not found")
    return order


def _get_claim(cid):
    claim = db.store.warranty_claims.get(cid)
    if claim is None:
        raise err(ERR_NOT_FOUND, f"warranty claim {cid} not found")
    return claim


@bp.route("/orders/<oid>/warranty-claims", methods=["POST"])
def create_claim(oid):
    user_id, role = require_roles("Customer")
    order = _get_order(oid)
    check_ownership(user_id, role, order["customer_id"])
    payload = body()
    if "weather_case" not in payload or payload["weather_case"] is None:
        raise err(ERR_INVALID_REQUEST, "weather_case is required")
    if payload["weather_case"] not in WEATHER_CASES:
        raise err(ERR_INVALID_ENUM, "weather_case must be W1, W2, or W3")
    if order["status"] == "CANCELLED":
        raise err(ERR_ALREADY_TERMINAL, f"order {oid} is CANCELLED")
    if order["installed_at"] is None:
        raise err(ERR_INVALID_STATE, "order has not completed installation")
    if order["delivery_flagged"]:
        raise err(ERR_INVALID_STATE,
                  "order is delivery-flagged until a later in-window check clears it")
    # tier 9: thirty-day claim window (inclusive at exactly 30 days)
    if db.now() > order["installed_at"] + timedelta(days=CLAIM_WINDOW_DAYS):
        raise err(ERR_CLAIM_WINDOW_EXPIRED,
                  "claim window expired (30 days after installation)")
    # tier 10: one claim per order
    for c in db.store.warranty_claims.values():
        if c["order_id"] == oid:
            raise err(ERR_DUPLICATE_CLAIM, "order already has a warranty claim")
    # tier 12: fully settled
    if order["payment_status"] != "PAID":
        raise err(ERR_ORDER_NOT_SETTLED, "order payment_status is not PAID")
    claim = common_fields()
    claim.update({
        "order_id": oid,
        "customer_id": order["customer_id"],
        "weather_case": payload["weather_case"],
        "eligible_turf_sqft": order["delivered_sqft"],
        "target_credits": calc.WEATHER_TARGET[payload["weather_case"]],
        "total_credits": 0,
        "status": "SUBMITTED",
        "resolution": "NONE",
        "credit_amount": r2(0),
        "evaluated_at": None,
    })
    db.store.warranty_claims[claim["id"]] = claim
    return ok(pub_claim(claim), 201)


@bp.route("/orders/<oid>/warranty-claims", methods=["GET"])
def list_order_claims(oid):
    user_id, role = require_roles("SalesRep", "FarmManager", "Customer")
    order = _get_order(oid)
    check_ownership(user_id, role, order["customer_id"])
    limit, offset = pagination()
    items = sort_created(c for c in db.store.warranty_claims.values()
                         if c["order_id"] == oid)
    page, total = paged(items, limit, offset)
    return ok_list([pub_claim(c) for c in page], total, limit, offset)


@bp.route("/warranty-claims", methods=["GET"])
def list_claims():
    require_roles("SalesRep", "FarmManager")
    limit, offset = pagination()
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = sort_created(db.store.warranty_claims.values())
    if customer_id is not None:
        items = [c for c in items if c["customer_id"] == customer_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paged(items, limit, offset)
    return ok_list([pub_claim(c) for c in page], total, limit, offset)


@bp.route("/warranty-claims/<cid>", methods=["GET"])
def get_claim(cid):
    user_id, role = require_roles("SalesRep", "FarmManager", "Customer")
    claim = _get_claim(cid)
    check_ownership(user_id, role, claim["customer_id"])
    return ok(pub_claim(claim), 200)


@bp.route("/warranty-claims/<cid>/watering-logs", methods=["POST"])
def create_watering_log(cid):
    user_id, role = require_roles("Customer")
    claim = _get_claim(cid)
    check_ownership(user_id, role, claim["customer_id"])
    payload = body()
    log_date = parse_date(require(payload, "log_date"), "log_date")
    moisture = as_num(require(payload, "moisture_reading"), "moisture_reading", 0, 100)
    if claim["status"] in ("COMPLIANT", "INSUFFICIENT"):
        raise err(ERR_ALREADY_TERMINAL, f"warranty claim {cid} is {claim['status']}")
    order = db.store.orders.get(claim["order_id"])
    installed_date = order["installed_at"].date()
    window_end_date = (order["installed_at"] + timedelta(days=CLAIM_WINDOW_DAYS)).date()
    if not (installed_date <= log_date <= window_end_date):
        raise err(ERR_INVALID_REQUEST,
                  "log_date must lie within [installed_at date, installed_at + 30 days]")
    for w in db.store.watering_logs.values():
        if w["claim_id"] == cid and w["log_date"] == log_date:
            raise err(ERR_INVALID_REQUEST,
                      "a watering log already exists for this claim on that date")
    log = sub_fields()
    log.update({
        "claim_id": cid,
        "log_date": log_date,
        "moisture_reading": moisture,
        "credits_awarded": calc.watering_credits(moisture),
    })
    db.store.watering_logs[log["id"]] = log
    claim["total_credits"] += log["credits_awarded"]
    db.bump(claim)
    return ok(pub_watering_log(log), 201)


@bp.route("/warranty-claims/<cid>/watering-logs", methods=["GET"])
def list_watering_logs(cid):
    user_id, role = require_roles("SalesRep", "FarmManager", "Customer")
    claim = _get_claim(cid)
    check_ownership(user_id, role, claim["customer_id"])
    limit, offset = pagination()
    items = sort_created(w for w in db.store.watering_logs.values()
                         if w["claim_id"] == cid)
    page, total = paged(items, limit, offset)
    return ok_list([pub_watering_log(w) for w in page], total, limit, offset)


@bp.route("/warranty-claims/<cid>/evaluate", methods=["POST"])
def evaluate_claim(cid):
    require_roles("FarmManager")
    claim = _get_claim(cid)
    if claim["status"] in ("COMPLIANT", "INSUFFICIENT"):
        raise err(ERR_ALREADY_TERMINAL, f"warranty claim {cid} is {claim['status']}")
    if claim["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, f"warranty claim {cid} is not SUBMITTED")
    has_logs = any(w["claim_id"] == cid for w in db.store.watering_logs.values())
    if not has_logs:
        raise err(ERR_INVALID_STATE, "at least one watering log is required")
    if claim["total_credits"] >= claim["target_credits"]:
        claim["status"] = "COMPLIANT"
        claim["resolution"] = "CREDIT_ISSUED"
        claim["credit_amount"] = r2(claim["eligible_turf_sqft"] * r2("0.50"))
    else:
        claim["status"] = "INSUFFICIENT"
        claim["resolution"] = "REJECTED"
        claim["credit_amount"] = r2(0)
    claim["evaluated_at"] = db.now()
    db.bump(claim)
    return ok(pub_claim(claim), 200)
