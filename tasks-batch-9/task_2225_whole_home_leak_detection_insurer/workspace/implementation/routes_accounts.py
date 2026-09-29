"""Homeowners, emergency contacts, properties and irrigation windows."""
from flask import Blueprint, request

import auth
import clock
import db
import serializers as ser
import services
from config import (
    ACCOUNT_STATES,
    CONTACT_STATUSES,
    IRRIGATION_STATUSES,
    NOTIFICATION_CHANNELS,
    PROPERTY_STATES,
    ROLE_ADJUSTER,
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_HOMEOWNER,
    ROLE_INSTALLER,
    LIFECYCLE_STATES,
    CREDIT_STATES,
)
from errors import ApiError, bad_request
from response import created, enum_filter, listing, ok, page_params
from util import (
    POSTAL_CODE,
    STATE_CODE,
    get_body,
    req_bool,
    req_datetime,
    req_e164,
    req_int,
    req_number,
    req_string,
    opt_bool_default,
    opt_enum,
    opt_string,
    to_dec,
)

bp = Blueprint("accounts", __name__)


def _homeowner(hid):
    row = db.homeowners.get(hid)
    if row is None:
        raise ApiError("ERR_HOMEOWNER_NOT_FOUND", "No homeowner exists with id %s." % hid)
    return row


def _property(pid):
    row = db.properties.get(pid)
    if row is None:
        raise ApiError("ERR_PROPERTY_NOT_FOUND", "No property exists with id %s." % pid)
    return row


# ---------------------------------------------------------------- reads
@bp.get("/homeowners/<hid>")
def get_homeowner(hid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN, ROLE_ANALYST, ROLE_ADJUSTER)
    row = _homeowner(hid)
    auth.own_homeowner(actor, row)
    return ok(ser.homeowner(row))


@bp.get("/homeowners/<hid>/emergency-contacts")
def list_contacts(hid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN)
    row = _homeowner(hid)
    limit, offset = page_params()
    auth.own_homeowner(actor, row)
    status = enum_filter("status", CONTACT_STATUSES)
    rows = db.contacts_for_homeowner(hid)
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows = db.sort_rows(rows, lambda c: (c["priority_rank"], c["created_at"]))
    return listing(rows, ser.emergency_contact, limit, offset)


@bp.get("/homeowners/<hid>/properties")
def list_properties(hid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN, ROLE_ANALYST)
    row = _homeowner(hid)
    limit, offset = page_params()
    auth.own_homeowner(actor, row)
    state = enum_filter("property_state", PROPERTY_STATES)
    rows = db.properties_for_homeowner(hid)
    if state is not None:
        rows = [p for p in rows if p["property_state"] == state]
    rows = db.sort_rows(rows, lambda p: p["created_at"])
    return listing(rows, ser.property_row, limit, offset)


@bp.get("/properties/<pid>")
def get_property(pid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_INSTALLER, ROLE_ADMIN, ROLE_ANALYST)
    row = _property(pid)
    auth.own_property(actor, row)
    return ok(ser.property_row(row))


@bp.get("/properties/<pid>/devices")
def list_devices(pid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_INSTALLER, ROLE_ADMIN, ROLE_ANALYST)
    row = _property(pid)
    limit, offset = page_params()
    auth.own_property(actor, row)
    state = enum_filter("lifecycle_state", LIFECYCLE_STATES)
    rows = db.devices_for_property(pid)
    if state is not None:
        rows = [d for d in rows if d["lifecycle_state"] == state]
    rows = db.sort_rows(rows, lambda d: d["created_at"])
    return listing(rows, ser.device, limit, offset)


@bp.get("/properties/<pid>/irrigation-windows")
def list_windows(pid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN, ROLE_ANALYST)
    row = _property(pid)
    limit, offset = page_params()
    auth.own_property(actor, row)
    status = enum_filter("status", IRRIGATION_STATUSES)
    rows = db.windows_for_property(pid)
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    rows = db.sort_rows(rows, lambda w: w["start_at"])
    return listing(rows, ser.irrigation_window, limit, offset)


@bp.get("/properties/<pid>/policies")
def list_property_policies(pid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ANALYST, ROLE_ADJUSTER, ROLE_ADMIN)
    row = _property(pid)
    limit, offset = page_params()
    auth.own_property(actor, row)
    state = enum_filter("credit_state", CREDIT_STATES)
    rows = db.policies_for_property(pid)
    if state is not None:
        rows = [p for p in rows if p["credit_state"] == state]
    rows = db.sort_rows(rows, lambda p: p["created_at"], reverse=True)
    return listing(rows, ser.policy, limit, offset)


# ---------------------------------------------------------------- writes
@bp.post("/homeowners")
def create_homeowner():
    auth.guard(ROLE_ADMIN)
    body = get_body(request)
    full_name = req_string(body, "full_name", 1, 120)
    email = req_string(body, "email", 1, 320, lower=True)
    phone = req_e164(body, "phone_e164")
    channel = opt_enum(body, "notification_channel", NOTIFICATION_CHANNELS, "SMS")
    for existing in db.homeowners.values():
        if existing["email"] == email:
            raise bad_request("The email address is already registered.")
    row = {
        "email": email,
        "full_name": full_name,
        "phone_e164": phone,
        "notification_channel": channel,
        "account_state": "ACTIVE",
        "deactivated_at": None,
    }
    db.insert(db.homeowners, row)
    return created(ser.homeowner(row))


@bp.post("/homeowners/<hid>/emergency-contacts")
def create_contact(hid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN)
    owner = _homeowner(hid)
    body = get_body(request)
    full_name = req_string(body, "full_name", 1, 120)
    phone = req_e164(body, "phone_e164")
    rank = req_int(body, "priority_rank", 1, 5)
    verify = opt_bool_default(body, "verify_immediately", False)
    auth.own_homeowner(actor, owner)
    auth.alive(owner)
    for existing in db.contacts_for_homeowner(hid):
        if existing["status"] == "ACTIVE" and existing["priority_rank"] == rank:
            raise ApiError(
                "ERR_CONTACT_RANK_TAKEN",
                "Priority rank %d is already held by an active contact." % rank,
            )
    row = {
        "homeowner_id": hid,
        "full_name": full_name,
        "phone_e164": phone,
        "priority_rank": rank,
        "verification_state": "VERIFIED" if verify else "PENDING",
        "status": "ACTIVE",
        "last_notified_at": None,
    }
    db.insert(db.emergency_contacts, row)
    return created(ser.emergency_contact(row))


@bp.post("/homeowners/<hid>/deactivate")
def deactivate(hid):
    auth.guard(ROLE_ADMIN)
    owner = _homeowner(hid)
    if owner["account_state"] != "ACTIVE":
        raise ApiError(
            "ERR_HOMEOWNER_DEACTIVATED", "This homeowner account is already deactivated."
        )
    if services.account_has_approved_claim(hid):
        raise ApiError(
            "ERR_OPEN_PAYOUT_BLOCKS_DEACTIVATION",
            "An approved but unpaid claim must be settled before closing the account.",
        )
    services.deactivate_account(owner)
    return ok(ser.homeowner(owner))


@bp.post("/properties")
def create_property():
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN)
    body = get_body(request)
    homeowner_id = req_string(body, "homeowner_id")
    address = req_string(body, "address_line1", 1, 160)
    city = req_string(body, "city", 1, 120)
    state_code = req_string(body, "state_code", 2, 2, pattern=STATE_CODE)
    postal = req_string(body, "postal_code", 5, 5, pattern=POSTAL_CODE)
    year_built = req_int(body, "year_built", 1850, 2026)
    irrigation = opt_bool_default(body, "irrigation_present", False)
    owner = _homeowner(homeowner_id)
    auth.own_homeowner(actor, owner)
    auth.alive(owner)
    row = {
        "homeowner_id": homeowner_id,
        "address_line1": address,
        "city": city,
        "state_code": state_code,
        "postal_code": postal,
        "year_built": year_built,
        "irrigation_present": irrigation,
        "property_state": "ACTIVE",
        "archived_at": None,
    }
    db.insert(db.properties, row)
    return created(ser.property_row(row))


@bp.post("/properties/<pid>/irrigation-windows")
def create_window(pid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN)
    prop = _property(pid)
    body = get_body(request)
    label = req_string(body, "label", 1, 60)
    start_at = req_datetime(body, "start_at")
    end_at = req_datetime(body, "end_at")
    if end_at <= start_at:
        raise bad_request("Field 'end_at' must be strictly after 'start_at'.")
    ceiling = req_number(body, "expected_max_flow_gpm")
    if ceiling <= 0:
        raise bad_request("Field 'expected_max_flow_gpm' must be greater than zero.")
    auth.own_property(actor, prop)
    auth.alive_property(prop)
    for existing in db.windows_for_property(pid):
        if existing["status"] != "ACTIVE":
            continue
        if start_at < existing["end_at"] and existing["start_at"] < end_at:
            raise ApiError(
                "ERR_IRRIGATION_WINDOW_OVERLAP",
                "The submitted span overlaps an active irrigation window.",
            )
    if not prop["irrigation_present"]:
        raise ApiError(
            "ERR_IRRIGATION_NOT_ENABLED",
            "This property does not declare an irrigation system.",
        )
    row = {
        "property_id": pid,
        "label": label,
        "start_at": start_at,
        "end_at": end_at,
        "expected_max_flow_gpm": ceiling,
        "status": "ACTIVE",
        "suspended_at": None,
    }
    db.insert(db.irrigation_windows, row)
    return created(ser.irrigation_window(row))
