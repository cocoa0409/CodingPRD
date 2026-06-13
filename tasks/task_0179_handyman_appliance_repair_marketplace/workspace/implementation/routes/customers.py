"""Customer registration + fetch (PRD §3.2, §4)."""
import re

from flask import Blueprint, g

from db import store
from errors import ApiError
from middleware import require_role, _read_headers, VALID_ROLES
from models import common, serialize, CUSTOMER_FIELDS
from response import object_response
from services.lookup import require_body, require_string, get_or_404

bp = Blueprint("customers", __name__)

_ZIP_RE = re.compile(r"^[0-9]{5}$")


@bp.post("/customers")
def create_customer():
    # PRD §2.1: self-registration, no auth required (Anonymous role).
    user_id, role = _read_headers()
    if role is not None and role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown role")

    body = require_body()
    email = require_string(body, "email")
    full_name = require_string(body, "full_name")
    zip_code = require_string(body, "zip_code")
    if not _ZIP_RE.match(zip_code):
        raise ApiError("ERR_INVALID_REQUEST", "zip_code must be exactly 5 digits")

    for c in store.customers.values():
        if c["email"] == email:
            raise ApiError("ERR_VALIDATION", "email must be unique across Customer")

    cust = {
        "email": email,
        "full_name": full_name,
        "zip_code": zip_code,
        "wallet_credit_cents": 0,
    }
    common(cust)
    store.customers[cust["id"]] = cust
    return object_response(serialize(cust, CUSTOMER_FIELDS), status=201)


@bp.get("/customers/<cid>")
@require_role({"PlatformAdmin", "Customer"})
def get_customer(cid):
    cust = get_or_404(store.customers, cid)
    # ownership: a Customer may fetch only their own record (PRD §2.1).
    if g.role == "Customer" and g.user_id != cid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Customers may only read their own record")
    return object_response(serialize(cust, CUSTOMER_FIELDS))
