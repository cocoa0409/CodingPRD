from flask import Blueprint

import db
import response
from errors import err
from middleware import authenticate, get_role, get_user_id, require_roles
from routes.lookup import get_path
from services import serialize
from util import base_record, get_json_body, require_bool, require_enum, require_int, require_str

bp = Blueprint("customers", __name__)


@bp.post("/customers")
@require_roles("SalesManager")
def create_customer():
    body = get_json_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    monthly_income_cents = require_int(body, "monthly_income_cents", minimum=0)
    credit_tier = require_enum(body, "credit_tier", ("TIER_A", "TIER_B", "TIER_C", "TIER_D"))
    drivers_license_valid = require_bool(body, "drivers_license_valid", required=False, default=False)

    rec = base_record()
    rec.update({
        "full_name": full_name,
        "email": email,
        "monthly_income_cents": monthly_income_cents,
        "credit_tier": credit_tier,
        "drivers_license_valid": drivers_license_valid,
    })
    db.customers[rec["id"]] = rec
    return response.success(serialize.customer(rec), status=201)


@bp.get("/customers/<cid>")
def get_customer(cid):
    role = authenticate()
    if role not in ("SalesManager", "FinanceManager", "Customer"):
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
    # Customer may only read their own record (PRD §2.1).
    if role == "Customer" and get_user_id() != cid:
        raise err("ERR_FORBIDDEN", "Customer may only read their own record")
    rec = get_path(db.customers, cid)
    return response.success(serialize.customer(rec))
