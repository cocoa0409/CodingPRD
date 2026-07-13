"""Utility-account endpoints (§3.5, §2.8)."""
from flask import request

from store import db, stamp_new, touch, public
from common import (
    endpoint, object_response, get_body, req_str, req_enum, opt_int, opt_bool,
)
from helpers import get_path, get_ref, list_collection, forbid

SERVICE_TYPES = {"HEATING", "COOLING", "ELECTRIC", "GAS"}


def register(app):
    @app.route("/liheap/utility-accounts", methods=["POST"])
    @endpoint(["Caseworker", "VendorAgent"])
    def create_utility_account(role, user_id):
        body = get_body()
        household_id = req_str(body, "household_id")
        vendor_id = req_str(body, "vendor_id")
        account_number = req_str(body, "account_number")
        service_type = req_enum(body, "service_type", SERVICE_TYPES)
        current_balance_cents = opt_int(body, "current_balance_cents", 0, minimum=0)
        arrearage_cents = opt_int(body, "arrearage_cents", 0, minimum=0)
        is_disconnected = opt_bool(body, "is_disconnected", False)
        if role == "VendorAgent" and vendor_id != user_id:
            forbid()
        get_ref(db.households, household_id)
        get_ref(db.vendors, vendor_id)
        account = {
            "household_id": household_id,
            "vendor_id": vendor_id,
            "account_number": account_number,
            "service_type": service_type,
            "current_balance_cents": current_balance_cents,
            "arrearage_cents": arrearage_cents,
            "lifetime_credited_cents": 0,
            "is_disconnected": is_disconnected,
            "reconnection_eligible": False,
            "original_obligation_cents": current_balance_cents + arrearage_cents,
        }
        stamp_new(account)
        db.utility_accounts[account["id"]] = account
        return object_response(public(account), 201)

    @app.route("/liheap/utility-accounts/<id_>", methods=["GET"])
    @endpoint(["Applicant", "Caseworker", "VendorAgent", "ProgramAdmin"])
    def get_utility_account(role, user_id, id_):
        account = get_path(db.utility_accounts, id_)
        if role == "Applicant" and account["household_id"] != user_id:
            forbid()
        if role == "VendorAgent" and account["vendor_id"] != user_id:
            forbid()
        return object_response(public(account), 200)

    @app.route("/liheap/utility-accounts", methods=["GET"])
    @endpoint(["Caseworker", "VendorAgent", "ProgramAdmin"])
    def list_utility_accounts(role, user_id):
        filters = {
            "household_id": request.args.get("household_id"),
            "vendor_id": request.args.get("vendor_id"),
        }
        return list_collection(db.utility_accounts, "utility_accounts", filters)

    @app.route("/liheap/utility-accounts/<id_>/report-status", methods=["POST"])
    @endpoint(["VendorAgent"])
    def report_utility_status(role, user_id, id_):
        account = get_path(db.utility_accounts, id_)
        if account["vendor_id"] != user_id:
            forbid()
        body = get_body(required=False)
        current_balance_cents = opt_int(body, "current_balance_cents",
                                        account["current_balance_cents"], minimum=0)
        arrearage_cents = opt_int(body, "arrearage_cents",
                                  account["arrearage_cents"], minimum=0)
        is_disconnected = opt_bool(body, "is_disconnected", account["is_disconnected"])
        account["current_balance_cents"] = current_balance_cents
        account["arrearage_cents"] = arrearage_cents
        account["is_disconnected"] = is_disconnected
        # Re-anchor the ledger (§2.8): original = current + arrearage + lifetime_credited.
        account["original_obligation_cents"] = (
            current_balance_cents + arrearage_cents + account["lifetime_credited_cents"]
        )
        touch(account)
        return object_response(public(account), 200)
