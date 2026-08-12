from flask import Blueprint, request

import services as svc
from middleware import auth, get_body, require, lookup, parse_pagination, paginate
from errors import err_invalid_request, err_unauthorized
from response import ok_object, ok_list

bp = Blueprint("customers", __name__)


@bp.post("/api/customers")
def create_customer():
    auth("OperationsManager")
    data = get_body()
    full_name = require(data, "full_name", str)
    email = require(data, "email", str)
    phone = require(data, "phone", str)
    for c in svc.customers.values():
        if c["email"] == email:
            raise err_invalid_request("email must be unique across customers")
    rec = svc.new_record()
    rec.update(
        {
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "account_status": "ACTIVE",
            "credit_balance_cents": 0,
            "lifetime_visits_completed": 0,
            "satisfaction_rolling_avg": None,
        }
    )
    svc.customers[rec["id"]] = rec
    return ok_object(svc.ser_customer(rec), status=201)


@bp.get("/api/customers/<cid>")
def get_customer(cid):
    uid, role = auth("OperationsManager", "BillingAdmin", "Customer")
    rec = lookup(svc.customers, cid, "Customer")
    if role == "Customer" and rec["id"] != uid:
        raise err_unauthorized("Customers may only access their own record")
    return ok_object(svc.ser_customer(rec))


@bp.get("/api/customers")
def list_customers():
    auth("OperationsManager", "BillingAdmin")
    limit, offset = parse_pagination()
    records = list(svc.customers.values())
    email = request.args.get("email")
    if email is not None:
        records = [c for c in records if c["email"] == email]
    page, total = paginate(records, limit, offset)
    return ok_list([svc.ser_customer(c) for c in page], total, limit, offset)
