"""AllocationRelease routes (PRD §3.5). OCC-guarded quota windows."""
from flask import Blueprint, request

from db import db, common_fields, touch
from errors import (
    err, ERR_INVALID_STATE, ERR_INSUFFICIENT_INVENTORY,
    ERR_STALE_RELEASE_VERSION, ERR_STALE_PRODUCT_VERSION, ERR_INVALID_REQUEST,
)
from middleware import authenticate, authorize
from response import success
from serialize import public
from domain import recompute_product_free, recompute_release_available
from validate import (
    get_json_body, require_str, require_int, require_positive_int, require_enum,
    get_or_404, resolve_winery_fk, resolve_fk,
)
from pagination import paginate, sorted_by_creation
from util import parse_datetime

bp = Blueprint("releases", __name__)


def _new_release(winery_id, product_id, pool_bottles, per_member_cap, opens_at, closes_at):
    r = common_fields()
    r.update({
        "product_id": product_id,
        "winery_id": winery_id,
        "pool_bottles": pool_bottles,
        "per_member_cap": per_member_cap,
        "reserved_bottles": 0,
        "committed_bottles": 0,
        "available_bottles": 0,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "status": "DRAFT",
    })
    return r


@bp.route("/releases", methods=["POST"])
def create_release():
    _, role = authenticate()
    authorize(role, ["CellarManager"])
    body = get_json_body()
    winery_id = require_str(body, "winery_id")
    product_id = require_str(body, "product_id")
    pool_bottles = require_positive_int(body, "pool_bottles")
    per_member_cap = require_positive_int(body, "per_member_cap")
    opens_at_raw = require_str(body, "opens_at")
    closes_at_raw = require_str(body, "closes_at")
    opens_at = parse_datetime(opens_at_raw, "opens_at")
    closes_at = parse_datetime(closes_at_raw, "closes_at")
    if closes_at <= opens_at:
        raise err(ERR_INVALID_REQUEST, "closes_at must be after opens_at")
    with db.lock:
        resolve_winery_fk(winery_id)
        resolve_fk(db.products, product_id, winery_id)
        r = _new_release(winery_id, product_id, pool_bottles, per_member_cap,
                         opens_at_raw, closes_at_raw)
        db.releases[r["id"]] = r
        return success(public(r), status=201)


@bp.route("/releases", methods=["GET"])
def list_releases():
    _, role = authenticate()
    authorize(role, ["CellarManager", "ClubManager", "ComplianceOfficer"])
    with db.lock:
        items = list(db.releases.values())
        product_id = request.args.get("product_id")
        winery_id = request.args.get("winery_id")
        status = request.args.get("status")
        if product_id is not None:
            items = [r for r in items if r["product_id"] == product_id]
        if winery_id is not None:
            items = [r for r in items if r["winery_id"] == winery_id]
        if status is not None:
            items = [r for r in items if r["status"] == status]
        items = sorted_by_creation(items)
        page, pg = paginate(items)
        return success([public(r) for r in page], pagination=pg)


@bp.route("/releases/<release_id>", methods=["GET"])
def get_release(release_id):
    _, role = authenticate()
    authorize(role, ["CellarManager", "ClubManager", "ComplianceOfficer"])
    with db.lock:
        r = get_or_404(db.releases, release_id)
        return success(public(r))


@bp.route("/releases/<release_id>/transitions", methods=["POST"])
def transition_release(release_id):
    _, role = authenticate()
    authorize(role, ["CellarManager"])
    with db.lock:
        r = get_or_404(db.releases, release_id)
        body = get_json_body()
        action = require_enum(body, "action", {"OPEN_RELEASE", "CLOSE_RELEASE"})
        product = db.products.get(r["product_id"])

        if action == "OPEN_RELEASE":
            expected_release_version = require_int(body, "expected_release_version")
            expected_product_version = require_int(body, "expected_product_version")
            if r["status"] != "DRAFT":
                raise err(ERR_INVALID_STATE, "Release is not DRAFT")
            # product must be ACTIVE (PRD §3.5 prose order: before inventory + OCC)
            if product["status"] != "ACTIVE":
                raise err(ERR_INVALID_STATE, "Product is not ACTIVE")
            # OCC: release version then product version (PRD §2.9 priority 7)
            if expected_release_version != r["version"]:
                raise err(ERR_STALE_RELEASE_VERSION, "expected_release_version is stale")
            if expected_product_version != product["version"]:
                raise err(ERR_STALE_PRODUCT_VERSION, "expected_product_version is stale")
            # inventory sufficiency: free_bottles >= pool_bottles
            if product["free_bottles"] < r["pool_bottles"]:
                raise err(ERR_INSUFFICIENT_INVENTORY, "Insufficient free inventory for the pool")
            # cascade: product allocation reserved out of free
            product["allocated_bottles"] = product["allocated_bottles"] + r["pool_bottles"]
            recompute_product_free(product)
            touch(product)  # increments Product.version by 1
            r["status"] = "OPEN"
            r["available_bottles"] = r["pool_bottles"]
            touch(r)  # increments AllocationRelease.version by 1

        else:  # CLOSE_RELEASE
            expected_release_version = require_int(body, "expected_release_version")
            if r["status"] != "OPEN":
                raise err(ERR_INVALID_STATE, "Release is not OPEN")
            if expected_release_version != r["version"]:
                raise err(ERR_STALE_RELEASE_VERSION, "expected_release_version is stale")
            # free residual available back to the product
            residual = r["available_bottles"]
            product["allocated_bottles"] = product["allocated_bottles"] - residual
            recompute_product_free(product)
            touch(product)
            r["available_bottles"] = 0
            r["status"] = "CLOSED"
            touch(r)

        return success(public(r))
