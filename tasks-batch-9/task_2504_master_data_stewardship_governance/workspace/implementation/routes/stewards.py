"""Steward identity registry (PRD 3.1)."""

from flask import Blueprint

import db
import response
import validation as v
from auth import endpoint
from errors import fail

bp = Blueprint("stewards", __name__)

LEVELS = ("JUNIOR", "SENIOR", "PRINCIPAL")
READERS = ("GovernanceAdmin", "DataOwner", "DataSteward", "Auditor")


@bp.post("/mdm/stewards")
@endpoint("GovernanceAdmin")
def create_steward():
    body = v.body()
    full_name = v.req_str(body, "full_name", 1)
    email = v.req_str(body, "email", 1)
    level = v.req_enum(body, "certification_level", LEVELS)

    for existing in db.store.stewards.values():
        if existing["email"] == email:
            fail("ERR_DUPLICATE_STEWARD_EMAIL", "A steward with this email already exists.")

    steward = db.create("Steward", {
        "full_name": full_name,
        "email": email,
        "certification_level": level,
        "open_finding_load": 0,
    })
    db.store.stewards[steward["id"]] = steward
    return response.created(steward)


@bp.get("/mdm/stewards")
@endpoint(*READERS)
def list_stewards():
    limit, offset = v.pagination()
    level = v.enum_filter("certification_level", LEVELS)
    rows = db.ordered(db.store.stewards)
    if level is not None:
        rows = [r for r in rows if r["certification_level"] == level]
    return response.collection(rows, limit, offset)


@bp.get("/mdm/stewards/<steward_id>")
@endpoint(*READERS)
def read_steward(steward_id):
    steward = db.resolve(db.store.stewards, steward_id, "ERR_STEWARD_NOT_FOUND")
    return response.entity(steward)
