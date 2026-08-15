"""Customer endpoints."""

from flask import Blueprint, g

import db
from errors import forbidden
from middleware import authenticate, require_roles
from response import success_object
from services.common import new_id, get_body, require, get_customer

bp = Blueprint("customers", __name__)


@bp.post("/api/customers")
def create_customer():
    authenticate()
    require_roles("SalesRep")
    body = get_body()
    row = {"id": new_id()}
    for name in ("full_name", "email", "phone", "street", "city", "state_code", "zip"):
        row[name] = require(body, name, "str")
    now = db.now_iso()
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    db.customers[row["id"]] = row
    return success_object(row, 201)


@bp.get("/api/customers/<cid>")
def read_customer(cid):
    authenticate()
    require_roles("Customer", "SalesRep", "PermitCoordinator", "InstallCrew",
                  "FinanceManager", "OperationsAdmin")
    row = get_customer(cid)
    # Customer identity is entity-backed: a Customer caller reads only their own record
    if g.role == "Customer" and g.user_id != row["id"]:
        raise forbidden("Customer may only access their own resources")
    return success_object(row)
