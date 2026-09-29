"""Reel stock and lineage (PRD Section 3.6)."""
from flask import Blueprint

import constants as C
import db
import listing
import response
import serializers as ser
import validation as v
from middleware import endpoint
from services import lookup

bp = Blueprint("reels", __name__)


@bp.post("/reels")
@endpoint(["BranchOps", "PlatformAdmin"])
def create_reel():
    body = v.body()
    product_id = v.req_str(body, "product_id")
    branch_id = v.req_str(body, "branch_id")
    lot_code = v.req_str(body, "lot_code")
    nominal_length_ft = v.req_num(body, "nominal_length_ft", exclusive_min=0)

    # Body foreign keys resolve in declaration order: branch_id, then product_id.
    lookup.branch(branch_id)
    lookup.product(product_id)

    rec = db.base_record()
    rec.update({
        "product_id": product_id,
        "branch_id": branch_id,
        "parent_reel_id": None,
        "reel_type": "MASTER",
        "lot_code": lot_code,
        "nominal_length_ft": nominal_length_ft,
        "current_length_ft": nominal_length_ft,
        "allocated_length_ft": 0,
        "scrap_ft": 0,
        "status": "IN_STOCK",
        "delivered_sales_order_id": None,
        "delivered_at": None,
    })
    db.reels.add(rec)
    return response.object_response(ser.reel(rec), 201)


@bp.get("/reels/<reel_id>")
@endpoint(["PlatformAdmin", "BranchOps", "SalesRep"])
def get_reel(reel_id):
    return response.object_response(ser.reel(lookup.reel(reel_id)))


@bp.get("/reels")
@endpoint(["PlatformAdmin", "BranchOps", "SalesRep"])
def list_reels():
    v.pagination()
    branch_id = v.query_str("branch_id")
    product_id = v.query_str("product_id")
    parent_reel_id = v.query_str("parent_reel_id")
    delivered_sales_order_id = v.query_str("delivered_sales_order_id")
    status = v.query_enum("status", C.REEL_STATUSES)
    lot_code = v.query_str("lot_code")
    reel_type = v.query_enum("reel_type", C.REEL_TYPES)

    rows = db.reels.values_ordered()
    if branch_id:
        rows = [r for r in rows if r["branch_id"] == branch_id]
    if product_id:
        rows = [r for r in rows if r["product_id"] == product_id]
    if parent_reel_id:
        rows = [r for r in rows if r["parent_reel_id"] == parent_reel_id]
    if delivered_sales_order_id:
        rows = [r for r in rows if r["delivered_sales_order_id"] == delivered_sales_order_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if lot_code:
        rows = [r for r in rows if r["lot_code"] == lot_code]
    if reel_type:
        rows = [r for r in rows if r["reel_type"] == reel_type]
    return listing.respond(rows, ser.reel)
