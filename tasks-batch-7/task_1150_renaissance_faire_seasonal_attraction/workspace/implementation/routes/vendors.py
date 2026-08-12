"""Vendor endpoints."""
from flask import Blueprint

from db import store, new_id, next_seq
from errors import ERR_VENDOR_NOT_FOUND
from middleware import (
    require_roles,
    get_body,
    load,
    parse_pagination,
    apply_filters,
    sorted_by_creation,
)
from response import obj_response, list_response
from util import req, check_unknown, new_record, public_view

bp = Blueprint("vendors", __name__)

CATEGORIES = {"FOOD", "BEVERAGE", "ARTISAN", "GAMES"}
CREATE_FIELDS = {"business_name", "category"}


@bp.route("/vendors", methods=["POST"])
def create_vendor():
    require_roles("VendorCoordinator")
    body = get_body()
    check_unknown(body, CREATE_FIELDS)
    vendor = new_record()
    vendor.update(
        {
            "id": new_id(),
            "_seq": next_seq(),
            "business_name": req(body, "business_name", "str"),
            "category": req(body, "category", "enum", enum=CATEGORIES),
        }
    )
    store.vendors[vendor["id"]] = vendor
    return obj_response(public_view(vendor), 201)


@bp.route("/vendors", methods=["GET"])
def list_vendors():
    require_roles()
    limit, offset = parse_pagination()
    items = apply_filters(sorted_by_creation(store.vendors), [("category", "category")])
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([public_view(v) for v in page], limit, offset, total)


@bp.route("/vendors/<vid>", methods=["GET"])
def get_vendor(vid):
    require_roles()
    return obj_response(public_view(load(store.vendors, vid, ERR_VENDOR_NOT_FOUND, "vendor")))
