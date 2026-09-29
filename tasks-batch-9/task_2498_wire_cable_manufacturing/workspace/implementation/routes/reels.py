"""The reel fleet, packaging and deposit settlement (PRD 3.8, 3.9)."""

from flask import Blueprint

import clock
import constants as C
import errors
import lookups
import response
import validation
from auth import require_auth
from db import all_sorted, db, new_record, sort_created, touch
from serializers import view, views
from services import ledger, pricing
from util import D, day_diff, money, parse_iso_dt, parse_ymd

bp = Blueprint("reels", __name__)

_READ_ROLES = ("ShippingClerk", "BillingAnalyst", "ProcessEngineer", "PlantAdmin")


@bp.route("/reels", methods=["POST"])
def create_reel():
    require_auth("ShippingClerk", "PlantAdmin")
    b = validation.body()
    reel_serial = validation.f_str(b, "reel_serial")
    reel_type = validation.f_enum(b, "reel_type", C.REEL_TYPES)
    deposit = validation.f_num(b, "deposit_usd", ge=0)
    capacity = validation.f_num(b, "capacity_ft", gt=0)

    if reel_type == "NON_RETURNABLE" and deposit != D("0"):
        errors.fail(
            errors.ERR_REEL_DEPOSIT_MISMATCH,
            "A NON_RETURNABLE reel must carry a deposit of exactly 0",
        )
    if reel_type != "NON_RETURNABLE" and deposit == D("0"):
        errors.fail(
            errors.ERR_REEL_DEPOSIT_MISMATCH,
            "A returnable reel must carry a non-zero deposit",
        )

    rec = new_record()
    rec.update({
        "reel_serial": reel_serial,
        "reel_type": reel_type,
        "deposit_usd": money(deposit),
        "capacity_ft": capacity,
        "current_lot_id": None,
        "held_by_customer_id": None,
        "loaded_length_ft": 0,
        "occupancy_start_at": None,
        "occupancy_end_at": None,
        "shipped_at": None,
        "returned_at": None,
        "cycle_count": 0,
        "last_return_condition": None,
        "status": "AVAILABLE",
    })
    db.reels[rec["id"]] = rec
    return response.created(view("reel", rec))


@bp.route("/reels/<reel_id>", methods=["GET"])
def get_reel(reel_id):
    require_auth(*_READ_ROLES)
    rec = lookups.reel(reel_id)
    return response.ok(view("reel", rec))


@bp.route("/reels", methods=["GET"])
def list_reels():
    require_auth(*_READ_ROLES)
    limit, offset = validation.pagination()
    status = validation.q_enum("status", C.REEL_STATUSES)
    reel_type = validation.q_enum("reel_type", C.REEL_TYPES)
    current_lot_id = validation.q_str("current_lot_id")
    held_by = validation.q_str("held_by_customer_id")

    rows = all_sorted(db.reels)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if reel_type is not None:
        rows = [r for r in rows if r["reel_type"] == reel_type]
    if current_lot_id is not None:
        rows = [r for r in rows if r["current_lot_id"] == current_lot_id]
    if held_by is not None:
        rows = [r for r in rows if r["held_by_customer_id"] == held_by]
    page, total = response.paginate(rows, limit, offset)
    return response.ok_list(views("reel", page), limit, offset, total)


@bp.route("/reels/<reel_id>/load", methods=["POST"])
def load_reel(reel_id):
    require_auth("ShippingClerk", "PlantAdmin")
    b = validation.body()
    lot_id = validation.f_str(b, "lot_id")
    load_length = validation.f_num(b, "load_length_ft", ge=0)
    start_raw, start_dt = validation.f_datetime(b, "occupancy_start_at")

    # Path segments resolve before body references (PRD 2.10).
    reel = lookups.reel(reel_id)
    lot = lookups.lot(lot_id)

    if reel["status"] != "AVAILABLE":
        errors.fail(
            errors.ERR_INVALID_REEL_STATE,
            "Only an AVAILABLE reel may be loaded (this one is %s)" % reel["status"],
        )
    if lot["process_state"] != "TESTED" or lot["quality_state"] != "CONFORMING":
        errors.fail(
            errors.ERR_INVALID_LOT_STATE,
            "Loading requires a TESTED lot released to CONFORMING",
        )

    # Rung 18: reel occupancy is half-open with no buffer.
    if reel["returned_at"] is not None:
        if start_dt < parse_iso_dt(reel["returned_at"]):
            errors.fail(
                errors.ERR_REEL_OCCUPANCY_OVERLAP,
                "occupancy_start_at must be at or after the reel's last return instant",
            )

    # Rung 22: capacity.
    if D(reel["loaded_length_ft"]) + D(load_length) > D(reel["capacity_ft"]):
        errors.fail(
            errors.ERR_REEL_CAPACITY_EXCEEDED,
            "The requested load exceeds the reel's capacity",
        )

    reel["current_lot_id"] = lot["id"]
    reel["loaded_length_ft"] = D(reel["loaded_length_ft"]) + D(load_length)
    reel["occupancy_start_at"] = start_raw
    reel["_occupancy_start_dt"] = start_dt
    reel["occupancy_end_at"] = None
    reel["shipped_at"] = None
    reel["returned_at"] = None
    reel["status"] = "LOADED"
    touch(reel)

    lot["process_state"] = "PACKAGED"
    touch(lot)
    return response.ok(view("reel", reel))


# --------------------------------------------------------------------------
# Reel returns
# --------------------------------------------------------------------------
@bp.route("/reels/<reel_id>/returns", methods=["POST"])
def create_reel_return(reel_id):
    require_auth("ShippingClerk", "PlantAdmin")
    b = validation.body()
    shipment_id = validation.f_str(b, "shipment_id")
    returned_date = validation.f_date(b, "returned_date")
    condition = validation.f_enum(b, "condition", C.RETURN_CONDITIONS)

    reel = lookups.reel(reel_id)
    shipment = lookups.shipment(shipment_id)

    if reel["status"] != "RETURN_PENDING":
        errors.fail(
            errors.ERR_INVALID_REEL_STATE,
            "Only a reel at RETURN_PENDING may be received back (this one is %s)"
            % reel["status"],
        )

    shipped_day = parse_iso_dt(reel["shipped_at"]).date()
    if condition == "GOOD" and parse_ymd(returned_date) < shipped_day:
        validation.bad("returned_date may not precede the reel's shipped date")

    days_out = day_diff(parse_ymd(returned_date), shipped_day)
    refund, variant = pricing.reel_deposit_refund(reel, condition, days_out)
    forfeited = money(D(reel["deposit_usd"]) - D(refund))

    row = new_record(common_fields=False)
    row.update({
        "reel_id": reel["id"],
        "shipment_id": shipment["id"],
        "returned_date": returned_date,
        "condition": condition,
        "days_out": days_out,
        "refund_usd": refund,
        "forfeited_usd": forfeited,
        "refund_variant_applied": variant,
    })
    db.reel_returns[row["id"]] = row

    customer = (
        db.customers.get(reel["held_by_customer_id"])
        if reel["held_by_customer_id"] is not None
        else None
    )
    cycles_before = reel["cycle_count"]

    reel["returned_at"] = clock.now_iso()
    reel["last_return_condition"] = condition
    reel["cycle_count"] = cycles_before + 1
    reel["current_lot_id"] = None
    reel["held_by_customer_id"] = None
    reel["loaded_length_ft"] = 0
    if condition == "GOOD":
        reel["status"] = "AVAILABLE"
    elif cycles_before < C.REEL_CYCLE_LIMIT:
        reel["status"] = "DAMAGED"
    else:
        reel["status"] = "RETIRED"
    touch(reel)

    if customer is not None:
        customer["credit_memo_balance_usd"] = money(
            D(customer["credit_memo_balance_usd"]) + D(refund)
        )
        customer["forfeited_deposit_total_usd"] = money(
            D(customer["forfeited_deposit_total_usd"]) + D(forfeited)
        )
        # Hop two: exposure is recomputed and credit standing re-evaluated.
        ledger.recompute_credit(customer)

    return response.created(view("reel_return", row))


@bp.route("/reels/<reel_id>/returns", methods=["GET"])
def list_reel_returns(reel_id):
    require_auth("ShippingClerk", "BillingAnalyst", "PlantAdmin")
    limit, offset = validation.pagination()
    condition = validation.q_enum("condition", C.RETURN_CONDITIONS)
    reel = lookups.reel(reel_id)

    rows = [r for r in db.reel_returns.values() if r["reel_id"] == reel["id"]]
    if condition is not None:
        rows = [r for r in rows if r["condition"] == condition]
    rows = sort_created(rows)
    page, total = response.paginate(rows, limit, offset)
    return response.ok_list(views("reel_return", page), limit, offset, total)
