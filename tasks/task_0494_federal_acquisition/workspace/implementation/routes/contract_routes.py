from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import auth
from response import object_response, list_response
from services.query import get_or_404, paginate
from services import calc
from validate import (
    get_body, req_str, req_int, opt_int, req_enum, pagination_params,
)

bp = Blueprint("contracts", __name__)

CONTRACT_TYPES = {"FFP", "CPFF"}


@bp.route("/contracts", methods=["POST"])
def create_contract():
    auth(["ContractingOfficer"])
    body = get_body()
    award_id = req_str(body, "award_id")
    contract_type = req_enum(body, "contract_type", CONTRACT_TYPES)
    base_value = req_int(body, "base_value_cents", minimum=0)

    award = get_or_404(db.awards, award_id)

    tec = None
    fixed_fee = None
    if contract_type == "CPFF":
        # Required for CPFF; semantic failure -> ERR_VALIDATION.
        if body.get("total_estimated_cost_cents") is None or body.get("fixed_fee_cents") is None:
            raise err("ERR_VALIDATION",
                      "CPFF contracts require total_estimated_cost_cents and fixed_fee_cents.")
        tec = req_int(body, "total_estimated_cost_cents")
        if tec <= 0:
            raise err("ERR_VALIDATION", "total_estimated_cost_cents must be > 0 for CPFF.")
        fixed_fee = req_int(body, "fixed_fee_cents")
        if fixed_fee < 0:
            raise err("ERR_VALIDATION", "fixed_fee_cents must be >= 0 for CPFF.")

    # vendor_id copied from the winning proposal of the award.
    proposal = db.proposals.get(award["proposal_id"])
    vendor_id = proposal["vendor_id"] if proposal else None

    contract = {
        "award_id": award_id,
        "vendor_id": vendor_id,
        "contract_type": contract_type,
        "total_estimated_cost_cents": tec,
        "fixed_fee_cents": fixed_fee,
        "base_value_cents": base_value,
        "obligated_amount_cents": base_value,
        "lifecycle_status": "ACTIVE",
        "funding_posture": "WITHIN_CEILING",
        "cumulative_invoiced_cents": 0,
    }
    stamp_create(contract)
    db.contracts[contract["id"]] = contract
    return object_response(contract, status=201)


@bp.route("/contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    return object_response(get_or_404(db.contracts, contract_id))


@bp.route("/contracts", methods=["GET"])
def list_contracts():
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    award = request.args.get("award_id")
    vendor = request.args.get("vendor_id")
    lifecycle = request.args.get("lifecycle_status")
    limit, offset = pagination_params()
    items = list(db.contracts.values())
    if award is not None:
        items = [c for c in items if c["award_id"] == award]
    if vendor is not None:
        items = [c for c in items if c["vendor_id"] == vendor]
    if lifecycle is not None:
        items = [c for c in items if c["lifecycle_status"] == lifecycle]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


# ---- CLINs ----

@bp.route("/contracts/<contract_id>/clins", methods=["POST"])
def add_clin(contract_id):
    auth(["ContractingOfficer"])
    contract = get_or_404(db.contracts, contract_id)
    if contract["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "CLINs can only be added to an ACTIVE contract.")
    body = get_body()
    clin_number = req_str(body, "clin_number")
    funded_qty = req_int(body, "funded_qty", minimum=0)
    unit_price = opt_int(body, "unit_price_cents", default=None, minimum=0)

    # Uniqueness of clin_number within the contract.
    for c in db.clins.values():
        if c["contract_id"] == contract_id and c["clin_number"] == clin_number:
            raise err("ERR_DUPLICATE_CLIN", "clin_number already exists on this contract.")

    clin = {
        "contract_id": contract_id,
        "clin_number": clin_number,
        "unit_price_cents": unit_price,
        "funded_qty": funded_qty,
        "delivered_qty": 0,
    }
    stamp_create(clin)
    db.clins[clin["id"]] = clin
    return object_response(clin, status=201)


@bp.route("/contracts/<contract_id>/clins", methods=["GET"])
def list_clins(contract_id):
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    get_or_404(db.contracts, contract_id)
    limit, offset = pagination_params()
    items = [c for c in db.clins.values() if c["contract_id"] == contract_id]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


# ---- lifecycle ----

@bp.route("/contracts/<contract_id>/complete", methods=["POST"])
def complete_contract(contract_id):
    auth(["ContractingOfficer"])
    contract = get_or_404(db.contracts, contract_id)
    if contract["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE contract can be completed.")
    # No invoice in SUBMITTED remains.
    if any(i["contract_id"] == contract_id and i["status"] == "SUBMITTED"
           for i in db.invoices.values()):
        raise err("ERR_INVALID_STATE", "A SUBMITTED invoice still remains.")
    award = db.awards.get(contract["award_id"])
    if award is None or award["status"] != "AWARDED":
        raise err("ERR_INVALID_STATE", "Parent award must be AWARDED.")
    contract["lifecycle_status"] = "COMPLETE"
    touch(contract)
    return object_response(contract)


@bp.route("/contracts/<contract_id>/closeout", methods=["POST"])
def closeout_contract(contract_id):
    auth(["ContractingOfficer"])
    contract = get_or_404(db.contracts, contract_id)
    if contract["lifecycle_status"] != "COMPLETE":
        raise err("ERR_INVALID_STATE", "Only a COMPLETE contract can be closed out.")
    if not any(r["contract_id"] == contract_id for r in db.cpars.values()):
        raise err("ERR_INVALID_STATE", "At least one CPARS report is required to close out.")
    award = db.awards.get(contract["award_id"])
    if award is None or award["status"] != "AWARDED":
        raise err("ERR_INVALID_STATE", "Parent award must be AWARDED.")
    contract["lifecycle_status"] = "CLOSED"
    touch(contract)
    # Recompute the awardee vendor's performance index.
    if contract["vendor_id"] is not None:
        vendor = db.vendors.get(contract["vendor_id"])
        if vendor is not None:
            vendor["performance_index"] = calc.compute_performance_index(contract["vendor_id"])
            touch(vendor)
    return object_response(contract)
