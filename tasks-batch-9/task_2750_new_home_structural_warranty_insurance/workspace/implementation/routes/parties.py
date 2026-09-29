"""Home buyers and the panel of neutrals (PRD 3.3, 3.9)."""

from flask import Blueprint

import calc
import db
import listing
import response
import store
import validators as v
from errors import err, invalid
from middleware import (ROLE_ADJUSTER, ROLE_BUILDER, ROLE_COMPLIANCE,
                        ROLE_HOMEOWNER, ROLE_UNDERWRITER, endpoint)

bp = Blueprint("parties", __name__)


@bp.post("/homeowners")
@endpoint(ROLE_UNDERWRITER, ROLE_BUILDER)
def create_homeowner(user_id, role):
    body = v.body()
    row = {
        "full_name": v.req_str(body, "full_name", 1, 120),
        "email": v.req_str(body, "email"),
        "state_code": v.req_enum(body, "state_code", calc.STATE_CODES),
    }
    if "@" not in row["email"]:
        raise invalid("field 'email' must contain an at-sign")
    db.stamp_create(row, versioned=False)
    db.homeowners[row["id"]] = row
    return response.object_response(db.public(row), 201)


@bp.get("/homeowners/<homeowner_id>")
@endpoint(ROLE_UNDERWRITER, ROLE_COMPLIANCE, ROLE_ADJUSTER, ROLE_HOMEOWNER)
def read_homeowner(homeowner_id, user_id, role):
    return response.object_response(db.public(store.get_homeowner(homeowner_id)))


@bp.post("/neutrals")
@endpoint(ROLE_COMPLIANCE)
def create_neutral(user_id, role):
    body = v.body()
    row = {
        "full_name": v.req_str(body, "full_name", 1, 120),
        "credential": v.req_enum(body, "credential", calc.CREDENTIALS),
        "state_code": v.req_enum(body, "state_code", calc.STATE_CODES),
        "status": "ACTIVE",
        "booked_session_count": 0,
    }
    db.stamp_create(row)
    db.neutrals[row["id"]] = row
    return response.object_response(db.public(row), 201)


@bp.post("/neutrals/<neutral_id>/deactivation")
@endpoint(ROLE_COMPLIANCE)
def deactivate_neutral(neutral_id, user_id, role):
    neutral = store.get_neutral(neutral_id)
    v.req_str(v.body(), "reason")
    if neutral["status"] != "ACTIVE":
        raise err("ERR_INVALID_NEUTRAL_STATE",
                  "neutral is already in status '%s'" % neutral["status"])
    neutral["status"] = "INACTIVE"
    db.mark(neutral)
    return response.object_response(db.public(neutral))


@bp.get("/neutrals/<neutral_id>")
@endpoint(ROLE_UNDERWRITER, ROLE_COMPLIANCE, ROLE_ADJUSTER, ROLE_HOMEOWNER)
def read_neutral(neutral_id, user_id, role):
    return response.object_response(db.public(store.get_neutral(neutral_id)))


@bp.get("/neutrals")
@endpoint(ROLE_COMPLIANCE, ROLE_ADJUSTER, ROLE_HOMEOWNER)
def list_neutrals(user_id, role):
    rows = store.all_rows(db.neutrals)
    rows = listing.eq_filter(rows, "credential")
    rows = listing.eq_filter(rows, "status")
    rows = listing.eq_filter(rows, "state_code")
    return response.paginate(rows)
