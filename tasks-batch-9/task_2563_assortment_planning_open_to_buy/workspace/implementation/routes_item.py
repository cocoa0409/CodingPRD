"""Assortment items and localization overlays."""
from flask import Blueprint, request

from common import (F, ROLE_PLANNER, ROLE_DIRECTOR, ROLE_BUYER, PLANNING_ROLES,
                    auth, fail, page_of, pagination, parse_input, public,
                    public_list, respond)
import calc
import store
import svc
from store import db, make_row, touch

bp = Blueprint("item", __name__)

LIFECYCLE_STAGES = ["NEW", "CARRYOVER", "CORE", "EXIT"]


def _filter(rows, name, field=None):
    value = request.args.get(name)
    if value is None:
        return rows
    return [r for r in rows if r.get(field or name) == value]


# ---------------------------------------------------------------------------
# Assortment items
# ---------------------------------------------------------------------------
ITEM_FIELDS = [
    F("option_plan_id", "str", min_len=1),
    F("vendor_id", "str", min_len=1),
    F("sku_code", "str", min_len=3, max_len=24),
    F("color_code", "str", min_len=2, max_len=8),
    F("lifecycle_stage", "enum", enum=LIFECYCLE_STAGES),
    F("unit_cost_cents", "int", minimum=1),
    F("retail_price_cents", "int", minimum=1),
    F("prior_season_sell_through_bps", "int", required=False, default=0,
      minimum=0, maximum=10000),
]


@bp.post("/otb/assortment-items")
def create_item():
    auth([ROLE_PLANNER, ROLE_BUYER])
    data = parse_input(ITEM_FIELDS)
    store.get_optionplan(data["option_plan_id"])
    store.get_vendor(data["vendor_id"])
    for row in db.items.values():
        if row["sku_code"] == data["sku_code"]:
            fail("ERR_INVALID_REQUEST", "sku_code must be unique across assortment items")
    row = make_row(
        status="PROPOSED",
        sell_through_basis=None,
        sell_through_bps=None,
        effective_overlay_multiplier_bps=10000,
        planned_units=None,
        **data)
    db.items[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/otb/assortment-items/<rid>")
def read_item(rid):
    auth(PLANNING_ROLES)
    return respond(public(store.get_item(rid)))


@bp.get("/otb/assortment-items")
def list_items():
    auth(PLANNING_ROLES)
    limit, offset = pagination()
    rows = store.by_seq(list(db.items.values()))
    rows = _filter(rows, "option_plan_id")
    rows = _filter(rows, "vendor_id")
    rows = _filter(rows, "lifecycle_stage")
    rows = _filter(rows, "status")
    window, meta = page_of(rows, limit, offset)
    return respond(public_list(window), 200, meta)


@bp.post("/otb/assortment-items/<rid>/adopt")
def adopt_item(rid):
    auth([ROLE_BUYER])
    parse_input([])
    item = store.get_item(rid)
    if item["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "a %s item cannot be adopted" % item["status"])
    cell = db.optionplans.get(item["option_plan_id"])
    if cell["status"] != "SLOTTED":
        fail("ERR_OPTION_PLAN_NOT_SLOTTED", "the option plan is %s" % cell["status"])
    plan = db.plans.get(cell["category_plan_id"])
    if plan["status"] not in ("APPROVED", "REFORECAST_OPEN"):
        fail("ERR_INVALID_STATE",
             "the governing category plan is %s" % plan["status"])
    if not cell["option_slots_open"] or cell["option_slots_open"] < 1:
        fail("ERR_NO_OPTION_SLOT", "the option plan has no open slot")
    item["status"] = "ADOPTED"
    item["planned_units"] = cell["target_units_per_option"]
    svc.resolve_item_forecast(item)
    touch(item)
    cell["option_slots_assigned"] = cell["option_slots_assigned"] + 1
    cell["option_slots_open"] = cell["option_slots_open"] - 1
    touch(cell)
    return respond(public(item))


@bp.post("/otb/assortment-items/<rid>/activate")
def activate_item(rid):
    auth([ROLE_BUYER])
    parse_input([])
    item = store.get_item(rid)
    if item["status"] != "ADOPTED":
        fail("ERR_INVALID_STATE", "a %s item cannot be activated" % item["status"])
    plan = store.item_plan(item)
    if not any(m["status"] == "IN_SEASON" for m in store.plan_months(plan["id"])):
        fail("ERR_INVALID_STATE",
             "no plan month of the category plan has reached IN_SEASON")
    item["status"] = "IN_SEASON"
    touch(item)
    return respond(public(item))


@bp.post("/otb/assortment-items/<rid>/close")
def close_item(rid):
    auth([ROLE_BUYER])
    parse_input([])
    item = store.get_item(rid)
    if item["status"] not in ("ADOPTED", "IN_SEASON", "CHASED", "CANCELLED_IN_SEASON"):
        fail("ERR_INVALID_STATE", "a %s item cannot be closed" % item["status"])
    for rc in store.item_commitments(item["id"]):
        if rc["commit_status"] in ("PROPOSED", "COMMITTED"):
            fail("ERR_INVALID_STATE",
                 "a receipt commitment of this item is still %s" % rc["commit_status"])
    item["status"] = "CLOSED"
    touch(item)
    cell = db.optionplans.get(item["option_plan_id"])
    if cell is not None:
        cell["option_slots_assigned"] = cell["option_slots_assigned"] - 1
        if cell["option_slots_open"] is not None:
            cell["option_slots_open"] = cell["option_slots_open"] + 1
        touch(cell)
    return respond(public(item))


# ---------------------------------------------------------------------------
# Localization overlays
# ---------------------------------------------------------------------------
OVERLAY_FIELDS = [
    F("category_plan_id", "str", min_len=1),
    F("store_cluster_id", "str", min_len=1),
    F("overlay_type", "enum", enum=["CLIMATE", "DEMOGRAPHIC", "VOLUME"]),
    F("effective_start", "datetime"),
    F("effective_end", "datetime"),
    F("unit_multiplier_bps", "int", minimum=5000, maximum=15000),
]


@bp.post("/otb/localization-overlays")
def create_overlay():
    auth([ROLE_PLANNER])
    data = parse_input(OVERLAY_FIELDS)
    store.get_plan(data["category_plan_id"])
    store.get_cluster(data["store_cluster_id"])
    planned = [c for c in store.plan_optionplans(data["category_plan_id"])
               if c["store_cluster_id"] == data["store_cluster_id"]]
    if not planned:
        fail("ERR_CLUSTER_NOT_IN_PLAN",
             "no option plan exists for this plan and cluster")
    start = store.dt(data["effective_start"])
    end = store.dt(data["effective_end"])
    buffer_delta = calc.days(calc.OVERLAY_BUFFER_DAYS)
    for other in store.by_seq(list(db.overlays.values())):
        if other["store_cluster_id"] != data["store_cluster_id"]:
            continue
        if other["overlay_type"] != data["overlay_type"]:
            continue
        if other["status"] not in ("DRAFT", "ACTIVE"):
            continue
        other_start = store.dt(other["effective_start"])
        other_end = store.dt(other["effective_end"])
        if start <= other_end + buffer_delta and other_start <= end + buffer_delta:
            fail("ERR_OVERLAY_WINDOW_CONFLICT",
                 "another overlay of the same type on this cluster is within seven days")
    if end < start:
        fail("ERR_OVERLAY_WINDOW_INVERTED",
             "effective_end must be greater than or equal to effective_start")
    row = make_row(status="DRAFT", **data)
    db.overlays[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/otb/localization-overlays/<rid>")
def read_overlay(rid):
    auth(PLANNING_ROLES)
    return respond(public(store.get_overlay(rid)))


@bp.get("/otb/localization-overlays")
def list_overlays():
    auth(PLANNING_ROLES)
    limit, offset = pagination()
    rows = store.by_seq(list(db.overlays.values()))
    rows = _filter(rows, "category_plan_id")
    rows = _filter(rows, "store_cluster_id")
    rows = _filter(rows, "overlay_type")
    rows = _filter(rows, "status")
    window, meta = page_of(rows, limit, offset)
    return respond(public_list(window), 200, meta)


@bp.post("/otb/localization-overlays/<rid>/activate")
def activate_overlay(rid):
    auth([ROLE_DIRECTOR])
    parse_input([])
    overlay = store.get_overlay(rid)
    if overlay["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "a %s overlay cannot be activated" % overlay["status"])
    plan = db.plans.get(overlay["category_plan_id"])
    if plan["status"] not in ("APPROVED", "REFORECAST_OPEN"):
        fail("ERR_INVALID_STATE", "the parent category plan is %s" % plan["status"])
    end = store.dt(overlay["effective_end"])
    if end is not None and store.clock() > end:
        fail("ERR_INVALID_STATE", "the logical clock has passed effective_end")
    overlay["status"] = "ACTIVE"
    touch(overlay)
    svc.reresolve_overlay_items(overlay)
    return respond(public(overlay))
