"""ManufacturerAuthorization endpoints (PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_AUTHORIZATION_INVALID_STATE,
    ERR_AUTHORIZATION_WINDOW_OVERLAP,
)
from middleware import authorized
from response import success_object, success_list
from services.core import (
    get_body, require_fields, require_string, require_int, parse_date_field,
    public, get_or_404, get_clinic_or_404, require_clinic_active, paginate,
)
from util import CLOCK, new_id, now_ts, touch, quarter_label

bp = Blueprint("authorizations", __name__)

READ_ROLES = ["AccountManager", "ClinicBuyer", "ComplianceOfficer"]


@bp.route("/vet/manufacturer-authorizations", methods=["POST"])
def create_authorization():
    authorized(["ComplianceOfficer"])
    body = get_body()
    require_fields(body, ["clinic_id", "manufacturer_code", "valid_from",
                          "valid_until", "approved_ship_to_address",
                          "quarterly_quantity_cap"])
    # Existence, left to right: clinic first.
    clinic = get_clinic_or_404(body["clinic_id"])
    manufacturer_code = require_string(body, "manufacturer_code")
    valid_from = parse_date_field(body, "valid_from")
    valid_until = parse_date_field(body, "valid_until")
    if valid_until < valid_from:
        raise_error(ERR_INVALID_REQUEST, "valid_until must be >= valid_from")
    approved_ship_to = require_string(body, "approved_ship_to_address")
    cap = require_int(body, "quarterly_quantity_cap", minimum=1)

    # Closed-interval window overlap per (clinic, manufacturer) over
    # authorizations in {PENDING, APPROVED, SUSPENDED}: shared boundary conflicts.
    for other in db["manufacturer_authorizations"].values():
        if other["clinic_id"] != clinic["id"]:
            continue
        if other["manufacturer_code"] != manufacturer_code:
            continue
        if other["status"] not in ("PENDING", "APPROVED", "SUSPENDED"):
            continue
        if valid_from <= other["valid_until"] and other["valid_from"] <= valid_until:
            raise_error(ERR_AUTHORIZATION_WINDOW_OVERLAP,
                        "authorization validity window overlaps an existing one")

    auth = {
        "id": new_id(),
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
        "clinic_id": clinic["id"],
        "manufacturer_code": manufacturer_code,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "approved_ship_to_address": approved_ship_to,
        "quarterly_quantity_cap": cap,
        "quantity_approved_this_quarter": 0,
        "_counter_quarter": quarter_label(CLOCK.today()),
        "status": "PENDING",
    }
    db["manufacturer_authorizations"][auth["id"]] = auth
    return success_object(_serialize(auth), status=201)


def _serialize(auth):
    out = public(auth)
    out["valid_from"] = auth["valid_from"].isoformat()
    out["valid_until"] = auth["valid_until"].isoformat()
    return out


@bp.route("/vet/manufacturer-authorizations", methods=["GET"])
def list_authorizations():
    authorized(READ_ROLES)
    items = list(db["manufacturer_authorizations"].values())
    for param in ("clinic_id", "manufacturer_code", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [a for a in items if str(a.get(param)) == val]
    page, total, limit, offset = paginate(items)
    return success_list([_serialize(a) for a in page], total, limit, offset)


@bp.route("/vet/manufacturer-authorizations/<aid>", methods=["GET"])
def get_authorization(aid):
    authorized(READ_ROLES)
    auth = get_or_404("manufacturer_authorizations", aid)
    return success_object(_serialize(auth))


@bp.route("/vet/manufacturer-authorizations/<aid>/approve", methods=["POST"])
def approve_authorization(aid):
    authorized(["ComplianceOfficer"])
    auth = get_or_404("manufacturer_authorizations", aid)
    if auth["status"] != "PENDING":
        raise_error(ERR_AUTHORIZATION_INVALID_STATE,
                    f"authorization must be PENDING (is {auth['status']})")
    clinic = get_clinic_or_404(auth["clinic_id"])
    require_clinic_active(clinic)
    auth["status"] = "APPROVED"
    touch(auth)
    return success_object(_serialize(auth))


@bp.route("/vet/manufacturer-authorizations/<aid>/suspend", methods=["POST"])
def suspend_authorization(aid):
    authorized(["ComplianceOfficer"])
    auth = get_or_404("manufacturer_authorizations", aid)
    if auth["status"] != "APPROVED":
        raise_error(ERR_AUTHORIZATION_INVALID_STATE,
                    f"authorization must be APPROVED (is {auth['status']})")
    auth["status"] = "SUSPENDED"
    touch(auth)
    return success_object(_serialize(auth))


@bp.route("/vet/manufacturer-authorizations/<aid>/reinstate", methods=["POST"])
def reinstate_authorization(aid):
    authorized(["ComplianceOfficer"])
    auth = get_or_404("manufacturer_authorizations", aid)
    if auth["status"] != "SUSPENDED":
        raise_error(ERR_AUTHORIZATION_INVALID_STATE,
                    f"authorization must be SUSPENDED (is {auth['status']})")
    # Reinstatement only while the window is still open (valid_until >= today).
    if auth["valid_until"] < CLOCK.today():
        raise_error(ERR_AUTHORIZATION_INVALID_STATE,
                    "authorization window has closed; cannot reinstate")
    auth["status"] = "APPROVED"
    touch(auth)
    return success_object(_serialize(auth))


@bp.route("/vet/manufacturer-authorizations/<aid>/revoke", methods=["POST"])
def revoke_authorization(aid):
    authorized(["ComplianceOfficer"])
    auth = get_or_404("manufacturer_authorizations", aid)
    if auth["status"] not in ("PENDING", "APPROVED", "SUSPENDED"):
        raise_error(ERR_AUTHORIZATION_INVALID_STATE,
                    f"authorization cannot be revoked from {auth['status']}")
    auth["status"] = "REVOKED"
    touch(auth)
    return success_object(_serialize(auth))
