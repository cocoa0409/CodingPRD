"""Customer registration and read (PRD §3.2)."""

from flask import Blueprint

from db import db
from core import get_body, stamp_new, check_str, check_bool
from errors import err
from middleware import get_identity, require_role
from response import success
from lookups import get_customer
import serialize

bp = Blueprint("customers", __name__)


@bp.post("/v1/customers")
def create_customer():
    uid, role = get_identity()
    require_role(role, {"ProgramAdmin", "Customer"})
    body = get_body()
    email = check_str(body, "email")
    full_name = check_str(body, "full_name")
    residence_state_code = check_str(body, "residence_state_code")
    is_corporate = check_bool(body, "is_corporate", default=False)

    c = {
        "email": email,
        "full_name": full_name,
        "residence_state_code": residence_state_code,
        "is_corporate": is_corporate,
    }
    stamp_new(c)
    db.customers[c["id"]] = c
    return success(serialize.customer(c), status=201)


@bp.get("/v1/customers/<customer_id>")
def read_customer(customer_id):
    uid, role = get_identity()
    require_role(role, {"ProgramAdmin", "Customer", "FraudAnalyst", "B2BBuyer"})
    c = get_customer(customer_id)
    # Ownership: a Customer/B2BBuyer reads only their own customer record.
    if role in ("Customer", "B2BBuyer") and c["id"] != uid:
        raise err("ERR_FORBIDDEN", "Not the owner of this resource.")
    return success(serialize.customer(c))
