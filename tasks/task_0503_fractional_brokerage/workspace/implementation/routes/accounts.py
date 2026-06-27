"""Account endpoints (PRD §2.9, §3.10, §4)."""
from flask import Blueprint

import errors
from db import db
from middleware import get_identity, require_role, require_account_owner
from models import make_account, account_dict, touch
from response import object_response
from routes.common import get_json_body, get_account
from services.account import recompute_account

bp = Blueprint("accounts", __name__)


@bp.post("/accounts")
def open_account():
    _, role = get_identity()
    require_role(role, {"AccountHolder", "ComplianceOfficer"})
    body = get_json_body()

    holder_email = body.get("holder_email")
    if not isinstance(holder_email, str) or not holder_email:
        raise errors.err(errors.ERR_INVALID_REQUEST, "holder_email is required")

    account_type = body.get("account_type", "CASH")
    if account_type not in ("CASH", "MARGIN"):
        raise errors.err(errors.ERR_INVALID_REQUEST, "account_type must be CASH or MARGIN")

    acct = make_account(holder_email, account_type)
    recompute_account(acct)
    return object_response(account_dict(acct), 201)


@bp.get("/accounts/<account_id>")
def get_account_ep(account_id):
    user_id, role = get_identity()
    require_role(role, {"AccountHolder", "ComplianceOfficer", "ClearingSystem"})
    acct = get_account(account_id)
    require_account_owner(role, user_id, acct["id"])
    return object_response(account_dict(acct), 200)


@bp.patch("/accounts/<account_id>/compliance-hold")
def set_compliance_hold(account_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    acct = get_account(account_id)
    body = get_json_body()

    hold = body.get("compliance_hold")
    if not isinstance(hold, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "compliance_hold must be a boolean")

    acct["compliance_hold"] = hold
    # Each compliance-hold change recomputes posture and increments version (PRD §3.10)
    recompute_account(acct)
    touch(acct)
    return object_response(account_dict(acct), 200)
