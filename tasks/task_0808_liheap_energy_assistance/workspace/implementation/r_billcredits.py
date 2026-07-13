"""Bill-credit read endpoints (§3.7). Credits are only created via the remit cascade."""
from flask import request

from store import db, public
from common import endpoint, object_response
from helpers import get_path, list_collection, forbid, vendor_of_bill_credit


def register(app):
    @app.route("/liheap/bill-credits/<id_>", methods=["GET"])
    @endpoint(["Caseworker", "VendorAgent", "ProgramAdmin"])
    def get_bill_credit(role, user_id, id_):
        credit = get_path(db.bill_credits, id_)
        if role == "VendorAgent" and vendor_of_bill_credit(credit) != user_id:
            forbid()
        return object_response(public(credit), 200)

    @app.route("/liheap/bill-credits", methods=["GET"])
    @endpoint(["Caseworker", "VendorAgent", "ProgramAdmin"])
    def list_bill_credits(role, user_id):
        filters = {
            "payment_id": request.args.get("payment_id"),
            "utility_account_id": request.args.get("utility_account_id"),
            "status": request.args.get("status"),
        }
        return list_collection(db.bill_credits, "bill_credits", filters)
