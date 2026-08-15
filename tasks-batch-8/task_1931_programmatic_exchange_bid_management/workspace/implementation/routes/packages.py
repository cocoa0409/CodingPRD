"""Inventory package endpoints (PRD §3.2) plus the fee transparency report."""

from flask import Blueprint, request

from db import store
from errors import (
    not_found, invalid_state, stale_version, unauthorized, ApiError,
    ERR_PUBLISHER_SUSPENDED,
)
from middleware import require_roles, ALL_ROLES, ROLE_PUBLISHER_MANAGER
from response import success_object, success_list, paginate
from util import (
    get_body, req_str, opt_str, req_int, opt_int, req_enum, opt_enum,
    req_category_tags, opt_category_tags,
)
from services.core import (
    AD_FORMATS, base_record, touch, serialize_package, serialize_node,
    recompute_package_floor, _sorted,
)

bp = Blueprint("packages", __name__)


def _get_package_or_404(package_id):
    pkg = store.packages.get(package_id)
    if pkg is None:
        raise not_found("InventoryPackage not found")
    return pkg


def _require_package_owner(pkg, user_id):
    """Pipeline stage 6 ownership: a PublisherManager mutates only packages
    whose owning publisher id equals X-User-ID."""
    if pkg["publisher_id"] != user_id:
        raise unauthorized("Package belongs to a different publisher")


@bp.route("/packages", methods=["POST"])
def create_package():
    role, user_id = require_roles([ROLE_PUBLISHER_MANAGER])
    body = get_body()
    name = req_str(body, "name")
    ad_format = req_enum(body, "ad_format", AD_FORMATS)
    category_tags = req_category_tags(body)
    base_floor = req_int(body, "base_floor_cpm_micros", min_v=1)
    # publisher_id comes from the caller's X-User-ID, never the body (§3.2)
    pub = store.publishers.get(user_id)
    if pub is None:
        raise not_found("Publisher not found")
    if pub["status"] != "ACTIVE":
        raise ApiError(ERR_PUBLISHER_SUSPENDED, 409,
                       "Publisher is SUSPENDED; package creation is blocked")
    pkg = base_record()
    pkg.update({
        "publisher_id": user_id,
        "name": name,
        "ad_format": ad_format,
        "category_tags": category_tags,
        "base_floor_cpm_micros": base_floor,
        "status": "ACTIVE",
        "current_seasonal_multiplier_bps": 10000,
        "effective_floor_cpm_micros": base_floor,
    })
    recompute_package_floor(pkg)  # no window can exist yet; defensive no-op
    store.packages[pkg["id"]] = pkg
    return success_object(serialize_package(pkg), 201)


@bp.route("/packages", methods=["GET"])
def list_packages():
    require_roles(ALL_ROLES)
    publisher_id = request.args.get("publisher_id")
    status = request.args.get("status")
    items = list(store.packages.values())
    if publisher_id is not None:
        items = [p for p in items if p["publisher_id"] == publisher_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = paginate(_sorted(items), request.args)
    return success_list([serialize_package(p) for p in page], limit, offset, total)


@bp.route("/packages/<packageId>", methods=["GET"])
def get_package(packageId):
    require_roles(ALL_ROLES)
    pkg = _get_package_or_404(packageId)
    # floor recomputed against the logical clock on read (all mutation
    # triggers already keep it current, so this is a defensive no-op)
    if recompute_package_floor(pkg):
        touch(pkg)
    return success_object(serialize_package(pkg))


@bp.route("/packages/<packageId>", methods=["PUT"])
def update_package(packageId):
    role, user_id = require_roles([ROLE_PUBLISHER_MANAGER])
    body = get_body()
    expected_version = req_int(body, "expected_package_version")
    name = opt_str(body, "name")
    ad_format = opt_enum(body, "ad_format", AD_FORMATS)
    category_tags = opt_category_tags(body)
    base_floor = opt_int(body, "base_floor_cpm_micros", min_v=1)
    pkg = _get_package_or_404(packageId)
    _require_package_owner(pkg, user_id)
    if expected_version != pkg["version"]:
        raise stale_version("expected_package_version does not match the package version")
    if name is not None:
        pkg["name"] = name
    if ad_format is not None:
        pkg["ad_format"] = ad_format
    if category_tags is not None:
        pkg["category_tags"] = category_tags
    if base_floor is not None:
        pkg["base_floor_cpm_micros"] = base_floor
    recompute_package_floor(pkg)
    touch(pkg)
    return success_object(serialize_package(pkg))


@bp.route("/packages/<packageId>/pause", methods=["POST"])
def pause_package(packageId):
    role, user_id = require_roles([ROLE_PUBLISHER_MANAGER])
    pkg = _get_package_or_404(packageId)
    _require_package_owner(pkg, user_id)
    if pkg["status"] != "ACTIVE":
        raise invalid_state("Package is not ACTIVE")
    pkg["status"] = "PAUSED"
    touch(pkg)
    # Cascade: every ACTIVE deal of this package -> PAUSED (own bumps).
    for deal in _sorted(store.deals.values()):
        if deal["package_id"] == pkg["id"] and deal["status"] == "ACTIVE":
            deal["status"] = "PAUSED"
            touch(deal)
    return success_object(serialize_package(pkg))


@bp.route("/packages/<packageId>/resume", methods=["POST"])
def resume_package(packageId):
    role, user_id = require_roles([ROLE_PUBLISHER_MANAGER])
    pkg = _get_package_or_404(packageId)
    _require_package_owner(pkg, user_id)
    if pkg["status"] != "PAUSED":
        raise invalid_state("Package is not PAUSED")
    pub = store.publishers.get(pkg["publisher_id"])
    if pub is None or pub["status"] != "ACTIVE":
        raise ApiError(ERR_PUBLISHER_SUSPENDED, 409,
                       "Owning publisher is SUSPENDED; package cannot resume")
    pkg["status"] = "ACTIVE"
    recompute_package_floor(pkg)
    touch(pkg)
    return success_object(serialize_package(pkg))


@bp.route("/packages/<packageId>/fee-report", methods=["GET"])
def fee_report(packageId):
    require_roles(ALL_ROLES)
    pkg = _get_package_or_404(packageId)
    chain = [serialize_node(n) for n in
             sorted((n for n in store.nodes.values() if n["package_id"] == packageId),
                    key=lambda n: n["hop_index"])]
    deal_ids = {d["id"] for d in store.deals.values() if d["package_id"] == packageId}
    records = [r for r in store.records.values()
               if r["deal_id"] in deal_ids and not r["voided"]]
    return success_object({
        "package_id": packageId,
        "chain": chain,
        "non_voided_record_count": len(records),
        "total_gross_micros": sum(r["gross_micros"] for r in records),
        "total_exchange_fee_micros": sum(r["exchange_fee_micros"] for r in records),
        "total_supply_fee_micros": sum(r["supply_fee_micros"] for r in records),
        "total_publisher_net_micros": sum(r["publisher_net_micros"] for r in records),
    })
