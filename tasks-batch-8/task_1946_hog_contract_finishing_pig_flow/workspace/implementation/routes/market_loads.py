"""Market loads (PRD §3.5): slot booking (OCC), dispatch biosecurity, delivery
weight-window branch, and the delivery -> close -> settlement cascade."""

from flask import Blueprint, request

from db import store
from errors import (
    api_error, conflict, malformed,
    ERR_INVALID_STATE_TRANSITION,
    ERR_STALE_SLOT_VERSION,
    ERR_GROUP_NOT_ACTIVE,
    ERR_SLOT_NOT_OPEN,
    ERR_WASH_NOT_VERIFIED,
    ERR_WASH_TYPE_INSUFFICIENT,
    ERR_WASH_STALE,
    ERR_WASH_ALREADY_USED,
    ERR_SLOT_DATE_PAST,
    ERR_DELIVERY_BEFORE_SLOT_DATE,
    ERR_HEAD_COUNT_EXCEEDED,
    ERR_WEIGHT_WINDOW_PROJECTED,
    ERR_SLOT_CAPACITY_EXCEEDED,
)
from middleware import (
    require_roles, ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH,
    ROLE_TRANSPORT_COORDINATOR, ROLE_GROWER,
)
from response import success_object, paginate
from services.core import (
    new_record, touch, ser_market_load,
    group_mortality_total, group_cull_total, group_head_marketed,
    projected_avg_weight, slot_reserved_head,
    slot_refresh_after_booking_change, wash_in_use_by_other_load,
    maybe_auto_close, recompute_settlement_deductions,
    REJECT_PENALTY_CENTS_PER_HEAD, WASH_VALIDITY_HOURS,
)
from util import get_body, req, opt, as_str, as_int, load_or_404, round2
from datetime import timedelta
from decimal import Decimal

bp = Blueprint("market_loads", __name__)

ROLES_READ = [ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_TRANSPORT_COORDINATOR, ROLE_GROWER]


@bp.route("/market-loads", methods=["POST"])
def create_market_load():
    require_roles([ROLE_FIELD_TECH])
    body = get_body()
    # priority 4: body FK existence, left-to-right — group_id then slot_id
    group_id = as_str(req(body, "group_id"), "group_id")
    group = load_or_404(store.pig_groups, group_id, "PigGroup")
    slot_id = as_str(req(body, "slot_id"), "slot_id")
    slot = load_or_404(store.packer_slots, slot_id, "PackerSlot")
    # priority 5: OCC on PackerSlot.version (before field shape / state / ...)
    expected = opt(body, "expected_slot_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != slot["version"]:
            raise api_error(ERR_STALE_SLOT_VERSION, 412,
                            f"expected_slot_version {expected} != current slot version "
                            f"{slot['version']}")
    # priority 6: field shape
    head_count = as_int(req(body, "head_count"), "head_count", 1)
    if expected is None:
        raise malformed("Missing required field: expected_slot_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise malformed("expected_slot_version must be an integer")
    # priority 7: state — group PLACED/MARKETING; slot not CLOSED
    if group["group_status"] not in ("PLACED", "MARKETING"):
        raise conflict(ERR_GROUP_NOT_ACTIVE,
                       "Load booking requires a PLACED or MARKETING group")
    if slot["slot_status"] == "CLOSED":
        raise conflict(ERR_SLOT_NOT_OPEN, "Slot is CLOSED")
    # priority 9: temporal — slot date must not lie before the clock date
    if slot["slot_date"] < store.now().date():
        raise conflict(ERR_SLOT_DATE_PAST, "slot_date is before the clock date")
    # priority 11: head-accounting invariant guards booking (DELIVERED loads only)
    accounted = (group_mortality_total(group_id) + group_cull_total(group_id)
                 + group_head_marketed(group_id) + head_count)
    if accounted > group["head_placed"]:
        raise conflict(ERR_HEAD_COUNT_EXCEEDED,
                       "Load would push accounted head beyond head_placed")
    # priority 11: forward-looking weight window on the slot date (inclusive bounds)
    projected = projected_avg_weight(group, slot)
    if projected < Decimal(slot["min_weight_lbs"]) or projected > Decimal(slot["max_weight_lbs"]):
        raise conflict(ERR_WEIGHT_WINDOW_PROJECTED,
                       f"Projected avg weight {projected} outside slot window "
                       f"[{slot['min_weight_lbs']}, {slot['max_weight_lbs']}]")
    # priority 12: fiscal — reserved head plus new head stays at or below capacity
    reserved = slot_reserved_head(slot_id)
    if reserved + head_count > slot["capacity_head"]:
        raise conflict(ERR_SLOT_CAPACITY_EXCEEDED,
                       f"reserved_head {reserved} + {head_count} exceeds capacity "
                       f"{slot['capacity_head']}")
    rec = new_record()
    rec.update({
        "group_id": group_id, "slot_id": slot_id, "head_count": head_count,
        "truck_wash_id": None, "live_weight_lbs_total": None,
        "avg_weight_lbs": None, "load_status": "SCHEDULED",
    })
    store.market_loads[rec["id"]] = rec
    # booking recomputes reserved_head, advances the slot's version, may flip FULL
    slot_refresh_after_booking_change(slot)
    return success_object(ser_market_load(rec), 201)


@bp.route("/market-loads", methods=["GET"])
def list_market_loads():
    require_roles(ROLES_READ)
    group_id = request.args.get("group_id")
    slot_id = request.args.get("slot_id")
    wash_id = request.args.get("truck_wash_id")
    status = request.args.get("load_status")
    items = list(store.market_loads.values())
    if group_id is not None:
        items = [l for l in items if l["group_id"] == group_id]
    if slot_id is not None:
        items = [l for l in items if l["slot_id"] == slot_id]
    if wash_id is not None:
        items = [l for l in items if l.get("truck_wash_id") == wash_id]
    if status is not None:
        items = [l for l in items if l["load_status"] == status]
    return paginate(items, request.args, ser_market_load)


@bp.route("/market-loads/<lid>", methods=["GET"])
def get_market_load(lid):
    require_roles(ROLES_READ)
    return success_object(ser_market_load(load_or_404(store.market_loads, lid, "MarketLoad")))


@bp.route("/market-loads/<lid>/dispatch", methods=["POST"])
def dispatch_market_load(lid):
    require_roles([ROLE_TRANSPORT_COORDINATOR])
    load = load_or_404(store.market_loads, lid, "MarketLoad")
    body = get_body()
    wash_id = as_str(req(body, "truck_wash_id"), "truck_wash_id")
    wash = load_or_404(store.truck_washes, wash_id, "TruckWash")
    # state (7): the load must be SCHEDULED
    if load["load_status"] != "SCHEDULED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot dispatch a load in {load['load_status']}")
    # biosecurity (8): wash VERIFIED, then FULL_DISINFECT type
    if wash["wash_status"] != "VERIFIED":
        raise conflict(ERR_WASH_NOT_VERIFIED, "Truck wash is not VERIFIED")
    if wash["wash_type"] != "FULL_DISINFECT":
        raise conflict(ERR_WASH_TYPE_INSUFFICIENT, "WASH_ONLY never suffices")
    # temporal (9): dispatch within 48h of the wash (the exact mark is valid);
    # then the clock date must still be on or before the slot's date
    now = store.now()
    if now > wash["washed_at"] + timedelta(hours=WASH_VALIDITY_HOURS):
        raise conflict(ERR_WASH_STALE, "Truck wash is older than 48 hours")
    slot = store.packer_slots.get(load["slot_id"])
    if slot is not None and now.date() > slot["slot_date"]:
        raise conflict(ERR_SLOT_DATE_PAST, "Clock date is past the slot date")
    # quota (11): a wash backs at most one active load
    if wash_in_use_by_other_load(wash_id, exclude_load_id=lid):
        raise conflict(ERR_WASH_ALREADY_USED,
                       "Truck wash already backs another active load")
    load["truck_wash_id"] = wash_id
    load["load_status"] = "DISPATCHED"
    touch(load)
    return success_object(ser_market_load(load))


@bp.route("/market-loads/<lid>/deliver", methods=["POST"])
def deliver_market_load(lid):
    require_roles([ROLE_TRANSPORT_COORDINATOR])
    load = load_or_404(store.market_loads, lid, "MarketLoad")
    body = get_body()
    live_total = as_int(req(body, "live_weight_lbs_total"), "live_weight_lbs_total", 0)
    # state (7): the load must be DISPATCHED
    if load["load_status"] != "DISPATCHED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot deliver a load in {load['load_status']}")
    # temporal (9): delivery is not accepted before the slot's calendar date
    slot = store.packer_slots.get(load["slot_id"])
    if slot is not None and store.now().date() < slot["slot_date"]:
        raise conflict(ERR_DELIVERY_BEFORE_SLOT_DATE,
                       "Clock date is before the slot date")
    load["live_weight_lbs_total"] = live_total
    avg = round2(Decimal(live_total) / Decimal(load["head_count"]))
    load["avg_weight_lbs"] = avg
    in_window = (slot is not None
                 and Decimal(slot["min_weight_lbs"]) <= avg <= Decimal(slot["max_weight_lbs"]))
    group = store.pig_groups.get(load["group_id"])
    if in_window:
        load["load_status"] = "DELIVERED"
        touch(load)
        if group is not None:
            # aggregates are computed live; first delivery moves PLACED -> MARKETING
            if group["group_status"] == "PLACED":
                group["group_status"] = "MARKETING"
            touch(group)
            # a delivery that drains head_current to zero closes the group (§3.8)
            maybe_auto_close(group)
    else:
        load["load_status"] = "REJECTED_AT_PLANT"
        touch(load)
        if group is not None:
            # reject penalty: 1500 cents per head shipped; head are not marketed,
            # and the load still counts toward the slot's reserved set
            group["pending_deductions_cents"] += (
                REJECT_PENALTY_CENTS_PER_HEAD * load["head_count"])
            touch(group)
            recompute_settlement_deductions(group)
    return success_object(ser_market_load(load))


@bp.route("/market-loads/<lid>/cancel", methods=["POST"])
def cancel_market_load(lid):
    require_roles([ROLE_FIELD_TECH])
    load = load_or_404(store.market_loads, lid, "MarketLoad")
    if load["load_status"] not in ("SCHEDULED", "DISPATCHED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot cancel a load in {load['load_status']}")
    load["load_status"] = "CANCELLED"
    touch(load)
    # cancellation pulls the load out of the reserved set; FULL -> OPEN when the
    # reserved head drops back below capacity; a dispatched wash is freed (the
    # load leaves the reserved statuses, so the reuse gate no longer sees it)
    slot = store.packer_slots.get(load["slot_id"])
    if slot is not None:
        slot_refresh_after_booking_change(slot)
    return success_object(ser_market_load(load))
