"""Offer windows: creation, the cutoff, locking, the one extension, the
lifecycle advance, production planning and the computed capacity read."""

from datetime import timedelta

from flask import Blueprint

import config
from db import DB, base_record, touch
from errors import ApiError
from ladder import endpoint
from response import created, ok
from routes.common import list_endpoint
from serialize import dump
from services import capacity, cascade
from services.capacity import CONFIRMED_ORDER_STATES, DEAD_LINE_STATES
from services.gates import permit_gate, require_state
from tsutil import gte, lt, num2, ts_input, ts_shift

bp = Blueprint("windows", __name__)

ADMIN = config.ROLE_ADMIN
BAKER = config.ROLE_BAKER
CUSTOMER = config.ROLE_CUSTOMER
INSPECTOR = config.ROLE_INSPECTOR


def orders_on(window_id):
    return [o for o in DB.values("orders")
            if o.get("offer_window_id") == window_id]


def batches_on(window_id):
    return [b for b in DB.values("batches")
            if b.get("offer_window_id") == window_id]


def cycles_on(window_id):
    return [c for c in DB.values("subscription_cycles")
            if c.get("offer_window_id") == window_id]


@bp.post("/bakery/offer-windows")
@endpoint(roles=[BAKER])
def create_window(ctx):
    fks = ctx.body_fks(required=("baker_id",))          # rung 10
    baker = fks["baker_id"]
    if baker is None:
        raise ApiError("ERR_VALIDATION", "baker_id is required.")
    ctx.ownership(baker_id=baker["id"])                 # rung 12
    # rung 13
    label = ctx.req_str("label")
    opens_at = ctx.req_dt("opens_at")
    order_cutoff_at = ctx.req_dt("order_cutoff_at")
    production_date = ctx.req_dt("production_date")
    handoff_date = ctx.req_dt("handoff_date")
    handoff_window_end_at = ctx.req_dt("handoff_window_end_at")
    capacity_units = ctx.opt_int("capacity_units",
                                 config.WINDOW_UNIT_CAPACITY_DEFAULT, minimum=0)
    capacity_batch_slots = ctx.opt_int("capacity_batch_slots",
                                       config.WINDOW_BATCH_SLOT_CAPACITY_DEFAULT,
                                       minimum=0)
    capacity_oven_hours = ctx.opt_num("capacity_oven_hours",
                                      config.WINDOW_OVEN_HOURS_CAPACITY_DEFAULT)
    permit_gate(baker)                                  # rung 15
    # rung 44: opens < cutoff <= production <= handoff < handoff end
    t = [ts_input(x) for x in (opens_at, order_cutoff_at, production_date,
                               handoff_date, handoff_window_end_at)]
    if not (lt(t[0], t[1]) and gte(t[2], t[1]) and gte(t[3], t[2])
            and lt(t[3], t[4])):
        raise ApiError("ERR_VALIDATION",
                       "The window's instants are not strictly ordered.")

    rec = base_record(ctx.now)
    rec.update({
        "baker_id": baker["id"],
        "label": label,
        "opens_at": t[0],
        "order_cutoff_at": t[1],
        "production_date": t[2],
        "handoff_date": t[3],
        "handoff_window_end_at": t[4],
        "window_status": "DRAFT",
        "plan_status": "UNPLANNED",
        "capacity_posture": "OPEN_CAPACITY",
        "capacity_units": capacity_units,
        "capacity_batch_slots": capacity_batch_slots,
        "capacity_oven_hours": capacity_oven_hours,
        "confirmed_units": 0,
        "held_units": 0,
        "reserved_units": 0,
        "cutoff_extension_count": 0,
    })
    DB.coll("offer_windows")[rec["id"]] = rec
    return created(dump("offer_windows", rec))


@bp.post("/bakery/offer-windows/<offer_window_id>/lock")
@endpoint(roles=[BAKER], path=("offer_window_id",))
def lock_window(ctx):
    # CARVE-OUT: neither rung 15 nor rung 16 applies to locking.
    window = ctx.p["offer_window_id"]
    ctx.ownership(baker_id=window.get("baker_id"))               # rung 12
    require_state(window.get("window_status"), ("OPEN",), "window_status")
    if not gte(ctx.now, window["order_cutoff_at"]):
        raise ApiError("ERR_INVALID_STATE",
                       "The window may not be locked before its cutoff.")
    window["window_status"] = "LOCKED"
    for order in orders_on(window["id"]):
        if order.get("order_status") != "PENDING_HOLD":
            continue
        cascade.release_pending_lines(order, ctx.now)
        order["order_status"] = "EXPIRED_HOLD"
        order["hold_expires_at"] = None
        touch(order, ctx.now)
    for cyc in cycles_on(window["id"]):
        if cyc.get("cycle_status") == "RESERVED":
            cascade.release_cycle(cyc, ctx.now)
    capacity.sync(window, ctx.now, force_bump=True)
    return ok(dump("offer_windows", window))


@bp.post("/bakery/offer-windows/<offer_window_id>/extend-cutoff")
@endpoint(roles=[BAKER], path=("offer_window_id",))
def extend_cutoff(ctx):
    window = ctx.p["offer_window_id"]
    ctx.ownership(baker_id=window.get("baker_id"))
    require_state(window.get("window_status"), ("LOCKED",), "window_status")
    if window.get("plan_status") != "UNPLANNED":
        raise ApiError("ERR_INVALID_STATE",
                       "The cutoff may only be extended while UNPLANNED.")
    if (window.get("cutoff_extension_count") or 0) >= config.CUTOFF_EXTENSION_MAX_COUNT:
        raise ApiError("ERR_INVALID_STATE",
                       "The cutoff extension maximum has been reached.")
    window["window_status"] = "OPEN"
    # two hours from NOW, not from the old cutoff
    window["order_cutoff_at"] = ts_shift(
        ctx.now, timedelta(minutes=config.CUTOFF_EXTENSION_MINUTES))
    window["cutoff_extension_count"] = (window.get("cutoff_extension_count") or 0) + 1
    for cyc in cycles_on(window["id"]):
        if cyc.get("skip_deadline_at") is not None or cyc.get("cycle_status") in (
                "GENERATED", "RESERVED", "CONFIRMED"):
            cyc["skip_deadline_at"] = ts_shift(
                window["order_cutoff_at"],
                timedelta(hours=-config.SKIP_DEADLINE_HOURS_BEFORE_CUTOFF))
            touch(cyc, ctx.now)
    capacity.sync(window, ctx.now, force_bump=True)
    return ok(dump("offer_windows", window))


@bp.post("/bakery/offer-windows/<offer_window_id>/advance")
@endpoint(roles=[BAKER], path=("offer_window_id",))
def advance_window(ctx):
    window = ctx.p["offer_window_id"]
    ctx.ownership(baker_id=window.get("baker_id"))                  # rung 12
    if ctx.body.get("to_status") is None:                            # rung 13
        raise ApiError("ERR_VALIDATION", "to_status is required.")
    to_status = ctx.enum("to_status", "window_status")               # rung 14
    baker = DB.get("bakers", window.get("baker_id"))
    permit_gate(baker)                                               # rung 15
    current = window.get("window_status")

    if to_status == "OPEN":                                          # rung 19
        require_state(current, ("DRAFT",), "window_status")
        if not gte(ctx.now, window["opens_at"]):
            raise ApiError("ERR_INVALID_STATE",
                           "The window may not open before opens_at.")
        window["window_status"] = "OPEN"
        capacity.sync(window, ctx.now, force_bump=True)

    elif to_status == "IN_PRODUCTION":
        require_state(current, ("LOCKED",), "window_status")
        if window.get("plan_status") != "PLANNED":
            raise ApiError("ERR_INVALID_STATE",
                           "Production requires a PLANNED window.")
        if not gte(ctx.now, window["production_date"]):
            raise ApiError("ERR_INVALID_STATE",
                           "Production may not begin before production_date.")
        window["window_status"] = "IN_PRODUCTION"
        for order in orders_on(window["id"]):
            if order.get("order_status") == "CONFIRMED":
                order["order_status"] = "IN_PRODUCTION"
                touch(order, ctx.now)
        capacity.sync(window, ctx.now, force_bump=True)

    elif to_status == "HANDOFF_OPEN":
        require_state(current, ("IN_PRODUCTION",), "window_status")
        for batch in batches_on(window["id"]):
            if batch.get("batch_status") not in ("ALLOCATED", "CLOSED",
                                                 "SCRAPPED_RECALL"):
                raise ApiError("ERR_INVALID_STATE",
                               "Every batch must have reached ALLOCATED, "
                               "CLOSED or SCRAPPED_RECALL.")
        if not gte(ctx.now, window["handoff_date"]):
            raise ApiError("ERR_INVALID_STATE",
                           "Handoff may not open before handoff_date.")
        window["window_status"] = "HANDOFF_OPEN"
        forfeit_at = ts_shift(window["handoff_window_end_at"],
                              timedelta(minutes=config.PICKUP_GRACE_MINUTES))
        for order in orders_on(window["id"]):
            dirty = False
            if order.get("order_status") == "IN_PRODUCTION":
                order["order_status"] = "READY"
                dirty = True
            if order.get("handoff_mode") in ("PICKUP_COUNTER", "PORCH_SELF_SERVE"):
                order["pickup_forfeit_at"] = forfeit_at
                if order.get("handoff_status") == "SCHEDULED":
                    order["handoff_status"] = "PICKUP_READY"
                dirty = True
            if dirty:
                touch(order, ctx.now)
        for batch in batches_on(window["id"]):
            if batch.get("batch_status") == "ALLOCATED":
                batch["batch_status"] = "CLOSED"
                touch(batch, ctx.now)
        capacity.sync(window, ctx.now, force_bump=True)

    elif to_status == "CLOSED":
        require_state(current, ("HANDOFF_OPEN",), "window_status")
        for order in orders_on(window["id"]):
            if order.get("order_status") == "READY":
                raise ApiError("ERR_INVALID_STATE",
                               "An order on this window is still READY.")
        window["window_status"] = "CLOSED"
        window["plan_status"] = "RECONCILED"
        capacity.sync(window, ctx.now, force_bump=True)

    elif to_status == "CANCELLED":
        require_state(current, ("DRAFT", "OPEN"), "window_status")
        if current == "OPEN":
            for order in orders_on(window["id"]):
                if order.get("order_status") in ("CONFIRMED", "IN_PRODUCTION",
                                                 "READY"):
                    raise ApiError("ERR_INVALID_STATE",
                                   "An order on this window is committed.")
            for order in orders_on(window["id"]):
                if order.get("order_status") in ("DRAFT", "PENDING_HOLD",
                                                 "EXPIRED_HOLD"):
                    cascade.release_pending_lines(order, ctx.now)
                    order["order_status"] = "CANCELLED"
                    order["hold_expires_at"] = None
                    touch(order, ctx.now)
        window["window_status"] = "CANCELLED"
        capacity.sync(window, ctx.now, force_bump=True)

    else:
        raise ApiError("ERR_INVALID_STATE",
                       "%s is not reachable through this capability." % to_status)
    return ok(dump("offer_windows", window))


@bp.post("/bakery/offer-windows/<offer_window_id>/plan")
@endpoint(roles=[BAKER], path=("offer_window_id",))
def plan_window(ctx):
    # CARVE-OUT: rung 16 never applies -- planning is legal only once LOCKED.
    window = ctx.p["offer_window_id"]
    ctx.ownership(baker_id=window.get("baker_id"))              # rung 12
    if ctx.body.get("mode") is None:                             # rung 13
        raise ApiError("ERR_VALIDATION", "mode is required.")
    mode = ctx.enum("mode", "plan_mode")                         # rung 14

    if mode == "PLAN":                                           # rung 19
        require_state(window.get("plan_status"), ("UNPLANNED",), "plan_status")
        if window.get("window_status") != "LOCKED":
            raise ApiError("ERR_INVALID_STATE",
                           "Planning requires a LOCKED window.")
        _build_plan(window, ctx.now)
        window["plan_status"] = "PLANNED"
    else:
        require_state(window.get("plan_status"), ("PLANNED",), "plan_status")
        if window.get("window_status") != "LOCKED":
            raise ApiError("ERR_INVALID_STATE",
                           "Replanning requires a LOCKED window.")
        for batch in batches_on(window["id"]):
            if batch.get("batch_status") != "PLANNED":
                raise ApiError("ERR_INVALID_STATE",
                               "A batch on this window has already been mixed.")
        ids = [b["id"] for b in batches_on(window["id"])]
        for line in DB.values("order_lines"):
            if line.get("batch_id") in ids:
                line["batch_id"] = None
                touch(line, ctx.now)
        for bid in ids:
            DB.coll("batches").pop(bid, None)
        window["plan_status"] = "UNPLANNED"
    capacity.sync(window, ctx.now, force_bump=True)
    return ok(dump("offer_windows", window))


def _build_plan(window, now):
    """One batch per distinct menu item across the CONFIRMED orders."""
    demand = {}
    lines_by_item = {}
    for order in orders_on(window["id"]):
        if order.get("order_status") != "CONFIRMED":
            continue
        for line in DB.values("order_lines"):
            if line.get("order_id") != order["id"]:
                continue
            if line.get("line_status") in DEAD_LINE_STATES:
                continue
            item_id = line.get("menu_item_id")
            demand[item_id] = demand.get(item_id, 0) + (line.get("quantity") or 0)
            lines_by_item.setdefault(item_id, []).append(line)

    for item_id in sorted(demand, key=lambda i: (i or "")):
        item = DB.get("menu_items", item_id)
        slots = capacity.slot_count_for(demand[item_id])
        recipe = DB.get("recipes", (item or {}).get("recipe_id"))
        batch = base_record(now)
        batch.update({
            "offer_window_id": window["id"],
            "menu_item_id": item_id,
            "recipe_id": (item or {}).get("recipe_id"),
            "batch_status": "PLANNED",
            "slot_count": slots,
            "planned_yield_units": slots * ((item or {}).get("yield_units_per_slot")
                                            or config.DEFAULT_YIELD_UNITS_PER_SLOT),
            "actual_yield_units": None,
            "surplus_units": 0,
            "oven_hours": num2(capacity._oven_for(item, slots)),
            "recipe_version_pinned": (recipe or {}).get("published_version") or 0,
        })
        DB.coll("batches")[batch["id"]] = batch
        for line in lines_by_item[item_id]:
            line["batch_id"] = batch["id"]
            touch(line, now)


@bp.get("/bakery/offer-windows/<offer_window_id>")
@endpoint(roles=[BAKER, CUSTOMER, ADMIN, INSPECTOR], path=("offer_window_id",))
def read_window(ctx):
    window = ctx.p["offer_window_id"]
    ctx.ownership(baker_id=window.get("baker_id"))
    return ok(dump("offer_windows", window))


@bp.get("/bakery/offer-windows")
@endpoint(roles=[BAKER, CUSTOMER, ADMIN, INSPECTOR], list_ep=True)
def list_windows(ctx):
    return list_endpoint(ctx, "offer_windows", {
        "baker_id": "baker_id",
        "window_status": "window_status",
        "plan_status": "plan_status",
        "capacity_posture": "capacity_posture",
    })


@bp.get("/bakery/offer-windows/<offer_window_id>/capacity")
@endpoint(roles=[BAKER, CUSTOMER, ADMIN], path=("offer_window_id",))
def read_capacity(ctx):
    window = ctx.p["offer_window_id"]
    ctx.ownership(baker_id=window.get("baker_id"))
    # PRD 2.11: this read recomputes the four stored figures.  A read never
    # bumps a version.
    fig = capacity.figures(window, ctx.now)
    capacity.store(window, ctx.now)
    return ok({
        "units_remaining": fig["units_remaining"],
        "batch_slots_remaining": fig["batch_slots_remaining"],
        "oven_hours_remaining": fig["oven_hours_remaining"],
        "capacity_posture": fig["capacity_posture"],
        "confirmed_units": fig["confirmed_units"],
        "held_units": fig["held_units"],
        "reserved_units": fig["reserved_units"],
        "slots_used": fig["slots_used"],
        "oven_hours_used": fig["oven_hours_used"],
    })
