"""Display events: create/read/list, site plans, and the show-day transition
endpoints (standby-confirm, ready, go-no-go, complete-show, cancel)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from auth import require_roles
from db import store, new_record, bump
from errors import err
from response import ok, ok_list, serialize, serialize_list, sort_created
from services import (
    EVENT_CANCELLABLE, EVENT_TERMINAL, GO_NO_GO_WINDOW_MIN, WEATHER_VALIDITY_MIN,
    WIND_SUSTAINED_LIMIT_MPH, WIND_GUST_LIMIT_MPH, batches_at_show, cancel_event,
    check_display_ownership, check_operator_active, check_operator_exists,
    current_site_plan, approved_application, event_movement_sums,
    rsd_for_diameter, venue_conflict, wind_adjusted_radius,
)
from validation import validate_schema, parse_pagination, paginate

bp = Blueprint("displays", __name__)


def _get_display(display_id):
    ev = store.displays.get(display_id)
    if ev is None:
        err("ERR_NOT_FOUND", f"display {display_id} not found")
    return ev


def _latest_reading(ev):
    readings = [w for w in store.weather_readings.values()
                if w["display_event_id"] == ev["id"]]
    if not readings:
        return None
    return sorted(readings, key=lambda w: (w["created_at"], w["_seq"]))[-1]


@bp.post("/pyro/displays")
def create_display():
    uid, _ = require_roles("Operator")
    vals = validate_schema(request.get_json(silent=True), [
        ("venue_id", "str", True, None),
        ("venue_name", "str", True, None),
        ("scheduled_start_at", "dt", True, None),
        ("scheduled_end_at", "dt", True, None),
        ("declared_max_shell_diameter_in", "num", True, None),
    ])
    start = vals["scheduled_start_at"]
    end = vals["scheduled_end_at"]
    if end <= start:
        err("ERR_VALIDATION", "scheduled_end_at must be strictly after scheduled_start_at")
    if start <= store.clock:
        err("ERR_VALIDATION", "scheduled_start_at must be strictly in the future")
    if vals["declared_max_shell_diameter_in"] <= 0:
        err("ERR_VALIDATION", "declared_max_shell_diameter_in must be > 0")
    op = check_operator_exists(uid)
    check_operator_active(uid)
    # License window contains the show date inclusively at both ends.
    if not (op["license_valid_from"] <= start <= op["license_expires_at"]):
        err("ERR_LICENSE_EXPIRED", "operator license window does not contain scheduled_start_at")
    venue_conflict(uid, vals["venue_id"], start, end)
    rec = new_record()
    rec.update({
        "operator_id": uid,
        "venue_id": vals["venue_id"],
        "venue_name": vals["venue_name"],
        "scheduled_start_at": start,
        "scheduled_end_at": end,
        "declared_max_shell_diameter_in": vals["declared_max_shell_diameter_in"],
        "status": "DRAFT",
        "weather_decision": "PENDING",
        "cancellation_reason": None,
        "termination_reason": None,
        "standby_confirmed_at": None,
        "standby_confirmed_by": None,
        "show_completed_at": None,
        "closed_at": None,
        "dud_count": 0,
        "fired_count": 0,
        "final_fallout_radius_ft": None,
        "final_standby_fee_cents": None,
    })
    store.displays[rec["id"]] = rec
    return ok(serialize(rec), 201)

@bp.get("/pyro/displays/<display_id>")
def get_display(display_id):
    uid, role = require_roles("Operator", "FireMarshal", "CrewMember", "SystemAdmin")
    ev = _get_display(display_id)
    if role == "Operator":
        check_display_ownership(ev, uid)
    return ok(serialize(ev))

@bp.get("/pyro/displays")
def list_displays():
    uid, role = require_roles("Operator", "FireMarshal", "SystemAdmin")
    limit, offset = parse_pagination(request.args)
    recs = list(store.displays.values())
    op_filter = request.args.get("operator_id")
    if role == "Operator":
        if op_filter is not None and op_filter != uid:
            err("ERR_FORBIDDEN_OWNERSHIP", "operator may only list its own displays")
        recs = [e for e in recs if e["operator_id"] == uid]
    elif op_filter is not None:
        recs = [e for e in recs if e["operator_id"] == op_filter]
    status = request.args.get("status")
    if status is not None:
        recs = [e for e in recs if e["status"] == status]
    recs = sort_created(recs)
    return ok_list(serialize_list(paginate(recs, limit, offset)), len(recs),
                   limit, offset)

# ---- Site plans ---------------------------------------------------------

@bp.post("/pyro/displays/<display_id>/site-plans")
def create_site_plan(display_id):
    uid, _ = require_roles("Operator")
    vals = validate_schema(request.get_json(silent=True), [
        ("diagram_ref", "str", True, None),
        ("launch_area_width_ft", "num", True, None),
        ("launch_area_length_ft", "num", True, None),
        ("spectator_boundary_ft", "int", True, None),
        ("spectator_arc_center_deg", "int", True, None),
        ("nearest_structure_ft", "int", True, None),
        ("expected_display_event_version", "int", True, None),
    ])
    if vals["launch_area_width_ft"] <= 0:
        err("ERR_VALIDATION", "launch_area_width_ft must be > 0")
    if vals["launch_area_length_ft"] <= 0:
        err("ERR_VALIDATION", "launch_area_length_ft must be > 0")
    if not (0 <= vals["spectator_arc_center_deg"] <= 359):
        err("ERR_VALIDATION", "spectator_arc_center_deg must be in [0, 359]")
    ev = _get_display(display_id)
    check_display_ownership(ev, uid)
    # OCC (tier 6): the client must have observed the latest event state
    # before superseding its current plan.
    if vals["expected_display_event_version"] != ev["version"]:
        err("ERR_STALE_VERSION", "expected_display_event_version does not match current version")
    check_operator_active(uid)
    rsd = rsd_for_diameter(ev["declared_max_shell_diameter_in"])
    if vals["spectator_boundary_ft"] < rsd or vals["nearest_structure_ft"] < rsd:
        err("ERR_FALLOUT_EXCEEDS_BOUNDARY",
            "spectator boundary and nearest structure must be >= required distance")
    prior = current_site_plan(ev)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        bump(prior)
    rec = new_record()
    rec.update({
        "display_event_id": ev["id"],
        "diagram_ref": vals["diagram_ref"],
        "launch_area_width_ft": vals["launch_area_width_ft"],
        "launch_area_length_ft": vals["launch_area_length_ft"],
        "spectator_boundary_ft": vals["spectator_boundary_ft"],
        "spectator_arc_center_deg": vals["spectator_arc_center_deg"],
        "nearest_structure_ft": vals["nearest_structure_ft"],
        "required_spectator_distance_ft": rsd,
        "status": "CURRENT",
    })
    store.site_plans[rec["id"]] = rec
    bump(ev)
    return ok(serialize(rec), 201)

@bp.get("/pyro/displays/<display_id>/site-plans")
def list_site_plans(display_id):
    uid, role = require_roles("Operator", "FireMarshal")
    ev = _get_display(display_id)
    if role == "Operator":
        check_display_ownership(ev, uid)
    limit, offset = parse_pagination(request.args)
    recs = sort_created([p for p in store.site_plans.values()
                         if p["display_event_id"] == display_id])
    return ok_list(serialize_list(paginate(recs, limit, offset)), len(recs),
                   limit, offset)

# ---- Show-day transitions ------------------------------------------------

@bp.post("/pyro/displays/<display_id>/standby-confirm")
def standby_confirm(display_id):
    uid, _ = require_roles("FireMarshal")
    vals = validate_schema(request.get_json(silent=True), [
        ("standby_engines_on_site", "int", True, None),
        ("note", "str", False, None),
    ])
    ev = _get_display(display_id)
    if ev["status"] != "APPROVED":
        err("ERR_INVALID_STATE", "event is not APPROVED")
    app = approved_application(ev)
    engines_required = app["standby_engines"] if app else None
    # Segregation of duties: confirmer must differ from the approver.
    if app is not None and uid == app["reviewed_by_user_id"]:
        err("ERR_SOD_VIOLATION", "standby confirmer must differ from approving marshal")
    if vals["standby_engines_on_site"] != engines_required:
        err("ERR_VALIDATION", "standby_engines_on_site must equal the approved standby_engines")
    ev["standby_confirmed_at"] = store.clock
    ev["standby_confirmed_by"] = uid
    ev["status"] = "STANDBY_CONFIRMED"
    bump(ev)
    return ok(serialize(ev))

@bp.post("/pyro/displays/<display_id>/ready")
def ready(display_id):
    uid, _ = require_roles("Operator")
    ev = _get_display(display_id)
    check_display_ownership(ev, uid)
    if ev["status"] != "STANDBY_CONFIRMED":
        err("ERR_INVALID_STATE", "event is not STANDBY_CONFIRMED")
    check_operator_active(uid)
    # Tier 10 (certification) precedes tier 11 (aggregate gates).
    lead_ok = any(
        c["operator_id"] == uid and c["cert_level"] == "LEAD_OPERATOR"
        and c["cert_expires_at"] >= ev["scheduled_start_at"]
        for c in store.crew_members.values())
    if not lead_ok:
        err("ERR_CERT_NOT_VALID",
            "no LEAD_OPERATOR crew certification covers the show date")
    posts = [p for p in store.security_posts.values()
             if p["display_event_id"] == ev["id"]]
    if not posts or any(p["status"] != "SECURED" for p in posts):
        err("ERR_SECURITY_NOT_SECURED",
            "every security post must exist and be SECURED")
    co, re, _ = event_movement_sums(ev["id"])
    if co - re <= 0:
        err("ERR_NO_PRODUCT_ON_SITE", "net checked-out product for the event is zero")
    ev["status"] = "READY"
    bump(ev)
    return ok(serialize(ev))

@bp.post("/pyro/displays/<display_id>/go-no-go")
def go_no_go(display_id):
    uid, _ = require_roles("Operator")
    vals = validate_schema(request.get_json(silent=True), [
        ("decision", "enum", True, {"GO", "NO_GO"}),
        ("expected_display_event_version", "int", True, None),
    ])
    ev = _get_display(display_id)
    check_display_ownership(ev, uid)
    # OCC (tier 6) — a GO is only valid against the exact version reviewed.
    if vals["expected_display_event_version"] != ev["version"]:
        err("ERR_STALE_VERSION", "expected_display_event_version does not match current version")
    if ev["status"] != "READY":
        err("ERR_INVALID_STATE", "event is not READY")
    check_operator_active(uid)
    if vals["decision"] == "GO":
        latest = _latest_reading(ev)
        # GO limits are strict (tier 8): sustained >= 20.0, gust >= 25.0,
        # or any precipitation fails.
        if latest is not None and (
                latest["wind_speed_mph"] >= WIND_SUSTAINED_LIMIT_MPH
                or latest["gust_mph"] >= WIND_GUST_LIMIT_MPH
                or latest["precipitation"]):
            err("ERR_WEATHER_NO_GO", "latest weather reading breaches GO limits")
        if latest is None or (store.clock - latest["created_at"]) > timedelta(
                minutes=WEATHER_VALIDITY_MIN):
            err("ERR_WEATHER_STALE", "no weather reading, or latest reading is stale")
        if not (ev["scheduled_start_at"] - timedelta(minutes=GO_NO_GO_WINDOW_MIN)
                <= store.clock <= ev["scheduled_end_at"]):
            err("ERR_SHOW_WINDOW_NOT_OPEN", "go/no-go decision window is not open")
        # Final fallout geometry derives from product actually on site.
        at_show = batches_at_show(ev["id"])
        max_d = max((b["shell_diameter_in"] for b in at_show), default=Decimal("0"))
        base = rsd_for_diameter(max_d)
        plan = current_site_plan(ev)
        if plan is None:
            err("ERR_INVALID_STATE", "no CURRENT site plan for the event")
        final = wind_adjusted_radius(base, latest, plan["spectator_arc_center_deg"])
        if final > plan["spectator_boundary_ft"]:
            err("ERR_FALLOUT_EXCEEDS_BOUNDARY",
                "wind-adjusted fallout radius exceeds the spectator boundary")
        ev["weather_decision"] = "GO"
        ev["final_fallout_radius_ft"] = final
        ev["status"] = "IN_PROGRESS"
        bump(ev)
        return ok(serialize(ev))
    # NO_GO: cancel cascade with WEATHER_NO_GO.
    ev["weather_decision"] = "NO_GO"
    cancel_event(ev, "WEATHER_NO_GO")
    return ok(serialize(ev))

@bp.post("/pyro/displays/<display_id>/complete-show")
def complete_show(display_id):
    uid, _ = require_roles("Operator")
    ev = _get_display(display_id)
    check_display_ownership(ev, uid)
    if ev["status"] != "IN_PROGRESS":
        err("ERR_INVALID_STATE", "event is not IN_PROGRESS")
    check_operator_active(uid)
    ev["status"] = "SHOW_COMPLETE"
    ev["termination_reason"] = "COMPLETED"
    ev["show_completed_at"] = store.clock
    bump(ev)
    return ok(serialize(ev))

@bp.post("/pyro/displays/<display_id>/cancel")
def cancel(display_id):
    uid, _ = require_roles("Operator")
    vals = validate_schema(request.get_json(silent=True),
                           [("reason", "str", False, None)])
    ev = _get_display(display_id)
    check_display_ownership(ev, uid)
    if ev["status"] not in EVENT_CANCELLABLE:
        err("ERR_INVALID_STATE", "event cannot be cancelled from its current state")
    check_operator_active(uid)
    cancel_event(ev, "OPERATOR")
    return ok(serialize(ev))
