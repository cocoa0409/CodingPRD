"""Load endpoints: create, read, list, line-add, ship, cancel (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint, request

from authz import require_role
from db import store
from errors import (allocation_not_cut, dock_window_conflict, invalid_state,
                    load_over_capacity, malformed, outside_shipping_window,
                    posture_forbids)
from helpers import (body, get_or_404, new_record, paginate, req_field,
                     req_int, req_str, touch)
from respond import success
from serialize import load_out
from services import load_line_units, maybe_close_order
from timeutil import parse_datetime

bp = Blueprint("loads", __name__)

DOCK_BUFFER = timedelta(minutes=30)


def _req_dt(data, name):
    raw = req_field(data, name)
    try:
        return parse_datetime(raw)
    except ValueError:
        raise malformed("Field %s must be an ISO 8601 datetime" % name)


@bp.post("/api/loads")
def create_load():
    require_role("FarmManager")
    data = body()
    season_id = req_field(data, "season_id")
    if isinstance(season_id, str):
        get_or_404(store.seasons, season_id, "season_id does not exist")
    season_id = req_str(data, "season_id")
    carrier_name = req_str(data, "carrier_name")
    capacity_units = req_int(data, "capacity_units", minimum=1)
    win_start = _req_dt(data, "pickup_window_start")
    win_end = _req_dt(data, "pickup_window_end")
    season = store.seasons[season_id]
    # Posture (priority 7): load creation requires HARVEST or SHIPPING.
    if season["posture"] not in ("HARVEST", "SHIPPING"):
        raise posture_forbids("Load creation requires HARVEST or SHIPPING posture")
    # Temporal (priority 10): the pickup window must lie inside the season's
    # shipping window (end inclusive), with end strictly after start.
    if (win_start < season["shipping_window_start"]
            or win_end > season["shipping_window_end"]
            or win_end <= win_start):
        raise outside_shipping_window(
            "The pickup window must lie inside the shipping window")
    # Constraint (priority 25): buffered dock-window conflict. A new window
    # conflicts with any other non-CANCELLED load of the season iff
    # start < other.end + 30m AND other.start < end + 30m; an exact
    # 30-minute gap is permitted.
    for other in store.loads.values():
        if other["season_id"] == season_id and other["status"] != "CANCELLED":
            if (win_start < other["pickup_window_end"] + DOCK_BUFFER
                    and other["pickup_window_start"] < win_end + DOCK_BUFFER):
                raise dock_window_conflict(
                    "The pickup window conflicts with another load")
    rec = new_record({
        "season_id": season_id,
        "carrier_name": carrier_name,
        "capacity_units": capacity_units,
        "pickup_window_start": win_start,
        "pickup_window_end": win_end,
        "lines": [],
        "total_units": 0,
        "status": "BUILDING",
    })
    store.loads[rec["id"]] = rec
    return success(load_out(rec), status=201)


@bp.get("/api/loads/<lid>")
def get_load(lid):
    require_role("Owner", "FarmManager")
    return success(load_out(get_or_404(store.loads, lid)))


@bp.get("/api/loads")
def list_loads():
    require_role("Owner", "FarmManager")
    items = sorted(store.loads.values(), key=lambda ld: ld["_seq"])
    season_id = request.args.get("season_id")
    if season_id is not None:
        items = [ld for ld in items if ld["season_id"] == season_id]
    page, meta = paginate(items)
    return success([load_out(ld) for ld in page], response_type="array",
                   pagination=meta)


@bp.post("/api/loads/<lid>/lines")
def add_load_line(lid):
    require_role("FarmManager")
    load = get_or_404(store.loads, lid)
    data = body()
    # Existence of the body FK (priority 4).
    alloc_id = req_field(data, "allocation_id")
    if isinstance(alloc_id, str):
        get_or_404(store.allocations, alloc_id, "allocation_id does not exist")
    alloc_id = req_str(data, "allocation_id")
    quantity = req_int(data, "quantity", minimum=1)
    # State (priority 6): lines can be added only to a BUILDING load.
    if load["status"] != "BUILDING":
        raise invalid_state("Only a BUILDING load accepts lines")
    season = store.seasons[load["season_id"]]
    # Posture (priority 7): line-add requires HARVEST.
    if season["posture"] != "HARVEST":
        raise posture_forbids("Load lines can be added only in HARVEST posture")
    alloc = store.allocations[alloc_id]
    # Referential (priority 17): the allocation must be CUT with enough
    # cut-but-unloaded headroom.
    if alloc["status"] != "CUT" or quantity > alloc["cut_qty"] - alloc["loaded_qty"]:
        raise allocation_not_cut(
            "The allocation is not CUT or lacks cut-but-unloaded headroom")
    bucket = store.stand_buckets[alloc["bucket_id"]]
    units = load_line_units(bucket["height_class"], quantity)
    # Constraint (priority 26): total_units <= capacity_units (equality allowed).
    if load["total_units"] + units > load["capacity_units"]:
        raise load_over_capacity("The line would exceed the load's capacity")
    load["lines"].append({
        "allocation_id": alloc_id,
        "quantity": quantity,
        "height_class": bucket["height_class"],
        "units": units,
    })
    load["total_units"] += units
    touch(load)
    alloc["loaded_qty"] += quantity
    if alloc["loaded_qty"] == alloc["cut_qty"]:
        alloc["status"] = "LOADED"
    touch(alloc)
    # The order closes itself when fully allocated and fully loaded.
    maybe_close_order(store.orders[alloc["order_id"]])
    return success(load_out(load))


@bp.post("/api/loads/<lid>/ship")
def ship_load(lid):
    require_role("FarmManager")
    load = get_or_404(store.loads, lid)
    if load["status"] != "BUILDING":
        raise invalid_state("Only a BUILDING load can be shipped")
    season = store.seasons[load["season_id"]]
    if season["posture"] != "SHIPPING":
        raise posture_forbids("Shipping requires SHIPPING posture")
    # Temporal (priority 10): the clock must sit inside the shipping window,
    # both boundary instants inclusive.
    clk = store.clock
    if not (season["shipping_window_start"] <= clk <= season["shipping_window_end"]):
        raise outside_shipping_window("The clock is outside the shipping window")
    load["status"] = "SHIPPED"
    touch(load)
    return success(load_out(load))


@bp.post("/api/loads/<lid>/cancel")
def cancel_load(lid):
    require_role("FarmManager")
    load = get_or_404(store.loads, lid)
    if load["status"] != "BUILDING":
        raise invalid_state("Only a BUILDING load can be cancelled")
    season = store.seasons[load["season_id"]]
    if season["posture"] == "CLOSED":
        raise posture_forbids("The season is CLOSED")
    # Roll every line's quantity back off its allocation's loaded_qty.
    for line in load["lines"]:
        alloc = store.allocations[line["allocation_id"]]
        alloc["loaded_qty"] -= line["quantity"]
        if alloc["status"] == "LOADED" and alloc["loaded_qty"] < alloc["cut_qty"]:
            alloc["status"] = "CUT"
        touch(alloc)
    # A load cancellation never closes an order by itself.
    load["status"] = "CANCELLED"
    touch(load)
    return success(load_out(load))
