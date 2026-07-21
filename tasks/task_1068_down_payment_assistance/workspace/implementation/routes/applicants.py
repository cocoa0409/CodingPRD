from flask import Blueprint

import store
from errors import ApiError
import context as ctx
from serializers import public
import envelope as env

bp = Blueprint("applicants", __name__)


@bp.post("/applicants")
def create_applicant():
    # Public self-registration: no authentication headers required.
    data = ctx.body()
    full_name = ctx.req_str(data, "full_name")
    email = ctx.req_str(data, "email")
    household_size = ctx.req_int(data, "household_size", 1, 12)
    annual_income_cents = ctx.req_int(data, "annual_income_cents", 0)
    first_time_buyer = ctx.opt_bool(data, "first_time_buyer", True)

    for a in store.applicants.values():
        if a["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", "email must be unique across applicants.")

    rec = store.new_record("applicant")
    rec.update({
        "full_name": full_name,
        "email": email,
        "household_size": household_size,
        "annual_income_cents": annual_income_cents,
        "first_time_buyer": first_time_buyer,
    })
    store.applicants[rec["id"]] = rec
    return env.success(public(rec), 201)


@bp.get("/applicants/<aid>")
def get_applicant(aid):
    ctx.authenticate(["Applicant", "CaseManager", "ProgramAdmin"])
    rec = ctx.lookup("applicant", aid)
    return env.success(public(rec), 200)
