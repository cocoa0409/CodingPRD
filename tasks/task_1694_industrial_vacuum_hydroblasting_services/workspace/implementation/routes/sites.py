"""Sites and rate schedules (PRD 3.1)."""

from flask import Blueprint, request

from db import store
from errors import (ApiError, ERR_STALE_VERSION, bad_request, invalid_state,
                    not_found)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from util import (get_body, is_int, list_paginated, new_entity, opt_field,
                  req_field, touch)

bp = Blueprint("sites", __name__)

CREDIT_STATUSES = ["GOOD_STANDING", "CREDIT_HOLD"]
SCHEDULE_STATUSES = ["DRAFT", "ACTIVE", "SUPERSEDED"]


# --- Sites ------------------------------------------------------------------

@bp.post("/v1/sites")
def create_site():
    require_roles(["AccountManager"])
    body = get_body()
    name = req_field(body, "name")
    credit_status = opt_field(body, "credit_status", choices=CREDIT_STATUSES,
                              default="GOOD_STANDING")
    site = new_entity(store.sites, {
        "name": name,
        "credit_status": credit_status,
        "active_rate_schedule_id": None,
    })
    return success_object(site, status=201)


@bp.get("/v1/sites")
def list_sites():
    require_roles(ALL_ROLES)
    filters = {}
    if request.args.get("credit_status") is not None:
        filters["credit_status"] = request.args["credit_status"]
    if request.args.get("active_rate_schedule_id") is not None:
        filters["active_rate_schedule_id"] = request.args["active_rate_schedule_id"]
    page, limit, offset, total = list_paginated(store.sites, filters, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/v1/sites/<siteId>")
def get_site(siteId):
    require_roles(ALL_ROLES)
    site = store.sites.get(siteId)
    if site is None:
        raise not_found("Site not found")
    return success_object(site)


@bp.patch("/v1/sites/<siteId>")
def update_site(siteId):
    require_roles(["AccountManager"])
    body = get_body()
    credit_status = opt_field(body, "credit_status", choices=CREDIT_STATUSES)
    site = store.sites.get(siteId)
    if site is None:
        raise not_found("Site not found")
    if credit_status is not None:
        site["credit_status"] = credit_status
    touch(site)
    return success_object(site)


# --- Rate schedules ----------------------------------------------------------

@bp.post("/v1/rate-schedules")
def create_rate_schedule():
    require_roles(["AccountManager"])
    body = get_body()
    site_id = req_field(body, "site_id")
    label = req_field(body, "label")
    vacuum_rate = req_field(body, "vacuum_per_gallon_cents", kind="int", gte_zero=True)
    hydro_rate = req_field(body, "hydroblast_per_foot_cents", kind="int", gte_zero=True)
    labor_rate = req_field(body, "labor_rate_cents_per_hour", kind="int", gte_zero=True)
    equip_rate = req_field(body, "equipment_rate_cents_per_hour", kind="int", gte_zero=True)
    standby_rate = req_field(body, "standby_rate_cents_per_hour", kind="int", gte_zero=True)
    overtime_multiplier = opt_field(body, "overtime_multiplier", kind="number",
                                    gt_zero=True, default=None)
    minimum_invoice = req_field(body, "minimum_invoice_cents", kind="int", gte_zero=True)
    if site_id not in store.sites:
        raise not_found("Site not found")
    schedule = new_entity(store.rate_schedules, {
        "site_id": site_id,
        "label": label,
        "vacuum_per_gallon_cents": vacuum_rate,
        "hydroblast_per_foot_cents": hydro_rate,
        "labor_rate_cents_per_hour": labor_rate,
        "equipment_rate_cents_per_hour": equip_rate,
        "standby_rate_cents_per_hour": standby_rate,
        "overtime_multiplier": overtime_multiplier if overtime_multiplier is not None else 1.5,
        "minimum_invoice_cents": minimum_invoice,
        "status": "DRAFT",
    })
    return success_object(schedule, status=201)


@bp.get("/v1/rate-schedules")
def list_rate_schedules():
    require_roles(ALL_ROLES)
    filters = {}
    if request.args.get("site_id") is not None:
        filters["site_id"] = request.args["site_id"]
    if request.args.get("status") is not None:
        filters["status"] = request.args["status"]
    page, limit, offset, total = list_paginated(store.rate_schedules, filters,
                                                request.args)
    return success_list(page, limit, offset, total)


@bp.get("/v1/rate-schedules/<scheduleId>")
def get_rate_schedule(scheduleId):
    require_roles(ALL_ROLES)
    schedule = store.rate_schedules.get(scheduleId)
    if schedule is None:
        raise not_found("Rate schedule not found")
    return success_object(schedule)


@bp.post("/v1/rate-schedules/<scheduleId>/activate")
def activate_rate_schedule(scheduleId):
    require_roles(["AccountManager"])
    body = get_body()
    if "expected_site_version" not in body or body["expected_site_version"] is None:
        raise bad_request("Missing required field: expected_site_version")
    expected = body["expected_site_version"]
    if not is_int(expected):
        raise bad_request("Field expected_site_version must be an integer")
    schedule = store.rate_schedules.get(scheduleId)
    if schedule is None:
        raise not_found("Rate schedule not found")
    site = store.sites[schedule["site_id"]]
    # OCC on the owning site's version (priority 5).
    if expected != site["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_site_version does not match the site's current version")
    if schedule["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT rate schedule can be activated")
    for other in store.rate_schedules.values():
        if (other["site_id"] == site["id"] and other["status"] == "ACTIVE"
                and other["id"] != schedule["id"]):
            other["status"] = "SUPERSEDED"
            touch(other)
    site["active_rate_schedule_id"] = schedule["id"]
    touch(site)
    schedule["status"] = "ACTIVE"
    touch(schedule)
    return success_object(schedule)
