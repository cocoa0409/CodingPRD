"""PermitApplication endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import *
from db import store
from services.helpers import (
    require_fields, require_str, require_int, optional_int, optional_str,
    make_entity, touch, get_production, get_location, get_scoped,
    list_filtered, paginate, get_pagination_params, parse_date,
    find_verified_cert_covering, get_jurisdiction,
)
from services.calculations import (
    business_days_between, business_days_in_window, calendar_days_in_window,
    permit_fee as calc_permit_fee,
)

bp = Blueprint("permit_applications", __name__)


def _check_executed_agreement_covers(production_id, location_id, shoot_start, shoot_end):
    """Check an EXECUTED OwnerAgreement covers [shoot_start, shoot_end] for (production, location)."""
    for oa in store.owner_agreements.values():
        if (oa.get("production_id") == production_id
                and oa.get("location_id") == location_id
                and oa["status"] == "EXECUTED"):
            oa_start = parse_date(oa["shoot_start_date"])
            oa_end = parse_date(oa["shoot_end_date"])
            if oa_start <= shoot_start and oa_end >= shoot_end:
                return True
    return False


def _has_acknowledged_notification(permit_application_id):
    """Check if an ACKED NotificationRecord exists for this permit application."""
    for n in store.notification_records.values():
        if n.get("permit_application_id") == permit_application_id and n["status"] == "ACKED":
            return True
    return False


@bp.route("/productions/<pid>/permit-applications", methods=["POST"])
def create_permit_application(pid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["location_id", "shoot_start_date", "shoot_end_date",
                             "shoot_hours_per_day", "expected_production_version"])
    # OCC check
    expected_version = require_int(payload, "expected_production_version")
    if expected_version != p["version"]:
        raise ApiError(ERR_STALE_VERSION, "Production version mismatch", 412)
    loc_id = require_str(payload, "location_id")
    loc = get_location(loc_id)
    shoot_hours = require_int(payload, "shoot_hours_per_day")
    closed_lanes = optional_int(payload, "closed_lanes", 0)
    amendment_of_id = optional_str(payload, "amendment_of_id")

    # Handle amendment supersede
    if amendment_of_id:
        old_app = store.permit_applications.get(amendment_of_id)
        if not old_app:
            raise ApiError(ERR_NOT_FOUND, "Amendment target not found", 404)
        if old_app["status"] in ("ISSUED", "CONDITIONALLY_APPROVED"):
            old_app["_was_issued"] = (old_app["status"] == "ISSUED")
            from services.helpers import supersede_permit_application
            supersede_permit_application(old_app)

    entity = make_entity({
        "production_id": pid,
        "location_id": loc_id,
        "jurisdiction_id": loc["jurisdiction_id"],
        "shoot_start_date": require_str(payload, "shoot_start_date"),
        "shoot_end_date": require_str(payload, "shoot_end_date"),
        "closed_lanes": closed_lanes,
        "shoot_hours_per_day": shoot_hours,
        "submitted_at": None,
        "business_days_available": None,
        "lead_time_satisfied": None,
        "fee_cents": None,
        "amendment_of_id": amendment_of_id,
        "status": "DRAFT",
    })
    store.permit_applications[entity["id"]] = entity
    # Increment production version
    touch(p)
    return success_object(entity, 201)


@bp.route("/productions/<pid>/permit-applications", methods=["GET"])
def list_permit_applications(pid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    limit, offset = get_pagination_params(request.args)
    filters = {}
    for f in ("location_id", "jurisdiction_id", "status", "amendment_of_id"):
        v = request.args.get(f)
        if v:
            filters[f] = v
    items = list_filtered(store.permit_applications, filters, production_id=pid)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/productions/<pid>/permit-applications/<rid>", methods=["GET"])
def get_permit_application_nested(pid, rid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    pa = get_scoped(store.permit_applications, rid, pid, "PermitApplication")
    return success_object(pa)


@bp.route("/productions/<pid>/permit-applications/<rid>/submit", methods=["POST"])
def submit_permit_application(pid, rid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    pa = get_scoped(store.permit_applications, rid, pid, "PermitApplication")
    if pa["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "PermitApplication is not DRAFT", 409)
    if p["status"] not in ("PREP", "ACTIVE"):
        raise ApiError(ERR_INVALID_STATE, "Production must be PREP or ACTIVE", 409)
    loc = get_location(pa["location_id"])
    if loc["status"] != "AGREEMENT_EXECUTED":
        raise ApiError(ERR_AGREEMENT_NOT_EXECUTED, "Location agreement not executed", 422)
    jurisdiction = get_jurisdiction(pa["jurisdiction_id"])
    if jurisdiction["status"] != "ACTIVE":
        raise ApiError(ERR_JURISDICTION_SUSPENDED, "Jurisdiction is suspended", 422)
    shoot_start = parse_date(pa["shoot_start_date"])
    shoot_end = parse_date(pa["shoot_end_date"])
    if not _check_executed_agreement_covers(pid, pa["location_id"], shoot_start, shoot_end):
        raise ApiError(ERR_AGREEMENT_NOT_EXECUTED, "No EXECUTED agreement covers the window", 422)
    if pa["shoot_hours_per_day"] > loc["max_shoot_hours_per_day"]:
        raise ApiError(ERR_HOURS_EXCEED_LOCATION_CAP, "Shoot hours exceed location cap", 422)

    # Stamp and compute
    pa["submitted_at"] = store.clock.now_iso()
    submitted_date = store.clock.now_date()
    holidays = jurisdiction.get("holidays", [])
    pa["business_days_available"] = business_days_between(submitted_date, shoot_start, holidays)
    pa["lead_time_satisfied"] = pa["business_days_available"] >= jurisdiction["lead_time_business_days"]
    # Fee: business-day model (variant B, authoritative at submit)
    fee_days = business_days_in_window(shoot_start, shoot_end, holidays)
    pa["fee_cents"] = calc_permit_fee(
        jurisdiction["base_fee_cents"],
        jurisdiction["per_day_fee_cents"],
        jurisdiction["per_lane_fee_cents"],
        fee_days,
        pa["closed_lanes"],
        p["cast_size"],
        jurisdiction["large_cast_threshold"],
        jurisdiction["large_cast_multiplier_bps"],
    )
    pa["status"] = "SUBMITTED"
    touch(pa)
    return success_object(pa)


@bp.route("/productions/<pid>/permit-applications/<rid>/start-review", methods=["POST"])
def start_review(pid, rid):
    user_id, role = require_role("FilmOffice")
    p = get_production(pid)
    pa = get_scoped(store.permit_applications, rid, pid, "PermitApplication")
    if pa["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "PermitApplication is not SUBMITTED", 409)
    if not pa.get("lead_time_satisfied"):
        raise ApiError(ERR_LEAD_TIME_SHORT, "Lead time not satisfied", 422)
    pa["status"] = "UNDER_REVIEW"
    touch(pa)
    return success_object(pa)


@bp.route("/productions/<pid>/permit-applications/<rid>/decide", methods=["POST"])
def decide_permit_application(pid, rid):
    user_id, role = require_role("FilmOffice")
    p = get_production(pid)
    pa = get_scoped(store.permit_applications, rid, pid, "PermitApplication")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["decision"])
    decision = payload["decision"]
    if decision not in ("ISSUE", "APPROVE_WITH_CONDITIONS", "DENY"):
        raise ApiError(ERR_INVALID_REQUEST, "decision must be ISSUE, APPROVE_WITH_CONDITIONS, or DENY", 400)

    if pa["status"] == "UNDER_REVIEW":
        if decision == "DENY":
            pa["status"] = "DENIED"
        elif decision == "APPROVE_WITH_CONDITIONS":
            pa["status"] = "CONDITIONALLY_APPROVED"
        elif decision == "ISSUE":
            # Requires VERIFIED insurance cert covering the window
            shoot_start = parse_date(pa["shoot_start_date"])
            shoot_end = parse_date(pa["shoot_end_date"])
            cert = find_verified_cert_covering(pid, pa["jurisdiction_id"], shoot_start, shoot_end)
            if not cert:
                raise ApiError(ERR_INSURANCE_INSUFFICIENT, "No VERIFIED certificate covers the window", 422)
            pa["status"] = "ISSUED"
    elif pa["status"] == "CONDITIONALLY_APPROVED":
        if decision == "DENY":
            pa["status"] = "DENIED"
        elif decision == "ISSUE":
            # Requires VERIFIED cert + ACKED notification
            shoot_start = parse_date(pa["shoot_start_date"])
            shoot_end = parse_date(pa["shoot_end_date"])
            cert = find_verified_cert_covering(pid, pa["jurisdiction_id"], shoot_start, shoot_end)
            if not cert:
                raise ApiError(ERR_INSURANCE_INSUFFICIENT, "No VERIFIED certificate covers the window", 422)
            if not _has_acknowledged_notification(pa["id"]):
                raise ApiError(ERR_NOTIFICATION_DEFICIENT, "No ACKED notification for this application", 422)
            pa["status"] = "ISSUED"
        else:
            raise ApiError(ERR_INVALID_STATE, "Cannot APPROVE_WITH_CONDITIONS from CONDITIONALLY_APPROVED", 409)
    else:
        raise ApiError(ERR_INVALID_STATE, f"Cannot decide from {pa['status']}", 409)
    touch(pa)
    return success_object(pa)


@bp.route("/productions/<pid>/permit-applications/<rid>/withdraw", methods=["POST"])
def withdraw_permit_application(pid, rid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    pa = get_scoped(store.permit_applications, rid, pid, "PermitApplication")
    if pa["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError(ERR_INVALID_STATE, "Can only withdraw from DRAFT or SUBMITTED", 409)
    pa["status"] = "WITHDRAWN"
    touch(pa)
    return success_object(pa)
