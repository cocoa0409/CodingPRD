from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import auth
from response import object_response, list_response
from services.query import get_or_404, paginate
from services import calc
from validate import (
    get_body, req_str, req_int, opt_int, pagination_params,
)

bp = Blueprint("invoices", __name__)


@bp.route("/invoices", methods=["POST"])
def create_invoice():
    auth(["Vendor"])
    body = get_body()
    contract_id = req_str(body, "contract_id")
    expected_version = req_int(body, "expected_contract_version")

    contract = get_or_404(db.contracts, contract_id)

    # OCC on contract version.
    if expected_version != contract["version"]:
        raise err("ERR_STALE_VERSION", "Contract version is stale.")

    clin_id = body.get("clin_id")
    invoiced_qty = body.get("invoiced_qty")
    allowable_cost = body.get("allowable_cost_cents")

    if contract["contract_type"] == "FFP":
        # FFP must carry clin_id + invoiced_qty and must NOT carry allowable_cost_cents.
        if clin_id is None or invoiced_qty is None or allowable_cost is not None:
            raise err("ERR_INVOICE_SHAPE_MISMATCH",
                      "FFP invoice requires clin_id and invoiced_qty and no allowable_cost_cents.")
        invoiced_qty = req_int(body, "invoiced_qty", minimum=0)
        clin_id = req_str(body, "clin_id")
        clin = get_or_404(db.clins, clin_id)
        if clin["contract_id"] != contract_id:
            raise err("ERR_NOT_FOUND", "CLIN does not belong to the contract.")
        invoice = {
            "contract_id": contract_id,
            "clin_id": clin_id,
            "invoiced_qty": invoiced_qty,
            "allowable_cost_cents": None,
            "amount_cents": 0,
            "fee_portion_cents": 0,
            "status": "SUBMITTED",
        }
    else:  # CPFF
        # CPFF must carry allowable_cost_cents and must NOT carry a clin_id.
        if allowable_cost is None or clin_id is not None:
            raise err("ERR_INVOICE_SHAPE_MISMATCH",
                      "CPFF invoice requires allowable_cost_cents and no clin_id.")
        allowable_cost = req_int(body, "allowable_cost_cents", minimum=0)
        invoice = {
            "contract_id": contract_id,
            "clin_id": None,
            "invoiced_qty": None,
            "allowable_cost_cents": allowable_cost,
            "amount_cents": 0,
            "fee_portion_cents": 0,
            "status": "SUBMITTED",
        }

    amount, fee = calc.compute_invoice_amount(invoice, contract)
    invoice["amount_cents"] = amount
    invoice["fee_portion_cents"] = fee

    stamp_create(invoice)
    db.invoices[invoice["id"]] = invoice

    # Submitting an invoice bumps the contract's version.
    touch(contract)

    return object_response(invoice, status=201)


@bp.route("/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    return object_response(get_or_404(db.invoices, invoice_id))


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    contract = request.args.get("contract_id")
    clin = request.args.get("clin_id")
    status = request.args.get("status")
    limit, offset = pagination_params()
    items = list(db.invoices.values())
    if contract is not None:
        items = [i for i in items if i["contract_id"] == contract]
    if clin is not None:
        items = [i for i in items if i["clin_id"] == clin]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/invoices/<invoice_id>/approve", methods=["POST"])
def approve_invoice(invoice_id):
    auth(["ContractingOfficer"])
    invoice = get_or_404(db.invoices, invoice_id)
    if invoice["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Only a SUBMITTED invoice can be approved.")

    contract = db.contracts.get(invoice["contract_id"])
    if contract is None:
        raise err("ERR_NOT_FOUND", "Parent contract does not exist.")
    if contract["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Parent contract is not ACTIVE.")
    award = db.awards.get(contract["award_id"])
    if award is None or award["status"] != "AWARDED":
        raise err("ERR_INVALID_STATE", "Parent award is not AWARDED.")

    # FFP over-delivery check (priority 15).
    if contract["contract_type"] == "FFP":
        clin = db.clins.get(invoice["clin_id"])
        if clin is None:
            raise err("ERR_NOT_FOUND", "CLIN does not exist.")
        if clin["delivered_qty"] + invoice["invoiced_qty"] > clin["funded_qty"]:
            raise err("ERR_CLIN_OVERDELIVERY",
                      "Approving this invoice would over-deliver the CLIN.")

    # Obligation ceiling check (priority 16).
    if contract["cumulative_invoiced_cents"] + invoice["amount_cents"] > contract["obligated_amount_cents"]:
        raise err("ERR_CEILING_EXCEEDED",
                  "Approving this invoice would breach the obligation ceiling.")

    # Commit.
    invoice["status"] = "APPROVED"
    touch(invoice)

    if contract["contract_type"] == "FFP":
        clin = db.clins.get(invoice["clin_id"])
        clin["delivered_qty"] += invoice["invoiced_qty"]
        touch(clin)

    contract["cumulative_invoiced_cents"] = calc.compute_cumulative_invoiced(contract)
    if contract["cumulative_invoiced_cents"] == contract["obligated_amount_cents"]:
        contract["funding_posture"] = "CEILING_REACHED"
    touch(contract)

    return object_response(invoice)


@bp.route("/invoices/<invoice_id>/reject", methods=["POST"])
def reject_invoice(invoice_id):
    auth(["ContractingOfficer"])
    invoice = get_or_404(db.invoices, invoice_id)
    if invoice["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Only a SUBMITTED invoice can be rejected.")
    invoice["status"] = "REJECTED"
    touch(invoice)
    return object_response(invoice)
