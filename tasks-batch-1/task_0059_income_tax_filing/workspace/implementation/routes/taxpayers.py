from flask import Blueprint
import errors
from errors import err
from db import db, init_common
from middleware import get_auth, require_roles
from response import success
from util import get_body, require_str, require_int, require_enum
from serialize import public

bp = Blueprint("taxpayers", __name__)

FILING_STATUSES = {"SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE", "HEAD_OF_HOUSEHOLD"}


@bp.post("/taxpayers")
def create_taxpayer():
    _, role = get_auth()
    require_roles(role, {"Taxpayer", "Preparer"})
    body = get_body()

    email = require_str(body, "email", non_empty=True)
    full_name = require_str(body, "full_name")
    filing_status = require_enum(body, "filing_status", FILING_STATUSES)
    prior_agi = require_int(body, "prior_year_agi_cents", required=False, default=0)
    prior_tax = require_int(body, "prior_year_total_tax_cents", required=False, default=0)

    for tp in db.taxpayers.values():
        if tp["email"] == email:
            raise err(errors.ERR_INVALID_REQUEST, "email must be unique")

    tp = {
        "email": email,
        "full_name": full_name,
        "filing_status": filing_status,
        "prior_year_agi_cents": prior_agi,
        "prior_year_total_tax_cents": prior_tax,
    }
    init_common(tp)
    db.taxpayers[tp["id"]] = tp
    return success(public(tp), status=201)


@bp.get("/taxpayers/<taxpayer_id>")
def get_taxpayer(taxpayer_id):
    _, role = get_auth()
    require_roles(role, {"Taxpayer", "Preparer"})
    tp = db.taxpayers.get(taxpayer_id)
    if tp is None:
        raise err(errors.ERR_RETURN_NOT_FOUND, "Taxpayer not found")
    return success(public(tp))
