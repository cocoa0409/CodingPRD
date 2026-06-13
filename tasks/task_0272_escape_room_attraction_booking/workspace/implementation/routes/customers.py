from flask import Blueprint

import errors
from errors import err
from db import db, new_id, now_iso
from middleware import require_roles, get_json
from response import created, ok
from services import validate as V
from services.entities import get_customer, ser_customer

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    require_roles({"PlatformAdmin", "Customer"})
    body = get_json()
    email = V.req_str(body, "email")
    full_name = V.req_str(body, "full_name")

    # Unique email, case-insensitive (PRD §3.3).
    lower = email.lower()
    for c in db.customers.values():
        if c["email"].lower() == lower:
            raise err(errors.ERR_DUPLICATE_RESOURCE, "Email already registered")

    ts = now_iso()
    cid = new_id()
    customer = {
        "id": cid,
        "email": email,
        "full_name": full_name,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.customers[cid] = customer
    return created(ser_customer(customer))


@bp.get("/customers/<customer_id>")
def read_customer(customer_id):
    require_roles({"PlatformAdmin", "VenueManager", "Customer"})
    customer = get_customer(customer_id)
    return ok(ser_customer(customer))
