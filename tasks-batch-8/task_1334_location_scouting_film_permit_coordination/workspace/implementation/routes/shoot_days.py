"""ShootDay endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import *
from db import store
from services.helpers import (
    require_fields, require_str, require_int,
    make_entity, touch, get_production, get_location, get_scoped,
    list_filtered, paginate, get_pagination_params, parse_date,
    find_verified_cert_covering_date, recompute_monitors_confirmed,
    recompute_compliance, shut_down_shoot_day, cancel_shoot_day_monitors,
    get_jurisdiction,
)
from services.calculations import monitors_required as calc_monitors_required

bp = Blueprint("shoot_days", __name__)


def _get_monitors_required(permit_app, production, jurisdiction):
    return calc_monitors_required(
        permit_app["shoot_hours_per_day"],
        permit_app["closed_lanes"],
        production["cast_size"],
        jurisdiction["police_monitor_lane_threshold"],
        jurisdiction["large_cast_threshold"],
    )


def _has_police_monitor_confirmed(shoot_day_id):
    """Check if at least one CONFIRMED POLICE monitor exists for this day."""
    for ma in store.monitor_assignments.values():
        if (ma.get("shoot_day_id") == shoot_day_id
                and ma["status"] == "CONFIRMED"
                and ma.get("monitor_type") == "POLICE"):
            return True
    return False


@bp.route("/productions/<pid>/shoot-days", methods=["POST"])
def create_shoot_day(pid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["permit_application_id", "location_id", "shoot_date", "planned_hours"])
    pa_id = require_str(payload, "permit_application_id")
    pa = store.permit_applications.get(pa_id)
    if not pa or pa.get("production_id") != pid:
        raise ApiError(ERR_NOT_FOUND, "PermitApplication not found", 404)
    # Terminal permit check
    if pa["status"] in ("DENIED", "SUPERSEDED", "EXPIRED", "WITHDRAWN"):
        raise ApiError(ERR_PERMIT_NOT_ISSUED, "Permit is in a terminal state", 422)
    loc_id = require_str(payload, "location_id")
    loc = get_location(loc_id)
    planned_hours = require_int(payload, "planned_hours")
    if planned_hours > loc["max_shoot_hours_per_day"]:
        raise ApiError(ERR_HOURS_EXCEED_LOCATION_CAP, "Planned hours exceed location cap", 422)
    # shoot_date within permit window
    shoot_date = parse_date(require_str(payload, "shoot_date"), "shoot_date")
    pa_start = parse_date(pa["shoot_start_date"])
    pa_end = parse_date(pa["shoot_end_date"])
    if not (pa_start <= shoot_date <= pa_end):
        raise ApiError(ERR_INVALID_REQUEST, "shoot_date outside permit window", 400)
    # Insurance lapsed check: if cert for this permit's jurisdiction has LAPSED
    # and the permit window is not fully past, block creation
    jurisdiction = get_jurisdiction(pa["jurisdiction_id"])
    has_lapsed_blocking = False
    for cert in store.insurance_certificates.values():
        if (cert.get("production_id") == pid
                and cert.get("jurisdiction_id") == pa["jurisdiction_id"]
                and cert["status"] == "LAPSED"):
            # Check if permit window is not fully in the past
            today = store.clock.now_date()
            if pa_end >= today:
                # Check if there is no other VERIFIED cert
                cert_covering = find_verified_cert_covering_date(pid, pa["jurisdiction_id"], shoot_date)
                if not cert_covering:
                    has_lapsed_blocking = True
    if has_lapsed_blocking:
        raise ApiError(ERR_INSURANCE_INSUFFICIENT,
                       "Certificate lapsed; new shoot days blocked until fresh coverage verified", 422)
    mon_req = _get_monitors_required(pa, p, jurisdiction)
    entity = make_entity({
        "production_id": pid,
        "permit_application_id": pa_id,
        "location_id": loc_id,
        "shoot_date": payload["shoot_date"],
        "planned_hours": planned_hours,
        "actual_hours": None,
        "overtime_minutes": 0,
        "monitors_required": mon_req,
        "monitors_confirmed": 0,
        "compliance_status": "COMPLIANT",
        "status": "PLANNED",
    })
    store.shoot_days[entity["id"]] = entity
    return success_object(entity, 201)


@bp.route("/productions/<pid>/shoot-days", methods=["GET"])
def list_shoot_days(pid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    limit, offset = get_pagination_params(request.args)
    filters = {}
    for f in ("permit_application_id", "location_id", "status"):
        v = request.args.get(f)
        if v:
            filters[f] = v
    items = list_filtered(store.shoot_days, filters, production_id=pid)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/productions/<pid>/shoot-days/<rid>", methods=["GET"])
def get_shoot_day_nested(pid, rid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    sd = get_scoped(store.shoot_days, rid, pid, "ShootDay")
    return success_object(sd)


@bp.route("/productions/<pid>/shoot-days/<rid>/mark-ready", methods=["POST"])
def mark_ready(pid, rid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    sd = get_scoped(store.shoot_days, rid, pid, "ShootDay")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["expected_shoot_day_version"])
    expected_version = require_int(payload, "expected_shoot_day_version")
    if expected_version != sd["version"]:
        raise ApiError(ERR_STALE_VERSION, "ShootDay version mismatch", 412)
    if sd["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, "ShootDay must be PLANNED to mark ready", 409)
    # Gate checks in order
    pa = store.permit_applications.get(sd["permit_application_id"])
    if not pa or pa["status"] != "ISSUED":
        raise ApiError(ERR_PERMIT_NOT_ISSUED, "Backing permit is not ISSUED", 422)
    # Notification ACKED
    has_acked = any(
        n.get("permit_application_id") == pa["id"] and n["status"] == "ACKED"
        for n in store.notification_records.values()
    )
    if not has_acked:
        raise ApiError(ERR_NOTIFICATION_DEFICIENT, "No ACKED notification for permit", 422)
    # VERIFIED cert covering shoot_date
    shoot_date = parse_date(sd["shoot_date"])
    cert = find_verified_cert_covering_date(pid, pa["jurisdiction_id"], shoot_date)
    if not cert:
        raise ApiError(ERR_INSURANCE_INSUFFICIENT, "No VERIFIED certificate covers shoot date", 422)
    # Deposit FUNDED
    loc_id = sd["location_id"]
    da_funded = False
    for da in store.deposit_accounts.values():
        if (da.get("production_id") == pid
                and da.get("location_id") == loc_id
                and da["status"] == "FUNDED"):
            da_funded = True
            break
    if not da_funded:
        raise ApiError(ERR_DEPOSIT_NOT_FUNDED, "Deposit account is not FUNDED", 422)
    # SIGNED PRE walkthrough
    has_pre = any(
        wt.get("production_id") == pid
        and wt.get("location_id") == loc_id
        and wt.get("kind") == "PRE"
        and wt["status"] in ("SIGNED", "FINAL")
        for wt in store.walkthrough_reports.values()
    )
    if not has_pre:
        raise ApiError(ERR_PRE_WALKTHROUGH_MISSING, "No SIGNED PRE walkthrough for location", 422)
    # Monitor coverage
    recompute_monitors_confirmed(sd)
    if sd.get("monitors_confirmed", 0) < sd.get("monitors_required", 0):
        raise ApiError(ERR_MONITOR_SHORTFALL, "Confirmed monitors below required", 422)
    # Police monitor requirement
    jurisdiction = get_jurisdiction(pa["jurisdiction_id"])
    if pa["closed_lanes"] >= jurisdiction["police_monitor_lane_threshold"]:
        if not _has_police_monitor_confirmed(sd["id"]):
            raise ApiError(ERR_MONITOR_SHORTFALL, "POLICE monitor required but not confirmed", 422)
    # StreetClosure requirement when closed_lanes > 0
    if pa["closed_lanes"] > 0:
        has_approved_closure = any(
            sc.get("permit_application_id") == pa["id"]
            and sc["status"] == "APPROVED"
            for sc in store.street_closures.values()
        )
        if not has_approved_closure:
            raise ApiError(ERR_CLOSURE_MISSING, "No APPROVED street closure for this permit", 422)
    sd["status"] = "READY"
    touch(sd)
    # Production PREP -> ACTIVE
    if p["status"] == "PREP":
        p["status"] = "ACTIVE"
        touch(p)
    return success_object(sd)


@bp.route("/productions/<pid>/shoot-days/<rid>/complete", methods=["POST"])
def complete_shoot_day(pid, rid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    sd = get_scoped(store.shoot_days, rid, pid, "ShootDay")
    if sd["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, "ShootDay must be IN_PROGRESS to complete", 409)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["actual_hours"])
    actual_hours = require_int(payload, "actual_hours")
    loc = get_location(sd["location_id"])
    if actual_hours > loc["max_shoot_hours_per_day"]:
        raise ApiError(ERR_HOURS_EXCEED_LOCATION_CAP, "Actual hours exceed location cap", 422)
    sd["actual_hours"] = actual_hours
    sd["overtime_minutes"] = max(0, actual_hours - sd["planned_hours"]) * 60
    sd["status"] = "COMPLETED"
    # Sweep unchecked CONFIRMED monitors to NO_SHOW
    for ma in store.monitor_assignments.values():
        if (ma.get("shoot_day_id") == sd["id"]
                and ma["status"] == "CONFIRMED"
                and not ma.get("checked_in")):
            ma["status"] = "NO_SHOW"
            touch(ma)
    recompute_monitors_confirmed(sd)
    recompute_compliance(sd)
    touch(sd)
    return success_object(sd)


@bp.route("/productions/<pid>/shoot-days/<rid>/cancel", methods=["POST"])
def cancel_shoot_day_endpoint(pid, rid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    sd = get_scoped(store.shoot_days, rid, pid, "ShootDay")
    if sd["status"] not in ("PLANNED", "READY"):
        raise ApiError(ERR_INVALID_STATE, "Can only cancel PLANNED or READY shoot days", 409)
    sd["status"] = "CANCELLED"
    touch(sd)
    cancel_shoot_day_monitors(sd)
    return success_object(sd)


@bp.route("/productions/<pid>/shoot-days/<rid>/shut-down", methods=["POST"])
def shut_down_shoot_day_endpoint(pid, rid):
    user_id, role = require_role("FilmOffice")
    p = get_production(pid)
    sd = get_scoped(store.shoot_days, rid, pid, "ShootDay")
    if sd["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, "ShootDay must be IN_PROGRESS to shut down", 409)
    shut_down_shoot_day(sd)
    return success_object(sd)
