"""License endpoints + test-driving clock (PRD §3.1)."""
from datetime import datetime, timezone

from flask import Blueprint

import clock
import constants
import db
from errors import err
from helpers import (get_json_body, require_fields, is_number, paginate,
                     sort_by_created, stamp_create, touch)
from middleware import require_auth
from response import object_response, array_response
from serializers import license_view

bp = Blueprint("licenses", __name__)

ALL_ROLES = list(constants.ROLES)


def get_license_or_404(license_id):
    lic = db.licenses.get(license_id)
    if lic is None:
        raise err("ERR_NOT_FOUND", "License not found.")
    return lic


def parse_iso(value):
    """Parse an ISO 8601 instant (accepts trailing Z)."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Expected an ISO 8601 string.")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Invalid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.route("/compliance/licenses", methods=["POST"])
@require_auth(["StateRegulator"])
def create_license():
    body = get_json_body()
    require_fields(body, ["license_number", "license_type", "state_code", "expires_on"])

    license_number = body["license_number"]
    license_type = body["license_type"]
    state_code = body["state_code"]
    expires_on = body["expires_on"]

    if not isinstance(license_number, str) or not license_number:
        raise err("ERR_INVALID_REQUEST", "license_number must be a non-empty string.")
    if license_type not in constants.LICENSE_TYPES:
        raise err("ERR_INVALID_REQUEST", "Invalid license_type.")
    if not isinstance(state_code, str) or len(state_code) != 2 or not state_code.isupper() or not state_code.isalpha():
        raise err("ERR_INVALID_REQUEST", "state_code must be two uppercase letters.")
    # validate expires_on is a parseable datetime
    parse_iso(expires_on)

    dpl = body.get("daily_purchase_limit_grams")
    if dpl is None:
        dpl = 28.5
    else:
        if not is_number(dpl):
            raise err("ERR_INVALID_REQUEST", "daily_purchase_limit_grams must be a number.")
        if dpl < 0:
            raise err("ERR_INVALID_REQUEST", "daily_purchase_limit_grams must be >= 0.")

    # Tag uniqueness (license_number).
    for lic in db.licenses.values():
        if lic["license_number"] == license_number:
            raise err("ERR_DUPLICATE_TAG", "license_number already exists.")

    rec = {
        "id": db.new_id(),
        "license_number": license_number,
        "license_type": license_type,
        "status": "ACTIVE",
        "state_code": state_code,
        "expires_on": expires_on,
        "daily_purchase_limit_grams": dpl,
    }
    stamp_create(rec)
    db.licenses[rec["id"]] = rec
    return object_response(license_view(rec), 201)


@bp.route("/compliance/licenses", methods=["GET"])
@require_auth(ALL_ROLES, open_read=True)
def list_licenses():
    from flask import request
    items = list(db.licenses.values())
    lt = request.args.get("license_type")
    st = request.args.get("status")
    if lt is not None:
        items = [r for r in items if r["license_type"] == lt]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([license_view(r) for r in page], limit, offset, total)


@bp.route("/compliance/licenses/<license_id>", methods=["GET"])
@require_auth(ALL_ROLES, open_read=True)
def get_license(license_id):
    lic = get_license_or_404(license_id)
    return object_response(license_view(lic))


@bp.route("/compliance/licenses/<license_id>/suspend", methods=["POST"])
@require_auth(["StateRegulator"])
def suspend_license(license_id):
    lic = get_license_or_404(license_id)
    if lic["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "License must be ACTIVE to suspend.")
    lic["status"] = "SUSPENDED"
    touch(lic)
    return object_response(license_view(lic))


@bp.route("/compliance/licenses/<license_id>/reinstate", methods=["POST"])
@require_auth(["StateRegulator"])
def reinstate_license(license_id):
    lic = get_license_or_404(license_id)
    if lic["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "License must be SUSPENDED to reinstate.")
    # expires_on must be in the future relative to the server clock.
    if parse_iso(lic["expires_on"]) <= clock.now():
        raise err("ERR_INVALID_STATE", "License has expired; cannot reinstate.")
    lic["status"] = "ACTIVE"
    touch(lic)
    return object_response(license_view(lic))


@bp.route("/compliance/licenses/<license_id>/revoke", methods=["POST"])
@require_auth(["StateRegulator"])
def revoke_license(license_id):
    lic = get_license_or_404(license_id)
    if lic["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "License must be ACTIVE or SUSPENDED to revoke.")
    lic["status"] = "REVOKED"
    touch(lic)
    return object_response(license_view(lic))


@bp.route("/compliance/_clock/set_current_utc", methods=["POST"])
@require_auth(["StateRegulator"])
def set_clock():
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    clock.set_now(parse_iso(body["to_iso8601"]))
    return object_response({})
