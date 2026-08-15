"""All API routes (scaffold §1.5 endpoint table / PRD §4).

Validation order per PRD §2.11: auth -> rbac -> existence/scoping -> OCC ->
state -> roadability -> rail cutoff -> window -> booking shape -> membership ->
terminal capacity -> slot availability -> train arrival -> overpay -> open damage
-> in-flight transaction -> check-in container state -> payload shape.
"""
import math

from flask import Blueprint

import db
import services
from db import now, now_clock_iso, now_iso, stamp_new, touch
from errors import (
    ApiError,
    ERR_CHASSIS_UNROADABLE,
    ERR_CONGESTED_WINDOW_CAP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MEMBERSHIP_NOT_ACTIVE,
    ERR_NOT_FOUND,
    ERR_NO_CHECKED_IN_APPOINTMENT,
    ERR_NO_YARD_SLOT_AVAILABLE,
    ERR_OPEN_DAMAGE_EXISTS,
    ERR_OUTSIDE_APPOINTMENT_WINDOW,
    ERR_OVERPAY,
    ERR_RAIL_CUTOFF_MISSED,
    ERR_STALE_VERSION,
    ERR_TERMINAL_CLOSED,
    ERR_TRAIN_NOT_ARRIVED,
    ERR_TRANSACTION_IN_FLIGHT,
)
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from util import body, opt_str, pagination, req_dt, req_enum, req_int, req_str

bp = Blueprint("api", __name__)

# Role groups used across the endpoint table.
R_TERMINAL_GET = ALL_ROLES
R_POOL_GET = ["TerminalManager", "GateSupervisor", "PoolAdministrator", "MaintenancePlanner", "GateClerk"]
R_POOL_GET_FLAT = R_POOL_GET + ["BillingClerk"]
R_MEMBERSHIP_GET = ["PoolAdministrator", "TerminalManager", "BillingClerk"]
R_CARRIER_GET = ["TerminalManager", "PoolAdministrator", "BillingClerk", "GateSupervisor", "GateClerk"]
R_TRAIN_GET = ["TerminalManager", "RailCoordinator", "YardPlanner", "GateSupervisor", "GateClerk"]
R_SLOT_GET = ["TerminalManager", "YardPlanner", "GateSupervisor"]
R_CONTAINER_GET = ["TerminalManager", "RailCoordinator", "YardPlanner", "GateSupervisor", "GateClerk", "BillingClerk"]
R_APPT_GET = ["TerminalManager", "GateSupervisor", "GateClerk", "BillingClerk"]
R_TX_GET = ["TerminalManager", "GateSupervisor", "GateClerk", "BillingClerk", "MaintenancePlanner"]
R_DAMAGE_GET = ["TerminalManager", "MaintenancePlanner", "GateClerk", "BillingClerk"]
R_LEDGER_GET = ["TerminalManager", "BillingClerk"]

ISO_TYPES = ["20FT", "40FT", "40HC", "45FT"]
DIRECTIONS = ["IN", "OUT"]
DAMAGE_KINDS = ["TIRE", "BRAKE", "LIGHTS", "FRAME", "CONTAINER_DENT", "CONTAINER_PUNCTURE"]
SEVERITIES = ["MINOR", "MAJOR", "SAFETY_CRITICAL"]


# ---------------------------------------------------------------------------
# Lookup / scoping helpers (existence priority 3, left-to-right along the path)
# ---------------------------------------------------------------------------

def get_terminal(tid):
    t = db.terminals.get(tid)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Terminal not found")
    return t


def get_pool(tid, pid):
    get_terminal(tid)
    p = db.pools.get(pid)
    if p is None or p["terminal_id"] != tid:
        raise ApiError(ERR_NOT_FOUND, 404, "ChassisPool not found")
    return p


def get_chassis(tid, pid, cid):
    get_pool(tid, pid)
    c = db.chassis.get(cid)
    if c is None or c["pool_id"] != pid:
        raise ApiError(ERR_NOT_FOUND, 404, "Chassis not found")
    return c


def get_membership(tid, pid, mid):
    get_pool(tid, pid)
    m = db.memberships.get(mid)
    if m is None or m["pool_id"] != pid:
        raise ApiError(ERR_NOT_FOUND, 404, "ChassisMembership not found")
    return m


def get_carrier(cid):
    c = db.carriers.get(cid)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Carrier not found")
    return c


def get_container(tid, cid):
    get_terminal(tid)
    c = db.containers.get(cid)
    if c is None or c["terminal_id"] != tid:
        raise ApiError(ERR_NOT_FOUND, 404, "Container not found")
    return c


def get_slot(tid, sid):
    get_terminal(tid)
    s = db.slots.get(sid)
    if s is None or s["terminal_id"] != tid:
        raise ApiError(ERR_NOT_FOUND, 404, "YardSlot not found")
    return s


def get_train(tid, trid):
    get_terminal(tid)
    t = db.trains.get(trid)
    if t is None or t["terminal_id"] != tid:
        raise ApiError(ERR_NOT_FOUND, 404, "Train not found")
    return t


def get_appointment(tid, aid):
    get_terminal(tid)
    a = db.appointments.get(aid)
    if a is None or a["terminal_id"] != tid:
        raise ApiError(ERR_NOT_FOUND, 404, "GateAppointment not found")
    return a


def get_transaction(tid, txid):
    get_terminal(tid)
    t = db.transactions.get(txid)
    if t is None or t["terminal_id"] != tid:
        raise ApiError(ERR_NOT_FOUND, 404, "GateTransaction not found")
    return t


def get_damage(tid, did):
    get_terminal(tid)
    d = db.damage.get(did)
    if d is None or d["terminal_id"] != tid:
        raise ApiError(ERR_NOT_FOUND, 404, "DamageInspection not found")
    return d


def get_ledger(tid, lid):
    get_terminal(tid)
    e = db.ledger.get(lid)
    if e is None or e["terminal_id"] != tid:
        raise ApiError(ERR_NOT_FOUND, 404, "BillingLedgerEntry not found")
    return e


def list_view(records, filters=None):
    """Apply exact-match filters, sort by created_at ASC, paginate."""
    items = list(records)
    if filters:
        for key, val in filters.items():
            if val is None:
                continue
            items = [r for r in items if r.get(key) == val]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    limit, offset = pagination()
    return ok_list(items[offset:offset + limit], total, limit, offset)


# ---------------------------------------------------------------------------
# Clock (test-driving endpoint)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(ALL_ROLES)
    data = body()
    dt = req_dt(data, "to_iso8601")
    db.CLOCK.set(dt)
    return ok({"current_utc": db.CLOCK.now_clock_iso()})


# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------

@bp.post("/terminals")
def create_terminal():
    auth(["TerminalManager"])
    data = body()
    t = stamp_new({
        "terminal_code": req_str(data, "terminal_code"),
        "rail_cutoff_minutes_before_departure": req_int(data, "rail_cutoff_minutes_before_departure", positive=True),
        "gate_free_hours": req_int(data, "gate_free_hours", positive=True),
        "per_diem_rate_cents": req_int(data, "per_diem_rate_cents"),
        "storage_rate_cents": req_int(data, "storage_rate_cents"),
        "flip_fee_cents": req_int(data, "flip_fee_cents"),
        "max_stack_height": req_int(data, "max_stack_height", positive=True),
        "yard_slot_count": req_int(data, "yard_slot_count", positive=True),
        "yard_slots_in_use": 0,
        "yard_slots_free": None,  # set below
        "posture": "OPEN",
        "ops_run_index": 0,
    })
    t["yard_slots_free"] = t["yard_slot_count"]
    db.terminals[t["id"]] = t
    return ok(t, 201)


@bp.get("/terminals/<tid>")
def get_terminal_route(tid):
    auth(R_TERMINAL_GET)
    return ok(get_terminal(tid))


@bp.get("/terminals")
def list_terminals():
    auth(R_TERMINAL_GET)
    return list_view(db.terminals.values())


# ---------------------------------------------------------------------------
# ChassisPool
# ---------------------------------------------------------------------------

@bp.post("/terminals/<tid>/pools")
def create_pool(tid):
    auth(["PoolAdministrator"])
    get_terminal(tid)
    data = body()
    p = stamp_new({
        "terminal_id": tid,
        "pool_code": req_str(data, "pool_code"),
        "total_chassis_count": 0,
        "available_chassis_count": 0,
        "reserved_chassis_count": 0,
        "out_chassis_count": 0,
        "maintenance_chassis_count": 0,
        "flip_fee_balance_cents": 0,
    })
    db.pools[p["id"]] = p
    return ok(p, 201)


@bp.get("/terminals/<tid>/pools/<pid>")
def get_pool_route(tid, pid):
    auth(R_POOL_GET)
    return ok(get_pool(tid, pid))


@bp.get("/terminals/<tid>/pools")
def list_pools(tid):
    auth(R_POOL_GET)
    get_terminal(tid)
    return list_view(
        (p for p in db.pools.values() if p["terminal_id"] == tid),
        filters={"terminal_id": _q("terminal_id")},
    )


def _q(name):
    from flask import request
    return request.args.get(name)


# ---------------------------------------------------------------------------
# Chassis
# ---------------------------------------------------------------------------

@bp.post("/terminals/<tid>/pools/<pid>/chassis")
def create_chassis(tid, pid):
    auth(["PoolAdministrator"])
    pool = get_pool(tid, pid)
    data = body()
    c = stamp_new({
        "pool_id": pid,
        "chassis_number": req_str(data, "chassis_number"),
        "status": "AVAILABLE",
        "roadability_status": "ROADABLE",
        "last_inspection_at": None,
        "out_gate_transaction_id": None,
        "current_container_id": None,
        "reserved_appointment_id": None,
    })
    db.chassis[c["id"]] = c
    pool["total_chassis_count"] += 1
    pool["available_chassis_count"] += 1
    touch(pool)
    return ok(c, 201)


@bp.get("/terminals/<tid>/pools/<pid>/chassis/<cid>")
def get_chassis_route(tid, pid, cid):
    auth(R_POOL_GET)
    return ok(get_chassis(tid, pid, cid))


@bp.get("/terminals/<tid>/pools/<pid>/chassis")
def list_chassis(tid, pid):
    auth(R_POOL_GET)
    get_pool(tid, pid)
    return list_view(
        (c for c in db.chassis.values() if c["pool_id"] == pid),
        filters={
            "status": _q("status"),
            "roadability_status": _q("roadability_status"),
            "out_gate_transaction_id": _q("out_gate_transaction_id"),
            "current_container_id": _q("current_container_id"),
        },
    )


@bp.post("/terminals/<tid>/pools/<pid>/chassis/<cid>/reserve")
def reserve_chassis(tid, pid, cid):
    auth(["GateSupervisor"])
    pool = get_pool(tid, pid)
    ch = get_chassis(tid, pid, cid)
    data = body()
    # OCC (priority 4) — expected_pool_version is required on this endpoint.
    if "expected_pool_version" not in data or data.get("expected_pool_version") is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_pool_version is required")
    if data["expected_pool_version"] != pool["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "ChassisPool version mismatch")
    appointment_id = req_str(data, "appointment_id")
    # State (5): chassis must be AVAILABLE
    if ch["status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE, 409, "Chassis is not AVAILABLE")
    # Roadability (6)
    if ch["roadability_status"] != "ROADABLE":
        raise ApiError(ERR_CHASSIS_UNROADABLE, 409, "Chassis is not ROADABLE")
    # Appointment must be CHECKED_IN with direction OUT
    appt = db.appointments.get(appointment_id)
    if appt is None or appt["status"] != "CHECKED_IN" or appt["direction"] != "OUT":
        raise ApiError(ERR_NO_CHECKED_IN_APPOINTMENT, 409,
                       "No CHECKED_IN OUT appointment for reservation")
    ch["status"] = "RESERVED"
    ch["reserved_appointment_id"] = appt["id"]
    touch(ch)
    pool["reserved_chassis_count"] += 1
    pool["available_chassis_count"] -= 1
    touch(pool)
    return ok(ch)


@bp.post("/terminals/<tid>/pools/<pid>/chassis/<cid>/enter_maintenance")
def enter_maintenance(tid, pid, cid):
    auth(["MaintenancePlanner"])
    pool = get_pool(tid, pid)
    ch = get_chassis(tid, pid, cid)
    if ch["status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE, 409, "Chassis is not AVAILABLE")
    ch["status"] = "MAINTENANCE"
    touch(ch)
    pool["available_chassis_count"] -= 1
    pool["maintenance_chassis_count"] += 1
    touch(pool)
    return ok(ch)


@bp.post("/terminals/<tid>/pools/<pid>/chassis/<cid>/exit_maintenance")
def exit_maintenance(tid, pid, cid):
    auth(["MaintenancePlanner"])
    pool = get_pool(tid, pid)
    ch = get_chassis(tid, pid, cid)
    if ch["status"] != "MAINTENANCE":
        raise ApiError(ERR_INVALID_STATE, 409, "Chassis is not MAINTENANCE")
    if ch["roadability_status"] != "ROADABLE":
        raise ApiError(ERR_CHASSIS_UNROADABLE, 409, "Chassis is not ROADABLE")
    ch["status"] = "AVAILABLE"
    touch(ch)
    pool["maintenance_chassis_count"] -= 1
    pool["available_chassis_count"] += 1
    touch(pool)
    return ok(ch)


@bp.post("/terminals/<tid>/pools/<pid>/chassis/<cid>/retire")
def retire_chassis(tid, pid, cid):
    auth(["TerminalManager"])
    pool = get_pool(tid, pid)
    ch = get_chassis(tid, pid, cid)
    if ch["status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE, 409, "Chassis is not AVAILABLE")
    open_damage = any(
        d for d in db.damage.values()
        if d.get("chassis_id") == cid and d["status"] == "OPEN"
    )
    if open_damage:
        raise ApiError(ERR_OPEN_DAMAGE_EXISTS, 409,
                       "OPEN damage inspection references this chassis")
    ch["status"] = "RETIRED"
    touch(ch)
    pool["available_chassis_count"] -= 1
    pool["total_chassis_count"] -= 1
    touch(pool)
    return ok(ch)


# ---------------------------------------------------------------------------
# ChassisMembership
# ---------------------------------------------------------------------------

@bp.post("/terminals/<tid>/pools/<pid>/memberships")
def create_membership(tid, pid):
    auth(["PoolAdministrator"])
    get_pool(tid, pid)
    data = body()
    carrier_id = req_str(data, "carrier_id")
    get_carrier(carrier_id)
    m = stamp_new({
        "pool_id": pid,
        "carrier_id": carrier_id,
        "membership_status": "ACTIVE",
        "flip_fee_credit_cents": 0,
    })
    db.memberships[m["id"]] = m
    return ok(m, 201)


@bp.get("/terminals/<tid>/pools/<pid>/memberships/<mid>")
def get_membership_route(tid, pid, mid):
    auth(R_MEMBERSHIP_GET)
    return ok(get_membership(tid, pid, mid))


@bp.get("/terminals/<tid>/pools/<pid>/memberships")
def list_memberships(tid, pid):
    auth(R_MEMBERSHIP_GET)
    get_pool(tid, pid)
    return list_view(
        (m for m in db.memberships.values() if m["pool_id"] == pid),
        filters={"membership_status": _q("membership_status"), "carrier_id": _q("carrier_id")},
    )


@bp.post("/terminals/<tid>/pools/<pid>/memberships/<mid>/suspend")
def suspend_membership(tid, pid, mid):
    auth(["PoolAdministrator"])
    get_pool(tid, pid)
    m = get_membership(tid, pid, mid)
    if m["membership_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Membership is not ACTIVE")
    m["membership_status"] = "SUSPENDED"
    touch(m)
    services.release_carrier_reserved_chassis(m["carrier_id"], pid)
    return ok(m)


@bp.post("/terminals/<tid>/pools/<pid>/memberships/<mid>/reactivate")
def reactivate_membership(tid, pid, mid):
    auth(["PoolAdministrator"])
    m = get_membership(tid, pid, mid)
    if m["membership_status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Membership is not SUSPENDED")
    m["membership_status"] = "ACTIVE"
    touch(m)
    return ok(m)


@bp.post("/terminals/<tid>/pools/<pid>/memberships/<mid>/terminate")
def terminate_membership(tid, pid, mid):
    auth(["PoolAdministrator"])
    m = get_membership(tid, pid, mid)
    if m["membership_status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Membership must be ACTIVE or SUSPENDED to terminate")
    open_flip = any(
        e for e in db.ledger.values()
        if e["carrier_id"] == m["carrier_id"]
        and e["entry_kind"] == "FLIP_FEE"
        and e["status"] in ("OPEN", "PARTIALLY_APPLIED")
    )
    if open_flip:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Carrier has OPEN or PARTIALLY_APPLIED FLIP_FEE ledger entries")
    prior = m["membership_status"]
    m["membership_status"] = "TERMINATED"
    touch(m)
    if prior == "ACTIVE":
        services.release_carrier_reserved_chassis(m["carrier_id"], pid)
    return ok(m)


@bp.post("/terminals/<tid>/pools/<pid>/memberships/<mid>/load_flip_credit")
def load_flip_credit(tid, pid, mid):
    auth(["BillingClerk"])
    m = get_membership(tid, pid, mid)
    data = body()
    credit = req_int(data, "credit_cents", positive=True)
    m["flip_fee_credit_cents"] = m.get("flip_fee_credit_cents", 0) + credit
    touch(m)
    return ok(m)


# ---------------------------------------------------------------------------
# Carrier
# ---------------------------------------------------------------------------

@bp.post("/carriers")
def create_carrier():
    auth(["TerminalManager"])
    data = body()
    c = stamp_new({
        "scac_code": req_str(data, "scac_code"),
        "carrier_name": req_str(data, "carrier_name"),
        "billing_credit_limit_cents": req_int(data, "billing_credit_limit_cents"),
        "outstanding_billing_cents": 0,
    })
    db.carriers[c["id"]] = c
    return ok(c, 201)


@bp.get("/carriers/<cid>")
def get_carrier_route(cid):
    auth(R_CARRIER_GET)
    return ok(get_carrier(cid))


@bp.get("/carriers")
def list_carriers():
    auth(R_CARRIER_GET)
    return list_view(db.carriers.values())


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------

@bp.post("/terminals/<tid>/trains")
def create_train(tid):
    auth(["RailCoordinator"])
    terminal = get_terminal(tid)
    data = body()
    dep = req_dt(data, "scheduled_departure_utc")
    cutoff = dep - __import__("datetime").timedelta(
        minutes=terminal["rail_cutoff_minutes_before_departure"]
    )
    t = stamp_new({
        "terminal_id": tid,
        "train_symbol": req_str(data, "train_symbol"),
        "scheduled_departure_utc": db._fmt_clock(dep),
        "actual_departure_utc": None,
        "status": "SCHEDULED",
        "rail_cutoff_at": db._fmt_clock(cutoff),
    })
    db.trains[t["id"]] = t
    return ok(t, 201)


@bp.get("/terminals/<tid>/trains/<trid>")
def get_train_route(tid, trid):
    auth(R_TRAIN_GET)
    return ok(get_train(tid, trid))


@bp.get("/terminals/<tid>/trains")
def list_trains(tid):
    auth(R_TRAIN_GET)
    get_terminal(tid)
    return list_view(
        (t for t in db.trains.values() if t["terminal_id"] == tid),
        filters={"status": _q("status")},
    )


def _void_inbound_containers(train):
    for c in db.containers.values():
        if c.get("planned_train_id") == train["id"] and c["status"] == "INBOUND_TRAIN":
            c["status"] = "VOIDED"
            touch(c)


@bp.post("/terminals/<tid>/trains/<trid>/mark_arrived")
def mark_arrived(tid, trid):
    auth(["RailCoordinator"])
    t = get_train(tid, trid)
    if t["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Train is not SCHEDULED")
    t["status"] = "ARRIVED"
    touch(t)
    return ok(t)


@bp.post("/terminals/<tid>/trains/<trid>/begin_loading")
def begin_loading(tid, trid):
    auth(["RailCoordinator"])
    t = get_train(tid, trid)
    if t["status"] != "ARRIVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Train is not ARRIVED")
    t["status"] = "LOADING"
    touch(t)
    return ok(t)


@bp.post("/terminals/<tid>/trains/<trid>/mark_departed")
def mark_departed(tid, trid):
    auth(["RailCoordinator"])
    t = get_train(tid, trid)
    if t["status"] != "LOADING":
        raise ApiError(ERR_INVALID_STATE, 409, "Train is not LOADING")
    t["status"] = "DEPARTED"
    t["actual_departure_utc"] = now_clock_iso()
    touch(t)
    # Containers still INBOUND_TRAIN -> VOIDED; their OPEN per-diem/storage waived
    for c in db.containers.values():
        if c.get("planned_train_id") == t["id"] and c["status"] == "INBOUND_TRAIN":
            c["status"] = "VOIDED"
            touch(c)
            services.waive_open_entries_for_container(c["id"], kinds=("PER_DIEM", "STORAGE"))
    return ok(t)


@bp.post("/terminals/<tid>/trains/<trid>/cancel")
def cancel_train(tid, trid):
    auth(["RailCoordinator"])
    t = get_train(tid, trid)
    if t["status"] not in ("SCHEDULED", "ARRIVED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Train must be SCHEDULED or ARRIVED to cancel")
    t["status"] = "CANCELLED"
    touch(t)
    _void_inbound_containers(t)
    return ok(t)


# ---------------------------------------------------------------------------
# YardSlot
# ---------------------------------------------------------------------------

@bp.post("/terminals/<tid>/slots")
def create_slot(tid):
    auth(["YardPlanner"])
    terminal = get_terminal(tid)
    data = body()
    s = stamp_new({
        "terminal_id": tid,
        "slot_code": req_str(data, "slot_code"),
        "row": req_str(data, "row"),
        "tier_max": req_int(data, "tier_max", positive=True),
        "status": "EMPTY",
        "occupied_container_id": None,
        "current_height": 0,
    })
    db.slots[s["id"]] = s
    services.recompute_posture(terminal)
    touch(terminal)
    return ok(s, 201)


@bp.get("/terminals/<tid>/slots/<sid>")
def get_slot_route(tid, sid):
    auth(R_SLOT_GET)
    return ok(get_slot(tid, sid))


@bp.get("/terminals/<tid>/slots")
def list_slots(tid):
    auth(R_SLOT_GET)
    get_terminal(tid)
    return list_view(
        (s for s in db.slots.values() if s["terminal_id"] == tid),
        filters={"status": _q("status"), "row": _q("row"),
                 "occupied_container_id": _q("occupied_container_id")},
    )


def _slot_transition(tid, sid, from_status, to_status):
    auth(["YardPlanner"])
    terminal = get_terminal(tid)
    s = get_slot(tid, sid)
    if s["status"] != from_status:
        raise ApiError(ERR_INVALID_STATE, 409, f"Slot is not {from_status}")
    s["status"] = to_status
    touch(s)
    services.recompute_posture(terminal)
    touch(terminal)
    return ok(s)


@bp.post("/terminals/<tid>/slots/<sid>/block")
def block_slot(tid, sid):
    return _slot_transition(tid, sid, "EMPTY", "BLOCKED")


@bp.post("/terminals/<tid>/slots/<sid>/unblock")
def unblock_slot(tid, sid):
    return _slot_transition(tid, sid, "BLOCKED", "EMPTY")


@bp.post("/terminals/<tid>/slots/<sid>/reserve")
def reserve_slot(tid, sid):
    return _slot_transition(tid, sid, "EMPTY", "RESERVED")


@bp.post("/terminals/<tid>/slots/<sid>/unreserve")
def unreserve_slot(tid, sid):
    return _slot_transition(tid, sid, "RESERVED", "EMPTY")


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------

@bp.post("/terminals/<tid>/containers")
def create_container(tid):
    auth(["RailCoordinator"])
    get_terminal(tid)
    data = body()
    train_id = req_str(data, "planned_train_id")
    train = db.trains.get(train_id)
    if train is None or train["terminal_id"] != tid:
        raise ApiError(ERR_NOT_FOUND, 404, "Train not found")
    c = stamp_new({
        "terminal_id": tid,
        "container_number": req_str(data, "container_number"),
        "iso_type": req_enum(data, "iso_type", ISO_TYPES),
        "status": "INBOUND_TRAIN",
        "free_time_expires_at": None,
        "in_ground_at": None,
        "yard_slot_id": None,
        "stack_height": None,
        "planned_train_id": train_id,
        "out_gate_transaction_id": None,
    })
    db.containers[c["id"]] = c
    return ok(c, 201)


@bp.get("/terminals/<tid>/containers/<cid>")
def get_container_route(tid, cid):
    auth(R_CONTAINER_GET)
    return ok(get_container(tid, cid))


@bp.get("/terminals/<tid>/containers")
def list_containers(tid):
    auth(R_CONTAINER_GET)
    get_terminal(tid)
    return list_view(
        (c for c in db.containers.values() if c["terminal_id"] == tid),
        filters={
            "status": _q("status"),
            "planned_train_id": _q("planned_train_id"),
            "yard_slot_id": _q("yard_slot_id"),
            "out_gate_transaction_id": _q("out_gate_transaction_id"),
        },
    )


def _ground_container(terminal, container):
    """Shared grounding logic (initial ground and IN-transaction re-ground)."""
    slot = services.select_yard_slot(terminal["id"])
    container["in_ground_at"] = now_clock_iso()
    expiry = now() + __import__("datetime").timedelta(hours=terminal["gate_free_hours"])
    container["free_time_expires_at"] = db._fmt_clock(expiry)
    container["status"] = "ON_GROUND"
    services.occupy_slot(slot, container, terminal)
    touch(container)


@bp.post("/terminals/<tid>/containers/<cid>/ground")
def ground_container(tid, cid):
    auth(["YardPlanner"])
    terminal = get_terminal(tid)
    c = get_container(tid, cid)
    data = body()
    # OCC (priority 4)
    if "expected_terminal_version" not in data or data.get("expected_terminal_version") is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_terminal_version is required")
    if data["expected_terminal_version"] != terminal["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Terminal version mismatch")
    # State (5)
    if c["status"] != "INBOUND_TRAIN":
        raise ApiError(ERR_INVALID_STATE, 409, "Container is not INBOUND_TRAIN")
    # Train arrival (13)
    train = db.trains.get(c.get("planned_train_id") or "")
    if train is None or train["status"] != "ARRIVED":
        raise ApiError(ERR_TRAIN_NOT_ARRIVED, 409, "Planned train has not ARRIVED")
    # Terminal capacity (11)
    if terminal["posture"] == "CLOSED":
        raise ApiError(ERR_TERMINAL_CLOSED, 409, "Terminal posture is CLOSED")
    # Slot availability (12) — raised inside _ground_container
    _ground_container(terminal, c)
    return ok(c)


@bp.post("/terminals/<tid>/containers/<cid>/void")
def void_container(tid, cid):
    auth(["TerminalManager"])
    terminal = get_terminal(tid)
    c = get_container(tid, cid)
    if c["status"] != "ON_GROUND":
        raise ApiError(ERR_INVALID_STATE, 409, "Container is not ON_GROUND")
    open_damage = any(
        d for d in db.damage.values()
        if d.get("container_id") == cid and d["status"] == "OPEN"
    )
    if open_damage:
        raise ApiError(ERR_OPEN_DAMAGE_EXISTS, 409,
                       "OPEN damage inspection references this container")
    c["status"] = "VOIDED"
    services.release_slot(c, terminal)
    touch(c)
    services.waive_open_entries_for_container(cid)
    return ok(c)


# ---------------------------------------------------------------------------
# GateAppointment
# ---------------------------------------------------------------------------

def _active_membership_for_terminal(carrier_id, terminal_id):
    pool = services.terminal_pool(terminal_id)
    if pool is None:
        return None
    m = services.carrier_membership_on_pool(carrier_id, pool["id"])
    if m is not None and m["membership_status"] == "ACTIVE":
        return m
    return None


@bp.post("/terminals/<tid>/appointments")
def create_appointment(tid):
    auth(["GateSupervisor"])
    terminal = get_terminal(tid)
    data = body()
    carrier_id = req_str(data, "carrier_id")
    container_id = req_str(data, "container_id")
    direction = req_enum(data, "direction", DIRECTIONS)
    ws = req_dt(data, "window_start_utc")
    we = req_dt(data, "window_end_utc")
    # Existence of referenced entities
    get_carrier(carrier_id)
    container = db.containers.get(container_id)
    if container is None or container["terminal_id"] != tid:
        raise ApiError(ERR_NOT_FOUND, 404, "Container not found")
    # Booking window shape (9): end strictly after start; CONGESTED cap 3600s
    if (we - ws).total_seconds() <= 0:
        raise ApiError(ERR_CONGESTED_WINDOW_CAP, 409,
                       "window_end_utc must be strictly after window_start_utc")
    if terminal["posture"] == "CONGESTED":
        if (we - ws).total_seconds() > services.CONGESTED_MAX_WINDOW_SECONDS:
            raise ApiError(ERR_CONGESTED_WINDOW_CAP, 409,
                           "Window exceeds 3600 seconds under CONGESTED posture")
    # Membership (10) — OUT booking requires ACTIVE membership
    if direction == "OUT":
        if _active_membership_for_terminal(carrier_id, tid) is None:
            raise ApiError(ERR_MEMBERSHIP_NOT_ACTIVE, 409,
                           "Carrier has no ACTIVE membership on the chassis pool")
    a = stamp_new({
        "terminal_id": tid,
        "carrier_id": carrier_id,
        "container_id": container_id,
        "direction": direction,
        "window_start_utc": db._fmt_clock(ws),
        "window_end_utc": db._fmt_clock(we),
        "status": "BOOKED",
        "assigned_driver_id": None,
        "checked_in_at": None,
        "completed_at": None,
    })
    db.appointments[a["id"]] = a
    return ok(a, 201)


@bp.get("/terminals/<tid>/appointments/<aid>")
def get_appointment_route(tid, aid):
    auth(R_APPT_GET)
    return ok(get_appointment(tid, aid))


@bp.get("/terminals/<tid>/appointments")
def list_appointments(tid):
    auth(R_APPT_GET)
    get_terminal(tid)
    return list_view(
        (a for a in db.appointments.values() if a["terminal_id"] == tid),
        filters={"status": _q("status"), "direction": _q("direction"),
                 "carrier_id": _q("carrier_id"), "container_id": _q("container_id")},
    )


@bp.post("/terminals/<tid>/appointments/<aid>/check_in")
def check_in_appointment(tid, aid):
    auth(["GateClerk"])
    a = get_appointment(tid, aid)
    data = body()
    # State (5)
    if a["status"] != "BOOKED":
        raise ApiError(ERR_INVALID_STATE, 409, "Appointment is not BOOKED")
    # Window (8) — inclusive boundaries
    clock = now()
    ws = db._parse_iso(a["window_start_utc"])
    we = db._parse_iso(a["window_end_utc"])
    if clock < ws or clock > we:
        raise ApiError(ERR_OUTSIDE_APPOINTMENT_WINDOW, 409,
                       "Check-in outside the appointment window")
    # Membership (10) precedes check-in container state (17) per §2.11's fixed
    # validation sequence.
    if a["direction"] == "OUT":
        if _active_membership_for_terminal(a["carrier_id"], tid) is None:
            raise ApiError(ERR_MEMBERSHIP_NOT_ACTIVE, 409,
                           "Carrier membership is not ACTIVE")
    # Container state (17)
    container = db.containers.get(a["container_id"])
    if a["direction"] == "IN":
        if container is None or container["status"] not in ("MOUNTED", "OUTBOUND_TRUCK"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "IN check-in requires container MOUNTED or OUTBOUND_TRUCK")
    else:
        if container is None or container["status"] != "ON_GROUND":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "OUT check-in requires container ON_GROUND")
    driver_id = req_str(data, "driver_id")
    a["status"] = "CHECKED_IN"
    a["checked_in_at"] = now_clock_iso()
    a["assigned_driver_id"] = driver_id
    touch(a)
    return ok(a)


@bp.post("/terminals/<tid>/appointments/<aid>/cancel")
def cancel_appointment(tid, aid):
    auth(["GateClerk", "GateSupervisor"])
    a = get_appointment(tid, aid)
    if a["status"] not in ("BOOKED", "CHECKED_IN"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Appointment must be BOOKED or CHECKED_IN to cancel")
    if a["status"] == "CHECKED_IN":
        in_flight = any(
            t for t in db.transactions.values()
            if t["appointment_id"] == aid and t["status"] in ("PENDING", "COMPLETED")
        )
        if in_flight:
            raise ApiError(ERR_TRANSACTION_IN_FLIGHT, 409,
                           "A PENDING or COMPLETED transaction exists for this appointment")
    a["status"] = "CANCELLED"
    touch(a)
    # Release a RESERVED chassis held against this appointment
    if a["direction"] == "OUT":
        for ch in db.chassis.values():
            if ch.get("reserved_appointment_id") == aid and ch["status"] == "RESERVED":
                ch["reserved_appointment_id"] = None
                services.release_reserved_chassis(ch)
    return ok(a)


# ---------------------------------------------------------------------------
# GateTransaction
# ---------------------------------------------------------------------------

@bp.post("/terminals/<tid>/transactions")
def create_transaction(tid):
    auth(["GateClerk"])
    get_terminal(tid)
    data = body()
    appointment_id = req_str(data, "appointment_id")
    appt = db.appointments.get(appointment_id)
    if appt is None or appt["terminal_id"] != tid:
        raise ApiError(ERR_NOT_FOUND, 404, "GateAppointment not found")
    driver_id = req_str(data, "driver_id")
    gate_lane = req_str(data, "gate_lane")
    chassis_id = opt_str(data, "chassis_id")
    if appt["status"] != "CHECKED_IN":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Appointment must be CHECKED_IN to open a transaction")
    chassis_rec = None
    if chassis_id is not None:
        chassis_rec = db.chassis.get(chassis_id)
        if chassis_rec is None:
            raise ApiError(ERR_NOT_FOUND, 404, "Chassis not found")
        if appt["direction"] == "OUT":
            # The named chassis must be RESERVED against this appointment
            if chassis_rec["status"] != "RESERVED" or \
                    chassis_rec.get("reserved_appointment_id") != appointment_id:
                raise ApiError(ERR_INVALID_STATE, 409,
                               "Chassis is not RESERVED for this appointment")
    t = stamp_new({
        "terminal_id": tid,
        "appointment_id": appointment_id,
        "container_id": appt["container_id"],
        "chassis_id": chassis_id,
        "carrier_id": appt["carrier_id"],
        "direction": appt["direction"],
        "driver_id": driver_id,
        "gate_lane": gate_lane,
        "processed_at": None,
        "driver_turn_minutes": None,
        "status": "PENDING",
    })
    db.transactions[t["id"]] = t
    return ok(t, 201)


@bp.get("/terminals/<tid>/transactions/<txid>")
def get_transaction_route(tid, txid):
    auth(R_TX_GET)
    return ok(get_transaction(tid, txid))


@bp.get("/terminals/<tid>/transactions")
def list_transactions(tid):
    auth(R_TX_GET)
    get_terminal(tid)
    return list_view(
        (t for t in db.transactions.values() if t["terminal_id"] == tid),
        filters={"status": _q("status"), "direction": _q("direction"),
                 "carrier_id": _q("carrier_id"), "appointment_id": _q("appointment_id"),
                 "container_id": _q("container_id"), "chassis_id": _q("chassis_id")},
    )


def _complete_out(terminal, tx, appt, container, chassis_rec, pool):
    """OUT completion cascade (PRD §3.6)."""
    clock = now()
    tx["processed_at"] = now_clock_iso()
    # driver_turn_minutes = ceil((processed_at - checked_in_at)/60)
    checked_in = db._parse_iso(appt["checked_in_at"])
    delta = (clock - checked_in).total_seconds()
    tx["driver_turn_minutes"] = math.ceil(delta / 60) if delta > 0 else 0

    # Chassis RESERVED -> OUT
    chassis_rec["status"] = "OUT"
    chassis_rec["out_gate_transaction_id"] = tx["id"]
    chassis_rec["current_container_id"] = container["id"]
    chassis_rec["reserved_appointment_id"] = None
    touch(chassis_rec)
    pool["reserved_chassis_count"] -= 1
    pool["out_chassis_count"] += 1
    touch(pool)

    # Container ON_GROUND -> MOUNTED (release slot) -> OUTBOUND_TRUCK
    container["status"] = "MOUNTED"
    services.release_slot(container, terminal)
    container["status"] = "OUTBOUND_TRUCK"
    container["out_gate_transaction_id"] = tx["id"]
    touch(container)

    # Final per-diem/storage supersede provisional entries for this container
    expiry = db._parse_iso(container["free_time_expires_at"]) if container.get("free_time_expires_at") else None
    if expiry is not None and expiry < clock:
        # PRD §3.8: "the container is OUTBOUND_TRUCK by final-evaluation time,
        # so the final storage amount reflects the period up to the last
        # checkpoint at which the container was still ON_GROUND" — i.e. the
        # latest provisional STORAGE snapshot for the current billing period
        # (provisionals share period_start == free_time_expires_at). With no
        # such checkpoint the final storage charge is zero and no entry
        # replaces the (empty) provisional set.
        expiry_iso = container["free_time_expires_at"]
        st_final = 0
        for e in db.ledger.values():
            if (e.get("container_id") == container["id"]
                    and e["entry_kind"] == "STORAGE"
                    and e.get("period_start_utc") == expiry_iso):
                st_final = max(st_final, e["amount_cents"])
        services.waive_open_entries_for_container(container["id"], kinds=("PER_DIEM", "STORAGE"))
        pd_final = services.compute_per_diem(terminal, container, clock)
        if pd_final > 0:
            services.create_ledger_entry(
                terminal_id=terminal["id"], carrier_id=tx["carrier_id"],
                entry_kind="PER_DIEM", amount_cents=pd_final,
                container_id=container["id"], chassis_id=None,
                period_start=expiry, period_end=clock)
        if st_final > 0:
            services.create_ledger_entry(
                terminal_id=terminal["id"], carrier_id=tx["carrier_id"],
                entry_kind="STORAGE", amount_cents=st_final,
                container_id=container["id"], chassis_id=None,
                period_start=expiry, period_end=clock)

    # Flip fee
    services.settle_flip_fee(terminal, tx["carrier_id"],
                             chassis_rec["pool_id"], chassis_rec["id"], clock)


def _complete_in(terminal, tx, appt, container):
    """IN completion cascade (PRD §3.6): chassis returns, container re-grounds."""
    clock = now()
    tx["processed_at"] = now_clock_iso()
    # Chassis OUT -> AVAILABLE
    if tx.get("chassis_id"):
        ch = db.chassis.get(tx["chassis_id"])
        if ch is not None and ch["status"] == "OUT":
            pool = db.pools.get(ch["pool_id"])
            ch["status"] = "AVAILABLE"
            ch["out_gate_transaction_id"] = None
            ch["current_container_id"] = None
            touch(ch)
            if pool is not None:
                pool["out_chassis_count"] -= 1
                pool["available_chassis_count"] += 1
                touch(pool)
            # Safety wrinkle: OPEN SAFETY_CRITICAL damage forces UNROADABLE
            safety = any(
                d for d in db.damage.values()
                if d.get("chassis_id") == ch["id"]
                and d["status"] == "OPEN"
                and d["severity"] == "SAFETY_CRITICAL"
            )
            if safety:
                ch["roadability_status"] = "UNROADABLE"
                touch(ch)
    # Container re-grounds through the slot selector
    _ground_container(terminal, container)


@bp.post("/terminals/<tid>/transactions/<txid>/complete")
def complete_transaction(tid, txid):
    auth(["GateClerk"])
    terminal = get_terminal(tid)
    tx = get_transaction(tid, txid)
    # State (5)
    if tx["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Transaction is not PENDING")
    appt = db.appointments.get(tx["appointment_id"])
    if appt is None or appt["status"] != "CHECKED_IN":
        raise ApiError(ERR_INVALID_STATE, 409, "Appointment is not CHECKED_IN")
    container = db.containers.get(tx["container_id"])
    clock = now()

    if tx["direction"] == "OUT":
        chassis_rec = db.chassis.get(tx["chassis_id"]) if tx.get("chassis_id") else None
        if chassis_rec is None or chassis_rec["status"] != "RESERVED":
            raise ApiError(ERR_INVALID_STATE, 409, "Chassis is not RESERVED")
        # Roadability (6)
        if chassis_rec["roadability_status"] != "ROADABLE":
            raise ApiError(ERR_CHASSIS_UNROADABLE, 409, "Chassis is not ROADABLE")
        # Rail cutoff (7): only when planned train set and not yet DEPARTED
        train = db.trains.get(container.get("planned_train_id") or "") if container else None
        if train is not None and train["status"] != "DEPARTED":
            if clock >= db._parse_iso(train["rail_cutoff_at"]):
                raise ApiError(ERR_RAIL_CUTOFF_MISSED, 409,
                               "Completion at or after rail cutoff")
        pool = db.pools.get(chassis_rec["pool_id"])
        tx["status"] = "COMPLETED"
        _complete_out(terminal, tx, appt, container, chassis_rec, pool)
    else:
        # IN: terminal capacity (11)
        if terminal["posture"] == "CLOSED":
            raise ApiError(ERR_TERMINAL_CLOSED, 409, "Terminal posture is CLOSED")
        tx["status"] = "COMPLETED"
        _complete_in(terminal, tx, appt, container)

    touch(tx)
    # Appointment -> COMPLETED
    appt["status"] = "COMPLETED"
    appt["completed_at"] = tx["processed_at"]
    touch(appt)
    return ok(tx)


@bp.post("/terminals/<tid>/transactions/<txid>/reject")
def reject_transaction(tid, txid):
    auth(["GateClerk"])
    get_terminal(tid)
    tx = get_transaction(tid, txid)
    if tx["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Transaction is not PENDING")
    tx["status"] = "REJECTED"
    touch(tx)
    # Release a RESERVED chassis back to AVAILABLE; appointment stays CHECKED_IN
    if tx["direction"] == "OUT" and tx.get("chassis_id"):
        ch = db.chassis.get(tx["chassis_id"])
        if ch is not None and ch["status"] == "RESERVED":
            ch["reserved_appointment_id"] = None
            services.release_reserved_chassis(ch)
    return ok(tx)


# ---------------------------------------------------------------------------
# DamageInspection
# ---------------------------------------------------------------------------

@bp.post("/terminals/<tid>/damage")
def create_damage(tid):
    auth(["GateClerk", "MaintenancePlanner"])
    get_terminal(tid)
    data = body()
    txid = req_str(data, "gate_transaction_id")
    tx = db.transactions.get(txid)
    if tx is None or tx["terminal_id"] != tid:
        raise ApiError(ERR_NOT_FOUND, 404, "GateTransaction not found")
    chassis_id = opt_str(data, "chassis_id")
    container_id = opt_str(data, "container_id")
    if (chassis_id is None) == (container_id is None):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Exactly one of chassis_id / container_id must be set")
    damage_kind = req_enum(data, "damage_kind", DAMAGE_KINDS)
    severity = req_enum(data, "severity", SEVERITIES)
    repair_cost = req_int(data, "repair_cost_cents")
    if chassis_id is not None and chassis_id not in db.chassis:
        raise ApiError(ERR_NOT_FOUND, 404, "Chassis not found")
    if container_id is not None and container_id not in db.containers:
        raise ApiError(ERR_NOT_FOUND, 404, "Container not found")
    d = stamp_new({
        "terminal_id": tid,
        "gate_transaction_id": txid,
        "chassis_id": chassis_id,
        "container_id": container_id,
        "damage_kind": damage_kind,
        "severity": severity,
        "repair_cost_cents": repair_cost,
        "status": "OPEN",
    })
    db.damage[d["id"]] = d
    # MAJOR / SAFETY_CRITICAL on a chassis forces UNROADABLE; a RESERVED chassis
    # is released back to AVAILABLE (reservation voided).
    if chassis_id is not None and severity in ("MAJOR", "SAFETY_CRITICAL"):
        ch = db.chassis.get(chassis_id)
        if ch is not None and ch["status"] != "RETIRED":
            ch["roadability_status"] = "UNROADABLE"
            touch(ch)
            if ch["status"] == "RESERVED":
                ch["reserved_appointment_id"] = None
                services.release_reserved_chassis(ch)
    return ok(d, 201)


@bp.get("/terminals/<tid>/damage/<did>")
def get_damage_route(tid, did):
    auth(R_DAMAGE_GET)
    return ok(get_damage(tid, did))


@bp.get("/terminals/<tid>/damage")
def list_damage(tid):
    auth(R_DAMAGE_GET)
    get_terminal(tid)
    return list_view(
        (d for d in db.damage.values() if d["terminal_id"] == tid),
        filters={"status": _q("status"), "chassis_id": _q("chassis_id"),
                 "container_id": _q("container_id"),
                 "gate_transaction_id": _q("gate_transaction_id")},
    )


@bp.post("/terminals/<tid>/damage/<did>/schedule_repair")
def schedule_repair(tid, did):
    auth(["MaintenancePlanner"])
    d = get_damage(tid, did)
    if d["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Damage is not OPEN")
    d["status"] = "REPAIR_SCHEDULED"
    touch(d)
    return ok(d)


@bp.post("/terminals/<tid>/damage/<did>/mark_repaired")
def mark_repaired(tid, did):
    auth(["MaintenancePlanner"])
    d = get_damage(tid, did)
    if d["status"] != "REPAIR_SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Damage is not REPAIR_SCHEDULED")
    d["status"] = "REPAIRED"
    touch(d)
    # Bill the carrier of the linked gate transaction
    tx = db.transactions.get(d["gate_transaction_id"])
    if tx is not None:
        services.create_ledger_entry(
            terminal_id=tid, carrier_id=tx["carrier_id"],
            entry_kind="DAMAGE_REPAIR", amount_cents=d["repair_cost_cents"],
            container_id=d.get("container_id"), chassis_id=d.get("chassis_id"),
            period_start=now(), period_end=now())
    # Roadability recomputation
    if d.get("chassis_id"):
        ch = db.chassis.get(d["chassis_id"])
        if ch is not None:
            services.recompute_roadability(ch)
    return ok(d)


@bp.post("/terminals/<tid>/damage/<did>/waive")
def waive_damage(tid, did):
    auth(["TerminalManager"])
    d = get_damage(tid, did)
    if d["status"] not in ("OPEN", "REPAIR_SCHEDULED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Damage must be OPEN or REPAIR_SCHEDULED to waive")
    d["status"] = "WAIVED"
    touch(d)
    if d.get("chassis_id"):
        ch = db.chassis.get(d["chassis_id"])
        if ch is not None:
            services.recompute_roadability(ch)
    return ok(d)


# ---------------------------------------------------------------------------
# BillingLedgerEntry
# ---------------------------------------------------------------------------

@bp.get("/terminals/<tid>/ledger/<lid>")
def get_ledger_route(tid, lid):
    auth(R_LEDGER_GET)
    return ok(get_ledger(tid, lid))


@bp.get("/terminals/<tid>/ledger")
def list_ledger(tid):
    auth(R_LEDGER_GET)
    get_terminal(tid)
    return list_view(
        (e for e in db.ledger.values() if e["terminal_id"] == tid),
        filters={"status": _q("status"), "entry_kind": _q("entry_kind"),
                 "carrier_id": _q("carrier_id"), "container_id": _q("container_id"),
                 "chassis_id": _q("chassis_id")},
    )


@bp.post("/terminals/<tid>/ledger/<lid>/apply")
def apply_ledger(tid, lid):
    auth(["BillingClerk"])
    get_terminal(tid)
    entry = get_ledger(tid, lid)
    data = body()
    apply_cents = req_int(data, "apply_cents", positive=True)
    carrier = db.carriers.get(entry["carrier_id"]) if entry.get("carrier_id") else None
    # OCC (4) — expected_carrier_version required
    if "expected_carrier_version" not in data or data.get("expected_carrier_version") is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_carrier_version is required")
    if carrier is None or data["expected_carrier_version"] != carrier["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Carrier version mismatch")
    # State (5)
    if entry["status"] not in ("OPEN", "PARTIALLY_APPLIED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Entry must be OPEN or PARTIALLY_APPLIED")
    # Overpay (14)
    remaining = entry["amount_cents"] - entry["applied_cents"]
    if apply_cents > remaining:
        raise ApiError(ERR_OVERPAY, 409, "apply_cents exceeds remaining balance")
    entry["applied_cents"] += apply_cents
    entry["status"] = "APPLIED" if apply_cents == remaining else "PARTIALLY_APPLIED"
    touch(entry)
    carrier["outstanding_billing_cents"] -= apply_cents
    touch(carrier)
    return ok(entry)


@bp.post("/terminals/<tid>/ledger/<lid>/waive")
def waive_ledger(tid, lid):
    auth(["TerminalManager"])
    get_terminal(tid)
    entry = get_ledger(tid, lid)
    if entry["status"] not in ("OPEN", "PARTIALLY_APPLIED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Entry must be OPEN or PARTIALLY_APPLIED")
    services.waive_entry(entry)
    return ok(entry)


# ---------------------------------------------------------------------------
# run_ops checkpoint
# ---------------------------------------------------------------------------

@bp.post("/terminals/<tid>/run_ops")
def run_ops_route(tid):
    auth(["TerminalManager"])
    terminal = get_terminal(tid)
    services.run_ops(terminal)
    return ok(terminal)


# ---------------------------------------------------------------------------
# Flat single-resource GETs (FK reverse-reachability)
# ---------------------------------------------------------------------------

@bp.get("/pools/<id>")
def flat_get_pool(id):
    auth(R_POOL_GET_FLAT)
    p = db.pools.get(id)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, "ChassisPool not found")
    return ok(p)


@bp.get("/pools")
def flat_list_pools():
    auth(R_POOL_GET_FLAT)
    return list_view(db.pools.values(), filters={"terminal_id": _q("terminal_id")})


@bp.get("/chassis/<id>")
def flat_get_chassis(id):
    auth(R_POOL_GET_FLAT)
    c = db.chassis.get(id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Chassis not found")
    return ok(c)


@bp.get("/chassis")
def flat_list_chassis():
    auth(R_POOL_GET_FLAT)
    return list_view(db.chassis.values(), filters={
        "pool_id": _q("pool_id"),
        "out_gate_transaction_id": _q("out_gate_transaction_id"),
        "current_container_id": _q("current_container_id"),
        "status": _q("status"),
        "roadability_status": _q("roadability_status"),
    })


@bp.get("/memberships/<id>")
def flat_get_membership(id):
    auth(R_MEMBERSHIP_GET)
    m = db.memberships.get(id)
    if m is None:
        raise ApiError(ERR_NOT_FOUND, 404, "ChassisMembership not found")
    return ok(m)


@bp.get("/memberships")
def flat_list_memberships():
    auth(R_MEMBERSHIP_GET)
    return list_view(db.memberships.values(), filters={
        "pool_id": _q("pool_id"), "carrier_id": _q("carrier_id"),
        "membership_status": _q("membership_status"),
    })


@bp.get("/trains/<id>")
def flat_get_train(id):
    auth(R_TRAIN_GET)
    t = db.trains.get(id)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Train not found")
    return ok(t)


@bp.get("/trains")
def flat_list_trains():
    auth(R_TRAIN_GET)
    return list_view(db.trains.values(), filters={
        "terminal_id": _q("terminal_id"), "status": _q("status"),
    })


@bp.get("/slots/<id>")
def flat_get_slot(id):
    auth(R_SLOT_GET)
    s = db.slots.get(id)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, 404, "YardSlot not found")
    return ok(s)


@bp.get("/slots")
def flat_list_slots():
    auth(R_SLOT_GET)
    return list_view(db.slots.values(), filters={
        "terminal_id": _q("terminal_id"),
        "occupied_container_id": _q("occupied_container_id"),
        "status": _q("status"), "row": _q("row"),
    })


@bp.get("/containers/<id>")
def flat_get_container(id):
    auth(R_CONTAINER_GET)
    c = db.containers.get(id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Container not found")
    return ok(c)


@bp.get("/containers")
def flat_list_containers():
    auth(R_CONTAINER_GET)
    return list_view(db.containers.values(), filters={
        "terminal_id": _q("terminal_id"), "yard_slot_id": _q("yard_slot_id"),
        "planned_train_id": _q("planned_train_id"),
        "out_gate_transaction_id": _q("out_gate_transaction_id"),
        "status": _q("status"),
    })


@bp.get("/appointments/<id>")
def flat_get_appointment(id):
    auth(R_APPT_GET)
    a = db.appointments.get(id)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, 404, "GateAppointment not found")
    return ok(a)


@bp.get("/appointments")
def flat_list_appointments():
    auth(R_APPT_GET)
    return list_view(db.appointments.values(), filters={
        "terminal_id": _q("terminal_id"), "carrier_id": _q("carrier_id"),
        "container_id": _q("container_id"), "status": _q("status"),
        "direction": _q("direction"),
    })


@bp.get("/transactions/<id>")
def flat_get_transaction(id):
    auth(R_TX_GET)
    t = db.transactions.get(id)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, 404, "GateTransaction not found")
    return ok(t)


@bp.get("/transactions")
def flat_list_transactions():
    auth(R_TX_GET)
    return list_view(db.transactions.values(), filters={
        "terminal_id": _q("terminal_id"), "appointment_id": _q("appointment_id"),
        "container_id": _q("container_id"), "chassis_id": _q("chassis_id"),
        "carrier_id": _q("carrier_id"), "status": _q("status"),
        "direction": _q("direction"),
    })


@bp.get("/damage/<id>")
def flat_get_damage(id):
    auth(R_DAMAGE_GET)
    d = db.damage.get(id)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, 404, "DamageInspection not found")
    return ok(d)


@bp.get("/damage")
def flat_list_damage():
    auth(R_DAMAGE_GET)
    return list_view(db.damage.values(), filters={
        "terminal_id": _q("terminal_id"),
        "gate_transaction_id": _q("gate_transaction_id"),
        "chassis_id": _q("chassis_id"), "container_id": _q("container_id"),
        "status": _q("status"),
    })


@bp.get("/ledger/<id>")
def flat_get_ledger(id):
    auth(R_LEDGER_GET)
    e = db.ledger.get(id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "BillingLedgerEntry not found")
    return ok(e)


@bp.get("/ledger")
def flat_list_ledger():
    auth(R_LEDGER_GET)
    return list_view(db.ledger.values(), filters={
        "terminal_id": _q("terminal_id"), "container_id": _q("container_id"),
        "chassis_id": _q("chassis_id"), "carrier_id": _q("carrier_id"),
        "status": _q("status"), "entry_kind": _q("entry_kind"),
    })


def register(app):
    app.register_blueprint(bp)
