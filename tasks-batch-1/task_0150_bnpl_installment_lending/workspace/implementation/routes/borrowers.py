"""Borrower endpoints (PRD §3.1)."""
from flask import Blueprint

import db
from errors import err
from middleware import authenticate, require_role, require_borrower_owns
from response import success
from services import engine
from services import calculations as calc
from services.engine import stamp_new
from routes.common import get_json_body, require_str, require_int, require_borrower

bp = Blueprint("borrowers", __name__)


@bp.route("/borrowers", methods=["POST"])
def create_borrower():
    _uid, role = authenticate()
    require_role(role, {"Servicer"})
    body = get_json_body()

    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    annual_income_cents = require_int(body, "annual_income_cents", minimum=0)
    soft_credit_score = require_int(body, "soft_credit_score", minimum=300, maximum=850)

    # Uniqueness on email (priority 6, ERR_DUPLICATE) — checked after schema validity.
    for existing in db.borrowers.values():
        if existing["email"] == email:
            raise err("ERR_DUPLICATE", "A borrower with this email already exists.")

    eligible = calc.provisional_eligible_limit(soft_credit_score, annual_income_cents)
    b = {
        "full_name": full_name,
        "email": email,
        "annual_income_cents": annual_income_cents,
        "soft_credit_score": soft_credit_score,
        "eligible_credit_limit_cents": eligible,
    }
    stamp_new(b)
    db.borrowers[b["id"]] = b
    return success(engine.serialize_borrower(b), status=201)


@bp.route("/borrowers/<borrower_id>", methods=["GET"])
def get_borrower(borrower_id):
    uid, role = authenticate()
    require_role(role, {"Servicer", "Borrower"})
    b = require_borrower(borrower_id)
    require_borrower_owns(role, uid, b["id"])
    return success(engine.serialize_borrower(b), status=200)
