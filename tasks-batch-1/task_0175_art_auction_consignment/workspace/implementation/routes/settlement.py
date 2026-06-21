"""Settlement routes: invoice, payment, statement, disburse, and the
settlement-entity reads/lists (PRD §3.6–§3.9).
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_int, parse_pagination, paginate,
    validate_occ_field, match_occ,
)
from services.domain import recompute_bidder_outstanding
from services.calculations import (
    buyers_premium_cents, resale_royalty_cents, seller_commission_cents,
)

bp = Blueprint("settlement", __name__)


def _seller_owns_lot(role, user_id, lot):
    if role != "Seller":
        return
    cons = db.consignments.get(lot["consignment_id"])
    if cons is None or cons["seller_id"] != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning seller")


# ---------------------------------------------------------------------------
# POST /lots/{id}/invoice  (FinanceOfficer)  -> 201 Invoice
# ---------------------------------------------------------------------------
@bp.route("/lots/<id>/invoice", methods=["POST"])
def issue_invoice(id):
    require_role({"FinanceOfficer"})
    body = get_json_body()
    with db.LOCK:
        lot = db.lots.get(id)
        if lot is None:
            raise err(errors.ERR_NOT_FOUND, "Lot not found")
        # priority 6: body well-formedness (OCC field presence/type)
        validate_occ_field(body, "expected_lot_version", required=True)
        # priority 7: single-entity precondition (SOLD + settlement NONE)
        if lot["sale_status"] != "SOLD" or lot["settlement_status"] != "NONE":
            raise err(errors.ERR_INVALID_STATE, "Lot not SOLD / already in settlement")
        # priority 8: cross-entity dependency — sale CLOSED
        sale = db.auction_sales.get(lot["auction_sale_id"])
        if sale is None or sale["status"] != "CLOSED":
            raise err(errors.ERR_DEPENDENCY_NOT_READY, "Sale is not CLOSED")
        # priority 9: OCC match
        match_occ(lot, body, "expected_lot_version")

        # Resolve winning paddle + bidder.
        paddle_id = lot["winning_paddle_registration_id"]
        paddle = db.paddle_registrations.get(paddle_id)
        bidder_id = paddle["bidder_id"] if paddle else None

        hammer = lot["hammer_price_cents"]
        schedule = db.premium_schedules.get(sale["buyers_premium_schedule_id"])
        tiers = schedule["tiers"] if schedule else []
        premium = buyers_premium_cents(hammer, tiers)
        total_due = hammer + premium

        common = db.new_common()
        invoice = {
            "id": common["id"],
            "created_at": common["created_at"],
            "updated_at": common["updated_at"],
            "version": common["version"],
            "_seq": common["_seq"],
            "lot_id": id,
            "paddle_registration_id": paddle_id,
            "bidder_id": bidder_id,
            "hammer_price_cents": hammer,
            "buyers_premium_cents": premium,
            "total_due_cents": total_due,
            "amount_paid_cents": 0,
            "status": "ISSUED",
        }
        db.invoices[invoice["id"]] = invoice

        # Recompute winning bidder's outstanding balance (now includes this).
        if bidder_id is not None:
            recompute_bidder_outstanding(bidder_id)

        # Accrue resale royalty if eligible.
        eligible, royalty_amount = resale_royalty_cents(hammer, lot["artist_alive"])
        if eligible:
            rc = db.new_common()
            royalty = {
                "id": rc["id"],
                "created_at": rc["created_at"],
                "updated_at": rc["updated_at"],
                "version": rc["version"],
                "_seq": rc["_seq"],
                "lot_id": id,
                "hammer_price_cents": hammer,
                "royalty_cents": royalty_amount,
                "bearer": "SELLER",
                "status": "ACCRUED",
            }
            db.resale_royalties[royalty["id"]] = royalty

        lot["settlement_status"] = "INVOICED"
        db.touch(lot)
        return object_response(serialize(invoice), 201)


# ---------------------------------------------------------------------------
# POST /invoices/{id}/payments  (FinanceOfficer)  -> 200 Invoice
# ---------------------------------------------------------------------------
@bp.route("/invoices/<id>/payments", methods=["POST"])
def record_payment(id):
    require_role({"FinanceOfficer"})
    body = get_json_body()
    with db.LOCK:
        invoice = db.invoices.get(id)
        if invoice is None:
            raise err(errors.ERR_NOT_FOUND, "Invoice not found")
        # priority 6: body well-formed (amount + OCC field presence/type)
        amount = require_int(body, "amount_cents", minimum=None)
        validate_occ_field(body, "expected_invoice_version", required=True)
        # priority 7: single-entity state — invoice must be ISSUED
        if invoice["status"] != "ISSUED":
            raise err(errors.ERR_INVALID_STATE, "Invoice is not ISSUED")
        # priority 9: OCC match
        match_occ(invoice, body, "expected_invoice_version")
        # priority 14: payment amount must be > 0 and <= remaining due
        remaining = invoice["total_due_cents"] - invoice["amount_paid_cents"]
        if amount <= 0 or amount > remaining:
            raise err(errors.ERR_CREDIT_LIMIT_EXCEEDED, "Invalid payment amount")

        invoice["amount_paid_cents"] += amount
        if invoice["amount_paid_cents"] >= invoice["total_due_cents"]:
            invoice["status"] = "PAID"
            db.touch(invoice)
            recompute_bidder_outstanding(invoice["bidder_id"])
        else:
            db.touch(invoice)
        return object_response(serialize(invoice), 200)


@bp.route("/invoices/<id>", methods=["GET"])
def get_invoice(id):
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Bidder", "Viewer"})
    with db.LOCK:
        invoice = db.invoices.get(id)
        if invoice is None:
            raise err(errors.ERR_NOT_FOUND, "Invoice not found")
        if role == "Bidder" and invoice["bidder_id"] != user_id:
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning bidder's invoice")
        return object_response(serialize(invoice), 200)


@bp.route("/lots/<id>/invoices", methods=["GET"])
def list_lot_invoices(id):
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Bidder", "Viewer"})
    with db.LOCK:
        lot = db.lots.get(id)
        if lot is None:
            raise err(errors.ERR_NOT_FOUND, "Lot not found")
        limit, offset = parse_pagination(request.args)
        rows = [inv for inv in db.invoices.values() if inv["lot_id"] == id]
        if role == "Bidder":
            rows = [inv for inv in rows if inv["bidder_id"] == user_id]
        items, total = paginate(rows, limit, offset)
        return array_response(items, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# POST /lots/{id}/statement  (FinanceOfficer)  -> 201 SellerStatement
# ---------------------------------------------------------------------------
@bp.route("/lots/<id>/statement", methods=["POST"])
def generate_statement(id):
    require_role({"FinanceOfficer"})
    body = get_json_body()
    with db.LOCK:
        lot = db.lots.get(id)
        if lot is None:
            raise err(errors.ERR_NOT_FOUND, "Lot not found")
        # priority 6: body well-formedness (OCC field presence/type)
        validate_occ_field(body, "expected_lot_version", required=True)
        # priority 7: single-entity — lot settlement_status INVOICED
        if lot["settlement_status"] != "INVOICED":
            raise err(errors.ERR_INVALID_STATE, "Lot is not INVOICED")
        # priority 8: cross-entity — the lot's Invoice must be PAID
        invoice = _latest_lot_invoice(id, status="PAID")
        if invoice is None:
            raise err(errors.ERR_DEPENDENCY_NOT_READY, "Invoice is not PAID")
        # priority 9: OCC match
        match_occ(lot, body, "expected_lot_version")

        cons = db.consignments.get(lot["consignment_id"])
        hammer = lot["hammer_price_cents"]
        commission = seller_commission_cents(hammer, cons["seller_commission_bps"])

        # resale_royalty_withheld: royalty row for lot, bearer SELLER, not REVERSED.
        withheld = 0
        for roy in db.resale_royalties.values():
            if (roy["lot_id"] == id and roy["bearer"] == "SELLER"
                    and roy["status"] != "REVERSED"):
                withheld = roy["royalty_cents"]
                break

        net = hammer - commission - withheld

        common = db.new_common()
        statement = {
            "id": common["id"],
            "created_at": common["created_at"],
            "updated_at": common["updated_at"],
            "version": common["version"],
            "_seq": common["_seq"],
            "lot_id": id,
            "consignment_id": lot["consignment_id"],
            "hammer_price_cents": hammer,
            "seller_commission_cents": commission,
            "resale_royalty_withheld_cents": withheld,
            "net_payable_cents": net,
            "status": "PENDING",
        }
        db.seller_statements[statement["id"]] = statement

        lot["settlement_status"] = "STATEMENTED"
        db.touch(lot)
        return object_response(serialize(statement), 201)


def _latest_lot_invoice(lot_id, status=None):
    rows = [inv for inv in db.invoices.values() if inv["lot_id"] == lot_id]
    if status is not None:
        rows = [inv for inv in rows if inv["status"] == status]
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    return rows[-1]


@bp.route("/seller-statements/<id>", methods=["GET"])
def get_statement(id):
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Seller", "Viewer"})
    with db.LOCK:
        statement = db.seller_statements.get(id)
        if statement is None:
            raise err(errors.ERR_NOT_FOUND, "Seller statement not found")
        if role == "Seller":
            cons = db.consignments.get(statement["consignment_id"])
            if cons is None or cons["seller_id"] != user_id:
                raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning seller")
        return object_response(serialize(statement), 200)


@bp.route("/lots/<id>/seller-statements", methods=["GET"])
def list_lot_statements(id):
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Seller", "Viewer"})
    with db.LOCK:
        lot = db.lots.get(id)
        if lot is None:
            raise err(errors.ERR_NOT_FOUND, "Lot not found")
        _seller_owns_lot(role, user_id, lot)
        limit, offset = parse_pagination(request.args)
        rows = [s for s in db.seller_statements.values() if s["lot_id"] == id]
        items, total = paginate(rows, limit, offset)
        return array_response(items, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# POST /seller-statements/{id}/disburse  (FinanceOfficer)  -> 201 Payout
# ---------------------------------------------------------------------------
@bp.route("/seller-statements/<id>/disburse", methods=["POST"])
def disburse_statement(id):
    require_role({"FinanceOfficer"})
    body = get_json_body()
    with db.LOCK:
        statement = db.seller_statements.get(id)
        if statement is None:
            raise err(errors.ERR_NOT_FOUND, "Seller statement not found")
        lot = db.lots.get(statement["lot_id"])
        # priority 6: body well-formedness (OCC field presence/type)
        validate_occ_field(body, "expected_seller_statement_version", required=True)
        # priority 7: single-entity — lot STATEMENTED and statement PENDING
        if statement["status"] != "PENDING":
            raise err(errors.ERR_INVALID_STATE, "Statement is not PENDING")
        if lot is None or lot["settlement_status"] != "STATEMENTED":
            raise err(errors.ERR_INVALID_STATE, "Lot is not STATEMENTED")
        # priority 9: OCC match
        match_occ(statement, body, "expected_seller_statement_version")

        # Create the Payout (terminal DISBURSED).
        common = db.new_common()
        payout = {
            "id": common["id"],
            "created_at": common["created_at"],
            "updated_at": common["updated_at"],
            "version": common["version"],
            "_seq": common["_seq"],
            "seller_statement_id": id,
            "amount_cents": statement["net_payable_cents"],
            "status": "DISBURSED",
        }
        db.payouts[payout["id"]] = payout

        # Statement -> PAID
        statement["status"] = "PAID"
        db.touch(statement)

        # ACCRUED royalty -> REMITTED
        for roy in db.resale_royalties.values():
            if roy["lot_id"] == lot["id"] and roy["status"] == "ACCRUED":
                roy["status"] = "REMITTED"
                db.touch(roy)

        # Lot settlement -> SETTLED
        lot["settlement_status"] = "SETTLED"
        db.touch(lot)
        return object_response(serialize(payout), 201)


@bp.route("/payouts/<id>", methods=["GET"])
def get_payout(id):
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Seller", "Viewer"})
    with db.LOCK:
        payout = db.payouts.get(id)
        if payout is None:
            raise err(errors.ERR_NOT_FOUND, "Payout not found")
        if role == "Seller":
            statement = db.seller_statements.get(payout["seller_statement_id"])
            cons = db.consignments.get(statement["consignment_id"]) if statement else None
            if cons is None or cons["seller_id"] != user_id:
                raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning seller")
        return object_response(serialize(payout), 200)


@bp.route("/seller-statements/<id>/payouts", methods=["GET"])
def list_statement_payouts(id):
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Seller", "Viewer"})
    with db.LOCK:
        statement = db.seller_statements.get(id)
        if statement is None:
            raise err(errors.ERR_NOT_FOUND, "Seller statement not found")
        if role == "Seller":
            cons = db.consignments.get(statement["consignment_id"])
            if cons is None or cons["seller_id"] != user_id:
                raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning seller")
        limit, offset = parse_pagination(request.args)
        rows = [p for p in db.payouts.values() if p["seller_statement_id"] == id]
        items, total = paginate(rows, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/lots/<id>/resale-royalties", methods=["GET"])
def list_lot_royalties(id):
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Seller", "Viewer"})
    with db.LOCK:
        lot = db.lots.get(id)
        if lot is None:
            raise err(errors.ERR_NOT_FOUND, "Lot not found")
        _seller_owns_lot(role, user_id, lot)
        limit, offset = parse_pagination(request.args)
        rows = [r for r in db.resale_royalties.values() if r["lot_id"] == id]
        items, total = paginate(rows, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/resale-royalties/<id>", methods=["GET"])
def get_royalty(id):
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Seller", "Viewer"})
    with db.LOCK:
        royalty = db.resale_royalties.get(id)
        if royalty is None:
            raise err(errors.ERR_NOT_FOUND, "Resale royalty not found")
        if role == "Seller":
            lot = db.lots.get(royalty["lot_id"])
            cons = db.consignments.get(lot["consignment_id"]) if lot else None
            if cons is None or cons["seller_id"] != user_id:
                raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning seller")
        return object_response(serialize(royalty), 200)
