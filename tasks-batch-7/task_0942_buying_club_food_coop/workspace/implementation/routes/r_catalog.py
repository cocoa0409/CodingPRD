"""Routes, drop points, items and price versions (12 endpoints)."""

from flask import Blueprint

from core import clock, serialize
from core.constants import (DROP_MINIMUM_DEFAULT_CENTS, ITEM_STATUSES,
                            REMAINDER_POLICIES, ROLES, ROUTE_MAX_PALLETS_DEFAULT,
                            ROUTE_MINIMUM_DEFAULT_CENTS, ROUTE_REEFER_SLOTS_DEFAULT,
                            TEMP_CLASSES)
from core.envelope import created, ok, page
from core.errors import ApiError
from core.ladder import (body_fk, endpoint, enum_body, enum_filter, free_filter,
                         pagination, path_row, req_id, req_instant, req_int, req_str,
                         opt_bool, opt_int)
from core.money import ceil_div
from core.store import DB, touch

bp = Blueprint("catalog", __name__)
R5 = list(ROLES)


# --------------------------------------------------------------- routes -----

@bp.post("/routes")
@endpoint(["ClubAdmin"])
def create_route(ctx):
    code = req_str(ctx, "code")
    name = req_str(ctx, "name")
    reefer_slots = opt_int(ctx, "reefer_slots", minimum=0, default=ROUTE_REEFER_SLOTS_DEFAULT)
    route_minimum = opt_int(ctx, "route_minimum_cents", minimum=0,
                            default=ROUTE_MINIMUM_DEFAULT_CENTS)
    max_pallets = opt_int(ctx, "max_pallets", minimum=1, default=ROUTE_MAX_PALLETS_DEFAULT)
    for existing in DB.routes.values():
        if existing["code"] == code:
            raise ApiError("ERR_VALIDATION", "code must be unique across routes.")
    row = DB.insert("Route", {
        "code": code, "name": name, "reefer_slots": reefer_slots,
        "route_minimum_cents": route_minimum, "max_pallets": max_pallets,
    })
    return created(serialize.route(row))


@bp.get("/routes")
@endpoint(R5)
def list_routes(ctx):
    limit, offset = pagination(ctx)
    code = free_filter(ctx, "code")
    rows = [r for r in DB.all("Route") if code is None or r["code"] == code]
    return page(serialize.project_all(rows), limit, offset)


# ----------------------------------------------------------- drop points ----

@bp.post("/drop-points")
@endpoint(["ClubAdmin"])
def create_drop_point(ctx):
    route = body_fk(ctx, "route_id")
    coordinator = body_fk(ctx, "coordinator_member_id")
    req_id(ctx, "route_id")
    name = req_str(ctx, "name")
    drop_minimum = opt_int(ctx, "drop_minimum_cents", minimum=0,
                           default=DROP_MINIMUM_DEFAULT_CENTS)
    row = DB.insert("DropPoint", {
        "route_id": route["id"], "name": name,
        "coordinator_member_id": coordinator["id"] if coordinator else None,
        "drop_minimum_cents": drop_minimum,
    })
    return created(serialize.drop_point(row))


@bp.get("/drop-points")
@endpoint(R5)
def list_drop_points(ctx):
    limit, offset = pagination(ctx)
    route_id = free_filter(ctx, "route_id")
    coordinator_member_id = free_filter(ctx, "coordinator_member_id")
    rows = []
    for row in DB.all("DropPoint"):
        if route_id is not None and row["route_id"] != route_id:
            continue
        if coordinator_member_id is not None and row["coordinator_member_id"] != coordinator_member_id:
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/drop-points/<drop_point_id>")
@endpoint(R5)
def read_drop_point(ctx, drop_point_id):
    row = path_row("drop_point_id", drop_point_id)
    return ok(serialize.drop_point(row))


# ----------------------------------------------------------------- items ----

@bp.post("/items")
@endpoint(["ClubAdmin"])
def create_item(ctx):
    sku = req_str(ctx, "sku")
    name = req_str(ctx, "name")
    if "temp_class" not in ctx.body or ctx.body["temp_class"] is None:
        raise ApiError("ERR_VALIDATION", "temp_class is required.")
    case_pack_units = req_int(ctx, "case_pack_units", minimum=1)
    unit_weight_grams = req_int(ctx, "unit_weight_grams", minimum=1)
    unit_cube_cm3 = req_int(ctx, "unit_cube_cm3", minimum=1)
    split_allowed = opt_bool(ctx, "split_allowed", default=True)
    temp_class = enum_body(ctx, "temp_class", TEMP_CLASSES, required=True)
    remainder_policy = enum_body(ctx, "remainder_policy", REMAINDER_POLICIES,
                                 default="SHORT_FILL")
    for existing in DB.items.values():
        if existing["sku"] == sku:
            raise ApiError("ERR_VALIDATION", "sku must be unique across items.")
    row = DB.insert("Item", {
        "sku": sku, "name": name, "temp_class": temp_class,
        "case_pack_units": case_pack_units, "unit_weight_grams": unit_weight_grams,
        "unit_cube_cm3": unit_cube_cm3, "split_allowed": split_allowed,
        "remainder_policy": remainder_policy, "status": "ACTIVE",
    })
    return created(serialize.item(row))


@bp.get("/items")
@endpoint(R5)
def list_items(ctx):
    limit, offset = pagination(ctx)
    temp_class = enum_filter(ctx, "temp_class", TEMP_CLASSES)
    status = enum_filter(ctx, "status", ITEM_STATUSES)
    sku = free_filter(ctx, "sku")
    rows = []
    for row in DB.all("Item"):
        if sku is not None and row["sku"] != sku:
            continue
        if temp_class is not None and row["temp_class"] != temp_class:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/items/<item_id>")
@endpoint(R5)
def read_item(ctx, item_id):
    return ok(serialize.item(path_row("item_id", item_id)))


@bp.post("/items/<item_id>/discontinue")
@endpoint(["ClubAdmin"])
def discontinue_item(ctx, item_id):
    item = path_row("item_id", item_id)
    if item["status"] != "ACTIVE":
        raise ApiError("ERR_ITEM_DISCONTINUED", "The item is already DISCONTINUED.")
    item["status"] = "DISCONTINUED"
    touch(item)
    return ok(serialize.item(item))


# -------------------------------------------------------- price versions ----

@bp.post("/price-versions")
@endpoint(["ClubAdmin"])
def create_price_version(ctx):
    item = body_fk(ctx, "item_id")
    req_id(ctx, "item_id")
    effective_raw, effective_at = req_instant(ctx, "effective_from")
    case_price_cents = req_int(ctx, "case_price_cents", minimum=1)
    for existing in DB.price_versions.values():
        if existing["item_id"] != item["id"]:
            continue
        if clock.parse(existing["effective_from"]) == effective_at:
            raise ApiError("ERR_PRICE_VERSION_OVERLAP")
    row = DB.insert("PriceVersion", {
        "item_id": item["id"],
        "effective_from": effective_raw,
        "case_price_cents": case_price_cents,
        "split_unit_base_cents": ceil_div(case_price_cents, item["case_pack_units"]),
    }, versioned=False)
    return created(serialize.price_version(row))


@bp.get("/price-versions")
@endpoint(R5)
def list_price_versions(ctx):
    limit, offset = pagination(ctx)
    item_id = free_filter(ctx, "item_id")
    rows = [r for r in DB.all("PriceVersion") if item_id is None or r["item_id"] == item_id]
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/price-versions/<price_version_id>")
@endpoint(R5)
def read_price_version(ctx, price_version_id):
    return ok(serialize.price_version(path_row("price_version_id", price_version_id)))
