"""The guard workforce: training, equipment, certification and duty (PRD 3.4)."""
from flask import Blueprint

import calc
import domain
import validate as v
from auth import require
from db import base_entity, db, now, touch
from errors import bad_request, fail
from response import object_response
from timeutil import fmt_date, fmt_dt

bp = Blueprint("guards", __name__)

ITEM_TYPES = ("HIGH_VIS_VEST", "STOP_PADDLE", "WHISTLE")
DUTY_ACTIONS = ("ON_LEAVE", "RETURN")
CERTIFIABLE_STATUSES = ("IN_TRAINING", "CERTIFIED", "SUSPENDED")
INITIAL_TRAINING_HOURS = calc.Decimal("12.0")
REFRESHER_HOURS = calc.Decimal("4.0")


@bp.post("/srts/guards")
def enroll_guard():
    require("CrossingSupervisor", "ProgramAdmin")
    body = v.body()
    full_name = v.req_str(body, "full_name")
    home_zone_code = v.req_str(body, "home_zone_code")
    hire_date = v.req_date(body, "hire_date")
    optin = v.opt_bool(body, "substitute_pool_optin", default=True)

    guard = base_entity()
    guard.update({
        "full_name": full_name,
        "home_zone_code": home_zone_code,
        "hire_date": fmt_date(hire_date),
        "substitute_pool_optin": optin,
        "certification_status": "APPLICANT",
        "duty_status": "UNASSIGNED",
        "training_hours_completed": 0,
        "hours_since_last_certification": 0,
        "certified_on": None,
        "certification_expires_on": None,
        "equipment_issued": [],
        "equipment_complete": False,
        "reliability_score_rolling_90d": 100.00,
        "reliability_score_season_to_date": 100.00,
        "suspension_reason": None,
    })
    db.guards[guard["id"]] = guard
    return object_response(guard, 201)


@bp.get("/srts/guards/<guard_id>")
def read_guard(guard_id):
    require("ProgramAdmin", "CrossingSupervisor", "CrossingGuard")
    guard = domain.get_guard(guard_id)
    # The rolling figure is anchored on the logical clock, so it is re-evaluated
    # on every read (PRD 3.4).  A read is not a mutation: no version bump.
    domain.refresh_reliability(guard, rolling=True, season=True)
    return object_response(guard)


@bp.post("/srts/guards/<guard_id>/training")
def record_training(guard_id):
    require("CrossingSupervisor", "ProgramAdmin")
    body = v.body()
    training_date = v.req_date(body, "training_date")
    hours = v.req_num(body, "hours", exclusive_min=0)
    curriculum_code = v.req_str(body, "curriculum_code")
    guard = domain.get_guard(guard_id)

    guard["training_hours_completed"] = float(
        calc.dec(guard["training_hours_completed"]) + hours)
    guard["hours_since_last_certification"] = float(
        calc.dec(guard["hours_since_last_certification"]) + hours)
    # Training entries themselves are not a declared ledger on the Guard; only
    # the two hour counters are persisted.
    if guard["certification_status"] == "APPLICANT":
        guard["certification_status"] = "IN_TRAINING"
    domain.refresh_reliability(guard)
    touch(guard)
    return object_response(guard)


@bp.post("/srts/guards/<guard_id>/equipment")
def issue_equipment(guard_id):
    require("CrossingSupervisor", "ProgramAdmin")
    body = v.body()
    item_type = v.req_enum(body, "item_type", ITEM_TYPES)
    issued_on = v.req_date(body, "issued_on")
    guard = domain.get_guard(guard_id)

    guard["equipment_issued"].append({
        "item_type": item_type,
        "issued_on": fmt_date(issued_on),
        "recorded_at": fmt_dt(now()),
    })
    held = set(entry["item_type"] for entry in guard["equipment_issued"])
    guard["equipment_complete"] = all(item in held for item in ITEM_TYPES)
    touch(guard)
    return object_response(guard)


@bp.post("/srts/guards/<guard_id>/certify")
def certify_guard(guard_id):
    require("CrossingSupervisor")
    body = v.body()
    certified_on = v.req_date(body, "certified_on")
    expires_on = v.req_date(body, "certification_expires_on")
    if expires_on <= certified_on:
        bad_request("certification_expires_on must be strictly later than certified_on.")
    guard = domain.get_guard(guard_id)

    status = guard["certification_status"]
    if status not in CERTIFIABLE_STATUSES:
        fail("ERR_GUARD_NOT_IN_TRAINING",
             "An APPLICANT has no training on record and cannot be certified.")

    if status == "SUSPENDED":
        domain.refresh_reliability(guard, rolling=True, season=False)
        if calc.dec(guard["reliability_score_rolling_90d"]) < calc.RELIABILITY_FLOOR:
            fail("ERR_RELIABILITY_TOO_LOW",
                 "Reinstatement requires reliability_score_rolling_90d of at least 75.00.")
    elif status == "IN_TRAINING":
        if calc.dec(guard["training_hours_completed"]) < INITIAL_TRAINING_HOURS:
            fail("ERR_TRAINING_HOURS_INSUFFICIENT",
                 "Initial certification requires at least 12.0 training hours.")
    else:
        if calc.dec(guard["hours_since_last_certification"]) < REFRESHER_HOURS:
            fail("ERR_TRAINING_HOURS_INSUFFICIENT",
                 "Recertification requires at least 4.0 refresher hours.")

    if not guard["equipment_complete"]:
        fail("ERR_GUARD_EQUIPMENT_INCOMPLETE",
             "All three required equipment items must be issued first.")

    guard["certification_status"] = "CERTIFIED"
    guard["certified_on"] = fmt_date(certified_on)
    guard["certification_expires_on"] = fmt_date(expires_on)
    guard["hours_since_last_certification"] = 0
    guard["suspension_reason"] = None
    touch(guard)
    return object_response(guard)


@bp.post("/srts/guards/<guard_id>/duty-status")
def move_duty_status(guard_id):
    require("CrossingSupervisor")
    body = v.body()
    duty_action = v.req_enum(body, "duty_action", DUTY_ACTIONS)
    guard = domain.get_guard(guard_id)

    current = guard["duty_status"]
    if duty_action == "ON_LEAVE":
        if current not in ("UNASSIGNED", "ASSIGNED"):
            fail("ERR_INVALID_DUTY_ACTION",
                 "ON_LEAVE is only available from UNASSIGNED or ASSIGNED.")
        guard["duty_status"] = "ON_LEAVE"
    else:
        if current != "ON_LEAVE":
            fail("ERR_INVALID_DUTY_ACTION", "RETURN is only available from ON_LEAVE.")
        guard["duty_status"] = ("ASSIGNED" if domain.live_assignments_of_guard(guard)
                               else "UNASSIGNED")
    touch(guard)
    return object_response(guard)
