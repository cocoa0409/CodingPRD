"""Customer endpoints."""
from flask import Blueprint

import db
import errors
import store
import serializers as S
import middleware as M
from response import ok, created
import calculations as C

bp = Blueprint("customers", __name__)


@bp.post("/rental/customers")
def create_customer():
    body = M.get_json_body()
    full_name = M.require_str(body, "full_name")
    email = M.require_str(body, "email")
    skill_level = M.optional_enum(body, "skill_level", {"BEGINNER", "INTERMEDIATE", "EXPERT"}, "BEGINNER")
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    rec = store.create_customer(full_name, email, skill_level)
    return created(S.customer(rec))


@bp.get("/rental/customers/<id>")
def get_customer(id):
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    rec = db.customers.get(id)
    if not rec:
        raise errors.not_found("customer not found")
    # standing is a derived field; recompute on read so it always reflects
    # the current strike tally and open-loss balance.
    C.recompute_customer_standing(rec)
    return ok(S.customer(rec))
