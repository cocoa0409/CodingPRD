"""Grain lot endpoints: fill, read, list, carry analysis, shrink events
(PRD 3.1, 3.7, 3.9)."""
import math
from decimal import Decimal

from flask import Blueprint, request

import db
from clock import CLOCK
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services import core
from util import (as_bu, as_dt, as_enum, as_int, as_moisture, as_str, body,
                  paginate_sorted, query_enum, query_int_required, query_str,
                  required, resolve_body_fk, resolve_path)

bp = Blueprint("lots", __name__)


@bp.route("/grain/lots", methods=["POST"])
def create_lot():
    require_roles("SiteManager")
    data = body()
    # existence (4): body FK bin_id
    bin_rec = resolve_body_fk(db.bins, data, "bin_id", "bin")
    # shape (6)
    bin_id = as_str(required(data, "bin_id"), "bin_id")
    crop = as_enum(required(data, "crop"), "crop", core.CROPS)
    grade = as_enum(required(data, "grade"), "grade", core.GRADES)
    fill_date = as_dt(required(data, "fill_date"), "fill_date")
    original_bu = as_bu(required(data, "original_bu"), "original_bu")
    if original_bu <= 0:
        raise ApiError("ERR_VALIDATION", 400, "original_bu must be > 0")
    fill_moisture = as_moisture(required(data, "fill_moisture_pct"), "fill_moisture_pct")
    fill_basis = as_int(required(data, "fill_basis_cents"), "fill_basis_cents")
    ref_price = as_int(required(data, "reference_price_cents_per_bu"),
                       "reference_price_cents_per_bu")
    if ref_price <= 0:
        raise ApiError("ERR_VALIDATION", 400,
                       "reference_price_cents_per_bu must be > 0")
    # posture (15)
    if bin_rec["posture"] not in ("SOUND", "WATCH"):
        raise ApiError("ERR_BIN_POSTURE_BLOCKED", 409,
                       "bin posture blocks lot fills")
    # capacity (24): existing current_bu + new original_bu <= capacity
    existing = Decimal("0.00")
    for l in core.lots_of(bin_rec["id"]):
        existing += l["current_bu"]
    if core.q2(existing) + original_bu > bin_rec["capacity_bu"]:
        raise ApiError("ERR_BIN_CAPACITY_EXCEEDED", 409,
                       "fill would exceed bin capacity")
    # crop consistency (25)
    if crop != bin_rec["crop"]:
        raise ApiError("ERR_CROP_MIX", 409, "lot crop must equal bin crop")

    # provisional shrink (provisional_shrink calc): strictly-greater-than
    std = core.STANDARD_MOISTURE[crop]
    if fill_moisture > std:
        shrink = core.q2(original_bu * (fill_moisture - std)
                         * core.SHRINK_FACTOR / Decimal("100"))
    else:
        shrink = Decimal("0.00")
    current_bu = core.q2(original_bu - shrink)

    rec = core.new_common()
    rec.update({
        "bin_id": bin_id,
        "crop": crop,
        "grade": grade,
        "fill_date": fill_date,
        "original_bu": original_bu,
        "fill_moisture_pct": fill_moisture,
        "fill_basis_cents": fill_basis,
        "reference_price_cents_per_bu": ref_price,
        "current_moisture_pct": fill_moisture,
        "provisional_shrink_bu": shrink,
        "current_bu": current_bu,
        "drawn_bu": Decimal("0.00"),
        "cumulative_invisible_loss_bu": Decimal("0.00"),
        "cumulative_storage_charge_cents": 0,
        "months_assessed": 0,
        "status": "STORED",
    })
    db.lots[rec["id"]] = rec

    if shrink > 0:
        ev = core.new_event()
        ev.update({"lot_id": rec["id"], "kind": "PROVISIONAL",
                   "shrink_bu": shrink, "period": None})
        db.shrink_events[ev["id"]] = ev

    snap = core.bin_snap(bin_rec)
    core.recompute_inventory(bin_rec)
    core.recompute_posture(bin_rec)
    core.finalize_bin(bin_rec, snap)
    return ok(core.lot_view(rec), 201)


@bp.route("/grain/lots/<lid>", methods=["GET"])
def get_lot(lid):
    require_roles(*ALL_ROLES)
    return ok(core.lot_view(resolve_path(db.lots, lid, "lot")))


@bp.route("/grain/lots", methods=["GET"])
def list_lots():
    require_roles(*ALL_ROLES)
    f_bin = query_str("bin_id")
    f_status = query_enum("status", core.LOT_STATUSES)
    f_crop = query_enum("crop", core.CROPS)
    f_grade = query_enum("grade", core.GRADES)
    items = list(db.lots.values())
    if f_bin is not None:
        items = [l for l in items if l["bin_id"] == f_bin]
    if f_status is not None:
        items = [l for l in items if l["status"] == f_status]
    if f_crop is not None:
        items = [l for l in items if l["crop"] == f_crop]
    if f_grade is not None:
        items = [l for l in items if l["grade"] == f_grade]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([core.lot_view(l) for l in page], total, limit, offset)


@bp.route("/grain/lots/<lid>/carry-analysis", methods=["GET"])
def carry_analysis(lid):
    require_roles("SiteManager", "FarmOwner")
    lot = resolve_path(db.lots, lid, "lot")
    current_basis = query_int_required("current_basis_cents")
    variant = request_variant()
    now = CLOCK.now()
    months = core.month_diff(lot["fill_date"], now.year, now.month)
    rate = core.storage_rate_cents(months)
    storage_paid = lot["cumulative_storage_charge_cents"]
    projected = core.q0(lot["current_bu"] * rate)
    basis_gain = core.q0((current_basis - lot["fill_basis_cents"]) * lot["current_bu"])
    if variant == "ECONOMIC":
        days = math.floor((now - lot["fill_date"]).total_seconds() / 86400)
        interest = core.q0(lot["current_bu"] * lot["reference_price_cents_per_bu"]
                           * core.ANNUAL_INTEREST_PCT / Decimal("100")
                           * Decimal(days) / Decimal("365"))
    else:
        interest = 0
    net = basis_gain - storage_paid - projected - interest
    return ok({
        "lot_id": lot["id"],
        "variant": variant,
        "current_bu": core.f2(lot["current_bu"]),
        "storage_paid_cents": storage_paid,
        "projected_month_charge_cents": projected,
        "basis_gain_cents": basis_gain,
        "interest_cents": interest,
        "net_carry_cents": net,
        "recommendation": "HOLD" if net > 0 else "SELL",
    })


def request_variant():
    raw = request.args.get("variant")
    if raw is None:
        raise ApiError("ERR_VALIDATION", 400, "Missing required query parameter: variant")
    if raw not in core.CARRY_VARIANTS:
        raise ApiError("ERR_VALIDATION", 400, "variant must be CASH or ECONOMIC")
    return raw


@bp.route("/grain/lots/<lid>/shrink-events", methods=["GET"])
def list_shrink_events(lid):
    require_roles(*ALL_ROLES)
    lot = resolve_path(db.lots, lid, "lot")
    f_kind = query_enum("kind", core.SHRINK_KINDS)
    items = [e for e in db.shrink_events.values() if e["lot_id"] == lot["id"]]
    if f_kind is not None:
        items = [e for e in items if e["kind"] == f_kind]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([core.shrink_event_view(e) for e in page], total, limit, offset)
