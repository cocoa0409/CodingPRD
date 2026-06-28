"""Quote endpoints: get, send, accept (SCAFFOLD §1.5 / PRD §3.5)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, require_role
from response import success
from services import serialize
from services.common import get_body, touch

bp = Blueprint("quotes", __name__)


@bp.route("/quotes/<id>", methods=["GET"])
def get_quote(id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "SalesRep", "Scheduler", "Customer"})
    row = db.quotes.get(id)
    if row is None:
        raise err("ERR_NOT_FOUND", "Quote not found")
    return success(serialize.quote(row), 200)


@bp.route("/quotes/<id>/send", methods=["POST"])
def send_quote(id):
    _, role = authenticate()
    require_role(role, {"SalesRep"})
    quote = db.quotes.get(id)
    if quote is None:
        raise err("ERR_NOT_FOUND", "Quote not found")
    project = db.projects.get(quote["project_id"])

    # state guard: only DRAFT quotes can be sent
    if quote["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT quote can be sent")

    first_send = (project["sales_status"] == "ASSESSED")
    # First send requires sales track at ASSESSED with an APPROVED assessment.
    # Subsequent sends (project already QUOTED) are permitted; any other sales
    # state has no DRAFT quote path defined.
    if project["sales_status"] not in ("ASSESSED", "QUOTED"):
        raise err("ERR_INVALID_STATE", "Project not in a sendable sales state")
    if first_send:
        has_approved = any(a["project_id"] == project["id"] and a["status"] == "APPROVED"
                           for a in db.assessments.values())
        if not has_approved:
            raise err("ERR_INVALID_STATE", "No APPROVED assessment on the project")

    quote["status"] = "SENT"
    touch(quote)

    # first send advances sales track ASSESSED -> QUOTED
    if first_send:
        project["sales_status"] = "QUOTED"
    # every send increments project version (the offer set changed)
    touch(project)

    return success(serialize.quote(quote), 200)


@bp.route("/quotes/<id>/accept", methods=["POST"])
def accept_quote(id):
    user_id, role = authenticate()
    require_role(role, {"Customer"})
    quote = db.quotes.get(id)
    if quote is None:
        raise err("ERR_NOT_FOUND", "Quote not found")
    project = db.projects.get(quote["project_id"])

    # priority 3: ownership (X-User-ID == owning project's customer_id)
    if project["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customer does not own this project")

    body = get_body()

    # state guard (priority 8): project QUOTED + quote SENT
    if project["sales_status"] != "QUOTED" or quote["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Quote is not acceptable in the current state")

    # priority 20: OCC (expected_project_version required)
    expected = body.get("expected_project_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_VALIDATION", "expected_project_version is required")
    if expected != project["version"]:
        raise err("ERR_STALE_PROJECT_VERSION", "expected_project_version is stale")

    quote["status"] = "ACCEPTED"
    touch(quote)
    project["accepted_quote_id"] = quote["id"]
    project["sales_status"] = "ACCEPTED"

    # all other SENT/DRAFT quotes on the project -> SUPERSEDED
    for q in db.quotes.values():
        if q["project_id"] == project["id"] and q["id"] != quote["id"] \
                and q["status"] in ("DRAFT", "SENT"):
            q["status"] = "SUPERSEDED"
            touch(q)

    touch(project)
    return success(serialize.quote(quote), 200)
