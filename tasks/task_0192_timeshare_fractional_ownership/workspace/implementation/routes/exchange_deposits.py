"""ExchangeDeposit routes: get, list, redeem, recall."""
from flask import request

from db import db, touch
import errors
from errors import err
from middleware import get_user_context, require_role
from response import success
from routes.common import get_or_404, list_response, check_owner_of_contract
from services.util import serialize


def serialize_deposit(d):
    return serialize(d)


def register(app):
    @app.route("/exchange-deposits/<deposit_id>", methods=["GET"])
    def get_deposit(deposit_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        d = get_or_404(db.exchange_deposits, deposit_id)
        return success(serialize_deposit(d))

    @app.route("/exchange-deposits", methods=["GET"])
    def list_deposits():
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        items = list(db.exchange_deposits.values())
        for key in ("reservation_id", "contract_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [d for d in items if d.get(key) == val]
        return list_response(items, serialize_deposit)

    @app.route("/exchange-deposits/<deposit_id>/redeem", methods=["POST"])
    def redeem_deposit(deposit_id):
        user_id, role = get_user_context()
        require_role(role, ["Owner"])
        d = get_or_404(db.exchange_deposits, deposit_id)
        contract = db.contracts[d["contract_id"]]
        check_owner_of_contract(role, user_id, contract)
        if d["status"] != "DEPOSITED":
            raise err(errors.ERR_INVALID_STATE, "Deposit is not DEPOSITED.")
        d["status"] = "REDEEMED"
        touch(d)
        return success(serialize_deposit(d))

    @app.route("/exchange-deposits/<deposit_id>/recall", methods=["POST"])
    def recall_deposit(deposit_id):
        user_id, role = get_user_context()
        require_role(role, ["Owner"])
        d = get_or_404(db.exchange_deposits, deposit_id)
        contract = db.contracts[d["contract_id"]]
        check_owner_of_contract(role, user_id, contract)
        if d["status"] != "DEPOSITED":
            raise err(errors.ERR_INVALID_STATE, "Deposit is not DEPOSITED.")
        d["status"] = "RECALLED"
        touch(d)
        # Restore the reservation and unit.
        res = db.reservations.get(d["reservation_id"])
        if res is not None:
            res["status"] = "CONFIRMED"
            touch(res)
            unit = db.inventory_units.get(res["inventory_unit_id"])
            if unit is not None:
                unit["status"] = "RESERVED"
                touch(unit)
        return success(serialize_deposit(d))
