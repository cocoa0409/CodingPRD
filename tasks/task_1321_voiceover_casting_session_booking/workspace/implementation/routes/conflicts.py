"""ConflictExclusion endpoints: fetch and manual release."""
from flask import Blueprint

import errors
from db import DB
from middleware import auth
from response import ok
from services import conflict_json, lazy_read_tick, touch

bp = Blueprint("conflicts", __name__)


@bp.get("/conflict_exclusions/<cid>")
def get_conflict(cid):
    auth(["CastingDirector", "Client", "Talent", "Agent"])
    lazy_read_tick()
    rec = DB["conflict_exclusions"].get(cid)
    if rec is None:
        raise errors.not_found("Conflict exclusion not found")
    return ok(conflict_json(rec))


@bp.post("/conflict_exclusions/<cid>/release")
def release_conflict(cid):
    auth(["CastingDirector"])
    rec = DB["conflict_exclusions"].get(cid)
    if rec is None:
        raise errors.not_found("Conflict exclusion not found")
    if rec["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE exclusion can be released")
    rec["status"] = "RELEASED"
    touch(rec)
    return ok(conflict_json(rec))
