"""AssetHolding endpoints."""

from flask import Blueprint, request

import errors
from db import db
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.common import (
    get_json_body, make_entity, req_bool, req_date, req_enum, req_int, req_string, touch,
)

bp = Blueprint("asset_holdings", __name__)
ALL = ("ComplianceOfficer", "TaxDirector", "BoardDirector")
ASSET_CLASSES = ("REAL_ESTATE", "QUALIFYING_SECURITY", "NON_QUALIFYING")


@bp.route("/reit-compliance/asset-holdings", methods=["POST"])
def create_asset():
    require_roles("ComplianceOfficer")
    body = get_json_body()
    reit_id = body.get("reit_id")
    if not isinstance(reit_id, str) or not reit_id:
        raise errors.validation("Field 'reit_id' is required")
    reit = db.reits.get(reit_id)
    if reit is None:
        raise errors.not_found("reit_id does not resolve to an existing REIT")

    asset_name = req_string(body, "asset_name")
    asset_class = req_enum(body, "asset_class", ASSET_CLASSES)
    held_by_trs = req_bool(body, "held_by_trs")
    is_dealer_inventory = req_bool(body, "is_dealer_inventory")
    acquisition_date = req_date(body, "acquisition_date")
    value_cents = req_int(body, "value_cents", min_value=0)

    asset = make_entity({
        "reit_id": reit_id,
        "asset_name": asset_name,
        "asset_class": asset_class,
        "held_by_trs": held_by_trs,
        "is_dealer_inventory": is_dealer_inventory,
        "acquisition_date": acquisition_date,
        "value_cents": value_cents,
        "status": "HELD",
    })
    db.asset_holdings[asset["id"]] = asset
    return success_object(dict(asset), status=201)


@bp.route("/reit-compliance/asset-holdings/<aid>", methods=["GET"])
def get_asset(aid):
    require_roles(*ALL)
    asset = db.asset_holdings.get(aid)
    if asset is None:
        raise errors.not_found("Asset holding not found")
    return success_object(dict(asset))


@bp.route("/reit-compliance/asset-holdings", methods=["GET"])
def list_assets():
    require_roles(*ALL)
    limit, offset = parse_pagination(request.args)
    rows = list(db.asset_holdings.values())
    reit_id = request.args.get("reit_id")
    if reit_id is not None:
        rows = [a for a in rows if a["reit_id"] == reit_id]
    page, total = paginate(rows, limit, offset)
    return success_list([dict(a) for a in page], limit, offset, total)


@bp.route("/reit-compliance/asset-holdings/<aid>", methods=["PATCH"])
def update_asset(aid):
    require_roles("ComplianceOfficer")
    asset = db.asset_holdings.get(aid)
    if asset is None:
        raise errors.not_found("Asset holding not found")
    if asset["status"] != "HELD":
        raise errors.invalid_state("Only HELD assets may be amended")

    body = get_json_body()
    if "value_cents" in body:
        v = body["value_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise errors.validation("value_cents must be an integer >= 0")
        asset["value_cents"] = v
    if "asset_class" in body:
        if body["asset_class"] not in ASSET_CLASSES:
            raise errors.validation("asset_class out of declared set")
        asset["asset_class"] = body["asset_class"]
    if "held_by_trs" in body:
        if not isinstance(body["held_by_trs"], bool):
            raise errors.validation("held_by_trs must be a boolean")
        asset["held_by_trs"] = body["held_by_trs"]
    if "is_dealer_inventory" in body:
        if not isinstance(body["is_dealer_inventory"], bool):
            raise errors.validation("is_dealer_inventory must be a boolean")
        asset["is_dealer_inventory"] = body["is_dealer_inventory"]

    touch(asset)
    return success_object(dict(asset))
