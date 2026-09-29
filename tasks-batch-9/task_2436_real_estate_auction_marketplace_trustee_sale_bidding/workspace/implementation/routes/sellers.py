"""Seller onboarding and reads (PRD §3.1)."""

from flask import Blueprint

import calc
import db
import serial
import validate as v
from auth import authenticate
from db import ordered, store
from helpers import find
from util import ok, ok_list

bp = Blueprint("sellers", __name__)


@bp.post("/sellers")
def create_seller():
    authenticate(("PlatformAdmin",))
    data = v.body()
    org_name = v.req_str(data, "org_name", min_len=1, max_len=200)
    seller_type = v.req_enum(data, "seller_type", calc.SELLER_TYPES)
    contact_email = v.req_email(data, "contact_email")
    account_ref = v.req_str(data, "settlement_account_ref")
    commission = v.opt_int(data, "default_commission_bps", default=500, minimum=0, maximum=1500)

    rec = db.new_record(
        org_name=org_name,
        seller_type=seller_type,
        contact_email=contact_email,
        settlement_account_ref=account_ref,
        default_commission_bps=commission,
        settled_net_cents=0,
    )
    store.sellers[rec["id"]] = rec
    return ok(serial.dump("seller", rec), 201)


@bp.get("/sellers/<rec_id>")
def get_seller(rec_id):
    authenticate(("PlatformAdmin", "AuctionOps", "Seller"))
    rec = find(store.sellers, rec_id, "ERR_SELLER_NOT_FOUND")
    return ok(serial.dump("seller", rec))


@bp.get("/sellers/<rec_id>/asset-listings")
def list_seller_listings(rec_id):
    authenticate(("PlatformAdmin", "AuctionOps", "Seller"))
    find(store.sellers, rec_id, "ERR_SELLER_NOT_FOUND")
    limit, offset = v.pagination()
    status = v.query_enum("listing_status", calc.LISTING_STATUS)
    items = [a for a in ordered(store.asset_listings.values()) if a["seller_id"] == rec_id]
    if status is not None:
        items = [a for a in items if a["listing_status"] == status]
    total = len(items)
    return ok_list(serial.dump_many("asset_listing", v.page(items, limit, offset)),
                   limit, offset, total)
