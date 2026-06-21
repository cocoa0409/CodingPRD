"""Consignment routes (PRD §3.2).

DRAFT <-> ACTIVE, either -> TERMINATED. Owned by a Seller via seller_id.
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, require_int, optional_int, parse_pagination,
    paginate, validate_occ_field, match_occ,
)
from services.domain import (
    recompute_sale_lot_count, recompute_consignment_lot_count,
)

bp = Blueprint("consignments", __name__)


def _check_seller_ownership(role, user_id, consignment):
    if role == "Seller" and user_id != consignment["seller_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning seller")


@bp.route("/consignments", methods=["POST"])
def create_consignment():
    require_role({"SaleAdministrator"})
    body = get_json_body()
    seller_id = require_string(body, "seller_id")
    commission_bps = require_int(body, "seller_commission_bps", minimum=0)
    if commission_bps > 5000:
        raise err(errors.ERR_INVALID_REQUEST,
                  "seller_commission_bps must be between 0 and 5000")
    unsold_fee = optional_int(body, "unsold_fee_cents", 0, minimum=0)

    with db.LOCK:
        # body FK existence (priority 5)
        if seller_id not in db.sellers:
            raise err(errors.ERR_FK_NOT_FOUND, "seller_id does not resolve")
        common = db.new_common()
        record = {
            "id": common["id"],
            "created_at": common["created_at"],
            "updated_at": common["updated_at"],
            "version": common["version"],
            "_seq": common["_seq"],
            "seller_id": seller_id,
            "seller_commission_bps": commission_bps,
            "unsold_fee_cents": unsold_fee,
            "status": "DRAFT",
            "lot_count": 0,
        }
        db.consignments[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/consignments/<id>", methods=["GET"])
def get_consignment(id):
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Seller", "Viewer"})
    with db.LOCK:
        record = db.consignments.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Consignment not found")
        _check_seller_ownership(role, user_id, record)
        return object_response(serialize(record), 200)


@bp.route("/consignments", methods=["GET"])
def list_consignments():
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Seller", "Viewer"})
    with db.LOCK:
        limit, offset = parse_pagination(request.args)
        seller_filter = request.args.get("seller_id")
        rows = list(db.consignments.values())
        if seller_filter is not None:
            rows = [c for c in rows if c["seller_id"] == seller_filter]
        # An entity-backed Seller listing sees only its own consignments.
        if role == "Seller":
            rows = [c for c in rows if c["seller_id"] == user_id]
        items, total = paginate(rows, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/consignments/<id>/activate", methods=["POST"])
def activate_consignment(id):
    require_role({"SaleAdministrator"})
    body = get_json_body()
    with db.LOCK:
        record = db.consignments.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Consignment not found")
        validate_occ_field(body, "expected_consignment_version", required=True)
        if record["status"] != "DRAFT":
            raise err(errors.ERR_INVALID_STATE, "Consignment is not DRAFT")
        # Seller referenced must exist.
        if record["seller_id"] not in db.sellers:
            raise err(errors.ERR_FK_NOT_FOUND, "seller_id no longer resolves")
        match_occ(record, body, "expected_consignment_version")
        record["status"] = "ACTIVE"
        db.touch(record)
        return object_response(serialize(record), 200)


@bp.route("/consignments/<id>/revert-to-draft", methods=["POST"])
def revert_consignment(id):
    require_role({"SaleAdministrator"})
    body = get_json_body()
    with db.LOCK:
        record = db.consignments.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Consignment not found")
        validate_occ_field(body, "expected_consignment_version", required=True)
        if record["status"] != "ACTIVE":
            raise err(errors.ERR_INVALID_STATE, "Consignment is not ACTIVE")
        # No lot OPEN/SOLD/BOUGHT_IN.
        for lot in db.lots.values():
            if lot["consignment_id"] == id and lot["sale_status"] in (
                    "OPEN", "SOLD", "BOUGHT_IN"):
                raise err(errors.ERR_INVALID_STATE,
                          "A lot has advanced beyond CATALOGED; cannot revert")
        match_occ(record, body, "expected_consignment_version")
        record["status"] = "DRAFT"
        db.touch(record)
        return object_response(serialize(record), 200)


@bp.route("/consignments/<id>/terminate", methods=["POST"])
def terminate_consignment(id):
    require_role({"SaleAdministrator"})
    body = get_json_body()
    with db.LOCK:
        record = db.consignments.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Consignment not found")
        validate_occ_field(body, "expected_consignment_version", required=True)
        if record["status"] not in ("DRAFT", "ACTIVE"):
            raise err(errors.ERR_INVALID_STATE, "Consignment is terminal")
        # No lot OPEN or SOLD.
        for lot in db.lots.values():
            if lot["consignment_id"] == id and lot["sale_status"] in ("OPEN", "SOLD"):
                raise err(errors.ERR_INVALID_STATE,
                          "A lot is OPEN or SOLD; cannot terminate")
        match_occ(record, body, "expected_consignment_version")

        # Cascade: every CATALOGED lot under this consignment -> WITHDRAWN.
        affected_sales = set()
        for lot in db.lots.values():
            if lot["consignment_id"] == id and lot["sale_status"] == "CATALOGED":
                lot["sale_status"] = "WITHDRAWN"
                db.touch(lot)
                affected_sales.add(lot["auction_sale_id"])
        for sale_id in affected_sales:
            recompute_sale_lot_count(sale_id)
        recompute_consignment_lot_count(id)

        record["status"] = "TERMINATED"
        db.touch(record)
        return object_response(serialize(record), 200)


@bp.route("/consignments/<id>/seller-statements", methods=["GET"])
def list_consignment_statements(id):
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Seller", "Viewer"})
    with db.LOCK:
        cons = db.consignments.get(id)
        if cons is None:
            raise err(errors.ERR_NOT_FOUND, "Consignment not found")
        _check_seller_ownership(role, user_id, cons)
        limit, offset = parse_pagination(request.args)
        rows = [s for s in db.seller_statements.values() if s["consignment_id"] == id]
        items, total = paginate(rows, limit, offset)
        return array_response(items, limit, offset, total, 200)
