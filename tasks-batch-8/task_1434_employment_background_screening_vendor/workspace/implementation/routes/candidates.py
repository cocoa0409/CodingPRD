"""Candidate endpoints."""
from flask import Blueprint

import db
from db import bump
from errors import ApiError, ERR_NOT_FOUND, ERR_CANDIDATE_NOT_ACTIVE
from middleware import (
    auth, require_role, get_body, req_str, invalid, forbid, ALL_ROLES,
)
from response import success_object
from services import cancel_order_cascade, NON_TERMINAL_FULFILLMENT

bp = Blueprint("candidates", __name__)


@bp.route("/candidates", methods=["POST"])
def create_candidate():
    auth_uid, role = auth()
    require_role(role, {"HRAdmin"})
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    home = req_str(body, "home_jurisdiction_code")
    # uniqueness (priority 6): email unique across candidates
    for existing in db.candidates.values():
        if existing["email"] == email:
            invalid("Candidate email must be unique")
    candidate = db.new_entity({
        "full_name": full_name,
        "email": email,
        "home_jurisdiction_code": home,
        "status": "ACTIVE",
    })
    db.candidates[candidate["id"]] = candidate
    return success_object(candidate, 201)


@bp.route("/candidates/<candidate_id>", methods=["GET"])
def get_candidate(candidate_id):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    candidate = db.candidates.get(candidate_id)
    if candidate is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Candidate not found")
    return success_object(candidate, 200)


@bp.route("/candidates/<candidate_id>/withdraw", methods=["POST"])
def withdraw_candidate(candidate_id):
    uid, role = auth()
    require_role(role, {"Candidate"})
    candidate = db.candidates.get(candidate_id)
    if candidate is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Candidate not found")
    # entity-backed ownership: candidate acts only on self
    if uid != candidate["id"]:
        forbid("Candidate may only withdraw themself")
    if candidate["status"] != "ACTIVE":
        raise ApiError(ERR_CANDIDATE_NOT_ACTIVE, 409,
                       "Candidate must be ACTIVE to withdraw")
    candidate["status"] = "WITHDRAWN"
    bump(candidate)
    for order in list(db.orders.values()):
        if (order["candidate_id"] == candidate["id"]
                and order["fulfillment_status"] in NON_TERMINAL_FULFILLMENT):
            cancel_order_cascade(order)
    return success_object(candidate, 200)
