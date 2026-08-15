"""LinenStock endpoints (PRD 3.1)."""
from flask import Blueprint, request

import services
import store
from auth import authenticate, authorize, ALL_ROLES
from errors import ERR_INVALID_REQUEST, ERR_NEGATIVE_INVENTORY, ERR_STALE_VERSION, \
    raise_err
from serializers import stock_out
from util import body_json, bump, fk_ref, get_or_404, list_response, new_record, \
    occ_field, req_enum, req_int, req_number, req_str, success_object

bp = Blueprint("stocks", __name__)

CATEGORIES = ["FLATWORK", "TERRY", "PATIENT_APPAREL", "ISOLATION"]


@bp.route("/linen-stocks", methods=["POST"])
def create_stock():
    _, role = authenticate()
    authorize(role, ["LinenManager"])
    body = body_json()

    fac = fk_ref(body, "facility_id", store.facilities, "Facility")
    sku = req_str(body, "sku")
    display_name = req_str(body, "display_name")
    category = req_enum(body, "category", CATEGORIES)
    piece_weight = req_number(body, "piece_weight_lbs")
    if piece_weight <= 0:
        raise_err(ERR_INVALID_REQUEST, "piece_weight_lbs must be > 0")
    unit_cost = req_int(body, "unit_cost_cents")
    if unit_cost < 0:
        raise_err(ERR_INVALID_REQUEST, "unit_cost_cents must be >= 0")
    max_wash = req_int(body, "max_wash_cycles")
    if max_wash < 1:
        raise_err(ERR_INVALID_REQUEST, "max_wash_cycles must be >= 1")
    reorder = req_int(body, "reorder_point_pieces")
    if reorder < 0:
        raise_err(ERR_INVALID_REQUEST, "reorder_point_pieces must be >= 0")
    opening = req_int(body, "opening_pieces")
    if opening < 0:
        raise_err(ERR_INVALID_REQUEST, "opening_pieces must be >= 0")
    opening_reserve = req_int(body, "opening_reserve_pieces")
    if opening_reserve < 0:
        raise_err(ERR_INVALID_REQUEST, "opening_reserve_pieces must be >= 0")

    # sku unique per facility
    for s in store.stocks.values():
        if s["facility_id"] == fac["id"] and s["sku"] == sku:
            raise_err(ERR_INVALID_REQUEST,
                      "sku %s already registered for this facility" % sku)

    rec = new_record()
    rec.update({
        "facility_id": fac["id"],
        "sku": sku,
        "display_name": display_name,
        "category": category,
        "piece_weight_lbs": piece_weight,
        "unit_cost_cents": unit_cost,
        "max_wash_cycles": max_wash,
        "reorder_point_pieces": reorder,
        "opening_pieces": opening,
        "opening_reserve_pieces": opening_reserve,
        "in_circulation": opening,
        "in_wash": 0,
        "reserve_pieces": opening_reserve,
        "retired_pieces": 0,
        "lost_pieces": 0,
        "wash_cycles_completed": 0,
        "shrinkage_status": "NORMAL",
    })
    store.stocks[rec["id"]] = rec
    return success_object(stock_out(rec), 201)


@bp.route("/linen-stocks/<stock_id>", methods=["GET"])
def get_stock(stock_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.stocks, stock_id, "LinenStock")
    return success_object(stock_out(rec))


@bp.route("/linen-stocks", methods=["GET"])
def list_stocks():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.stocks.values())
    facility_id = request.args.get("facility_id")
    if facility_id is not None:
        records = [r for r in records if r["facility_id"] == facility_id]
    category = request.args.get("category")
    if category is not None:
        records = [r for r in records if r["category"] == category]
    posture = request.args.get("posture")
    if posture is not None:
        records = [r for r in records if services.stock_posture(r) == posture]
    return list_response(records, stock_out)


@bp.route("/linen-stocks/<stock_id>/adjustments", methods=["POST"])
def record_adjustment(stock_id):
    """OCC-guarded found/donation/write-off adjustment (PRD 3.1)."""
    _, role = authenticate()
    authorize(role, ["LinenManager"])
    stock = get_or_404(store.stocks, stock_id, "LinenStock")
    body = body_json()

    delta = req_int(body, "delta_pieces")
    req_str(body, "reason")
    expected = occ_field(body, "expected_linen_stock_version")

    # OCC (priority 6) before fiscal guard (priority 11)
    if expected != stock["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_linen_stock_version %s does not match current version %s"
                  % (expected, stock["version"]))

    if stock["in_circulation"] + delta < 0:
        raise_err(ERR_NEGATIVE_INVENTORY,
                  "adjustment would drive in_circulation negative")

    stock["in_circulation"] += delta
    bump(stock)
    return success_object(stock_out(stock), 201)
