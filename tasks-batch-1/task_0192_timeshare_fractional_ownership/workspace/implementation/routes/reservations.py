"""Reservation routes: create (pricing/borrow), get, list, confirm, cancel, complete, deposit-exchange."""
from flask import request

from db import db, stamp_create, touch
import errors
from errors import err
from middleware import get_user_context, require_role
from response import success
from routes.common import get_or_404, get_json, list_response, check_owner_of_contract
from services.util import serialize, require_str, require_int, require_enum
from services.calc import (
    reservation_base_cost,
    lead_time_discounted,
    borrow_surcharge,
    exchange_credits,
)
from services.computed import available_points

EXCHANGE_NETWORKS = {"RCI", "II"}


def serialize_reservation(r):
    return serialize(r)


def _find_account(contract_id, use_year):
    for a in db.points_accounts.values():
        if a["contract_id"] == contract_id and a["use_year"] == use_year:
            return a
    return None


def _ensure_account(contract_id, use_year):
    acct = _find_account(contract_id, use_year)
    if acct is not None:
        return acct
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


def register(app):
    @app.route("/reservations", methods=["POST"])
    def create_reservation():
        user_id, role = get_user_context()
        require_role(role, ["Owner"])
        data = get_json()
        # Body well-formedness (priority 5).
        contract_id = require_str(data, "contract_id")
        inventory_unit_id = require_str(data, "inventory_unit_id")
        use_year = require_int(data, "use_year")
        expected_version = require_int(data, "expected_points_account_version")

        # Existence of body FKs (contract first so ownership can be evaluated).
        contract = db.contracts.get(contract_id)
        if contract is None:
            raise err(errors.ERR_NOT_FOUND, "Contract not found.")
        # Ownership (priority 3).
        check_owner_of_contract(role, user_id, contract)
        unit = db.inventory_units.get(inventory_unit_id)
        if unit is None:
            raise err(errors.ERR_NOT_FOUND, "Inventory unit not found.")
        # Cross-resort referential integrity (priority 6).
        if unit["resort_id"] != contract["resort_id"]:
            raise err(errors.ERR_CROSS_RESORT_REFERENCE, "Unit belongs to a different resort.")

        resort = db.resorts[contract["resort_id"]]

        # Source account for use_year.
        source = _find_account(contract_id, use_year)
        if source is None:
            # No account to draw on / no version to match.
            raise err(errors.ERR_STALE_VERSION, "Source points account version is stale.")

        # --- Pricing ---
        base = reservation_base_cost(resort, unit)
        discounted = lead_time_discounted(base, resort, use_year)
        avail = available_points(source)

        borrowed_points = 0
        points_cost = discounted
        borrow_source = None
        if discounted > avail:
            shortfall = discounted - avail
            borrowed_points = shortfall
            surcharge = borrow_surcharge(shortfall, resort)
            points_cost = discounted + surcharge
            borrow_source = _ensure_account(contract_id, use_year + 1)
            # Priority 14: borrow ceiling.
            if borrowed_points > available_points(borrow_source):
                raise err(
                    errors.ERR_INSUFFICIENT_POINTS,
                    "Borrowed points exceed the next-year account's available points.",
                )

        # Priority 15: OCC on the source account.
        if expected_version != source["version"]:
            raise err(errors.ERR_STALE_VERSION, "PointsAccount version is stale.")

        reservation = {
            "contract_id": contract_id,
            "inventory_unit_id": inventory_unit_id,
            "use_year": use_year,
            "points_cost": points_cost,
            "borrowed_points": borrowed_points,
            "source_use_year_account_id": source["id"],
            "borrow_source_account_id": borrow_source["id"] if borrow_source else None,
            "status": "HELD",
        }
        stamp_create(reservation)
        db.reservations[reservation["id"]] = reservation
        # Creating the reservation bumps the source use-year account version.
        touch(source)
        return success(serialize_reservation(reservation), status=201)

    @app.route("/reservations/<reservation_id>", methods=["GET"])
    def get_reservation(reservation_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        res = get_or_404(db.reservations, reservation_id)
        return success(serialize_reservation(res))

    @app.route("/reservations", methods=["GET"])
    def list_reservations():
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        items = list(db.reservations.values())
        for key in (
            "contract_id",
            "inventory_unit_id",
            "source_use_year_account_id",
            "borrow_source_account_id",
            "status",
        ):
            val = request.args.get(key)
            if val is not None:
                items = [r for r in items if r.get(key) == val]
        use_year = request.args.get("use_year")
        if use_year is not None:
            try:
                uy = int(use_year)
            except (TypeError, ValueError):
                raise err(errors.ERR_INVALID_REQUEST, "use_year must be an integer.")
            items = [r for r in items if r["use_year"] == uy]
        return list_response(items, serialize_reservation)

    @app.route("/reservations/<reservation_id>/confirm", methods=["POST"])
    def confirm_reservation(reservation_id):
        user_id, role = get_user_context()
        require_role(role, ["Owner"])
        res = get_or_404(db.reservations, reservation_id)
        contract = db.contracts[res["contract_id"]]
        check_owner_of_contract(role, user_id, contract)
        if res["status"] != "HELD":
            raise err(errors.ERR_INVALID_STATE, "Reservation is not HELD.")
        # Priority 9: owning contract must be ACTIVE.
        if contract["status"] != "ACTIVE":
            raise err(errors.ERR_CONTRACT_NOT_ACTIVE, "Owning contract is not ACTIVE.")
        # Priority 10: unit must be AVAILABLE.
        unit = db.inventory_units[res["inventory_unit_id"]]
        if unit["status"] != "AVAILABLE":
            raise err(errors.ERR_UNIT_NOT_AVAILABLE, "Inventory unit is not AVAILABLE.")

        res["status"] = "CONFIRMED"
        touch(res)
        unit["status"] = "RESERVED"
        touch(unit)
        non_borrowed = res["points_cost"] - res["borrowed_points"]
        source = db.points_accounts[res["source_use_year_account_id"]]
        source["committed_points"] += non_borrowed
        touch(source)
        if res["borrowed_points"] > 0 and res.get("borrow_source_account_id"):
            borrow = db.points_accounts[res["borrow_source_account_id"]]
            borrow["borrowed_out_points"] += res["borrowed_points"]
            touch(borrow)
        return success(serialize_reservation(res))

    @app.route("/reservations/<reservation_id>/cancel", methods=["POST"])
    def cancel_reservation(reservation_id):
        user_id, role = get_user_context()
        require_role(role, ["Owner", "ResortManager"])
        res = get_or_404(db.reservations, reservation_id)
        contract = db.contracts[res["contract_id"]]
        check_owner_of_contract(role, user_id, contract)
        if res["status"] not in ("HELD", "CONFIRMED"):
            raise err(errors.ERR_INVALID_STATE, "Reservation cannot be cancelled from its state.")

        was_confirmed = res["status"] == "CONFIRMED"
        res["status"] = "CANCELLED"
        touch(res)
        if was_confirmed:
            unit = db.inventory_units[res["inventory_unit_id"]]
            unit["status"] = "AVAILABLE"
            touch(unit)
            non_borrowed = res["points_cost"] - res["borrowed_points"]
            source = db.points_accounts[res["source_use_year_account_id"]]
            source["committed_points"] -= non_borrowed
            touch(source)
            if res["borrowed_points"] > 0 and res.get("borrow_source_account_id"):
                borrow = db.points_accounts[res["borrow_source_account_id"]]
                borrow["borrowed_out_points"] -= res["borrowed_points"]
                touch(borrow)
        return success(serialize_reservation(res))

    @app.route("/reservations/<reservation_id>/complete", methods=["POST"])
    def complete_reservation(reservation_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager"])
        res = get_or_404(db.reservations, reservation_id)
        if res["status"] != "CONFIRMED":
            raise err(errors.ERR_INVALID_STATE, "Reservation is not CONFIRMED.")
        res["status"] = "COMPLETED"
        touch(res)
        unit = db.inventory_units[res["inventory_unit_id"]]
        unit["status"] = "AVAILABLE"
        touch(unit)
        non_borrowed = res["points_cost"] - res["borrowed_points"]
        source = db.points_accounts[res["source_use_year_account_id"]]
        source["committed_points"] -= non_borrowed
        touch(source)
        return success(serialize_reservation(res))

    @app.route("/reservations/<reservation_id>/deposit-exchange", methods=["POST"])
    def deposit_exchange(reservation_id):
        user_id, role = get_user_context()
        require_role(role, ["Owner"])
        res = get_or_404(db.reservations, reservation_id)
        contract = db.contracts[res["contract_id"]]
        check_owner_of_contract(role, user_id, contract)
        data = get_json()
        network = require_enum(data, "exchange_network", EXCHANGE_NETWORKS)
        if res["status"] != "CONFIRMED":
            raise err(errors.ERR_INVALID_STATE, "Reservation is not CONFIRMED.")
        # Priority 9: contract must be ACTIVE.
        if contract["status"] != "ACTIVE":
            raise err(errors.ERR_CONTRACT_NOT_ACTIVE, "Owning contract is not ACTIVE.")
        # No existing deposit in {DEPOSITED, REDEEMED}.
        for d in db.exchange_deposits.values():
            if d["reservation_id"] == reservation_id and d["status"] in ("DEPOSITED", "REDEEMED"):
                raise err(errors.ERR_ALREADY_DEPOSITED, "Reservation already deposited.")

        res["status"] = "DEPOSITED_TO_EXCHANGE"
        touch(res)
        unit = db.inventory_units[res["inventory_unit_id"]]
        unit["status"] = "DEPOSITED_TO_EXCHANGE"
        touch(unit)
        deposit = {
            "reservation_id": reservation_id,
            "contract_id": contract["id"],
            "exchange_network": network,
            "exchange_credits": exchange_credits(res["points_cost"], network),
            "status": "DEPOSITED",
        }
        stamp_create(deposit)
        db.exchange_deposits[deposit["id"]] = deposit
        from routes.exchange_deposits import serialize_deposit

        return success(serialize_deposit(deposit), status=201)
