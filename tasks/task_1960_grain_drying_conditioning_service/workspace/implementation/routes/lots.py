"""Grain lots, load-out, charge-preview (PRD §3.2, §3.3, §3.6)."""

from flask import Blueprint, request

from db import current_date, public, sort_by_creation, stamp_new, store, touch
from errors import raise_err
from middleware import get_ctx, require_roles
from response import success
from routes.helpers import (
    check_grower_on_lot,
    get_customer,
    get_lot,
    scope_lots_for_grower,
)
from services.calculations import drying_charge, find_schedule
from validation import get_body, opt_num, paginate, req_enum, req_int, req_num

bp = Blueprint("lots", __name__)

COMMODITIES = {"CORN", "SOYBEAN", "WHEAT"}
LOT_STATUSES = {
    "RECEIVED", "TESTED", "QUEUED", "DRYING", "DRIED",
    "DAMAGE_HOLD", "STORED", "LOADED_OUT", "BLENDED_OUT",
}
READ_ROLES = {"ElevatorManager", "Grower", "IntakeTechnician", "DryerOperator", "ClaimsAdjuster"}


@bp.post("/grain-lots")
def create_lot():
    ctx = get_ctx()
    require_roles(ctx, {"IntakeTechnician"})
    body = get_body()
    # priority 4: body FK existence before shape (§2.9)
    if body.get("customer_id") is not None:
        get_customer(body["customer_id"])
    # priority 5: request shape
    customer_id = body.get("customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        raise_err("ERR_INVALID_REQUEST", "Field customer_id is required")
    commodity = req_enum(body, "commodity", COMMODITIES)
    gross = req_int(body, "gross_weight_lbs")
    tare = req_int(body, "tare_weight_lbs")
    if not (tare > 0 and gross > tare):
        raise_err("ERR_INVALID_REQUEST", "gross_weight_lbs must be greater than tare_weight_lbs and tare_weight_lbs positive")
    target = req_num(body, "target_moisture_pct", minimum=10.0, maximum=20.0)
    fm = opt_num(body, "foreign_material_pct", default=0.0, minimum=0.0)
    rec = stamp_new(
        {
            "customer_id": customer_id,
            "commodity": commodity,
            "gross_weight_lbs": gross,
            "tare_weight_lbs": tare,
            "wet_net_weight_lbs": gross - tare,
            "foreign_material_pct": fm,
            "target_moisture_pct": target,
            "intake_moisture_pct": None,
            "current_moisture_pct": None,
            "certified_test_id": None,
            "provisional_shrink_pct": None,
            "provisional_dry_weight_lbs": None,
            "final_dry_weight_lbs": None,
            "final_shrink_pct": None,
            "shrink_variance_lbs": None,
            "status": "RECEIVED",
            "ownership": "GROWER_HELD",
            "current_owner_id": customer_id,
        }
    )
    store.lots[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.get("/grain-lots")
def list_lots():
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    records = scope_lots_for_grower(ctx, list(store.lots.values()))
    for field in ("customer_id", "current_owner_id", "certified_test_id", "status", "commodity"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]
    records = sort_by_creation(records)
    page, meta = paginate(records, request.args)
    return success([public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/grain-lots/<lid>")
def get_one_lot(lid):
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    rec = get_lot(lid)
    check_grower_on_lot(ctx, rec)
    return success(public(rec))


@bp.post("/grain-lots/<lid>/load-out")
def load_out_lot(lid):
    ctx = get_ctx()
    require_roles(ctx, {"IntakeTechnician"})
    rec = get_lot(lid)
    # priority 6: state permission
    if rec["status"] == "DAMAGE_HOLD":
        raise_err("ERR_LOT_ON_DAMAGE_HOLD", "Operation blocked while lot is in DAMAGE_HOLD")
    if rec["status"] in ("LOADED_OUT", "BLENDED_OUT"):
        raise_err("ERR_ALREADY_TERMINAL", "Lot is in a terminal state")
    if rec["status"] != "DRIED":
        raise_err("ERR_INVALID_STATE", "Lot must be DRIED to load out")
    live = [
        a for a in store.agreements.values()
        if a["lot_id"] == rec["id"] and a["status"] in ("RESERVED", "ACTIVE")
    ]
    if live:
        raise_err("ERR_INVALID_STATE", "Lot has a RESERVED or ACTIVE storage agreement")
    rec["status"] = "LOADED_OUT"
    touch(rec)
    return success(public(rec))


@bp.get("/grain-lots/<lid>/charge-preview")
def charge_preview(lid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager", "Grower", "IntakeTechnician"})
    rec = get_lot(lid)
    check_grower_on_lot(ctx, rec)
    # requires a certified moisture baseline
    if rec["certified_test_id"] is None or rec["intake_moisture_pct"] is None:
        raise_err("ERR_INVALID_STATE", "Lot does not carry a certified moisture baseline")
    schedule = find_schedule(rec["commodity"], current_date())
    if schedule is None:
        raise_err("ERR_SCHEDULE_NOT_FOUND", "No charge-schedule window covers the service date")
    figures = drying_charge(rec, schedule)
    data = {
        "lot_id": rec["id"],
        "schedule_id": schedule["id"],
        "bushels": figures["bushels"],
        "points_removed": figures["points_removed"],
        "rate_cents_per_pt_bu": figures["rate_cents_per_pt_bu"],
        "fm_surcharge_applied": figures["fm_surcharge_applied"],
        "drying_charge_cents": figures["drying_charge_cents"],
    }
    return success(data)
