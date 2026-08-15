"""GangOrder endpoints (PRD §3.2, §3.3, §3.5)."""
from decimal import Decimal

from flask import Blueprint, request

import errors
import services
from db import all_of, get, new_resource, pub, save, touch
from middleware import (
    ANY_ROLE, list_response, opt_int, req_enum, req_field, req_int,
    require_roles, require_version,
)
from response import get_body, ok

bp = Blueprint("gangs", __name__)

GANG_TYPES = ("CRANE_GANG", "HOLD_GANG", "LASHING_GANG", "DRIVING_GANG", "GENERAL")
CLASSIFICATIONS = ("CRANE_OPERATOR", "HOLDMAN", "LASHER", "DRIVER", "CLERK")
EQUIPMENT_TYPES = ("SHIP_CRANE", "RTG", "FORKLIFT", "TRACTOR")
AMENDABLE_STATES = ("PLACED", "DISPATCHING", "SHORT_MANNED", "MANNED")
DISPATCHABLE_STATES = ("PLACED", "DISPATCHING", "SHORT_MANNED")


@bp.post("/api/gang-orders")
def create_gang():
    require_roles("StevedoreSuperintendent")
    body = get_body()
    # existence (3) before schema (4)
    shift_window_id = req_field(body, "shift_window_id")
    shift = get("shift_windows", shift_window_id)
    if shift is None:
        raise errors.not_found("Shift window not found")
    gang_type = req_enum(body, "gang_type", GANG_TYPES)
    required_classification = req_enum(body, "required_classification", CLASSIFICATIONS)
    required_headcount = req_int(body, "required_headcount", min_value=1)
    required_equipment_type = req_enum(body, "required_equipment_type", EQUIPMENT_TYPES)
    required_equipment_count = req_int(body, "required_equipment_count", min_value=0)
    if shift["status"] != "OPEN_FOR_ORDERS":
        raise errors.shift_not_open()
    rec = new_resource("gang_orders")
    rec.update({
        "shift_window_id": shift_window_id,
        "gang_type": gang_type,
        "required_classification": required_classification,
        "required_headcount": required_headcount,
        "required_equipment_type": required_equipment_type,
        "required_equipment_count": required_equipment_count,
        "filled_headcount": 0,
        "offered_count": 0,
        "status": "PLACED",
        # PRD §3.2 verbatim: "A new order is born PLACED with ...
        # assigned_equipment_ok false". The §3.4 derivation (true iff coverage
        # >= required) is applied on equipment-assignment change and at the
        # start-work gate, not at creation.
        "assigned_equipment_ok": False,
        "suspension_count": 0,
        "actual_mph": 0,
        "bonus_eligible": False,
        "bonus_pool_cents": 0,
        "bonus_per_worker_cents": 0,
        "_pool_exhausted": False,
    })
    save("gang_orders", rec)
    return ok(pub(rec), 201)


@bp.get("/api/gang-orders")
def list_gangs():
    require_roles(*ANY_ROLE)
    return list_response("gang_orders", {
        "shift_window_id": request.args.get("shift_window_id"),
        "status": request.args.get("status"),
    })


def _get_gang(gid):
    gng = get("gang_orders", gid)
    if gng is None:
        raise errors.not_found("Gang order not found")
    return gng


@bp.get("/api/gang-orders/<gid>")
def get_gang(gid):
    require_roles(*ANY_ROLE)
    return ok(pub(_get_gang(gid)))


@bp.patch("/api/gang-orders/<gid>")
def amend_gang(gid):
    require_roles("StevedoreSuperintendent")
    gang = _get_gang(gid)
    body = get_body()
    new_headcount = opt_int(body, "required_headcount", min_value=1)
    new_equipment_count = opt_int(body, "required_equipment_count", min_value=0)
    # concurrency (5) before state (6)
    require_version(body, "expected_gang_order_version", gang["version"],
                    errors.stale_gang_order)
    if gang["status"] not in AMENDABLE_STATES:
        raise errors.invalid_state("Gang order cannot be amended in its current state")
    if new_headcount is not None:
        gang["required_headcount"] = new_headcount
    if new_equipment_count is not None:
        gang["required_equipment_count"] = new_equipment_count
    # amendment bump waterfall: least-senior CHECKED_IN/WORKING first
    services.recompute_manning(gang, _touch=False)
    filled = gang["filled_headcount"]
    if new_headcount is not None and new_headcount < filled:
        cands = [
            a for a in services.assignments_of_gang(gang["id"])
            if a["status"] in ("CHECKED_IN", "WORKING")
        ]
        # highest seniority_rank_at_dispatch first; ties: most recently created first
        cands.sort(key=lambda a: (-a["seniority_rank_at_dispatch"], -a["_seq"]))
        for a in cands[: filled - new_headcount]:
            a["status"] = "BUMPED"
            touch(a)
        # amendment-driven bumps do NOT auto-offer
    # PRD §3.2: "Every accepted amendment increments the order's `version` by
    # one." All derived-field recomputes below are part of the same mutation,
    # so their internal touches are suppressed — exactly one bump total.
    services.recompute_equipment_ok(gang, _touch=False)
    services.recompute_manning(gang, _touch=False)
    touch(gang)
    return ok(pub(gang))


@bp.post("/api/gang-orders/<gid>/cancel")
def cancel_gang(gid):
    require_roles("StevedoreSuperintendent")
    gang = _get_gang(gid)
    if gang["status"] in services.GANG_TERMINAL:
        raise errors.invalid_state("Gang order is already terminal")
    from_working = gang["status"] == "WORKING"
    for a in services.assignments_of_gang(gang["id"]):
        if a["status"] in ("OFFERED", "CHECKED_IN") or (from_working and a["status"] == "WORKING"):
            a["status"] = "CANCELLED"
            touch(a)
    for ea in services.eas_of_gang(gang["id"]):
        if ea["status"] == "RESERVED" or (from_working and ea["status"] == "ACTIVE"):
            services.release_equipment_assignment(ea)
    gang["status"] = "CANCELLED"
    touch(gang)
    services.recompute_equipment_ok(gang)
    services.recompute_manning(gang)
    services.maybe_close_shift(services.gang_shift(gang))
    return ok(pub(gang))


@bp.post("/api/gang-orders/<gid>/start-work")
def start_work(gid):
    require_roles("GangForeman")
    gang = _get_gang(gid)
    # state (6)
    if gang["status"] not in ("MANNED", "SHORT_MANNED", "SUSPENDED"):
        raise errors.invalid_state("Gang order cannot start work from its current state")
    shift = services.gang_shift(gang)
    if shift["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Shift must be IN_PROGRESS to start work")
    if gang["status"] == "SHORT_MANNED" and gang["filled_headcount"] < 1:
        raise errors.invalid_state("A short-manned gang needs at least one checked-in worker")
    # stoppage gate (7): PARTIAL_STOPPAGE blocks start-work too
    vessel = services.shift_vessel(shift)
    if vessel["work_posture"] != "NORMAL":
        raise errors.work_stoppage()
    # referential (8): recompute equipment coverage at the gate so a gang with
    # required_equipment_count == 0 (born false per PRD §3.2) evaluates to true
    # under the §3.4 derivation (0 bookings >= 0 required) when read here.
    services.recompute_equipment_ok(gang)
    if not gang["assigned_equipment_ok"]:
        raise errors.no_equipment()
    for a in services.assignments_of_gang(gang["id"]):
        if a["status"] == "CHECKED_IN":
            a["status"] = "WORKING"
            touch(a)
    for ea in services.eas_of_gang(gang["id"]):
        if ea["status"] == "RESERVED":
            ea["status"] = "ACTIVE"
            touch(ea)
    gang["status"] = "WORKING"
    touch(gang)
    services.recompute_manning(gang)
    return ok(pub(gang))


@bp.post("/api/gang-orders/<gid>/complete")
def complete_gang(gid):
    require_roles("GangForeman")
    gang = _get_gang(gid)
    if gang["status"] != "WORKING":
        raise errors.invalid_state("Only a WORKING gang order can be completed")
    for a in services.assignments_of_gang(gang["id"]):
        if a["status"] in ("CHECKED_IN", "WORKING"):
            a["status"] = "COMPLETED"
            touch(a)
        elif a["status"] == "OFFERED":
            a["status"] = "CANCELLED"
            touch(a)
    for ea in services.eas_of_gang(gang["id"]):
        if ea["status"] in ("RESERVED", "ACTIVE"):
            services.release_equipment_assignment(ea)
    services.finalize_productivity(gang)
    gang["status"] = "COMPLETED"
    touch(gang)
    services.recompute_equipment_ok(gang)
    services.recompute_manning(gang)
    services.maybe_close_shift(services.gang_shift(gang))
    return ok(pub(gang))


@bp.post("/api/gang-orders/<gid>/dispatch-batch")
def dispatch_batch(gid):
    require_roles("LaborHallDispatcher")
    gang = _get_gang(gid)
    body = get_body()
    forced_ids = None
    if "worker_ids" in body and body["worker_ids"] is not None:
        if not isinstance(body["worker_ids"], list) or not all(
            isinstance(w, str) for w in body["worker_ids"]
        ):
            raise errors.validation("worker_ids must be a list of worker ids")
        forced_ids = list(body["worker_ids"])
        # request-body FK existence (3), left to right
        for wid in forced_ids:
            if get("workers", wid) is None:
                raise errors.not_found(f"Worker not found: {wid}")
    # schema (4): OCC field is non-optional
    require_version(body, "expected_gang_order_version", gang["version"],
                    errors.stale_gang_order)
    # state (6)
    if gang["status"] not in DISPATCHABLE_STATES:
        raise errors.invalid_state("Gang order is not dispatchable in its current state")
    shift = services.gang_shift(gang)
    if shift["status"] not in ("OPEN_FOR_ORDERS", "IN_PROGRESS"):
        raise errors.invalid_state("Shift must be OPEN_FOR_ORDERS or IN_PROGRESS to dispatch")
    # stoppage gate (7): FULL_STOPPAGE blocks dispatch
    vessel = services.shift_vessel(shift)
    if vessel["work_posture"] == "FULL_STOPPAGE":
        raise errors.work_stoppage()
    services.recompute_manning(gang)
    open_slots = gang["required_headcount"] - gang["filled_headcount"] - gang["offered_count"]
    open_slots = max(open_slots, 0)
    # business rules (9/10) fire inside selection for forced lists
    services.run_dispatch_selection(gang, open_slots, forced_ids)
    if gang["status"] == "PLACED":
        gang["status"] = "DISPATCHING"
    # recount after the batch, derive final manning state, then bump exactly once
    gang["filled_headcount"] = sum(
        1 for a in services.assignments_of_gang(gang["id"]) if a["status"] in ("CHECKED_IN", "WORKING"))
    gang["offered_count"] = sum(
        1 for a in services.assignments_of_gang(gang["id"]) if a["status"] == "OFFERED")
    gang["status"] = services.derive_manning_status(gang)
    touch(gang)  # every batch increments version by exactly one
    return ok(pub(gang))


@bp.get("/api/gang-orders/<gid>/productivity")
def productivity(gid):
    require_roles("StevedoreAdmin", "StevedoreSuperintendent", "LaborHallDispatcher",
                  "GangForeman", "PayrollClerk")
    gang = _get_gang(gid)
    total_moves, productive, mph = services.move_aggregates(gang)
    vessel = services.gang_vessel(gang)
    target = vessel["contracted_mph_target"]
    productive_minutes = int(productive) if productive == productive.to_integral_value() else float(productive)
    return ok({
        "gang_order_id": gang["id"],
        "total_moves": total_moves,
        "productive_minutes": productive_minutes,
        "actual_mph": float(mph),
        "mph_target": target,
        "bonus_eligible_now": mph >= Decimal(str(target)),
    })
