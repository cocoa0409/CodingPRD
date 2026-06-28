"""Guardian routes: register, fetch, wallet adjustments (PRD §3.2)."""
from flask import Blueprint

import errors
from errors import err
from db import db
from response import success
from serialize import out
from middleware import get_auth, require_role
from validators import get_body, require_str, require_int
from services import lookup

bp = Blueprint("guardians", __name__)


@bp.route("/guardians", methods=["POST"])
def create_guardian():
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Guardian"})
    body = get_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    # email unique, case-insensitive
    lowered = email.lower()
    for g in db.guardians.values():
        if g["email"].lower() == lowered:
            raise err(errors.ERR_INVALID_FIELD, "email must be unique.")
    rec = db.make({
        "full_name": full_name,
        "email": email,
        "wallet_credit_cents": 0,
    })
    db.guardians[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/guardians/<rid>", methods=["GET"])
def get_guardian(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Guardian"})
    rec = lookup.require_guardian(rid)
    return success(out(rec))


@bp.route("/guardians/<rid>/wallet/adjustments", methods=["POST"])
def adjust_wallet(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    guardian = lookup.require_guardian(rid)
    body = get_body()
    amount = require_int(body, "amount_cents")
    require_str(body, "reason")
    new_balance = guardian["wallet_credit_cents"] + amount
    if new_balance < 0:
        raise err(errors.ERR_WALLET_INSUFFICIENT, "Debit exceeds wallet balance.")
    guardian["wallet_credit_cents"] = new_balance
    db.touch(guardian)
    return success(out(guardian))
