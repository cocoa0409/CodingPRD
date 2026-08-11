"""Catalog styles and physical house stock (PRD 3.3)."""

from flask import Blueprint

import auth
import constants as K
import envelope
import listing
import lookup
import serialize
import shape
import store
from errors import ApiError

bp = Blueprint("catalog", __name__)


def void_draft_assessments_for_unit(unit_id):
    """A DRAFT record is voided outright when its covered unit reaches RETIRED."""
    for record in store.all_rows("assessments"):
        if record["unit_id"] == unit_id and record["status"] == "DRAFT":
            record["status"] = "VOIDED"
            store.touch(record)


@bp.post("/kidswear/garment-styles")
def create_style():
    auth.gate("MerchandisePlanner")
    body = shape.body_json()
    sku = shape.string(body, "sku")
    name = shape.string(body, "name")
    brand_tier = shape.enum_in(body, "brand_tier", K.BRAND_TIERS)
    retail_price_cents = shape.integer(body, "retail_price_cents", minimum=100)
    size_code = shape.enum_in(body, "size_code", K.SIZE_LADDER)
    season = shape.enum_in(body, "season", K.SEASONS)
    category = shape.string(body, "category")
    demand_band = shape.enum_in(body, "demand_band", K.DEMAND_BANDS,
                                required=False, default="MEDIUM")
    for existing in store.db["styles"].values():
        if existing["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_SKU")
    row = store.insert("styles", {
        "sku": sku,
        "name": name,
        "brand_tier": brand_tier,
        "retail_price_cents": retail_price_cents,
        "size_code": size_code,
        "season": season,
        "category": category,
        "demand_band": demand_band,
        "units_ever_acquired": 0,
        "status": "ACTIVE",
    })
    return envelope.created(serialize.style(row))


@bp.get("/kidswear/garment-styles")
def list_styles():
    auth.gate("MerchandisePlanner", "WarehouseOperator", "Member",
              "PlatformAdmin", "GradingTechnician")
    rows = store.all_rows("styles")
    rows = listing.eq(rows, "size_code", shape.query_member("size_code", K.SIZE_LADDER))
    rows = listing.eq(rows, "season", shape.query_member("season", K.SEASONS))
    rows = listing.eq(rows, "brand_tier", shape.query_member("brand_tier", K.BRAND_TIERS))
    rows = listing.eq(rows, "status", shape.query_member("status", K.STYLE_STATUSES))
    return envelope.listing(rows, serialize.style)


@bp.get("/kidswear/garment-styles/<style_id>")
def read_style(style_id):
    auth.gate("MerchandisePlanner", "WarehouseOperator", "Member", "PlatformAdmin")
    return envelope.ok(serialize.style(lookup.style(style_id)))


@bp.patch("/kidswear/garment-styles/<style_id>")
def update_style(style_id):
    auth.gate("MerchandisePlanner")
    body = shape.body_json()
    demand_band = shape.enum_in(body, "demand_band", K.DEMAND_BANDS,
                                required=False, default=None)
    status = shape.member_in(body, "status", K.STYLE_STATUSES, required=False, default=None)
    row = lookup.style(style_id)
    if demand_band is not None:
        row["demand_band"] = demand_band
    if status is not None:
        row["status"] = status
    store.touch(row)
    return envelope.ok(serialize.style(row))


@bp.post("/kidswear/garment-units")
def acquire_unit():
    auth.gate("MerchandisePlanner")
    body = shape.body_json()
    style_id = shape.id_string(body, "style_id")
    acquired_at = shape.instant(body, "acquired_at")
    capsule_id = shape.id_string(body, "capsule_id", required=False)
    current_grade = shape.member_in(body, "current_grade", K.GRADE_LADDER,
                                    required=False, default="A")
    cycles_completed = shape.integer(body, "cycles_completed", required=False,
                                     default=0, minimum=0)
    style = lookup.style(style_id)
    if capsule_id is not None:
        lookup.capsule(capsule_id)
    if style["status"] == "DISCONTINUED":
        raise ApiError("ERR_STYLE_DISCONTINUED")
    row = store.insert("units", {
        "style_id": style_id,
        "capsule_id": capsule_id,
        "state": "IN_STOCK",
        "acquisition_source": "PURCHASED",
        "acquired_at": acquired_at,
        "cycles_completed": cycles_completed,
        "cumulative_cleaning_cost_cents": 0,
        "current_grade": current_grade,
        "retired_reason": None,
        "retirement_eligible": False,
    })
    style["units_ever_acquired"] += 1
    store.touch(style)
    return envelope.created(serialize.unit(row))


@bp.get("/kidswear/garment-units")
def list_units():
    auth.gate("MerchandisePlanner", "WarehouseOperator", "PlatformAdmin",
              "CleaningVendor", "GradingTechnician", "Member")
    rows = store.all_rows("units")
    rows = listing.eq(rows, "style_id", shape.query_str("style_id"))
    rows = listing.eq(rows, "capsule_id", shape.query_str("capsule_id"))
    rows = listing.eq(rows, "state", shape.query_member("state", K.UNIT_STATES))
    return envelope.listing(rows, serialize.unit)


@bp.get("/kidswear/garment-units/<unit_id>")
def read_unit(unit_id):
    auth.gate("MerchandisePlanner", "WarehouseOperator", "PlatformAdmin",
              "CleaningVendor", "GradingTechnician", "Member")
    return envelope.ok(serialize.unit(lookup.unit(unit_id)))


@bp.post("/kidswear/garment-units/<unit_id>/retire")
def retire_unit(unit_id):
    auth.gate("MerchandisePlanner")
    body = shape.body_json()
    reason = shape.enum_in(body, "reason", K.RETIRED_REASONS)
    unit = lookup.unit(unit_id)
    if unit["state"] != "IN_STOCK":
        raise ApiError("ERR_UNIT_INVALID_STATE")
    unit["state"] = "RETIRED"
    unit["retired_reason"] = reason
    store.touch(unit)
    void_draft_assessments_for_unit(unit_id)
    return envelope.ok(serialize.unit(unit))
