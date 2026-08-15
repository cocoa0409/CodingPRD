"""Unit endpoints (PRD §3.3)."""
from datetime import date

from flask import Blueprint, request

from db import store, stamp_new, touch, clock_date
from errors import err_not_found, err_invalid, err_stale, ApiError
from helpers import (body, req_str, req_enum, opt_str, req_int, parse_date,
                     paginate, sort_created)
from middleware import caller, ALL_ROLES
from response import success, success_list
from serializers import unit as ser, floor_plan_entry as entry_ser
import services

bp = Blueprint("units", __name__)

INSPECTABLE = ("IN_STOCK", "RECONDITIONING", "READY")
WHOLESALE_BUCKETS = ("B181_270", "B271_365", "OVER_365")


def _get_unit(rid):
    u = store.units.get(rid)
    if u is None:
        raise err_not_found("UNIT")
    return u


@bp.get("/dealership/units")
def list_units():
    caller(ALL_ROLES)
    items = sort_created(store.units.values())
    unit_kind = request.args.get("unit_kind")
    status = request.args.get("status")
    bucket = request.args.get("aging_bucket")
    fo_id = request.args.get("factory_order_id")
    ta_id = request.args.get("trade_appraisal_id")
    out = []
    for u in items:
        if unit_kind is not None and u["unit_kind"] != unit_kind:
            continue
        if status is not None and u["status"] != status:
            continue
        if bucket is not None and services.aging_bucket(
                services.days_in_stock(u)) != bucket:
            continue
        if fo_id is not None and u["factory_order_id"] != fo_id:
            continue
        if ta_id is not None and u["trade_appraisal_id"] != ta_id:
            continue
        out.append(u)
    page, meta = paginate(out)
    return success_list([ser(u) for u in page], meta)


@bp.get("/dealership/units/<rid>")
def get_unit(rid):
    caller(ALL_ROLES)
    return success(ser(_get_unit(rid)))


@bp.post("/dealership/units/<rid>/inspect")
def inspect_unit(rid):
    caller(["ServiceManager"])
    data = body()
    outcome = req_enum(data, "outcome", {"PASS", "FAIL"})
    u = _get_unit(rid)
    if u["status"] not in INSPECTABLE:
        raise ApiError("ERR_UNIT_STATE", 409,
                       "Unit state does not permit inspection")
    if outcome == "PASS":
        u["status"] = "READY"
    else:
        u["status"] = "RECONDITIONING"
        u["recondition_count"] += 1
    touch(u)
    return success(ser(u))


@bp.post("/dealership/units/<rid>/sell")
def sell_unit(rid):
    caller(["SalesConsultant"])
    data = body()
    buyer_id = req_str(data, "customer_account_id")
    sale_price = req_int(data, "sale_price_cents", minimum=0)
    appraisal_id = opt_str(data, "trade_appraisal_id")

    u = _get_unit(rid)
    buyer = store.customer_accounts.get(buyer_id)
    if buyer is None:
        raise err_not_found("CUSTOMER_ACCOUNT")
    appraisal = None
    if appraisal_id is not None:
        appraisal = store.trade_appraisals.get(appraisal_id)
        if appraisal is None:
            raise err_not_found("TRADE_APPRAISAL")

    # State (7) -> cross-resource appraisal check (19) -> fiscal posture (20).
    if u["status"] != "READY":
        raise ApiError("ERR_UNIT_NOT_SELLABLE", 409,
                       "Sell requires unit status READY")
    if appraisal is not None:
        if (appraisal["status"] != "ACCEPTED"
                or appraisal["customer_account_id"] != buyer_id):
            raise ApiError("ERR_APPRAISAL_STATE", 409,
                           "Referenced appraisal must be ACCEPTED and owned by the buyer")
    if buyer["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_ON_CREDIT_HOLD", 409,
                       "Buyer account must be ACTIVE")

    services.settle_floor_plan(u)
    u["sold_price_cents"] = sale_price
    u["_sold_at_dt"] = store.clock
    u["status"] = "SOLD"
    touch(u)
    if appraisal is not None:
        appraisal["status"] = "CONSUMED"
        touch(appraisal)
    return success(ser(u))


@bp.post("/dealership/units/<rid>/wholesale")
def wholesale_unit(rid):
    caller(["SalesManager"])
    data = body()
    price = req_int(data, "wholesale_price_cents", minimum=0)
    u = _get_unit(rid)
    if u["status"] != "READY":
        raise ApiError("ERR_UNIT_NOT_SELLABLE", 409,
                       "Wholesale requires unit status READY")
    bucket = services.aging_bucket(services.days_in_stock(u))
    if bucket not in WHOLESALE_BUCKETS:
        raise ApiError("ERR_UNIT_NOT_WHOLESALE_ELIGIBLE", 409,
                       "Wholesale requires aging bucket B181_270 or older")
    services.settle_floor_plan(u)
    u["wholesale_price_cents"] = price
    u["wholesale_loss_cents"] = max(0, u["invoice_cost_cents"] - price)
    u["status"] = "WHOLESALED"
    touch(u)
    return success(ser(u))


@bp.post("/dealership/units/<rid>/floor-plan-adjustments")
def floor_plan_adjustment(rid):
    caller(["Controller"])
    data = body()
    amount = req_int(data, "amount_cents")
    expected = req_int(data, "expected_unit_version")
    note = opt_str(data, "note")
    u = _get_unit(rid)
    if expected != u["version"]:
        raise err_stale()
    services.post_fp_entry(u, "ADJUSTMENT", amount, note)
    touch(u)
    return success(ser(u), status=201)


@bp.post("/dealership/units/<rid>/floor-plan-curtailments")
def floor_plan_curtailment(rid):
    caller(["Controller"])
    data = body()
    amount = req_int(data, "amount_cents", minimum=1)
    note = opt_str(data, "note")
    u = _get_unit(rid)
    if not u["floorplan_active"] or u["status"] not in INSPECTABLE:
        raise ApiError("ERR_UNIT_STATE", 409,
                       "Curtailment requires a floor-plan-active unit in stock")
    due = services.curtailment_due(u, services.days_in_stock(u))
    if amount > due or amount > u["floorplan_balance_cents"]:
        raise err_invalid(
            "amount_cents must not exceed curtailment_due_cents or the floor-plan balance")
    services.post_fp_entry(u, "CURTAILMENT", -amount, note)
    touch(u)
    return success(ser(u), status=201)


@bp.get("/dealership/units/<rid>/floor-plan-entries")
def list_fp_entries(rid):
    caller(ALL_ROLES)
    u = _get_unit(rid)
    entries = [e for e in store.floor_plan_entries.values()
               if e["unit_id"] == u["id"]]
    # Chronological replay order: entry_date ASC, created_at ASC tie-break.
    entries.sort(key=lambda e: (e["entry_date"], e["_seq"]))
    page, meta = paginate(entries)
    return success_list([entry_ser(e) for e in page], meta)


@bp.get("/dealership/units/<rid>/payoff-quote")
def payoff_quote(rid):
    caller(ALL_ROLES)
    u = _get_unit(rid)
    as_of_raw = request.args.get("as_of_date")
    as_of = parse_date(as_of_raw, "as_of_date") if as_of_raw else clock_date()
    balance = u["floorplan_balance_cents"]
    proj_days = 0
    if u["floorplan_active"] and u["last_accrual_date"]:
        proj_days = max(0, (as_of - date.fromisoformat(
            u["last_accrual_date"])).days)
    projected = services.interest_amount(balance, u["apr_bp"], proj_days) \
        if (u["floorplan_active"] and balance > 0) else 0
    curtailment = services.curtailment_due(u, services.days_in_stock(u))
    return success({
        "unit_id": u["id"],
        "as_of_date": as_of.isoformat(),
        "balance_cents": balance,
        "projected_interest_cents": projected,
        "curtailment_due_cents": curtailment,
        "payoff_cents": balance + projected + curtailment,
    })
