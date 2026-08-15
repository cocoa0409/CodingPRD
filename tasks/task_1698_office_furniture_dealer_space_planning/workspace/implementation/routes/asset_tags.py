"""AssetTag routes: asset inventory registration and disposal."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_STATE
from middleware import ALL_ROLES
from response import success_object
from routes.helpers import authorize, list_response, get_response
from serialize import public
from services.core import get_or_404, new_entity, touch
from validate import body_dict, req_str, req_enum

bp = Blueprint("asset_tags", __name__)

CONDITIONS = {"NEW", "GOOD", "FAIR", "POOR"}
SOURCES = {"PURCHASED", "TRADED_IN"}


@bp.route("/api/asset-tags", methods=["POST"])
def create_asset_tag():
    authorize(["AccountExecutive"])
    body = body_dict()
    customer_id = req_str(body, "customer_id")
    description = req_str(body, "description")
    condition = req_enum(body, "condition", CONDITIONS)
    current_location = req_str(body, "current_location")
    source = req_enum(body, "source", SOURCES)
    series_id = body.get("series_id")
    if series_id is not None:
        if not isinstance(series_id, str):
            from errors import ERR_INVALID_REQUEST
            raise_error(ERR_INVALID_REQUEST, "series_id must be a string")
        get_or_404("product_series", series_id)
    get_or_404("customers", customer_id)
    asset = new_entity("asset_tags", {
        "customer_id": customer_id,
        "series_id": series_id,
        "description": description,
        "condition": condition,
        "current_location": current_location,
        "source": source,
        # PURCHASED assets start IN_SERVICE; TRADED_IN start IN_STORAGE
        "status": "IN_SERVICE" if source == "PURCHASED" else "IN_STORAGE",
    })
    return success_object(public(asset), status=201)


@bp.route("/api/asset-tags", methods=["GET"])
def list_asset_tags():
    authorize(ALL_ROLES)
    return list_response("asset_tags", ["customer_id", "series_id", "status"])


@bp.route("/api/asset-tags/<asset_id>", methods=["GET"])
def get_asset_tag(asset_id):
    authorize(ALL_ROLES)
    return get_response("asset_tags", asset_id)


@bp.route("/api/asset-tags/<asset_id>/dispose", methods=["POST"])
def dispose_asset_tag(asset_id):
    authorize(["AccountExecutive"])
    asset = get_or_404("asset_tags", asset_id)
    if asset["status"] not in ("IN_SERVICE", "IN_STORAGE"):
        raise_error(ERR_INVALID_STATE, f"cannot dispose an asset in status {asset['status']}")
    asset["status"] = "DISPOSED"
    touch(asset)
    return success_object(public(asset))
