"""Confined space registry (PRD section 3.1) with OCC (section 2.7)."""

from flask import Blueprint, request

import db
import serializers
from errors import (
    ERR_INVALID_REQUEST, ERR_PERMITS_STILL_OPEN, ERR_SPACE_NOT_FOUND,
    ERR_STALE_VERSION, raise_error,
)
from helpers import (
    body, list_response, opt_bool, opt_enum, opt_int, reject_unknown,
    req_bool, req_enum, req_int, req_string, stamp_new, touch,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from routes.accounts import get_account
from services import NON_TERMINAL_PERMIT_STATES

bp = Blueprint("spaces", __name__)

CLASSIFICATIONS = ("NON_PERMIT", "PERMIT_REQUIRED", "PERMIT_REQUIRED_HAZARDOUS")
EXPOSURE_STANDARDS = ("TWA8", "PEAK_CEILING")
SPACE_STATUSES = ("AVAILABLE", "OUT_OF_SERVICE")


def get_space(space_id):
    space = db.confined_spaces.get(space_id)
    if space is None:
        raise_error(ERR_SPACE_NOT_FOUND, "Confined space not found")
    return space


def check_expected_space_version(data, space):
    """OCC (priority 6): expected_space_version is non-optional on the four
    space-serializing writes and must equal ConfinedSpace.version."""
    if "expected_space_version" not in data or data["expected_space_version"] is None:
        raise_error(ERR_INVALID_REQUEST, "Missing required field: expected_space_version")
    value = data["expected_space_version"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise_error(ERR_INVALID_REQUEST, "Field 'expected_space_version' must be an integer")
    if value != space["version"]:
        raise_error(ERR_STALE_VERSION, "expected_space_version does not match the space's current version")


def _has_non_terminal_permits(space_id):
    return any(p["space_id"] == space_id and p["status"] in NON_TERMINAL_PERMIT_STATES
               for p in db.entry_permits.values())


@bp.route("/rescue-ops/client-accounts/<account_id>/confined-spaces", methods=["POST"])
def create_space(account_id):
    require_auth(("OperationsManager",))
    account = get_account(account_id)
    data = body()
    reject_unknown(data, {
        "space_code", "classification", "requires_continuous_monitoring",
        "max_entrants", "ventilation_required", "blind_flange_required",
        "exposure_standard",
    })
    max_entrants = req_int(data, "max_entrants")
    if max_entrants <= 0:
        raise_error(ERR_INVALID_REQUEST, "max_entrants must be positive")
    space = {
        "client_account_id": account["id"],
        "space_code": req_string(data, "space_code"),
        "classification": req_enum(data, "classification", CLASSIFICATIONS),
        "requires_continuous_monitoring": req_bool(data, "requires_continuous_monitoring"),
        "max_entrants": max_entrants,
        "ventilation_required": req_bool(data, "ventilation_required"),
        "blind_flange_required": req_bool(data, "blind_flange_required"),
        "exposure_standard": req_enum(data, "exposure_standard", EXPOSURE_STANDARDS),
        "status": "AVAILABLE",
    }
    stamp_new(space)
    db.confined_spaces[space["id"]] = space
    return success_object(serializers.confined_space(space), 201)


@bp.route("/rescue-ops/confined-spaces", methods=["GET"])
def list_spaces():
    require_auth(ALL_ROLES)
    return list_response(list(db.confined_spaces.values()), serializers.confined_space, {
        "client_account_id": request.args.get("client_account_id"),
        "classification": request.args.get("classification"),
        "status": request.args.get("status"),
    })


@bp.route("/rescue-ops/confined-spaces/<space_id>", methods=["GET"])
def get_one_space(space_id):
    require_auth(ALL_ROLES)
    return success_object(serializers.confined_space(get_space(space_id)))


@bp.route("/rescue-ops/confined-spaces/<space_id>", methods=["PATCH"])
def update_space(space_id):
    require_auth(("OperationsManager", "SafetyOfficer"))
    space = get_space(space_id)
    data = body()
    reject_unknown(data, {
        "classification", "max_entrants", "requires_continuous_monitoring",
        "status", "expected_space_version",
    })
    classification = opt_enum(data, "classification", CLASSIFICATIONS, None)
    max_entrants = opt_int(data, "max_entrants", None)
    if max_entrants is not None and max_entrants <= 0:
        raise_error(ERR_INVALID_REQUEST, "max_entrants must be positive")
    rcm = opt_bool(data, "requires_continuous_monitoring", None)
    status = opt_enum(data, "status", SPACE_STATUSES, None)
    check_expected_space_version(data, space)
    # Guardrails (PRD 3.1): downgrade to NON_PERMIT or OUT_OF_SERVICE is
    # rejected while any of the space's permits is non-terminal.
    if classification == "NON_PERMIT" and _has_non_terminal_permits(space["id"]):
        raise_error(ERR_PERMITS_STILL_OPEN,
                    "Cannot downgrade classification to NON_PERMIT while permits are non-terminal")
    if status == "OUT_OF_SERVICE" and _has_non_terminal_permits(space["id"]):
        raise_error(ERR_PERMITS_STILL_OPEN,
                    "Cannot set status OUT_OF_SERVICE while permits are non-terminal")
    if classification is not None:
        space["classification"] = classification
    if max_entrants is not None:
        space["max_entrants"] = max_entrants
    if rcm is not None:
        space["requires_continuous_monitoring"] = rcm
    if status is not None:
        space["status"] = status
    touch(space)
    return success_object(serializers.confined_space(space))
