"""MaintenanceFeeInvoice routes: create, get, list, issue, mark-delinquent."""
from flask import request

from db import db, stamp_create, touch
import errors
from errors import err
from middleware import get_user_context, require_role
from response import success
from routes.common import get_or_404, get_json, list_response
from services.util import serialize, require_str, require_int, require_enum, parse_iso
from services.calc import annual_full_fee
from services.computed import serialize_invoice, invoice_amount_due
from services.cascade import grace_elapsed, open_delinquency_case_for

SOURCE_TYPES = {"ANNUAL", "SPECIAL_ASSESSMENT"}


def _points_basis(contract):
    """Points basis for the annual fee: allotment (POINTS) or fixed unit points_value (FIXED_WEEK)."""
    if contract["inventory_model"] == "FIXED_WEEK" and contract.get("fixed_unit_id"):
        unit = db.inventory_units.get(contract["fixed_unit_id"])
        if unit is not None:
            return unit["points_value"]
        return 0
    return contract["annual_points_allotment"]


def provisional_amount(resort, contract):
    return annual_full_fee(resort, _points_basis(contract))


def register(app):
    @app.route("/invoices", methods=["POST"])
    def create_invoice():
        _, role = get_user_context()
        require_role(role, ["ResortManager"])
        data = get_json()
        contract_id = require_str(data, "contract_id")
        source_type = require_enum(data, "source_type", SOURCE_TYPES)
        use_year = require_int(data, "use_year")
        due_date = require_str(data, "due_date")
        try:
            parse_iso(due_date)
        except Exception:
            raise err(errors.ERR_INVALID_REQUEST, "due_date is not a valid ISO 8601 timestamp.")
        special_assessment_id = data.get("special_assessment_id")
        if special_assessment_id is not None and not isinstance(special_assessment_id, str):
            raise err(errors.ERR_INVALID_REQUEST, "special_assessment_id must be a string.")

        # Existence + cross-resort (priority 4 then 6).
        contract = db.contracts.get(contract_id)
        if contract is None:
            raise err(errors.ERR_NOT_FOUND, "Contract not found.")
        resort = db.resorts[contract["resort_id"]]
        if special_assessment_id is not None:
            sa = db.special_assessments.get(special_assessment_id)
            if sa is None:
                raise err(errors.ERR_NOT_FOUND, "Special assessment not found.")
            if sa["resort_id"] != contract["resort_id"]:
                raise err(
                    errors.ERR_CROSS_RESORT_REFERENCE,
                    "Special assessment belongs to a different resort.",
                )

        invoice = {
            "contract_id": contract_id,
            "owner_id": contract["owner_id"],
            "source_type": source_type,
            "special_assessment_id": special_assessment_id,
            "use_year": use_year,
            "amount_cents": provisional_amount(resort, contract),
            "late_charge_cents": 0,
            "amount_paid_cents": 0,
            "due_date": due_date,
            "status": "DRAFT",
        }
        stamp_create(invoice)
        db.invoices[invoice["id"]] = invoice
        return success(serialize_invoice(invoice), status=201)

    @app.route("/invoices/<invoice_id>", methods=["GET"])
    def get_invoice(invoice_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        inv = get_or_404(db.invoices, invoice_id)
        return success(serialize_invoice(inv))

    @app.route("/invoices", methods=["GET"])
    def list_invoices():
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        items = list(db.invoices.values())
        for key in ("contract_id", "owner_id", "status", "special_assessment_id"):
            val = request.args.get(key)
            if val is not None:
                items = [i for i in items if i.get(key) == val]
        use_year = request.args.get("use_year")
        if use_year is not None:
            try:
                uy = int(use_year)
            except (TypeError, ValueError):
                raise err(errors.ERR_INVALID_REQUEST, "use_year must be an integer.")
            items = [i for i in items if i["use_year"] == uy]
        return list_response(items, serialize_invoice)

    @app.route("/invoices/<invoice_id>/issue", methods=["POST"])
    def issue_invoice(invoice_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager"])
        inv = get_or_404(db.invoices, invoice_id)
        if inv["status"] != "DRAFT":
            raise err(errors.ERR_INVALID_STATE, "Invoice is not DRAFT.")
        contract = db.contracts[inv["contract_id"]]
        # Priority 9: contract must be ACTIVE or SUSPENDED.
        if contract["status"] not in ("ACTIVE", "SUSPENDED"):
            raise err(errors.ERR_CONTRACT_NOT_ACTIVE, "Owning contract is not ACTIVE/SUSPENDED.")
        inv["status"] = "ISSUED"
        # Finalize amount: full-year figure (resale split only happens on transfer complete).
        if inv["source_type"] == "ANNUAL":
            resort = db.resorts[contract["resort_id"]]
            inv["amount_cents"] = provisional_amount(resort, contract)
        touch(inv)
        return success(serialize_invoice(inv))

    @app.route("/invoices/<invoice_id>/mark-delinquent", methods=["POST"])
    def mark_delinquent(invoice_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager"])
        inv = get_or_404(db.invoices, invoice_id)
        if inv["status"] != "ISSUED":
            raise err(errors.ERR_INVALID_STATE, "Invoice is not ISSUED.")
        contract = db.contracts[inv["contract_id"]]
        resort = db.resorts[contract["resort_id"]]
        # Priority: amount_due > 0 (ERR_INVOICE_NOT_PAYABLE) then grace gate.
        if invoice_amount_due(inv) <= 0:
            raise err(errors.ERR_INVOICE_NOT_PAYABLE, "Invoice has no outstanding balance.")
        if not grace_elapsed(resort, inv):
            raise err(errors.ERR_GRACE_PERIOD_ACTIVE, "Grace period has not elapsed.")
        inv["status"] = "DELINQUENT"
        touch(inv)
        open_delinquency_case_for(contract, inv)
        return success(serialize_invoice(inv))
