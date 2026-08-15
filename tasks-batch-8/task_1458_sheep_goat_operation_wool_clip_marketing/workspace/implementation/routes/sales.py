"""Holiday window and livestock sale endpoints (PRD 3.6)."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import db
import serial
import validate as v
from errors import (ERR_INSUFFICIENT_HEAD, ERR_PAYMENT_AMOUNT_MISMATCH,
                    ERR_SALE_INVALID_STATE, ERR_SALE_UNPAID, ERR_VALIDATION,
                    ERR_WITHDRAWAL_ACTIVE, raise_err)
from middleware import require_roles
from response import success
from routes.flocks import check_flock_active

bp = Blueprint("sales", __name__)


# ------------------------------------------------------------------ holiday windows
@bp.post("/api/holiday-windows")
def create_holiday():
    require_roles("RanchManager")
    b = v.body()
    name = v.req_str(b, "holiday_name")
    start = v.req_dt(b, "window_start")
    end = v.req_dt(b, "window_end")
    premium = v.req_num(b, "premium_pct", gte=0, lte=100)
    min_head = v.req_int(b, "min_head", min=1)
    if not start < end:
        raise_err(ERR_VALIDATION, "window_start must be strictly before window_end")
    if any(w["holiday_name"] == name for w in db.STORE["holidays"].values()):
        raise_err(ERR_VALIDATION, "holiday_name must be unique")
    row = db.new_row()
    row.update({
        "holiday_name": name,
        "window_start": start,
        "window_end": end,
        "premium_pct": premium,
        "min_head": min_head,
    })
    db.STORE["holidays"][row["id"]] = row
    return success(serial.holiday_public(row), status=201)


# ------------------------------------------------------------------ sales
@bp.post("/api/livestock-sales")
def create_sale():
    require_roles("RanchManager")
    b = v.body()
    flock_id = v.req_str(b, "flock_id")
    sale_type = v.req_enum(b, "sale_type", ("MEAT", "BREEDING"))
    channel = v.req_enum(b, "channel", ("AUCTION", "DIRECT", "ETHNIC_MARKET"))
    head = v.req_int(b, "head_count", min=1)
    shrink = v.opt_num(b, "shrink_pct", default=Decimal("0"), gte=0, lte=100)
    scheduled = v.req_dt(b, "scheduled_date")
    if sale_type == "MEAT":
        avg_weight = v.req_num(b, "avg_weight_lbs", gt=0)
        base_price = v.req_int(b, "base_price_per_cwt_cents", min=1)
        if v.present(b, "per_head_price_cents"):
            raise_err(ERR_VALIDATION, "MEAT sales must not carry per_head_price_cents")
        per_head = None
    else:
        per_head = v.req_int(b, "per_head_price_cents", min=1)
        if v.present(b, "avg_weight_lbs") or v.present(b, "base_price_per_cwt_cents"):
            raise_err(ERR_VALIDATION, "BREEDING sales must not carry meat pricing fields")
        avg_weight = None
        base_price = None
    flock = db.get_or_404("flocks", flock_id)
    check_flock_active(flock)
    if sale_type == "MEAT":
        gate = calc.flock_withdrawal_until(flock_id)
        if gate is not None and scheduled < gate:
            raise_err(ERR_WITHDRAWAL_ACTIVE, "scheduled_date is earlier than the flock's withdrawal gate")
    if head > calc.flock_headcount(flock_id):
        raise_err(ERR_INSUFFICIENT_HEAD, "head_count exceeds flock current_headcount")
    # booked pricing (pinned order: gross -> premium -> commission -> total)
    applied_holiday = None
    premium_applied = Decimal("0")
    if sale_type == "MEAT":
        if channel == "ETHNIC_MARKET":
            window = calc.select_holiday_window(scheduled)
            if window is not None:
                applied_holiday = window["holiday_name"]
                premium_applied = (window["premium_pct"] if head >= window["min_head"]
                                   else window["premium_pct"] / Decimal(2))
        gross = calc.sale_gross_meat(head, avg_weight, base_price, shrink, channel)
        booked = calc.sale_total(gross, channel, premium_applied)
    else:
        booked = head * per_head
    row = db.new_row()
    row.update({
        "flock_id": flock_id,
        "sale_type": sale_type,
        "channel": channel,
        "head_count": head,
        "avg_weight_lbs": avg_weight,
        "base_price_per_cwt_cents": base_price,
        "per_head_price_cents": per_head,
        "shrink_pct": shrink,
        "scheduled_date": scheduled,
        "payment_status": "UNPAID",
        "delivery_status": "PENDING",
        "booked_price_cents": booked,
        "applied_holiday_name": applied_holiday,
        "premium_pct_applied": premium_applied,
        "actual_total_weight_lbs": None,
        "actual_head_delivered": None,
        "settled_price_cents": None,
    })
    db.STORE["sales"][row["id"]] = row
    return success(serial.sale_public(row), status=201)


@bp.get("/api/livestock-sales")
def list_sales():
    require_roles("RanchManager", "RangeHand")
    limit, offset = v.pagination()
    rows = db.sorted_rows("sales")
    for param, field in (("flock_id", "flock_id"), ("delivery_status", "delivery_status")):
        val = request.args.get(param)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    page, meta = v.paginate(rows, limit, offset)
    return success([serial.sale_public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/api/livestock-sales/<sid>")
def get_sale(sid):
    require_roles("RanchManager", "RangeHand")
    row = db.get_or_404("sales", sid)
    return success(serial.sale_public(row))


@bp.post("/api/livestock-sales/<sid>/record-payment")
def record_payment(sid):
    require_roles("RanchManager")
    b = v.body()
    amount = v.req_int(b, "amount_cents")
    row = db.get_or_404("sales", sid)
    if row["delivery_status"] not in ("PENDING", "LOADED") or row["payment_status"] != "UNPAID":
        raise_err(ERR_SALE_INVALID_STATE, "payment is not accepted in the sale's current state")
    if amount != row["booked_price_cents"]:
        raise_err(ERR_PAYMENT_AMOUNT_MISMATCH, "amount_cents must equal booked_price_cents")
    row["payment_status"] = "PAID"
    db.touch(row)
    return success(serial.sale_public(row))


@bp.post("/api/livestock-sales/<sid>/load")
def load_sale(sid):
    require_roles("RanchManager", "RangeHand")
    row = db.get_or_404("sales", sid)
    if row["delivery_status"] != "PENDING":
        raise_err(ERR_SALE_INVALID_STATE, "only a PENDING sale can be loaded")
    if row["payment_status"] != "PAID":
        raise_err(ERR_SALE_UNPAID, "loading requires payment_status PAID")
    row["delivery_status"] = "LOADED"
    db.touch(row)
    return success(serial.sale_public(row))


@bp.post("/api/livestock-sales/<sid>/deliver")
def deliver_sale(sid):
    require_roles("RanchManager", "RangeHand")
    row = db.get_or_404("sales", sid)
    b = v.body()
    if row["sale_type"] == "MEAT":
        actual_weight = v.req_num(b, "actual_total_weight_lbs", gt=0)
        actual_head = None
    else:
        actual_head = v.req_int(b, "actual_head_delivered", min=1)
        actual_weight = None
    if row["delivery_status"] != "LOADED":
        raise_err(ERR_SALE_INVALID_STATE, "only a LOADED sale can be delivered")
    if row["sale_type"] == "MEAT":
        gross = calc.sale_gross_meat(row["head_count"], row["avg_weight_lbs"],
                                     row["base_price_per_cwt_cents"], row["shrink_pct"],
                                     row["channel"], actual_total_weight_lbs=actual_weight)
        settled = calc.sale_total(gross, row["channel"], row["premium_pct_applied"])
        row["actual_total_weight_lbs"] = actual_weight
    else:
        settled = actual_head * row["per_head_price_cents"]
        row["actual_head_delivered"] = actual_head
    row["settled_price_cents"] = settled
    row["delivery_status"] = "DELIVERED"
    db.touch(row)
    flock = db.STORE["flocks"][row["flock_id"]]
    db.touch(flock)  # headcount ledger is recomputed on read; the delivery bumps flock version
    return success(serial.sale_public(row))


@bp.post("/api/livestock-sales/<sid>/cancel")
def cancel_sale(sid):
    require_roles("RanchManager")
    row = db.get_or_404("sales", sid)
    if row["delivery_status"] != "PENDING":
        raise_err(ERR_SALE_INVALID_STATE, "only a PENDING sale can be cancelled")
    row["delivery_status"] = "CANCELLED"
    if row["payment_status"] == "PAID":
        row["payment_status"] = "REFUNDED"
    db.touch(row)
    return success(serial.sale_public(row))
