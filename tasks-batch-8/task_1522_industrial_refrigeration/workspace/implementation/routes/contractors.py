"""Contractor qualification lifecycle (PRD 3.7)."""
from flask import Blueprint

import envelope
from errors import ApiError
from guards import (
    ALL_ROLES,
    endpoint,
    path_row,
    req_instant,
    req_int,
    req_string,
)
from serialize import contractor_out
from store import db, touch

bp = Blueprint("contractors", __name__)

CREATE_SCHEMA = (
    frozenset(["company_name", "safety_score"]),
    frozenset(["company_name", "safety_score"]),
)
QUALIFY_SCHEMA = (frozenset(["qualified_until"]), frozenset(["qualified_until"]))
EMPTY_SCHEMA = (frozenset(), frozenset())


@bp.post("/psm/contractors")
@endpoint(["MaintenanceLead"], schema=CREATE_SCHEMA)
def create_contractor(ctx):
    company = req_string(ctx.body, "company_name")
    score = req_int(ctx.body, "safety_score", minimum=0, maximum=100)
    row = db.create(
        "contractors",
        {
            "company_name": company,
            "safety_score": score,
            "qualification_status": "PENDING",
            "qualified_until": None,
        },
    )
    return envelope.created(contractor_out(row))


@bp.get("/psm/contractors/<contractor_id>")
@endpoint(ALL_ROLES)
def get_contractor(ctx, contractor_id):
    return envelope.ok(contractor_out(path_row("contractors", contractor_id)))


@bp.post("/psm/contractors/<contractor_id>/qualify")
@endpoint(["MaintenanceLead"], schema=QUALIFY_SCHEMA)
def qualify(ctx, contractor_id):
    qualified_until = req_instant(ctx.body, "qualified_until")
    contractor = path_row("contractors", contractor_id)
    # step 5 -- PENDING or EXPIRED only
    if contractor["qualification_status"] not in ("PENDING", "EXPIRED"):
        raise ApiError("ERR_INVALID_STATE")
    # step 7 -- the expiry must lie in the future of the logical clock
    if qualified_until <= db.now():
        raise ApiError("ERR_INVALID_WINDOW")
    contractor["qualification_status"] = "QUALIFIED"
    contractor["qualified_until"] = qualified_until
    touch(contractor)
    return envelope.ok(contractor_out(contractor))


@bp.post("/psm/contractors/<contractor_id>/suspend")
@endpoint(["MaintenanceLead"], schema=EMPTY_SCHEMA)
def suspend(ctx, contractor_id):
    contractor = path_row("contractors", contractor_id)
    if contractor["qualification_status"] != "QUALIFIED":
        raise ApiError("ERR_INVALID_STATE")
    contractor["qualification_status"] = "SUSPENDED"
    touch(contractor)
    return envelope.ok(contractor_out(contractor))


@bp.post("/psm/contractors/<contractor_id>/reinstate")
@endpoint(["MaintenanceLead"], schema=EMPTY_SCHEMA)
def reinstate(ctx, contractor_id):
    contractor = path_row("contractors", contractor_id)
    if contractor["qualification_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE")
    # the recorded expiry must still lie in the future
    qualified_until = contractor["qualified_until"]
    if qualified_until is None or qualified_until <= db.now():
        raise ApiError("ERR_INVALID_WINDOW")
    contractor["qualification_status"] = "QUALIFIED"
    touch(contractor)
    return envelope.ok(contractor_out(contractor))
