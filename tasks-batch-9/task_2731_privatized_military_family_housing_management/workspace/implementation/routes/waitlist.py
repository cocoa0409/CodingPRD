"""Waitlist applications: creation, recertification, accept and decline (PRD 3.3)."""

from flask import Blueprint

import middleware as mw
import response as resp
from db import (base_row, bump, db, fmt_date, now, parse_date, sort_rows,
                timedelta)
from errors import ApiError
from services import calc, core, lookup

bp = Blueprint("waitlist", __name__)

APP_READ_ROLES = (mw.PLATFORM_ADMIN, mw.PROPERTY_MANAGER, mw.SERVICE_MEMBER,
                  mw.INSTALLATION_HOUSING_OFFICE)
APP_ACTOR_ROLES = (mw.SERVICE_MEMBER, mw.INSTALLATION_HOUSING_OFFICE)
ACTIVE_STATUSES = ("PENDING", "OFFERED", "ACCEPTED")
TERMINAL_STATUSES = ("HOUSED", "EXPIRED")


def _snapshot(app_row, sponsor, control_date):
    dependents = lookup.dependents_of(sponsor["id"])
    app_row["effective_control_date"] = fmt_date(control_date)
    app_row["bedroom_eligibility"] = calc.bedroom_eligibility(dependents, control_date)
    app_row["rank_category"] = sponsor["rank_category"]
    app_row["dependent_count_at_application"] = calc.full_time_dependent_count(dependents)


@bp.post("/waitlist-applications")
def create_application():
    user_id, role = mw.authenticate(APP_ACTOR_ROLES)
    body = mw.json_body()
    mw.require_owner(role, user_id, mw.raw_ref(body, "service_member_id"))
    installation_id = mw.v_id(body, "installation_id")
    member_id = mw.v_id(body, "service_member_id")
    pcs_orders_date = mw.v_date(body, "pcs_orders_date")
    expected_arrival_date = mw.v_date(body, "expected_arrival_date")
    accessibility_required = mw.v_bool(body, "accessibility_required", required=False,
                                       default=False)
    installation = lookup.installation(installation_id)
    sponsor = lookup.service_member(member_id)

    dependents = lookup.dependents_of(sponsor["id"])
    if calc.full_time_dependent_count(dependents) < 1:
        raise ApiError("ERR_NOT_ELIGIBLE_FAMILY_HOUSING")
    for other in db.applications.values():
        if other["installation_id"] != installation["id"]:
            continue
        if other["service_member_id"] != sponsor["id"]:
            continue
        if other["status"] in ACTIVE_STATUSES:
            raise ApiError("ERR_DUPLICATE_ACTIVE_APPLICATION")

    control_date = calc.effective_control_date(
        pcs_orders_date, sponsor["deployment_status"] == "DEPLOYED")

    row = base_row()
    row["installation_id"] = installation["id"]
    row["service_member_id"] = sponsor["id"]
    row["pcs_orders_date"] = fmt_date(pcs_orders_date)
    row["expected_arrival_date"] = fmt_date(expected_arrival_date)
    row["accessibility_required"] = accessibility_required
    row["status"] = "PENDING"
    row["decline_count"] = 0
    row["offer_count"] = 0
    row["offered_unit_id"] = None
    row["offer_expires_at"] = None
    _snapshot(row, sponsor, control_date)
    db.applications[row["id"]] = row
    core.recount(installation)
    return resp.created(row)


@bp.get("/waitlist-applications/<application_id>")
def get_application(application_id):
    user_id, role = mw.authenticate(APP_READ_ROLES)
    app_row = lookup.maybe("applications", application_id)
    if app_row is not None:
        mw.require_owner(role, user_id, app_row["service_member_id"])
    app_row = lookup.application(application_id)
    return resp.ok(app_row)


@bp.get("/waitlist-applications")
def list_applications():
    mw.authenticate(APP_READ_ROLES)
    limit, offset = mw.pagination()
    installation_id = mw.q_str("installation_id")
    member_id = mw.q_str("service_member_id")
    offered_unit_id = mw.q_str("offered_unit_id")
    status = mw.q_enum("status", mw.APPLICATION_STATUSES)
    rows = sort_rows(list(db.applications.values()))
    if installation_id is not None:
        rows = [r for r in rows if r["installation_id"] == installation_id]
    if member_id is not None:
        rows = [r for r in rows if r["service_member_id"] == member_id]
    if offered_unit_id is not None:
        rows = [r for r in rows if r["offered_unit_id"] == offered_unit_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return resp.page(rows, limit, offset)


@bp.post("/waitlist-applications/<application_id>/recertify")
def recertify(application_id):
    mw.authenticate((mw.PLATFORM_ADMIN, mw.INSTALLATION_HOUSING_OFFICE))
    body = mw.json_body()
    expected_version = mw.v_int(body, "expected_application_version")
    replacement = mw.v_date(body, "pcs_orders_date", required=False, default=None)
    app_row = lookup.application(application_id)
    lookup.check_application_version(app_row, expected_version)
    # Rung 20: HOUSED and EXPIRED are terminal for an application, so a
    # correct version token still cannot reopen a finished one.
    if app_row["status"] in TERMINAL_STATUSES:
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")

    installation = lookup.installation(app_row["installation_id"])
    sponsor = lookup.service_member(app_row["service_member_id"])
    if replacement is not None:
        app_row["pcs_orders_date"] = fmt_date(replacement)

    control_date = calc.effective_control_date(
        parse_date(app_row["pcs_orders_date"]),
        sponsor["deployment_status"] == "DEPLOYED")
    control_date = control_date + timedelta(
        days=int(app_row["decline_count"]) * int(installation["decline_penalty_days"]))
    _snapshot(app_row, sponsor, control_date)
    bump(app_row)
    return resp.ok(app_row)


def _guard_offer_state(app_row):
    if app_row["status"] in TERMINAL_STATUSES:
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")
    if app_row["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")


@bp.post("/waitlist-applications/<application_id>/accept-offer")
def accept_offer(application_id):
    user_id, role = mw.authenticate(APP_ACTOR_ROLES)
    app_row = lookup.maybe("applications", application_id)
    if app_row is not None:
        mw.require_owner(role, user_id, app_row["service_member_id"])
    mw.json_body()
    app_row = lookup.application(application_id)
    _guard_offer_state(app_row)

    from db import parse_dt
    expires_at = parse_dt(app_row["offer_expires_at"])
    if now() > expires_at:
        raise ApiError("ERR_OFFER_WINDOW_CLOSED")

    app_row["status"] = "ACCEPTED"
    bump(app_row)
    core.recount(db.installations.get(app_row["installation_id"]))
    return resp.ok(app_row)


@bp.post("/waitlist-applications/<application_id>/decline-offer")
def decline_offer(application_id):
    user_id, role = mw.authenticate(APP_ACTOR_ROLES)
    app_row = lookup.maybe("applications", application_id)
    if app_row is not None:
        mw.require_owner(role, user_id, app_row["service_member_id"])
    body = mw.json_body()
    mw.v_str(body, "decline_reason", required=False, default=None)
    app_row = lookup.application(application_id)
    _guard_offer_state(app_row)

    installation = lookup.installation(app_row["installation_id"])
    unit = db.housing_units.get(app_row["offered_unit_id"])

    app_row["decline_count"] = int(app_row["decline_count"]) + 1
    app_row["offered_unit_id"] = None
    app_row["offer_expires_at"] = None
    if unit is not None and unit["status"] == "ASSIGNED":
        unit["status"] = "AVAILABLE"
        bump(unit)

    if int(app_row["decline_count"]) < int(installation["decline_limit"]):
        app_row["status"] = "PENDING"
        control_date = parse_date(app_row["effective_control_date"]) + timedelta(
            days=int(installation["decline_penalty_days"]))
        app_row["effective_control_date"] = fmt_date(control_date)
    else:
        app_row["status"] = "EXPIRED"
    bump(app_row)
    core.recount(installation)
    return resp.ok(app_row)
