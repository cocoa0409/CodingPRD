"""ParkingProgram endpoints, posture transitions, run-ops checkpoint, cost report."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
from db import fmt_dt, now, parse_date, parse_dt, touch
from domain import (
    NON_TERMINAL_PERMIT_STATUSES, get_or_404, serialize_program,
    promotion_pass, promotion_pass_program, suspend_permit, reinstate_permit,
    revoke_permit, lot_bookable, lot_available, cycle_total, round_half_up,
    post_permit_fee, open_cycle_for_program,
)
from errors import raise_error
from middleware import require_roles
from response import success_object

bp = Blueprint("programs", __name__)

ALL_ROLES = ("ParkingAdmin", "Employee", "PayrollAdmin",
             "EnforcementOfficer", "AppealsOfficer", "ShuttleDispatcher")


# ---------------------------------------------------------------------------
# Clock (test-driving)
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("ParkingAdmin")
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    dt = parse_dt(to_iso)
    if dt is None:
        raise_error("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 datetime")
    db.set_now(dt)
    return success_object({"current_utc": fmt_dt(db.now())}, 200)


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------

@bp.route("/parking/programs", methods=["POST"])
def create_program():
    require_roles("ParkingAdmin")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    name = body.get("name")
    if not name or not isinstance(name, str):
        raise_error("ERR_INVALID_REQUEST", "name is required")
    proration_mode = body.get("proration_mode", "CALENDAR_DAY")
    if proration_mode not in ("CALENDAR_DAY", "HALF_MONTH"):
        raise_error("ERR_INVALID_REQUEST", "invalid proration_mode")
    pool = body.get("monthly_subsidy_pool_cents", 0)
    if not isinstance(pool, int) or isinstance(pool, bool) or pool < 0:
        raise_error("ERR_INVALID_REQUEST", "monthly_subsidy_pool_cents must be >= 0")
    ttl = body.get("waitlist_offer_ttl_hours", 72)
    if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= 0:
        raise_error("ERR_INVALID_REQUEST", "waitlist_offer_ttl_hours must be > 0")
    threshold = body.get("violation_suspension_threshold", 3)
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1:
        raise_error("ERR_INVALID_REQUEST", "violation_suspension_threshold must be >= 1")
    tow_hold = body.get("tow_hold_hours", 48)
    if not isinstance(tow_hold, int) or isinstance(tow_hold, bool) or tow_hold < 0:
        raise_error("ERR_INVALID_REQUEST", "tow_hold_hours must be >= 0")
    rec = db.new_record({
        "name": name,
        "posture": "PROGRAM_NORMAL",
        "proration_mode": proration_mode,
        "monthly_subsidy_pool_cents": pool,
        "waitlist_offer_ttl_hours": ttl,
        "violation_suspension_threshold": threshold,
        "tow_hold_hours": tow_hold,
        "ops_run_index": 0,
    })
    db.programs[rec["id"]] = rec
    return success_object(serialize_program(rec), 201)


@bp.route("/parking/programs/<pid>", methods=["GET"])
def get_program(pid):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.programs, pid)
    return success_object(serialize_program(rec), 200)


@bp.route("/parking/programs/<pid>/posture", methods=["POST"])
def program_posture(pid):
    require_roles("ParkingAdmin")
    program = get_or_404(db.programs, pid)
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    target = body.get("posture")
    if target not in ("PROGRAM_FROZEN", "PROGRAM_NORMAL", "PROGRAM_CLOSED"):
        raise_error("ERR_INVALID_REQUEST", "invalid posture")
    cur = program["posture"]
    allowed = {
        ("PROGRAM_NORMAL", "PROGRAM_FROZEN"),
        ("PROGRAM_FROZEN", "PROGRAM_NORMAL"),
        ("PROGRAM_NORMAL", "PROGRAM_CLOSED"),
        ("PROGRAM_FROZEN", "PROGRAM_CLOSED"),
    }
    if (cur, target) not in allowed:
        raise_error("ERR_INVALID_STATE", f"Posture transition {cur} -> {target} not allowed")
    if target == "PROGRAM_CLOSED":
        # Preconditions: no non-terminal permits, no OPEN billing cycles
        program_lot_ids = {l["id"] for l in db.lots.values() if l["program_id"] == pid}
        for p in db.permits.values():
            if p["lot_id"] in program_lot_ids and p["status"] in NON_TERMINAL_PERMIT_STATUSES:
                raise_error("ERR_INVALID_STATE", "Program has non-terminal permits")
        for c in db.billing_cycles.values():
            if c["program_id"] == pid and c["status"] == "OPEN":
                raise_error("ERR_INVALID_STATE", "Program has an OPEN billing cycle")
    program["posture"] = target
    touch(program)
    if cur == "PROGRAM_FROZEN" and target == "PROGRAM_NORMAL":
        promotion_pass_program(program)
    return success_object(serialize_program(program), 200)


# ---------------------------------------------------------------------------
# Run-ops checkpoint
# ---------------------------------------------------------------------------

@bp.route("/parking/programs/<pid>/run-ops", methods=["POST"])
def run_ops(pid):
    require_roles("ParkingAdmin")
    program = get_or_404(db.programs, pid)
    current = now()

    program_lots = {l["id"]: l for l in db.lots.values() if l["program_id"] == pid}

    # (1) PeakWindow activation/ending
    windows = [w for w in db.peak_windows.values() if w["lot_id"] in program_lots]
    windows.sort(key=lambda w: w["created_at"])
    for w in windows:
        starts = parse_dt(w["starts_at"])
        ends = parse_dt(w["ends_at"])
        if w["status"] == "SCHEDULED" and starts <= current < ends:
            w["status"] = "ACTIVE"
            touch(w)
            lot = program_lots[w["lot_id"]]
            if lot["status"] == "STANDBY":
                lot["status"] = "ACTIVATED"
                touch(lot)
                promotion_pass(lot["id"])
        elif w["status"] == "ACTIVE" and current >= ends:
            w["status"] = "ENDED"
            touch(w)
            lot = program_lots[w["lot_id"]]
            if lot["status"] == "ACTIVATED":
                lot["status"] = "STANDBY"
                touch(lot)

    # (2) PUBLISHED notices reaching effective_from -> EFFECTIVE with cascades
    notices = [n for n in db.notices.values()
               if n["status"] == "PUBLISHED" and parse_dt(n["effective_from"]) <= current]
    # Scope to this program: notices carry lot_id or route_id
    scoped = []
    for n in notices:
        if n.get("lot_id") and n["lot_id"] in program_lots:
            scoped.append(n)
        elif n.get("route_id"):
            route = db.routes.get(n["route_id"])
            if route and route["lot_id"] in program_lots:
                scoped.append(n)
        elif not n.get("lot_id") and not n.get("route_id"):
            # GENERAL notice without targets: cannot attribute; skip
            continue
    scoped.sort(key=lambda n: n["created_at"])
    for n in scoped:
        _apply_notice_effectiveness(n, program, program_lots, current)

    # (3) OFFERED permits with offer_expires_at < now -> EXPIRED
    for p in sorted(db.permits.values(), key=lambda x: x["created_at"]):
        if p["lot_id"] in program_lots and p["status"] == "OFFERED":
            exp = parse_dt(p["offer_expires_at"])
            if exp is not None and exp < current:
                p["status"] = "EXPIRED"
                touch(p)

    # (4) Termination sweep
    for p in sorted(db.permits.values(), key=lambda x: x["created_at"]):
        if p["lot_id"] in program_lots and p["status"] in NON_TERMINAL_PERMIT_STATUSES:
            emp = db.employees.get(p["employee_id"])
            if emp and emp["employment_status"] == "TERMINATED":
                revoke_permit(p, run_promotion=False)

    # (5) Waitlist promotion pass per lot (created_at ASC)
    for lot in sorted(program_lots.values(), key=lambda l: l["created_at"]):
        if lot_bookable(lot):
            promotion_pass(lot["id"])

    # (6) PENDING renewals whose permit term_end < now -> EXPIRED
    for r in sorted(db.renewals.values(), key=lambda x: x["created_at"]):
        if r["status"] == "PENDING":
            permit = db.permits.get(r["permit_id"])
            if permit and permit["lot_id"] in program_lots and permit.get("term_end"):
                term = parse_date(permit["term_end"])
                if term is not None and term < current.date():
                    r["status"] = "EXPIRED"
                    touch(r)

    # (7) ops_run_index += 1 and version bump
    program["ops_run_index"] += 1
    touch(program)
    return success_object(serialize_program(program), 200)


def _apply_notice_effectiveness(n, program, program_lots, current):
    """Fire a notice cascade and mark it EFFECTIVE."""
    ntype = n["notice_type"]
    if ntype == "LOT_CLOSURE":
        lot = program_lots.get(n.get("lot_id"))
        if lot is not None and lot["status"] in ("ACTIVE", "ACTIVATED"):
            lot["status"] = "CLOSED"
            touch(lot)
            # Suspend every ACTIVE permit on this lot (LOT_CLOSURE cascade)
            for p in sorted(db.permits.values(), key=lambda x: x["created_at"]):
                if p["lot_id"] == lot["id"] and p["status"] == "ACTIVE":
                    suspend_permit(p, "LOT_CLOSURE")
        elif lot is not None and lot["status"] == "STANDBY":
            lot["status"] = "CLOSED"
            touch(lot)
    elif ntype == "LOT_REOPEN":
        lot = program_lots.get(n.get("lot_id"))
        if lot is not None and lot["status"] == "CLOSED":
            lot["status"] = "ACTIVE" if lot["tier"] == "CORE" else "STANDBY"
            touch(lot)
            # Auto-reinstate permits suspended with reason LOT_CLOSURE
            for p in sorted(db.permits.values(), key=lambda x: x["created_at"]):
                if (p["lot_id"] == lot["id"] and p["status"] == "SUSPENDED"
                        and p.get("suspension_reason") == "LOT_CLOSURE"):
                    reinstate_permit(p)
            promotion_pass(lot["id"])
    elif ntype == "ROUTE_SUSPENSION":
        route = db.routes.get(n.get("route_id"))
        if route is not None and route["status"] == "ACTIVE":
            route["status"] = "SUSPENDED"
            touch(route)
    elif ntype == "HEADWAY_CHANGE":
        route = db.routes.get(n.get("route_id"))
        if route is not None and n.get("new_headway_minutes"):
            route["headway_target_minutes"] = n["new_headway_minutes"]
            touch(route)
    # GENERAL: no structural effect
    n["status"] = "EFFECTIVE"
    touch(n)


# ---------------------------------------------------------------------------
# Cost report
# ---------------------------------------------------------------------------

@bp.route("/parking/programs/<pid>/cost-report", methods=["GET"])
def cost_report(pid):
    require_roles("ParkingAdmin", "PayrollAdmin")
    program = get_or_404(db.programs, pid)
    program_lot_ids = {l["id"] for l in db.lots.values() if l["program_id"] == pid}

    total_cost = 0
    for r in db.routes.values():
        if r["lot_id"] in program_lot_ids:
            completed = sum(1 for t in db.trips.values()
                            if t["route_id"] == r["id"] and t["status"] == "COMPLETED")
            total_cost += completed * r["operating_cost_per_trip_cents"]
    for l in db.lots.values():
        if l["program_id"] == pid:
            total_cost += l["monthly_maintenance_cents"]

    program_permit_ids = {p["id"] for p in db.permits.values() if p["lot_id"] in program_lot_ids}
    subsidy_spent = 0
    for e in db.charge_entries.values():
        if (e.get("permit_id") in program_permit_ids and e["charge_type"] == "PERMIT_FEE"
                and e["status"] != "REVERSED"):
            subsidy_spent += e["subsidy_cents"]

    active_count = sum(1 for p in db.permits.values()
                       if p["lot_id"] in program_lot_ids and p["status"] == "ACTIVE")
    denom = max(1, active_count)
    gross = round_half_up(Decimal(total_cost) / Decimal(denom))
    net = round_half_up(Decimal(total_cost - subsidy_spent) / Decimal(denom))
    return success_object({
        "total_cost_cents": total_cost,
        "subsidy_spent_cents": subsidy_spent,
        "active_permit_count": active_count,
        "gross_cost_per_employee_cents": gross,
        "net_cost_per_employee_cents": net,
    }, 200)
