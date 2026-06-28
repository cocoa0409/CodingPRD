"""PrenatalVisit routes: schedule, complete (risk loop), no-show, cancel."""
from flask import Blueprint, request

from db import db
from common import (stamp_new, touch, public, get_body,
                    require_string, require_int, require_enum, require_datetime,
                    parse_dt)
from errors import err, ERR_INVALID_STATE
from middleware import require_auth, require_role, ALL_ROLES
from response import object_response
import lookup
from services import calc

bp = Blueprint("visits", __name__)


@bp.route("/birth-center/prenatal-visits", methods=["POST"])
def schedule_visit():
    _, role = require_auth()
    require_role(role, ["IntakeCoordinator", "Midwife"])
    body = get_body()
    episode_id = require_string(body, "episode_id")
    visit_kind = require_enum(body, "visit_kind", {"PRENATAL", "POSTPARTUM", "LACTATION"})
    scheduled_at = require_datetime(body, "scheduled_at")
    lookup.get_episode(episode_id)
    rec = {
        "episode_id": episode_id,
        "visit_kind": visit_kind,
        "scheduled_at": scheduled_at,
        "status": "SCHEDULED",
        "blood_pressure_systolic": None,
        "risk_flag": None,
    }
    stamp_new(rec)
    db.prenatal_visits[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.route("/birth-center/prenatal-visits/<vid>", methods=["GET"])
def get_visit(vid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    rec = lookup.get_visit(vid)
    return object_response(public(rec), 200)


@bp.route("/birth-center/prenatal-visits/<vid>/complete", methods=["POST"])
def complete_visit(vid):
    _, role = require_auth()
    require_role(role, ["Midwife"])
    rec = lookup.get_visit(vid)
    body = get_body()
    # well-formedness (priority 4): risk_flag required; bp optional
    risk_flag = require_enum(body, "risk_flag", {"NONE", "WATCH", "TRANSFER"})
    bp_sys = require_int(body, "blood_pressure_systolic", required=False, default=None)
    # state check (priority 6)
    if rec["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Visit is not SCHEDULED")
    episode = db.episodes.get(rec["episode_id"])
    if episode is not None and episode["clinical_status"] in ("TRANSFERRED", "COMPLETED"):
        raise err(ERR_INVALID_STATE, "Episode is closed; cannot complete visit")

    rec["status"] = "COMPLETED"
    rec["risk_flag"] = risk_flag
    rec["blood_pressure_systolic"] = bp_sys
    touch(rec)

    if episode is not None:
        # re-derive risk_tier and prenatal_visits_completed; bump episode version.
        calc.rederive_risk_tier(episode)
        episode["prenatal_visits_completed"] = calc.completed_visit_count(episode)
        touch(episode)

    return object_response(public(rec), 200)


@bp.route("/birth-center/prenatal-visits/<vid>/mark-no-show", methods=["POST"])
def mark_no_show(vid):
    _, role = require_auth()
    require_role(role, ["Midwife"])
    rec = lookup.get_visit(vid)
    if rec["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Visit is not SCHEDULED")
    # requires logical clock >= scheduled_at
    if db.logical_clock < parse_dt(rec["scheduled_at"], "scheduled_at"):
        raise err(ERR_INVALID_STATE, "Visit is not yet past due")
    rec["status"] = "NO_SHOW"
    touch(rec)
    return object_response(public(rec), 200)


@bp.route("/birth-center/prenatal-visits/<vid>/cancel", methods=["POST"])
def cancel_visit(vid):
    _, role = require_auth()
    require_role(role, ["IntakeCoordinator", "Midwife"])
    rec = lookup.get_visit(vid)
    if rec["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Visit is not SCHEDULED")
    rec["status"] = "CANCELLED"
    touch(rec)
    return object_response(public(rec), 200)
