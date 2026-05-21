"""TransitCenter endpoints."""
from flask import Blueprint

from .. import store
from ..auth import authed
from ..envelope import success_object
from ..errors import raise_error
from ..serializers import serialize_transit_center
from ._helpers import get_json_body, is_tc_code, require


bp = Blueprint("transit_centers", __name__)


@bp.post("/transit-centers")
@authed(["Dispatcher"])
def create_tc(user_id, user_role):
    body = get_json_body()
    code = require(body, "code")
    prefixes = require(body, "serviced_postal_prefixes")
    hazmat_certified = bool(body.get("hazmat_certified", False))

    if not is_tc_code(code):
        raise_error("ERR_REFERENCE_NOT_FOUND", "code must be 3 uppercase letters")
    if not isinstance(prefixes, list) or not all(
        isinstance(p, str) and len(p) == 3 and p.isdigit() for p in prefixes
    ):
        raise_error(
            "ERR_REFERENCE_NOT_FOUND",
            "serviced_postal_prefixes must be a list of 3-digit strings",
        )

    # Optional latitude/longitude for distance calc (PRD references stored coords).
    latitude = body.get("latitude", 0.0)
    longitude = body.get("longitude", 0.0)
    try:
        latitude = float(latitude) if latitude is not None else 0.0
        longitude = float(longitude) if longitude is not None else 0.0
    except Exception:
        raise_error("ERR_REFERENCE_NOT_FOUND", "lat/lon must be numbers")
    if latitude < -90.0 or latitude > 90.0:
        raise_error("ERR_REFERENCE_NOT_FOUND", "latitude out of range")
    if longitude < -180.0 or longitude > 180.0:
        raise_error("ERR_REFERENCE_NOT_FOUND", "longitude out of range")

    with store.lock:
        for existing in store.transit_centers.values():
            if existing.get("code") == code:
                raise_error("ERR_REFERENCE_NOT_FOUND", "code already exists")
        tc = {
            "code": code,
            "serviced_postal_prefixes": prefixes,
            "hazmat_certified": hazmat_certified,
            "parcels_on_belt": 0,
            "latitude": latitude,
            "longitude": longitude,
        }
        store.stamp_create(tc)
        store.transit_centers[tc["id"]] = tc
        return success_object(serialize_transit_center(tc), status=201)


@bp.get("/transit-centers/<tcid>")
@authed(["Dispatcher", "SortingHubOperator", "ComplianceOfficer"])
def read_tc(user_id, user_role, tcid):
    with store.lock:
        tc = store.transit_centers.get(tcid)
        if not tc:
            raise_error("ERR_NOT_FOUND", "transit center not found")
        return success_object(serialize_transit_center(tc))
