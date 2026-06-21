"""Blood units: labeling, reads, reserve/unreserve/issue lifecycle."""
from flask import Blueprint, request

import db
import errors
import lookup
from common import get_json_body, paginate, require_enum, require_string
from errors import ApiError
from middleware import require_roles
from response import success, success_list
from services import domain
from services.serialize import serialize_unit
from timeutil import iso_to_epoch

bp = Blueprint("blood_units", __name__)

# donation_type -> compatible components
COMPONENT_COMPAT = {
    "WHOLE": {"RBC", "PLASMA", "WHOLE_BLOOD"},
    "PLASMA": {"PLASMA"},
    "PLATELET": {"PLATELET"},
}


@bp.route("/blood-bank/blood-units", methods=["POST"])
@require_roles("LabTechnician")
def label_unit():
    body = get_json_body()
    with db.lock:
        donation_id = require_string(body, "donation_id")
        component = require_enum(body, "component", domain.COMPONENTS)
        din = require_string(body, "din")

        donation = lookup.donation(donation_id)

        # component compatibility with parent donation_type (422)
        compatible = COMPONENT_COMPAT.get(donation["donation_type"], set())
        if component not in compatible:
            raise ApiError(errors.ERR_COMPONENT_TYPE_MISMATCH, 422,
                           "Component incompatible with the donation type.")

        center_id = donation["center_id"]
        # DIN unique among units at the center (409)
        for u in db.blood_units.values():
            if u["center_id"] == center_id and u["din"] == din:
                raise ApiError(errors.ERR_DUPLICATE_DIN, 409,
                               "DIN already used by another unit at the center.")

        donor = db.donors.get(donation["donor_id"])
        blood_type = donor["blood_type"] if donor is not None else "UNKNOWN"
        collected_at = donation["collected_at"]

        # collection-anchored expiry for RBC/PLASMA/WHOLE_BLOOD; platelet deferred
        if component == "PLATELET":
            expires_at = None
        else:
            expires_at = domain.collection_anchored_expiry(component, collected_at)

        unit = {
            "donation_id": donation_id,
            "donor_id": donation["donor_id"],
            "center_id": center_id,
            "component": component,
            "blood_type": blood_type,
            "din": din,
            "collected_at": collected_at,
            "released_at": None,
            "expires_at": expires_at,
            "status": "QUARANTINED",
        }
        db.stamp_new(unit)
        db.blood_units[unit["id"]] = unit
        return success(serialize_unit(unit), status=201)


@bp.route("/blood-bank/blood-units", methods=["GET"])
@require_roles("CenterAdmin", "LabTechnician", "InventoryManager")
def list_units():
    donation_id = request.args.get("donation_id")
    donor_id = request.args.get("donor_id")
    center_id = request.args.get("center_id")
    blood_type = request.args.get("blood_type")
    component = request.args.get("component")
    status = request.args.get("status")
    with db.lock:
        rows = list(db.blood_units.values())
        if donation_id is not None:
            rows = [u for u in rows if u["donation_id"] == donation_id]
        if donor_id is not None:
            rows = [u for u in rows if u["donor_id"] == donor_id]
        if center_id is not None:
            rows = [u for u in rows if u["center_id"] == center_id]
        if blood_type is not None:
            rows = [u for u in rows if u["blood_type"] == blood_type]
        if component is not None:
            rows = [u for u in rows if u["component"] == component]
        if status is not None:
            rows = [u for u in rows if u["status"] == status]
        page, limit, offset, total = paginate(rows)
        return success_list([serialize_unit(u) for u in page], limit, offset, total)


@bp.route("/blood-bank/blood-units/<unit_id>", methods=["GET"])
@require_roles("CenterAdmin", "LabTechnician", "InventoryManager")
def get_unit(unit_id):
    with db.lock:
        unit = lookup.blood_unit(unit_id)
        return success(serialize_unit(unit))


@bp.route("/blood-bank/blood-units/<unit_id>/reserve", methods=["POST"])
@require_roles("InventoryManager")
def reserve_unit(unit_id):
    with db.lock:
        unit = lookup.blood_unit(unit_id)
        center = db.centers.get(unit["center_id"])
        if unit["status"] != "AVAILABLE":
            raise ApiError(errors.ERR_UNIT_NOT_AVAILABLE, 409,
                           "Unit must be AVAILABLE to reserve.")
        # not expired: current_utc strictly before expires_at
        if unit.get("expires_at") is not None and \
                iso_to_epoch(center["current_utc"]) >= iso_to_epoch(unit["expires_at"]):
            raise ApiError(errors.ERR_UNIT_EXPIRED, 409,
                           "Unit is past its expiry and cannot be reserved.")
        unit["status"] = "RESERVED"
        db.touch(unit)
        domain.adjust_bucket(unit["center_id"], unit["blood_type"], unit["component"],
                             available_delta=-1, reserved_delta=1)
        return success(serialize_unit(unit))


@bp.route("/blood-bank/blood-units/<unit_id>/unreserve", methods=["POST"])
@require_roles("InventoryManager")
def unreserve_unit(unit_id):
    with db.lock:
        unit = lookup.blood_unit(unit_id)
        if unit["status"] != "RESERVED":
            raise ApiError(errors.ERR_UNIT_NOT_RESERVED, 409,
                           "Unit must be RESERVED to unreserve.")
        unit["status"] = "AVAILABLE"
        db.touch(unit)
        domain.adjust_bucket(unit["center_id"], unit["blood_type"], unit["component"],
                             available_delta=1, reserved_delta=-1)
        return success(serialize_unit(unit))


@bp.route("/blood-bank/blood-units/<unit_id>/issue", methods=["POST"])
@require_roles("InventoryManager")
def issue_unit(unit_id):
    with db.lock:
        unit = lookup.blood_unit(unit_id)
        if unit["status"] != "RESERVED":
            raise ApiError(errors.ERR_UNIT_NOT_RESERVED, 409,
                           "Unit must be RESERVED to issue.")
        unit["status"] = "ISSUED"
        db.touch(unit)
        domain.adjust_bucket(unit["center_id"], unit["blood_type"], unit["component"],
                             reserved_delta=-1)
        return success(serialize_unit(unit))
