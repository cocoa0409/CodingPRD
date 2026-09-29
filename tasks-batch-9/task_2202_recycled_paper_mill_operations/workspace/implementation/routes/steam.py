from decimal import Decimal

from flask import Blueprint

import auth
import calc
import clock
import common
import response
import shape
import store
from errors import err
from shape import D, parse_dt, q

bp = Blueprint("steam", __name__)
ZERO = Decimal("0")
CONSUMER_KINDS = ["PAPER_MACHINE", "DEINK_PLANT", "EVAPORATOR"]


def _candidates(ws, we):
    """GRANTED / CURTAILED allocations whose half-open window intersects [ws, we)."""
    rows = []
    for a in store.all_rows("steam_allocations"):
        if a["status"] not in ("GRANTED", "CURTAILED"):
            continue
        a_start = parse_dt(a["window_start"])
        a_end = parse_dt(a["window_end"])
        if calc.windows_overlap_half_open(a_start, a_end, ws, we):
            rows.append((int(a["priority_rank"]), a_start, a["created_at"], a["_seq"], a))
    rows.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
    return [t[4] for t in rows]


@bp.post("/steam-allocations")
def create_allocation():
    auth.require_roles("EnergyManager")
    data = shape.body()
    shape.reject_unexpected_version(data)
    kind = shape.get_enum(data, "consumer_kind", CONSUMER_KINDS)
    ref_id = shape.get_str(data, "consumer_ref_id", required=False, default=None)
    ws = shape.get_dt(data, "window_start")
    we = shape.get_dt(data, "window_end")
    demand = shape.get_num(data, "demand_tph", exclusive_min=0, maximum=200, places=3)
    rank = shape.get_int(data, "priority_rank", minimum=1, maximum=3)
    if kind == "PAPER_MACHINE":
        if ref_id is None:
            raise err("ERR_VALIDATION", "consumer_ref_id is required for PAPER_MACHINE")
        if store.get("paper_machines", ref_id) is None:
            raise err("ERR_LINK_TARGET_NOT_FOUND", "consumer_ref_id does not resolve to a paper machine")
    else:
        ref_id = None
    if we <= ws:
        raise err("ERR_INVALID_WINDOW", "window_end must be strictly after window_start")
    if ws < clock.now():
        raise err("ERR_DATE_OUT_OF_RANGE", "window_start precedes the logical clock instant")
    cands = _candidates(ws, we)
    res = calc.steam_waterfall_dispatch(cands, demand)
    if res["saturated"]:
        raise err("ERR_STEAM_HEADER_SATURATED", "no viable steam header headroom in that window")
    credit = calc.cogen_credit(res["consumed"], res["granted_tph"], ws, we)
    row = {
        "consumer_kind": kind,
        "consumer_ref_id": ref_id,
        "window_start": shape.iso(ws),
        "window_end": shape.iso(we),
        "demand_tph": demand,
        "priority_rank": rank,
        "granted_tph": res["granted_tph"],
        "curtailed_tph": res["curtailed_tph"],
        "cogen_credit_usd": credit,
        "status": res["status"],
    }
    store.insert("steam_allocations", row)
    return response.ok(common.view(row), 201)


@bp.get("/steam-allocations/<aid>")
def get_allocation(aid):
    auth.require_roles("EnergyManager", "MillPlanner")
    return response.ok(common.view(
        common.need("steam_allocations", aid, "ERR_STEAM_ALLOCATION_NOT_FOUND")))


@bp.get("/steam-allocations")
def list_allocations():
    auth.require_roles("EnergyManager", "MillPlanner")
    limit, offset = shape.pagination()
    rows = common.filtered("steam_allocations", {
        "consumer_ref_id": "consumer_ref_id",
        "consumer_kind": "consumer_kind",
        "status": "status",
    })
    return response.ok_list(common.views(shape.paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.post("/steam-allocations/<aid>/release")
def release_allocation(aid):
    auth.require_roles("EnergyManager")
    alloc = common.need("steam_allocations", aid, "ERR_STEAM_ALLOCATION_NOT_FOUND")
    shape.reject_unexpected_version(shape.body())
    if alloc["status"] not in ("GRANTED", "CURTAILED"):
        raise err("ERR_ENV_RECORD_INVALID_STATE", "allocation is not GRANTED or CURTAILED")
    alloc["granted_tph"] = float(q(ZERO, 3))
    alloc["curtailed_tph"] = float(q(D(alloc["demand_tph"]), 3))
    alloc["status"] = "RELEASED"
    store.touch("steam_allocations", alloc)
    return response.ok(common.view(alloc))
