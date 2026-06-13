"""Catalog & config routes: catalogs, device-models, promotion-campaigns,
inspection-slots (PRD 3.1, 3.2, 3.8)."""
from flask import Blueprint

from db import db
from errors import (err, ERR_DUPLICATE, ERR_INVALID_MULTIPLIERS, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_PROMO_WINDOW_OVERLAP, ERR_SLOT_OVERLAP)
from middleware import get_principal, require_role
from models import new_record, touch, serialize, sort_by_created
from reqs import (get_json_body, req_str, req_int, req_number, req_enum,
                  req_str_list, parse_pagination, paginate)
from response import object_response, array_response
from services.lookups import get_catalog_or_404, get_device_model_or_404
from util import parse_iso
from datetime import timedelta
from flask import request

bp = Blueprint("catalogs", __name__)

CATEGORIES = {"SMARTPHONE", "LAPTOP", "TABLET", "REFRIGERATOR", "WASHER", "TV", "WEARABLE"}
PROMO_SCOPES = CATEGORIES | {"ALL"}
GRADE_KEYS = {"FLAWLESS", "GOOD", "FAIR", "POOR"}
DEFECT_KEYS = {"CRACKED_SCREEN", "BATTERY_DEGRADED", "WATER_DAMAGE", "MISSING_PARTS",
               "WONT_POWER_ON", "DENTED_BODY"}

SLOT_BUFFER = timedelta(minutes=30)


# ---------------------------------------------------------------- Catalogs
@bp.route("/catalogs", methods=["POST"])
def create_catalog():
    _, role = get_principal()
    require_role(role, {"CatalogAdmin"})
    body = get_json_body()

    name = req_str(body, "name")
    currency = req_str(body, "currency", required=False, default="USD")
    price_lock_hours = req_int(body, "price_lock_hours", required=False, default=168)
    requote_tolerance_pct = req_number(body, "requote_tolerance_pct", required=False, default=0.15)
    data_wipe_required_categories = req_str_list(body, "data_wipe_required_categories",
                                                 required=False, default=[])
    recycle_floor_value_cents = req_int(body, "recycle_floor_value_cents",
                                        required=False, default=0)

    for c in data_wipe_required_categories:
        if c not in CATEGORIES:
            raise err(ERR_INVALID_REQUEST, f"invalid category: {c}")

    # Uniqueness: catalog name (PRD 3.1).
    for cat in db.catalogs.values():
        if cat["name"] == name:
            raise err(ERR_DUPLICATE, "catalog name already exists")

    rec = new_record("Catalog", {
        "name": name,
        "currency": currency,
        "price_lock_hours": price_lock_hours,
        "requote_tolerance_pct": requote_tolerance_pct,
        "data_wipe_required_categories": data_wipe_required_categories,
        "recycle_floor_value_cents": recycle_floor_value_cents,
    })
    db.catalogs[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/catalogs/<cid>", methods=["GET"])
def get_catalog(cid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "FinanceOperator", "GradingAgent"})
    rec = get_catalog_or_404(cid)
    return object_response(serialize(rec))


# ---------------------------------------------------------------- Device models
@bp.route("/catalogs/<cid>/device-models", methods=["POST"])
def create_device_model(cid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin"})
    catalog = get_catalog_or_404(cid)
    body = get_json_body()

    manufacturer = req_str(body, "manufacturer")
    model_code = req_str(body, "model_code")
    category = req_enum(body, "category", CATEGORIES)
    base_value_cents = req_int(body, "base_value_cents")
    if "condition_multipliers" not in body or body["condition_multipliers"] is None:
        raise err(ERR_INVALID_REQUEST, "missing required field: condition_multipliers")
    if "defect_deductions" not in body or body["defect_deductions"] is None:
        raise err(ERR_INVALID_REQUEST, "missing required field: defect_deductions")
    condition_multipliers = body["condition_multipliers"]
    defect_deductions = body["defect_deductions"]

    if not isinstance(condition_multipliers, dict):
        raise err(ERR_INVALID_REQUEST, "condition_multipliers must be an object")
    if not isinstance(defect_deductions, dict):
        raise err(ERR_INVALID_REQUEST, "defect_deductions must be an object")

    # defect_deductions keys must be drawn from the known defect set; values int.
    for k, v in defect_deductions.items():
        if k not in DEFECT_KEYS:
            raise err(ERR_INVALID_REQUEST, f"unknown defect key: {k}")
        if isinstance(v, bool) or not isinstance(v, int):
            raise err(ERR_INVALID_REQUEST, "defect deduction must be an integer")

    # condition_multipliers must define exactly {FLAWLESS,GOOD,FAIR,POOR}, each in [0,1].
    if set(condition_multipliers.keys()) != GRADE_KEYS:
        raise err(ERR_INVALID_MULTIPLIERS,
                  "condition_multipliers must define exactly FLAWLESS, GOOD, FAIR, POOR")
    for k, v in condition_multipliers.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise err(ERR_INVALID_MULTIPLIERS, "multiplier must be a number")
        if v < 0 or v > 1:
            raise err(ERR_INVALID_MULTIPLIERS, "multiplier must be in [0,1]")

    # model_code unique per catalog among non-RETIRED models (case-insensitive).
    for m in db.device_models.values():
        if (m["catalog_id"] == cid and m["status"] != "RETIRED"
                and m["model_code"].lower() == model_code.lower()):
            raise err(ERR_DUPLICATE, "model_code already exists in this catalog")

    rec = new_record("DeviceModel", {
        "catalog_id": catalog["id"],
        "manufacturer": manufacturer,
        "model_code": model_code,
        "category": category,
        "base_value_cents": base_value_cents,
        "condition_multipliers": condition_multipliers,
        "defect_deductions": defect_deductions,
        "status": "ACTIVE",
    })
    db.device_models[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/catalogs/<cid>/device-models", methods=["GET"])
def list_device_models(cid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "GradingAgent", "Customer"})
    get_catalog_or_404(cid)
    limit, offset = parse_pagination()

    category = request.args.get("category")
    model_code = request.args.get("model_code")
    items = [m for m in db.device_models.values() if m["catalog_id"] == cid]
    if category is not None:
        items = [m for m in items if m["category"] == category]
    if model_code is not None:
        items = [m for m in items if m["model_code"] == model_code]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serialize(m) for m in page], limit, offset, total)


@bp.route("/device-models/<mid>", methods=["GET"])
def get_device_model(mid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "GradingAgent", "Customer"})
    rec = get_device_model_or_404(mid)
    return object_response(serialize(rec))


@bp.route("/device-models/<mid>/retire", methods=["POST"])
def retire_device_model(mid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin"})
    rec = get_device_model_or_404(mid)
    rec["status"] = "RETIRED"
    touch(rec)
    return object_response(serialize(rec))


# ---------------------------------------------------------------- Promotion campaigns
def _intervals_overlap(a_from, a_to, b_from, b_to):
    """Half-open [from, to) overlap: a_from < b_to and b_from < a_to."""
    return a_from < b_to and b_from < a_to


def _lanes_collide(scope_a, scope_b):
    return scope_a == scope_b or scope_a == "ALL" or scope_b == "ALL"


@bp.route("/catalogs/<cid>/promotion-campaigns", methods=["POST"])
def create_promotion_campaign(cid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin"})
    catalog = get_catalog_or_404(cid)
    body = get_json_body()

    code = req_str(body, "code")
    category_scope = req_enum(body, "category_scope", PROMO_SCOPES)
    effective_from_raw = req_str(body, "effective_from")
    effective_to_raw = req_str(body, "effective_to")
    bonus_pct = req_number(body, "bonus_pct", required=False, default=0)
    bonus_flat_cents = req_int(body, "bonus_flat_cents", required=False, default=0)
    bonus_cap_cents = req_int(body, "bonus_cap_cents")

    effective_from = parse_iso(effective_from_raw)
    effective_to = parse_iso(effective_to_raw)
    if not (effective_to > effective_from):
        raise err(ERR_INVALID_REQUEST, "effective_to must be after effective_from")

    # code unique per catalog among ACTIVE campaigns (case-insensitive).
    for p in db.promotion_campaigns.values():
        if (p["catalog_id"] == cid and p["status"] == "ACTIVE"
                and p["code"].lower() == code.lower()):
            raise err(ERR_DUPLICATE, "promo code already exists in this catalog")

    # Window-overlap on category lane among ACTIVE campaigns (half-open intervals).
    for p in db.promotion_campaigns.values():
        if p["catalog_id"] != cid or p["status"] != "ACTIVE":
            continue
        if not _lanes_collide(category_scope, p["category_scope"]):
            continue
        p_from = parse_iso(p["effective_from"])
        p_to = parse_iso(p["effective_to"])
        if _intervals_overlap(effective_from, effective_to, p_from, p_to):
            raise err(ERR_PROMO_WINDOW_OVERLAP,
                      "promotion window overlaps an active campaign on this lane")

    rec = new_record("PromotionCampaign", {
        "catalog_id": catalog["id"],
        "code": code,
        "category_scope": category_scope,
        "effective_from": effective_from_raw,
        "effective_to": effective_to_raw,
        "bonus_pct": bonus_pct,
        "bonus_flat_cents": bonus_flat_cents,
        "bonus_cap_cents": bonus_cap_cents,
        "status": "ACTIVE",
    })
    db.promotion_campaigns[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/catalogs/<cid>/promotion-campaigns", methods=["GET"])
def list_promotion_campaigns(cid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "Customer"})
    get_catalog_or_404(cid)
    limit, offset = parse_pagination()

    code = request.args.get("code")
    status = request.args.get("status")
    items = [p for p in db.promotion_campaigns.values() if p["catalog_id"] == cid]
    if code is not None:
        items = [p for p in items if p["code"] == code]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serialize(p) for p in page], limit, offset, total)


@bp.route("/promotion-campaigns/<pid>/expire", methods=["POST"])
def expire_promotion_campaign(pid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin"})
    from services.lookups import get_or_404
    rec = get_or_404(db.promotion_campaigns, pid)
    rec["status"] = "EXPIRED"
    touch(rec)
    return object_response(serialize(rec))


# ---------------------------------------------------------------- Inspection slots
@bp.route("/catalogs/<cid>/inspection-slots", methods=["POST"])
def create_inspection_slot(cid):
    _, role = get_principal()
    require_role(role, {"GradingAgent", "CatalogAdmin"})
    catalog = get_catalog_or_404(cid)
    body = get_json_body()

    lane_category = req_enum(body, "lane_category", CATEGORIES)
    slot_start_raw = req_str(body, "slot_start")
    slot_end_raw = req_str(body, "slot_end")
    slot_start = parse_iso(slot_start_raw)
    slot_end = parse_iso(slot_end_raw)
    if not (slot_end > slot_start):
        raise err(ERR_INVALID_REQUEST, "slot_end must be after slot_start")

    # Buffered closed-interval overlap vs existing BOOKED slots on same lane.
    new_lo = slot_start - SLOT_BUFFER
    new_hi = slot_end + SLOT_BUFFER
    for s in db.inspection_slots.values():
        if s["catalog_id"] != cid or s["status"] != "BOOKED":
            continue
        if s["lane_category"] != lane_category:
            continue
        s_start = parse_iso(s["slot_start"])
        s_end = parse_iso(s["slot_end"])
        # Closed intervals: overlap iff new_lo <= s_end AND s_start <= new_hi.
        if new_lo <= s_end and s_start <= new_hi:
            raise err(ERR_SLOT_OVERLAP, "slot overlaps an existing booked slot on this lane")

    rec = new_record("InspectionSlot", {
        "catalog_id": catalog["id"],
        "lane_category": lane_category,
        "slot_start": slot_start_raw,
        "slot_end": slot_end_raw,
        "status": "BOOKED",
    })
    db.inspection_slots[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/catalogs/<cid>/inspection-slots", methods=["GET"])
def list_inspection_slots(cid):
    _, role = get_principal()
    require_role(role, {"GradingAgent", "CatalogAdmin"})
    get_catalog_or_404(cid)
    limit, offset = parse_pagination()

    lane_category = request.args.get("lane_category")
    status = request.args.get("status")
    items = [s for s in db.inspection_slots.values() if s["catalog_id"] == cid]
    if lane_category is not None:
        items = [s for s in items if s["lane_category"] == lane_category]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serialize(s) for s in page], limit, offset, total)


@bp.route("/inspection-slots/<sid>/release", methods=["POST"])
def release_inspection_slot(sid):
    _, role = get_principal()
    require_role(role, {"GradingAgent", "CatalogAdmin"})
    from services.lookups import get_or_404
    rec = get_or_404(db.inspection_slots, sid)
    if rec["status"] != "BOOKED":
        raise err(ERR_INVALID_STATE, "slot is not BOOKED")
    rec["status"] = "RELEASED"
    touch(rec)
    return object_response(serialize(rec))
