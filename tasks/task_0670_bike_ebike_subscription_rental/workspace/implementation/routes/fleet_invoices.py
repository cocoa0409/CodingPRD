from flask import Blueprint, request

from db import db
from middleware import require_role
from response import object_response, array_response
from errors import err, ERR_INVALID_REQUEST, ERR_NOT_FLEET_ACCOUNT, ERR_INVALID_STATE
from services.common import (
    stamp_create, touch, get_json_body, require_fields, parse_pagination, paginate,
)
from services.lookups import get_account, get_invoice, check_account_ownership
from services.reconcile import recompute_active_rental_count
from services.serialize import fleet_invoice_view
from services import calculations as calc

fleet_invoices_bp = Blueprint("fleet_invoices", __name__)

VIEW_ROLES = {"OpsAdmin", "FleetManager"}


@fleet_invoices_bp.route("/accounts/<account_id>/fleet-invoices", methods=["POST"])
def create_fleet_invoice(account_id):
    user_id, role = require_role({"OpsAdmin", "FleetManager"})
    body = get_json_body()
    with db.lock:
        account = get_account(account_id)
        # FleetManager may only act on its own account (entity-backed ownership).
        check_account_ownership(account, user_id, role)
        require_fields(body, ["cycle_index"])
        cycle_index = body["cycle_index"]
        if not isinstance(cycle_index, int) or isinstance(cycle_index, bool) or cycle_index < 0:
            raise err(ERR_INVALID_REQUEST, "cycle_index must be a non-negative integer.")
        # Only FLEET accounts may be invoiced.
        if account["account_type"] != "FLEET":
            raise err(ERR_NOT_FLEET_ACCOUNT, "Account is not a FLEET account.")

        # Lines: MONTHLY rentals for the account in {ACTIVE, IN_SERVICE},
        # ordered by created_at ASC (insertion seq tiebreak).
        lines = [
            r for r in db.rentals.values()
            if r["account_id"] == account_id
            and r["rental_mode"] == "MONTHLY"
            and r["lifecycle_status"] in ("ACTIVE", "IN_SERVICE")
        ]
        lines.sort(key=lambda r: r["_seq"])
        lines_with_models = [(r, db.bike_models[r["model_id"]]) for r in lines]
        amounts = calc.fleet_invoice_amounts(lines_with_models)

        invoice = {
            "account_id": account_id,
            "cycle_index": cycle_index,
            "line_count": amounts["line_count"],
            "gross_amount_cents": amounts["gross_amount_cents"],
            "discount_cents": amounts["discount_cents"],
            "amount_due_cents": amounts["amount_due_cents"],
            "status": "ISSUED",
        }
        stamp_create(invoice)
        db.fleet_invoices[invoice["id"]] = invoice
    return object_response(fleet_invoice_view(invoice), 201)


@fleet_invoices_bp.route("/fleet-invoices/<invoice_id>", methods=["GET"])
def fetch_invoice(invoice_id):
    require_role(VIEW_ROLES)
    invoice = get_invoice(invoice_id)
    return object_response(fleet_invoice_view(invoice), 200)


@fleet_invoices_bp.route("/accounts/<account_id>/fleet-invoices", methods=["GET"])
def list_invoices(account_id):
    user_id, role = require_role(VIEW_ROLES)
    account = get_account(account_id)
    check_account_ownership(account, user_id, role)
    limit, offset = parse_pagination()
    records = [i for i in db.fleet_invoices.values() if i["account_id"] == account_id]
    status = request.args.get("status")
    if status:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response([fleet_invoice_view(r) for r in page], limit, offset, total)


@fleet_invoices_bp.route("/fleet-invoices/<invoice_id>/pay", methods=["POST"])
def pay_invoice(invoice_id):
    user_id, role = require_role(VIEW_ROLES)
    with db.lock:
        invoice = get_invoice(invoice_id)
        account = db.accounts.get(invoice["account_id"])
        if account is not None:
            check_account_ownership(account, user_id, role)
        if invoice["status"] != "ISSUED":
            raise err(ERR_INVALID_STATE, "Invoice must be ISSUED to pay.")
        invoice["status"] = "PAID"
        touch(invoice)
        # outstanding_balance_cents is derived; recomputed on read.
    return object_response(fleet_invoice_view(invoice), 200)
