"""ServiceVisit endpoints (PRD §3.4, §3.5, §3.6, §3.7) plus chemical readings."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success, success_list
from services import calculations
from services.common import (
    new_record,
    paginate,
    require_bool,
    require_enum,
    require_int,
    require_json_object,
    require_number,
    require_str,
    serialize,
    sort_by_created,
    touch,
)
from services.derived import recompute_visits_remaining
from services.lookup import (
    get_plan_or_404,
    get_pool_or_404,
    get_route_or_404,
    get_visit_or_404,
)

bp = Blueprint("visits", __name__)

SKIP_REASONS = {"WEATHER", "HOLIDAY", "CUSTOMER_REQUEST"}
# Non-terminal visit statuses (occupy a route slot / count toward capacity).
_NON_TERMINAL = {"SCHEDULED", "RECOVERY_SCHEDULED"}


def serialize_visit(visit):
    out = serialize(visit)
    out["billed_amount_cents"] = visit["billed_amount_cents"]
    return out


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open overlap: [a_start,a_end) vs [b_start,b_end). Adjacency allowed."""
    return a_start < b_end and b_start < a_end


def _next_makeup_slot(route):
    """Find the next available capacity slot on a route for a WEATHER makeup.

    Returns (start, end). Packs makeup visits inside the route window without
    overlapping any existing non-terminal slot, using unit-minute placement.
    """
    win_start = route["window_start_minute"]
    win_end = route["window_end_minute"]
    occupied = sorted(
        (v["slot_start_minute"], v["slot_end_minute"])
        for v in db.visits.values()
        if v["route_id"] == route["id"] and v["status"] in _NON_TERMINAL
    )
    # Walk the window and find the first free single-minute slot of length 1.
    cursor = win_start
    for (s, e) in occupied:
        if cursor < s:
            return cursor, cursor + 1
        cursor = max(cursor, e)
    if cursor < win_end:
        return cursor, cursor + 1
    # No room left; return None to signal capacity exhaustion.
    return None


@bp.post("/visits")
@require_roles("RouteManager")
def create_visit():
    with db.lock:
        body = require_json_object(request.get_json(silent=True))
        pool_id = require_str(body, "pool_id")
        plan_id = require_str(body, "plan_id")
        route_id = require_str(body, "route_id")
        slot_start = require_int(body, "slot_start_minute", minimum=0, maximum=1439)
        slot_end = require_int(body, "slot_end_minute", minimum=1, maximum=1440)
        # Existence (priority 3).
        get_pool_or_404(pool_id)
        get_plan_or_404(plan_id)
        route = get_route_or_404(route_id)
        # Interval validity (priority 7).
        if slot_end <= slot_start:
            raise err("ERR_INVALID_INTERVAL", "slot_end_minute must exceed slot_start_minute")
        # Slot must lie within the route window and not overlap a sibling (priority 8).
        if slot_start < route["window_start_minute"] or slot_end > route["window_end_minute"]:
            raise err("ERR_SLOT_OVERLAP", "Visit slot falls outside the route window")
        for v in db.visits.values():
            if v["route_id"] == route_id and v["status"] in _NON_TERMINAL:
                if _overlaps(slot_start, slot_end, v["slot_start_minute"], v["slot_end_minute"]):
                    raise err("ERR_SLOT_OVERLAP", "Visit slot overlaps an existing visit")
        # Capacity (priority 12): count of non-terminal visits == capacity_visits.
        non_terminal_count = sum(
            1
            for v in db.visits.values()
            if v["route_id"] == route_id and v["status"] in _NON_TERMINAL
        )
        if non_terminal_count >= route["capacity_visits"]:
            raise err("ERR_ROUTE_AT_CAPACITY", "Route is at capacity")
        rec = new_record(
            {
                "pool_id": pool_id,
                "plan_id": plan_id,
                "route_id": route_id,
                "slot_start_minute": slot_start,
                "slot_end_minute": slot_end,
                "status": "SCHEDULED",
                "skip_reason": "NONE",
                "billed_amount_cents": 0,
                "makeup_visit_id": None,
            }
        )
        db.visits[rec["id"]] = rec
        return success(serialize_visit(rec), 201)


@bp.get("/visits/<visit_id>")
@require_roles("AccountManager", "RouteManager", "FieldTechnician", "Customer")
def get_visit(visit_id):
    with db.lock:
        visit = get_visit_or_404(visit_id)
        return success(serialize_visit(visit), 200)


@bp.get("/visits")
@require_roles("AccountManager", "RouteManager", "FieldTechnician")
def list_visits():
    with db.lock:
        limit, offset = paginate(request.args)
        items = list(db.visits.values())
        for key in ("pool_id", "plan_id", "route_id", "makeup_visit_id"):
            val = request.args.get(key)
            if val is not None:
                items = [v for v in items if v.get(key) == val]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize_visit(v) for v in page], limit, offset, total)


@bp.post("/visits/<visit_id>/complete")
@require_roles("FieldTechnician")
def complete_visit(visit_id):
    with db.lock:
        visit = get_visit_or_404(visit_id)
        body = require_json_object(request.get_json(silent=True))
        green_pool = require_bool(body, "green_pool")
        pool = db.pools.get(visit["pool_id"])
        plan = db.service_plans.get(visit["plan_id"])
        route = db.routes.get(visit["route_id"])
        # State validity (priority 5): visit must be SCHEDULED or RECOVERY_SCHEDULED,
        # pool OPEN/GREEN_RECOVERY (per the relevant branch), route DISPATCHED.
        status = visit["status"]
        if status == "SCHEDULED":
            if (
                pool is None
                or pool["service_status"] not in ("OPEN", "GREEN_RECOVERY")
                or route is None
                or route["status"] != "DISPATCHED"
            ):
                raise err("ERR_INVALID_STATE", "Visit cannot be completed from its current state")
            was_recovery = False
        elif status == "RECOVERY_SCHEDULED":
            if (
                pool is None
                or pool["service_status"] != "GREEN_RECOVERY"
                or route is None
                or route["status"] != "DISPATCHED"
            ):
                raise err("ERR_INVALID_STATE", "Recovery visit cannot be completed from its current state")
            was_recovery = True
        else:
            raise err("ERR_INVALID_STATE", "Visit cannot be completed from its current state")

        green_initial = (status == "SCHEDULED") and green_pool

        # visits_remaining BEFORE this completion drives prepaid coverage.
        visits_remaining_before = plan["visits_remaining"]

        billed = calculations.final_visit_bill(
            plan=plan,
            was_recovery=was_recovery,
            green_pool_initial=green_initial,
            volume_gallons=pool["volume_gallons"],
            visits_remaining_before=visits_remaining_before,
        )

        visit["status"] = "COMPLETED"
        visit["billed_amount_cents"] = billed
        touch(visit)

        # Recompute funding plan's visits_remaining (a mutation of the plan).
        recompute_visits_remaining(plan)

        # Green-pool cascade.
        if green_initial:
            # OPEN -> GREEN_RECOVERY; auto-create RECOVERY_SCHEDULED follow-up.
            pool["service_status"] = "GREEN_RECOVERY"
            touch(pool)
            follow = new_record(
                {
                    "pool_id": pool["id"],
                    "plan_id": plan["id"],
                    "route_id": route["id"],
                    "slot_start_minute": visit["slot_start_minute"],
                    "slot_end_minute": visit["slot_end_minute"],
                    "status": "RECOVERY_SCHEDULED",
                    "skip_reason": "NONE",
                    "billed_amount_cents": 0,
                    "makeup_visit_id": None,
                }
            )
            db.visits[follow["id"]] = follow
        elif was_recovery and not green_pool:
            # GREEN_RECOVERY -> OPEN when recovery follow-up completes clean.
            pool["service_status"] = "OPEN"
            touch(pool)

        # Plan bubble-up: ACTIVE plan whose visits_remaining hit 0 completes.
        if plan["status"] == "ACTIVE" and plan["visits_remaining"] == 0:
            plan["status"] = "COMPLETED"
            touch(plan)

        return success(serialize_visit(visit), 200)


@bp.post("/visits/<visit_id>/skip")
@require_roles("RouteManager")
def skip_visit(visit_id):
    with db.lock:
        visit = get_visit_or_404(visit_id)
        body = require_json_object(request.get_json(silent=True))
        # State validity (priority 5) before skip_reason check (priority 13).
        if visit["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Visit cannot be skipped from its current state")
        skip_reason = body.get("skip_reason")
        if skip_reason is None or skip_reason == "NONE":
            raise err("ERR_SKIP_REASON_REQUIRED", "A skip_reason other than NONE is required")
        if skip_reason not in SKIP_REASONS:
            raise err("ERR_INVALID_REQUEST", "Invalid skip_reason")

        visit["status"] = "SKIPPED"
        visit["skip_reason"] = skip_reason

        if skip_reason == "WEATHER":
            route = db.routes.get(visit["route_id"])
            slot = _next_makeup_slot(route)
            if slot is not None:
                m_start, m_end = slot
                makeup = new_record(
                    {
                        "pool_id": visit["pool_id"],
                        "plan_id": visit["plan_id"],
                        "route_id": visit["route_id"],
                        "slot_start_minute": m_start,
                        "slot_end_minute": m_end,
                        "status": "SCHEDULED",
                        "skip_reason": "NONE",
                        "billed_amount_cents": 0,
                        "makeup_visit_id": None,
                    }
                )
                db.visits[makeup["id"]] = makeup
                visit["makeup_visit_id"] = makeup["id"]
        touch(visit)
        return success(serialize_visit(visit), 200)


@bp.post("/visits/<visit_id>/cancel")
@require_roles("RouteManager")
def cancel_visit(visit_id):
    with db.lock:
        visit = get_visit_or_404(visit_id)
        if visit["status"] not in ("SCHEDULED", "RECOVERY_SCHEDULED"):
            raise err("ERR_INVALID_STATE", "Visit cannot be cancelled from its current state")
        was_recovery = visit["status"] == "RECOVERY_SCHEDULED"
        visit["status"] = "CANCELLED"
        touch(visit)
        # Recovery cancel: if no other RECOVERY_SCHEDULED remains on the pool,
        # revert pool GREEN_RECOVERY -> OPEN (cascade).
        if was_recovery:
            pool = db.pools.get(visit["pool_id"])
            remaining = any(
                v["pool_id"] == visit["pool_id"]
                and v["status"] == "RECOVERY_SCHEDULED"
                and v["id"] != visit["id"]
                for v in db.visits.values()
            )
            if pool is not None and pool["service_status"] == "GREEN_RECOVERY" and not remaining:
                pool["service_status"] = "OPEN"
                touch(pool)
        return success(serialize_visit(visit), 200)


@bp.post("/visits/<visit_id>/readings")
@require_roles("FieldTechnician")
def create_reading(visit_id):
    with db.lock:
        visit = get_visit_or_404(visit_id)
        body = require_json_object(request.get_json(silent=True))
        free_chlorine_ppm = require_number(body, "free_chlorine_ppm", minimum=0)
        ph = require_number(body, "ph", minimum=0, maximum=14)
        total_alkalinity_ppm = require_number(body, "total_alkalinity_ppm", minimum=0)
        pool = db.pools.get(visit["pool_id"])
        dose = calculations.dosing_recommendation(
            water_type=pool["water_type"],
            volume_gallons=pool["volume_gallons"],
            free_chlorine_ppm=free_chlorine_ppm,
            ph=ph,
            total_alkalinity_ppm=total_alkalinity_ppm,
        )
        # ChemicalReading is append-only: only id + created_at, no version/updated_at.
        rec = new_record(
            {
                "visit_id": visit_id,
                "free_chlorine_ppm": free_chlorine_ppm,
                "ph": ph,
                "total_alkalinity_ppm": total_alkalinity_ppm,
                "recommended_dose_grams": dose,
            },
            common=False,
        )
        db.readings[rec["id"]] = rec
        return success(serialize(rec), 201)


@bp.get("/visits/<visit_id>/readings")
@require_roles("AccountManager", "RouteManager", "FieldTechnician", "Customer")
def list_readings(visit_id):
    with db.lock:
        get_visit_or_404(visit_id)
        limit, offset = paginate(request.args)
        items = [r for r in db.readings.values() if r["visit_id"] == visit_id]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize(r) for r in page], limit, offset, total)
