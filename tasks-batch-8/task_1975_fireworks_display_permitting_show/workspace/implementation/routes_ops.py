"""Weather readings, security posts, misfires, sweeps, incident reports."""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from auth import require_roles
from db import store, new_record, bump
from errors import err
from response import ok, ok_list, serialize, serialize_list, sort_created
from services import (
    DUD_HALT_MIN, DUD_RATE_LIMIT, EVENT_TERMINAL, SOAK_MINUTES,
    check_display_ownership, check_operator_active, current_site_plan,
    evaluate_auto_close, operator_of_batch, required_guards,
)
from validation import validate_schema, parse_pagination, paginate

bp = Blueprint("ops", __name__)

WEATHER_SOURCES = {"ON_SITE_ANEMOMETER", "NWS"}
SWEEP_TYPES = {"NIGHT_SWEEP", "DAWN_RECHECK"}
VERDICTS = {"VERIFIED", "REJECTED"}
DISPOSAL_METHODS = {"SOAK_CRUSH", "BURN_PIT", "RETURN_TO_SUPPLIER"}
INCIDENT_TYPES = {"INJURY", "FIRE", "PROPERTY_DAMAGE", "DUD_OFFSITE", "CROWD_BREACH"}
SEVERITIES = {"MINOR", "SERIOUS", "CRITICAL"}


def _get_display(display_id):
    ev = store.displays.get(display_id)
    if ev is None:
        err("ERR_NOT_FOUND", f"display {display_id} not found")
    return ev


def _get_crew(uid):
    crew = store.crew_members.get(uid)
    if crew is None:
        err("ERR_NOT_FOUND", f"crew member {uid} not found")
    return crew


def _operator_access(ev, uid):
    """Ownership + suspension for Operator callers on display-scoped writes."""
    check_display_ownership(ev, uid)
    return uid


def _crew_scope_check(ev, uid):
    crew = _get_crew(uid)
    return crew


# ---- Weather readings --------------------------------------------------------

@bp.post("/pyro/displays/<display_id>/weather-readings")
def create_weather_reading(display_id):
    uid, role = require_roles("CrewMember", "Operator")
    vals = validate_schema(request.get_json(silent=True), [
        ("wind_speed_mph", "num", True, None),
        ("gust_mph", "num", True, None),
        ("wind_direction_deg", "int", True, None),
        ("precipitation", "bool", True, None),
        ("source", "enum", True, WEATHER_SOURCES),
    ])
    if vals["wind_speed_mph"] < 0:
        err("ERR_VALIDATION", "wind_speed_mph must be >= 0")
    if vals["gust_mph"] < 0:
        err("ERR_VALIDATION", "gust_mph must be >= 0")
    if not (0 <= vals["wind_direction_deg"] <= 359):
        err("ERR_VALIDATION", "wind_direction_deg must be in [0, 359]")
    ev = _get_display(display_id)
    crew = None
    if role == "Operator":
        check_display_ownership(ev, uid)
    else:
        crew = _get_crew(uid)
    # Crews log weather throughout setup: any non-terminal state accepts a reading.
    if ev["status"] in EVENT_TERMINAL:
        err("ERR_INVALID_STATE", "event is terminal")
    if role == "Operator":
        check_operator_active(uid)
    if crew is not None and crew["operator_id"] != ev["operator_id"]:
        err("ERR_SCOPE_MISMATCH", "crew member does not belong to the event's operator")
    rec = new_record(with_version=False)
    rec.update({
        "display_event_id": ev["id"],
        "wind_speed_mph": vals["wind_speed_mph"].quantize(Decimal("0.1"),
                                                          rounding=ROUND_HALF_UP),
        "gust_mph": vals["gust_mph"].quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
        "wind_direction_deg": vals["wind_direction_deg"],
        "precipitation": vals["precipitation"],
        "source": vals["source"],
        "recorded_by_user_id": uid,
    })
    store.weather_readings[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/pyro/displays/<display_id>/weather-readings")
def list_weather_readings(display_id):
    uid, role = require_roles("Operator", "CrewMember", "FireMarshal")
    ev = _get_display(display_id)
    if role == "Operator":
        check_display_ownership(ev, uid)
    limit, offset = parse_pagination(request.args)
    recs = sort_created([w for w in store.weather_readings.values()
                         if w["display_event_id"] == display_id])
    return ok_list(serialize_list(paginate(recs, limit, offset)), len(recs),
                   limit, offset)


# ---- Security posts ----------------------------------------------------------

@bp.post("/pyro/displays/<display_id>/security-posts")
def create_security_post(display_id):
    uid, _ = require_roles("Operator")
    vals = validate_schema(request.get_json(silent=True), [
        ("post_label", "str", True, None),
        ("arc_degrees", "int", True, None),
        ("radius_ft", "int", True, None),
    ])
    if not (1 <= vals["arc_degrees"] <= 360):
        err("ERR_VALIDATION", "arc_degrees must be in [1, 360]")
    ev = _get_display(display_id)
    check_display_ownership(ev, uid)
    check_operator_active(uid)
    if any(p["display_event_id"] == ev["id"] and p["post_label"] == vals["post_label"]
           for p in store.security_posts.values()):
        err("ERR_VALIDATION", "post_label must be unique within the event")
    plan = current_site_plan(ev)
    if plan is None:
        err("ERR_VALIDATION", "no CURRENT site plan exists to derive the required distance")
    if vals["radius_ft"] < plan["required_spectator_distance_ft"]:
        err("ERR_FALLOUT_EXCEEDS_BOUNDARY",
            "post radius must be >= the current plan's required spectator distance")
    rec = new_record()
    rec.update({
        "display_event_id": ev["id"],
        "post_label": vals["post_label"],
        "arc_degrees": vals["arc_degrees"],
        "radius_ft": vals["radius_ft"],
        "required_guards": required_guards(vals["radius_ft"], vals["arc_degrees"]),
        "assigned_guards": 0,
        "status": "UNSTAFFED",
    })
    store.security_posts[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/pyro/displays/<display_id>/security-posts")
def list_security_posts(display_id):
    uid, role = require_roles("Operator", "FireMarshal")
    ev = _get_display(display_id)
    if role == "Operator":
        check_display_ownership(ev, uid)
    limit, offset = parse_pagination(request.args)
    recs = [p for p in store.security_posts.values() if p["display_event_id"] == display_id]
    status = request.args.get("status")
    if status is not None:
        recs = [p for p in recs if p["status"] == status]
    recs = sort_created(recs)
    return ok_list(serialize_list(paginate(recs, limit, offset)), len(recs),
                   limit, offset)


@bp.post("/pyro/security-posts/<post_id>/assign")
def assign_guard(post_id):
    uid, _ = require_roles("Operator")
    vals = validate_schema(request.get_json(silent=True), [
        ("guard_name", "str", True, None),
        ("guard_company", "str", True, None),
    ])
    post = store.security_posts.get(post_id)
    if post is None:
        err("ERR_NOT_FOUND", f"security post {post_id} not found")
    ev = _get_display(post["display_event_id"])
    check_display_ownership(ev, uid)
    if post["status"] not in ("UNSTAFFED", "STAFFED"):
        err("ERR_INVALID_STATE", "post does not accept guard assignments")
    check_operator_active(uid)
    post["assigned_guards"] += 1
    if post["assigned_guards"] >= post["required_guards"]:
        # Inclusive equality secures (threshold auto-transition).
        post["status"] = "SECURED"
    elif post["status"] == "UNSTAFFED":
        post["status"] = "STAFFED"
    bump(post)
    return ok(serialize(post))


# ---- Misfires ----------------------------------------------------------------

@bp.post("/pyro/displays/<display_id>/misfires")
def create_misfire(display_id):
    uid, role = require_roles("CrewMember", "Operator")
    vals = validate_schema(request.get_json(silent=True), [
        ("product_batch_id", "str", True, None),
        ("shell_description", "str", True, None),
        ("location_note", "str", False, None),
    ])
    ev = _get_display(display_id)
    batch = store.batches.get(vals["product_batch_id"])
    if batch is None:
        err("ERR_NOT_FOUND", f"batch {vals['product_batch_id']} not found")
    crew = None
    if role == "Operator":
        check_display_ownership(ev, uid)
    else:
        crew = _get_crew(uid)
    if role == "Operator":
        check_operator_active(uid)
    if operator_of_batch(batch) != ev["operator_id"]:
        err("ERR_SCOPE_MISMATCH", "batch's operator does not match the event's operator")
    if crew is not None and crew["operator_id"] != ev["operator_id"]:
        err("ERR_SCOPE_MISMATCH", "crew member does not belong to the event's operator")
    rec = new_record()
    rec.update({
        "display_event_id": ev["id"],
        "product_batch_id": batch["id"],
        "shell_description": vals["shell_description"],
        "location_note": vals["location_note"],
        "logged_by_crew_id": uid,
        "soak_until": store.clock + timedelta(minutes=SOAK_MINUTES),
        "disposal_method": None,
        "disposed_at": None,
        "status": "LOGGED",
    })
    store.misfires[rec["id"]] = rec
    ev["dud_count"] += 1
    bump(ev)
    # c_dud_halt_threshold: fired_count is evaluated before this misfire
    # (misfires never change fired_count).
    threshold = max(DUD_HALT_MIN,
                    math.ceil(Decimal(ev["fired_count"]) * DUD_RATE_LIMIT))
    if ev["dud_count"] >= threshold and ev["status"] == "IN_PROGRESS":
        ev["status"] = "SHOW_COMPLETE"
        ev["termination_reason"] = "DUD_HALT"
        ev["show_completed_at"] = store.clock
        bump(ev)
    return ok(serialize(rec), 201)


@bp.get("/pyro/displays/<display_id>/misfires")
def list_misfires_of_display(display_id):
    uid, role = require_roles("Operator", "FireMarshal", "CrewMember")
    ev = _get_display(display_id)
    if role == "Operator":
        check_display_ownership(ev, uid)
    limit, offset = parse_pagination(request.args)
    recs = [m for m in store.misfires.values() if m["display_event_id"] == display_id]
    status = request.args.get("status")
    if status is not None:
        recs = [m for m in recs if m["status"] == status]
    recs = sort_created(recs)
    return ok_list(serialize_list(paginate(recs, limit, offset)), len(recs),
                   limit, offset)


@bp.get("/pyro/batches/<batch_id>/misfires")
def list_misfires_of_batch(batch_id):
    uid, role = require_roles("Operator", "FireMarshal")
    batch = store.batches.get(batch_id)
    if batch is None:
        err("ERR_NOT_FOUND", f"batch {batch_id} not found")
    if role == "Operator" and operator_of_batch(batch) != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", "batch belongs to another operator")
    limit, offset = parse_pagination(request.args)
    recs = sort_created([m for m in store.misfires.values()
                         if m["product_batch_id"] == batch_id])
    return ok_list(serialize_list(paginate(recs, limit, offset)), len(recs),
                   limit, offset)


@bp.post("/pyro/misfires/<misfire_id>/dispose")
def dispose_misfire(misfire_id):
    uid, _ = require_roles("Operator")
    vals = validate_schema(request.get_json(silent=True),
                           [("disposal_method", "enum", True, DISPOSAL_METHODS)])
    rec = store.misfires.get(misfire_id)
    if rec is None:
        err("ERR_NOT_FOUND", f"misfire {misfire_id} not found")
    ev = _get_display(rec["display_event_id"])
    check_display_ownership(ev, uid)
    if rec["status"] != "LOGGED":
        err("ERR_INVALID_STATE", "misfire is not LOGGED")
    if ev["status"] not in ("SHOW_COMPLETE", "SWEEP_VERIFIED"):
        err("ERR_INVALID_STATE", "disposal requires the event to be SHOW_COMPLETE or SWEEP_VERIFIED")
    check_operator_active(uid)
    # Disposal allowed at or after soak_until, inclusive.
    if store.clock < rec["soak_until"]:
        err("ERR_SOAK_INCOMPLETE", "soak period has not elapsed")
    rec["disposal_method"] = vals["disposal_method"]
    rec["disposed_at"] = store.clock
    rec["status"] = "DISPOSED"
    bump(rec)
    return ok(serialize(rec))


# ---- Sweeps ------------------------------------------------------------------

@bp.post("/pyro/displays/<display_id>/sweeps")
def create_sweep(display_id):
    uid, _ = require_roles("CrewMember")
    vals = validate_schema(request.get_json(silent=True), [
        ("sweep_type", "enum", True, SWEEP_TYPES),
        ("area_clear", "bool", True, None),
        ("notes", "str", False, None),
    ])
    ev = _get_display(display_id)
    crew = _get_crew(uid)
    if ev["status"] != "SHOW_COMPLETE":
        err("ERR_INVALID_STATE", "sweeps are recorded after the show is complete")
    if crew["operator_id"] != ev["operator_id"]:
        err("ERR_SCOPE_MISMATCH", "crew member does not belong to the event's operator")
    # Reconciliation gate: every dud must be disposed before a sweep.
    if any(m["display_event_id"] == ev["id"] and m["status"] == "LOGGED"
           for m in store.misfires.values()):
        err("ERR_SWEEP_RECONCILE_FAILED", "misfires of the event are still LOGGED")
    rec = new_record()
    rec.update({
        "display_event_id": ev["id"],
        "sweep_type": vals["sweep_type"],
        "area_clear": vals["area_clear"],
        "notes": vals["notes"],
        "swept_by_crew_id": uid,
        "verified_by_user_id": None,
        "verdict": "PENDING",
    })
    store.sweeps[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/pyro/displays/<display_id>/sweeps")
def list_sweeps(display_id):
    uid, role = require_roles("Operator", "FireMarshal", "CrewMember")
    ev = _get_display(display_id)
    if role == "Operator":
        check_display_ownership(ev, uid)
    limit, offset = parse_pagination(request.args)
    recs = sort_created([s for s in store.sweeps.values()
                         if s["display_event_id"] == display_id])
    return ok_list(serialize_list(paginate(recs, limit, offset)), len(recs),
                   limit, offset)


@bp.post("/pyro/sweeps/<sweep_id>/verify")
def verify_sweep(sweep_id):
    uid, _ = require_roles("FireMarshal")
    vals = validate_schema(request.get_json(silent=True), [
        ("verdict", "enum", True, VERDICTS),
        ("note", "str", False, None),
    ])
    sweep = store.sweeps.get(sweep_id)
    if sweep is None:
        err("ERR_NOT_FOUND", f"sweep {sweep_id} not found")
    if sweep["verdict"] != "PENDING":
        err("ERR_INVALID_STATE", "sweep is not PENDING")
    ev = _get_display(sweep["display_event_id"])
    sweep["verdict"] = vals["verdict"]
    if vals["verdict"] == "VERIFIED":
        sweep["verified_by_user_id"] = uid
    bump(sweep)
    if vals["verdict"] == "VERIFIED":
        for p in store.security_posts.values():
            if p["display_event_id"] == ev["id"] and p["status"] in (
                    "UNSTAFFED", "STAFFED", "SECURED"):
                p["status"] = "RELEASED"
                bump(p)
        if ev["status"] == "SHOW_COMPLETE":
            ev["status"] = "SWEEP_VERIFIED"
            bump(ev)
        evaluate_auto_close(ev)
    # REJECTED: event stays SHOW_COMPLETE; a fresh sweep may be recorded.
    return ok(serialize(sweep))


# ---- Incident reports ----------------------------------------------------------

@bp.post("/pyro/displays/<display_id>/incidents")
def create_incident(display_id):
    uid, role = require_roles("Operator", "CrewMember", "FireMarshal")
    vals = validate_schema(request.get_json(silent=True), [
        ("incident_type", "enum", True, INCIDENT_TYPES),
        ("severity", "enum", True, SEVERITIES),
        ("description", "str", True, None),
    ])
    ev = _get_display(display_id)
    crew = None
    if role == "Operator":
        check_display_ownership(ev, uid)
        check_operator_active(uid)
    elif role == "CrewMember":
        crew = _get_crew(uid)
    if crew is not None and crew["operator_id"] != ev["operator_id"]:
        err("ERR_SCOPE_MISMATCH", "crew member does not belong to the event's operator")
    rec = new_record()
    rec.update({
        "display_event_id": ev["id"],
        "incident_type": vals["incident_type"],
        "severity": vals["severity"],
        "description": vals["description"],
        "reported_by_user_id": uid,
        "reported_by_role": role,
        "resolution_note": None,
        "closed_by_user_id": None,
        "status": "FILED",
    })
    store.incidents[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/pyro/displays/<display_id>/incidents")
def list_incidents(display_id):
    uid, role = require_roles("Operator", "FireMarshal", "CrewMember")
    ev = _get_display(display_id)
    if role == "Operator":
        check_display_ownership(ev, uid)
    limit, offset = parse_pagination(request.args)
    recs = [i for i in store.incidents.values() if i["display_event_id"] == display_id]
    status = request.args.get("status")
    if status is not None:
        recs = [i for i in recs if i["status"] == status]
    recs = sort_created(recs)
    return ok_list(serialize_list(paginate(recs, limit, offset)), len(recs),
                   limit, offset)


@bp.post("/pyro/incidents/<incident_id>/close")
def close_incident(incident_id):
    uid, _ = require_roles("FireMarshal")
    vals = validate_schema(request.get_json(silent=True),
                           [("resolution_note", "str", True, None)])
    rec = store.incidents.get(incident_id)
    if rec is None:
        err("ERR_NOT_FOUND", f"incident {incident_id} not found")
    if rec["status"] != "FILED":
        err("ERR_INVALID_STATE", "incident is not FILED")
    # Segregation of duties: the closer must not be the reporter.
    if uid == rec["reported_by_user_id"]:
        err("ERR_SOD_VIOLATION", "incident closer must differ from the reporter")
    rec["status"] = "CLOSED"
    rec["resolution_note"] = vals["resolution_note"]
    rec["closed_by_user_id"] = uid
    bump(rec)
    ev = store.displays.get(rec["display_event_id"])
    if ev is not None:
        evaluate_auto_close(ev)
    return ok(serialize(rec))
