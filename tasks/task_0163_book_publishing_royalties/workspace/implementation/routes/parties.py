"""Authors and Agents (PRD §3.1)."""
from flask import Blueprint, request

import db
import errors
from middleware import get_principal, require_publisher, serialize
from response import object_response, array_response
from services import validate
from services.access import assert_read_author, assert_read_agent
from services.listing import paginate

bp = Blueprint("parties", __name__)


# ---- Authors ----

@bp.route("/authors", methods=["POST"])
def create_author():
    role, _ = get_principal()
    require_publisher(role)
    body = validate.get_body()
    full_name = validate.req_string(body, "full_name")
    email = validate.req_string(body, "email")
    tax = validate.opt_number(body, "tax_withholding_pct", 0)
    validate.range_pct_closed(tax, "tax_withholding_pct")
    # Uniqueness (priority 5).
    for a in db.authors.values():
        if a["email"] == email:
            raise errors.duplicate_email("Author email already exists.")
    rec = db.make_common({
        "full_name": full_name,
        "email": email,
        "tax_withholding_pct": tax,
    })
    db.authors[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/authors/<aid>", methods=["GET"])
def get_author(aid):
    role, user_id = get_principal()
    author = db.authors.get(aid)
    if author is None:
        raise errors.not_found("Author not found.")
    assert_read_author(role, user_id, author)
    return object_response(serialize(author))


@bp.route("/authors", methods=["GET"])
def list_authors():
    role, _ = get_principal()
    require_publisher(role)
    limit, offset = validate.pagination()
    email = request.args.get("email")
    records = list(db.authors.values())
    if email is not None:
        records = [a for a in records if a["email"] == email]
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


# ---- Agents ----

@bp.route("/agents", methods=["POST"])
def create_agent():
    role, _ = get_principal()
    require_publisher(role)
    body = validate.get_body()
    agency_name = validate.req_string(body, "agency_name")
    email = validate.req_string(body, "email")
    for a in db.agents.values():
        if a["email"] == email:
            raise errors.duplicate_email("Agent email already exists.")
    rec = db.make_common({
        "agency_name": agency_name,
        "email": email,
    })
    db.agents[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/agents/<aid>", methods=["GET"])
def get_agent(aid):
    role, user_id = get_principal()
    agent = db.agents.get(aid)
    if agent is None:
        raise errors.not_found("Agent not found.")
    assert_read_agent(role, user_id, agent)
    return object_response(serialize(agent))


@bp.route("/agents", methods=["GET"])
def list_agents():
    role, _ = get_principal()
    require_publisher(role)
    limit, offset = validate.pagination()
    email = request.args.get("email")
    records = list(db.agents.values())
    if email is not None:
        records = [a for a in records if a["email"] == email]
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)
