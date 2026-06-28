"""Quote endpoints (PRD §3.2, §2.6)."""
from flask import Blueprint

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize
from services.quote_builder import build_quote

bp = Blueprint("quotes", __name__)


@bp.route("/quotes", methods=["POST"])
def create_quote():
    require_roles({"SalesDesigner"})
    body = common.get_json()

    project_id = common.require_field(body, "project_id", expected_types=["string"])
    project = common.get_project(project_id)

    # state: DESIGNED -> QUOTED (priority 5)
    if project["status"] != "DESIGNED":
        raise errors.invalid_state("Project must be DESIGNED to issue a quote.")

    quote = build_quote(project, variant="ESTIMATE")
    project["status"] = "QUOTED"
    common.touch(project)
    return response.success(serialize.quote(quote), status=201)


@bp.route("/quotes/<qid>", methods=["GET"])
def get_quote(qid):
    require_roles({"SalesDesigner", "Homeowner"})
    quote = common.get_quote(qid)
    return response.success(serialize.quote(quote), status=200)


@bp.route("/quotes/<qid>/financing-applications", methods=["GET"])
def list_financing(qid):
    require_roles({"SalesDesigner", "Homeowner"})
    limit, offset = common.parse_pagination()
    common.get_quote(qid)  # existence (priority 4)
    items = [f for f in db.financing_applications.values() if f["quote_id"] == qid]
    page, total = common.paginate(items, limit, offset)
    return response.array([serialize.financing(f) for f in page], limit, offset, total)


@bp.route("/quotes/<qid>/accept", methods=["POST"])
def accept_quote(qid):
    user_id, role = require_roles({"Homeowner"})
    body = common.get_json()

    # existence (priority 4) — resolve before consuming the OCC field so a missing
    # quote yields ERR_NOT_FOUND ahead of any well-formedness error.
    quote = common.get_quote(qid)
    project = common.get_project(quote["project_id"])

    # ownership (priority 3 — applied after existence resolution per §2.7 precedence
    # but only meaningful once the owning project is known)
    if project["homeowner_id"] != user_id:
        raise errors.not_resource_owner("You do not own this project.")

    # state (priority 5): quote ISSUED and project QUOTED
    if quote["status"] != "ISSUED":
        raise errors.invalid_state("Quote must be ISSUED to accept.")
    if project["status"] != "QUOTED":
        raise errors.invalid_state("Project must be QUOTED to accept a quote.")

    # OCC (priority 6): the required expected_project_version is consumed here.
    expected_version = common.require_field(
        body, "expected_project_version", expected_types=["integer"])
    if expected_version != project["version"]:
        raise errors.stale_project_version(
            "expected_project_version does not match current Project.version.")

    quote["status"] = "ACCEPTED"
    common.touch(quote)
    # supersede every OTHER ISSUED quote on this project
    for q in db.quotes.values():
        if q["project_id"] == project["id"] and q["id"] != qid and q["status"] == "ISSUED":
            q["status"] = "SUPERSEDED"
            common.touch(q)
    project["accepted_quote_id"] = quote["id"]
    project["status"] = "PERMITTING"
    common.touch(project)
    return response.success(serialize.quote(quote), status=200)


@bp.route("/quotes/<qid>/reject", methods=["POST"])
def reject_quote(qid):
    user_id, role = require_roles({"Homeowner"})
    common.get_json()
    quote = common.get_quote(qid)
    project = common.get_project(quote["project_id"])

    # ownership (priority 3)
    if project["homeowner_id"] != user_id:
        raise errors.not_resource_owner("You do not own this project.")

    # state (priority 5)
    if quote["status"] != "ISSUED":
        raise errors.invalid_state("Quote must be ISSUED to reject.")

    quote["status"] = "REJECTED"
    common.touch(quote)
    return response.success(serialize.quote(quote), status=200)
