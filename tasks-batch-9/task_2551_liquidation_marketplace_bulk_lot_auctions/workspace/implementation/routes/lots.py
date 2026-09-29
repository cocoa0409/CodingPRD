"""Lots, manifest lines, manifest submissions and manifest reviews (PRD 3.1)."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.helpers import list_rows
from services import aggregates, guards, lookups

bp = Blueprint("lots", __name__)

READ_ALL = (
    mw.PLATFORM_ADMIN, mw.MARKETPLACE_OPS, mw.SELLER_OPS, mw.TRUST_SAFETY, mw.BUYER,
)
EDITABLE_LOT_STATES = ("DRAFT", "MANIFEST_REJECTED")


@bp.post("/liquidation/lots")
def create_lot():
    user_id, _role = mw.authenticate((mw.SELLER_OPS,))
    payload = mw.body()
    # band 4: a seller acts only for itself
    if mw.present(payload, "seller_id"):
        guards.own_or_403(payload.get("seller_id"), user_id)
    # band 6: body foreign keys
    seller = lookups.seller(payload.get("seller_id")) if mw.present(payload, "seller_id") else None
    warehouse = (
        lookups.warehouse(payload.get("warehouse_id"))
        if mw.present(payload, "warehouse_id") else None
    )
    policy = (
        lookups.brand_policy(payload.get("brand_policy_id"))
        if mw.present(payload, "brand_policy_id") else None
    )
    # band 7: request shape
    if seller is None:
        raise ApiError("ERR_INVALID_REQUEST", "seller_id is required.")
    if warehouse is None:
        raise ApiError("ERR_INVALID_REQUEST", "warehouse_id is required.")
    title = mw.req_str(payload, "title")
    category_code = mw.req_enum(payload, "category_code", mw.CATEGORY_CODES)
    condition_grade = mw.req_enum(payload, "condition_grade", mw.CONDITION_GRADES)

    row = db.new_row(
        seller_id=seller["id"],
        warehouse_id=warehouse["id"],
        brand_policy_id=policy["id"] if policy else None,
        title=title,
        category_code=category_code,
        condition_grade=condition_grade,
        lot_status="DRAFT",
        manifest_line_count=0,
        declared_unit_count=0,
        declared_retail_value_cents=0,
        manifest_reviewed_by_user_id=None,
        manifest_accuracy_score=None,
        de_branding_required=bool(policy["de_branding_required"]) if policy else False,
    )
    db.lots[row["id"]] = row
    return response.created(db.view("lot", row))


@bp.get("/liquidation/lots/<lot_id>")
def read_lot(lot_id):
    mw.authenticate(READ_ALL)
    return response.success(db.view("lot", lookups.lot(lot_id)))


@bp.get("/liquidation/lots")
def list_lots():
    mw.authenticate(READ_ALL)
    return list_rows(
        "lot",
        list(db.lots.values()),
        (
            ("seller_id", "seller_id"),
            ("warehouse_id", "warehouse_id"),
            ("brand_policy_id", "brand_policy_id"),
            ("lot_status", "lot_status"),
            ("category_code", "category_code"),
        ),
    )


def _refresh_manifest(lot):
    aggregates.recompute_lot_aggregates(lot)
    if lot["lot_status"] == "MANIFEST_REJECTED":
        lot["lot_status"] = "DRAFT"
    db.touch(lot)


@bp.post("/liquidation/lots/<lot_id>/manifest-lines")
def append_manifest_line(lot_id):
    user_id, _role = mw.authenticate((mw.SELLER_OPS,))
    lot = lookups.lot(lot_id)
    guards.owns_lot(lot, user_id)
    payload = mw.body()
    if mw.present(payload, "lot_id"):
        lookups.lot(payload.get("lot_id"))
    sku = mw.req_str(payload, "sku")
    unit_count = mw.req_int(payload, "unit_count", minimum=1)
    unit_retail_cents = mw.req_int(payload, "unit_retail_cents", minimum=1)
    declared_condition = mw.req_enum(payload, "declared_condition", mw.DECLARED_CONDITIONS)
    if lot["lot_status"] not in EDITABLE_LOT_STATES:
        raise ApiError("ERR_LOT_STATE_INVALID")

    row = db.new_row(
        lot_id=lot["id"],
        sku=sku,
        unit_count=unit_count,
        unit_retail_cents=unit_retail_cents,
        declared_condition=declared_condition,
        line_status="ACTIVE",
        verified_unit_count=None,
    )
    db.manifest_lines[row["id"]] = row
    _refresh_manifest(lot)
    return response.created(db.view("manifest_line", row))


@bp.get("/liquidation/lots/<lot_id>/manifest-lines")
def list_lot_manifest_lines(lot_id):
    mw.authenticate(READ_ALL)
    lot = lookups.lot(lot_id)
    rows = [r for r in db.manifest_lines.values() if r["lot_id"] == lot["id"]]
    return list_rows("manifest_line", rows, (("line_status", "line_status"),))


@bp.get("/liquidation/manifest-lines/<line_id>")
def read_manifest_line(line_id):
    mw.authenticate(READ_ALL)
    return response.success(db.view("manifest_line", lookups.manifest_line(line_id)))


@bp.get("/liquidation/manifest-lines")
def list_manifest_lines():
    mw.authenticate(READ_ALL)
    return list_rows(
        "manifest_line",
        list(db.manifest_lines.values()),
        (("lot_id", "lot_id"), ("line_status", "line_status")),
    )


@bp.post("/liquidation/manifest-lines/<line_id>/voids")
def void_manifest_line(line_id):
    user_id, _role = mw.authenticate((mw.SELLER_OPS,))
    line = lookups.manifest_line(line_id)
    lot = lookups.lot(line["lot_id"])
    guards.owns_lot(lot, user_id)
    if lot["lot_status"] not in EDITABLE_LOT_STATES:
        raise ApiError("ERR_LOT_STATE_INVALID")
    line["line_status"] = "VOIDED"
    db.touch(line)
    _refresh_manifest(lot)
    return response.success(db.view("manifest_line", line))


@bp.post("/liquidation/lots/<lot_id>/manifest-submissions")
def submit_manifest(lot_id):
    user_id, _role = mw.authenticate((mw.SELLER_OPS,))
    lot = lookups.lot(lot_id)
    guards.owns_lot(lot, user_id)
    if lot["lot_status"] != "DRAFT":
        raise ApiError("ERR_LOT_STATE_INVALID")
    if not lookups.lines_of_lot(lot["id"], active_only=True):
        raise ApiError("ERR_MANIFEST_EMPTY")
    lot["lot_status"] = "MANIFEST_IN_REVIEW"
    db.touch(lot)
    return response.success(db.view("lot", lot))


@bp.post("/liquidation/lots/<lot_id>/manifest-reviews")
def review_manifest(lot_id):
    user_id, _role = mw.authenticate((mw.MARKETPLACE_OPS,))
    lot = lookups.lot(lot_id)
    payload = mw.body()
    decision = mw.req_enum(payload, "decision", ("APPROVE", "REJECT"))
    if lot["lot_status"] != "MANIFEST_IN_REVIEW":
        raise ApiError("ERR_LOT_STATE_INVALID")
    lot["lot_status"] = "MANIFEST_APPROVED" if decision == "APPROVE" else "MANIFEST_REJECTED"
    lot["manifest_reviewed_by_user_id"] = user_id
    db.touch(lot)
    return response.success(db.view("lot", lot))
