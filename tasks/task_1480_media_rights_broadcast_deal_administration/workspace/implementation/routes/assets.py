import db
from errors import raise_error
from flask import Blueprint, request
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from serializers import serialize
from services.system import deal_terminal_statuses
from util import (apply_filters, get_pagination, paginate, req_datetime,
                  req_int, req_string, sorted_by_created, stamp_new, touch)
from services.clock import parse_iso

bp = Blueprint("assets", __name__)


def _get_asset_or_404(asset_id):
    asset = db.rights_assets.get(asset_id)
    if asset is None:
        raise_error("ERR_ASSET_NOT_FOUND")
    return asset


def _recompute_active_package_count(asset):
    count = sum(
        1 for p in db.packages.values()
        if p["asset_id"] == asset["id"]
        and p["status"] in ("DRAFT", "OPEN_FOR_BIDS", "UNDER_NEGOTIATION", "AWARDED")
    )
    if asset["active_package_count"] != count:
        asset["active_package_count"] = count


@bp.route("/rights-assets", methods=["POST"])
def create_asset():
    require_roles({"RightsManager"})
    from util import get_json_body
    body = get_json_body()
    asset_code = req_string(body, "asset_code")
    competition_name = req_string(body, "competition_name")
    season_label = req_string(body, "season_label")
    season_start = req_datetime(body, "season_start_date", parse_iso)
    season_end = req_datetime(body, "season_end_date", parse_iso)
    total_package_pool = req_int(body, "total_package_pool", minimum=1)
    guaranteed_rating_bp = req_int(body, "guaranteed_rating_basis_points")
    if season_end <= season_start:
        raise_error("ERR_INVALID_REQUEST", "season_end_date must be strictly later than season_start_date")
    asset = {
        "asset_code": asset_code,
        "competition_name": competition_name,
        "season_label": season_label,
        "season_start_date": season_start,
        "season_end_date": season_end,
        "total_package_pool": total_package_pool,
        "guaranteed_rating_basis_points": guaranteed_rating_bp,
        "status": "OPEN",
        "active_package_count": 0,
    }
    stamp_new(asset)
    db.rights_assets[asset["id"]] = asset
    return success_object(serialize(asset), status_code=201)


@bp.route("/rights-assets", methods=["GET"])
def list_assets():
    require_roles(ALL_ROLES)
    limit, offset = get_pagination()
    items = sorted_by_created(list(db.rights_assets.values()))
    items = apply_filters(items, [("status", request.args.get("status"))])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(a) for a in page], limit, offset, total)


@bp.route("/rights-assets/<assetId>", methods=["GET"])
def get_asset(assetId):
    require_roles(ALL_ROLES)
    asset = _get_asset_or_404(assetId)
    return success_object(serialize(asset))


@bp.route("/rights-assets/<assetId>/lock-packages", methods=["POST"])
def lock_packages(assetId):
    require_roles({"RightsManager"})
    asset = _get_asset_or_404(assetId)
    if asset["status"] != "OPEN":
        raise_error("ERR_ASSET_NOT_OPEN")
    # Validate every DRAFT package definition.
    for p in db.packages.values():
        if p["asset_id"] != asset["id"] or p["status"] != "DRAFT":
            continue
        if (p["window_start"] < asset["season_start_date"]
                or p["window_end"] > asset["season_end_date"]
                or not p["territory_code"]
                or p["games_committed"] < 0):
            raise_error("ERR_PACKAGE_DEFINITION_INVALID",
                        f"Package {p['package_code']} definition invalid at lock time")
    for p in db.packages.values():
        if p["asset_id"] == asset["id"] and p["status"] == "DRAFT":
            p["status"] = "OPEN_FOR_BIDS"
            touch(p)
    asset["status"] = "PACKAGES_LOCKED"
    touch(asset)
    _recompute_active_package_count(asset)
    # Packages entering OPEN_FOR_BIDS become visible to the exclusivity scan.
    from services import calculations as calc
    calc.run_exclusivity_scan(asset["id"])
    return success_object(serialize(asset))


@bp.route("/rights-assets/<assetId>/close-awards", methods=["POST"])
def close_awards(assetId):
    require_roles({"RightsManager"})
    asset = _get_asset_or_404(assetId)
    if asset["status"] != "PACKAGES_LOCKED":
        raise_error("ERR_ASSET_NOT_LOCKED")
    for p in db.packages.values():
        if p["asset_id"] == asset["id"] and p["status"] not in ("AWARDED", "WITHDRAWN"):
            raise_error("ERR_UNRESOLVED_PACKAGES_EXIST")
    asset["status"] = "AWARD_CLOSED"
    touch(asset)
    return success_object(serialize(asset))


@bp.route("/rights-assets/<assetId>/retire", methods=["POST"])
def retire_asset(assetId):
    require_roles({"RightsManager"})
    asset = _get_asset_or_404(assetId)
    if asset["status"] != "AWARD_CLOSED":
        raise_error("ERR_ASSET_NOT_AWARD_CLOSED")
    for d in db.deals.values():
        if d["asset_id"] == asset["id"] and d["status"] not in deal_terminal_statuses():
            raise_error("ERR_DEALS_STILL_ACTIVE")
    asset["status"] = "RETIRED"
    touch(asset)
    return success_object(serialize(asset))
