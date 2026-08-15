"""Freezer zones and inventory lots (PRD §3.7)."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_COMPLAINT_STILL_OPEN,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from services import quarantine_lot_cascade, serialize
from util import (
    apply_filters,
    body_json,
    check_shape,
    paginate,
    pagination_params,
    path_entity,
)

bp = Blueprint("zones", __name__)

ZONE_SPEC = {
    "zone_code": {"type": "string", "required": True},
    "pallet_capacity": {"type": "integer", "min": 1, "required": True},
}


@bp.route("/freezer-zones", methods=["POST"])
def create_zone():
    authenticate({"PlantManager"})
    body = body_json()
    check_shape(body, ZONE_SPEC)
    zone = db.new_entity("zones", {
        "zone_code": body["zone_code"],
        "pallet_capacity": body["pallet_capacity"],
    })
    return success_obj(serialize("zones", zone), 201)


@bp.route("/freezer-zones", methods=["GET"])
def list_zones():
    authenticate(ALL_ROLES)
    items = apply_filters(db.all_of("zones"), [])
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("zones", e) for e in page],
                        limit, offset, total, has_more)


@bp.route("/freezer-zones/<zone_id>", methods=["GET"])
def get_zone(zone_id):
    authenticate(ALL_ROLES)
    zone = path_entity("zones", zone_id, "freezer zone")
    return success_obj(serialize("zones", zone))


@bp.route("/inventory-lots", methods=["GET"])
def list_lots():
    authenticate(ALL_ROLES)
    items = apply_filters(
        db.all_of("lots"), ["product_id", "run_id", "zone_id", "status"]
    )
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("lots", e) for e in page],
                        limit, offset, total, has_more)


@bp.route("/inventory-lots/<lot_id>", methods=["GET"])
def get_lot(lot_id):
    authenticate(ALL_ROLES)
    lot = path_entity("lots", lot_id, "inventory lot")
    return success_obj(serialize("lots", lot))


@bp.route("/inventory-lots/<lot_id>/quarantine", methods=["POST"])
def quarantine_lot(lot_id):
    user_id, _role = authenticate({"QAManager"})
    lot = path_entity("lots", lot_id, "inventory lot")
    if lot["status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE, 409, "lot is not AVAILABLE")
    quarantine_lot_cascade(lot, user_id)
    return success_obj(serialize("lots", lot))


@bp.route("/inventory-lots/<lot_id>/release-quarantine", methods=["POST"])
def release_lot_quarantine(lot_id):
    user_id, _role = authenticate({"QAManager"})
    lot = path_entity("lots", lot_id, "inventory lot")
    if lot["status"] != "QUARANTINED":
        raise ApiError(ERR_INVALID_STATE, 409, "lot is not QUARANTINED")
    # Segregation of duties (PRD §2.8): releaser != quarantiner.
    if user_id == lot["quarantined_by"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            403,
            "releaser must differ from the quarantiner",
        )
    # Priority 32: blocked while any complaint on the same run is open.
    same_run_lot_ids = {
        other["id"] for other in db.all_of("lots") if other["run_id"] == lot["run_id"]
    }
    for complaint in db.all_of("complaints"):
        if (
            complaint["lot_id"] in same_run_lot_ids
            and complaint["status"] in ("UNDER_REVIEW", "LAB_TEST")
        ):
            raise ApiError(
                ERR_COMPLAINT_STILL_OPEN,
                422,
                "a complaint on the same run is still open",
            )
    lot["status"] = "AVAILABLE"
    db.touch(lot)
    return success_obj(serialize("lots", lot))


@bp.route("/inventory-lots/<lot_id>/destroy", methods=["POST"])
def destroy_lot(lot_id):
    authenticate({"QAManager"})
    lot = path_entity("lots", lot_id, "inventory lot")
    if lot["status"] != "QUARANTINED":
        raise ApiError(ERR_INVALID_STATE, 409, "lot is not QUARANTINED")
    # lot_units_conservation: available units move to destroyed.
    lot["units_destroyed"] += lot["units_available"]
    lot["units_available"] = 0
    lot["status"] = "DESTROYED"
    db.touch(lot)
    return success_obj(serialize("lots", lot))
