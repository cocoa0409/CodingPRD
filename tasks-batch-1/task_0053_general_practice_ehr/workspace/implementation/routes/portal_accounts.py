"""Patient portal account endpoints (PRD §3.9)."""
from __future__ import annotations

import uuid

from flask import Blueprint, g

import db
from db import stamp_create, touch
from errors import (
    APIError,
    ERR_DUPLICATE_PORTAL_ACCOUNT,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_REFERENCE_NOT_FOUND,
)
from middleware import require
from response import ok_object
from routes.common import lookup_or_404
from services import derive
from validation import get_body, require_str

bp = Blueprint("portal_accounts", __name__)

PORTAL_LOCKOUT_THRESHOLD = 3


@bp.route("/portal-accounts", methods=["POST"])
def create_portal_account():
    require(["FrontDesk"])
    body = get_body()

    # Priority 4: patient_id FK existence.
    pid_raw = body.get("patient_id")
    if isinstance(pid_raw, str) and pid_raw not in db.patients:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "patient_id does not resolve")

    patient_id = require_str(body, "patient_id")
    login_email = require_str(body, "login_email")
    if patient_id not in db.patients:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "patient_id does not resolve")

    # Uniqueness (priority 16): one account per patient AND unique login_email.
    for pa in db.portal_accounts.values():
        if pa["patient_id"] == patient_id:
            raise APIError(ERR_DUPLICATE_PORTAL_ACCOUNT, 409, "Patient already has a portal account")
        if pa["login_email"] == login_email:
            raise APIError(ERR_DUPLICATE_PORTAL_ACCOUNT, 409, "login_email already in use")

    rec = stamp_create({
        "patient_id": patient_id,
        "login_email": login_email,
        "status": "INVITED",
        "activation_token": uuid.uuid4().hex,
        "failed_login_count": 0,
    })
    db.portal_accounts[rec["id"]] = rec
    return ok_object(derive.serialize_portal_account(rec), 201)


@bp.route("/portal-accounts/<aid>", methods=["GET"])
def get_portal_account(aid):
    require(["FrontDesk", "Patient"])
    rec = lookup_or_404(db.portal_accounts, aid, "PortalAccount")
    if g.user_role == "Patient" and g.user_id != rec["patient_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Patient may only read own portal account")
    return ok_object(derive.serialize_portal_account(rec), 200)


@bp.route("/portal-accounts/<aid>/activate", methods=["POST"])
def activate_portal_account(aid):
    require(["Patient"])
    rec = lookup_or_404(db.portal_accounts, aid, "PortalAccount")
    body = get_body()
    token = require_str(body, "activation_token")

    # Priority 6: must be INVITED.
    if rec["status"] != "INVITED":
        raise APIError(ERR_INVALID_STATE, 409, "Portal account is not INVITED")
    # Priority 7: acting patient must own the account.
    if g.user_id != rec["patient_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Patient may only activate own account")

    if token == rec["activation_token"]:
        rec["status"] = "ACTIVE"
        rec["failed_login_count"] = 0
        touch(rec)
    else:
        rec["failed_login_count"] += 1
        if rec["failed_login_count"] >= PORTAL_LOCKOUT_THRESHOLD:
            rec["status"] = "SUSPENDED"
        touch(rec)
    return ok_object(derive.serialize_portal_account(rec), 200)


@bp.route("/portal-accounts/<aid>/suspend", methods=["POST"])
def suspend_portal_account(aid):
    require(["FrontDesk"])
    rec = lookup_or_404(db.portal_accounts, aid, "PortalAccount")
    if rec["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "Portal account is not ACTIVE")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return ok_object(derive.serialize_portal_account(rec), 200)


@bp.route("/portal-accounts/<aid>/reinstate", methods=["POST"])
def reinstate_portal_account(aid):
    require(["FrontDesk"])
    rec = lookup_or_404(db.portal_accounts, aid, "PortalAccount")
    if rec["status"] != "SUSPENDED":
        raise APIError(ERR_INVALID_STATE, 409, "Portal account is not SUSPENDED")
    rec["status"] = "ACTIVE"
    rec["failed_login_count"] = 0
    touch(rec)
    return ok_object(derive.serialize_portal_account(rec), 200)


@bp.route("/portal-accounts/<aid>/deactivate", methods=["POST"])
def deactivate_portal_account(aid):
    require(["FrontDesk"])
    rec = lookup_or_404(db.portal_accounts, aid, "PortalAccount")
    if rec["status"] not in ("ACTIVE", "SUSPENDED", "INVITED"):
        raise APIError(ERR_INVALID_STATE, 409, "Portal account cannot be deactivated from its state")
    rec["status"] = "DEACTIVATED"
    touch(rec)
    return ok_object(derive.serialize_portal_account(rec), 200)
