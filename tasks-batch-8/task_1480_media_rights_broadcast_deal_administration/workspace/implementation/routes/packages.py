import db
from errors import raise_error
from flask import Blueprint, request
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from serializers import serialize
from services import calculations as calc
from services.clock import parse_iso
from util import (apply_filters, get_json_body, get_pagination, paginate,
                  req_datetime, req_enum, req_int, req_string,
                  sorted_by_created, stamp_new, touch)

bp = Blueprint("packages", __name__)

PLATFORM_CLASSES = {"LINEAR_TV", "SVOD", "AVOD", "MOBILE", "RADIO", "SOCIAL_CLIP"}
EXCLUSIVITY_CLASSES = {"EXCLUSIVE", "CO_EXCLUSIVE", "NON_EXCLUSIVE"}


def get_package_or_404(package_id):
    p = db.packages.get(package_id)
    if p is None:
        raise_error("ERR_PACKAGE_NOT_FOUND")
    return p


def _bump_asset_package_count(asset_id):
    asset = db.rights_assets.get(asset_id)
    if asset is None:
        return
    count = sum(
        1 for p in db.packages.values()
        if p["asset_id"] == asset_id
        and p["status"] in ("DRAFT", "OPEN_FOR_BIDS", "UNDER_NEGOTIATION", "AWARDED")
    )
    if asset["active_package_count"] != count:
        asset["active_package_count"] = count
        touch(asset)


@bp.route("/packages", methods=["POST"])
def create_package():
    require_roles({"RightsManager"})
    body = get_json_body()
    asset_id = body.get("asset_id")
    if not isinstance(asset_id, str) or asset_id not in db.rights_assets:
        raise_error("ERR_ASSET_NOT_FOUND")
    asset = db.rights_assets[asset_id]
    package_code = req_string(body, "package_code")
    territory_code = req_string(body, "territory_code")
    platform_class = req_enum(body, "platform_class", PLATFORM_CLASSES)
    window_start = req_datetime(body, "window_start", parse_iso)
    window_end = req_datetime(body, "window_end", parse_iso)
    exclusivity_class = req_enum(body, "exclusivity_class", EXCLUSIVITY_CLASSES)
    minimum_bid_cents = req_int(body, "minimum_bid_cents", minimum=0)
    games_committed = req_int(body, "games_committed", minimum=0)
    if window_end <= window_start:
        raise_error("ERR_INVALID_REQUEST", "window_end must be strictly later than window_start")
    existing = [p for p in db.packages.values() if p["asset_id"] == asset_id]
    if len(existing) >= asset["total_package_pool"]:
        raise_error("ERR_INVALID_REQUEST", "total_package_pool reached for this asset")
    package = {
        "asset_id": asset_id,
        "package_code": package_code,
        "territory_code": territory_code,
        "platform_class": platform_class,
        "window_start": window_start,
        "window_end": window_end,
        "exclusivity_class": exclusivity_class,
        "minimum_bid_cents": minimum_bid_cents,
        "games_committed": games_committed,
        "status": "DRAFT",
        "awarded_bid_id": None,
        "awarded_deal_id": None,
    }
    stamp_new(package)
    db.packages[package["id"]] = package
    _bump_asset_package_count(asset_id)
    # Creating a package runs the exclusivity conflict scan (§2.9).
    calc.run_exclusivity_scan(asset_id)
    return success_object(serialize(package), status_code=201)


@bp.route("/packages", methods=["GET"])
def list_packages():
    require_roles(ALL_ROLES)
    limit, offset = get_pagination()
    items = sorted_by_created(list(db.packages.values()))
    items = apply_filters(items, [
        ("asset_id", request.args.get("asset_id")),
        ("status", request.args.get("status")),
        ("territory_code", request.args.get("territory_code")),
        ("platform_class", request.args.get("platform_class")),
        ("awarded_bid_id", request.args.get("awarded_bid_id")),
        ("awarded_deal_id", request.args.get("awarded_deal_id")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(p) for p in page], limit, offset, total)


@bp.route("/packages/<packageId>", methods=["GET"])
def get_package(packageId):
    require_roles(ALL_ROLES)
    return success_object(serialize(get_package_or_404(packageId)))


@bp.route("/packages/<packageId>/withdraw", methods=["POST"])
def withdraw_package(packageId):
    require_roles({"RightsManager"})
    package = get_package_or_404(packageId)
    if package["status"] not in ("OPEN_FOR_BIDS", "UNDER_NEGOTIATION"):
        raise_error("ERR_PACKAGE_NOT_WITHDRAWABLE")
    package["status"] = "WITHDRAWN"
    touch(package)
    from services.system import bid_terminal_statuses
    for bid in db.bids.values():
        if bid["package_id"] == package["id"] and bid["status"] not in bid_terminal_statuses():
            bid["status"] = "WITHDRAWN"
            touch(bid)
    _bump_asset_package_count(package["asset_id"])
    return success_object(serialize(package))
