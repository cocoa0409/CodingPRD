"""Server permits: create, fetch, activate, revoke, check-expiry."""
from datetime import timedelta

from flask import Blueprint

import errors
from auth import require_auth, ALL_READERS
from clock import clock, add_months
from db import db, new_id, common_fields, touch
from helpers import body, out, get_or_404, find_license_class_by_code
import validate
from response import ok, created

bp = Blueprint("server_permits", __name__)


@bp.route("/server-permits", methods=["POST"])
def create_server_permit():
    require_auth(["Applicant"])
    data = body()
    license_id = validate.require_str(data, "license_id")
    if license_id not in db.licenses:
        raise errors.err(errors.ERR_NOT_FOUND, "License not found")
    holder_name = validate.require_str(data, "holder_name")
    training_completed = validate.opt_bool(data, "training_completed", False)

    ent = {
        "id": new_id(), "license_id": license_id, "holder_name": holder_name,
        "status": "PENDING", "training_completed": training_completed,
        "expires_at": None,
    }
    ent.update(common_fields())
    db.server_permits[ent["id"]] = ent
    return created(out(ent))


@bp.route("/server-permits/<id>", methods=["GET"])
def get_server_permit(id):
    require_auth(ALL_READERS)
    ent = get_or_404(db.server_permits, id)
    return ok(out(ent))


@bp.route("/server-permits/<id>/activate", methods=["POST"])
def activate_server_permit(id):
    require_auth(["Applicant"])
    permit = get_or_404(db.server_permits, id)
    if permit["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Permit not PENDING")
    lic = db.licenses.get(permit["license_id"])
    if lic is None:
        raise errors.err(errors.ERR_NOT_FOUND, "License not found")

    data = body()
    lc = find_license_class_by_code(lic["license_class_code"])

    # Business preconditions per validation order: license ACTIVE (state-ish),
    # then capacity (priority 13), then training (priority 14), then OCC (23).
    if lic["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "License not ACTIVE")
    if lic["active_server_count"] >= lc["max_servers_per_license"]:
        raise errors.err(errors.ERR_SERVER_CAPACITY_EXCEEDED, "Server capacity exceeded")
    if not permit["training_completed"]:
        raise errors.err(errors.ERR_TRAINING_INCOMPLETE, "Training incomplete")

    # priority 23: OCC against license version (required on activate)
    if "expected_license_version" not in data or data["expected_license_version"] is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Missing expected_license_version")
    expected = data["expected_license_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_license_version must be an integer")
    if expected != lic["version"]:
        raise errors.err(errors.ERR_STALE_LICENSE_VERSION, "Stale license version")

    permit["status"] = "ACTIVE"
    permit["expires_at"] = add_months(clock.now(), 36)
    touch(permit)
    lic["active_server_count"] = lic["active_server_count"] + 1
    touch(lic)
    return ok(out(permit))


@bp.route("/server-permits/<id>/revoke", methods=["POST"])
def revoke_server_permit(id):
    require_auth(["Director"])
    permit = get_or_404(db.server_permits, id)
    if permit["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Permit not ACTIVE")
    permit["status"] = "REVOKED"
    touch(permit)
    lic = db.licenses.get(permit["license_id"])
    if lic is not None:
        lic["active_server_count"] = max(lic["active_server_count"] - 1, 0)
        touch(lic)
    return ok(out(permit))


@bp.route("/server-permits/<id>/check-expiry", methods=["POST"])
def check_expiry(id):
    require_auth(["Director", "LicensingExaminer"])
    permit = get_or_404(db.server_permits, id)
    if permit["status"] == "ACTIVE" and permit["expires_at"] is not None \
            and clock.now() >= permit["expires_at"]:
        permit["status"] = "EXPIRED"
        touch(permit)
        lic = db.licenses.get(permit["license_id"])
        if lic is not None:
            lic["active_server_count"] = max(lic["active_server_count"] - 1, 0)
            touch(lic)
    return ok(out(permit))
