from flask import Blueprint, request

from core import (
    require_ctx, ALL_ROLES, get_body, require_fields, require_enum, require_str,
    respond_object, list_response, fetch, base_record, touch, DB, current_clock,
    parse_dt, ApiError,
)

bp = Blueprint("people", __name__)

ADJUSTER_TYPES = {"INDEPENDENT", "CAT", "STAFF"}
LICENSE_TYPES = {"ALL_LINES", "PROPERTY"}


# ---------------------------------------------------------------------------
# Adjuster
# ---------------------------------------------------------------------------
@bp.route("/adjusters", methods=["POST"])
def create_adjuster():
    require_ctx({"LicensingAdmin"})
    body = get_body()
    require_fields(body, ["full_name", "email", "adjuster_type", "home_state"])
    require_str(body["full_name"], "full_name")
    require_str(body["email"], "email")
    require_enum(body["adjuster_type"], ADJUSTER_TYPES, "adjuster_type")
    require_str(body["home_state"], "home_state")
    rec = base_record()
    rec.update({
        "full_name": body["full_name"],
        "email": body["email"],
        "adjuster_type": body["adjuster_type"],
        "home_state": body["home_state"],
        "status": "ACTIVE",
    })
    DB["adjusters"][rec["id"]] = rec
    return respond_object(rec, status=201)


@bp.route("/adjusters", methods=["GET"])
def list_adjusters():
    require_ctx(ALL_ROLES)
    return list_response("adjusters", {
        "adjuster_type": request.args.get("adjuster_type"),
        "home_state": request.args.get("home_state"),
    })


@bp.route("/adjusters/<rid>", methods=["GET"])
def get_adjuster(rid):
    require_ctx(ALL_ROLES)
    return respond_object(fetch("adjusters", rid, "ERR_ADJUSTER_NOT_FOUND"))


# ---------------------------------------------------------------------------
# AdjusterLicense
# ---------------------------------------------------------------------------
@bp.route("/licenses", methods=["POST"])
def create_license():
    require_ctx({"LicensingAdmin"})
    body = get_body()
    require_fields(body, ["adjuster_id", "state_code", "license_number",
                          "license_type", "issued_at", "expires_at"])
    fetch("adjusters", body["adjuster_id"], "ERR_ADJUSTER_NOT_FOUND")
    require_str(body["state_code"], "state_code")
    require_str(body["license_number"], "license_number")
    require_enum(body["license_type"], LICENSE_TYPES, "license_type")
    try:
        issued = parse_dt(body["issued_at"])
        expires = parse_dt(body["expires_at"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid datetime")
    rec = base_record()
    rec.update({
        "adjuster_id": body["adjuster_id"],
        "state_code": body["state_code"],
        "license_number": body["license_number"],
        "license_type": body["license_type"],
        "issued_at": body["issued_at"],
        "expires_at": body["expires_at"],
        "status": "PENDING",
    })
    rec["_expires_dt"] = expires
    rec["_issued_dt"] = issued
    DB["licenses"][rec["id"]] = rec
    return respond_object(rec, status=201)


@bp.route("/licenses", methods=["GET"])
def list_licenses():
    require_ctx(ALL_ROLES)
    return list_response("licenses", {
        "adjuster_id": request.args.get("adjuster_id"),
        "state_code": request.args.get("state_code"),
        "status": request.args.get("status"),
    })


@bp.route("/licenses/<rid>", methods=["GET"])
def get_license(rid):
    require_ctx(ALL_ROLES)
    return respond_object(fetch("licenses", rid, "ERR_LICENSE_NOT_FOUND"))


def _expires_dt(lic):
    return lic["_expires_dt"]


@bp.route("/licenses/<rid>/activate", methods=["POST"])
def activate_license(rid):
    require_ctx({"LicensingAdmin"})
    lic = fetch("licenses", rid, "ERR_LICENSE_NOT_FOUND")
    if lic["status"] != "PENDING":
        raise ApiError("ERR_LICENSE_NOT_PENDING", 409)
    if current_clock() >= _expires_dt(lic):
        raise ApiError("ERR_LICENSE_EXPIRED", 409)
    lic["status"] = "ACTIVE"
    touch(lic)
    return respond_object(lic)


@bp.route("/licenses/<rid>/suspend", methods=["POST"])
def suspend_license(rid):
    require_ctx({"LicensingAdmin"})
    lic = fetch("licenses", rid, "ERR_LICENSE_NOT_FOUND")
    # Suspension is NOT gated on the expiry boundary (PRD 3.1).
    if lic["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_ACTIVE", 409)
    lic["status"] = "SUSPENDED"
    touch(lic)
    return respond_object(lic)


@bp.route("/licenses/<rid>/reinstate", methods=["POST"])
def reinstate_license(rid):
    require_ctx({"LicensingAdmin"})
    lic = fetch("licenses", rid, "ERR_LICENSE_NOT_FOUND")
    if lic["status"] != "SUSPENDED":
        raise ApiError("ERR_LICENSE_NOT_SUSPENDED", 409)
    if current_clock() >= _expires_dt(lic):
        raise ApiError("ERR_LICENSE_EXPIRED", 409)
    lic["status"] = "ACTIVE"
    touch(lic)
    return respond_object(lic)
