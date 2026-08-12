"""Catalog stewardship: plans, SKUs and stock (PRD 3.3). OpsAdmin territory."""

from flask import Blueprint

import calc
import constants as C
import serialize
import services
import shapes
import store
from auth import api, get_plan, get_sku
from envelope import ok, created, paginate
from errors import ApiError
from store import db, touch

bp = Blueprint("catalog", __name__)

READ_ROLES = ["AccountHolder", "RegistryOwner", "GiftPurchaser", "SupportAgent",
              "OpsAdmin"]


@api(bp, "POST", "/plans", ["OpsAdmin"], catalog_write=True)
def create_plan():
    parsed = shapes.validate(shapes.body(), [
        shapes.field("code", required=True, kind="string"),
        shapes.field("name", required=True, kind="string"),
        shapes.field("default_pack_count", required=True, kind="int",
                     lo=C.PACK_COUNT_MIN, hi=C.PACK_COUNT_MAX),
        shapes.field("promo_discount_pct", kind="number", lo=0,
                     hi=float(C.PROMO_DISCOUNT_MAX_PCT), default=0),
        shapes.field("allows_hypoallergenic", kind="bool", default=True),
    ])
    for row in db.plans.values():
        if row["code"] == parsed["code"]:
            raise ApiError("ERR_DUPLICATE_CODE")
    row = store.base_row(full=True)
    row.update({
        "code": parsed["code"],
        "name": parsed["name"],
        "default_pack_count": parsed["default_pack_count"],
        "promo_discount_pct": parsed["promo_discount_pct"],
        "allows_hypoallergenic": bool(parsed["allows_hypoallergenic"]),
        "status": "ACTIVE",
    })
    db.plans[row["id"]] = row
    return created(serialize.plan(row))


@api(bp, "GET", "/plans/<id>", READ_ROLES)
def read_plan(id):
    return ok(serialize.plan(get_plan(id)))


@api(bp, "GET", "/plans", READ_ROLES)
def list_plans():
    status = shapes.qs("status")
    rows = [r for r in db.plans.values() if shapes.match(r, "status", status)]
    return paginate(rows, serialize.plan)


@api(bp, "PATCH", "/plans/<id>", ["OpsAdmin"], catalog_write=True)
def update_plan(id):
    plan = get_plan(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("name", kind="string"),
        shapes.field("promo_discount_pct", kind="number", lo=0,
                     hi=float(C.PROMO_DISCOUNT_MAX_PCT)),
        shapes.field("allows_hypoallergenic", kind="bool"),
        shapes.field("status", kind="enum", members=C.PLAN_STATUSES),
    ])
    for name in ("name", "promo_discount_pct", "allows_hypoallergenic", "status"):
        if shapes.supplied(parsed, name):
            plan[name] = parsed[name]
    touch(plan)
    return ok(serialize.plan(plan))


@api(bp, "POST", "/skus", ["OpsAdmin"], catalog_write=True)
def create_sku():
    parsed = shapes.validate(shapes.body(), [
        shapes.field("code", required=True, kind="string"),
        shapes.field("name", required=True, kind="string"),
        shapes.field("stage", required=True, kind="enum", members=C.STAGE_ORDER),
        shapes.field("line", required=True, kind="enum", members=C.SKU_LINES),
        shapes.field("pack_price_cents", required=True, kind="int", lo=0),
        shapes.field("pack_size_units", kind="int", lo=1, hi=200, default=60),
        shapes.field("allergen_tags", kind="array", default=None),
        shapes.field("stock_packs", kind="int", lo=0, default=0),
    ])
    for row in db.skus.values():
        if row["code"] == parsed["code"]:
            raise ApiError("ERR_DUPLICATE_CODE")
    row = store.base_row(full=True)
    row.update({
        "code": parsed["code"],
        "name": parsed["name"],
        "stage": parsed["stage"],
        "line": parsed["line"],
        "pack_size_units": parsed["pack_size_units"],
        "pack_price_cents": parsed["pack_price_cents"],
        "allergen_tags": list(parsed["allergen_tags"] or []),
        "stock_packs": parsed["stock_packs"] or 0,
        "status": "ACTIVE",
    })
    db.skus[row["id"]] = row
    return created(serialize.sku(row))


@api(bp, "GET", "/skus/<id>", READ_ROLES)
def read_sku(id):
    return ok(serialize.sku(get_sku(id)))


@api(bp, "GET", "/skus", READ_ROLES)
def list_skus():
    stage = shapes.qs("stage")
    line = shapes.qs("line")
    status = shapes.qs("status")
    rows = [r for r in db.skus.values()
            if shapes.match(r, "stage", stage)
            and shapes.match(r, "line", line)
            and shapes.match(r, "status", status)]
    return paginate(rows, serialize.sku)


@api(bp, "PATCH", "/skus/<id>", ["OpsAdmin"], catalog_write=True)
def update_sku(id):
    sku = get_sku(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("name", kind="string"),
        shapes.field("pack_price_cents", kind="int", lo=0),
        shapes.field("allergen_tags", kind="array"),
        shapes.field("status", kind="enum", members=C.SKU_STATUSES),
    ])
    for name in ("name", "pack_price_cents", "status"):
        if shapes.supplied(parsed, name):
            sku[name] = parsed[name]
    if shapes.supplied(parsed, "allergen_tags"):
        sku["allergen_tags"] = list(parsed["allergen_tags"])
    touch(sku)
    return ok(serialize.sku(sku))


@api(bp, "POST", "/skus/<id>/stock-adjustments", ["OpsAdmin"], catalog_write=True)
def adjust_stock(id):
    sku = get_sku(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("delta_packs", required=True, kind="int"),
    ])
    delta = parsed["delta_packs"]
    sku["stock_packs"] = max(0, int(sku["stock_packs"]) + delta)
    touch(sku)

    if delta < 0:
        # A negative adjustment pushes any line it can no longer fill into the
        # substitution queue — but only on PLANNED or ALLOCATED cycles.
        for line in list(db.cycle_lines.values()):
            if line["sku_id"] != sku["id"]:
                continue
            if line["status"] != "ALLOCATED":
                continue
            cycle = db.cycles.get(line["cycle_id"])
            if cycle is None or cycle["status"] not in ("PLANNED", "ALLOCATED"):
                continue
            if int(sku["stock_packs"]) < int(line["quantity_packs"]):
                services.flag_line_pending(line, "OUT_OF_STOCK")
    return ok(serialize.sku(sku))
