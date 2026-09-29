"""Single-source menu authoring: versions, items, finalize."""
from flask import Blueprint

import clock
import db
import errors
import middleware as M
import response
import validation
from errors import fail
from routes import common
from services import serializers

bp = Blueprint("menu_versions", __name__)


@bp.post("/menu-versions")
@M.endpoint(M.PLATFORM_ADMIN)
def create_menu_version():
    payload = validation.body()
    brand_code = validation.req_str(payload, "brand_code")
    label = validation.req_str(payload, "version_label")

    for existing in db.menu_versions.values():
        if existing["brand_code"] == brand_code and existing["version_label"] == label:
            fail(errors.ERR_DUPLICATE_VERSION_LABEL)

    version = db.record()
    version.update({
        "brand_code": brand_code,
        "version_label": label,
        "state": "DRAFT",
        "item_count": 0,
        "published_store_count": 0,
        "published_at": None,
        "superseded_at": None,
    })
    db.menu_versions[version["id"]] = version
    return response.object_response(serializers.menu_version(version), 201)


@bp.get("/menu-versions/<version_id>")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.CHANNEL_PARTNER)
def read_menu_version(version_id):
    version = common.get_menu_version(version_id)
    return response.object_response(serializers.menu_version(version))


@bp.post("/menu-versions/<version_id>/items")
@M.endpoint(M.PLATFORM_ADMIN)
def create_menu_item(version_id):
    payload = validation.body()
    sku = validation.req_str(payload, "sku")
    name = validation.req_str(payload, "name")
    base_price = validation.req_int(payload, "base_price_cents", 1)
    tax_bps = validation.req_int(payload, "tax_bps", 0, 2000)
    delivery_eligible = validation.opt_bool(payload, "is_delivery_eligible", True)

    version = common.get_menu_version(version_id)

    # Uniqueness (rank 8) is evaluated above the version lock (rank 9).
    for item in db.menu_items.values():
        if item["menu_version_id"] == version["id"] and item["sku"] == sku:
            fail(errors.ERR_DUPLICATE_SKU)
    if version["state"] != "DRAFT":
        fail(errors.ERR_MENU_VERSION_LOCKED)

    item = db.record()
    item.update({
        "menu_version_id": version["id"],
        "sku": sku,
        "name": name,
        "base_price_cents": base_price,
        "tax_bps": tax_bps,
        "is_delivery_eligible": delivery_eligible,
    })
    db.menu_items[item["id"]] = item

    version["item_count"] += 1
    db.touch(version)
    return response.object_response(serializers.menu_item(item), 201)


@bp.get("/menu-versions/<version_id>/items")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.CHANNEL_PARTNER)
def list_menu_items(version_id):
    limit, offset = validation.pagination()
    sku = validation.query_str("sku")
    common.get_menu_version(version_id)

    def keep(rec):
        if rec["menu_version_id"] != version_id:
            return False
        if sku is not None and rec["sku"] != sku:
            return False
        return True

    records = db.sorted_records(db.menu_items, keep)
    page, meta = response.paginate(records, limit, offset)
    return response.array_response([serializers.menu_item(r) for r in page], meta)


@bp.post("/menu-versions/<version_id>/finalize")
@M.endpoint(M.PLATFORM_ADMIN)
def finalize_menu_version(version_id):
    version = common.get_menu_version(version_id)
    if version["state"] != "DRAFT":
        fail(errors.ERR_MENU_VERSION_LOCKED)
    if version["item_count"] <= 0:
        fail(errors.ERR_MENU_VERSION_EMPTY)

    version["state"] = "PUBLISHED"
    version["published_at"] = clock.now()
    db.touch(version)
    return response.object_response(serializers.menu_version(version))
