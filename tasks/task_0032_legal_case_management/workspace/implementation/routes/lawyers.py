"""Lawyer endpoints.

POST /lawyers           — register a Lawyer (PartnerLawyer only)
GET  /lawyers/{id}      — read a Lawyer (any authenticated role)
"""

from flask import Blueprint

import db
import errors
import helpers
import response
import serializers
from middleware import auth_required


bp = Blueprint("lawyers", __name__)


VALID_LAWYER_ROLES = {"JUNIOR", "SENIOR", "PARTNER"}


@bp.route("/lawyers", methods=["POST"])
@auth_required("PartnerLawyer")
def create_lawyer():
    body = helpers.get_json_body()
    full_name = helpers.require_str(body, "full_name", min_len=1, max_len=120)
    bar_number = helpers.require_str(body, "bar_number", min_len=1)
    role = helpers.require_enum(body, "role", VALID_LAWYER_ROLES)
    hourly_rate_cents = helpers.require_int(body, "hourly_rate_cents", min_val=0)
    client_history = body.get("client_history", []) or []
    if not isinstance(client_history, list):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "client_history must be an array.")
    for h in client_history:
        if not isinstance(h, str):
            errors.raise_error(errors.ERR_VALIDATION_FAILED, "client_history entries must be strings.")

    # Bar number uniqueness
    for lw in db.lawyers.values():
        if lw["bar_number"] == bar_number:
            errors.raise_error(errors.ERR_VALIDATION_FAILED, "bar_number must be unique.")

    lid = db.new_id()
    common = helpers.common_create()
    lawyer = {
        "id": lid,
        "full_name": full_name,
        "bar_number": bar_number,
        "role": role,
        "hourly_rate_cents": int(hourly_rate_cents),
        "status": "ACTIVE",
        "client_history": list(client_history),
        **common,
    }
    db.lawyers[lid] = lawyer
    return response.created(serializers.lawyer_dict(lawyer))


@bp.route("/lawyers/<lid>", methods=["GET"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer", "IntakeClerk")
def read_lawyer(lid):
    lw = db.lawyers.get(lid)
    if lw is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Lawyer {lid} not found.")
    return response.ok(serializers.lawyer_dict(lw))
