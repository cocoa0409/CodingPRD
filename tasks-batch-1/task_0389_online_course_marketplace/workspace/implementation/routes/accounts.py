"""Instructor and Learner registration + reads (PRD §3.1)."""
from flask import Blueprint, request

import response
from db import db, new_id
from errors import err
from middleware import authenticate, require_roles
from services.common import (stamp_create, require_field, as_str, as_number)
from services.ledger import recompute_balances
from services.serialize import view

bp = Blueprint("accounts", __name__)


def _body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


# --------------------------------------------------------------------------
# Instructors
# --------------------------------------------------------------------------

@bp.route("/instructors", methods=["POST"])
def create_instructor():
    # Anonymous-allowed (unauthenticated) registration endpoint.
    body = _body()
    display_name = as_str(require_field(body, "display_name"), "display_name")
    email = as_str(require_field(body, "email"), "email")

    revenue_share = body.get("revenue_share_pct", 0.50)
    revenue_share = as_number(revenue_share, "revenue_share_pct")
    if not (0.0 <= revenue_share <= 1.0):
        raise err("ERR_INVALID_REQUEST", "revenue_share_pct must be between 0.00 and 1.00.")

    # email unique across instructors
    for inst in db.instructors.values():
        if inst["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email must be unique across instructors.")

    rec = {
        "id": new_id(),
        "display_name": display_name,
        "email": email,
        "revenue_share_pct": revenue_share,
        "payout_balance_cents": 0,
        "pending_balance_cents": 0,
        "lifetime_earned_cents": 0,
    }
    stamp_create(rec)
    db.instructors[rec["id"]] = rec
    return response.success(view(rec), status=201)


@bp.route("/instructors/<instructor_id>", methods=["GET"])
def get_instructor(instructor_id):
    principal = authenticate()
    require_roles(principal, "Instructor", "PlatformAdmin")
    inst = db.instructors.get(instructor_id)
    if inst is None:
        raise err("ERR_NOT_FOUND")
    # ownership: an Instructor may read only its own record
    if principal.role == "Instructor" and principal.user_id != instructor_id:
        raise err("ERR_FORBIDDEN")
    # Reading an instructor recomputes and returns current balances.
    recompute_balances(instructor_id)
    return response.success(view(inst), status=200)


# --------------------------------------------------------------------------
# Learners
# --------------------------------------------------------------------------

@bp.route("/learners", methods=["POST"])
def create_learner():
    body = _body()
    full_name = as_str(require_field(body, "full_name"), "full_name")
    email = as_str(require_field(body, "email"), "email")

    for lrn in db.learners.values():
        if lrn["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email must be unique across learners.")

    rec = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "wallet_credit_cents": 0,
    }
    stamp_create(rec)
    db.learners[rec["id"]] = rec
    return response.success(view(rec), status=201)


@bp.route("/learners/<learner_id>", methods=["GET"])
def get_learner(learner_id):
    principal = authenticate()
    require_roles(principal, "Learner", "PlatformAdmin")
    lrn = db.learners.get(learner_id)
    if lrn is None:
        raise err("ERR_NOT_FOUND")
    if principal.role == "Learner" and principal.user_id != learner_id:
        raise err("ERR_FORBIDDEN")
    return response.success(view(lrn), status=200)
