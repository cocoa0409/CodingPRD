"""Claimant endpoints."""
from decimal import Decimal

from flask import Blueprint

import db
import derive
import middleware
import response
import serialize
import validate
from routes import common

bp = Blueprint("claimants", __name__)

ENTITY_TYPES = ("INDIVIDUAL", "IRRIGATION_DISTRICT", "MUNICIPALITY", "TRIBE")
STANDING_STATUSES = ("IN_GOOD_STANDING", "DELINQUENT", "BARRED")


@bp.route("/claimants", methods=["POST"])
def create_claimant():
    middleware.authenticate((middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR))
    body = validate.get_body()
    legal_name = validate.req_str(body, "legal_name", min_len=1, max_len=160)
    contact_email = validate.req_str(body, "contact_email", min_len=1, max_len=254)
    if "@" not in contact_email:
        validate.invalid("Field 'contact_email' must contain '@'.")
    entity_type = validate.req_enum(body, "entity_type", ENTITY_TYPES)

    row = db.base_row()
    row.update({
        "legal_name": legal_name,
        "contact_email": contact_email,
        "entity_type": entity_type,
        "standing_status": "IN_GOOD_STANDING",
        "outstanding_fee_balance_usd": Decimal("0.00"),
        "open_application_count": 0,
    })
    db.claimants[row["id"]] = row
    return response.object_response(serialize.claimant(row), 201)


@bp.route("/claimants/<cid>", methods=["GET"])
def get_claimant(cid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    row = common.get_claimant(cid)
    middleware.require_owner(caller, row["id"])
    return response.object_response(serialize.claimant(row))


@bp.route("/claimants/<cid>/standing", methods=["PATCH"])
def set_standing(cid):
    middleware.authenticate((middleware.ROLE_ADJUDICATOR,))
    row = common.get_claimant(cid)
    body = validate.get_body()
    standing = validate.req_enum(body, "standing_status", STANDING_STATUSES)

    row["standing_status"] = standing
    derive.recompute_claimant(row)
    db.touch(row)
    derive.repost_claimant_accounts(row)
    return response.object_response(serialize.claimant(row))
