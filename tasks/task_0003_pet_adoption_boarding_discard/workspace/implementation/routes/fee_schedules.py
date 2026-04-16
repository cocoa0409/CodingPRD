"""Fee schedule endpoints."""

from datetime import datetime, timezone
from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import require_role, get_pagination
from response import success_object, success_list
from errors import (raise_error, ERR_FEE_SCHEDULE_NOT_FOUND, ERR_SHELTER_NOT_FOUND,
                    ERR_INVALID_DATES, ERR_INVALID_REQUEST)

bp = Blueprint("fee_schedules", __name__)


def _parse_dt(s):
    if isinstance(s, datetime):
        return s
    s_clean = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s_clean)


def _compute_is_active(fs):
    now = datetime.now(timezone.utc)
    eff_from = _parse_dt(fs["effective_from"])
    if eff_from > now:
        return False
    if fs.get("effective_to"):
        eff_to = _parse_dt(fs["effective_to"])
        if eff_to <= now:
            return False
    return True


def serialize_fs(fs):
    result = dict(fs)
    result["is_active"] = _compute_is_active(fs)
    return result


@bp.route("/fee-schedules", methods=["POST"])
def create_fee_schedule():
    user_id, role = require_role("ShelterManager")
    body = request.get_json(force=True, silent=True) or {}

    required = ["shelter_id", "fee_type", "species", "amount", "effective_from"]
    for field in required:
        if field not in body or body[field] is None:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")

    shelter = db.shelters.get(body["shelter_id"])
    if not shelter:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")

    valid_types = ["ADOPTION_BASE", "BOARDING_DAILY", "SPECIAL_NEEDS_SURCHARGE", "VACCINATION_FEE", "LOYALTY_DISCOUNT"]
    if body["fee_type"] not in valid_types:
        raise_error(ERR_INVALID_REQUEST, f"Invalid fee_type: {body['fee_type']}")

    valid_species = ["DOG", "CAT", "RABBIT", "BIRD", "OTHER", "ALL"]
    if body["species"] not in valid_species:
        raise_error(ERR_INVALID_REQUEST, f"Invalid species: {body['species']}")

    # Validate dates
    if body.get("effective_to"):
        eff_from = _parse_dt(body["effective_from"])
        eff_to = _parse_dt(body["effective_to"])
        if eff_to <= eff_from:
            raise_error(ERR_INVALID_DATES, "effective_to must be after effective_from")

    ts = now_iso()
    fs = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "shelter_id": body["shelter_id"],
        "fee_type": body["fee_type"],
        "species": body["species"],
        "amount": body["amount"],
        "effective_from": body["effective_from"],
        "effective_to": body.get("effective_to"),
        "is_active": True,  # will be recomputed on read
    }
    db.fee_schedules[fs["id"]] = fs
    return success_object(serialize_fs(fs), 201)


@bp.route("/fee-schedules", methods=["GET"])
def list_fee_schedules():
    require_role("ShelterManager", "CaseWorker")
    limit, offset = get_pagination()

    items = list(db.fee_schedules.values())
    shelter_id = request.args.get("shelter_id")
    fee_type = request.args.get("fee_type")
    species = request.args.get("species")
    if shelter_id:
        items = [f for f in items if f["shelter_id"] == shelter_id]
    if fee_type:
        items = [f for f in items if f["fee_type"] == fee_type]
    if species:
        items = [f for f in items if f["species"] == species]

    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_fs(f) for f in page], total, limit, offset)


@bp.route("/fee-schedules/<feeScheduleId>", methods=["GET"])
def get_fee_schedule(feeScheduleId):
    require_role("ShelterManager", "CaseWorker")
    fs = db.fee_schedules.get(feeScheduleId)
    if not fs:
        raise_error(ERR_FEE_SCHEDULE_NOT_FOUND, "Fee schedule not found")
    return success_object(serialize_fs(fs))
