"""Capital accounts; read-only, every field is a cascade product (PRD 3.4)."""

from flask import Blueprint

import db
import errors
import response
import validation as v
from middleware import (ALL_ROLES, OPERATOR_ROLES, endpoint, lookup,
                        require_owner)

bp = Blueprint("investor_accounts", __name__)


@bp.get("/investor-accounts/<account_id>")
@endpoint(ALL_ROLES)
def read_investor_account(account_id):
    account = lookup("investor_accounts", account_id,
                     errors.ERR_INVESTOR_ACCOUNT_NOT_FOUND)
    require_owner(account["investor_id"])
    return response.obj(account)


@bp.get("/investor-accounts")
@endpoint(OPERATOR_ROLES)
def list_investor_accounts():
    production_id = v.q_str("production_id")
    investor_id = v.q_str("investor_id")
    limit, offset = v.pagination()
    rows = [r for r in db.all_rows("investor_accounts")
            if (production_id is None or r["production_id"] == production_id)
            and (investor_id is None or r["investor_id"] == investor_id)]
    return response.listing(rows, limit, offset)
