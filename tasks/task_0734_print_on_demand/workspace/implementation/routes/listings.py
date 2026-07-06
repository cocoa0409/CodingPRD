"""Listing endpoints — create, read, list, publish."""
from flask import Blueprint, request

import db
from errors import raise_error
from middleware import require_auth
from response import ok, created, paginate_and_serialize
from services.calc import listing_price_cents
from services.serialize import serialize

bp = Blueprint("listings", __name__)


def _get_listing_or_404(lid):
    row = db.listings.get(lid)
    if not row:
        raise_error("ERR_NOT_FOUND", f"listing {lid} not found")
    return row


@bp.post("/pod/listings")
@require_auth(["Creator"])
def create_listing():
    body = request.get_json(silent=True) or {}
    for f in ("storefront_id", "design_id", "variant_id", "title"):
        if f not in body:
            raise_error("ERR_INVALID_REQUEST", f"missing {f}")
    if not isinstance(body["title"], str) or not body["title"]:
        raise_error("ERR_INVALID_REQUEST", "title must be non-empty string")

    # FK resolution — priority 4.
    storefront = db.storefronts.get(body["storefront_id"])
    if not storefront:
        raise_error("ERR_FK_NOT_FOUND", "storefront not found")
    design = db.designs.get(body["design_id"])
    if not design:
        raise_error("ERR_FK_NOT_FOUND", "design not found")
    variant = db.variants.get(body["variant_id"])
    if not variant:
        raise_error("ERR_FK_NOT_FOUND", "variant not found")
    product = db.products.get(variant["product_id"])
    if not product:
        raise_error("ERR_FK_NOT_FOUND", "product not found")

    # Priority 9: Design creator must match Storefront creator.
    if design["creator_id"] != storefront["creator_id"]:
        raise_error("ERR_DESIGN_CREATOR_MISMATCH", "design creator does not match storefront creator")

    listed_price = listing_price_cents(product, variant, storefront, is_sample=False)

    row = db.new_common_fields()
    row.update(
        {
            "storefront_id": storefront["id"],
            "design_id": design["id"],
            "variant_id": variant["id"],
            "title": body["title"],
            "listed_price_cents": listed_price,
            "status": "DRAFT",
        }
    )
    db.listings.insert(row)
    return created(serialize(row))


@bp.get("/pod/listings/<lid>")
@require_auth(["Creator", "PlatformAdmin"])
def read_listing(lid):
    return ok(serialize(_get_listing_or_404(lid)))


@bp.get("/pod/listings")
@require_auth(["Creator", "PlatformAdmin"])
def list_listings():
    storefront_id = request.args.get("storefront_id")
    design_id = request.args.get("design_id")
    variant_id = request.args.get("variant_id")
    rows = db.listings.all()
    if storefront_id is not None:
        rows = [r for r in rows if r["storefront_id"] == storefront_id]
    if design_id is not None:
        rows = [r for r in rows if r["design_id"] == design_id]
    if variant_id is not None:
        rows = [r for r in rows if r["variant_id"] == variant_id]
    rows = db.sorted_rows(rows)
    return paginate_and_serialize(rows, serialize)


@bp.post("/pod/listings/<lid>/publish")
@require_auth(["Creator"])
def publish_listing(lid):
    row = _get_listing_or_404(lid)
    if row["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE", "listing must be DRAFT to publish")
    row["status"] = "PUBLISHED"
    db.bump(row)
    return ok(serialize(row))
