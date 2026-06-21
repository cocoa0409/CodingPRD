"""SystemClock endpoints: set_current_utc (triggers arrears recompute) and read
(PRD §3.9)."""
from flask import Blueprint

from db import db, touch
from errors import err
from middleware import authenticate, require_roles
from response import success
from services import serializers as ser
from services.common import get_json_body, require_dt, require_fields
from services.ledger import reage_account

bp = Blueprint("clock", __name__)

ALL_ROLES = {"BillingOperator", "Customer", "AssistanceCaseworker", "FieldDispatcher"}


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    body = get_json_body()
    require_fields(body, ["current_utc"])
    # Validate shape (ISO 8601). require_dt raises ERR_INVALID_REQUEST on bad shape.
    require_dt(body, "current_utc")

    db.clock["current_utc"] = body["current_utc"]

    # System-wide arrears recompute; bump version for any account that changes.
    for account in db.accounts.values():
        if reage_account(account):
            touch(account)

    return success(ser.clock(db.clock), status=200)


@bp.route("/_clock", methods=["GET"])
def get_clock():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    return success(ser.clock(db.clock), status=200)
