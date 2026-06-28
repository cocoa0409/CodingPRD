"""Clock, Herd, Parlor, Ration, CoopPriceSheet routes."""
from flask import Blueprint, request, g

import db
import errors
import serializers
import calculations
from errors import err
from middleware import require_roles
from records import make_record
from response import object_response, array_response
from domain import paginate, sorted_by_creation
from util import iso_format
import clock
import validators as V

bp = Blueprint("core", __name__)

ALL_ROLES = ("HerdManager", "ParlorTech", "Veterinarian", "CoopSettlementAgent", "Auditor")
READ_ROLES = ALL_ROLES


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
@bp.route("/herds/_clock/set_current_utc", methods=["POST"])
@require_roles(*ALL_ROLES)
def set_clock():
    body = V.require_json_object()
    instant = V.require_datetime(body, "to_iso8601")
    clock.set_clock(instant)
    return object_response({"current_utc": iso_format(clock.now())}, 200)


# ---------------------------------------------------------------------------
# Herd (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.route("/herds", methods=["POST"])
@require_roles("HerdManager")
def create_herd():
    body = V.require_json_object()
    name = V.require_str(body, "name")
    federal_order_number = V.require_str(body, "federal_order_number")
    with db.lock:
        rec = make_record({
            "name": name,
            "federal_order_number": federal_order_number,
            "milk_quality_status": "GOOD",
        })
        db.herds[rec["id"]] = rec
        return object_response(serializers.herd_out(rec), 201)


@bp.route("/herds", methods=["GET"])
@require_roles(*READ_ROLES)
def list_herds():
    items = sorted_by_creation(list(db.herds.values()))
    page, limit, offset, total = paginate(items, request.args)
    return array_response([serializers.herd_out(r) for r in page], limit, offset, total)


@bp.route("/herds/<herd_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_herd(herd_id):
    rec = V.get_or_404("herd", herd_id)
    return object_response(serializers.herd_out(rec), 200)


# ---------------------------------------------------------------------------
# Parlor (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.route("/herds/parlors", methods=["POST"])
@require_roles("HerdManager")
def create_parlor():
    body = V.require_json_object()
    herd_id = V.require_fk(body, "herd_id")
    name = V.require_str(body, "name")
    stall_capacity = V.require_int(body, "stall_capacity", minimum=1)
    turnaround_minutes = V.opt_int(body, "turnaround_minutes", default=0, minimum=0)
    # existence (priority 3)
    V.get_or_404("herd", herd_id)
    with db.lock:
        rec = make_record({
            "herd_id": herd_id,
            "name": name,
            "stall_capacity": stall_capacity,
            "turnaround_minutes": turnaround_minutes,
        })
        db.parlors[rec["id"]] = rec
        return object_response(serializers.parlor_out(rec), 201)


@bp.route("/herds/parlors", methods=["GET"])
@require_roles(*READ_ROLES)
def list_parlors():
    items = list(db.parlors.values())
    herd_id = request.args.get("herd_id")
    if herd_id is not None:
        items = [r for r in items if r["herd_id"] == herd_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items, request.args)
    return array_response([serializers.parlor_out(r) for r in page], limit, offset, total)


@bp.route("/herds/parlors/<parlor_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_parlor(parlor_id):
    rec = V.get_or_404("parlor", parlor_id)
    return object_response(serializers.parlor_out(rec), 200)


# ---------------------------------------------------------------------------
# Ration (PRD §3.1)
# ---------------------------------------------------------------------------
def _validate_ingredients(body):
    if "ingredients" not in body:
        raise V.invalid("Missing field: ingredients")
    ingredients = body["ingredients"]
    if not isinstance(ingredients, list):
        raise V.invalid("ingredients must be an array")
    parsed = []
    for ing in ingredients:
        if not isinstance(ing, dict):
            raise V.invalid("each ingredient must be an object")
        ing_name = ing.get("ingredient_name")
        if not isinstance(ing_name, str) or not ing_name.strip():
            raise V.invalid("ingredient_name must be a non-empty string")
        lbs = ing.get("lbs_as_fed")
        price = ing.get("price_per_lb")
        for label, num in (("lbs_as_fed", lbs), ("price_per_lb", price)):
            if isinstance(num, bool) or not isinstance(num, (int, float)):
                raise V.invalid("%s must be a number" % label)
            if num < 0:
                raise V.invalid("%s must be >= 0" % label)
        parsed.append({
            "ingredient_name": ing_name,
            "lbs_as_fed": lbs,
            "price_per_lb": price,
        })
    return parsed


@bp.route("/herds/rations", methods=["POST"])
@require_roles("HerdManager")
def create_ration():
    body = V.require_json_object()
    herd_id = V.require_fk(body, "herd_id")
    name = V.require_str(body, "name")
    ingredients = _validate_ingredients(body)
    V.get_or_404("herd", herd_id)
    with db.lock:
        cost = calculations.daily_feed_cost(ingredients)
        rec = make_record({
            "herd_id": herd_id,
            "name": name,
            "ingredients": ingredients,
            "daily_feed_cost_per_cow": cost,
            "status": "ACTIVE",
        })
        db.rations[rec["id"]] = rec
        return object_response(serializers.ration_out(rec), 201)


@bp.route("/herds/rations", methods=["GET"])
@require_roles("HerdManager", "Veterinarian", "CoopSettlementAgent", "Auditor")
def list_rations():
    items = list(db.rations.values())
    herd_id = request.args.get("herd_id")
    if herd_id is not None:
        items = [r for r in items if r["herd_id"] == herd_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items, request.args)
    return array_response([serializers.ration_out(r) for r in page], limit, offset, total)


@bp.route("/herds/rations/<ration_id>", methods=["GET"])
@require_roles("HerdManager", "Veterinarian", "CoopSettlementAgent", "Auditor")
def get_ration(ration_id):
    rec = V.get_or_404("ration", ration_id)
    return object_response(serializers.ration_out(rec), 200)


# ---------------------------------------------------------------------------
# CoopPriceSheet (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.route("/herds/coop-price-sheets", methods=["POST"])
@require_roles("CoopSettlementAgent")
def create_price_sheet():
    body = V.require_json_object()
    herd_id = V.require_fk(body, "herd_id")
    settlement_month = V.require_str(body, "settlement_month")
    fat = V.require_number(body, "fat_price_per_lb")
    protein = V.require_number(body, "protein_price_per_lb")
    other_solids = V.require_number(body, "other_solids_price_per_lb")
    ppd = V.require_number(body, "ppd_per_cwt")
    advance = V.require_number(body, "advance_rate_per_cwt")
    hauling = V.opt_number(body, "hauling_rate_per_cwt", default=0)
    # existence
    V.get_or_404("herd", herd_id)
    with db.lock:
        # uniqueness: settlement_month unique within herd (priority 7)
        for existing in db.coop_price_sheets.values():
            if existing["herd_id"] == herd_id and existing["settlement_month"] == settlement_month:
                raise err(errors.ERR_DUPLICATE_KEY,
                          "settlement_month already exists for this herd")
        rec = make_record({
            "herd_id": herd_id,
            "settlement_month": settlement_month,
            "fat_price_per_lb": fat,
            "protein_price_per_lb": protein,
            "other_solids_price_per_lb": other_solids,
            "ppd_per_cwt": ppd,
            "advance_rate_per_cwt": advance,
            "hauling_rate_per_cwt": hauling,
        })
        db.coop_price_sheets[rec["id"]] = rec
        return object_response(serializers.price_sheet_out(rec), 201)


@bp.route("/herds/coop-price-sheets", methods=["GET"])
@require_roles("HerdManager", "CoopSettlementAgent", "Auditor")
def list_price_sheets():
    items = list(db.coop_price_sheets.values())
    herd_id = request.args.get("herd_id")
    if herd_id is not None:
        items = [r for r in items if r["herd_id"] == herd_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items, request.args)
    return array_response([serializers.price_sheet_out(r) for r in page], limit, offset, total)


@bp.route("/herds/coop-price-sheets/<price_sheet_id>", methods=["GET"])
@require_roles("HerdManager", "CoopSettlementAgent", "Auditor")
def get_price_sheet(price_sheet_id):
    rec = V.get_or_404("price_sheet", price_sheet_id)
    return object_response(serializers.price_sheet_out(rec), 200)
