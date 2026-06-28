"""Air-Duct & Dryer-Vent Cleaning API — Flask entry point.

In-memory store, no seeding. Boots clean from a fresh process every time.
"""
import os
from datetime import timedelta

from flask import Flask, request

from clock import clock, format_iso8601, parse_iso8601
import common
from common import (
    add_months,
    as_bool,
    as_int,
    as_number,
    as_str,
    get_json_body,
    get_pagination,
    paginate,
    require_fields,
)
from constants import (
    ADDON_CODES,
    CADENCE_MONTHS,
    MIN_AFTER_PHOTOS,
    REFERRAL_RISK_THRESHOLD,
    REFERRAL_TTL_DAYS,
    SERVICE_TYPES,
)
from db import db, now_iso, new_id
from errors import ApiError, err
import lookups
from middleware import get_user_context, require_roles
import response
from serializers import public, public_list
import services

app = Flask(__name__)
app.url_map.strict_slashes = False


# ==========================================================================
# Global error handling
# ==========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return response.error(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return response.error("ERR_INVALID_REQUEST", 400, "Unknown route.")


@app.errorhandler(405)
def handle_405(e):
    return response.error("ERR_INVALID_REQUEST", 400, "Method not allowed.")


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return response.error(e.error_id, e.http_status, e.message)
    return response.error("ERR_INVALID_REQUEST", 400, "Bad request.")


def auth(allowed_roles):
    """Validate user context (401) then role (403). Returns (user_id, role)."""
    user_id, role = get_user_context()
    require_roles(role, allowed_roles)
    return user_id, role


# ==========================================================================
# Service-line / addon body validation (PRD §3.3)
# ==========================================================================
def validate_and_normalize_service_lines(home_id, raw):
    if not isinstance(raw, list) or len(raw) == 0:
        raise err("ERR_INVALID_REQUEST", "service_lines must be a non-empty array.")
    normalized = []
    for sl in raw:
        if not isinstance(sl, dict):
            raise err("ERR_INVALID_REQUEST", "Each service line must be an object.")
        stype = sl.get("service_type")
        if stype not in SERVICE_TYPES:
            raise err("ERR_INVALID_REQUEST", "Invalid service_type.")
        system_id = sl.get("system_id")
        if stype in ("DUCT", "SANITIZE"):
            if system_id is None:
                raise err(
                    "ERR_INVALID_REQUEST",
                    "DUCT/SANITIZE service line requires system_id.",
                )
        else:  # DRYER_VENT
            if system_id is not None:
                raise err(
                    "ERR_INVALID_REQUEST",
                    "DRYER_VENT service line must omit system_id.",
                )
        normalized.append(
            {"service_type": stype, "system_id": system_id}
        )
    return normalized


def validate_addons(raw):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise err("ERR_INVALID_REQUEST", "addons must be an array.")
    out = []
    for code in raw:
        if code not in ADDON_CODES:
            raise err("ERR_INVALID_REQUEST", "Invalid addon code.")
        if code not in out:  # deduplicate, preserving order
            out.append(code)
    return out


def check_service_line_systems_exist(home_id, service_lines):
    """FK existence: each system_id must be an HvacSystem on the SAME home (404)."""
    for sl in service_lines:
        sid = sl.get("system_id")
        if sid is None:
            continue
        sys = db.hvac_systems.get(sid)
        if sys is None or sys["home_id"] != home_id:
            raise err("ERR_SYSTEM_NOT_FOUND", "Service line system not on this home.")


# ==========================================================================
# PricingConfig
# ==========================================================================
@app.route("/pricing-configs", methods=["POST"])
def create_pricing_config():
    auth(["PlanAdmin"])
    body = get_json_body()
    cfg = {
        "duct_base_cents": as_int(body, "duct_base_cents", minimum=0),
        "duct_per_system_cents": as_int(body, "duct_per_system_cents", minimum=0),
        "dryer_vent_flat_cents": as_int(body, "dryer_vent_flat_cents", minimum=0),
        "sanitize_per_system_cents": as_int(
            body, "sanitize_per_system_cents", minimum=0
        ),
        "addon_sanitizer_cents": as_int(body, "addon_sanitizer_cents", minimum=0),
        "addon_uv_cents": as_int(body, "addon_uv_cents", minimum=0),
        "addon_coil_cents": as_int(body, "addon_coil_cents", minimum=0),
        "multi_system_discount_pct": as_number(
            body, "multi_system_discount_pct", minimum=0, maximum=1
        ),
        "plan_member_discount_pct": as_number(
            body, "plan_member_discount_pct", minimum=0, maximum=1
        ),
        "tax_pct": as_number(body, "tax_pct", minimum=0, maximum=1),
        "status": "DRAFT",
    }
    services.stamp_new(cfg)
    db.pricing_configs[cfg["id"]] = cfg
    return response.success(public(cfg), 201)


@app.route("/pricing-configs/<cid>", methods=["GET"])
def get_pricing_config(cid):
    auth(["PlanAdmin", "Dispatcher", "Technician"])
    cfg = lookups.get_pricing_config(cid)
    return response.success(public(cfg), 200)


@app.route("/pricing-configs/<cid>/activate", methods=["POST"])
def activate_pricing_config(cid):
    auth(["PlanAdmin"])
    cfg = lookups.get_pricing_config(cid)
    # Activation rejected if target is not DRAFT (already ACTIVE/RETIRED).
    if cfg["status"] != "DRAFT":
        raise err(
            "ERR_PRICING_CONFIG_ALREADY_ACTIVE",
            "PricingConfig is not DRAFT.",
        )
    # Cascade: retire any currently ACTIVE config.
    for other in db.pricing_configs.values():
        if other["id"] != cfg["id"] and other["status"] == "ACTIVE":
            other["status"] = "RETIRED"
            services.touch(other)
    cfg["status"] = "ACTIVE"
    services.touch(cfg)
    return response.success(public(cfg), 200)


# ==========================================================================
# Homeowner
# ==========================================================================
@app.route("/homeowners", methods=["POST"])
def create_homeowner():
    auth(["PlanAdmin", "Dispatcher"])
    body = get_json_body()
    full_name = as_str(body, "full_name")
    email = as_str(body, "email")
    phone = as_str(body, "phone")
    # Email unique among homeowners.
    for ho in db.homeowners.values():
        if ho["email"] == email:
            raise err("ERR_INVALID_REQUEST", "Email already in use.")
    ho = {"full_name": full_name, "email": email, "phone": phone}
    services.stamp_new(ho)
    db.homeowners[ho["id"]] = ho
    return response.success(public(ho), 201)


# ==========================================================================
# Home
# ==========================================================================
@app.route("/homes", methods=["POST"])
def create_home():
    auth(["PlanAdmin", "Dispatcher"])
    body = get_json_body()
    # FK existence (priority 4) before body-shape on the remaining fields:
    # homeowner_id existence is a not-found FK check.
    homeowner_id = body.get("homeowner_id")
    if homeowner_id is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: homeowner_id")
    lookups.get_homeowner(homeowner_id)
    address_line = as_str(body, "address_line")
    zone_code = as_str(body, "zone_code")
    square_footage = as_int(body, "square_footage", minimum=1)
    home = {
        "homeowner_id": homeowner_id,
        "address_line": address_line,
        "zone_code": zone_code,
        "square_footage": square_footage,
        "active_system_count": 0,
        "has_active_plan": False,
    }
    services.stamp_new(home)
    db.homes[home["id"]] = home
    return response.success(public(home), 201)


@app.route("/homes", methods=["GET"])
def list_homes():
    auth(["PlanAdmin", "Dispatcher", "Technician"])
    limit, offset = get_pagination()
    homeowner_id = request.args.get("homeowner_id")
    zone_code = request.args.get("zone_code")
    rows = list(db.homes.values())
    if homeowner_id is not None:
        rows = [h for h in rows if h["homeowner_id"] == homeowner_id]
    if zone_code is not None:
        rows = [h for h in rows if h["zone_code"] == zone_code]
    page, total = paginate(rows, limit, offset)
    return response.success_list(public_list(page), limit, offset, total, 200)


@app.route("/homes/<hid>", methods=["GET"])
def get_home(hid):
    auth(["PlanAdmin", "Dispatcher", "Technician", "Homeowner"])
    home = lookups.get_home(hid)
    return response.success(public(home), 200)


# ==========================================================================
# HvacSystem (nested under Home)
# ==========================================================================
@app.route("/homes/<hid>/systems", methods=["POST"])
def add_system(hid):
    auth(["PlanAdmin", "Dispatcher"])
    home = lookups.get_home(hid)
    body = get_json_body()
    label = as_str(body, "label")
    register_count = as_int(body, "register_count", minimum=1)
    sys = {
        "home_id": home["id"],
        "label": label,
        "register_count": register_count,
        "status": "ACTIVE",
    }
    services.stamp_new(sys)
    db.hvac_systems[sys["id"]] = sys
    # Cascade: recompute home active_system_count and bump home version.
    services.recompute_home_active_system_count(home)
    services.touch(home)
    return response.success(public(sys), 201)


@app.route("/homes/<hid>/systems", methods=["GET"])
def list_systems(hid):
    auth(["PlanAdmin", "Dispatcher", "Technician"])
    home = lookups.get_home(hid)
    limit, offset = get_pagination()
    status = request.args.get("status")
    rows = [s for s in db.hvac_systems.values() if s["home_id"] == home["id"]]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.success_list(public_list(page), limit, offset, total, 200)


@app.route("/homes/<hid>/systems/<sid>/decommission", methods=["POST"])
def decommission_system(hid, sid):
    auth(["PlanAdmin", "Dispatcher"])
    home = lookups.get_home(hid)
    sys = lookups.get_system(sid)
    if sys["home_id"] != home["id"]:
        raise err("ERR_SYSTEM_NOT_FOUND", "System not on this home.")
    sys["status"] = "DECOMMISSIONED"
    services.touch(sys)
    services.recompute_home_active_system_count(home)
    services.touch(home)
    return response.success(public(sys), 200)


# ==========================================================================
# RecurringPlan
# ==========================================================================
@app.route("/homes/<hid>/recurring-plans", methods=["POST"])
def enroll_plan(hid):
    auth(["PlanAdmin"])
    home = lookups.get_home(hid)
    body = get_json_body()
    cadence_months = as_int(body, "cadence_months")
    if cadence_months not in CADENCE_MONTHS:
        raise err("ERR_INVALID_REQUEST", "cadence_months must be 6, 12, or 24.")
    expected_home_version = as_int(body, "expected_home_version")
    # State: one plan per home (ACTIVE or PAUSED) — priority 14 (business_constraint).
    for p in db.recurring_plans.values():
        if p["home_id"] == home["id"] and p["lifecycle_status"] in (
            "ACTIVE",
            "PAUSED",
        ):
            raise err("ERR_PLAN_ALREADY_EXISTS", "Home already has a plan.")
    # OCC: expected_home_version — priority 15 (fiscal, last).
    if expected_home_version != home["version"]:
        raise err("ERR_STALE_HOME_VERSION", "Home version stale.")

    enrolled_at_dt = clock.now()
    next_reminder_dt = add_months(enrolled_at_dt, cadence_months)
    plan = {
        "home_id": home["id"],
        "cadence_months": cadence_months,
        "enrolled_at": format_iso8601(enrolled_at_dt),
        "next_reminder_at": format_iso8601(next_reminder_dt),
        "reminder_status": "WAITING",
        "lifecycle_status": "ACTIVE",
    }
    services.stamp_new(plan)
    db.recurring_plans[plan["id"]] = plan
    # Cascade: recompute home has_active_plan -> true; bump home version.
    services.recompute_home_has_active_plan(home)
    services.touch(home)
    return response.success(public(plan), 201)


@app.route("/homes/<hid>/recurring-plans", methods=["GET"])
def list_plans(hid):
    auth(["PlanAdmin", "Dispatcher", "Homeowner"])
    home = lookups.get_home(hid)
    limit, offset = get_pagination()
    lifecycle_status = request.args.get("lifecycle_status")
    rows = [p for p in db.recurring_plans.values() if p["home_id"] == home["id"]]
    if lifecycle_status is not None:
        rows = [p for p in rows if p["lifecycle_status"] == lifecycle_status]
    page, total = paginate(rows, limit, offset)
    return response.success_list(public_list(page), limit, offset, total, 200)


@app.route("/recurring-plans/<pid>/acknowledge", methods=["POST"])
def acknowledge_plan(pid):
    auth(["PlanAdmin"])
    plan = lookups.get_plan(pid)
    # State (priority 6): reminder must be DUE.
    if plan["reminder_status"] != "DUE":
        raise err("ERR_REMINDER_NOT_DUE", "Reminder not DUE.")
    # Cross-entity/parallel-dim state (priority 7): plan must be ACTIVE.
    if plan["lifecycle_status"] != "ACTIVE":
        raise err("ERR_PLAN_NOT_ACTIVE", "Plan not ACTIVE.")
    services.advance_reminder(plan)
    services.touch(plan)
    return response.success(public(plan), 200)


@app.route("/recurring-plans/<pid>/refresh-reminder", methods=["POST"])
def refresh_reminder(pid):
    auth(["PlanAdmin", "Dispatcher"])
    plan = lookups.get_plan(pid)
    # Force WAITING->DUE if clock now >= next_reminder_at and plan ACTIVE.
    if plan["lifecycle_status"] != "ACTIVE":
        raise err("ERR_PLAN_NOT_ACTIVE", "Plan not ACTIVE.")
    if plan["reminder_status"] == "WAITING":
        due_at = parse_iso8601(plan["next_reminder_at"])
        if due_at is not None and clock.now() >= due_at:
            plan["reminder_status"] = "DUE"
            services.touch(plan)
        else:
            # Forcing a reminder due before next_reminder_at -> ERR_REMINDER_NOT_DUE.
            raise err("ERR_REMINDER_NOT_DUE", "Reminder not yet due.")
    # If the reminder is already DUE, re-evaluation is a no-op leaving it DUE.
    return response.success(public(plan), 200)


@app.route("/recurring-plans/<pid>/pause", methods=["POST"])
def pause_plan(pid):
    auth(["PlanAdmin"])
    plan = lookups.get_plan(pid)
    if plan["lifecycle_status"] != "ACTIVE":
        raise err("ERR_PLAN_BAD_STATE", "Plan not ACTIVE.")
    plan["lifecycle_status"] = "PAUSED"
    services.touch(plan)
    home = db.homes.get(plan["home_id"])
    if home is not None:
        services.recompute_home_has_active_plan(home)
        services.touch(home)
    return response.success(public(plan), 200)


@app.route("/recurring-plans/<pid>/resume", methods=["POST"])
def resume_plan(pid):
    auth(["PlanAdmin"])
    plan = lookups.get_plan(pid)
    if plan["lifecycle_status"] != "PAUSED":
        raise err("ERR_PLAN_BAD_STATE", "Plan not PAUSED.")
    plan["lifecycle_status"] = "ACTIVE"
    services.touch(plan)
    home = db.homes.get(plan["home_id"])
    if home is not None:
        services.recompute_home_has_active_plan(home)
        services.touch(home)
    return response.success(public(plan), 200)


@app.route("/recurring-plans/<pid>/cancel", methods=["POST"])
def cancel_plan(pid):
    auth(["PlanAdmin"])
    plan = lookups.get_plan(pid)
    if plan["lifecycle_status"] not in ("ACTIVE", "PAUSED"):
        raise err("ERR_PLAN_BAD_STATE", "Plan cannot be cancelled.")
    plan["lifecycle_status"] = "CANCELLED"
    # reminder_status frozen at current value.
    services.touch(plan)
    home = db.homes.get(plan["home_id"])
    if home is not None:
        services.recompute_home_has_active_plan(home)
        services.touch(home)
    return response.success(public(plan), 200)


# ==========================================================================
# CrewMember
# ==========================================================================
@app.route("/crew-members", methods=["POST"])
def create_crew():
    auth(["Dispatcher"])
    body = get_json_body()
    full_name = as_str(body, "full_name")
    home_zone_code = as_str(body, "home_zone_code")
    certified_for_uv = as_bool(body, "certified_for_uv", default=False)
    crew = {
        "full_name": full_name,
        "home_zone_code": home_zone_code,
        "certified_for_uv": certified_for_uv,
    }
    services.stamp_new(crew)
    db.crew_members[crew["id"]] = crew
    return response.success(public(crew), 201)


# ==========================================================================
# RoutePlan
# ==========================================================================
@app.route("/route-plans", methods=["POST"])
def create_route():
    auth(["Dispatcher"])
    body = get_json_body()
    # FK existence (priority 4): crew_member_id.
    crew_member_id = body.get("crew_member_id")
    if crew_member_id is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: crew_member_id")
    lookups.get_crew(crew_member_id)
    zone_code = as_str(body, "zone_code")
    service_date = as_str(body, "service_date")
    shift_start_minute = as_int(body, "shift_start_minute", minimum=0, exclusive_max=1440)
    shift_end_minute = as_int(body, "shift_end_minute", minimum=0, maximum=1440)
    if shift_end_minute <= shift_start_minute:
        raise err(
            "ERR_INVALID_REQUEST",
            "shift_end_minute must be greater than shift_start_minute.",
        )
    # Crew double-booking (priority 11b): closed-interval, whole-window, no buffer.
    for r in db.route_plans.values():
        if (
            r["crew_member_id"] == crew_member_id
            and r["service_date"] == service_date
        ):
            # closed-interval overlap: a <= d AND c <= b
            if (
                shift_start_minute <= r["shift_end_minute"]
                and r["shift_start_minute"] <= shift_end_minute
            ):
                raise err("ERR_CREW_DOUBLE_BOOKED", "Crew already booked.")
    route = {
        "crew_member_id": crew_member_id,
        "zone_code": zone_code,
        "service_date": service_date,
        "shift_start_minute": shift_start_minute,
        "shift_end_minute": shift_end_minute,
        "committed_minutes": 0,
        "status": "OPEN",
    }
    services.stamp_new(route)
    db.route_plans[route["id"]] = route
    return response.success(public(route), 201)


@app.route("/route-plans", methods=["GET"])
def list_routes():
    auth(["PlanAdmin", "Dispatcher", "Technician"])
    limit, offset = get_pagination()
    crew_member_id = request.args.get("crew_member_id")
    zone_code = request.args.get("zone_code")
    status = request.args.get("status")
    rows = list(db.route_plans.values())
    if crew_member_id is not None:
        rows = [r for r in rows if r["crew_member_id"] == crew_member_id]
    if zone_code is not None:
        rows = [r for r in rows if r["zone_code"] == zone_code]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.success_list(public_list(page), limit, offset, total, 200)


@app.route("/route-plans/<rid>", methods=["GET"])
def get_route(rid):
    auth(["PlanAdmin", "Dispatcher", "Technician"])
    route = lookups.get_route(rid)
    return response.success(public(route), 200)


@app.route("/route-plans/<rid>/commit", methods=["POST"])
def commit_slot(rid):
    auth(["Dispatcher"])
    route = lookups.get_route(rid)
    body = get_json_body()
    # FK existence (priority 4): work_order_id.
    work_order_id = body.get("work_order_id")
    if work_order_id is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: work_order_id")
    wo = lookups.get_work_order(work_order_id)
    scheduled_start_minute = as_int(
        body, "scheduled_start_minute", minimum=0, exclusive_max=1440
    )
    expected_route_plan_version = as_int(body, "expected_route_plan_version")

    # State (priority 6): work order QUOTED, route OPEN.
    if wo["status"] != "QUOTED":
        raise err("ERR_WORK_ORDER_BAD_STATE", "WorkOrder not QUOTED.")
    if route["status"] != "OPEN":
        raise err("ERR_ROUTE_NOT_OPEN", "Route not OPEN.")

    home = db.homes.get(wo["home_id"])

    # Business safety (priority 8): UV add-on requires certified crew.
    if "UV" in wo["addons"]:
        crew = db.crew_members.get(route["crew_member_id"])
        if crew is None or not crew["certified_for_uv"]:
            raise err("ERR_CREW_NOT_UV_CERTIFIED", "Crew not UV-certified.")

    # Business constraint (priority 9): zone match.
    if home is None or route["zone_code"] != home["zone_code"]:
        raise err("ERR_ZONE_MISMATCH", "Zone mismatch.")

    # Business temporal (priority 10): shift containment.
    duration = wo["duration_minutes"]
    if (
        scheduled_start_minute < route["shift_start_minute"]
        or scheduled_start_minute + duration > route["shift_end_minute"]
    ):
        raise err("ERR_OUTSIDE_SHIFT", "Slot outside shift window.")

    # Business temporal (priority 11): slot overlap (buffered, half-open).
    if services.slot_overlaps(route, scheduled_start_minute, duration):
        raise err("ERR_SLOT_OVERLAP", "Slot overlaps an existing committed slot.")

    # OCC (priority 15): expected_route_plan_version.
    if expected_route_plan_version != route["version"]:
        raise err("ERR_STALE_ROUTE_VERSION", "Route version stale.")

    # Commit.
    wo["route_plan_id"] = route["id"]
    wo["crew_member_id"] = route["crew_member_id"]
    wo["scheduled_start_minute"] = scheduled_start_minute
    wo["status"] = "SCHEDULED"
    services.touch(wo)
    # Cascade: committed_minutes += duration; route version bump.
    route["committed_minutes"] += duration
    services.touch(route)
    return response.success(public(wo), 200)


@app.route("/route-plans/<rid>/lock", methods=["POST"])
def lock_route(rid):
    auth(["Dispatcher"])
    route = lookups.get_route(rid)
    if route["status"] != "OPEN":
        raise err("ERR_ROUTE_BAD_STATE", "Route not OPEN.")
    if route["committed_minutes"] <= 0:
        raise err("ERR_ROUTE_EMPTY", "Cannot lock an empty route.")
    route["status"] = "LOCKED"
    services.touch(route)
    return response.success(public(route), 200)


@app.route("/route-plans/<rid>/close", methods=["POST"])
def close_route(rid):
    auth(["Dispatcher"])
    route = lookups.get_route(rid)
    if route["status"] != "LOCKED":
        raise err("ERR_ROUTE_BAD_STATE", "Route not LOCKED.")
    # Cross-entity (priority 7): no committed WO still SCHEDULED/IN_PROGRESS.
    for wo in db.work_orders.values():
        if wo["route_plan_id"] == route["id"] and wo["status"] in (
            "SCHEDULED",
            "IN_PROGRESS",
        ):
            raise err("ERR_ROUTE_HAS_OPEN_WORK", "Route has open work.")
    route["status"] = "CLOSED"
    services.touch(route)
    return response.success(public(route), 200)


# ==========================================================================
# WorkOrder
# ==========================================================================
@app.route("/work-orders", methods=["POST"])
def create_work_order():
    auth(["Dispatcher", "Technician"])
    body = get_json_body()
    # FK existence (priority 4): home_id.
    home_id = body.get("home_id")
    if home_id is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: home_id")
    home = lookups.get_home(home_id)
    # Body-shape (priority 5).
    requested_start_minute = as_int(
        body, "requested_start_minute", minimum=0, exclusive_max=1440
    )
    service_lines = validate_and_normalize_service_lines(
        home["id"], body.get("service_lines")
    )
    addons = validate_addons(body.get("addons"))
    # FK existence of service-line systems (priority 4 referential).
    check_service_line_systems_exist(home["id"], service_lines)
    wo = {
        "home_id": home["id"],
        "route_plan_id": None,
        "crew_member_id": None,
        "service_lines": service_lines,
        "addons": addons,
        "requested_start_minute": requested_start_minute,
        "scheduled_start_minute": None,
        "duration_minutes": None,
        "estimate_total_cents": None,
        "invoice_total_cents": None,
        "pricing_config_id": None,
        "status": "DRAFT",
    }
    services.stamp_new(wo)
    db.work_orders[wo["id"]] = wo
    return response.success(public(wo), 201)


@app.route("/work-orders", methods=["GET"])
def list_work_orders():
    auth(["PlanAdmin", "Dispatcher", "Technician"])
    limit, offset = get_pagination()
    home_id = request.args.get("home_id")
    route_plan_id = request.args.get("route_plan_id")
    crew_member_id = request.args.get("crew_member_id")
    pricing_config_id = request.args.get("pricing_config_id")
    status = request.args.get("status")
    rows = list(db.work_orders.values())
    if home_id is not None:
        rows = [w for w in rows if w["home_id"] == home_id]
    if route_plan_id is not None:
        rows = [w for w in rows if w["route_plan_id"] == route_plan_id]
    if crew_member_id is not None:
        rows = [w for w in rows if w["crew_member_id"] == crew_member_id]
    if pricing_config_id is not None:
        rows = [w for w in rows if w["pricing_config_id"] == pricing_config_id]
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.success_list(public_list(page), limit, offset, total, 200)


@app.route("/work-orders/<wid>", methods=["GET"])
def get_work_order(wid):
    auth(["PlanAdmin", "Dispatcher", "Technician", "Homeowner"])
    wo = lookups.get_work_order(wid)
    return response.success(public(wo), 200)


def _upsert_inspection(wo, phase, before_photo_count, after_photo_count,
                       dust_severity, recommend_hvac_repair):
    """Find an existing inspection of the given phase for this WO, or create one."""
    existing = None
    for ins in db.inspections.values():
        if ins["work_order_id"] == wo["id"] and ins["phase"] == phase:
            existing = ins
            break
    if existing is None:
        ins = {
            "work_order_id": wo["id"],
            "before_photo_count": before_photo_count,
            "after_photo_count": after_photo_count,
            "dust_severity": dust_severity,
            "recommend_hvac_repair": recommend_hvac_repair,
            "phase": phase,
        }
        services.stamp_new(ins)
        db.inspections[ins["id"]] = ins
        return ins
    existing["before_photo_count"] = before_photo_count
    existing["after_photo_count"] = after_photo_count
    existing["dust_severity"] = dust_severity
    existing["recommend_hvac_repair"] = recommend_hvac_repair
    services.touch(existing)
    return existing


def _delete_before_inspection(wo):
    to_del = [
        ins["id"]
        for ins in db.inspections.values()
        if ins["work_order_id"] == wo["id"] and ins["phase"] == "BEFORE"
    ]
    for iid in to_del:
        del db.inspections[iid]


@app.route("/work-orders/<wid>/inspect", methods=["POST"])
def inspect_work_order(wid):
    auth(["Technician"])
    wo = lookups.get_work_order(wid)
    body = get_json_body()
    before_photo_count = as_int(body, "before_photo_count", minimum=0)
    dust_severity = as_int(body, "dust_severity", minimum=0, maximum=10)
    recommend_hvac_repair = as_bool(body, "recommend_hvac_repair", default=False)

    # State (priority 6): must be DRAFT (initial) or QUOTED (re-inspect).
    if wo["status"] not in ("DRAFT", "QUOTED"):
        raise err("ERR_WORK_ORDER_BAD_STATE", "WorkOrder not inspectable.")

    if wo["status"] == "QUOTED":
        # Cross-entity (priority 7): re-inspect requires route_plan_id null.
        if wo["route_plan_id"] is not None:
            raise err(
                "ERR_WORK_ORDER_ALREADY_SCHEDULED",
                "WorkOrder already scheduled.",
            )

    # All service lines must reference ACTIVE systems on the WO's home.
    for sl in wo["service_lines"]:
        sid = sl.get("system_id")
        if sid is None:
            continue
        sys = db.hvac_systems.get(sid)
        if sys is None or sys["status"] != "ACTIVE":
            raise err("ERR_SYSTEM_NOT_ACTIVE", "Service line system not ACTIVE.")

    if wo["status"] == "DRAFT":
        _upsert_inspection(
            wo, "BEFORE", before_photo_count, 0, dust_severity,
            recommend_hvac_repair,
        )
        wo["status"] = "INSPECTED"
    else:  # QUOTED -> INSPECTED re-inspection
        _delete_before_inspection(wo)
        ins = {
            "work_order_id": wo["id"],
            "before_photo_count": before_photo_count,
            "after_photo_count": 0,
            "dust_severity": dust_severity,
            "recommend_hvac_repair": recommend_hvac_repair,
            "phase": "BEFORE",
        }
        services.stamp_new(ins)
        db.inspections[ins["id"]] = ins
        # Clear estimate + pinned config (re-quote required).
        wo["estimate_total_cents"] = None
        wo["pricing_config_id"] = None
        wo["status"] = "INSPECTED"
    services.touch(wo)
    return response.success(public(wo), 200)


@app.route("/work-orders/<wid>/quote", methods=["POST"])
def quote_work_order(wid):
    auth(["Technician"])
    wo = lookups.get_work_order(wid)
    # State (priority 6).
    if wo["status"] != "INSPECTED":
        raise err("ERR_WORK_ORDER_BAD_STATE", "WorkOrder not INSPECTED.")
    # Business constraint (priority 13): exactly one ACTIVE PricingConfig.
    active_cfgs = [c for c in db.pricing_configs.values() if c["status"] == "ACTIVE"]
    if len(active_cfgs) != 1:
        raise err("ERR_NO_ACTIVE_PRICING_CONFIG", "No active pricing config.")
    cfg = active_cfgs[0]
    home = db.homes.get(wo["home_id"])
    wo["pricing_config_id"] = cfg["id"]
    wo["estimate_total_cents"] = services.compute_estimate_total(wo, home, cfg)
    wo["duration_minutes"] = services.compute_duration_minutes(wo, home)
    wo["status"] = "QUOTED"
    services.touch(wo)
    return response.success(public(wo), 200)


@app.route("/work-orders/<wid>/start", methods=["POST"])
def start_work_order(wid):
    auth(["Technician"])
    wo = lookups.get_work_order(wid)
    if wo["status"] != "SCHEDULED":
        raise err("ERR_WORK_ORDER_BAD_STATE", "WorkOrder not SCHEDULED.")
    # Cross-entity (priority 7): route must be LOCKED.
    route = db.route_plans.get(wo["route_plan_id"])
    if route is None or route["status"] != "LOCKED":
        raise err("ERR_ROUTE_NOT_LOCKED", "Route not LOCKED.")
    wo["status"] = "IN_PROGRESS"
    services.touch(wo)
    return response.success(public(wo), 200)


@app.route("/work-orders/<wid>/complete", methods=["POST"])
def complete_work_order(wid):
    auth(["Technician"])
    wo = lookups.get_work_order(wid)
    body = get_json_body()
    after_photo_count = as_int(body, "after_photo_count", minimum=0)
    dust_severity = as_int(body, "dust_severity", minimum=0, maximum=10)
    recommend_hvac_repair = as_bool(body, "recommend_hvac_repair", default=False)
    home = db.homes.get(wo["home_id"])
    performed_service_lines = validate_and_normalize_service_lines(
        wo["home_id"], body.get("performed_service_lines")
    )
    performed_addons = validate_addons(body.get("performed_addons"))
    check_service_line_systems_exist(wo["home_id"], performed_service_lines)

    # State (priority 6).
    if wo["status"] != "IN_PROGRESS":
        raise err("ERR_WORK_ORDER_BAD_STATE", "WorkOrder not IN_PROGRESS.")
    # Business safety (priority 12): after_photo_count >= MIN_AFTER_PHOTOS.
    if after_photo_count < MIN_AFTER_PHOTOS:
        raise err("ERR_INSUFFICIENT_AFTER_PHOTOS", "Need at least one after photo.")

    # Record AFTER inspection.
    after_ins = _upsert_inspection(
        wo, "AFTER", 0, after_photo_count, dust_severity, recommend_hvac_repair
    )

    # Invoice from performed lines + pinned config + live home counts.
    cfg = db.pricing_configs.get(wo["pricing_config_id"])
    wo["invoice_total_cents"] = services.compute_invoice_total(
        performed_service_lines, performed_addons, home, cfg
    )
    wo["status"] = "COMPLETED"
    services.touch(wo)

    # Cascade 1: referral if recommend_hvac_repair true.
    if after_ins["recommend_hvac_repair"]:
        referral = {
            "work_order_id": wo["id"],
            "home_id": wo["home_id"],
            "severity_at_referral": after_ins["dust_severity"],
            "status": "PENDING",
        }
        services.stamp_new(referral)
        db.upsell_referrals[referral["id"]] = referral
        # Home denormalization touch.
        if home is not None:
            services.touch(home)

    # Cascade 2: acknowledge a DUE ACTIVE plan on this home.
    for plan in db.recurring_plans.values():
        if (
            plan["home_id"] == wo["home_id"]
            and plan["lifecycle_status"] == "ACTIVE"
            and plan["reminder_status"] == "DUE"
        ):
            services.advance_reminder(plan)
            services.touch(plan)

    return response.success(public(wo), 200)


@app.route("/work-orders/<wid>/cancel", methods=["POST"])
def cancel_work_order(wid):
    auth(["Dispatcher"])
    wo = lookups.get_work_order(wid)
    if wo["status"] not in ("DRAFT", "INSPECTED", "QUOTED", "SCHEDULED"):
        raise err("ERR_WORK_ORDER_BAD_STATE", "WorkOrder not cancellable.")
    # Ledger reversal if committed to a route.
    if wo["route_plan_id"] is not None:
        route = db.route_plans.get(wo["route_plan_id"])
        if route is not None:
            route["committed_minutes"] -= wo["duration_minutes"]
            services.touch(route)
        wo["route_plan_id"] = None
        wo["crew_member_id"] = None
        wo["scheduled_start_minute"] = None
    wo["status"] = "CANCELLED"
    services.touch(wo)
    return response.success(public(wo), 200)


@app.route("/work-orders/<wid>/inspections", methods=["GET"])
def list_inspections(wid):
    auth(["PlanAdmin", "Dispatcher", "Technician", "Homeowner"])
    wo = lookups.get_work_order(wid)
    limit, offset = get_pagination()
    phase = request.args.get("phase")
    rows = [i for i in db.inspections.values() if i["work_order_id"] == wo["id"]]
    if phase is not None:
        rows = [i for i in rows if i["phase"] == phase]
    page, total = paginate(rows, limit, offset)
    return response.success_list(public_list(page), limit, offset, total, 200)


# ==========================================================================
# UpsellReferral
# ==========================================================================
@app.route("/upsell-referrals", methods=["GET"])
def list_referrals():
    auth(["PlanAdmin", "Dispatcher"])
    limit, offset = get_pagination()
    work_order_id = request.args.get("work_order_id")
    home_id = request.args.get("home_id")
    status = request.args.get("status")
    rows = list(db.upsell_referrals.values())
    if work_order_id is not None:
        rows = [r for r in rows if r["work_order_id"] == work_order_id]
    if home_id is not None:
        rows = [r for r in rows if r["home_id"] == home_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.success_list(public_list(page), limit, offset, total, 200)


@app.route("/upsell-referrals/<rid>", methods=["GET"])
def get_referral(rid):
    auth(["PlanAdmin", "Dispatcher"])
    referral = lookups.get_referral(rid)
    return response.success(public(referral), 200)


@app.route("/upsell-referrals/<rid>/decline", methods=["POST"])
def decline_referral(rid):
    auth(["PlanAdmin"])
    referral = lookups.get_referral(rid)
    if referral["status"] != "PENDING":
        raise err("ERR_REFERRAL_BAD_STATE", "Referral not PENDING.")
    referral["status"] = "DECLINED"
    services.touch(referral)
    return response.success(public(referral), 200)


@app.route("/upsell-referrals/<rid>/expire", methods=["POST"])
def expire_referral(rid):
    auth(["PlanAdmin", "Dispatcher"])
    referral = lookups.get_referral(rid)
    if referral["status"] != "PENDING":
        raise err("ERR_REFERRAL_BAD_STATE", "Referral not PENDING.")
    created = parse_iso8601(referral["created_at"])
    if created is not None and clock.now() >= created + timedelta(
        days=REFERRAL_TTL_DAYS
    ):
        referral["status"] = "EXPIRED"
        services.touch(referral)
    # Otherwise no-op, leaving PENDING (and still returns 200 with the referral).
    return response.success(public(referral), 200)


# ==========================================================================
# CallbackTicket
# ==========================================================================
@app.route("/callback-tickets", methods=["POST"])
def create_ticket():
    auth(["Dispatcher", "Homeowner"])
    body = get_json_body()
    # FK existence (priority 4): work_order_id, optional reopened_from_ticket_id.
    work_order_id = body.get("work_order_id")
    if work_order_id is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: work_order_id")
    lookups.get_work_order(work_order_id)
    reopened_from_ticket_id = body.get("reopened_from_ticket_id")
    if reopened_from_ticket_id is not None:
        lookups.get_ticket(reopened_from_ticket_id)
    reason = as_str(body, "reason")
    redo_required = as_bool(body, "redo_required", default=False)
    ticket = {
        "work_order_id": work_order_id,
        "reopened_from_ticket_id": reopened_from_ticket_id,
        "reason": reason,
        "redo_required": redo_required,
        "status": "OPEN",
    }
    services.stamp_new(ticket)
    db.callback_tickets[ticket["id"]] = ticket
    return response.success(public(ticket), 201)


@app.route("/callback-tickets", methods=["GET"])
def list_tickets():
    auth(["PlanAdmin", "Dispatcher"])
    limit, offset = get_pagination()
    work_order_id = request.args.get("work_order_id")
    reopened_from_ticket_id = request.args.get("reopened_from_ticket_id")
    status = request.args.get("status")
    rows = list(db.callback_tickets.values())
    if work_order_id is not None:
        rows = [t for t in rows if t["work_order_id"] == work_order_id]
    if reopened_from_ticket_id is not None:
        rows = [
            t for t in rows
            if t["reopened_from_ticket_id"] == reopened_from_ticket_id
        ]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.success_list(public_list(page), limit, offset, total, 200)


@app.route("/callback-tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    auth(["PlanAdmin", "Dispatcher", "Homeowner"])
    ticket = lookups.get_ticket(tid)
    return response.success(public(ticket), 200)


@app.route("/callback-tickets/<tid>/resolve", methods=["POST"])
def resolve_ticket(tid):
    auth(["Dispatcher"])
    ticket = lookups.get_ticket(tid)
    if ticket["status"] not in ("OPEN", "REOPENED"):
        raise err("ERR_TICKET_BAD_STATE", "Ticket not OPEN/REOPENED.")
    # Cross-entity (priority 7): referenced WO must be COMPLETED.
    wo = db.work_orders.get(ticket["work_order_id"])
    if wo is None or wo["status"] != "COMPLETED":
        raise err("ERR_WORK_ORDER_NOT_COMPLETED", "WorkOrder not COMPLETED.")
    ticket["status"] = "RESOLVED"
    services.touch(ticket)
    return response.success(public(ticket), 200)


@app.route("/callback-tickets/<tid>/reopen", methods=["POST"])
def reopen_ticket(tid):
    auth(["Dispatcher"])
    ticket = lookups.get_ticket(tid)
    if ticket["status"] != "RESOLVED":
        raise err("ERR_TICKET_BAD_STATE", "Ticket not RESOLVED.")
    ticket["status"] = "REOPENED"
    services.touch(ticket)
    return response.success(public(ticket), 200)


# ==========================================================================
# Logical clock
# ==========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(["PlanAdmin", "Dispatcher"])
    body = get_json_body()
    to_iso8601 = as_str(body, "to_iso8601")
    dt = parse_iso8601(to_iso8601)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "Invalid to_iso8601 value.")
    clock.set(dt)
    # Re-evaluate due reminders and TTL-expired referrals.
    services.reevaluate_clock_driven()
    return response.success({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
