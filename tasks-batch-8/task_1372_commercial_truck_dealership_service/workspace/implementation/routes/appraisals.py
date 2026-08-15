"""TradeAppraisal endpoints (PRD §3.4)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, stamp_new, touch, now_dt, clock_date
from errors import err_not_found, err_invalid, err_forbidden, ApiError
from helpers import (body, req_str, req_enum, req_int, paginate, sort_created,
                     apply_filters)
from middleware import caller, ALL_ROLES
from response import success, success_list
from serializers import trade_appraisal as ser
import services

bp = Blueprint("appraisals", __name__)

CONDITION_GRADES = {"A", "B", "C"}
OFFER_DAYS = 10


def _get_appraisal(rid):
    a = store.trade_appraisals.get(rid)
    if a is None:
        raise err_not_found("TRADE_APPRAISAL")
    return a


def _check_owner(a, uid):
    """FleetCustomer may only act on its own account's appraisal (priority 3)."""
    if uid != a["customer_account_id"]:
        raise err_forbidden(
            "FleetCustomer may only act on its own account's appraisals")


@bp.post("/dealership/trade-appraisals")
def create_appraisal():
    caller(["SalesConsultant"])
    data = body()
    account_id = req_str(data, "customer_account_id")
    trade_vin = req_str(data, "trade_vin")
    model_year = req_int(data, "model_year")
    mileage = req_int(data, "mileage", minimum=0)
    grade = req_enum(data, "condition_grade", CONDITION_GRADES)
    book_value = req_int(data, "base_book_value_cents", minimum=0)
    if account_id not in store.customer_accounts:
        raise err_not_found("CUSTOMER_ACCOUNT")
    appraisal = {
        "customer_account_id": account_id,
        "trade_vin": trade_vin,
        "model_year": model_year,
        "mileage": mileage,
        "condition_grade": grade,
        "base_book_value_cents": book_value,
        "book_estimate_cents": services.book_estimate(model_year, mileage,
                                                      book_value),
        "market_index_bp": None,
        "offer_acv_cents": None,
        "offered_allowance_cents": None,
        "_offer_expires_dt": None,
        "offer_round": 0,
        "created_unit_id": None,
        "status": "DRAFT",
    }
    stamp_new(appraisal)
    store.trade_appraisals[appraisal["id"]] = appraisal
    return success(ser(appraisal), status=201)


@bp.get("/dealership/trade-appraisals")
def list_appraisals():
    caller(ALL_ROLES)
    items = apply_filters(sort_created(store.trade_appraisals.values()), [
        ("customer_account_id", request.args.get("customer_account_id")),
        ("status", request.args.get("status")),
    ])
    page, meta = paginate(items)
    return success_list([ser(a) for a in page], meta)


@bp.get("/dealership/trade-appraisals/<rid>")
def get_appraisal(rid):
    caller(ALL_ROLES)
    return success(ser(_get_appraisal(rid)))


@bp.post("/dealership/trade-appraisals/<rid>/offer")
def offer_appraisal(rid):
    caller(["SalesManager"])
    data = body()
    index_bp = req_int(data, "market_index_bp", minimum=0)
    allowance = req_int(data, "offered_allowance_cents", minimum=0)
    a = _get_appraisal(rid)
    if a["status"] not in ("DRAFT", "NEGOTIATING"):
        raise ApiError("ERR_APPRAISAL_STATE", 409,
                       "Offer requires status DRAFT or NEGOTIATING")
    acv = services.market_acv(a["book_estimate_cents"], a["condition_grade"],
                              index_bp)
    if allowance > acv:
        raise ApiError("ERR_APPRAISAL_OFFER_EXCEEDS_ACV", 422,
                       "offered_allowance_cents exceeds the market ACV ceiling")
    a["market_index_bp"] = index_bp
    a["offer_acv_cents"] = acv
    a["offered_allowance_cents"] = allowance
    a["_offer_expires_dt"] = now_dt() + timedelta(days=OFFER_DAYS)
    a["offer_round"] += 1
    a["status"] = "OFFERED"
    touch(a)
    return success(ser(a))


@bp.post("/dealership/trade-appraisals/<rid>/counter")
def counter_appraisal(rid):
    uid, _ = caller(["FleetCustomer"])
    a = _get_appraisal(rid)
    _check_owner(a, uid)
    if a["status"] != "OFFERED":
        raise ApiError("ERR_APPRAISAL_STATE", 409,
                       "Counter requires status OFFERED")
    a["status"] = "NEGOTIATING"
    touch(a)
    return success(ser(a))


@bp.post("/dealership/trade-appraisals/<rid>/accept")
def accept_appraisal(rid):
    uid, _ = caller(["FleetCustomer"])
    a = _get_appraisal(rid)
    _check_owner(a, uid)
    if a["status"] != "OFFERED":
        raise ApiError("ERR_APPRAISAL_STATE", 409,
                       "Accept requires status OFFERED")
    if now_dt() >= a["_offer_expires_dt"]:
        raise ApiError("ERR_APPRAISAL_STATE", 409,
                       "Offer has expired")
    unit = {
        "vin": a["trade_vin"],
        "unit_kind": "USED",
        "factory_order_id": None,
        "trade_appraisal_id": a["id"],
        "status": "RECONDITIONING",
        "invoice_cost_cents": a["offered_allowance_cents"],
        "stocking_date": clock_date().isoformat(),
        "floorplan_active": False,
        "apr_bp": 690,
        "floorplan_balance_cents": 0,
        "last_accrual_date": None,
        "recondition_count": 0,
        "sold_price_cents": None,
        "_sold_at_dt": None,
        "wholesale_price_cents": None,
        "wholesale_loss_cents": None,
        "_sweep_bucket": "B0_90",
    }
    stamp_new(unit)
    store.units[unit["id"]] = unit
    a["created_unit_id"] = unit["id"]
    a["status"] = "ACCEPTED"
    touch(a)
    return success(ser(a))


@bp.post("/dealership/trade-appraisals/<rid>/decline")
def decline_appraisal(rid):
    uid, _ = caller(["FleetCustomer"])
    a = _get_appraisal(rid)
    _check_owner(a, uid)
    if a["status"] != "OFFERED":
        raise ApiError("ERR_APPRAISAL_STATE", 409,
                       "Decline requires status OFFERED")
    a["status"] = "DECLINED"
    touch(a)
    return success(ser(a))
