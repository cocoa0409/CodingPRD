"""Rich-media assets and retailer media decisions (PRD 3.3)."""
from flask import Blueprint, g, request

import calc
import envelope
import recompute
import validate
from auth import ALL_ROLES, endpoint
from entities import get_media_asset, get_product, media_asset_out
from errors import ApiError
from store import base_row, db, in_order, now, touch

bp = Blueprint("media", __name__)

ASSET_ROLES = ("HERO_IMAGE", "SECONDARY_IMAGE", "VIDEO", "A_PLUS_MODULE")
DECISIONS = ("APPROVE", "REJECT")


@bp.route("/media-assets", methods=["POST"])
@endpoint(["ContentAuthor"])
def create_media_asset():
    data = validate.body()
    product_id = validate.req_str(data, "product_id", 1)
    asset_role = validate.req_enum(data, "asset_role", ASSET_ROLES)
    source_uri = validate.req_str(data, "source_uri", 1, 500)
    product = get_product(product_id)
    asset = base_row()
    asset.update({
        "product_id": product["id"],
        "asset_role": asset_role,
        "source_uri": source_uri,
        "approval_state": "PENDING",
        "approving_retailer_id": None,
        "decided_at": None,
    })
    db.media_assets[asset["id"]] = asset
    return envelope.created(media_asset_out(asset))


@bp.route("/media-assets/<row_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_media_asset(row_id):
    return envelope.ok(media_asset_out(get_media_asset(row_id)))


@bp.route("/media-assets", methods=["GET"])
@endpoint(ALL_ROLES)
def list_media_assets():
    limit, offset = envelope.page_params()
    product_id = request.args.get("product_id")
    approval_state = request.args.get("approval_state")
    approving_retailer_id = request.args.get("approving_retailer_id")
    rows = in_order(list(db.media_assets.values()))
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if approval_state is not None:
        rows = [r for r in rows if r["approval_state"] == approval_state]
    if approving_retailer_id is not None:
        rows = [r for r in rows if r.get("approving_retailer_id") == approving_retailer_id]
    return envelope.paged_with(rows, media_asset_out, limit, offset)


@bp.route("/media-assets/<row_id>/retailer-decision", methods=["POST"])
@endpoint(["RetailerIntegration"])
def decide_media_asset(row_id):
    asset = get_media_asset(row_id)
    # Step 4: the acting retailer must carry the product on a listing of its own.
    listing = calc.find_listing(asset["product_id"], g.user_id)
    if listing is None:
        raise ApiError("ERR_RETAILER_SCOPE_VIOLATION")
    data = validate.body()
    decision = validate.req_enum(data, "decision", DECISIONS)
    if asset["approval_state"] != "PENDING":
        raise ApiError("ERR_MEDIA_ASSET_NOT_PENDING",
                       "The media asset has already been decided.")
    asset["approval_state"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    asset["approving_retailer_id"] = g.user_id
    asset["decided_at"] = now()
    touch(asset)
    if decision == "APPROVE":
        # The approved image count feeds the certified image component.
        detail = calc.completeness_detail(listing)
        listing["completeness_score_certified"] = detail["certified_score"]
        recompute.recompute_listing_readiness(listing)
    return envelope.ok(media_asset_out(asset))
