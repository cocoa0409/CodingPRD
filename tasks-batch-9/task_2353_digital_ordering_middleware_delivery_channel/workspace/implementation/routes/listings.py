"""Channel listings: read, list and per-channel suppression."""
from flask import Blueprint

import db
import middleware as M
import response
import validation
from routes import common
from services import constants as K
from services import domain, serializers

bp = Blueprint("listings", __name__)


@bp.get("/channel-listings/<listing_id>")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.CHANNEL_PARTNER, M.SETTLEMENT_ANALYST)
def read_listing(listing_id):
    listing = common.get_listing(listing_id)
    M.require_store_scope(listing["store_id"])
    M.require_channel_scope(listing["channel_id"])
    return response.object_response(serializers.listing(listing))


@bp.get("/channel-listings")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.CHANNEL_PARTNER, M.SETTLEMENT_ANALYST)
def list_listings():
    limit, offset = validation.pagination()
    store_id = validation.query_str("store_id")
    channel_id = validation.query_str("channel_id")
    menu_item_id = validation.query_str("menu_item_id")
    sku = validation.query_str("sku")
    availability_state = validation.query_enum("availability_state",
                                               K.AVAILABILITY_STATES)

    def keep(rec):
        if store_id is not None and rec["store_id"] != store_id:
            return False
        if channel_id is not None and rec["channel_id"] != channel_id:
            return False
        if menu_item_id is not None and rec["menu_item_id"] != menu_item_id:
            return False
        if sku is not None and rec["sku"] != sku:
            return False
        if availability_state is not None and rec["availability_state"] != availability_state:
            return False
        return True

    records = db.sorted_records(db.listings, keep)
    page, meta = response.paginate(records, limit, offset)
    return response.array_response([serializers.listing(r) for r in page], meta)


@bp.patch("/channel-listings/<listing_id>")
@M.endpoint(M.CHANNEL_PARTNER)
def update_listing(listing_id):
    payload = validation.body()
    suppressed = validation.req_bool(payload, "suppressed")
    listing = common.get_listing(listing_id)
    M.require_channel_scope(listing["channel_id"])

    listing["suppressed"] = suppressed
    listing["availability_state"] = domain.derive_availability_state(listing)
    db.touch(listing)
    return response.object_response(serializers.listing(listing))
