"""Catalog: HomeModel, Community, Lot (PRD 3.1)."""

from flask import Blueprint, request

from db import create_record, store
from errors import fail
from middleware import ALL_ROLES, require
from response import ok, ok_list
from services import bump, get_or_404, order_is_live, ser
from validate import Shape, get_body, pagination_params

bp = Blueprint("catalog", __name__)

FLOOR_PLAN_TYPES = ["SINGLE_WIDE", "DOUBLE_WIDE", "TRIPLE_WIDE", "MODULAR"]


def _list_page(records, filters):
    limit, offset = pagination_params()
    rows = [r for r in records if all(r.get(k) == v for k, v in filters.items())]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    return ok_list([ser(r) for r in rows[offset:offset + limit]], total, limit, offset)


# ------------------------------------------------------------- home models --

@bp.post("/home-models")
@require("DealershipAdmin")
def create_home_model(actor_id, actor_role):
    shape = Shape(get_body())
    shape.req_str("model_code")
    shape.req_str("name")
    shape.req_enum("floor_plan_type", FLOOR_PLAN_TYPES)
    shape.req_int("section_count", minimum=1)
    shape.req_num("width_ft", gt0=True)
    shape.req_num("length_ft", gt0=True)
    shape.req_int("base_price_cents", minimum=0)
    shape.req_int("factory_lead_time_days", minimum=0)
    # (18) uniqueness: model_code scoped to non-DISCONTINUED models
    if shape.ok("model_code"):
        code = shape.value("model_code")
        if any(m["model_code"] == code and m["status"] != "DISCONTINUED"
               for m in store.home_models.values()):
            fail("ERR_DUPLICATE_RESOURCE", "model_code already registered on a live model")
    shape.raise_if_errors()
    rec = create_record(store.home_models, {
        "model_code": shape.value("model_code"),
        "name": shape.value("name"),
        "floor_plan_type": shape.value("floor_plan_type"),
        "section_count": shape.value("section_count"),
        "width_ft": shape.value("width_ft"),
        "length_ft": shape.value("length_ft"),
        "base_price_cents": shape.value("base_price_cents"),
        "factory_lead_time_days": shape.value("factory_lead_time_days"),
        "status": "ACTIVE",
    })
    return ok(ser(rec), 201)


@bp.get("/home-models")
@require(*ALL_ROLES)
def list_home_models(actor_id, actor_role):
    filters = {}
    for k in ("status", "floor_plan_type"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    return _list_page(store.home_models.values(), filters)


@bp.get("/home-models/<rid>")
@require(*ALL_ROLES)
def get_home_model(rid, actor_id, actor_role):
    return ok(ser(get_or_404(store.home_models, rid, "ERR_HOME_MODEL_NOT_FOUND", "Home model")))


# -------------------------------------------------------------- communities --

@bp.post("/communities")
@require("DealershipAdmin")
def create_community(actor_id, actor_role):
    shape = Shape(get_body())
    shape.req_str("name")
    shape.req_str("address")
    shape.req_int("lot_rent_cents", minimum=0)
    shape.raise_if_errors()
    rec = create_record(store.communities, {
        "name": shape.value("name"),
        "address": shape.value("address"),
        "lot_rent_cents": shape.value("lot_rent_cents"),
        "status": "ACTIVE",
    })
    return ok(ser(rec), 201)


@bp.get("/communities/<rid>")
@require(*ALL_ROLES)
def get_community(rid, actor_id, actor_role):
    return ok(ser(get_or_404(store.communities, rid, "ERR_COMMUNITY_NOT_FOUND", "Community")))


# --------------------------------------------------------------------- lots --

@bp.post("/communities/<rid>/lots")
@require("DealershipAdmin")
def create_lot(rid, actor_id, actor_role):
    community = get_or_404(store.communities, rid, "ERR_COMMUNITY_NOT_FOUND", "Community")
    shape = Shape(get_body())
    shape.req_str("lot_number")
    shape.req_int("max_sections", minimum=1)
    shape.req_num("max_length_ft", gt0=True)
    shape.req_bool("utilities_ready")
    # (18) uniqueness: lot_number within its community
    if shape.ok("lot_number"):
        num = shape.value("lot_number")
        if any(l["community_id"] == community["id"] and l["lot_number"] == num
               for l in store.lots.values()):
            fail("ERR_DUPLICATE_RESOURCE", "lot_number already exists within this community")
    shape.raise_if_errors()
    rec = create_record(store.lots, {
        "community_id": community["id"],
        "lot_number": shape.value("lot_number"),
        "max_sections": shape.value("max_sections"),
        "max_length_ft": shape.value("max_length_ft"),
        "utilities_ready": shape.value("utilities_ready"),
        "status": "AVAILABLE",
    })
    return ok(ser(rec), 201)


@bp.get("/communities/<rid>/lots")
@require(*ALL_ROLES)
def list_lots(rid, actor_id, actor_role):
    community = get_or_404(store.communities, rid, "ERR_COMMUNITY_NOT_FOUND", "Community")
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = request.args.get("status")
    lots = [l for l in store.lots.values() if l["community_id"] == community["id"]]
    return _list_page(lots, filters)


@bp.get("/lots/<rid>")
@require(*ALL_ROLES)
def get_lot(rid, actor_id, actor_role):
    return ok(ser(get_or_404(store.lots, rid, "ERR_LOT_NOT_FOUND", "Lot")))


@bp.post("/lots/<rid>/reserve")
@require("SalesConsultant")
def reserve_lot(rid, actor_id, actor_role):
    lot = get_or_404(store.lots, rid, "ERR_LOT_NOT_FOUND", "Lot")
    # (7) state precondition: community must be ACTIVE
    community = store.communities.get(lot["community_id"])
    if community is None or community["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Community is not ACTIVE")
    # (12) lot availability
    if lot["status"] != "AVAILABLE":
        fail("ERR_LOT_NOT_AVAILABLE", "Lot is not AVAILABLE")
    lot["status"] = "RESERVED"
    bump(lot)
    return ok(ser(lot))


@bp.post("/lots/<rid>/release")
@require("SalesConsultant")
def release_lot(rid, actor_id, actor_role):
    lot = get_or_404(store.lots, rid, "ERR_LOT_NOT_FOUND", "Lot")
    # (7) state precondition: RESERVED, and no live order references the lot
    if lot["status"] != "RESERVED":
        fail("ERR_INVALID_STATE", "Lot is not RESERVED")
    if any(o.get("lot_id") == lot["id"] and order_is_live(o)
           for o in store.sales_orders.values()):
        fail("ERR_INVALID_STATE", "Lot is referenced by a non-terminal sales order")
    lot["status"] = "AVAILABLE"
    bump(lot)
    return ok(ser(lot))
