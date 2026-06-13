"""Copy endpoints (PRD §3.2). Copy status is system-driven; no direct status edit."""

from flask import Blueprint, request

import db
import errors
import response
from middleware import authenticate, require_roles, ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER
from services import serialize, derive
from routes import helpers
from timeutil import parse

bp = Blueprint("copies", __name__)


@bp.post("/library/copies")
def create_copy():
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN, ROLE_MANAGER})
    body = helpers.get_json_body()

    helpers.require_fields(body, ["title_id", "branch_id", "barcode", "acquired_on"])
    title_id = helpers.require_string(body, "title_id")
    branch_id = helpers.require_string(body, "branch_id")
    barcode = helpers.require_string(body, "barcode")

    # existence (priority 3), left-to-right: title then branch
    title = helpers.find_or_404(db.titles, title_id)
    helpers.find_or_404(db.branches, branch_id)

    # acquired_on must be a valid datetime
    try:
        acquired_on = parse(body["acquired_on"])
    except (ValueError, TypeError):
        raise errors.invalid_request("acquired_on must be an ISO 8601 datetime.")

    condition_factor = helpers.optional_number(body, "condition_factor", 1.0)
    if condition_factor < 0.0 or condition_factor > 1.0:
        raise errors.invalid_request("condition_factor must be between 0.0 and 1.0.")

    # business referential (priority 6): may not add a copy to a WITHDRAWN title
    if title["status"] == "WITHDRAWN":
        raise errors.ApiError(errors.ERR_TITLE_WITHDRAWN, 409, "Title is WITHDRAWN.")

    record = {
        "title_id": title_id,
        "branch_id": branch_id,
        "barcode": barcode,
        "status": "AVAILABLE",
        "acquired_on": acquired_on,
        "condition_factor": condition_factor,
    }
    db.stamp_create(record)
    db.copies[record["id"]] = record

    derive.reconcile_title(title)
    return response.object_response(serialize.copy(record), status=201)


@bp.get("/library/copies/<cid>")
def get_copy(cid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    record = helpers.find_or_404(db.copies, cid)
    return response.object_response(serialize.copy(record))


@bp.get("/library/copies")
def list_copies():
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    title_id = request.args.get("title_id")
    branch_id = request.args.get("branch_id")
    records = [
        c for c in db.copies.values()
        if (title_id is None or c["title_id"] == title_id)
        and (branch_id is None or c["branch_id"] == branch_id)
    ]
    return helpers.list_response(records, serialize.copy)
