"""Partner state licenses (PRD §3.1): registration and lifecycle.

ACTIVE on creation; suspend/reinstate/revoke by ComplianceOfficer. Reinstate
requires the logical clock not past valid_to; revoke is terminal.
"""
from flask import Blueprint

import db
import errors
from db import store
from errors import ApiError
from middleware import endpoint, ALL_ROLES
from response import ok, created, Paginator
from validation import (get_body, req_str, req_enum, req_datetime, body_fk,
                        path_entity)

bp = Blueprint("licenses", __name__)

LICENSE_SCOPES = ["RX_ONLY", "RX_AND_CONTROLLED", "RX_AND_COLD_CHAIN", "FULL"]


@bp.route("/wholesale/partner-state-licenses", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def create_license():
    body = get_body()
    partner = body_fk(body, "partner_id", store.trading_partners, "TradingPartner")
    state_code = req_str(body, "state_code")
    license_number = req_str(body, "license_number")
    scope = req_enum(body, "license_scope", LICENSE_SCOPES)
    valid_from = req_datetime(body, "valid_from")
    valid_to = req_datetime(body, "valid_to")
    if not valid_to > valid_from:
        raise ApiError(errors.ERR_INVALID_REQUEST[0], errors.ERR_INVALID_REQUEST[1],
                       "valid_to must be strictly after valid_from")
    license_ = {
        "id": db.new_id(),
        "partner_id": partner["id"],
        "state_code": state_code,
        "license_number": license_number,
        "license_scope": scope,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "license_status": "ACTIVE",
    }
    db.new_common(license_)
    store.partner_state_licenses[license_["id"]] = license_
    return created(license_)


@bp.route("/wholesale/partner-state-licenses", methods=["GET"])
@endpoint(ALL_ROLES)
def list_licenses():
    pg = Paginator()
    rows = list(store.partner_state_licenses.values())
    rows = pg.filter(rows, "partner_id")
    rows = pg.filter(rows, "state_code")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.route("/wholesale/partner-state-licenses/<licenseId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_license(licenseId):
    license_ = path_entity(store.partner_state_licenses, licenseId, "PartnerStateLicense")
    return ok(license_)


@bp.route("/wholesale/partner-state-licenses/<licenseId>/suspend", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def suspend_license(licenseId):
    license_ = path_entity(store.partner_state_licenses, licenseId, "PartnerStateLicense")
    if license_["license_status"] != "ACTIVE":
        raise ApiError(errors.ERR_LICENSE_NOT_ACTIVE[0], errors.ERR_LICENSE_NOT_ACTIVE[1],
                       "License must be ACTIVE to suspend")
    license_["license_status"] = "SUSPENDED"
    db.touch(license_)
    return ok(license_)


@bp.route("/wholesale/partner-state-licenses/<licenseId>/reinstate", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def reinstate_license(licenseId):
    license_ = path_entity(store.partner_state_licenses, licenseId, "PartnerStateLicense")
    if license_["license_status"] != "SUSPENDED":
        raise ApiError(errors.ERR_LICENSE_NOT_SUSPENDED[0], errors.ERR_LICENSE_NOT_SUSPENDED[1],
                       "License must be SUSPENDED to reinstate")
    if db.logical_now() > license_["valid_to"]:
        raise ApiError(errors.ERR_LICENSE_EXPIRED[0], errors.ERR_LICENSE_EXPIRED[1],
                       "License validity window has ended; reinstatement forbidden")
    license_["license_status"] = "ACTIVE"
    db.touch(license_)
    return ok(license_)


@bp.route("/wholesale/partner-state-licenses/<licenseId>/revoke", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def revoke_license(licenseId):
    license_ = path_entity(store.partner_state_licenses, licenseId, "PartnerStateLicense")
    if license_["license_status"] == "REVOKED":
        raise ApiError(errors.ERR_LICENSE_ALREADY_REVOKED[0], errors.ERR_LICENSE_ALREADY_REVOKED[1],
                       "License is already REVOKED (terminal)")
    license_["license_status"] = "REVOKED"
    db.touch(license_)
    return ok(license_)
