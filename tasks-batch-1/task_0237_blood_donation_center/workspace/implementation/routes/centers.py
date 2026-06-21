"""Donation centers and the deterministic clock."""
from flask import Blueprint

import db
import errors
import lookup
from common import get_json_body, paginate, require_iso_datetime, require_string
from errors import ApiError
from middleware import require_roles
from response import success, success_list
from services import domain
from services.serialize import serialize_center
from timeutil import EPOCH_ISO, iso_to_epoch, normalize_iso

bp = Blueprint("centers", __name__)

ALL_ROLES = ("CenterAdmin", "IntakeNurse", "LabTechnician", "InventoryManager", "Donor")


@bp.route("/blood-bank/centers", methods=["POST"])
@require_roles("CenterAdmin")
def create_center():
    body = get_json_body()
    name = require_string(body, "name")
    region_code = require_string(body, "region_code")
    with db.lock:
        center = {
            "name": name,
            "region_code": region_code,
            "current_utc": EPOCH_ISO,
        }
        db.stamp_new(center)
        db.centers[center["id"]] = center
        return success(serialize_center(center), status=201)


@bp.route("/blood-bank/centers", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_centers():
    from flask import request
    region = request.args.get("region_code")
    with db.lock:
        rows = list(db.centers.values())
        if region is not None:
            rows = [c for c in rows if c["region_code"] == region]
        page, limit, offset, total = paginate(rows)
        return success_list([serialize_center(c) for c in page], limit, offset, total)


@bp.route("/blood-bank/centers/<center_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_center(center_id):
    with db.lock:
        center = lookup.center(center_id)
        return success(serialize_center(center))


@bp.route("/blood-bank/centers/<center_id>/clock/advance", methods=["POST"])
@require_roles("CenterAdmin")
def advance_clock(center_id):
    body = get_json_body()
    with db.lock:
        center = lookup.center(center_id)
        target = require_iso_datetime(body, "to_iso8601")
        target_epoch = iso_to_epoch(target)
        current_epoch = iso_to_epoch(center["current_utc"])
        if target_epoch <= current_epoch:
            raise ApiError(
                errors.ERR_CLOCK_NOT_MONOTONIC,
                409,
                "Clock can only advance strictly forward.",
            )
        center["current_utc"] = normalize_iso(target)
        db.touch(center)

        # Sweep 1: TEMPORARY ACTIVE deferrals whose expires_at <= current_utc.
        affected_donor_ids = set()
        for deferral in db.deferrals.values():
            if (deferral["status"] == "ACTIVE"
                    and deferral["kind"] == "TEMPORARY"
                    and deferral.get("expires_at")
                    and target_epoch >= iso_to_epoch(deferral["expires_at"])):
                deferral["status"] = "EXPIRED"
                db.touch(deferral)
                affected_donor_ids.add(deferral["donor_id"])
        for donor_id in affected_donor_ids:
            donor = db.donors.get(donor_id)
            if donor is not None:
                domain.recompute_donor(donor, center)

        # Sweep 2: AVAILABLE units whose expires_at <= current_utc -> EXPIRED.
        for unit in db.blood_units.values():
            if (unit["status"] == "AVAILABLE"
                    and unit.get("expires_at")
                    and target_epoch >= iso_to_epoch(unit["expires_at"])):
                unit["status"] = "EXPIRED"
                db.touch(unit)
                domain.adjust_bucket(unit["center_id"], unit["blood_type"],
                                     unit["component"], available_delta=-1)

        return success(serialize_center(center))
