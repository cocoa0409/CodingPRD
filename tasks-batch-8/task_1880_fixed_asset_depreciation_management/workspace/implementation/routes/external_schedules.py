"""ExternalSchedule endpoints."""
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint
import db
import errors
from db import new_id, now_iso
from middleware import (require_roles, get_body, get_pagination,
                        require_string, require_enum, require_int, optional_int)
from response import success_object, success_list
from services.serializers import external_schedule_view

bp = Blueprint("external_schedules", __name__)
ALL_ROLES = ("AssetAccountant", "Controller", "InventoryClerk", "TaxAnalyst")
SCHEDULE_TYPES = {"PROPERTY_TAX", "INSURANCE"}
MILL_RATE = Decimal("0.0125")


@bp.route("/external-schedules", methods=["POST"])
def create_schedule():
    require_roles("TaxAnalyst")
    data = get_body()
    asset_id = require_string(data, "asset_id")
    schedule_type = require_enum(data, "schedule_type", SCHEDULE_TYPES)
    schedule_year = require_int(data, "schedule_year")
    assessed = optional_int(data, "assessed_value_cents")
    premium = optional_int(data, "annual_premium_cents")

    asset = db.fixed_assets.get(asset_id)
    if asset is None:
        raise errors.not_found("asset_id not found")
    # uniqueness (priority 6)
    for s in db.external_schedules.values():
        if (s["asset_id"] == asset_id and s["schedule_type"] == schedule_type
                and s["schedule_year"] == schedule_year):
            raise errors.duplicate_schedule()
    # field-value (priority 8)
    if schedule_type == "PROPERTY_TAX":
        if assessed is None:
            raise errors.invalid_schedule_fields("PROPERTY_TAX requires assessed_value_cents")
        if premium is not None:
            raise errors.invalid_schedule_fields("annual_premium_cents must be null for PROPERTY_TAX")
    else:
        if premium is None:
            raise errors.invalid_schedule_fields("INSURANCE requires annual_premium_cents")
        if assessed is not None:
            raise errors.invalid_schedule_fields("assessed_value_cents must be null for INSURANCE")

    pta = None
    if schedule_type == "PROPERTY_TAX":
        pta = int((Decimal(assessed) * MILL_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    ts = now_iso()
    rec = {
        "id": new_id(),
        "asset_id": asset_id,
        "schedule_type": schedule_type,
        "schedule_year": schedule_year,
        "assessed_value_cents": assessed if schedule_type == "PROPERTY_TAX" else None,
        "annual_premium_cents": premium if schedule_type == "INSURANCE" else None,
        "property_tax_amount_cents": pta,
        "status": "IMPORTED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.external_schedules[rec["id"]] = rec
    return success_object(external_schedule_view(rec), 201)


@bp.route("/fixed-assets/<aid>/external-schedules", methods=["GET"])
def list_asset_schedules(aid):
    require_roles(*ALL_ROLES)
    asset = db.fixed_assets.get(aid)
    if asset is None:
        raise errors.not_found("Fixed asset not found")
    limit, offset = get_pagination()
    items = sorted(
        (s for s in db.external_schedules.values() if s["asset_id"] == aid),
        key=lambda r: (r["created_at"], r["id"]),
    )
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([external_schedule_view(r) for r in page], limit, offset, total)


@bp.route("/external-schedules/<sid>/apply", methods=["POST"])
def apply_schedule(sid):
    require_roles("Controller")
    rec = db.external_schedules.get(sid)
    if rec is None:
        raise errors.not_found("External schedule not found")
    if rec["status"] != "IMPORTED":
        raise errors.invalid_state("Schedule is not IMPORTED")
    asset = db.fixed_assets.get(rec["asset_id"])
    if asset is None:
        raise errors.not_found("Asset not found")
    if asset["status"] == "DISPOSED":
        raise errors.already_disposed()
    rec["status"] = "APPLIED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(external_schedule_view(rec))
