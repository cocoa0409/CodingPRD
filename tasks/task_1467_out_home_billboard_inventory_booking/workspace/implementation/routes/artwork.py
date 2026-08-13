"""ArtworkOrder endpoints (PRD 3.6)."""
from flask import Blueprint, request

import db
import domain
from errors import ApiError, err_invalid_request, err_invalid_state
from middleware import require_roles
from response import success
from serializers import artwork_out
from util import req_int, req_str, req_enum

bp = Blueprint("artwork", __name__, url_prefix="/api")

MATERIALS = ("VINYL", "POLYETHYLENE", "DIGITAL_FILE")
NON_TERMINAL = ("SUBMITTED", "IN_PRODUCTION", "REVISION_REQUESTED", "PRINTED",
                "SHIPPED")


def get_artwork_or_404(aid):
    a = db.artwork_orders.get(aid)
    if a is None:
        raise ApiError("ERR_ARTWORK_ORDER_NOT_FOUND", 404,
                       "Artwork order not found")
    return a


@bp.route("/artwork-orders", methods=["POST"])
def create_artwork_order():
    require_roles("ProductionCoordinator")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    flight_id = body.get("flight_id")
    if isinstance(flight_id, str) and flight_id not in db.flights:
        raise ApiError("ERR_FLIGHT_NOT_FOUND", 404, "Flight not found")

    # Family 4: shape (dimensions and material validated against the face)
    flight_id = req_str(body, "flight_id")
    creative_code = req_str(body, "creative_code")
    material = req_enum(body, "material", MATERIALS)
    width_inches = req_int(body, "width_inches", 1)
    height_inches = req_int(body, "height_inches", 1)

    flight = db.flights[flight_id]
    face = db.faces.get(flight["face_id"])
    if face is not None:
        if width_inches != face["width_inches"] \
                or height_inches != face["height_inches"]:
            raise ApiError("ERR_ARTWORK_DIMENSION_MISMATCH", 400,
                           "Artwork dimensions must equal the face dimensions")
        if face["display_type"] == "DIGITAL":
            if material != "DIGITAL_FILE":
                raise ApiError("ERR_MATERIAL_FACE_MISMATCH", 400,
                               "A DIGITAL face requires DIGITAL_FILE material")
        else:
            if material not in ("VINYL", "POLYETHYLENE"):
                raise ApiError("ERR_MATERIAL_FACE_MISMATCH", 400,
                               "A STATIC face requires VINYL or POLYETHYLENE")

    # Family 5: flight must be BOOKED
    if flight["status"] != "BOOKED":
        raise err_invalid_state(
            "Artwork may be submitted only for a BOOKED flight")

    # Family 12: one non-terminal artwork order per flight
    for other in db.artwork_orders.values():
        if other["flight_id"] == flight["id"] \
                and other["status"] in NON_TERMINAL:
            raise ApiError("ERR_ACTIVE_ARTWORK_ORDER_EXISTS", 409,
                           "The flight already has a non-terminal artwork "
                           "order")

    a = db.new_resource()
    a.update({
        "flight_id": flight["id"],
        "creative_code": creative_code,
        "material": material,
        "width_inches": width_inches,
        "height_inches": height_inches,
        "revision_count": 0,
        "production_charge_cents": 0,
        "status": "SUBMITTED",
    })
    db.artwork_orders[a["id"]] = a
    return success(artwork_out(a), code=201)


@bp.route("/artwork-orders/<aid>", methods=["PUT"])
def update_artwork_order(aid):
    require_roles("ProductionCoordinator")
    a = get_artwork_or_404(aid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    new_status = body.get("status")
    if not isinstance(new_status, str) or new_status not in (
            "SUBMITTED", "IN_PRODUCTION", "REVISION_REQUESTED", "PRINTED",
            "SHIPPED", "DELIVERED", "CANCELLED"):
        raise err_invalid_request("status is required and must be a valid "
                                  "artwork-order status")

    cur = a["status"]
    allowed = {
        ("SUBMITTED", "IN_PRODUCTION"),
        ("IN_PRODUCTION", "REVISION_REQUESTED"),
        ("REVISION_REQUESTED", "SUBMITTED"),
        ("IN_PRODUCTION", "PRINTED"),
        ("PRINTED", "SHIPPED"),
        ("SHIPPED", "DELIVERED"),
        ("SUBMITTED", "CANCELLED"),
        ("IN_PRODUCTION", "CANCELLED"),
        ("REVISION_REQUESTED", "CANCELLED"),
    }
    if (cur, new_status) not in allowed:
        raise err_invalid_state(
            "Artwork order cannot transition %s -> %s" % (cur, new_status))

    if (cur, new_status) == ("IN_PRODUCTION", "REVISION_REQUESTED"):
        a["revision_count"] += 1
    a["status"] = new_status
    db.touch(a)

    if new_status == "DELIVERED":
        charge = max(0, a["revision_count"] - 2) * 35000
        a["production_charge_cents"] = charge
        db.touch(a)
        flight = db.flights.get(a["flight_id"])
        if flight is not None:
            campaign = db.campaigns.get(flight["campaign_id"])
            if campaign is not None:
                campaign["production_charges_cents"] += charge
                db.touch(campaign)
            if flight["status"] == "BOOKED":
                flight["status"] = "ART_CLEARED"
                db.touch(flight)
            if campaign is not None:
                domain.recompute_delivery_posture(campaign)

    return success(artwork_out(a))
