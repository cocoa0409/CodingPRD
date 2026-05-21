"""Plate endpoints — read, suspend, reinstate, surrender."""

from flask import Blueprint

from config import (
    PLATE_ACTIVE,
    PLATE_SURRENDERED,
    PLATE_SURRENDER_REASONS,
    PLATE_SUSPENDED,
    REALID_ENFORCEMENT_ISO,
    REAL_ID_REVOKED,
    ROLE_APPLICANT,
    ROLE_PLATE_ISSUER,
    ROLE_PLATFORM_ADMIN,
    TITLE_STATUS_CLEAN,
    TITLE_STATUS_REBUILT,
)
from db import store
from errors import make_error
from middleware import parse_json_body, require_auth
from response import success
from routes._helpers import require_enum, require_field
from services.engine import stamp_update
from services.serializers import serialize_plate
from utils import iso_format, parse_iso8601

plates_bp = Blueprint("plates", __name__)


def _get_plate_or_404(plate_id: str) -> dict:
    plate = store.plates.get(plate_id)
    if plate is None:
        raise make_error("ERR_RESOURCE_NOT_FOUND")
    return plate


@plates_bp.route("/plates/<plate_id>", methods=["GET"])
@require_auth(allowed_roles=[ROLE_PLATFORM_ADMIN, ROLE_APPLICANT, ROLE_PLATE_ISSUER])
def read_plate(plate_id: str):
    plate = _get_plate_or_404(plate_id)
    return success(serialize_plate(plate))


@plates_bp.route("/plates/<plate_id>/suspend", methods=["POST"])
@require_auth(allowed_roles=[ROLE_PLATFORM_ADMIN])
def suspend_plate(plate_id: str):
    parse_json_body()
    with store.lock:
        plate = _get_plate_or_404(plate_id)
        if plate["status"] != PLATE_ACTIVE:
            raise make_error("ERR_INVALID_STATE")
        plate["status"] = PLATE_SUSPENDED
        plate["suspended_at"] = iso_format(store.now())
        stamp_update(plate, now=store.now())
    return success(serialize_plate(plate))


@plates_bp.route("/plates/<plate_id>/reinstate", methods=["POST"])
@require_auth(allowed_roles=[ROLE_PLATFORM_ADMIN])
def reinstate_plate(plate_id: str):
    parse_json_body()
    with store.lock:
        plate = _get_plate_or_404(plate_id)
        if plate["status"] != PLATE_SUSPENDED:
            raise make_error("ERR_INVALID_STATE")

        vehicle = store.vehicles.get(plate["vehicle_id"])
        if vehicle is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        if vehicle["title_status"] not in (TITLE_STATUS_CLEAN, TITLE_STATUS_REBUILT):
            raise make_error("ERR_VEHICLE_SALVAGE_LOCKED")

        # REAL ID gate: must be non-REVOKED, OR now < enforcement instant
        owner_id = None
        cur_title_id = vehicle.get("current_title_id")
        if cur_title_id:
            title = store.titles.get(cur_title_id)
            if title is not None:
                owner_id = title.get("owner_id")
        owner = store.owners.get(owner_id) if owner_id else None
        if owner is not None and owner.get("real_id_status") == REAL_ID_REVOKED:
            enforcement_dt = parse_iso8601(REALID_ENFORCEMENT_ISO)
            if store.now() >= enforcement_dt:
                raise make_error("ERR_OWNER_REAL_ID_REVOKED")

        plate["status"] = PLATE_ACTIVE
        plate["suspended_at"] = None
        stamp_update(plate, now=store.now())
    return success(serialize_plate(plate))


@plates_bp.route("/plates/<plate_id>/surrender", methods=["POST"])
@require_auth(allowed_roles=[ROLE_PLATFORM_ADMIN])
def surrender_plate(plate_id: str):
    body = parse_json_body()
    surrender_reason = require_enum(require_field(body, "surrender_reason"),
                                    "surrender_reason", PLATE_SURRENDER_REASONS)
    with store.lock:
        plate = _get_plate_or_404(plate_id)
        if plate["status"] not in (PLATE_ACTIVE, PLATE_SUSPENDED):
            raise make_error("ERR_INVALID_STATE")
        plate["status"] = PLATE_SURRENDERED
        plate["surrender_reason"] = surrender_reason
        stamp_update(plate, now=store.now())
    return success(serialize_plate(plate))
