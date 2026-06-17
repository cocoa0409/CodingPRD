"""Customer and SalesRep registration + fetch endpoints."""
from flask import Blueprint

from db import db, stamp_light_create
from errors import err
from middleware import anonymous_or_admin, require_roles
from response import created, ok
from services import serialize
from services.helpers import body, require_fields

bp = Blueprint("actors", __name__)


@bp.post("/flooring/customers")
@anonymous_or_admin
def create_customer():
    data = body()
    require_fields(data, ["full_name", "address", "email"])
    full_name = data["full_name"]
    address = data["address"]
    email = data["email"]
    if not isinstance(full_name, str) or not isinstance(address, str) or not isinstance(email, str):
        raise err("ERR_INVALID_REQUEST", "full_name, address, email must be strings.")
    with db.lock:
        # email unique among customers, case-insensitive.
        lowered = email.lower()
        for c in db.customers.values():
            if c["email"].lower() == lowered:
                raise err("ERR_DUPLICATE_KEY", "A customer with this email already exists.")
        record = stamp_light_create(
            {"full_name": full_name, "address": address, "email": email}
        )
        db.customers[record["id"]] = record
    return created(serialize.customer_view(record))


@bp.get("/flooring/customers/<cid>")
@require_roles("Admin", "SalesRep", "Customer")
def get_customer(cid):
    with db.lock:
        c = db.customers.get(cid)
        if c is None:
            raise err("ERR_NOT_FOUND", "Customer not found.")
        return ok(serialize.customer_view(c))


@bp.post("/flooring/sales-reps")
@anonymous_or_admin
def create_sales_rep():
    data = body()
    require_fields(data, ["name"])
    name = data["name"]
    if not isinstance(name, str):
        raise err("ERR_INVALID_REQUEST", "name must be a string.")
    with db.lock:
        record = stamp_light_create({"name": name})
        db.sales_reps[record["id"]] = record
    return created(serialize.sales_rep_view(record))


@bp.get("/flooring/sales-reps/<rid>")
@require_roles("Admin", "SalesRep")
def get_sales_rep(rid):
    with db.lock:
        r = db.sales_reps.get(rid)
        if r is None:
            raise err("ERR_NOT_FOUND", "Sales rep not found.")
        return ok(serialize.sales_rep_view(r))
