"""Investors and the accreditation determination (PRD 3.3)."""

from flask import Blueprint

import db
import response
import validation as v
from middleware import (ALL_ROLES, SYNDICATION_COUNSEL, ctx, endpoint,
                        find_investor, require_owner)

bp = Blueprint("investors", __name__)

DETERMINATIONS = ("ACCREDITED", "NON_ACCREDITED")


@bp.post("/investors")
@endpoint((SYNDICATION_COUNSEL,))
def create_investor():
    data = v.body()
    row = db.insert("investors", {
        "legal_name": v.req_str(data, "legal_name", 1, 200),
        "jurisdiction": v.req_str(data, "jurisdiction", 2, 2),
        "contact_email": v.req_str(data, "contact_email"),
        "accreditation_status": "UNVERIFIED",
    })
    return response.obj(row, 201)


@bp.post("/investors/<investor_id>/accredit")
@endpoint((SYNDICATION_COUNSEL,))
def accredit_investor(investor_id):
    investor = find_investor(investor_id)
    data = v.body()
    determination = v.req_enum(data, "accreditation_status", DETERMINATIONS)
    ctx().force(investor)
    investor["accreditation_status"] = determination
    return response.obj(investor)


@bp.get("/investors/<investor_id>")
@endpoint(ALL_ROLES)
def read_investor(investor_id):
    investor = find_investor(investor_id)
    require_owner(investor["id"])
    return response.obj(investor)
