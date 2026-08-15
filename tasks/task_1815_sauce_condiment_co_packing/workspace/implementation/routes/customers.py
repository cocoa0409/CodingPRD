"""CustomerAccount endpoints: brand-owner onboarding and account read."""
from flask import Blueprint

from db import STORE
from errors import ERR_CUSTOMER_NOT_FOUND
from middleware import check_customer_scope, require_roles
from response import success
from services.core import find_or_404, new_record, serialize
from util import as_int, as_str, body_json, check_enum, opt, req

bp = Blueprint("customers", __name__)

DISPOSITION_OWNERS = ("CUSTOMER", "COPACKER")


@bp.post("/copack/customers")
def create_customer():
    require_roles("OpsAdmin")
    body = body_json()
    brand_name = as_str(req(body, "brand_name"), "brand_name")
    contact_email = as_str(req(body, "contact_email"), "contact_email")
    credit_limit_cents = as_int(req(body, "credit_limit_cents"), "credit_limit_cents")
    if credit_limit_cents < 0:
        from errors import err, ERR_INVALID_REQUEST
        raise err(ERR_INVALID_REQUEST, 400, "credit_limit_cents must be >= 0")
    default_disposition_owner = opt(body, "default_disposition_owner", "COPACKER")
    check_enum(default_disposition_owner, DISPOSITION_OWNERS, "default_disposition_owner")
    rec = new_record({
        "brand_name": brand_name,
        "contact_email": contact_email,
        "default_disposition_owner": default_disposition_owner,
        "credit_limit_cents": credit_limit_cents,
        "outstanding_billed_cents": 0,
    })
    STORE.customers[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/copack/customers/<cid>")
def get_customer(cid):
    require_roles("OpsAdmin", "QAReviewer", "Customer")
    rec = find_or_404(STORE.customers, cid, ERR_CUSTOMER_NOT_FOUND, "customer")
    check_customer_scope(rec["id"])
    return success(serialize(rec))
