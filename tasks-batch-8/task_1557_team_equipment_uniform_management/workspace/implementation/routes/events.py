"""Game events (PRD §3.6): scheduling gates, checklist, parallel laundry cycle."""
from datetime import timedelta

from flask import Blueprint

from db import db, clock, stamp, touch, serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_GAME_EVENT_NOT_FOUND,
    ERR_POOL_NOT_FOUND,
    ERR_EVENT_SPACING_VIOLATION,
    ERR_ALTERNATE_KIT_LIMIT_REACHED,
    ERR_EVENT_NOT_SCHEDULED,
    ERR_EVENT_NOT_LOCKED,
    ERR_LAUNDRY_NOT_READY,
    ERR_LAUNDRY_INVALID_TRANSITION,
    ERR_CHECKLIST_INCOMPLETE,
    ERR_POOL_CLOSED,
    ERR_POOL_INSUFFICIENT_STOCK,
)
from middleware import endpoint
from response import success
from routes.common import ALL_ROLES
from services.pools import reconcile_pool
from util import is_int, parse_dt

bp = Blueprint("events", __name__)

DESIGNATED_KITS = {"HOME", "AWAY", "ALTERNATE"}
MIN_EVENT_SPACING = timedelta(hours=48)
MAX_ALTERNATE_KIT_GAMES_PER_SEASON = 3
LAUNDRY_TURNAROUND = timedelta(hours=48)
LAUNDRY_OPEN = ("COLLECTING", "IN_WASH")
LAUNDRY_STEPS = {"COLLECTING": "IN_WASH", "IN_WASH": "READY", "READY": "CLOSED"}


def _serialize_event(event):
    due = event["laundry_due_at"]
    overdue = bool(
        due is not None and clock() > due and event["laundry_status"] in LAUNDRY_OPEN
    )
    return serialize(event, {"laundry_overdue": overdue})


@bp.post("/game-events")
@endpoint("EquipmentManager")
def create_event(ctx):
    b = ctx.body
    season_label = b.get("season_label")
    opponent_name = b.get("opponent_name")
    kickoff_at = parse_dt(b.get("kickoff_at"))
    designated_kit = b.get("designated_kit")
    checklist = b.get("checklist", [])
    if not isinstance(season_label, str) or not season_label:
        raise_err(ERR_INVALID_REQUEST, "season_label is required")
    if not isinstance(opponent_name, str) or not opponent_name:
        raise_err(ERR_INVALID_REQUEST, "opponent_name is required")
    if kickoff_at is None:
        raise_err(ERR_INVALID_REQUEST, "kickoff_at must be an ISO 8601 timestamp")
    if designated_kit not in DESIGNATED_KITS:
        raise_err(ERR_INVALID_REQUEST, "designated_kit is not a declared value")
    if not isinstance(checklist, list):
        raise_err(ERR_INVALID_REQUEST, "checklist must be an array")
    items = []
    for entry in checklist:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "checklist entries invalid")
        item_ref = entry.get("item_ref")
        label = entry.get("label")
        required = entry.get("required")
        if not isinstance(item_ref, str) or not item_ref:
            raise_err(ERR_INVALID_REQUEST, "checklist item_ref is required")
        if not isinstance(label, str):
            raise_err(ERR_INVALID_REQUEST, "checklist label is required")
        if not isinstance(required, bool):
            raise_err(ERR_INVALID_REQUEST, "checklist required must be a boolean")
        items.append(
            {"item_ref": item_ref, "label": label, "required": required, "status": "PENDING"}
        )
    # Temporal gates (rung 8): spacing before alternate-kit cap.
    for other in db.events.values():
        if other["season_label"] != season_label or other["status"] == "CANCELLED":
            continue
        if abs(kickoff_at - other["kickoff_at"]) < MIN_EVENT_SPACING:
            raise_err(
                ERR_EVENT_SPACING_VIOLATION,
                "kickoff within 48h of another non-cancelled same-season event",
            )
    if designated_kit == "ALTERNATE":
        count = sum(
            1
            for e in db.events.values()
            if e["season_label"] == season_label
            and e["designated_kit"] == "ALTERNATE"
            and e["status"] != "CANCELLED"
        )
        if count >= MAX_ALTERNATE_KIT_GAMES_PER_SEASON:
            raise_err(
                ERR_ALTERNATE_KIT_LIMIT_REACHED,
                "season already has 3 non-cancelled ALTERNATE designations",
            )
    event = stamp(
        {
            "season_label": season_label,
            "opponent_name": opponent_name,
            "kickoff_at": kickoff_at,
            "designated_kit": designated_kit,
            "status": "SCHEDULED",
            "checklist": items,
            "laundry_status": "NOT_STARTED",
            "laundry_load": [],
            "laundry_due_at": None,
        }
    )
    db.events[event["id"]] = event
    return success(_serialize_event(event), 201)


@bp.get("/game-events/<event_id>")
@endpoint(*ALL_ROLES)
def get_event(ctx, event_id):
    event = db.events.get(event_id)
    if event is None:
        raise_err(ERR_GAME_EVENT_NOT_FOUND, "game event not found")
    return success(_serialize_event(event))


@bp.post("/game-events/<event_id>/lock-kit")
@endpoint("EquipmentManager")
def lock_kit(ctx, event_id):
    event = db.events.get(event_id)
    if event is None:
        raise_err(ERR_GAME_EVENT_NOT_FOUND, "game event not found")
    if event["status"] != "SCHEDULED":
        raise_err(ERR_EVENT_NOT_SCHEDULED, "lock-kit requires event in SCHEDULED")
    # Laundry turnaround gate: a prior same-season completed event whose
    # laundry is still in the pipeline blocks the lock.
    if any(
        e
        for e in db.events.values()
        if e["id"] != event_id
        and e["season_label"] == event["season_label"]
        and e["status"] == "COMPLETED"
        and e["laundry_status"] in LAUNDRY_OPEN
    ):
        raise_err(ERR_LAUNDRY_NOT_READY, "prior event laundry still in COLLECTING/IN_WASH")
    event["status"] = "KIT_LOCKED"
    touch(event)
    return success(_serialize_event(event))


@bp.post("/game-events/<event_id>/complete")
@endpoint("EquipmentManager")
def complete_event(ctx, event_id):
    b = ctx.body
    load = b.get("laundry_load", [])
    if not isinstance(load, list):
        raise_err(ERR_INVALID_REQUEST, "laundry_load must be an array")
    lines = []
    for entry in load:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "laundry_load entries invalid")
        pool_id = entry.get("pool_id")
        qty = entry.get("quantity")
        if not isinstance(pool_id, str) or not pool_id:
            raise_err(ERR_INVALID_REQUEST, "laundry_load pool_id is required")
        if not is_int(qty) or qty <= 0:
            raise_err(ERR_INVALID_REQUEST, "laundry_load quantity must be an integer > 0")
        lines.append({"pool_id": pool_id, "quantity": qty})
    # Existence (rung 4): path event, then body-referenced pools.
    event = db.events.get(event_id)
    if event is None:
        raise_err(ERR_GAME_EVENT_NOT_FOUND, "game event not found")
    pools = []
    for line in lines:
        pool = db.pools.get(line["pool_id"])
        if pool is None:
            raise_err(ERR_POOL_NOT_FOUND, "laundry_load pool not found")
        pools.append(pool)
    # State (rung 5): event KIT_LOCKED, checklist complete, pools ACTIVE.
    if event["status"] != "KIT_LOCKED":
        raise_err(ERR_EVENT_NOT_LOCKED, "complete requires event in KIT_LOCKED")
    if any(i for i in event["checklist"] if i["required"] and i["status"] == "PENDING"):
        raise_err(ERR_CHECKLIST_INCOMPLETE, "a required checklist item is still PENDING")
    for pool in pools:
        if pool["status"] != "ACTIVE":
            raise_err(ERR_POOL_CLOSED, "pool is CLOSED")
    # Fiscal (rung 9): aggregated per pool so duplicate lines cannot overspend.
    needed = {}
    for pool, line in zip(pools, lines):
        needed[pool["id"]] = needed.get(pool["id"], 0) + line["quantity"]
    for pool_id, qty in needed.items():
        if db.pools[pool_id]["available_quantity"] < qty:
            raise_err(ERR_POOL_INSUFFICIENT_STOCK, "pool has insufficient available units")
    for pool_id, qty in needed.items():
        pool = db.pools[pool_id]
        prev = pool["available_quantity"]
        pool["stock_on_hand"] -= qty
        pool["in_laundry_quantity"] += qty
        reconcile_pool(pool, "decrease", prev)
    event["laundry_load"] = lines
    event["status"] = "COMPLETED"
    if lines:
        event["laundry_status"] = "COLLECTING"
        event["laundry_due_at"] = event["kickoff_at"] + LAUNDRY_TURNAROUND
    touch(event)
    return success(_serialize_event(event))


@bp.post("/game-events/<event_id>/cancel")
@endpoint("EquipmentManager")
def cancel_event(ctx, event_id):
    event = db.events.get(event_id)
    if event is None:
        raise_err(ERR_GAME_EVENT_NOT_FOUND, "game event not found")
    if event["status"] not in ("SCHEDULED", "KIT_LOCKED"):
        raise_err(
            ERR_EVENT_NOT_SCHEDULED, "cancel requires event in SCHEDULED or KIT_LOCKED"
        )
    event["status"] = "CANCELLED"
    for item in event["checklist"]:
        if item["status"] == "PENDING":
            item["status"] = "NA"
    touch(event)
    return success(_serialize_event(event))


@bp.post("/game-events/<event_id>/laundry-advance")
@endpoint("LaundryVendor", "EquipmentManager")
def laundry_advance(ctx, event_id):
    event = db.events.get(event_id)
    if event is None:
        raise_err(ERR_GAME_EVENT_NOT_FOUND, "game event not found")
    current = event["laundry_status"]
    if current not in LAUNDRY_STEPS:
        raise_err(
            ERR_LAUNDRY_INVALID_TRANSITION,
            "laundry-advance not valid from NOT_STARTED or CLOSED",
        )
    target = LAUNDRY_STEPS[current]
    if target == "READY":
        # Restock: each load line moves back from in_laundry into stock_on_hand.
        returned = {}
        for line in event["laundry_load"]:
            returned[line["pool_id"]] = returned.get(line["pool_id"], 0) + line["quantity"]
        for pool_id, qty in returned.items():
            pool = db.pools.get(pool_id)
            if pool is None:
                continue
            prev = pool["available_quantity"]
            pool["in_laundry_quantity"] -= qty
            pool["stock_on_hand"] += qty
            reconcile_pool(pool, "increase", prev)
    event["laundry_status"] = target
    touch(event)
    return success(_serialize_event(event))


@bp.post("/game-events/<event_id>/checklist/<item_ref>/complete")
@endpoint("EquipmentManager")
def complete_checklist_item(ctx, event_id, item_ref):
    b = ctx.body
    outcome = b.get("outcome")
    if outcome not in ("DONE", "NA"):
        raise_err(ERR_INVALID_REQUEST, "outcome must be DONE or NA")
    event = db.events.get(event_id)
    if event is None:
        raise_err(ERR_GAME_EVENT_NOT_FOUND, "game event not found")
    item = next((i for i in event["checklist"] if i["item_ref"] == item_ref), None)
    if item is None:
        raise_err(ERR_INVALID_REQUEST, "checklist item not found")
    item["status"] = outcome
    touch(event)
    return success(_serialize_event(event))
