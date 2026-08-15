"""Investor registry, portal access dimension, portal sessions (PRD 3.1, 3.9)."""
from flask import Blueprint

import resolve
from db import db
from errors import raise_error
from middleware import SPONSOR, COMPLIANCE, AGENT, INVESTOR, endpoint
from response import success_list, success_object
from serializers import ser_investor, ser_portal_session
from services.domain import stamp_new, stamp_new_light, touch, sorted_items
from util import CLOCK, add_hours, fmt_dt, new_id
from validate import get_body, req_enum, req_str, pagination, apply_filters

bp = Blueprint("investors", __name__)
RS = {"strict_slashes": False}

INVESTOR_CLASSES = ("ACCREDITED", "QUALIFIED_PURCHASER", "NON_ACCREDITED")


@bp.route("/investors", methods=["POST"], **RS)
@endpoint(SPONSOR)
def create_investor(caller):
    body = get_body()
    name = req_str(body, "full_legal_name")
    tax = req_str(body, "tax_id_last4")
    email = req_str(body, "email")
    klass = req_enum(body, "investor_class", INVESTOR_CLASSES)
    if any(i["email"] == email for i in db["investors"].values()):
        raise_error("ERR_INVALID_REQUEST", f"email already registered: {email}")
    o = {
        "full_legal_name": name,
        "tax_id_last4": tax,
        "email": email,
        "investor_class": klass,
        "portal_access_status": "INVITED",
        "accreditation_expires_on": None,
    }
    stamp_new(o)
    db["investors"][o["id"]] = o
    return success_object(ser_investor(o), 201)


@bp.route("/investors", methods=["GET"], **RS)
@endpoint(SPONSOR, COMPLIANCE, AGENT)
def list_investors(caller):
    limit, offset = pagination()
    items = sorted_items(db["investors"].values())
    page = items[offset:offset + limit]
    return success_list([ser_investor(o) for o in page], len(items), limit, offset)


@bp.route("/investors/<investorId>", methods=["GET"], **RS)
@endpoint(SPONSOR, COMPLIANCE, AGENT, INVESTOR)
def get_investor(caller, investorId):
    inv = db["investors"].get(investorId)
    if inv is None:
        raise_error("ERR_INVESTOR_NOT_FOUND", f"investor not found: {investorId}")
    # Investor role reads its own record only; another investor's id reads as not found.
    if caller.role == INVESTOR and caller.user_id != investorId:
        raise_error("ERR_INVESTOR_NOT_FOUND", f"investor not found: {investorId}")
    return success_object(ser_investor(inv))


@bp.route("/investors/<investorId>/suspend-portal", methods=["POST"], **RS)
@endpoint(SPONSOR)
def suspend_portal(caller, investorId):
    inv = resolve.investor(investorId)
    inv["portal_access_status"] = "SUSPENDED"
    touch(inv)
    return success_object(ser_investor(inv))


@bp.route("/investors/<investorId>/revoke-portal", methods=["POST"], **RS)
@endpoint(SPONSOR)
def revoke_portal(caller, investorId):
    inv = resolve.investor(investorId)
    inv["portal_access_status"] = "REVOKED"
    touch(inv)
    return success_object(ser_investor(inv))


@bp.route("/investors/<investorId>/portal-sessions", methods=["POST"], **RS)
@endpoint(INVESTOR)
def create_portal_session(caller, investorId):
    inv = resolve.investor(investorId)
    if caller.user_id != investorId:
        raise_error("ERR_INSUFFICIENT_PERMISSIONS",
                    "an investor may only mint portal sessions for itself")
    if inv["portal_access_status"] != "ACTIVE":
        raise_error("ERR_PORTAL_ACCESS_DENIED",
                    f"portal access is {inv['portal_access_status']}, not ACTIVE")
    now = CLOCK.now()
    s = {
        "investor_id": investorId,
        "session_token": new_id(),
        "issued_at": fmt_dt(now),
        "expires_at": fmt_dt(add_hours(now, 12)),
        "last_accessed_at": fmt_dt(now),
    }
    stamp_new_light(s)
    db["portal_sessions"][s["id"]] = s
    return success_object(ser_portal_session(s), 201)


@bp.route("/investors/<investorId>/portal-sessions", methods=["GET"], **RS)
@endpoint(INVESTOR, SPONSOR, COMPLIANCE)
def list_portal_sessions(caller, investorId):
    resolve.investor(investorId)
    if caller.role == INVESTOR and caller.user_id != investorId:
        raise_error("ERR_INSUFFICIENT_PERMISSIONS",
                    "an investor may only list its own portal sessions")
    limit, offset = pagination()
    items = [s for s in db["portal_sessions"].values() if s["investor_id"] == investorId]
    items = apply_filters(sorted_items(items), {})
    page = items[offset:offset + limit]
    return success_list([ser_portal_session(o) for o in page], len(items), limit, offset)
