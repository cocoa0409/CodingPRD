"""Permit term cycle: renewal, revocation and the reads that expose the version."""

from flask import Blueprint

import calc
import engine
import rt
from core import F, authenticate, check_owner, listing, ok, q, validate
from errors import ApiError
from store import now, store, touch, whole_days_between

bp = Blueprint("permits", __name__)

RENEW_ROLES = ["ProgramAdministrator", "PermitClerk", "AlarmUser"]
READ_ROLES = ["ProgramAdministrator", "PermitClerk", "BillingClerk",
              "FalseAlarmReviewOfficer", "AlarmUser"]

RENEW_FIELDS = [F("expected_alarm_permit_version", "int")]
REVOKE_FIELDS = [F("revocation_reason", "string")]


@bp.post("/alarm-permits/<permit_id>/renewals")
def renew_permit(permit_id):
    ctx = authenticate(RENEW_ROLES)
    data = validate(ctx.body, RENEW_FIELDS)
    permit = rt.resolve("AlarmPermit", permit_id)
    check_owner(ctx, site_id=permit.get("alarm_site_id"))
    if data["expected_alarm_permit_version"] != permit.get("version"):
        raise ApiError("ERR_STALE_ALARM_PERMIT_VERSION",
                       "The permit has been modified since it was read.")
    status = permit.get("status")
    if status not in ("RENEWAL_DUE", "RENEWAL_BLOCKED", "GRACE"):
        raise ApiError("ERR_INVALID_STATE",
                       "A permit in %s may not be renewed." % status)
    if status == "GRACE":
        grace_through = permit.get("grace_through_at")
        if grace_through is not None and now() > grace_through:
            raise ApiError("ERR_INVALID_STATE",
                           "The grace window has closed on this permit.")
    site = store.alarm_sites.get(permit.get("alarm_site_id"))
    if site is None:
        raise ApiError("ERR_ALARM_SITE_NOT_FOUND", "The premises is missing.")
    if len(engine.live_callable_contacts(site["id"])) < 2:
        raise ApiError("ERR_INSUFFICIENT_ECV_CONTACTS",
                       "The premises needs at least 2 live callable contacts.")
    if engine.active_schedule() is None:
        raise ApiError("ERR_NO_ACTIVE_FEE_SCHEDULE",
                       "No fee schedule is ACTIVE at the logical clock.")
    sched = engine.governing_schedule(site) or engine.active_schedule()
    engine.rollup_site(site, bump=False)
    if site.get("renewal_block_active"):
        if status == "GRACE":
            raise ApiError("ERR_SITE_BALANCE_DELINQUENT",
                           "The premises' delinquent balance blocks renewal.")
        raise ApiError("ERR_PERMIT_RENEWAL_BLOCKED",
                       "Renewal is blocked until the balance clears.")

    days_late = whole_days_between(now(), permit.get("term_end_at")) \
        if permit.get("term_end_at") is not None else 0
    late_fee = calc.late_renewal_fee(sched, days_late)
    started = now()
    permit["status"] = "ACTIVE"
    engine.set_permit_term(permit, sched, started)
    permit["new_installation_grace_through"] = None
    permit["renewal_count"] = (permit.get("renewal_count") or 0) + 1
    permit["last_renewed_at"] = started
    touch(permit)

    engine.new_invoice(site, sched, "PERMIT_RENEWAL_FEE",
                       calc.permit_renewal_lines(sched, late_fee),
                       "alarm_permit_id", permit["id"])

    system = store.alarm_systems.get(permit.get("alarm_system_id"))
    if system is not None and system.get("status") == "UNPERMITTED":
        system["status"] = "PERMITTED"
        system["permitted_at"] = started
        system["unpermitted_since"] = None
        touch(system)
    site["chargeable_count_permit_year"] = 0
    engine.rollup_site(site)
    return ok(permit)


@bp.post("/alarm-permits/<permit_id>/revoke")
def revoke_permit(permit_id):
    ctx = authenticate(["ProgramAdministrator"])
    data = validate(ctx.body, REVOKE_FIELDS)
    permit = rt.resolve("AlarmPermit", permit_id)
    if permit.get("status") not in engine.LIVE_PERMIT_STATUSES:
        raise ApiError("ERR_INVALID_STATE",
                       "A permit in %s may not be revoked."
                       % permit.get("status"))
    permit["status"] = "REVOKED"
    permit["revocation_reason"] = data["revocation_reason"]
    touch(permit)
    site = store.alarm_sites.get(permit.get("alarm_site_id"))
    if site is not None:
        engine.unpermitted_cascade(permit, site)
        engine.rollup_site(site)
    return ok(permit)


@bp.get("/alarm-permits/<permit_id>")
def get_permit(permit_id):
    ctx = authenticate(READ_ROLES)
    permit = rt.resolve("AlarmPermit", permit_id)
    check_owner(ctx, site_id=permit.get("alarm_site_id"))
    return ok(permit)


@bp.get("/alarm-permits")
def list_permits():
    ctx = authenticate(READ_ROLES)
    rows = rt.scope_reads(ctx, rt.all_rows("AlarmPermit"), company_field=None)
    for field in ("alarm_system_id", "alarm_site_id", "status"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, rt.fields("AlarmPermit"))
