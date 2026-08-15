from flask import Blueprint

import db
from errors import ApiError
from middleware import authenticate, require_role, locked
from response import ok
from serializers import ser_budget
from validators import body, req_field, as_int

bp = Blueprint("budgets", __name__)


@bp.post("/pole-program/budgets")
@locked
def create_budget():
    authenticate_role = authenticate()
    require_role(authenticate_role[1], "ProgramManager")
    d = body()
    fiscal_year = as_int(req_field(d, "fiscal_year"), "fiscal_year", 2000, 2100)
    total_cents = as_int(req_field(d, "total_cents"), "total_cents", 0)
    if any(b["fiscal_year"] == fiscal_year for b in db.budgets.values()):
        raise ApiError("ERR_DUPLICATE_FISCAL_YEAR", 409,
                       "A budget already exists for fiscal_year %s" % fiscal_year)
    rec = db.new_record()
    rec.update(fiscal_year=fiscal_year, total_cents=total_cents,
               committed_cents=0, spent_cents=0)
    db.budgets[rec["id"]] = rec
    return ok(ser_budget(rec), 201)


@bp.get("/pole-program/budgets/<bid>")
def get_budget(bid):
    authenticate()
    rec = db.budgets.get(bid)
    if rec is None:
        raise ApiError("ERR_BUDGET_NOT_FOUND", 404, "budget_id does not resolve")
    return ok(ser_budget(rec), 200)
