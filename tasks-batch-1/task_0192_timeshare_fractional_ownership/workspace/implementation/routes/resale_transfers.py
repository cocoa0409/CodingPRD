"""ResaleTransfer routes: create, get, list, complete, rescind."""
from flask import request

from db import db, stamp_create, touch
import errors
from errors import err
from middleware import get_user_context, require_role
from response import success
from routes.common import get_or_404, get_json, list_response, check_owner_of_contract
from services.util import serialize, require_str, require_int, parse_iso, add_days
from services.calc import annual_full_fee, resale_seller_share
from services.cascade import open_case_for_contract


def serialize_transfer(t):
    return serialize(t)


def _points_basis(contract):
    if contract["inventory_model"] == "FIXED_WEEK" and contract.get("fixed_unit_id"):
        unit = db.inventory_units.get(contract["fixed_unit_id"])
        if unit is not None:
            return unit["points_value"]
        return 0
    return contract["annual_points_allotment"]


def register(app):
    @app.route("/resale-transfers", methods=["POST"])
    def create_transfer():
        _, role = get_user_context()
        require_role(role, ["ResaleAgent"])
        data = get_json()
        source_contract_id = require_str(data, "source_contract_id")
        buyer_owner_id = require_str(data, "buyer_owner_id")
        sale_price_cents = require_int(data, "sale_price_cents", minimum=0)
        transfer_use_year = require_int(data, "transfer_use_year")
        transfer_day_of_year = require_int(data, "transfer_day_of_year")
        if transfer_day_of_year < 1 or transfer_day_of_year > 365:
            raise err(errors.ERR_INVALID_REQUEST, "transfer_day_of_year must be in 1..365.")

        # Existence + cross-resort (priority 4 then 6).
        source = db.contracts.get(source_contract_id)
        if source is None:
            raise err(errors.ERR_NOT_FOUND, "Source contract not found.")
        buyer = db.owners.get(buyer_owner_id)
        if buyer is None:
            raise err(errors.ERR_NOT_FOUND, "Buyer owner not found.")
        if buyer["resort_id"] != source["resort_id"]:
            raise err(errors.ERR_CROSS_RESORT_REFERENCE, "Buyer belongs to a different resort.")

        resort = db.resorts[source["resort_id"]]
        transfer = {
            "source_contract_id": source_contract_id,
            "resort_id": source["resort_id"],
            "buyer_owner_id": buyer_owner_id,
            "sale_price_cents": sale_price_cents,
            "transfer_use_year": transfer_use_year,
            "transfer_day_of_year": transfer_day_of_year,
            "new_contract_id": None,
            "signed_at": resort["current_utc"],
            "status": "PENDING_RESCISSION",
        }
        stamp_create(transfer)
        db.resale_transfers[transfer["id"]] = transfer
        return success(serialize_transfer(transfer), status=201)

    @app.route("/resale-transfers/<transfer_id>", methods=["GET"])
    def get_transfer(transfer_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        t = get_or_404(db.resale_transfers, transfer_id)
        return success(serialize_transfer(t))

    @app.route("/resale-transfers", methods=["GET"])
    def list_transfers():
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        items = list(db.resale_transfers.values())
        for key in ("source_contract_id", "buyer_owner_id", "new_contract_id", "resort_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [t for t in items if t.get(key) == val]
        return list_response(items, serialize_transfer)

    @app.route("/resale-transfers/<transfer_id>/complete", methods=["POST"])
    def complete_transfer(transfer_id):
        _, role = get_user_context()
        require_role(role, ["ResaleAgent"])
        t = get_or_404(db.resale_transfers, transfer_id)
        if t["status"] != "PENDING_RESCISSION":
            raise err(errors.ERR_INVALID_STATE, "Transfer is not PENDING_RESCISSION.")
        resort = db.resorts[t["resort_id"]]
        source = db.contracts[t["source_contract_id"]]
        # Priority 8: rescission window must have elapsed.
        threshold = add_days(parse_iso(t["signed_at"]), resort["rescission_days"])
        if parse_iso(resort["current_utc"]) < threshold:
            raise err(errors.ERR_RESCISSION_WINDOW_OPEN, "Rescission window is still open.")
        # Priority 9: source contract must be ACTIVE.
        if source["status"] != "ACTIVE":
            raise err(errors.ERR_CONTRACT_NOT_ACTIVE, "Source contract is not ACTIVE.")
        # Priority 11: no open DelinquencyCase in {NOTICE, LIEN}.
        if open_case_for_contract(source) is not None:
            raise err(errors.ERR_CONTRACT_DELINQUENT, "Source contract has an open delinquency case.")

        # Complete.
        t["status"] = "COMPLETED"
        # Mint buyer contract (ACTIVE, same inventory_model/allotment).
        new_contract = {
            "resort_id": source["resort_id"],
            "owner_id": t["buyer_owner_id"],
            "ownership_type": source["ownership_type"],
            "inventory_model": source["inventory_model"],
            "annual_points_allotment": source["annual_points_allotment"],
            "fixed_unit_id": source.get("fixed_unit_id"),
            "rtu_expiry_use_year": source.get("rtu_expiry_use_year"),
            "signed_at": resort["current_utc"],
            "superseded_by_contract_id": None,
            "status": "ACTIVE",
        }
        stamp_create(new_contract)
        db.contracts[new_contract["id"]] = new_contract
        t["new_contract_id"] = new_contract["id"]
        touch(t)

        # Cascade source contract -> TRANSFERRED.
        source["status"] = "TRANSFERRED"
        source["superseded_by_contract_id"] = new_contract["id"]
        touch(source)

        # Resale-split the transfer_use_year ANNUAL invoice.
        annual_full = annual_full_fee(resort, _points_basis(source))
        seller_share = resale_seller_share(annual_full, t["transfer_day_of_year"])
        buyer_share = annual_full - seller_share
        seller_inv = _find_seller_annual_invoice(source["id"], t["transfer_use_year"])
        if seller_inv is not None:
            seller_inv["amount_cents"] = seller_share
            touch(seller_inv)
        # New ISSUED buyer invoice for the remainder.
        buyer_inv = {
            "contract_id": new_contract["id"],
            "owner_id": t["buyer_owner_id"],
            "source_type": "ANNUAL",
            "special_assessment_id": None,
            "use_year": t["transfer_use_year"],
            "amount_cents": buyer_share,
            "late_charge_cents": 0,
            "amount_paid_cents": 0,
            "due_date": seller_inv["due_date"] if seller_inv else resort["current_utc"],
            "status": "ISSUED",
        }
        stamp_create(buyer_inv)
        db.invoices[buyer_inv["id"]] = buyer_inv

        return success(serialize_transfer(t))

    @app.route("/resale-transfers/<transfer_id>/rescind", methods=["POST"])
    def rescind_transfer(transfer_id):
        user_id, role = get_user_context()
        require_role(role, ["Owner", "ComplianceOfficer"])
        t = get_or_404(db.resale_transfers, transfer_id)
        # Ownership: the resource resolves to the source contract.
        source = db.contracts[t["source_contract_id"]]
        check_owner_of_contract(role, user_id, source)
        if t["status"] != "PENDING_RESCISSION":
            raise err(errors.ERR_INVALID_STATE, "Transfer is not PENDING_RESCISSION.")
        resort = db.resorts[t["resort_id"]]
        threshold = add_days(parse_iso(t["signed_at"]), resort["rescission_days"])
        if parse_iso(resort["current_utc"]) > threshold:
            raise err(errors.ERR_RESCISSION_WINDOW_CLOSED, "Rescission window has closed.")
        t["status"] = "RESCINDED"
        touch(t)
        return success(serialize_transfer(t))


def _find_seller_annual_invoice(contract_id, use_year):
    candidates = [
        inv
        for inv in db.invoices.values()
        if inv["contract_id"] == contract_id
        and inv["use_year"] == use_year
        and inv["source_type"] == "ANNUAL"
        and inv["status"] != "WRITTEN_OFF"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda i: i["_seq"])
    return candidates[0]
