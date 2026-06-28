"""Authorization endpoints + reauthorization cycle (PRD §3.4, §2.9)."""

from flask import Blueprint

import errors
from errors import ApiError
from db import db
from response import success
from middleware import require_roles, ALL_ROLES
from validation import get_body, require_str, require_int, require_enum, require_iso_datetime, bad
from services.common import new_record, touch, lookup
from services import serialize, engine, calc
from clock import format_iso

bp = Blueprint("authorizations", __name__)


@bp.route("/clinic/authorizations", methods=["POST"])
@require_roles("ClinicAdmin")
def create_authorization(user_id=None, role=None):
    body = get_body()
    child_id = require_str(body, "child_id")
    discipline = require_enum(body, "discipline", {"SLP", "OT"})
    payer_name = require_str(body, "payer_name")
    authorized = require_int(body, "authorized_visits", minimum=1)
    valid_from = require_iso_datetime(body, "valid_from")
    valid_until = require_iso_datetime(body, "valid_until")
    lookup(db.children, child_id)
    rec = new_record({
        "child_id": child_id,
        "discipline": discipline,
        "payer_name": payer_name,
        "authorized_visits": authorized,
        "valid_from": format_iso(valid_from),
        "valid_until": format_iso(valid_until),
        "reserved_visits": 0,
        "committed_visits": 0,
        "available_visits": authorized,
        "status": "ACTIVE",
    })
    db.authorizations[rec["id"]] = rec
    return success(serialize.authorization(rec), status=201)


@bp.route("/clinic/authorizations/<authorization_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_authorization(authorization_id, user_id=None, role=None):
    rec = lookup(db.authorizations, authorization_id)
    return success(serialize.authorization(rec), status=200)


@bp.route("/clinic/authorizations/<authorization_id>/request-reauth", methods=["POST"])
@require_roles("ClinicAdmin")
def request_reauth(authorization_id, user_id=None, role=None):
    auth = lookup(db.authorizations, authorization_id)
    body = get_body()
    expected = require_int(body, "expected_authorization_version")
    # State legality before OCC (PRD §2.9): ACTIVE or EXHAUSTED.
    if auth["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise ApiError(errors.ERR_AUTH_NOT_REAUTHABLE, 409,
                       "Authorization must be ACTIVE or EXHAUSTED to request reauth.")
    # OCC check after state legality, before further business rules.
    if expected != auth["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412,
                       "Authorization version is stale.")
    auth["status"] = "REAUTH_REQUESTED"
    touch(auth)
    return success(serialize.authorization(auth), status=200)


@bp.route("/clinic/authorizations/<authorization_id>/grant-reauth", methods=["POST"])
@require_roles("ClinicAdmin")
def grant_reauth(authorization_id, user_id=None, role=None):
    auth = lookup(db.authorizations, authorization_id)
    body = get_body()
    # State legality before OCC.
    if auth["status"] != "REAUTH_REQUESTED":
        raise ApiError(errors.ERR_AUTH_NOT_IN_REAUTH, 409,
                       "Authorization must be REAUTH_REQUESTED to grant reauth.")
    expected = require_int(body, "expected_authorization_version")
    # OCC check after state legality, before business rules.
    if expected != auth["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412,
                       "Authorization version is stale.")
    additional = require_int(body, "additional_visits", minimum=1)
    new_valid_until = require_iso_datetime(body, "new_valid_until")
    auth["authorized_visits"] += additional
    auth["valid_until"] = format_iso(new_valid_until)
    # Recompute available; if > 0, return to ACTIVE.
    calc.recompute_authorization_counts(auth)
    if auth["available_visits"] > 0:
        auth["status"] = "ACTIVE"
    touch(auth)
    return success(serialize.authorization(auth), status=200)


@bp.route("/clinic/authorizations/<authorization_id>/close", methods=["POST"])
@require_roles("ClinicAdmin")
def close_authorization(authorization_id, user_id=None, role=None):
    auth = lookup(db.authorizations, authorization_id)
    if auth["status"] not in ("EXPIRED", "EXHAUSTED"):
        raise ApiError(errors.ERR_AUTH_NOT_CLOSEABLE, 409,
                       "Authorization must be EXPIRED or EXHAUSTED to close.")
    if auth["reserved_visits"] != 0:
        raise ApiError(errors.ERR_OUTSTANDING_RESERVATIONS, 409,
                       "Authorization has outstanding reservations.")
    auth["status"] = "CLOSED"
    touch(auth)
    return success(serialize.authorization(auth), status=200)
