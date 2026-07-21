from flask import Blueprint
from db import db, touch, fmt_ts, now
from errors import err
from middleware import get_caller, require_role
from response import object_response
import lookups

invoices_bp = Blueprint("invoices", __name__)


@invoices_bp.post("/invoices/<invoice_id>/pay")
def pay_invoice(invoice_id):
    caller = get_caller()
    require_role(caller, {"Renter"})

    invoice = lookups.get_invoice(invoice_id)
    policy = db.policies[invoice["policy_id"]]
    if lookups.renter_id_for_policy(policy) != caller.user_id:
        raise err("ERR_UNAUTHORIZED", "Caller does not own this invoice's policy.")

    if invoice["status"] not in ("ISSUED", "OVERDUE"):
        raise err("ERR_INVALID_STATE", "Invoice is not payable in its current state.")

    policy_invoices = lookups.invoices_for_policy(policy["id"])
    sorted_invoices = sorted(policy_invoices, key=lambda i: (i["created_at"], i["id"]))
    is_first_invoice = sorted_invoices[0]["id"] == invoice["id"]

    non_paid = [i for i in policy_invoices if i["status"] != "PAID"]
    is_only_non_paid = len(non_paid) == 1 and non_paid[0]["id"] == invoice["id"]

    invoice["status"] = "PAID"
    invoice["paid_at"] = fmt_ts(now())
    touch(invoice)

    if policy["status"] == "AWAITING_FIRST_PAYMENT" and is_first_invoice:
        policy["status"] = "ACTIVE"
        touch(policy)
    elif policy["status"] == "LAPSED" and is_only_non_paid:
        policy["status"] = "ACTIVE"
        touch(policy)

    return object_response(invoice)
