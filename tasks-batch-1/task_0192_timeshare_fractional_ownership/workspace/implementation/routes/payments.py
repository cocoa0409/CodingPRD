"""Payment routes: create, get, list, clear, fail, reverse."""
from flask import request

from db import db, stamp_create, touch
import errors
from errors import err
from middleware import get_user_context, require_role
from response import success
from routes.common import get_or_404, get_json, list_response, check_owner_of_contract
from services.util import serialize, require_str, require_int
from services.cascade import allocate_payment, reverse_payment

# Public payment fields (hide internal allocation bookkeeping).
_PAYMENT_HIDDEN = {"allocations", "cured_case_id", "cured_case_prior_status"}


def serialize_payment(p):
    return serialize({k: v for k, v in p.items() if k not in _PAYMENT_HIDDEN})


def register(app):
    @app.route("/payments", methods=["POST"])
    def create_payment():
        user_id, role = get_user_context()
        require_role(role, ["ResortManager", "Owner"])
        data = get_json()
        contract_id = require_str(data, "contract_id")
        amount_cents = require_int(data, "amount_cents", positive=True)
        invoice_id = data.get("invoice_id")
        if invoice_id is not None and not isinstance(invoice_id, str):
            raise err(errors.ERR_INVALID_REQUEST, "invoice_id must be a string.")

        contract = db.contracts.get(contract_id)
        if contract is None:
            raise err(errors.ERR_NOT_FOUND, "Contract not found.")
        # Ownership (priority 3).
        check_owner_of_contract(role, user_id, contract)
        # Cross-resort referential integrity for invoice_id (priority 6).
        if invoice_id is not None:
            inv = db.invoices.get(invoice_id)
            if inv is None:
                raise err(errors.ERR_NOT_FOUND, "Invoice not found.")
            inv_contract = db.contracts.get(inv["contract_id"])
            if inv_contract is None or inv_contract["resort_id"] != contract["resort_id"]:
                raise err(
                    errors.ERR_CROSS_RESORT_REFERENCE, "Invoice belongs to a different resort."
                )

        payment = {
            "contract_id": contract_id,
            "amount_cents": amount_cents,
            "invoice_id": invoice_id,
            "status": "INITIATED",
            "allocations": [],
            "cured_case_id": None,
            "cured_case_prior_status": None,
        }
        stamp_create(payment)
        db.payments[payment["id"]] = payment
        return success(serialize_payment(payment), status=201)

    @app.route("/payments/<payment_id>", methods=["GET"])
    def get_payment(payment_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        p = get_or_404(db.payments, payment_id)
        return success(serialize_payment(p))

    @app.route("/payments", methods=["GET"])
    def list_payments():
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        items = list(db.payments.values())
        for key in ("contract_id", "invoice_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [p for p in items if p.get(key) == val]
        return list_response(items, serialize_payment)

    @app.route("/payments/<payment_id>/clear", methods=["POST"])
    def clear_payment(payment_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager"])
        p = get_or_404(db.payments, payment_id)
        if p["status"] != "INITIATED":
            raise err(errors.ERR_INVALID_STATE, "Payment is not INITIATED.")
        contract = db.contracts[p["contract_id"]]
        resort = db.resorts[contract["resort_id"]]
        p["status"] = "CLEARED"
        touch(p)
        allocate_payment(p, contract, resort)
        return success(serialize_payment(p))

    @app.route("/payments/<payment_id>/fail", methods=["POST"])
    def fail_payment(payment_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager"])
        p = get_or_404(db.payments, payment_id)
        if p["status"] != "INITIATED":
            raise err(errors.ERR_INVALID_STATE, "Payment is not INITIATED.")
        p["status"] = "FAILED"
        touch(p)
        return success(serialize_payment(p))

    @app.route("/payments/<payment_id>/reverse", methods=["POST"])
    def reverse_payment_route(payment_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager"])
        p = get_or_404(db.payments, payment_id)
        if p["status"] != "CLEARED":
            raise err(errors.ERR_INVALID_STATE, "Payment is not CLEARED.")
        contract = db.contracts[p["contract_id"]]
        resort = db.resorts[contract["resort_id"]]
        p["status"] = "REVERSED"
        touch(p)
        reverse_payment(p, contract, resort)
        return success(serialize_payment(p))
