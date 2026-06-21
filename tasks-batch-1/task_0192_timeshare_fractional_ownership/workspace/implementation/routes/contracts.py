"""Contract routes: create, get, list, activate, rescind."""
from flask import request

from db import db, stamp_create, touch
import errors
from errors import err
from middleware import get_user_context, require_role
from response import success
from routes.common import get_or_404, get_json, list_response, check_owner_of_contract
from services.util import (
    serialize,
    require_str,
    require_enum,
    require_int,
    parse_iso,
    add_days,
)

OWNERSHIP_TYPES = {"DEEDED", "RIGHT_TO_USE"}
INVENTORY_MODELS = {"POINTS", "FIXED_WEEK"}


def serialize_contract(c):
    return serialize(c)


def register(app):
    @app.route("/contracts", methods=["POST"])
    def create_contract():
        _, role = get_user_context()
        require_role(role, ["ResortManager", "ResaleAgent"])
        data = get_json()
        resort_id = require_str(data, "resort_id")
        owner_id = require_str(data, "owner_id")
        ownership_type = require_enum(data, "ownership_type", OWNERSHIP_TYPES)
        inventory_model = require_enum(data, "inventory_model", INVENTORY_MODELS)

        annual_points_allotment = 0
        if data.get("annual_points_allotment") is not None:
            annual_points_allotment = require_int(data, "annual_points_allotment", minimum=0)

        fixed_unit_id = data.get("fixed_unit_id")
        if fixed_unit_id is not None and not isinstance(fixed_unit_id, str):
            raise err(errors.ERR_INVALID_REQUEST, "fixed_unit_id must be a string.")

        rtu_expiry = data.get("rtu_expiry_use_year")
        if rtu_expiry is not None:
            rtu_expiry = require_int(data, "rtu_expiry_use_year")

        # Existence + cross-resort referential integrity (priority 4 then 6).
        resort = _resolve_same_resort(db.resorts, resort_id, resort_id)
        _resolve_same_resort(db.owners, owner_id, resort_id)
        if fixed_unit_id is not None:
            _resolve_same_resort(db.inventory_units, fixed_unit_id, resort_id)

        contract = {
            "resort_id": resort_id,
            "owner_id": owner_id,
            "ownership_type": ownership_type,
            "inventory_model": inventory_model,
            "annual_points_allotment": annual_points_allotment,
            "fixed_unit_id": fixed_unit_id,
            "rtu_expiry_use_year": rtu_expiry,
            "signed_at": resort["current_utc"],
            "superseded_by_contract_id": None,
            "status": "PENDING_RESCISSION",
        }
        stamp_create(contract)
        db.contracts[contract["id"]] = contract
        return success(serialize_contract(contract), status=201)

    @app.route("/contracts/<contract_id>", methods=["GET"])
    def get_contract(contract_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        contract = get_or_404(db.contracts, contract_id)
        return success(serialize_contract(contract))

    @app.route("/contracts", methods=["GET"])
    def list_contracts():
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        items = list(db.contracts.values())
        for key in ("resort_id", "owner_id", "status", "fixed_unit_id", "superseded_by_contract_id"):
            val = request.args.get(key)
            if val is not None:
                items = [c for c in items if c.get(key) == val]
        return list_response(items, serialize_contract)

    @app.route("/contracts/<contract_id>/activate", methods=["POST"])
    def activate_contract(contract_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager"])
        contract = get_or_404(db.contracts, contract_id)
        if contract["status"] != "PENDING_RESCISSION":
            raise err(errors.ERR_INVALID_STATE, "Contract is not PENDING_RESCISSION.")
        resort = db.resorts[contract["resort_id"]]
        # Rescission window must have fully elapsed: current_utc >= signed_at + rescission_days.
        threshold = add_days(parse_iso(contract["signed_at"]), resort["rescission_days"])
        if parse_iso(resort["current_utc"]) < threshold:
            raise err(errors.ERR_RESCISSION_WINDOW_OPEN, "Rescission window is still open.")

        contract["status"] = "ACTIVE"
        touch(contract)
        if contract["inventory_model"] == "POINTS":
            _open_points_account_if_absent(contract, resort["current_use_year"])
        elif contract["inventory_model"] == "FIXED_WEEK" and contract.get("fixed_unit_id"):
            unit = db.inventory_units.get(contract["fixed_unit_id"])
            if unit is not None:
                unit["status"] = "RESERVED"
                touch(unit)
        return success(serialize_contract(contract))

    @app.route("/contracts/<contract_id>/rescind", methods=["POST"])
    def rescind_contract(contract_id):
        user_id, role = get_user_context()
        require_role(role, ["Owner", "ComplianceOfficer"])
        contract = get_or_404(db.contracts, contract_id)
        check_owner_of_contract(role, user_id, contract)
        if contract["status"] != "PENDING_RESCISSION":
            raise err(errors.ERR_INVALID_STATE, "Contract is not PENDING_RESCISSION.")
        resort = db.resorts[contract["resort_id"]]
        # Still inside the cooling-off window: current_utc <= signed_at + rescission_days.
        threshold = add_days(parse_iso(contract["signed_at"]), resort["rescission_days"])
        if parse_iso(resort["current_utc"]) > threshold:
            raise err(errors.ERR_RESCISSION_WINDOW_CLOSED, "Rescission window has closed.")

        contract["status"] = "RESCINDED"
        touch(contract)
        # Void all DRAFT/ISSUED invoices for this contract.
        for inv in db.invoices.values():
            if inv["contract_id"] == contract_id and inv["status"] in ("DRAFT", "ISSUED"):
                inv["status"] = "WRITTEN_OFF"
                touch(inv)
        return success(serialize_contract(contract))


def _resolve_same_resort(collection, resource_id, resort_id):
    """Resolve a body FK: 404 if missing, 409 cross-resort if wrong resort.

    For the resort collection itself, resort_id is the entity's own id."""
    obj = collection.get(resource_id)
    if obj is None:
        raise err(errors.ERR_NOT_FOUND, "Referenced resource not found: %s" % resource_id)
    # The resort row has no resort_id field; compare its own id.
    obj_resort = obj.get("resort_id", obj["id"])
    if obj_resort != resort_id:
        raise err(errors.ERR_CROSS_RESORT_REFERENCE, "Referenced resource is in a different resort.")
    return obj


def _open_points_account_if_absent(contract, use_year):
    for a in db.points_accounts.values():
        if a["contract_id"] == contract["id"] and a["use_year"] == use_year:
            return a
    acct = {
        "contract_id": contract["id"],
        "use_year": use_year,
        "allotment_points": contract["annual_points_allotment"],
        "banked_in_points": 0,
        "banked_out_points": 0,
        "borrowed_out_points": 0,
        "committed_points": 0,
        "status": "OPEN",
    }
    stamp_create(acct)
    db.points_accounts[acct["id"]] = acct
    return acct
