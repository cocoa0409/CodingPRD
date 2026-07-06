"""PassProduct and Pass endpoints (PRD §3.4)."""
from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination, require_owner
from services import lookup
from services.common import (
    require_str, require_int, require_enum, optional_int, base_record, sort_and_paginate,
)
from services.serialize import (
    serialize_pass_product, serialize_pass, venue_operational_state,
)

bp = Blueprint("passes", __name__)

PRODUCT_READ_ROLES = {"OpsManager", "BoxOffice", "Guest"}


# ---------------------------------------------------------------------------
# PassProduct (immutable)
# ---------------------------------------------------------------------------
@bp.route("/venues/<venue_id>/pass-products", methods=["POST"])
def create_pass_product(venue_id):
    _, role = get_identity()
    require_role(role, {"OpsManager"})
    venue = lookup.venue(venue_id)
    body = get_json_body()
    kind = require_enum(body, "kind", {"SEASON", "GROUP"})
    price_cents = require_int(body, "price_cents", minimum=0)
    discount_pct = require_int(body, "discount_pct", minimum=0, maximum=100)
    max_redemptions = require_int(body, "max_redemptions", minimum=1)
    min_party = optional_int(body, "min_party", default=1, minimum=1)

    product = base_record(with_version=False)
    product.update({
        "venue_id": venue["id"],
        "kind": kind,
        "price_cents": price_cents,
        "discount_pct": discount_pct,
        "min_party": min_party,
        "max_redemptions": max_redemptions,
    })
    db.pass_products[product["id"]] = product
    return response.success(serialize_pass_product(product), 201)


@bp.route("/pass-products/<pass_product_id>", methods=["GET"])
def get_pass_product(pass_product_id):
    _, role = get_identity()
    require_role(role, PRODUCT_READ_ROLES)
    product = lookup.pass_product(pass_product_id)
    return response.success(serialize_pass_product(product), 200)


@bp.route("/pass-products", methods=["GET"])
def list_pass_products():
    _, role = get_identity()
    require_role(role, PRODUCT_READ_ROLES)
    limit, offset = parse_pagination()
    venue_id = request.args.get("venue_id")
    records = list(db.pass_products.values())
    if venue_id is not None:
        records = [p for p in records if p["venue_id"] == venue_id]
    page, total = sort_and_paginate(records, limit, offset)
    return response.success_list(
        [serialize_pass_product(p) for p in page], limit, offset, total, 200
    )


# ---------------------------------------------------------------------------
# Pass (issued)
# ---------------------------------------------------------------------------
@bp.route("/passes", methods=["POST"])
def issue_pass():
    user_id, role = get_identity()
    require_role(role, {"BoxOffice", "Guest"})
    body = get_json_body()
    pass_product_id = require_str(body, "pass_product_id")
    guest_id = require_str(body, "guest_id")

    # Ownership: a Guest may only buy their own pass.
    require_owner(role, user_id, guest_id)

    # Existence of body FKs, validated in order.
    product = lookup.pass_product(pass_product_id)
    lookup.guest(guest_id)

    # Purchasing a pass is blocked when operational_state is RESTRICTED or SHUTDOWN.
    venue = db.venues.get(product["venue_id"])
    if venue is not None and venue_operational_state(venue) in ("RESTRICTED", "SHUTDOWN"):
        raise ApiError(errors.ERR_SALES_BLOCKED, 409,
                       "Pass purchases are blocked under the current venue posture.")

    issued = base_record()
    issued.update({
        "pass_product_id": product["id"],
        "guest_id": guest_id,
        "redemptions_used": 0,
        "status": "ACTIVE",
    })
    db.passes[issued["id"]] = issued
    return response.success(serialize_pass(issued), 201)


@bp.route("/passes/<pass_id>", methods=["GET"])
def get_pass(pass_id):
    user_id, role = get_identity()
    require_role(role, PRODUCT_READ_ROLES)
    issued = lookup.issued_pass(pass_id)
    require_owner(role, user_id, issued["guest_id"])
    return response.success(serialize_pass(issued), 200)


@bp.route("/passes", methods=["GET"])
def list_passes():
    user_id, role = get_identity()
    require_role(role, PRODUCT_READ_ROLES)
    limit, offset = parse_pagination()
    guest_id = request.args.get("guest_id")
    pass_product_id = request.args.get("pass_product_id")
    records = list(db.passes.values())
    if guest_id is not None:
        records = [p for p in records if p["guest_id"] == guest_id]
    if pass_product_id is not None:
        records = [p for p in records if p["pass_product_id"] == pass_product_id]
    if role == "Guest":
        records = [p for p in records if p["guest_id"] == user_id]
    page, total = sort_and_paginate(records, limit, offset)
    return response.success_list(
        [serialize_pass(p) for p in page], limit, offset, total, 200
    )
