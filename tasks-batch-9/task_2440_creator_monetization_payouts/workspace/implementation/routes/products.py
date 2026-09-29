"""Revenue product catalogue (PRD 3.3).  Global configuration: never narrowed."""
from flask import Blueprint, request

import serialize
from apierrors import fail
from envelope import created, ok
from fields import F
from gate import endpoint
from listutil import filter_rows, respond
from store import db, sort_rows

bp = Blueprint("products", __name__)

TYPES = ("ADVERTISING", "SUBSCRIPTIONS", "TIPS", "COMMERCE")
ALL_ROLES = ("PlatformAdmin", "FinanceOperator", "PolicyReviewer", "Auditor", "Creator")

CREATE = (
    F("product_type", "enum", required=True, enum=TYPES),
    F("name", "str", required=True, text=(1, 120)),
    F("creator_share_bps", "int", required=True, minv=0, maxv=9000),
    F("platform_fee_bps", "int", required=True, minv=0, maxv=10000),
    F("min_payable_cents", "int", default=0, minv=0),
    F("terms_version", "int", default=1, minv=1),
)
PATCH = (
    F("creator_share_bps", "int", minv=0, maxv=9000),
    F("platform_fee_bps", "int", minv=0, maxv=10000),
    F("min_payable_cents", "int", minv=0),
    F("terms_version", "int", minv=1),
)

PATH = (("product_id", "products"),)


@bp.route("/monetization/revenue-products", methods=["POST"])
@endpoint(roles=("PlatformAdmin",), fields=CREATE)
def create_product(ctx):
    data = ctx.data
    if data["creator_share_bps"] + data["platform_fee_bps"] != 10000:    # 62
        fail("ERR_SHARE_SPLIT_NOT_WHOLE",
             "creator_share_bps + platform_fee_bps must equal 10000.")
    row = db.insert("products", {
        "product_type": data["product_type"],
        "name": data["name"],
        "creator_share_bps": data["creator_share_bps"],
        "platform_fee_bps": data["platform_fee_bps"],
        "min_payable_cents": data["min_payable_cents"],
        "terms_version": data["terms_version"],
        "suitability_sensitive": data["product_type"] == "ADVERTISING",
        "status": "ACTIVE",
        "retired_at": None,
    })
    return created(serialize.product(row))


@bp.route("/monetization/revenue-products", methods=["GET"])
@endpoint(roles=ALL_ROLES, listing=True)
def list_products(ctx):
    rows = filter_rows(db.rows("products"), request.args,
                       {"product_type": "product_type", "status": "status"})
    rows = sort_rows(rows, lambda r: (r["created_at"],))
    return respond(ctx, rows, serialize.product)


@bp.route("/monetization/revenue-products/<product_id>", methods=["PATCH"])
@endpoint(roles=("PlatformAdmin",), path=PATH, fields=PATCH)
def patch_product(ctx, product_id):
    row = ctx.path["product_id"]
    if row["status"] != "ACTIVE":                                        # 17
        fail("ERR_PRODUCT_ALREADY_RETIRED", "A retired product's terms are frozen.")
    merged = dict(row)
    for name in ("creator_share_bps", "platform_fee_bps", "min_payable_cents",
                 "terms_version"):
        if ctx.data.get(name) is not None:
            merged[name] = ctx.data[name]
    if merged["creator_share_bps"] + merged["platform_fee_bps"] != 10000:  # 62
        fail("ERR_SHARE_SPLIT_NOT_WHOLE",
             "creator_share_bps + platform_fee_bps must equal 10000.")
    for name in ("creator_share_bps", "platform_fee_bps", "min_payable_cents",
                 "terms_version"):
        row[name] = merged[name]
    db.touch(row)
    return ok(serialize.product(row))


@bp.route("/monetization/revenue-products/<product_id>/retire", methods=["POST"])
@endpoint(roles=("PlatformAdmin",), path=PATH)
def retire_product(ctx, product_id):
    row = ctx.path["product_id"]
    if row["status"] != "ACTIVE":                                        # 16
        fail("ERR_PRODUCT_ALREADY_RETIRED", "The product is already retired.")
    row["status"] = "RETIRED"
    row["retired_at"] = db.now
    db.touch(row)
    return ok(serialize.product(row))
