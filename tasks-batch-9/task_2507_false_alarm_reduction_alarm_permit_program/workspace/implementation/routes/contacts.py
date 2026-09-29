"""The callable roster: responsible parties held per premises."""

from flask import Blueprint

import engine
import rt
from core import (F, authenticate, check_owner, created, listing, ok, q, q_bool,
                  validate)
from errors import ApiError
from store import base_row, now, store, touch

bp = Blueprint("contacts", __name__)

WRITE_ROLES = ["ProgramAdministrator", "PermitClerk", "AlarmUser"]
READ_ONE_ROLES = ["ProgramAdministrator", "PermitClerk",
                  "PoliceDispatchSupervisor", "FalseAlarmReviewOfficer",
                  "AlarmUser"]
READ_MANY_ROLES = READ_ONE_ROLES + ["AlarmCompanyOperator"]

LIVE_SYSTEM_STATUSES = ("SUBMITTED", "PERMITTED")
ROSTER_MINIMUM = 2

CREATE_FIELDS = [
    F("alarm_site_id", "uuid"),
    F("full_name", "string"),
    F("phone_number", "string"),
    F("relationship", "string"),
    F("contact_priority", "int", min=1, max=5),
    F("is_ecv_callable", "bool", required=False),
]


@bp.post("/site-contacts")
def create_contact():
    ctx = authenticate(WRITE_ROLES)
    data = validate(ctx.body, CREATE_FIELDS)
    site = rt.resolve("AlarmSite", data["alarm_site_id"])
    check_owner(ctx, site_id=site["id"])
    priority = data["contact_priority"]
    for existing in engine.site_contacts(site["id"]):
        if existing.get("status") != "ACTIVE":
            continue
        if existing.get("contact_priority") == priority:
            raise ApiError("ERR_DUPLICATE_CONTACT_PRIORITY",
                           "Call priority %s is already held at this premises."
                           % priority)
    row = base_row()
    row["alarm_site_id"] = site["id"]
    row["full_name"] = data["full_name"]
    row["phone_number"] = data["phone_number"]
    row["relationship"] = data["relationship"]
    row["contact_priority"] = priority
    row["is_ecv_callable"] = data.get("is_ecv_callable", True)
    row["status"] = "ACTIVE"
    row["removed_at"] = None
    store.site_contacts[row["id"]] = row
    engine.rollup_site(site)
    return created(row)


@bp.delete("/site-contacts/<contact_id>")
def remove_contact(contact_id):
    ctx = authenticate(WRITE_ROLES)
    contact = rt.resolve("SiteContact", contact_id)
    check_owner(ctx, site_id=contact.get("alarm_site_id"))
    if contact.get("status") != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an ACTIVE roster entry may be removed.")
    site = store.alarm_sites.get(contact.get("alarm_site_id"))
    if site is not None:
        holds_live_system = any(
            s.get("status") in LIVE_SYSTEM_STATUSES
            for s in engine.site_systems(site["id"]))
        if holds_live_system:
            remaining = [c for c in engine.live_callable_contacts(site["id"])
                         if c["id"] != contact["id"]]
            if len(remaining) < ROSTER_MINIMUM:
                raise ApiError(
                    "ERR_CONTACT_ROSTER_MINIMUM",
                    "The premises must keep at least %d live callable contacts."
                    % ROSTER_MINIMUM)
    contact["status"] = "REMOVED"
    contact["removed_at"] = now()
    touch(contact)
    if site is not None:
        engine.rollup_site(site)
    return ok(contact)


@bp.get("/site-contacts/<contact_id>")
def get_contact(contact_id):
    ctx = authenticate(READ_ONE_ROLES)
    contact = rt.resolve("SiteContact", contact_id)
    check_owner(ctx, site_id=contact.get("alarm_site_id"))
    return ok(contact)


@bp.get("/site-contacts")
def list_contacts():
    ctx = authenticate(READ_MANY_ROLES)
    rows = rt.scope_reads(ctx, rt.all_rows("SiteContact"), company_field=None)
    site_id = q("alarm_site_id")
    status = q("status")
    callable_flag = q_bool("is_ecv_callable")
    if site_id is not None:
        rows = [r for r in rows if r.get("alarm_site_id") == site_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if callable_flag is not None:
        rows = [r for r in rows if bool(r.get("is_ecv_callable")) == callable_flag]
    return listing(rows, rt.fields("SiteContact"))
