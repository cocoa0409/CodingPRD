"""PointsAccount routes: get, list, bank."""
from flask import request

from db import db, stamp_create, touch
import errors
from errors import err
from middleware import get_user_context, require_role
from response import success
from routes.common import get_or_404, get_json, list_response
from services.util import require_int
from services.computed import serialize_points_account, available_points


def register(app):
    @app.route("/points-accounts/<account_id>", methods=["GET"])
    def get_points_account(account_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        acct = get_or_404(db.points_accounts, account_id)
        return success(serialize_points_account(acct))

    @app.route("/points-accounts", methods=["GET"])
    def list_points_accounts():
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        items = list(db.points_accounts.values())
        contract_id = request.args.get("contract_id")
        use_year = request.args.get("use_year")
        if contract_id is not None:
            items = [a for a in items if a["contract_id"] == contract_id]
        if use_year is not None:
            try:
                uy = int(use_year)
            except (TypeError, ValueError):
                raise err(errors.ERR_INVALID_REQUEST, "use_year must be an integer.")
            items = [a for a in items if a["use_year"] == uy]
        return list_response(items, serialize_points_account)

    @app.route("/points-accounts/<account_id>/bank", methods=["POST"])
    def bank_points(account_id):
        _, role = get_user_context()
        require_role(role, ["Owner", "ResortManager"])
        acct = get_or_404(db.points_accounts, account_id)
        data = get_json()
        points = require_int(data, "points", positive=True)
        expected_version = require_int(data, "expected_points_account_version")

        # Priority 14: points sufficiency.
        if points > available_points(acct):
            raise err(errors.ERR_INSUFFICIENT_POINTS, "Bank amount exceeds available points.")
        # Priority 15: OCC stale version.
        if expected_version != acct["version"]:
            raise err(errors.ERR_STALE_VERSION, "PointsAccount version is stale.")

        acct["banked_out_points"] += points
        touch(acct)
        # Next-year account gets banked_in_points += points; created if absent.
        next_acct = _ensure_next_year_account(acct["contract_id"], acct["use_year"] + 1)
        next_acct["banked_in_points"] += points
        touch(next_acct)
        return success(serialize_points_account(acct))


def _ensure_next_year_account(contract_id, use_year):
    for a in db.points_accounts.values():
        if a["contract_id"] == contract_id and a["use_year"] == use_year:
            return a
    contract = db.contracts.get(contract_id)
    allotment = contract["annual_points_allotment"] if contract else 0
    acct = {
        "contract_id": contract_id,
        "use_year": use_year,
        "allotment_points": allotment,
        "banked_in_points": 0,
        "banked_out_points": 0,
        "borrowed_out_points": 0,
        "committed_points": 0,
        "status": "OPEN",
    }
    stamp_create(acct)
    db.points_accounts[acct["id"]] = acct
    return acct
