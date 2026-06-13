"""Branch endpoints (PRD §3.1)."""

from flask import Blueprint

import db
import response
from middleware import authenticate, require_roles, ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER
from services import serialize
from routes import helpers

bp = Blueprint("branches", __name__)


@bp.post("/library/branches")
def create_branch():
    caller = authenticate()
    require_roles(caller, {ROLE_MANAGER})
    body = helpers.get_json_body()

    helpers.require_fields(body, ["name"])
    name = helpers.require_string(body, "name")

    record = {
        "name": name,
        "fine_free": helpers.optional_bool(body, "fine_free", False),
        "daily_fine_cents": helpers.optional_int(body, "daily_fine_cents", 25),
        "max_fine_cents": helpers.optional_int(body, "max_fine_cents", 1000),
        "grace_days": helpers.optional_int(body, "grace_days", 1),
        "loan_period_days": helpers.optional_int(body, "loan_period_days", 21),
        "block_threshold_cents": helpers.optional_int(body, "block_threshold_cents", 1000),
        "reservation_buffer_minutes": helpers.optional_int(body, "reservation_buffer_minutes", 15),
    }
    db.stamp_create(record)
    db.branches[record["id"]] = record
    return response.object_response(serialize.branch(record), status=201)


@bp.get("/library/branches/<bid>")
def get_branch(bid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    record = helpers.find_or_404(db.branches, bid)
    return response.object_response(serialize.branch(record))


@bp.get("/library/branches")
def list_branches():
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    records = list(db.branches.values())
    return helpers.list_response(records, serialize.branch)
