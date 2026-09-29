"""Alarm system registration, approval and retirement."""

from flask import Blueprint

import calc
import engine
import rt
from core import F, authenticate, check_owner, created, listing, ok, q, validate
from errors import ApiError
from store import add_days, base_row, now, store, touch

bp = Blueprint("systems", __name__)

WRITE_ROLES = ["ProgramAdministrator", "PermitClerk", "AlarmUser"]
CLERK_ROLES = ["ProgramAdministrator", "PermitClerk"]
READ_ROLES = ["ProgramAdministrator", "PermitClerk", "PoliceDispatchSupervisor",
              "FalseAlarmReviewOfficer", "BillingClerk", "AlarmCompanyOperator",
              "AlarmUser"]

SYSTEM_TYPES = ("BURGLARY", "HOLDUP_PANIC", "COMBINATION")
RESPONSE_MODES = ("NONE", "AUDIO_VIDEO_REQUIRED", "GUARD_REQUIRED")
CONFIGURABLE_STATUSES = ("SUBMITTED", "PERMITTED", "UNPERMITTED")

CREATE_FIELDS = [
    F("alarm_site_id", "uuid"),
    F("monitoring_company_id", "uuid"),
    F("system_type", "enum", values=SYSTEM_TYPES),
    F("zone_count", "int", min=1),
    F("ecv_enabled", "bool"),
    F("verified_response_mode", "enum", values=RESPONSE_MODES, required=False),
    F("installed_at", "ts"),
]

PATCH_FIELDS = [
    F("expected_alarm_system_version", "int"),
    F("monitoring_company_id", "uuid", required=False),
    F("ecv_enabled", "bool", required=False),
    F("verified_response_mode", "enum", values=RESPONSE_MODES, required=False),
    F("zone_count", "int", min=1, required=False),
]

REJECT_FIELDS = [F("rejection_reason", "string")]


@bp.post("/alarm-systems")
def create_system():
    ctx = authenticate(WRITE_ROLES)
    data = validate(ctx.body, CREATE_FIELDS)
    site = rt.resolve("AlarmSite", data["alarm_site_id"])
    company = rt.resolve("AlarmCompany", data["monitoring_company_id"])
    check_owner(ctx, site_id=site["id"], company_id=company["id"])
    row = base_row()
    row["alarm_site_id"] = site["id"]
    row["monitoring_company_id"] = company["id"]
    row["system_type"] = data["system_type"]
    row["zone_count"] = data["zone_count"]
    row["ecv_enabled"] = data["ecv_enabled"]
    row["verified_response_mode"] = data.get("verified_response_mode", "NONE")
    row["status"] = "SUBMITTED"
    row["installed_at"] = data["installed_at"]
    row["permitted_at"] = None
    row["unpermitted_since"] = None
    row["rejection_reason"] = None
    row["decommissioned_at"] = None
    store.alarm_systems[row["id"]] = row
    engine.rollup_company(company)
    return created(row)


@bp.patch("/alarm-systems/<system_id>")
def patch_system(system_id):
    ctx = authenticate(WRITE_ROLES)
    data = validate(ctx.body, PATCH_FIELDS)
    system = rt.resolve("AlarmSystem", system_id)
    company = None
    if "monitoring_company_id" in data:
        company = rt.resolve("AlarmCompany", data["monitoring_company_id"])
    check_owner(ctx, site_id=system.get("alarm_site_id"),
                company_id=system.get("monitoring_company_id"))
    if data["expected_alarm_system_version"] != system.get("version"):
        raise ApiError("ERR_STALE_ALARM_SYSTEM_VERSION",
                       "The alarm system has been modified since it was read.")
    if system.get("status") not in CONFIGURABLE_STATUSES:
        raise ApiError("ERR_INVALID_STATE",
                       "A %s system may not be reconfigured."
                       % system.get("status"))
    previous_company = system.get("monitoring_company_id")
    if company is not None:
        system["monitoring_company_id"] = company["id"]
    for field in ("ecv_enabled", "verified_response_mode", "zone_count"):
        if field in data:
            system[field] = data[field]
    touch(system)
    if company is not None and company["id"] != previous_company:
        engine.rollup_company(company)
        outgoing = store.alarm_companies.get(previous_company)
        if outgoing is not None:
            engine.rollup_company(outgoing)
    return ok(system)


@bp.post("/alarm-systems/<system_id>/approve-registration")
def approve_registration(system_id):
    ctx = authenticate(CLERK_ROLES)
    system = rt.resolve("AlarmSystem", system_id)
    if system.get("status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SUBMITTED registration may be approved.")
    site = store.alarm_sites.get(system.get("alarm_site_id"))
    if site is None or site.get("status") != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The premises is not ACTIVE.")
    for order in engine.site_orders(site["id"]):
        if order.get("status") in ("EFFECTIVE", "REINSTATEMENT_PENDING"):
            raise ApiError("ERR_POLICE_RESPONSE_SUSPENDED",
                           "Police response is withdrawn from this premises.")
    if len(engine.live_callable_contacts(site["id"])) < 2:
        raise ApiError("ERR_INSUFFICIENT_ECV_CONTACTS",
                       "The premises needs at least 2 live callable contacts.")
    for permit in engine.system_permits(system["id"]):
        if permit.get("status") in engine.LIVE_PERMIT_STATUSES:
            raise ApiError("ERR_ACTIVE_PERMIT_EXISTS",
                           "This system already holds a live permit.")
    sched = engine.active_schedule()
    if sched is None:
        raise ApiError("ERR_NO_ACTIVE_FEE_SCHEDULE",
                       "No fee schedule is ACTIVE at the logical clock.")
    pricing = engine.governing_schedule(site) or sched
    block = int(pricing.get("delinquent_balance_block_cents") or 0)
    if (site.get("outstanding_balance_cents") or 0) >= block:
        raise ApiError("ERR_SITE_BALANCE_DELINQUENT",
                       "The premises' delinquent balance blocks new permits.")

    first_issuance = len(engine.site_permits(site["id"])) == 0
    started = now()
    permit = base_row()
    permit["alarm_system_id"] = system["id"]
    permit["alarm_site_id"] = site["id"]
    permit["permit_number"] = store.next_permit_number()
    permit["status"] = "ACTIVE"
    engine.set_permit_term(permit, sched, started)
    permit["new_installation_grace_through"] = None
    permit["renewal_count"] = 0
    permit["issued_by_user_id"] = ctx.user_id
    permit["last_renewed_at"] = None
    permit["revocation_reason"] = None
    if first_issuance:
        engine.pin_site_schedule(site, sched)
        permit["new_installation_grace_through"] = add_days(
            started, int(sched.get("new_installation_grace_days") or 0))
    store.alarm_permits[permit["id"]] = permit

    system["status"] = "PERMITTED"
    system["permitted_at"] = started
    system["unpermitted_since"] = None
    touch(system)

    pinned = engine.governing_schedule(site) or sched
    engine.new_invoice(site, pinned, "PERMIT_ISSUE_FEE",
                       calc.permit_issue_lines(pinned),
                       "alarm_permit_id", permit["id"])
    engine.rollup_site(site)
    company = store.alarm_companies.get(system.get("monitoring_company_id"))
    if company is not None:
        engine.rollup_company(company)
    return created(permit)


@bp.post("/alarm-systems/<system_id>/reject-registration")
def reject_registration(system_id):
    ctx = authenticate(CLERK_ROLES)
    data = validate(ctx.body, REJECT_FIELDS)
    system = rt.resolve("AlarmSystem", system_id)
    if system.get("status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SUBMITTED registration may be rejected.")
    system["status"] = "REJECTED"
    system["rejection_reason"] = data["rejection_reason"]
    touch(system)
    company = store.alarm_companies.get(system.get("monitoring_company_id"))
    if company is not None:
        engine.rollup_company(company)
    return ok(system)


@bp.post("/alarm-systems/<system_id>/decommission")
def decommission_system(system_id):
    ctx = authenticate(WRITE_ROLES)
    system = rt.resolve("AlarmSystem", system_id)
    check_owner(ctx, site_id=system.get("alarm_site_id"))
    if system.get("status") not in ("PERMITTED", "UNPERMITTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only a live system may be decommissioned.")
    for req in engine.system_requests(system["id"]):
        if req.get("status") in engine.OPEN_REQUEST_STATUSES:
            raise ApiError("ERR_OPEN_DISPATCH_REQUEST_EXISTS",
                           "This system still has an open dispatch request.")
    system["decommissioned_at"] = now()
    was_permitted = system.get("status") == "PERMITTED"
    system["status"] = "DECOMMISSIONED"
    touch(system)
    if was_permitted:
        for permit in engine.system_permits(system["id"]):
            if permit.get("status") in engine.LIVE_PERMIT_STATUSES:
                permit["status"] = "REVOKED"
                permit["revocation_reason"] = "SYSTEM_DECOMMISSIONED"
                touch(permit)
    site = store.alarm_sites.get(system.get("alarm_site_id"))
    if site is not None:
        engine.rollup_site(site)
    company = store.alarm_companies.get(system.get("monitoring_company_id"))
    if company is not None:
        engine.rollup_company(company)
    return ok(system)


@bp.get("/alarm-systems/<system_id>")
def get_system(system_id):
    ctx = authenticate(READ_ROLES)
    system = rt.resolve("AlarmSystem", system_id)
    check_owner(ctx, site_id=system.get("alarm_site_id"),
                company_id=system.get("monitoring_company_id"))
    return ok(system)


@bp.get("/alarm-systems")
def list_systems():
    ctx = authenticate(READ_ROLES)
    rows = rt.scope_reads(ctx, rt.all_rows("AlarmSystem"))
    for field in ("alarm_site_id", "monitoring_company_id", "status",
                  "system_type"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, rt.fields("AlarmSystem"))
