"""Royalty participants and the pool-share recompute (PRD 3.6)."""

from flask import Blueprint

import db
import errors
import response
import validation as v
from db import ZERO4
from errors import fail
from middleware import (GENERAL_MANAGER, LEAD_PRODUCER, MANAGEMENT_ROLES, ctx,
                        endpoint, find_production, lookup)
from services import ledger

bp = Blueprint("royalty_participants", __name__)

PARTICIPANT_ROLES = ("AUTHOR", "COMPOSER", "DIRECTOR", "CHOREOGRAPHER",
                     "DESIGNER", "LEAD_PRODUCER", "STAR")
PARTICIPANT_STATUSES = ("ACTIVE", "TERMINATED")


def _find_participant(participant_id):
    return lookup("royalty_participants", participant_id,
                  errors.ERR_ROYALTY_PARTICIPANT_NOT_FOUND)


@bp.post("/royalty-participants")
@endpoint((GENERAL_MANAGER,))
def create_royalty_participant():
    data = v.body()
    production_id = v.req_id(data, "production_id")
    participant_name = v.req_str(data, "participant_name", 1, 200)
    role = v.req_enum(data, "role", PARTICIPANT_ROLES)
    fixed_gross_pct = v.req_pct(data, "fixed_gross_pct")
    pool_points = v.req_int(data, "pool_points", 0)
    min_guarantee = v.req_int(data, "min_guarantee_cents", 0)

    production = find_production(production_id)

    row = db.insert("royalty_participants", {
        "production_id": production_id,
        "participant_name": participant_name,
        "role": role,
        "fixed_gross_pct": fixed_gross_pct,
        "pool_points": pool_points,
        "min_guarantee_cents": min_guarantee,
        "pool_share_pct": ZERO4,
        "cumulative_royalty_cents": 0,
        "status": "ACTIVE",
    })
    ctx().created(row)
    ctx().force(production)
    ledger.royalty_pool_share_pct(ctx(), production)
    return response.obj(row, 201)


@bp.post("/royalty-participants/<participant_id>/terminate")
@endpoint((LEAD_PRODUCER,))
def terminate_royalty_participant(participant_id):
    participant = _find_participant(participant_id)
    production = db.get("productions", participant["production_id"])
    if participant["status"] != "ACTIVE":
        fail(errors.ERR_INVALID_PARTICIPANT_STATE,
             "Only an ACTIVE participation may be terminated.")

    ctx().force(production)
    ctx().watch(participant)
    participant["status"] = "TERMINATED"
    participant["pool_share_pct"] = ZERO4
    # Recompute drops the terminated points out of the total and re-splits.
    ledger.royalty_pool_share_pct(ctx(), production)
    return response.obj(participant)


@bp.post("/royalty-participants/<participant_id>/reinstate")
@endpoint((LEAD_PRODUCER,))
def reinstate_royalty_participant(participant_id):
    participant = _find_participant(participant_id)
    production = db.get("productions", participant["production_id"])
    if participant["status"] != "TERMINATED":
        fail(errors.ERR_INVALID_PARTICIPANT_STATE,
             "Only a TERMINATED participation may be reinstated.")

    ctx().force(production)
    ctx().watch(participant)
    participant["status"] = "ACTIVE"
    ledger.royalty_pool_share_pct(ctx(), production)
    return response.obj(participant)


@bp.get("/royalty-participants/<participant_id>")
@endpoint(MANAGEMENT_ROLES)
def read_royalty_participant(participant_id):
    return response.obj(_find_participant(participant_id))


@bp.get("/royalty-participants")
@endpoint(MANAGEMENT_ROLES)
def list_royalty_participants():
    production_id = v.q_str("production_id")
    status = v.q_enum("status", PARTICIPANT_STATUSES)
    role = v.q_enum("role", PARTICIPANT_ROLES)
    limit, offset = v.pagination()
    rows = [r for r in db.all_rows("royalty_participants")
            if (production_id is None or r["production_id"] == production_id)
            and (status is None or r["status"] == status)
            and (role is None or r["role"] == role)]
    return response.listing(rows, limit, offset)
