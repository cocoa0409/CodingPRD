"""Tax-bill endpoints: fetch and pay (PRD §3.8)."""
from flask import Blueprint

import db
from errors import err
from middleware import require_roles
from response import object_response
from services.common import lookup
from services.serialize import serialize

bp = Blueprint("tax_bills", __name__)


@bp.get("/tax-bills/<bill_id>")
def get_bill(bill_id):
    require_roles(["Assessor", "Reviewer", "Taxpayer"])
    return object_response(serialize(lookup(db.tax_bills, bill_id)), 200)


@bp.post("/tax-bills/<bill_id>/pay")
def pay_bill(bill_id):
    require_roles(["Assessor", "Taxpayer"])
    with db.LOCK:
        bill = lookup(db.tax_bills, bill_id)
        if bill["status"] != "ISSUED":
            raise err("ERR_INVALID_STATE", "Bill is not ISSUED")
        bill["status"] = "PAID"
        db.touch(bill)
    return object_response(serialize(bill), 200)
