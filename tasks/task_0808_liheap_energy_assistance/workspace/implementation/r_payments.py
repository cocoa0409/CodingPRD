"""Payment endpoints and the remittance/return cascade (§3.7)."""
from flask import request

from store import db, stamp_new, touch, public, now_iso
from common import (
    endpoint, object_response, get_body, req_str, req_int, ApiError,
)
from calc import bill_credit_allocation
from helpers import get_path, get_ref, list_collection, forbid, vendor_of_payment


def register(app):
    @app.route("/liheap/payments", methods=["POST"])
    @endpoint(["Caseworker"])
    def create_payment(role, user_id):
        body = get_body()
        pledge_id = req_str(body, "pledge_id")
        amount_cents = req_int(body, "amount_cents", gt=0)
        get_ref(db.pledges, pledge_id)
        payment = {
            "pledge_id": pledge_id,
            "amount_cents": amount_cents,
            "status": "INITIATED",
            "remitted_at": None,
        }
        stamp_new(payment)
        db.payments[payment["id"]] = payment
        return object_response(public(payment), 201)

    @app.route("/liheap/payments/<id_>", methods=["GET"])
    @endpoint(["Caseworker", "VendorAgent", "ProgramAdmin"])
    def get_payment(role, user_id, id_):
        payment = get_path(db.payments, id_)
        if role == "VendorAgent" and vendor_of_payment(payment) != user_id:
            forbid()
        return object_response(public(payment), 200)

    @app.route("/liheap/payments", methods=["GET"])
    @endpoint(["Caseworker", "VendorAgent", "ProgramAdmin"])
    def list_payments(role, user_id):
        filters = {
            "pledge_id": request.args.get("pledge_id"),
            "status": request.args.get("status"),
        }
        return list_collection(db.payments, "payments", filters)

    @app.route("/liheap/payments/<id_>/remit", methods=["POST"])
    @endpoint(["VendorAgent"])
    def remit_payment(role, user_id, id_):
        payment = get_path(db.payments, id_)
        pledge = db.pledges.get(payment["pledge_id"])
        vendor_id = pledge["vendor_id"] if pledge else None
        if vendor_id != user_id:
            forbid()
        if payment["status"] != "INITIATED":
            raise ApiError("ERR_INVALID_STATE", "Payment is not INITIATED")
        if pledge is None or pledge["status"] != "PLEDGED":
            raise ApiError("ERR_INVALID_STATE", "Pledge is not PLEDGED")
        vendor = db.vendors.get(vendor_id)
        if vendor is None or vendor["status"] != "ENROLLED":
            raise ApiError("ERR_VENDOR_NOT_ENROLLED", "Vendor is not ENROLLED")

        # --- cascade ---
        payment["status"] = "REMITTED"
        payment["remitted_at"] = now_iso()
        touch(payment)
        # pledge PLEDGED -> PAID: reserved -> disbursed (derived), pool version bumps.
        pledge["status"] = "PAID"
        touch(pledge)
        pool = db.funding_pools.get(pledge["funding_pool_id"])
        if pool is not None:
            touch(pool)
        # create + apply the bill credit (arrearage-first waterfall)
        account = db.utility_accounts.get(pledge["utility_account_id"])
        credit_amount = payment["amount_cents"]
        applied_arr, applied_cur = bill_credit_allocation(
            credit_amount, account["arrearage_cents"], account["current_balance_cents"]
        )
        credit = {
            "payment_id": payment["id"],
            "utility_account_id": account["id"],
            "credit_amount_cents": credit_amount,
            "applied_to_arrearage_cents": applied_arr,
            "applied_to_current_cents": applied_cur,
            "status": "APPLIED",
        }
        stamp_new(credit)
        db.bill_credits[credit["id"]] = credit
        account["arrearage_cents"] -= applied_arr
        account["current_balance_cents"] -= applied_cur
        account["lifetime_credited_cents"] += (applied_arr + applied_cur)
        if account["arrearage_cents"] == 0 and account["is_disconnected"]:
            account["reconnection_eligible"] = True
        touch(account)
        return object_response(public(payment), 200)

    @app.route("/liheap/payments/<id_>/return", methods=["POST"])
    @endpoint(["VendorAgent"])
    def return_payment(role, user_id, id_):
        payment = get_path(db.payments, id_)
        pledge = db.pledges.get(payment["pledge_id"])
        vendor_id = pledge["vendor_id"] if pledge else None
        if vendor_id != user_id:
            forbid()
        if payment["status"] != "REMITTED":
            raise ApiError("ERR_PAYMENT_NOT_REMITTED", "Payment is not REMITTED")

        payment["status"] = "RETURNED"
        touch(payment)
        # reverse the associated bill credit + account ledger (compensating).
        credit = _credit_for_payment(payment["id"])
        if credit is not None:
            credit["status"] = "REVERSED"
            touch(credit)
            account = db.utility_accounts.get(credit["utility_account_id"])
            if account is not None:
                account["arrearage_cents"] += credit["applied_to_arrearage_cents"]
                account["current_balance_cents"] += credit["applied_to_current_cents"]
                account["lifetime_credited_cents"] -= (
                    credit["applied_to_arrearage_cents"] + credit["applied_to_current_cents"]
                )
                if account["arrearage_cents"] > 0:
                    account["reconnection_eligible"] = False
                touch(account)
        return object_response(public(payment), 200)


def _credit_for_payment(payment_id):
    for c in db.bill_credits.values():
        if c["payment_id"] == payment_id and c["status"] == "APPLIED":
            return c
    return None
