"""Housing sites: CRUD + season lifecycle + compliance summary."""

from flask import Blueprint

import clock
import db
from errors import err
from middleware import require_roles, get_auth, ALL_ROLES
from response import success_object, success_list
from services import core
from validate import (
    get_body, require_string, require_enum, parse_pagination, get_filter,
    sort_and_paginate,
)

bp = Blueprint("sites", __name__)

ALL_GET = tuple(sorted(ALL_ROLES))

SITE_STATUSES = {"DRAFT", "OPENING", "OPEN", "CLOSING", "CLOSED"}


def _view(site):
    return {
        "id": site["id"],
        "name": site["name"],
        "state_code": site["state_code"],
        "status": site["status"],
        "compliance_posture": site["compliance_posture"],
        "created_at": site["created_at"],
        "updated_at": site["updated_at"],
        "version": site["version"],
    }


@bp.route("/housing-sites", methods=["POST"])
def create_site():
    require_roles("OperatorAdmin")
    body = get_body()
    name = require_string(body, "name")
    state_code = require_string(body, "state_code")
    if len(state_code) != 2 or not state_code.isalpha() or not state_code.isupper():
        raise err("ERR_INVALID_REQUEST", "state_code must be two uppercase letters")
    now = db.now_ts()
    site = {
        "id": db.new_id(),
        "name": name,
        "state_code": state_code,
        "status": "DRAFT",
        "compliance_posture": "NORMAL",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.sites[site["id"]] = site
    return success_object(_view(site), status=201)


@bp.route("/housing-sites", methods=["GET"])
def list_sites():
    get_auth()
    limit, offset = parse_pagination()
    items = list(db.sites.values())
    status_f = get_filter("status")
    posture_f = get_filter("compliance_posture")
    if status_f is not None:
        items = [s for s in items if s["status"] == status_f]
    if posture_f is not None:
        items = [s for s in items if s["compliance_posture"] == posture_f]
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([_view(s) for s in page], total, limit, offset)


@bp.route("/housing-sites/<sid>", methods=["GET"])
def get_site(sid):
    get_auth()
    site = db.sites.get(sid)
    if site is None:
        raise err("ERR_SITE_NOT_FOUND")
    return success_object(_view(site))


@bp.route("/housing-sites/<sid>/compliance-summary", methods=["GET"])
def compliance_summary(sid):
    get_auth()
    site = db.sites.get(sid)
    if site is None:
        raise err("ERR_SITE_NOT_FOUND")
    return success_object(core.compute_compliance_summary(sid))


@bp.route("/housing-sites/<sid>", methods=["PUT"])
def drive_site(sid):
    require_roles("OperatorAdmin")
    body = get_body()
    target = require_enum(body, "status", SITE_STATUSES)
    site = db.sites.get(sid)
    if site is None:
        raise err("ERR_SITE_NOT_FOUND")
    current = site["status"]
    clock_date = clock.current_date()

    # State machine from-state validity (priority 7).
    allowed = {
        "DRAFT": {"OPENING"},
        "OPENING": {"DRAFT", "OPEN"},
        "OPEN": {"CLOSING"},
        "CLOSING": {"CLOSED"},
        "CLOSED": {"OPENING"},
    }
    if target not in allowed.get(current, set()):
        raise err("ERR_INVALID_STATE", f"Cannot move site from {current} to {target}")

    if target == "OPENING":
        # Requires a PLANNED window covering the clock date.
        covering = None
        for w in db.season_windows.values():
            if w["site_id"] == sid and w["status"] == "PLANNED":
                if clock.parse_date(w["planned_open_date"]) <= clock_date <= clock.parse_date(w["planned_close_date"]):
                    covering = w
                    break
        if covering is None:
            raise err("ERR_NO_COVERING_SEASON_WINDOW")

    elif target == "OPEN":
        # Requires at least one CERTIFIED unit.
        has_certified = any(u["status"] == "CERTIFIED" for u in core.units_of_site(sid))
        if not has_certified:
            raise err("ERR_NO_CERTIFIED_UNIT")

    elif target == "CLOSED":
        # Three preconditions in order.
        for t in core.tenancies_of_site(sid):
            if t["status"] in ("ACTIVE", "NOTICE"):
                raise err("ERR_ACTIVE_TENANCIES_REMAIN")
        for w in core.work_orders_of_site(sid):
            if w["status"] in core.OPEN_WORK_ORDER_STATUSES:
                raise err("ERR_OPEN_WORK_ORDERS_REMAIN")
        active_window = None
        for w in db.season_windows.values():
            if w["site_id"] == sid and w["status"] == "ACTIVE":
                active_window = w
                break
        if active_window is not None:
            win_open = clock.parse_date(active_window["planned_open_date"])
            win_close = clock.parse_date(active_window["planned_close_date"])
            for u in core.units_of_site(sid):
                if u["status"] in ("CERTIFIED", "OCCUPIED", "HABITABILITY_HOLD"):
                    has_treatment = False
                    for p in core.pest_treatments_of_unit(u["id"]):
                        if p["status"] in ("APPLIED", "CLEARED") and p.get("applied_date"):
                            ad = clock.parse_date(p["applied_date"])
                            if win_open <= ad <= win_close:
                                has_treatment = True
                                break
                    if not has_treatment:
                        raise err("ERR_SEASON_PEST_TREATMENT_MISSING")

    # Apply transition + side effects.
    site["status"] = target
    site["updated_at"] = db.now_ts()
    site["version"] += 1

    if target == "OPEN":
        # Covering PLANNED window -> ACTIVE.
        for w in db.season_windows.values():
            if w["site_id"] == sid and w["status"] == "PLANNED":
                if clock.parse_date(w["planned_open_date"]) <= clock_date <= clock.parse_date(w["planned_close_date"]):
                    w["status"] = "ACTIVE"
                    w["updated_at"] = db.now_ts()
                    break

    if target == "CLOSED":
        # ACTIVE window -> COMPLETED.
        for w in db.season_windows.values():
            if w["site_id"] == sid and w["status"] == "ACTIVE":
                w["status"] = "COMPLETED"
                w["updated_at"] = db.now_ts()
        # Certification expiry sweep.
        affected = core.sweep_all_certs()
        for unit_id in affected:
            unit = db.units.get(unit_id)
            if unit and unit["status"] == "CERTIFIED":
                if not core.unit_has_valid_certification(unit_id):
                    unit["status"] = "REGISTERED"
                    unit["updated_at"] = db.now_ts()
        core.recompute_site_posture(sid)

    core.recompute_site_posture(sid)
    return success_object(_view(site))
