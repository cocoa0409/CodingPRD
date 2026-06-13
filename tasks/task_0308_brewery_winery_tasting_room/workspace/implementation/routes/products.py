"""Product routes (PRD §3.4). Linear OCC-guarded lifecycle."""
from flask import Blueprint, request

from db import db, common_fields, touch
from errors import (
    err, ERR_INVALID_STATE, ERR_STALE_PRODUCT_VERSION, ERR_FK_NOT_FOUND,
)
from middleware import authenticate, authorize
from response import success
from serialize import public
from validate import (
    get_json_body, require_str, require_int, require_positive_int, require_enum,
    opt_bool, get_or_404, resolve_winery_fk, resolve_fk,
)
from pagination import paginate, sorted_by_creation

bp = Blueprint("products", __name__)


def _new_product(winery_id, source_batch_id, sku, vintage_year, bottle_volume_ml,
                 list_price_cents, is_age_restricted):
    p = common_fields()
    p.update({
        "winery_id": winery_id,
        "source_batch_id": source_batch_id,
        "sku": sku,
        "vintage_year": vintage_year,
        "bottle_volume_ml": bottle_volume_ml,
        "list_price_cents": list_price_cents,
        "is_age_restricted": is_age_restricted,
        "on_hand_bottles": 0,
        "allocated_bottles": 0,
        "free_bottles": 0,
        "status": "DRAFT",
    })
    return p


@bp.route("/products", methods=["POST"])
def create_product():
    _, role = authenticate()
    authorize(role, ["CellarManager"])
    body = get_json_body()
    winery_id = require_str(body, "winery_id")
    source_batch_id = require_str(body, "source_batch_id")
    sku = require_str(body, "sku")
    vintage_year = require_int(body, "vintage_year")
    bottle_volume_ml = require_positive_int(body, "bottle_volume_ml")
    list_price_cents = require_int(body, "list_price_cents")
    is_age_restricted = opt_bool(body, "is_age_restricted", True)
    with db.lock:
        resolve_winery_fk(winery_id)
        # source batch must resolve and be in the same winery
        resolve_fk(db.batches, source_batch_id, winery_id)
        p = _new_product(winery_id, source_batch_id, sku, vintage_year,
                         bottle_volume_ml, list_price_cents, is_age_restricted)
        db.products[p["id"]] = p
        return success(public(p), status=201)


@bp.route("/products", methods=["GET"])
def list_products():
    _, role = authenticate()
    authorize(role, ["CellarManager", "ComplianceOfficer", "ClubManager", "TastingRoomStaff"])
    with db.lock:
        items = list(db.products.values())
        winery_id = request.args.get("winery_id")
        source_batch_id = request.args.get("source_batch_id")
        status = request.args.get("status")
        if winery_id is not None:
            items = [p for p in items if p["winery_id"] == winery_id]
        if source_batch_id is not None:
            items = [p for p in items if p["source_batch_id"] == source_batch_id]
        if status is not None:
            items = [p for p in items if p["status"] == status]
        items = sorted_by_creation(items)
        page, pg = paginate(items)
        return success([public(p) for p in page], pagination=pg)


@bp.route("/products/<product_id>", methods=["GET"])
def get_product(product_id):
    _, role = authenticate()
    authorize(role, ["CellarManager", "ComplianceOfficer", "ClubManager", "TastingRoomStaff"])
    with db.lock:
        p = get_or_404(db.products, product_id)
        return success(public(p))


@bp.route("/products/<product_id>/transitions", methods=["POST"])
def transition_product(product_id):
    _, role = authenticate()
    authorize(role, ["CellarManager"])
    with db.lock:
        p = get_or_404(db.products, product_id)
        body = get_json_body()
        action = require_enum(body, "action", {"ACTIVATE", "DISCONTINUE"})
        expected_version = require_int(body, "expected_product_version")

        if action == "ACTIVATE":
            if p["status"] != "DRAFT":
                raise err(ERR_INVALID_STATE, "Product is not DRAFT")
            # source batch must be BOTTLING or CLOSED (PRD §3.4 prose order: before OCC)
            batch = db.batches.get(p["source_batch_id"])
            if batch is None or batch["status"] not in ("BOTTLING", "CLOSED"):
                raise err(ERR_INVALID_STATE, "Source batch is not in BOTTLING or CLOSED")
            # OCC check
            if expected_version != p["version"]:
                raise err(ERR_STALE_PRODUCT_VERSION, "expected_product_version is stale")
            p["status"] = "ACTIVE"
            touch(p)  # increments version by 1

        else:  # DISCONTINUE
            if p["status"] != "ACTIVE":
                raise err(ERR_INVALID_STATE, "Product is not ACTIVE")
            # no OPEN allocation release of this product (PRD §3.4 prose order: before OCC)
            for r in db.releases.values():
                if r["product_id"] == p["id"] and r["status"] == "OPEN":
                    raise err(ERR_INVALID_STATE, "Product has an OPEN allocation release")
            if expected_version != p["version"]:
                raise err(ERR_STALE_PRODUCT_VERSION, "expected_product_version is stale")
            p["status"] = "DISCONTINUED"
            touch(p)

        return success(public(p))
