"""Donor endpoints (PRD 3.4)."""
from flask import Blueprint

import config
import db
import response
import validators as v
from auth import authorize
from db import store
from services import domain

bp = Blueprint("donors", __name__)


@bp.post("/api/donors")
def create_donor():
    authorize(
        [
            config.ROLE_ANONYMOUS,
            config.ROLE_PLATFORM_ADMIN,
            config.ROLE_CAMPAIGN_MANAGER,
        ]
    )
    body = v.get_body()
    display_name = v.req_str(body, "display_name")
    email = v.req_str(body, "email")
    is_anonymous = v.opt_bool(body, "is_anonymous", default=False)
    rec = db.new_record(
        display_name=display_name, email=email, is_anonymous=is_anonymous
    )
    store.donors[rec["id"]] = rec
    return response.object_response(domain.ser_donor(rec), 201)


@bp.get("/api/donors/<donor_id>")
def read_donor(donor_id):
    user_id, role = authorize(
        [
            config.ROLE_PLATFORM_ADMIN,
            config.ROLE_CAMPAIGN_MANAGER,
            config.ROLE_DONOR,
        ]
    )
    rec = domain.get_donor(donor_id)
    if role == config.ROLE_DONOR:
        domain.require_donor_is(user_id, rec["id"])
    return response.object_response(domain.ser_donor(rec))
